"""
Real-Time Data Aggregator for AI Monitoring Agent

Tracks ALL sensors, I/O states, fault counters, QC data, sorting data,
warehouse levels, machining progress, and P&P states from every station
on both assembly lines.

Converts ~108 raw messages/sec into compact health reports every 30s.

SAVES TO:
    output_dir/line1/health_reports.jsonl     ← line 1 health snapshots
    output_dir/line2/health_reports.jsonl     ← line 2 health snapshots
    output_dir/line1/alerts.jsonl             ← line 1 alerts only
    output_dir/line2/alerts.jsonl             ← line 2 alerts only
    output_dir/factory_snapshots.jsonl        ← full factory snapshots
    output_dir/ai_context_log.txt            ← what the LLM would see

MQTT Topics:
    INPUT:  factory/line{1,2}/+/status              (raw, high frequency)
    OUTPUT: agents/monitor/line{1,2}/health          (every 30s)
            agents/monitor/line{1,2}/alert           (on anomaly)
            agents/monitor/factory/snapshot           (every 60s)

Save as: tests/realtime_aggregator.py
"""

import sys
import json
import time
import math
import logging
import argparse
import threading
import signal
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict, deque
import uuid

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.repository import DbRepository

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Aggregator")


def _utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# ═══════════════════════════════════════════════════════════════════════════
# FIELD CATEGORIES
# ═══════════════════════════════════════════════════════════════════════════

# FLUCTUATE around baseline → z-score anomaly detection
SENSOR_FIELDS = {
    "temperature",
    "vibration",
    "power_consumption",
    "motor_runtime",
    "belt_distance",
}

# ALWAYS INCREASE → track rate, NOT z-score
COUNTER_FIELDS = {
    "products_completed",
    "products_passed",
    "products_failed",
    "products_good",
    "products_rejected",
    "products_stored",
    "store_errors",
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
}

# BOUNDED 0-100% → threshold alerts
GAUGE_FIELDS = {
    "pass_rate",
    "good_rate",
    "fill_percent",
    "machining_progress",
}

OTHER_NUMERIC_FIELDS = {
    "last_vision_value",
    "expected_value",
    "cells_occupied",
    "max_cells",
}

ALL_NUMERIC_FIELDS = SENSOR_FIELDS | COUNTER_FIELDS | GAUGE_FIELDS | OTHER_NUMERIC_FIELDS

BOOLEAN_FIELDS = {
    "belt_on",
    "blade_up",
    "emitter_on",
    "sensor_entry",
    "sensor_station",
    "gripper_on",
    "emergency_active",
    "fault_active",
    "pp_has_item",
    "bar_clamped",
    "bar_at_limit",
}

CATEGORICAL_FIELDS = {
    "state",
    "pp_phase",
    "last_qc_result",
    "last_sort_result",
    "last_vision_item",
}

GAUGE_THRESHOLDS = {
    "pass_rate": {"warning_below": 80.0, "critical_below": 60.0},
    "good_rate": {"warning_below": 80.0, "critical_below": 60.0},
    "fill_percent": {"warning_above": 85.0, "critical_above": 95.0},
}

SENSOR_THRESHOLDS = {
    "temperature": {"warning": 55.0, "critical": 70.0},
    "vibration": {"warning": 45.0, "critical": 60.0},
    "power_consumption": {"warning": 4.0, "critical": 5.0},
}

# States that are normal "waiting" — don't trigger stuck alerts
IDLE_STATES = {
    "idle", "waiting_for_product", "waiting_upstream",
    "waiting_downstream", "waiting_for_base",
    "waiting_for_lid", "waiting_pallet", "wait_transfer",
    "wait_sensor_1", "wait_sync",
    "s2_wait_product", "s3_wait_product",
}


# ═══════════════════════════════════════════════════════════════════════════
# JSONL FILE WRITER (Thread-Safe, Append-Mode)
# ═══════════════════════════════════════════════════════════════════════════

class JSONLWriter:
    """
    Thread-safe JSONL (JSON Lines) file writer.

    Each line is a complete JSON object — easy to parse, append-friendly,
    and works great for log-style data.

    Why JSONL instead of CSV?
      - Health reports have nested/variable structure
      - Different stations have different fields
      - JSONL handles this naturally, CSV would need 200+ columns
    """

    def __init__(self, filepath):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._total_lines = 0

        # Open in append mode
        self._file = open(self.filepath, "a", encoding="utf-8")
        logger.info(f"  📄 JSONL: {self.filepath}")

    def write(self, data):
        """Write a single JSON object as one line."""
        with self._lock:
            try:
                line = json.dumps(data, default=str)
                self._file.write(line + "\n")
                self._file.flush()
                self._total_lines += 1
            except Exception as e:
                logger.error(f"JSONL write error: {e}")

    def close(self):
        with self._lock:
            if self._file:
                self._file.flush()
                self._file.close()
        logger.info(f"  ✅ Closed: {self.filepath.name} "
                    f"({self._total_lines} entries)")

    @property
    def total_lines(self):
        return self._total_lines


