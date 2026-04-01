"""
MQTT Sensor Data Logger — Saves sensor/telemetry data from each assembly line
to SEPARATE CSV files for analysis.

Each line gets its OWN dedicated folder and files:
    data/run_003/line1/telemetry.csv
    data/run_003/line1/faults.csv
    data/run_003/line1/production.csv
    data/run_003/line1/status.csv
    data/run_003/line2/telemetry.csv
    data/run_003/line2/faults.csv
    data/run_003/line2/production.csv
    data/run_003/line2/status.csv
    data/run_003/summary.csv              (cross-line, shared)

USAGE:
    python tests/mqtt_data_logger.py                            # Default
    python tests/mqtt_data_logger.py --output ./data/run_001    # Custom dir
    python tests/mqtt_data_logger.py --duration 3600            # 1 hour
    python tests/mqtt_data_logger.py --interval 0.3             # Fast sample

PREREQUISITES:
    1. Mosquitto (MQTT broker) must be running on localhost:1883
    2. Start this script BEFORE run_twin.py

STARTUP ORDER:
    Terminal 1:  mosquitto -v
    Terminal 2:  python tests/mqtt_data_logger.py --output ./data/run_003
    Terminal 3:  python run_twin.py
"""

import os
import sys
import csv
import json
import time
import signal
import logging
import argparse
import threading
from pathlib import Path
from datetime import datetime, timezone
from collections import OrderedDict

# ── Fix Python path so imports work from tests/ directory ──
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ── Logging setup ──
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("DataLogger")


# ═══════════════════════════════════════════════════════════════════════════
# CSV COLUMN DEFINITIONS
# ═══════════════════════════════════════════════════════════════════════════

TELEMETRY_COLUMNS = [
    "timestamp",
    "local_time",
    "line",
    "station",
    "state",

    # Production counters
    "products_completed",
    "products_passed",
    "products_failed",
    "products_good",
    "products_rejected",
    "products_stored",
    "store_errors",

    # QC / Sorting rates
    "pass_rate",
    "good_rate",

    # QC specific
    "last_qc_result",
    "last_vision_value",
    "last_vision_item",
    "expected_value",

    # Sorting specific
    "last_sort_result",

    # Machining specific
    "machining_progress",

    # Warehouse specific
    "fill_percent",
    "next_cell",
    "cells_occupied",
    "max_cells",

    # Pick & Place
    "pp_phase",
    "pp_has_item",

    # Positioning bar
    "bar_clamped",
    "bar_at_limit",

    # Simulation values
    "temperature",
    "vibration",
    "power_consumption",
    "motor_runtime",
    "belt_distance",

    # Digital I/O states
    "belt_on",
    "blade_up",
    "emitter_on",
    "sensor_entry",
    "sensor_station",
    "gripper_on",

    # Emergency
    "emergency_active",

    # Fault state
    "fault_active",
    "active_faults",
    "fault_count",

    # Fault effect counters
    "belt_stutters",
    "brownouts",
    "sensor_misreads",
    "vision_errors",
    "sorter_jams",
    "misroutes",
    "gripper_failures",
    "pp_jams",
    "positioner_jams",
    "cnc_jams",
    "material_errors",
    "crane_drifts",
    "fork_jams",
    "grab_failures",
    "move_delays",
    "inspect_delays",
    "arm_delays",
    "blade_chatters",
    "emergency_stops",
    "timing_delays",
]

FAULT_EVENT_COLUMNS = [
    "timestamp",
    "local_time",
    "line",
    "station",
    "fault_type",
    "severity",
    "action",
    "real_cause",
    "effect_description",
    "mtbf_hours",
]

PRODUCTION_COLUMNS = [
    "timestamp",
    "local_time",
    "line",
    "station",
    "event",
    "product_number",
    "cycle_time",
    "result",
    "pass_rate",
    "good_rate",
    "vision_value",
    "sort_result",
]

STATUS_COLUMNS = [
    "timestamp",
    "local_time",
    "line",
    "station",
    "state",
    "products_completed",
    "fault_active",
    "active_faults",
    "emergency_active",
]

SUMMARY_COLUMNS = [
    "timestamp",
    "local_time",
    "line1_total_produced",
    "line1_active_faults",
    "line1_station_states",
    "line2_total_produced",
    "line2_active_faults",
    "line2_station_states",
]


# ═══════════════════════════════════════════════════════════════════════════
# CSV WRITER (Thread-Safe, Buffered)
# ═══════════════════════════════════════════════════════════════════════════

class CSVWriter:
    """Thread-safe CSV writer with buffered writes."""

    def __init__(self, filepath, columns, flush_rows=50, flush_interval=5.0):
        self.filepath = Path(filepath)
        self.columns = columns
        self.flush_rows = flush_rows
        self.flush_interval = flush_interval

        self._lock = threading.Lock()
        self._buffer = []
        self._last_flush = time.time()
        self._total_rows = 0
        self._file = None
        self._writer = None

        self.filepath.parent.mkdir(parents=True, exist_ok=True)

        self._file = open(self.filepath, "w", newline="", encoding="utf-8")
        self._writer = csv.DictWriter(
            self._file, fieldnames=columns, extrasaction="ignore"
        )
        self._writer.writeheader()
        self._file.flush()

        logger.info(f"  📄 {self.filepath.relative_to(self.filepath.parents[2])} "
                    f"({len(columns)} columns)")

    def write_row(self, data: dict):
        with self._lock:
            row = OrderedDict()
            for col in self.columns:
                row[col] = data.get(col, "")
            self._buffer.append(row)
            self._total_rows += 1

            now = time.time()
            if (len(self._buffer) >= self.flush_rows or
                    now - self._last_flush >= self.flush_interval):
                self._flush_buffer()

    def _flush_buffer(self):
        if not self._buffer:
            return
        try:
            self._writer.writerows(self._buffer)
            self._file.flush()
            self._buffer.clear()
            self._last_flush = time.time()
        except Exception as e:
            logger.error(f"  ❌ CSV write error: {e}")

    def flush(self):
        with self._lock:
            self._flush_buffer()

    def close(self):
        self.flush()
        if self._file:
            self._file.close()
        logger.info(f"  ✅ Closed: {self.filepath.name} "
                    f"({self._total_rows} rows)")

    @property
    def total_rows(self):
        return self._total_rows


# ═══════════════════════════════════════════════════════════════════════════
# DATA EXTRACTORS
# ═══════════════════════════════════════════════════════════════════════════

def _safe_dict(payload, key):
    val = payload.get(key, {})
    return val if isinstance(val, dict) else {}


def extract_telemetry_row(line, station, payload):
    row = {
        "timestamp": payload.get("timestamp", datetime.utcnow().isoformat() + "Z"),
        "local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "line": line,
        "station": station,
        "state": payload.get("state", ""),
    }

    counters = _safe_dict(payload, "counters")
    for k in ["products_completed", "products_passed", "products_failed",
              "products_good", "products_rejected", "products_stored", "store_errors"]:
        row[k] = counters.get(k, "")

    qc = _safe_dict(payload, "qc")
    row["pass_rate"] = qc.get("pass_rate", "")
    row["last_qc_result"] = qc.get("last_result", "")
    row["last_vision_value"] = qc.get("last_vision", "")
    row["last_vision_item"] = qc.get("last_vision_item", "")
    row["expected_value"] = qc.get("expected_value", "")

    sorting = _safe_dict(payload, "sorting")
    row["good_rate"] = sorting.get("good_rate", "")
    row["last_sort_result"] = sorting.get("last_result", "")

    machining = _safe_dict(payload, "machining")
    row["machining_progress"] = machining.get("progress", "")

    warehouse = _safe_dict(payload, "warehouse")
    for k in ["fill_percent", "next_cell", "cells_occupied", "max_cells"]:
        row[k] = warehouse.get(k, "")

    pp = _safe_dict(payload, "pick_and_place")
    row["pp_phase"] = pp.get("phase", "")
    row["pp_has_item"] = pp.get("has_item", "")

    bar = _safe_dict(payload, "positioning_bar")
    row["bar_clamped"] = bar.get("clamped", "")
    row["bar_at_limit"] = bar.get("at_limit", "")

    sim = _safe_dict(payload, "simulation") or _safe_dict(payload, "sensors")
    row["temperature"] = sim.get("temperature", sim.get("motor_temperature", ""))
    row["vibration"] = sim.get("vibration", "")
    row["power_consumption"] = sim.get("power_consumption", "")
    row["motor_runtime"] = sim.get("motor_runtime", "")
    row["belt_distance"] = sim.get("belt_distance", "")

    io = _safe_dict(payload, "io_state") or _safe_dict(payload, "digital_io")
    row["belt_on"] = io.get("belt", io.get("belt1", ""))
    row["blade_up"] = io.get("stop_blade", io.get("blade", ""))
    row["emitter_on"] = io.get("emitter", "")
    row["sensor_entry"] = io.get("sensor_entry", "")
    row["sensor_station"] = io.get("sensor_station", "")
    row["gripper_on"] = io.get("gripper", io.get("pp_grab", ""))

    row["emergency_active"] = payload.get("emergency_active", "")

    faults = _safe_dict(payload, "faults")
    row["fault_active"] = faults.get("has_fault", False)
    active_list = faults.get("active", [])
    if isinstance(active_list, list):
        row["active_faults"] = "|".join(str(f) for f in active_list) if active_list else ""
        row["fault_count"] = len(active_list)
    else:
        row["active_faults"] = str(active_list) if active_list else ""
        row["fault_count"] = 1 if active_list else 0

    fc = _safe_dict(payload, "fault_counters") or _safe_dict(payload, "fault_effects")
    for key in [
        "belt_stutters", "brownouts", "sensor_misreads", "vision_errors",
        "sorter_jams", "misroutes", "gripper_failures", "pp_jams",
        "positioner_jams", "cnc_jams", "material_errors", "crane_drifts",
        "fork_jams", "grab_failures", "move_delays", "inspect_delays",
        "arm_delays", "blade_chatters", "emergency_stops", "timing_delays",
        "stutters",
    ]:
        csv_key = "belt_stutters" if key == "stutters" else key
        if key in fc:
            row[csv_key] = fc[key]

    return row