class TextLogWriter:
    """Thread-safe text log writer for AI context snapshots."""

    def __init__(self, filepath):
        self.filepath = Path(filepath)
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._total_entries = 0
        self._file = open(self.filepath, "a", encoding="utf-8")

    def write(self, text):
        with self._lock:
            try:
                separator = f"\n{'─' * 70}\n"
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._file.write(f"{separator}[{timestamp}]\n{text}\n")
                self._file.flush()
                self._total_entries += 1
            except Exception as e:
                logger.error(f"Text log write error: {e}")

    def close(self):
        with self._lock:
            if self._file:
                self._file.flush()
                self._file.close()


# ═══════════════════════════════════════════════════════════════════════════
# FLATTEN STATUS PAYLOAD
# ═══════════════════════════════════════════════════════════════════════════

def _safe_dict(payload, key):
    val = payload.get(key, {})
    return val if isinstance(val, dict) else {}


def flatten_status(payload):
    flat = {}
    flat["state"] = payload.get("state", "unknown")

    counters = _safe_dict(payload, "counters")
    for k in ["products_completed", "products_passed", "products_failed",
              "products_good", "products_rejected", "products_stored",
              "store_errors"]:
        if k in counters:
            flat[k] = counters[k]

    qc = _safe_dict(payload, "qc")
    if qc:
        flat["pass_rate"] = qc.get("pass_rate")
        flat["last_qc_result"] = qc.get("last_result")
        flat["last_vision_value"] = qc.get("last_vision")
        flat["last_vision_item"] = qc.get("last_vision_item")
        flat["expected_value"] = qc.get("expected_value")

    sorting = _safe_dict(payload, "sorting")
    if sorting:
        flat["good_rate"] = sorting.get("good_rate")
        flat["last_sort_result"] = sorting.get("last_result")

    machining = _safe_dict(payload, "machining")
    if machining:
        flat["machining_progress"] = machining.get("progress")

    warehouse = _safe_dict(payload, "warehouse")
    if warehouse:
        flat["fill_percent"] = warehouse.get("fill_percent")
        flat["next_cell"] = warehouse.get("next_cell")
        flat["cells_occupied"] = warehouse.get("cells_occupied")
        flat["max_cells"] = warehouse.get("max_cells")

    pp = _safe_dict(payload, "pick_and_place")
    if pp:
        flat["pp_phase"] = pp.get("phase")
        flat["pp_has_item"] = pp.get("has_item")

    bar = _safe_dict(payload, "positioning_bar")
    if bar:
        flat["bar_clamped"] = bar.get("clamped")
        flat["bar_at_limit"] = bar.get("at_limit")

    sim = _safe_dict(payload, "simulation") or _safe_dict(payload, "sensors")
    if sim:
        flat["temperature"] = sim.get("temperature", sim.get("motor_temperature"))
        flat["vibration"] = sim.get("vibration")
        flat["power_consumption"] = sim.get("power_consumption")
        flat["motor_runtime"] = sim.get("motor_runtime")
        flat["belt_distance"] = sim.get("belt_distance")

    io = _safe_dict(payload, "io_state") or _safe_dict(payload, "digital_io")
    if io:
        flat["belt_on"] = io.get("belt", io.get("belt1"))
        flat["blade_up"] = io.get("stop_blade", io.get("blade"))
        flat["emitter_on"] = io.get("emitter")
        flat["sensor_entry"] = io.get("sensor_entry")
        flat["sensor_station"] = io.get("sensor_station")
        flat["gripper_on"] = io.get("gripper", io.get("pp_grab"))

    flat["emergency_active"] = payload.get("emergency_active", False)

    faults = _safe_dict(payload, "faults")
    flat["fault_active"] = faults.get("has_fault", False)
    active_list = faults.get("active", [])
    flat["active_faults"] = active_list if isinstance(active_list, list) else []

    fc = _safe_dict(payload, "fault_counters") or _safe_dict(payload, "fault_effects")
    for key in COUNTER_FIELDS:
        if key in fc:
            flat[key] = fc[key]
    if "stutters" in fc:
        flat["belt_stutters"] = fc["stutters"]

    return {k: v for k, v in flat.items() if v is not None}


# ═══════════════════════════════════════════════════════════════════════════
# STATION STATISTICS TRACKER
# ═══════════════════════════════════════════════════════════════════════════