def extract_fault_event_row(line, station, payload, detail_payload=None):
    row = {
        "timestamp": payload.get("timestamp", datetime.utcnow().isoformat() + "Z"),
        "local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "line": line,
        "station": station,
        "fault_type": payload.get("fault_type", ""),
        "severity": payload.get("severity", ""),
        "action": payload.get("action", ""),
        "real_cause": "",
        "effect_description": "",
        "mtbf_hours": "",
    }
    if detail_payload and isinstance(detail_payload, dict):
        row["real_cause"] = detail_payload.get("real_cause", "")
        row["effect_description"] = detail_payload.get("effect_description", "")
        row["mtbf_hours"] = detail_payload.get("mtbf_hours", "")
    return row


def extract_production_row(line, payload):
    return {
        "timestamp": payload.get("timestamp", datetime.utcnow().isoformat() + "Z"),
        "local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "line": line,
        "station": payload.get("station", ""),
        "event": payload.get("event", "cycle_complete"),
        "product_number": payload.get("product_number", ""),
        "cycle_time": payload.get("cycle_time", ""),
        "result": payload.get("result", ""),
        "pass_rate": payload.get("pass_rate", ""),
        "good_rate": payload.get("good_rate", ""),
        "vision_value": payload.get("vision_value", ""),
        "sort_result": payload.get("sort_result", ""),
    }


def extract_summary_row(payload):
    l1 = _safe_dict(payload, "line1")
    l2 = _safe_dict(payload, "line2")
    return {
        "timestamp": payload.get("timestamp", datetime.utcnow().isoformat() + "Z"),
        "local_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
        "line1_total_produced": l1.get("total_produced", ""),
        "line1_active_faults": l1.get("active_faults", ""),
        "line1_station_states": json.dumps(l1.get("station_states", {})),
        "line2_total_produced": l2.get("total_produced", ""),
        "line2_active_faults": l2.get("active_faults", ""),
        "line2_station_states": json.dumps(l2.get("station_states", {})),
    }


# ═══════════════════════════════════════════════════════════════════════════
# PER-LINE CSV FILE SET
# ═══════════════════════════════════════════════════════════════════════════