class StationStats:
    def __init__(self, station_id, window_seconds=60):
        self.station_id = station_id
        self.window_seconds = window_seconds

        self._sensors = defaultdict(lambda: deque(maxlen=300))
        self._counters = {}
        self._counter_prev = {}
        self._gauges = defaultdict(lambda: deque(maxlen=60))
        self._booleans = {}
        self._categoricals = {}

        self._state = "unknown"
        self._state_enter_time = time.time()
        self._last_update = 0

        self._fault_active = False
        self._active_faults = []
        self._fault_start_time = None
        self._total_fault_duration = 0.0
        self._fault_count = 0

        self._products_completed = 0
        self._production_history = deque(maxlen=120)

        self._fault_effects = {}

        self._baselines = {}
        self._baseline_samples = defaultdict(list)
        self._baseline_ready = False
        self._baseline_threshold = 50
        self._baseline_warmup = 10.0

        self._start_time = time.time()
        self._lock = threading.Lock()

    def update(self, payload):
        now = time.time()
        flat = flatten_status(payload)

        with self._lock:
            self._last_update = now

            new_state = flat.get("state", "unknown")
            if new_state != self._state:
                self._state = new_state
                self._state_enter_time = now

            for field in SENSOR_FIELDS:
                val = flat.get(field)
                if val is not None and isinstance(val, (int, float)):
                    self._sensors[field].append((now, float(val)))
                    self._update_baseline(field, float(val), now)

            # Only track these specifically as fault-driven "effects" if they are bad counters
            # Good counters like 'products_completed' naturally increase during regular operation!
            FAULT_METRICS = {"store_errors", "belt_stutters", "brownouts", "sensor_misreads", 
                             "vision_errors", "sorter_jams", "misroutes", "gripper_failures"}
                             
            for field in COUNTER_FIELDS:
                val = flat.get(field)
                if val is not None and isinstance(val, (int, float)):
                    val = int(val)
                    prev = self._counter_prev.get(field, val)
                    if val > prev and field in FAULT_METRICS:
                        self._fault_effects[field] = (
                            self._fault_effects.get(field, 0) + (val - prev)
                        )
                    self._counter_prev[field] = val
                    self._counters[field] = val

            for field in GAUGE_FIELDS:
                val = flat.get(field)
                if val is not None and isinstance(val, (int, float)):
                    self._gauges[field].append((now, float(val)))

            for field in BOOLEAN_FIELDS:
                val = flat.get(field)
                if val is not None:
                    bool_val = bool(val)
                    if field not in self._booleans:
                        self._booleans[field] = {
                            "current": bool_val,
                            "toggle_count": 0,
                            "last_change": now,
                        }
                    else:
                        if bool_val != self._booleans[field]["current"]:
                            self._booleans[field]["toggle_count"] += 1
                            self._booleans[field]["last_change"] = now
                        self._booleans[field]["current"] = bool_val

            for field in CATEGORICAL_FIELDS:
                val = flat.get(field)
                if val is not None:
                    self._categoricals[field] = val

            was_faulted = self._fault_active
            self._fault_active = flat.get("fault_active", False)
            self._active_faults = flat.get("active_faults", [])

            if self._fault_active and not was_faulted:
                self._fault_start_time = now
                self._fault_count += 1
            elif not self._fault_active and was_faulted:
                if self._fault_start_time:
                    self._total_fault_duration += (now - self._fault_start_time)
                self._fault_start_time = None

            completed = flat.get("products_completed",
                                 flat.get("products_stored", 0))
            if isinstance(completed, (int, float)):
                self._products_completed = int(completed)
                self._production_history.append((now, self._products_completed))

    def _update_baseline(self, field, value, now):
        if self._baseline_ready:
            return
        if now - self._start_time < self._baseline_warmup:
            return
        self._baseline_samples[field].append(value)
        seen = [f for f in SENSOR_FIELDS if f in self._baseline_samples]
        if not seen:
            return
        if min(len(self._baseline_samples[f]) for f in seen) >= self._baseline_threshold:
            for f in seen:
                samples = self._baseline_samples[f]
                mean = sum(samples) / len(samples)
                variance = sum((x - mean) ** 2 for x in samples) / len(samples)
                std = math.sqrt(variance) if variance > 0 else 0.01
                std = max(std, abs(mean) * 0.05) if mean != 0 else max(std, 0.5)
                self._baselines[f] = {"mean": mean, "std": std}
            self._baseline_ready = True

    def get_summary(self):
        now = time.time()
        with self._lock:
            summary = {
                "station": self.station_id,
                "state": self._state,
                "seconds_in_state": round(now - self._state_enter_time, 1),
                "last_update_ago": round(now - self._last_update, 1)
                    if self._last_update > 0 else -1,
                "products_completed": self._products_completed,
                "production_rate_per_min": self._calc_production_rate(),
                "fault_active": self._fault_active,
                "active_faults": list(self._active_faults),
                "fault_count_total": self._fault_count,
                "total_fault_duration_s": round(self._total_fault_duration, 1),
            }

            if self._fault_active and self._fault_start_time:
                summary["current_fault_duration_s"] = round(
                    now - self._fault_start_time, 1)

            effects = {k: v for k, v in self._fault_effects.items() if v > 0}
            if effects:
                summary["fault_effects"] = effects

            summary["sensors"] = {}
            for field in sorted(self._sensors.keys()):
                stats = self._calc_sensor_stats(field, now)
                if stats:
                    summary["sensors"][field] = stats

            summary["gauges"] = {}
            for field in sorted(self._gauges.keys()):
                gauge = self._calc_gauge(field, now)
                if gauge:
                    summary["gauges"][field] = gauge

            summary["io_states"] = {}
            for field, info in self._booleans.items():
                summary["io_states"][field] = {
                    "current": info["current"],
                    "toggles": info["toggle_count"],
                }

            for field, value in self._categoricals.items():
                if field != "state":
                    summary[field] = value

            summary["anomalies"] = self._detect_all_anomalies(now)

            return summary

    def _calc_sensor_stats(self, field, now):
        values = self._sensors.get(field)
        if not values:
            return None
        cutoff = now - self.window_seconds
        recent = [v for t, v in values if t >= cutoff]
        if not recent:
            return None

        mean = sum(recent) / len(recent)
        variance = sum((x - mean) ** 2 for x in recent) / len(recent)
        std = round(math.sqrt(variance), 3)

        quarter = max(1, len(recent) // 4)
        first_q = sum(recent[:quarter]) / quarter
        last_q = sum(recent[-quarter:]) / quarter
        trend = "rising" if last_q > first_q * 1.05 else \
                "falling" if last_q < first_q * 0.95 else "stable"

        return {
            "current": round(recent[-1], 2),
            "mean": round(mean, 2),
            "min": round(min(recent), 2),
            "max": round(max(recent), 2),
            "std": std,
            "trend": trend,
        }

    def _calc_gauge(self, field, now):
        values = self._gauges.get(field)
        if not values:
            return None
        cutoff = now - self.window_seconds
        recent = [v for t, v in values if t >= cutoff]
        if not recent:
            return None
        return {
            "current": round(recent[-1], 2),
            "mean": round(sum(recent) / len(recent), 2),
        }

    def _calc_production_rate(self):
        if len(self._production_history) < 2:
            return 0.0
        oldest_t, oldest_c = self._production_history[0]
        newest_t, newest_c = self._production_history[-1]
        elapsed = (newest_t - oldest_t) / 60.0
        if elapsed < 0.1:
            return 0.0
        return round((newest_c - oldest_c) / elapsed, 2)

    def _detect_all_anomalies(self, now):
        anomalies = []

        # 1. Sensor z-score
        if self._baseline_ready:
            for field, baseline in self._baselines.items():
                values = self._sensors.get(field)
                if not values:
                    continue
                _, current = values[-1]
                z = abs(current - baseline["mean"]) / baseline["std"]
                # Only trigger anomaly if the value spiked ABOVE normal. 
                # Dropping below normal just means the machine turned off or cooled down.
                if z > 4.5 and current > baseline["mean"]: 
                    anomalies.append({
                        "field": field,
                        "type": "z_score",
                        "severity": "critical" if z > 6.0 else "warning",
                        "current": round(current, 2),
                        "z_score": round(z, 1),
                        "message": (
                            f"{field}={current:.1f} is {z:.1f}σ above "
                            f"normal ({baseline['mean']:.1f})"
                        ),
                    })

        # 2. Absolute sensor thresholds
        for field, thresh in SENSOR_THRESHOLDS.items():
            values = self._sensors.get(field)
            if not values:
                continue
            _, current = values[-1]
            if current >= thresh["critical"]:
                anomalies.append({
                    "field": field, "type": "threshold",
                    "severity": "critical", "current": round(current, 2),
                    "message": f"{field}={current:.1f} exceeds CRITICAL ({thresh['critical']})",
                })
            elif current >= thresh["warning"]:
                anomalies.append({
                    "field": field, "type": "threshold",
                    "severity": "warning", "current": round(current, 2),
                    "message": f"{field}={current:.1f} exceeds WARNING ({thresh['warning']})",
                })

        # 3. Gauge thresholds
        for field, thresh in GAUGE_THRESHOLDS.items():
            values = self._gauges.get(field)
            if not values:
                continue
            _, current = values[-1]
            
            # Avoid triggering gauge alerts when production has just started and rates are volatile
            if self._products_completed < 3 and field in ["pass_rate", "good_rate"]:
                continue
                
            if "critical_below" in thresh and current < thresh["critical_below"]:
                anomalies.append({
                    "field": field, "type": "gauge_low",
                    "severity": "critical", "current": round(current, 2),
                    "message": f"{field}={current:.1f}% CRITICALLY LOW ({thresh['critical_below']}%)",
                })
            elif "warning_below" in thresh and current < thresh["warning_below"]:
                anomalies.append({
                    "field": field, "type": "gauge_low",
                    "severity": "warning", "current": round(current, 2),
                    "message": f"{field}={current:.1f}% below warning ({thresh['warning_below']}%)",
                })
            if "critical_above" in thresh and current > thresh["critical_above"]:
                anomalies.append({
                    "field": field, "type": "gauge_high",
                    "severity": "critical", "current": round(current, 2),
                    "message": f"{field}={current:.1f}% CRITICALLY HIGH ({thresh['critical_above']}%)",
                })
            elif "warning_above" in thresh and current > thresh["warning_above"]:
                anomalies.append({
                    "field": field, "type": "gauge_high",
                    "severity": "warning", "current": round(current, 2),
                    "message": f"{field}={current:.1f}% above warning ({thresh['warning_above']}%)",
                })

        return anomalies


# ═══════════════════════════════════════════════════════════════════════════
# LINE AGGREGATOR
# ═══════════════════════════════════════════════════════════════════════════

class LineAggregator:
    def __init__(self, line_id):
        self.line_id = line_id
        self.stations = {}
        self._lock = threading.Lock()

    def update_station(self, station_name, payload):
        with self._lock:
            if station_name not in self.stations:
                self.stations[station_name] = StationStats(
                    f"{self.line_id}/{station_name}")
            self.stations[station_name].update(payload)

    def get_health_report(self):
        with self._lock:
            report = {
                "line": self.line_id,
                "timestamp": _utc_now_iso(),
                "station_count": len(self.stations),
                "overall_health": "healthy",
                "stations": {},
                "alerts": [],
                "production": {
                    "total_produced": 0,
                    "total_rate_per_min": 0.0,
                    "per_station": {},
                },
                "faults": {
                    "stations_with_faults": 0,
                    "total_active_faults": 0,
                    "fault_list": [],
                    "total_fault_effects": {},
                },
                "io_summary": {
                    "emergency_active": False,
                    "belts_off": [],
                },
            }

            health_issues = 0

            for name, stats in self.stations.items():
                summary = stats.get_summary()
                report["stations"][name] = summary

                report["production"]["total_produced"] += summary["products_completed"]
                report["production"]["total_rate_per_min"] += summary["production_rate_per_min"]
                if summary["production_rate_per_min"] > 0:
                    report["production"]["per_station"][name] = {
                        "completed": summary["products_completed"],
                        "rate": summary["production_rate_per_min"],
                    }

                if summary["fault_active"]:
                    health_issues += 1
                    report["faults"]["stations_with_faults"] += 1
                    report["faults"]["total_active_faults"] += len(summary["active_faults"])
                    for fault in summary["active_faults"]:
                        report["faults"]["fault_list"].append(f"{name}: {fault}")

                for effect, count in summary.get("fault_effects", {}).items():
                    report["faults"]["total_fault_effects"][effect] = (
                        report["faults"]["total_fault_effects"].get(effect, 0) + count
                    )

                io = summary.get("io_states", {})
                if io.get("emergency_active", {}).get("current", False):
                    report["io_summary"]["emergency_active"] = True
                    health_issues += 2

                belt = io.get("belt_on", {})
                if belt and not belt.get("current", True):
                    report["io_summary"]["belts_off"].append(name)

                for anomaly in summary.get("anomalies", []):
                    health_issues += 1
                    # Build a sensor snapshot so downstream agents
                    # (simulation, diagnostic) can use real readings
                    sensor_snapshot = {
                        f: s["current"]
                        for f, s in summary.get("sensors", {}).items()
                        if "current" in s
                    }
                    report["alerts"].append({
                        "station": name,
                        "type": anomaly.get("type", "anomaly"),
                        "severity": anomaly["severity"],
                        "field": anomaly["field"],
                        "current": anomaly.get("current"),
                        "z_score": anomaly.get("z_score"),
                        "message": anomaly["message"],
                        # Real-time sensor context for the AI agents
                        "sensor_snapshot": sensor_snapshot,
                        "fault_active": summary.get("fault_active", False),
                        "active_faults": summary.get("active_faults", []),
                    })

                if summary["last_update_ago"] > 10:
                    health_issues += 1
                    report["alerts"].append({
                        "station": name, "type": "communication_loss",
                        "severity": "critical",
                        "message": f"{name} no data for {summary['last_update_ago']:.0f}s",
                    })

                if (summary["seconds_in_state"] > 120 and
                        summary["state"] not in IDLE_STATES):
                    health_issues += 1
                    report["alerts"].append({
                        "station": name, "type": "stuck_state",
                        "severity": "warning",
                        "message": f"{name} in '{summary['state']}' for {summary['seconds_in_state']:.0f}s",
                    })

                for effect, count in summary.get("fault_effects", {}).items():
                    if count >= 10:
                        report["alerts"].append({
                            "station": name, "type": "high_fault_effects",
                            "severity": "warning" if count < 20 else "critical",
                            "message": f"{name}: {effect} occurred {count} times",
                        })

            if health_issues == 0:
                report["overall_health"] = "healthy"
            elif health_issues <= 2:
                report["overall_health"] = "degraded"
            else:
                report["overall_health"] = "critical"

            report["production"]["total_rate_per_min"] = round(
                report["production"]["total_rate_per_min"], 2)

            return report

    def get_compact_report(self):
        full = self.get_health_report()
        compact = {
            "line": self.line_id,
            "health": full["overall_health"],
            "produced": full["production"]["total_produced"],
            "rate_per_min": full["production"]["total_rate_per_min"],
            "faults": full["faults"]["fault_list"],
            "fault_effects": full["faults"]["total_fault_effects"],
            "alerts": [f"[{a['severity'].upper()}] {a['message']}"
                       for a in full["alerts"][:8]],
        }

        problems = {}
        for name, summary in full["stations"].items():
            if (summary["fault_active"] or summary.get("anomalies") or
                    summary["last_update_ago"] > 10):
                stn = {"state": summary["state"]}
                if summary["active_faults"]:
                    stn["faults"] = summary["active_faults"]
                for f in ["temperature", "vibration", "power_consumption"]:
                    if f in summary.get("sensors", {}):
                        s = summary["sensors"][f]
                        stn[f] = f"{s['current']}({s['trend']})"
                for f in ["pass_rate", "good_rate", "fill_percent"]:
                    if f in summary.get("gauges", {}):
                        stn[f] = f"{summary['gauges'][f]['current']}%"
                effects = summary.get("fault_effects", {})
                if effects:
                    stn["effects"] = effects
                io = summary.get("io_states", {})
                if io.get("emergency_active", {}).get("current"):
                    stn["emergency"] = True
                if io.get("belt_on", {}).get("current") is False:
                    stn["belt_off"] = True
                problems[name] = stn

        compact["problem_stations"] = problems if problems else "none"
        return compact


# ═══════════════════════════════════════════════════════════════════════════
# FACTORY AGGREGATOR — WITH FILE SAVING
# ═══════════════════════════════════════════════════════════════════════════

class FactoryAggregator:
    """
    Top-level aggregator with file saving.

    Saves to:
        output_dir/line1/health_reports.jsonl
        output_dir/line2/health_reports.jsonl
        output_dir/line1/alerts.jsonl
        output_dir/line2/alerts.jsonl
        output_dir/factory_snapshots.jsonl
        output_dir/ai_context_log.txt
    """

    def __init__(self, mqtt_client, output_dir="data/aggregator",
                 health_interval=30.0, snapshot_interval=60.0):
        self.mqtt = mqtt_client
        self.output_dir = Path(output_dir)
        self.health_interval = health_interval
        self.snapshot_interval = snapshot_interval
        self._running = True

        self.lines = {
            "line1": LineAggregator("line1"),
            "line2": LineAggregator("line2"),
        }

        self._stats = {
            "messages_processed": 0,
            "health_reports_sent": 0,
            "alerts_sent": 0,
        }

        # ── Create output files ──
        logger.info("")
        logger.info("  📂 Creating output files:")

        self._health_writers = {}
        self._alert_writers = {}
        for line_id in ["line1", "line2"]:
            self._health_writers[line_id] = JSONLWriter(
                self.output_dir / line_id / "health_reports.jsonl"
            )
            self._alert_writers[line_id] = JSONLWriter(
                self.output_dir / line_id / "alerts.jsonl"
            )

        self._snapshot_writer = JSONLWriter(
            self.output_dir / "factory_snapshots.jsonl"
        )
        self._context_writer = TextLogWriter(
            self.output_dir / "ai_context_log.txt"
        )

        self._all_writers = (
            list(self._health_writers.values()) +
            list(self._alert_writers.values()) +
            [self._snapshot_writer]
        )

        logger.info("")
        logger.info(f"  📁 Output: {self.output_dir.resolve()}")

    def subscribe(self):
        for line_id in ["line1", "line2"]:
            topic = f"factory/{line_id}/+/status"
            self.mqtt.subscribe(topic, self._on_status)
            logger.info(f"  📡 Subscribed: {topic}")

    def _on_status(self, topic, payload):
        if not self._running:
            return
        try:
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, dict):
                return
            parts = topic.split("/")
            line = parts[1]
            station = parts[2]
            agg = self.lines.get(line)
            if agg:
                agg.update_station(station, payload)
                self._stats["messages_processed"] += 1
        except Exception as e:
            logger.debug(f"Aggregator error: {e}")

    def start_publishing(self):
        self._health_thread = threading.Thread(
            target=self._health_loop, daemon=True, name="HealthPublisher")
        self._health_thread.start()

        self._snapshot_thread = threading.Thread(
            target=self._snapshot_loop, daemon=True, name="SnapshotPublisher")
        self._snapshot_thread.start()

        logger.info(f"  📊 Health reports: every {self.health_interval}s")
        logger.info(f"  📸 Snapshots: every {self.snapshot_interval}s")

    def _health_loop(self):
        while self._running:
            time.sleep(self.health_interval)
            if not self._running:
                break

            for line_id, agg in self.lines.items():
                try:
                    report = agg.get_health_report()

                    # 1. Publish to MQTT
                    self.mqtt.publish(
                        f"agents/monitor/{line_id}/health", report)
                    self._stats["health_reports_sent"] += 1

                    # 2. SAVE to file
                    self._health_writers[line_id].write(report)

                    # 3. Process alerts
                    for alert in report.get("alerts", []):
                        # Construct a unique event_id for idempotency
                        event_id = "EV-MONITOR-" + uuid.uuid4().hex[:8]
                        # A stable correlation ID for the station if it's currently faulting, or a new fast one
                        correlation_id = f"CORR-{line_id}-{alert['station']}-{int(time.time())}"
                        
                        try:
                            # DB Trigger! Inject real fault incident directly into the SQLite data lake
                            db_res = DbRepository.save_monitor_alert(
                                event_id=event_id,
                                correlation_id=correlation_id,
                                alert_type=alert["type"],
                                message=alert["message"],
                                severity=alert["severity"],
                                line_id=line_id,
                                station_id=alert["station"],
                                status="open",
                                payload_json=alert
                            )
                            logger.debug(f"DB Insert: {db_res}")
                        except Exception as db_e:
                            logger.error(f"Failed DB Trigger on {line_id}: {db_e}")

                        # Publish to MQTT
                        self.mqtt.publish(
                            f"agents/monitor/{line_id}/alert", alert)
                        # SAVE to file
                        self._alert_writers[line_id].write(alert)
                        self._stats["alerts_sent"] += 1

                    # Console log
                    health = report["overall_health"]
                    produced = report["production"]["total_produced"]
                    faults = report["faults"]["total_active_faults"]
                    alerts_n = len(report.get("alerts", []))
                    effects = report["faults"]["total_fault_effects"]

                    icon = {"healthy": "✅", "degraded": "⚠️",
                            "critical": "🔴"}.get(health, "❓")
                    eff_str = ""
                    if effects:
                        top = sorted(effects.items(),
                                     key=lambda x: x[1], reverse=True)[:3]
                        eff_str = " | " + ", ".join(
                            f"{k}={v}" for k, v in top)

                    logger.info(
                        f"  {icon} {line_id}: {health} | "
                        f"produced={produced} | faults={faults} | "
                        f"alerts={alerts_n}{eff_str}")

                except Exception as e:
                    logger.error(f"Health error {line_id}: {e}")

    def _snapshot_loop(self):
        while self._running:
            time.sleep(self.snapshot_interval)
            if not self._running:
                break
            try:
                snapshot = {
                    "timestamp": _utc_now_iso(),
                    "lines": {},
                }
                for line_id, agg in self.lines.items():
                    snapshot["lines"][line_id] = agg.get_compact_report()

                # Publish to MQTT
                self.mqtt.publish("agents/monitor/factory/snapshot", snapshot)

                # SAVE to file
                self._snapshot_writer.write(snapshot)

                # Also save AI context as text
                context = self.get_ai_context()
                self._context_writer.write(context)

            except Exception as e:
                logger.error(f"Snapshot error: {e}")

    def get_ai_context(self):
        parts = ["=== FACTORY STATUS ===",
                  f"Time: {datetime.now().strftime('%H:%M:%S')}"]

        for line_id in ["line1", "line2"]:
            compact = self.lines[line_id].get_compact_report()
            parts.append(f"\n--- {line_id.upper()} ---")
            parts.append(f"Health: {compact['health']}")
            parts.append(
                f"Production: {compact['produced']} units "
                f"({compact['rate_per_min']}/min)")

            if compact["faults"]:
                parts.append(f"ACTIVE FAULTS: {', '.join(compact['faults'])}")
            effects = compact.get("fault_effects", {})
            if effects:
                parts.append("FAULT EFFECTS: " + ", ".join(
                    f"{k}={v}" for k, v in effects.items()))
            if compact["alerts"]:
                for alert in compact["alerts"][:5]:
                    parts.append(f"  ⚠ {alert}")

            if isinstance(compact["problem_stations"], dict):
                for name, info in compact["problem_stations"].items():
                    lp = [f"  {name}: state={info['state']}"]
                    if info.get("faults"):
                        lp.append(f"faults={info['faults']}")
                    for f in ["temperature", "vibration", "power_consumption",
                              "pass_rate", "good_rate", "fill_percent"]:
                        if f in info:
                            lp.append(f"{f}={info[f]}")
                    if info.get("effects"):
                        lp.append(f"effects={info['effects']}")
                    if info.get("emergency"):
                        lp.append("EMERGENCY!")
                    if info.get("belt_off"):
                        lp.append("belt=OFF")
                    parts.append(" ".join(lp))
            else:
                parts.append("  All stations normal ✅")

        return "\n".join(parts)

    def get_full_json_context(self):
        return {
            "timestamp": _utc_now_iso(),
            "line1": self.lines["line1"].get_compact_report(),
            "line2": self.lines["line2"].get_compact_report(),
        }

    def print_file_stats(self):
        print()
        print("  📄 Output File Sizes:")
        for line_id in ["line1", "line2"]:
            hw = self._health_writers[line_id]
            aw = self._alert_writers[line_id]
            print(f"  📂 {line_id}/")
            for w, label in [(hw, "health_reports"), (aw, "alerts")]:
                try:
                    size = w.filepath.stat().st_size / 1024
                except OSError:
                    size = 0
                print(f"     {label + '.jsonl':30s} "
                      f"{w.total_lines:>6} entries  {size:>8.1f} KB")

        sw = self._snapshot_writer
        try:
            size = sw.filepath.stat().st_size / 1024
        except OSError:
            size = 0
        print(f"  📄 Shared:")
        print(f"     {'factory_snapshots.jsonl':30s} "
              f"{sw.total_lines:>6} entries  {size:>8.1f} KB")
        print()

    def close(self):
        self._running = False
        for w in self._all_writers:
            w.close()
        self._context_writer.close()

    def stop(self):
        self._running = False


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Real-Time Factory Aggregator — AI-ready health reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Output folder structure:
  output_dir/
  ├── line1/
  │   ├── health_reports.jsonl   ← Full health snapshot every 30s
  │   └── alerts.jsonl           ← Only anomalies/faults
  ├── line2/
  │   ├── health_reports.jsonl
  │   └── alerts.jsonl
  ├── factory_snapshots.jsonl    ← Compact factory-wide snapshot every 60s
  └── ai_context_log.txt         ← What the LLM would see (human readable)
        """,
    )

    parser.add_argument("--output", "-o", default="data/aggregator",
                        help="Output directory (default: data/aggregator)")
    parser.add_argument("--health-interval", type=float, default=30.0,
                        help="Health report interval (default: 30s)")
    parser.add_argument("--snapshot-interval", type=float, default=60.0,
                        help="Snapshot interval (default: 60s)")
    parser.add_argument("--duration", "-d", type=int, default=0,
                        help="Run duration in seconds, 0=indefinite")

    args = parser.parse_args()

    print()
    print("═" * 70)
    print("  📊 REAL-TIME FACTORY DATA AGGREGATOR")
    print("  Tracks ALL sensors → saves AI-ready reports to disk")
    print("═" * 70)
    print()
    print("  Output folder:")
    print(f"  {args.output}/")
    print(f"  ├── line1/")
    print(f"  │   ├── health_reports.jsonl   ← every {args.health_interval}s")
    print(f"  │   └── alerts.jsonl           ← on anomaly")
    print(f"  ├── line2/")
    print(f"  │   ├── health_reports.jsonl")
    print(f"  │   └── alerts.jsonl")
    print(f"  ├── factory_snapshots.jsonl    ← every {args.snapshot_interval}s")
    print(f"  └── ai_context_log.txt         ← human readable")
    print()

    try:
        from core.mqtt_client import MQTTClient
        mqtt_client = MQTTClient("aggregator")
        if not mqtt_client.connect():
            logger.error("❌ Cannot connect to MQTT. Start Mosquitto first.")
            sys.exit(1)
    except ImportError:
        logger.error("❌ MQTTClient not available")
        sys.exit(1)

    logger.info("✅ MQTT connected")

    aggregator = FactoryAggregator(
        mqtt_client,
        output_dir=args.output,
        health_interval=args.health_interval,
        snapshot_interval=args.snapshot_interval,
    )

    aggregator.subscribe()
    aggregator.start_publishing()

    print()
    print("═" * 70)
    print("  ✅ AGGREGATOR RUNNING!")
    print(f"  📁 Saving to: {Path(args.output).resolve()}")
    if args.duration:
        print(f"  ⏰ Duration: {args.duration}s ({args.duration / 60:.1f} min)")
    else:
        print("  ⏰ Duration: indefinite (Ctrl+C to stop)")
    print("═" * 70)
    print()

    shutdown = threading.Event()

    def sig_handler(sig, frame):
        print()
        logger.info("🛑 Shutdown signal received...")
        shutdown.set()

    signal.signal(signal.SIGINT, sig_handler)
    signal.signal(signal.SIGTERM, sig_handler)

    try:
        cycle = 0
        while not shutdown.is_set():
            if args.duration and cycle * 60 >= args.duration:
                break
            shutdown.wait(timeout=60)
            if shutdown.is_set():
                break
            cycle += 1

            print()
            print(f"{'═' * 70}")
            print(f"  📋 AI CONTEXT — Cycle {cycle}")
            print(f"{'═' * 70}")
            print(aggregator.get_ai_context())
            print(f"{'═' * 70}")

            s = aggregator._stats
            print(f"  Stats: processed={s['messages_processed']:,} "
                  f"health={s['health_reports_sent']} "
                  f"alerts={s['alerts_sent']}")

            aggregator.print_file_stats()

    except KeyboardInterrupt:
        pass

    logger.info("🛑 Stopping aggregator...")
    aggregator.close()
    mqtt_client.disconnect()

    # Final file listing
    print()
    print("═" * 70)
    print("  📄 FINAL OUTPUT FILES:")
    print("═" * 70)
    out = Path(args.output)
    if out.exists():
        for f in sorted(out.rglob("*")):
            if f.is_file():
                size = f.stat().st_size / 1024
                rel = f.relative_to(out)
                print(f"  {str(rel):40s} {size:>8.1f} KB")
    print()
    print("  Done! 👋")


if __name__ == "__main__":
    main()