class LineCSVSet:
    """
    Holds ALL CSV writers for a single line.

    Folder structure:
        output_dir/line1/telemetry.csv
        output_dir/line1/faults.csv
        output_dir/line1/production.csv
        output_dir/line1/status.csv
    """

    def __init__(self, output_dir, line_id, flush_rows=50, flush_interval=5.0):
        self.line_id = line_id
        self.line_dir = Path(output_dir) / line_id

        logger.info(f"")
        logger.info(f"  📂 Creating CSV files for {line_id.upper()}:")
        logger.info(f"     Folder: {self.line_dir.resolve()}")

        self.telemetry = CSVWriter(
            self.line_dir / "telemetry.csv",
            TELEMETRY_COLUMNS,
            flush_rows=flush_rows,
            flush_interval=flush_interval,
        )
        self.faults = CSVWriter(
            self.line_dir / "faults.csv",
            FAULT_EVENT_COLUMNS,
            flush_rows=10,
            flush_interval=3.0,
        )
        self.production = CSVWriter(
            self.line_dir / "production.csv",
            PRODUCTION_COLUMNS,
            flush_rows=10,
            flush_interval=3.0,
        )
        self.status = CSVWriter(
            self.line_dir / "status.csv",
            STATUS_COLUMNS,
            flush_rows=flush_rows,
            flush_interval=flush_interval,
        )

        self.all_writers = [
            self.telemetry,
            self.faults,
            self.production,
            self.status,
        ]

    def flush_all(self):
        for w in self.all_writers:
            w.flush()

    def close_all(self):
        for w in self.all_writers:
            w.close()


# ═══════════════════════════════════════════════════════════════════════════
# MQTT DATA LOGGER
# ═══════════════════════════════════════════════════════════════════════════

class MQTTDataLogger:
    """
    Subscribes to ALL factory MQTT topics and logs data to CSV files.

    SEPARATE files for each line:
        output_dir/line1/telemetry.csv
        output_dir/line1/faults.csv
        output_dir/line1/production.csv
        output_dir/line1/status.csv
        output_dir/line2/telemetry.csv
        output_dir/line2/faults.csv
        output_dir/line2/production.csv
        output_dir/line2/status.csv
        output_dir/summary.csv   (cross-line, shared)
    """

    def __init__(self, mqtt_client, output_dir="data",
                 min_interval=0.5, flush_rows=50, flush_interval=5.0):
        self.mqtt = mqtt_client
        self.output_dir = Path(output_dir)
        self.min_interval = min_interval
        self._running = True

        # Rate limiting per station
        self._last_write = {}
        self._lock = threading.Lock()

        # Statistics per line
        self._stats = {
            "messages_received": 0,
            "rows_written": 0,
            "messages_dropped": 0,
            "errors": 0,
            "line1_rows": 0,
            "line2_rows": 0,
        }

        # Pending fault details
        self._pending_details = {}

        # ── Create per-line CSV file sets ──
        self.line_csv = {
            "line1": LineCSVSet(
                self.output_dir, "line1",
                flush_rows=flush_rows,
                flush_interval=flush_interval,
            ),
            "line2": LineCSVSet(
                self.output_dir, "line2",
                flush_rows=flush_rows,
                flush_interval=flush_interval,
            ),
        }

        # ── Summary CSV (cross-line, shared) ──
        logger.info("")
        logger.info("  📂 Creating shared summary CSV:")
        self.summary_csv = CSVWriter(
            self.output_dir / "summary.csv",
            SUMMARY_COLUMNS,
            flush_rows=10,
            flush_interval=10.0,
        )

        # Flat list of all writers for easy iteration
        self._all_writers = []
        for line_set in self.line_csv.values():
            self._all_writers.extend(line_set.all_writers)
        self._all_writers.append(self.summary_csv)

        logger.info("")
        logger.info(f"  📁 Output root: {self.output_dir.resolve()}")
        logger.info(f"  ⏱️  Min write interval: {self.min_interval}s per station")
        logger.info(f"  📄 Total CSV files: {len(self._all_writers)} "
                    f"(4 per line + 1 summary)")

    def _should_write(self, line, station):
        key = (line, station)
        now = time.time()
        with self._lock:
            last = self._last_write.get(key, 0)
            if now - last < self.min_interval:
                self._stats["messages_dropped"] += 1
                return False
            self._last_write[key] = now
            return True

    def _ensure_dict(self, payload):
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                return json.loads(payload)
            except json.JSONDecodeError:
                return {}
        if isinstance(payload, bytes):
            try:
                return json.loads(payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                return {}
        return {}

    def _get_line_csv(self, line):
        """Get the LineCSVSet for a given line, or None if unknown."""
        return self.line_csv.get(line)

    def subscribe_all(self):
        topics_handlers = {
            "factory/line1/+/status": self._on_status,
            "factory/line2/+/status": self._on_status,
            "factory/line1/+/faults/event": self._on_fault_event,
            "factory/line2/+/faults/event": self._on_fault_event,
            "factory/line1/+/faults/detail": self._on_fault_detail,
            "factory/line2/+/faults/detail": self._on_fault_detail,
            "factory/line1/production": self._on_production,
            "factory/line2/production": self._on_production,
            "factory/twin/summary": self._on_summary,
            "factory/twin/final_report": self._on_summary,
        }

        logger.info("")
        for topic, handler in topics_handlers.items():
            try:
                self.mqtt.subscribe(topic, handler)
                logger.info(f"  📡 Subscribed: {topic}")
            except Exception as e:
                logger.error(f"  ❌ Subscribe failed for {topic}: {e}")

        logger.info(f"  ✅ Subscribed to {len(topics_handlers)} topic patterns")

    # ══════════════════════════════════════════════════════════════════════
    # MQTT HANDLERS — callback(topic: str, payload: dict|str)
    # ══════════════════════════════════════════════════════════════════════

    def _on_status(self, topic, payload):
        if not self._running:
            return
        self._stats["messages_received"] += 1

        try:
            payload = self._ensure_dict(payload)
            if not payload:
                return

            parts = topic.split("/")
            line = parts[1]       # "line1" or "line2"
            station = parts[2]    # "stn1", "mc_a", etc.

            line_csv = self._get_line_csv(line)
            if not line_csv:
                return

            if not self._should_write(line, station):
                return

            # Write to this line's telemetry CSV
            row = extract_telemetry_row(line, station, payload)
            line_csv.telemetry.write_row(row)

            # Write to this line's status CSV
            status_row = {
                "timestamp": row["timestamp"],
                "local_time": row["local_time"],
                "line": line,
                "station": station,
                "state": row["state"],
                "products_completed": (
                    row.get("products_completed") or
                    row.get("products_stored") or ""
                ),
                "fault_active": row["fault_active"],
                "active_faults": row["active_faults"],
                "emergency_active": row["emergency_active"],
            }
            line_csv.status.write_row(status_row)

            self._stats["rows_written"] += 2
            self._stats[f"{line}_rows"] += 2

        except Exception as e:
            self._stats["errors"] += 1
            logger.debug(f"Status parse error on {topic}: {e}")

    def _on_fault_event(self, topic, payload):
        if not self._running:
            return
        self._stats["messages_received"] += 1

        try:
            payload = self._ensure_dict(payload)
            if not payload:
                return

            parts = topic.split("/")
            line = parts[1]
            station = parts[2]

            line_csv = self._get_line_csv(line)
            if not line_csv:
                return

            fault_type = payload.get("fault_type", "")
            detail_key = (line, station, fault_type)
            detail = self._pending_details.pop(detail_key, None)

            row = extract_fault_event_row(line, station, payload, detail)
            line_csv.faults.write_row(row)

            self._stats["rows_written"] += 1
            self._stats[f"{line}_rows"] += 1

            action = payload.get("action", "?")
            severity = payload.get("severity", "?")
            logger.info(f"  ⚡ FAULT: {line}/{station} — "
                        f"{fault_type} {action} (sev {severity})")

        except Exception as e:
            self._stats["errors"] += 1
            logger.debug(f"Fault event parse error on {topic}: {e}")

    def _on_fault_detail(self, topic, payload):
        if not self._running:
            return
        self._stats["messages_received"] += 1

        try:
            payload = self._ensure_dict(payload)
            if not payload:
                return

            parts = topic.split("/")
            line = parts[1]
            station = parts[2]
            fault_type = payload.get("fault_type", "")

            line_csv = self._get_line_csv(line)
            if not line_csv:
                return

            # Cache for correlation
            detail_key = (line, station, fault_type)
            self._pending_details[detail_key] = payload

            # Write detail row to this line's faults CSV
            row = {
                "timestamp": payload.get(
                    "timestamp", datetime.utcnow().isoformat() + "Z"),
                "local_time": datetime.now().strftime(
                    "%Y-%m-%d %H:%M:%S.%f")[:-3],
                "line": line,
                "station": station,
                "fault_type": fault_type,
                "severity": payload.get("severity", ""),
                "action": "detail",
                "real_cause": payload.get("real_cause", ""),
                "effect_description": payload.get("effect_description", ""),
                "mtbf_hours": payload.get("mtbf_hours", ""),
            }
            line_csv.faults.write_row(row)

            self._stats["rows_written"] += 1
            self._stats[f"{line}_rows"] += 1

        except Exception as e:
            self._stats["errors"] += 1
            logger.debug(f"Fault detail parse error on {topic}: {e}")

    def _on_production(self, topic, payload):
        if not self._running:
            return
        self._stats["messages_received"] += 1

        try:
            payload = self._ensure_dict(payload)
            if not payload:
                return

            parts = topic.split("/")
            line = parts[1]

            line_csv = self._get_line_csv(line)
            if not line_csv:
                return

            row = extract_production_row(line, payload)
            line_csv.production.write_row(row)

            self._stats["rows_written"] += 1
            self._stats[f"{line}_rows"] += 1

        except Exception as e:
            self._stats["errors"] += 1
            logger.debug(f"Production parse error on {topic}: {e}")

    def _on_summary(self, topic, payload):
        if not self._running:
            return
        self._stats["messages_received"] += 1

        try:
            payload = self._ensure_dict(payload)
            if not payload:
                return

            row = extract_summary_row(payload)
            self.summary_csv.write_row(row)
            self._stats["rows_written"] += 1

        except Exception as e:
            self._stats["errors"] += 1
            logger.debug(f"Summary parse error on {topic}: {e}")

    # ── Reporting ──

    def print_stats(self):
        s = self._stats
        print()
        print("  📊 Logger Statistics:")
        print(f"     Messages received:  {s['messages_received']:,}")
        print(f"     Rows written:       {s['rows_written']:,}")
        print(f"       ├─ Line 1:        {s['line1_rows']:,}")
        print(f"       └─ Line 2:        {s['line2_rows']:,}")
        print(f"     Messages dropped:   {s['messages_dropped']:,} (rate limited)")
        print(f"     Errors:             {s['errors']:,}")
        print()

        for line_id in ["line1", "line2"]:
            line_set = self.line_csv[line_id]
            print(f"  📂 {line_id.upper()} files:")
            for w in line_set.all_writers:
                try:
                    size_kb = w.filepath.stat().st_size / 1024 if w.filepath.exists() else 0
                except OSError:
                    size_kb = 0
                print(f"     {w.filepath.name:25s} {w.total_rows:>8,} rows  {size_kb:>8.1f} KB")
            print()

        # Summary
        try:
            size_kb = (self.summary_csv.filepath.stat().st_size / 1024
                       if self.summary_csv.filepath.exists() else 0)
        except OSError:
            size_kb = 0
        print(f"  📄 Shared:")
        print(f"     {self.summary_csv.filepath.name:25s} "
              f"{self.summary_csv.total_rows:>8,} rows  {size_kb:>8.1f} KB")
        print()

    def flush_all(self):
        for w in self._all_writers:
            w.flush()

    def close(self):
        self._running = False
        for w in self._all_writers:
            w.close()


# ═══════════════════════════════════════════════════════════════════════════
# PERIODIC STATS PRINTER
# ═══════════════════════════════════════════════════════════════════════════

class StatsTimer(threading.Thread):
    def __init__(self, data_logger, interval=30.0):
        super().__init__(daemon=True, name="StatsTimer")
        self.data_logger = data_logger
        self.interval = interval
        self._stop_event = threading.Event()

    def run(self):
        while not self._stop_event.is_set():
            self._stop_event.wait(timeout=self.interval)
            if not self._stop_event.is_set():
                self.data_logger.flush_all()
                self.data_logger.print_stats()

    def stop(self):
        self._stop_event.set()


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="MQTT Data Logger — Saves each line to separate CSV files",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python tests/mqtt_data_logger.py
  python tests/mqtt_data_logger.py --output ./data/run_001
  python tests/mqtt_data_logger.py --duration 3600
  python tests/mqtt_data_logger.py --interval 0.2

Prerequisites:
  1. Start Mosquitto:   mosquitto -v
  2. Start logger:      python tests/mqtt_data_logger.py
  3. Start simulation:  python run_twin.py

Output folder structure:
  data/run_001/
  ├── line1/
  │   ├── telemetry.csv      ← Line 1 sensor data
  │   ├── faults.csv         ← Line 1 fault events
  │   ├── production.csv     ← Line 1 cycle completions
  │   └── status.csv         ← Line 1 state changes
  ├── line2/
  │   ├── telemetry.csv      ← Line 2 sensor data
  │   ├── faults.csv         ← Line 2 fault events
  │   ├── production.csv     ← Line 2 cycle completions
  │   └── status.csv         ← Line 2 state changes
  └── summary.csv            ← Cross-line summary
        """,
    )

    parser.add_argument(
        "--output", "-o", default="data",
        help="Output directory (default: data/)",
    )
    parser.add_argument(
        "--interval", "-i", type=float, default=0.5,
        help="Min seconds between writes per station (default: 0.5)",
    )
    parser.add_argument(
        "--duration", "-d", type=int, default=0,
        help="Run duration in seconds, 0=indefinite (default: 0)",
    )
    parser.add_argument(
        "--host", default=None,
        help="MQTT broker host (default: from settings / localhost)",
    )
    parser.add_argument(
        "--port", type=int, default=None,
        help="MQTT broker port (default: from settings / 1883)",
    )
    parser.add_argument(
        "--stats-interval", type=float, default=30.0,
        help="Seconds between stats printout (default: 30)",
    )
    parser.add_argument(
        "--flush-rows", type=int, default=50,
        help="Flush CSV after N rows (default: 50)",
    )
    parser.add_argument(
        "--flush-interval", type=float, default=5.0,
        help="Flush CSV after N seconds (default: 5.0)",
    )

    args = parser.parse_args()

    # Resolve host/port
    try:
        from config.settings import MQTT_BROKER_HOST, MQTT_BROKER_PORT
        mqtt_host = args.host or MQTT_BROKER_HOST
        mqtt_port = args.port or MQTT_BROKER_PORT
    except ImportError:
        mqtt_host = args.host or "localhost"
        mqtt_port = args.port or 1883

    # ── Banner ──
    print()
    print("═" * 70)
    print("  📊 MQTT SENSOR DATA LOGGER")
    print("  Saves each line to SEPARATE CSV files")
    print("═" * 70)
    print()
    print("  Output folder structure:")
    print(f"  {args.output}/")
    print(f"  ├── line1/")
    print(f"  │   ├── telemetry.csv")
    print(f"  │   ├── faults.csv")
    print(f"  │   ├── production.csv")
    print(f"  │   └── status.csv")
    print(f"  ├── line2/")
    print(f"  │   ├── telemetry.csv")
    print(f"  │   ├── faults.csv")
    print(f"  │   ├── production.csv")
    print(f"  │   └── status.csv")
    print(f"  └── summary.csv")
    print()

    # ─── Connect MQTT ───
    mqtt_client = None

    try:
        from core.mqtt_client import MQTTClient
        mqtt_client = MQTTClient("data_logger")

        if not mqtt_client.connect():
            logger.error(
                f"❌ Cannot connect to MQTT broker at {mqtt_host}:{mqtt_port}")
            logger.error("")
            logger.error("   ╔══════════════════════════════════════════════╗")
            logger.error("   ║  Make sure Mosquitto is running FIRST!      ║")
            logger.error("   ║                                              ║")
            logger.error("   ║  Terminal 1:  mosquitto -v                   ║")
            logger.error("   ║  Terminal 2:  python tests/mqtt_data_logger  ║")
            logger.error("   ║  Terminal 3:  python run_twin.py             ║")
            logger.error("   ╚══════════════════════════════════════════════╝")
            sys.exit(1)

        logger.info(f"✅ MQTT connected to {mqtt_host}:{mqtt_port}")

    except ImportError as e:
        logger.warning(f"⚠️ Could not import MQTTClient: {e}")
        logger.info("   Falling back to direct paho-mqtt...")

        try:
            import paho.mqtt.client as paho_mqtt

            class FallbackMQTT:
                def __init__(self, host, port):
                    self.host = host
                    self.port = port
                    self._client = paho_mqtt.Client(
                        client_id=f"data_logger_{int(time.time())}",
                        protocol=paho_mqtt.MQTTv311,
                    )
                    self._handlers = {}
                    self.is_connected = False
                    self._conn_event = threading.Event()

                def connect(self):
                    try:
                        self._client.on_connect = self._on_connect
                        self._client.on_message = self._dispatch
                        self._client.connect(self.host, self.port, 60)
                        self._client.loop_start()
                        return self._conn_event.wait(timeout=10)
                    except Exception as e:
                        logger.error(f"MQTT connect error: {e}")
                        return False

                def _on_connect(self, client, userdata, flags, rc):
                    if rc == 0:
                        self.is_connected = True
                        self._conn_event.set()
                        logger.info("✅ MQTT connected (paho fallback)")
                        for topic in self._handlers:
                            self._client.subscribe(topic)

                def subscribe(self, topic, handler):
                    self._handlers[topic] = handler
                    if self.is_connected:
                        self._client.subscribe(topic)

                def _dispatch(self, client, userdata, msg):
                    try:
                        raw = msg.payload.decode("utf-8")
                        try:
                            data = json.loads(raw)
                        except json.JSONDecodeError:
                            data = raw
                        for pattern, handler in self._handlers.items():
                            if paho_mqtt.topic_matches_sub(pattern, msg.topic):
                                handler(msg.topic, data)
                                return
                    except Exception as e:
                        logger.error(f"❌ Error processing {msg.topic}: {e}")

                def disconnect(self):
                    self._client.loop_stop()
                    self._client.disconnect()

            mqtt_client = FallbackMQTT(mqtt_host, mqtt_port)
            if not mqtt_client.connect():
                logger.error(f"❌ Cannot connect to MQTT at {mqtt_host}:{mqtt_port}")
                logger.error("   Start Mosquitto first:  mosquitto -v")
                sys.exit(1)

        except ImportError:
            logger.error("❌ paho-mqtt not installed!")
            logger.error("   Install:  pip install paho-mqtt")
            sys.exit(1)

    # ─── Create Data Logger ───
    data_logger = MQTTDataLogger(
        mqtt_client,
        output_dir=args.output,
        min_interval=args.interval,
        flush_rows=args.flush_rows,
        flush_interval=args.flush_interval,
    )

    data_logger.subscribe_all()

    stats_timer = StatsTimer(data_logger, interval=args.stats_interval)
    stats_timer.start()

    # ── Startup banner ──
    print()
    print("═" * 70)
    print("  ✅ DATA LOGGER RUNNING!")
    print(f"  📁 Output: {Path(args.output).resolve()}")
    print(f"  ⏱️  Sample interval: {args.interval}s per station")
    if args.duration:
        print(f"  ⏰ Duration: {args.duration}s ({args.duration / 60:.1f} min)")
    else:
        print("  ⏰ Duration: indefinite (Ctrl+C to stop)")
    print(f"  📊 Stats every {args.stats_interval}s")
    print()
    print("  Waiting for MQTT messages...")
    print("  (Start run_twin.py in another terminal)")
    print("═" * 70)
    print()

    # ─── Graceful shutdown ───
    shutdown = threading.Event()

    def signal_handler(sig, frame):
        print()
        logger.info("🛑 Shutdown signal received...")
        shutdown.set()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # ─── Main loop ───
    try:
        if args.duration > 0:
            shutdown.wait(timeout=args.duration)
            if not shutdown.is_set():
                logger.info(f"⏰ Duration {args.duration}s reached")
        else:
            shutdown.wait()
    except KeyboardInterrupt:
        pass

    # ─── Shutdown ───
    logger.info("")
    logger.info("🛑 Stopping data logger...")

    stats_timer.stop()
    data_logger.print_stats()
    data_logger.close()

    try:
        mqtt_client.disconnect()
        logger.info("  ✅ MQTT disconnected")
    except Exception:
        pass

    # ── Final file listing ──
    print()
    print("═" * 70)
    print("  📄 OUTPUT FILES:")
    print("═" * 70)

    output_path = Path(args.output)
    if output_path.exists():
        total_size = 0
        total_files = 0
        total_rows = 0

        for line_id in ["line1", "line2"]:
            line_dir = output_path / line_id
            if line_dir.exists():
                print(f"\n  📂 {line_id.upper()}/")
                for f in sorted(line_dir.glob("*.csv")):
                    size_kb = f.stat().st_size / 1024
                    total_size += size_kb
                    total_files += 1
                    size_mb = size_kb / 1024
                    if size_mb >= 1:
                        print(f"     {f.name:25s} {size_mb:>8.1f} MB")
                    else:
                        print(f"     {f.name:25s} {size_kb:>8.1f} KB")

        # Summary file
        summary_file = output_path / "summary.csv"
        if summary_file.exists():
            size_kb = summary_file.stat().st_size / 1024
            total_size += size_kb
            total_files += 1
            print(f"\n  📄 SHARED/")
            print(f"     {summary_file.name:25s} {size_kb:>8.1f} KB")

        print(f"\n  {'─' * 50}")
        total_mb = total_size / 1024
        if total_mb >= 1:
            print(f"  Total: {total_mb:.1f} MB ({total_files} files)")
        else:
            print(f"  Total: {total_size:.1f} KB ({total_files} files)")
    else:
        print("  (no output directory found)")

    print()
    print("  Done! 👋")


if __name__ == "__main__":
    main()