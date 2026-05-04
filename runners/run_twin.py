"""
Run Line 1 and Line 2 concurrently — WITH REAL FAULT INJECTION + MQTT TELEMETRY

Line 1: Normal Modbus addresses (0-55)
Line 2: Offset Modbus addresses (+100 for IO, +10 for Registers)

FAULT INJECTION — ALL REAL INDUSTRIAL EFFECTS:
  Every fault models a REAL physical failure mode seen in manufacturing.
  Faults are injected per-station via interactive console or MQTT.
  Each fault produces VISIBLE effects in Factory I/O (not just log messages).

MQTT TELEMETRY:
  All sensor data, fault states, production counters, and cycle times
  are published to structured MQTT topics for digital twin consumption.

MQTT TOPICS:
  factory/line1/station_X/telemetry    — sensor data every 500ms
  factory/line2/station_X/telemetry    — sensor data every 500ms
  factory/lineN/station_X/faults/inject — per-station fault injection
  factory/lineN/faults/inject          — per-line broadcast
  factory/faults/inject                — global broadcast
  factory/lineN/station_X/status       — state changes
  factory/lineN/production             — cycle completion events

REAL FAULT MODELS (by station type):
  ┌─────────────────────────────────────────────────────────────────────────┐
  │ Station    │ Fault              │ Real Cause              │ Effect     │
  ├────────────┼────────────────────┼─────────────────────────┼────────────┤
  │ MC-A/B     │ overheat           │ Spindle bearing wear    │ +50-250%   │
  │            │                    │ coolant pump failure     │ cycle time │
  │            │ power              │ VFD capacitor aging     │ Belt OFF   │
  │            │                    │ supply voltage sag      │ 0.3-0.8s   │
  │            │ cnc_jam            │ Tool breakage           │ Start cmd  │
  │            │                    │ chip packing in flutes  │ dropped    │
  │            │ sensor_drift       │ Encoder contamination   │ Wrong      │
  │            │                    │ resolver coupling slip  │ progress   │
  │            │ material_error     │ Raw stock hardness      │ Bad part   │
  │            │                    │ variation ±15%          │ produced   │
  ├────────────┼────────────────────┼─────────────────────────┼────────────┤
  │ STN1       │ overheat           │ Belt motor winding      │ Inspect    │
  │ (Inspect)  │                    │ insulation degradation  │ time +50%  │
  │            │ vibration          │ Belt roller bearing     │ Blade      │
  │            │                    │ inner race spalling     │ chatter    │
  │            │ power              │ 24V PSU ripple >5%      │ Belt OFF   │
  │            │                    │ contactor bounce        │ 0.3-0.8s   │
  │            │ belt_slip          │ Belt surface glazing    │ Visible    │
  │            │                    │ tension spring fatigue  │ stuttering │
  │            │ sensor_drift       │ Photoelectric lens      │ False      │
  │            │                    │ dust accumulation       │ readings   │
  ├────────────┼────────────────────┼─────────────────────────┼────────────┤
  │ STN2       │ overheat           │ Stepper motor thermal   │ P&P moves  │
  │ (Assembly) │                    │ runaway (missed steps)  │ slower     │
  │            │ power              │ Pneumatic compressor    │ Belt OFF   │
  │            │                    │ pressure drop <4 bar    │ 0.3-0.8s   │
  │            │ belt_slip          │ Belt tracking           │ Product    │
  │            │                    │ misalignment (>2mm)     │ jerking    │
  │            │ sensor_drift       │ Inductive proximity     │ Position   │
  │            │                    │ sensor temp coefficient │ error      │
  │            │ gripper            │ Vacuum cup porosity     │ Lid        │
  │            │                    │ (shore hardness drop)   │ dropped    │
  │            │ pp_jam             │ Linear guide ball       │ Axis       │
  │            │                    │ screw backlash >0.1mm   │ stuck      │
  ├────────────┼────────────────────┼─────────────────────────┼────────────┤
  │ STN3       │ overheat           │ Solenoid coil I²R       │ Clamp      │
  │ (Panel)    │                    │ heating (duty cycle)    │ slower     │
  │            │ power              │ Relay contact pitting   │ Belt OFF   │
  │            │                    │ (arc erosion)           │ 0.3-0.8s   │
  │            │ belt_slip          │ Crowned pulley wear     │ Product    │
  │            │                    │ flat spot development   │ jerking    │
  │            │ sensor_drift       │ Capacitive sensor       │ Wrong      │
  │            │                    │ dielectric drift        │ detection  │
  │            │ positioner_jam     │ Cylinder rod seal       │ Bar        │
  │            │                    │ extrusion (O-ring)      │ stuck      │
  ├────────────┼────────────────────┼─────────────────────────┼────────────┤
  │ STN6       │ overheat           │ Vision CPU thermal      │ Inspect    │
  │ (QC)       │                    │ throttling (>85°C die)  │ time ×2-3  │
  │            │ power              │ LED driver PWM fault    │ Belt OFF   │
  │            │                    │ (backlight flicker)     │ 0.3-0.8s   │
  │            │ belt_slip          │ Flat belt surface       │ Product    │
  │            │                    │ oil contamination       │ jerking    │
  │            │ sensor_drift       │ Diffuse sensor          │ Entry      │
  │            │                    │ reflector degradation   │ missed     │
  │            │ vision_error       │ Camera CCD pixel        │ Wrong QC   │
  │            │                    │ degradation / hot pixel │ pass/fail  │
  ├──────��─────┼────────────────────┼─────────────────────────┼────────────┤
  │ STN7       │ overheat           │ Pivot actuator seal     │ Arm move   │
  │ (Sorting)  │                    │ thermal expansion       │ slower     │
  │            │ power              │ Solenoid valve coil     │ Belt OFF   │
  │            │                    │ short (partial)         │ 0.3-0.8s   │
  │            │ belt_slip          │ Sorting belt surface    │ Product    │
  │            │                    │ material transfer       │ jerking    │
  │            │ sensor_drift       │ Through-beam sensor     │ Entry      │
  │            │                    │ alignment vibration     │ missed     │
  │            │ sorter_jam         │ Pivot bearing seizure   │ Arm        │
  │            │                    │ (grease breakdown)      │ stuck      │
  │            │ misroute           │ Pneumatic 5/2 valve     │ Good↔      │
  │            │                    │ spool sticking          │ Reject     │
  ├────────────┼────────────────────┼─────────────────────────┼────────────┤
  │ Transfer   │ overheat           │ Servo amplifier         │ P&P        │
  │ (8)        │                    │ thermal derating        │ slower     │
  │            │ power              │ Main contactor weld     │ Belt OFF   │
  │            │                    │ (micro-welding)         │ 0.3-0.8s   │
  │            │ belt_slip          │ Drive roller lagging    │ Belt       │
  │            │                    │ rubber delamination     │ stutter    │
  │            │ sensor_drift       │ Retroreflective sensor  │ Product    │
  │            │                    │ polarization filter age │ missed     │
  │            │ pp2_jam            │ Ball screw nut preload  │ Axis cmd   │
  │            │                    │ loss (>0.05mm play)     │ dropped    │
  │            │ grab_failure       │ Venturi generator       │ Suction    │
  │            │                    │ orifice wear (flow↓)    │ lost       │
  ├────────────┼────────────────────┼─────────────────────────┼────────────┤
  │ Warehouse  │ overheat           │ Crane hoist motor       │ Operations │
  │ (9)        │                    │ thermal protection      │ slower     │
  │            │ power              │ Regenerative braking    │ Conveyor   │
  │            │                    │ resistor failure        │ OFF        │
  │            │ crane_drift        │ Absolute encoder        │ Wrong      │
  │            │                    │ battery backup failure  │ cell ±1-3  │
  │            │ sensor_drift       │ Inductive limit switch  │ Wrong      │
  │            │                    │ sensing distance drift  │ limits     │
  │            │ fork_jam           │ Fork chain elongation   │ Fork cmd   │
  │            │                    │ >2% (ANSI limit)        │ dropped    │
  └─────────────────────────────────────────────────────────────────────────┘
"""

import sys
import os
import threading
import time
import json
import logging
import random
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from factory.modbus_client import FactoryModbusClient
from factory.config import (
    STATION1_CONFIG, STATION2_CONFIG, MACHINING_A_CONFIG, MACHINING_B_CONFIG
)

STATION3_CONFIG = None
STATION6_CONFIG = None
STATION7_CONFIG = None

from factory.config_line2 import (
    STATION1_CONFIG as S1_L2,
    STATION2_CONFIG as S2_L2,
    STATION3_CONFIG as S3_L2,
    STATION6_CONFIG as S6_L2,
    STATION7_CONFIG as S7_L2,
    MACHINING_A_CONFIG as MA_L2,
    MACHINING_B_CONFIG as MB_L2,
)

from factory.stations.machining import MachiningBaseController, MachiningLidController

from tests.run_line import (
    ThreadSafeModbus,
    MachiningSynchronizer,
    SyncedStation1 as SyncedConfigStation1,
    SyncedStation2 as SyncedConfigStation2,
    SyncedStation3 as SyncedConfigStation3,
    LineStation6,
    LineStation7,
    LineTransferStation,
    LineWarehouse,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("TwinLines")


# ═══════════════════════════════════════════════════════════════════════════
# TRANSITION BELT ADDRESSES
# ═══════════════════════════════════════════════════════════════════════════

L1_BELT_1B = 1
L1_BELT_2B = 10
L1_BELT_3B = 14
L1_BELT_4B = 20
L1_BELT_5B = 27

L2_BELT_1B = 101
L2_BELT_2B = 110
L2_BELT_3B = 114
L2_BELT_4B = 120
L2_BELT_5B = 127


# ═══════════════════════════════════════════════════════════════════════════
# MQTT TELEMETRY PUBLISHER
# ═══════════════════════════════════════════════════════════════════════════

class MQTTTelemetryPublisher:
    """
    Publishes sensor data, fault states, and production events for BOTH lines.

    Topics:
      factory/line{N}/station_{X}/telemetry  — periodic sensor data (500ms)
      factory/line{N}/station_{X}/status     — state change events
      factory/line{N}/production             — cycle completion events
      factory/line{N}/faults/active          — current fault summary
      factory/twin/summary                   — cross-line production summary

    All payloads are JSON with ISO timestamp.
    """

    def __init__(self, mqtt_client):
        self.mqtt = mqtt_client
        self._lock = threading.Lock()
        self._running = True

    def publish(self, topic, payload_dict):
        """Thread-safe MQTT publish with timestamp injection."""
        if not self.mqtt:
            return
        with self._lock:
            payload_dict["timestamp"] = datetime.utcnow().isoformat() + "Z"
            try:
                self.mqtt.publish(topic, json.dumps(payload_dict))
            except Exception as e:
                logger.debug(f"MQTT publish error: {e}")

    def publish_telemetry(self, line_id, station_id, data):
        """Publish sensor telemetry for a station."""
        topic = f"factory/{line_id}/{station_id}/telemetry"
        self.publish(topic, data)

    def publish_status(self, line_id, station_id, status_data):
        """Publish station status (state, counters, faults)."""
        topic = f"factory/{line_id}/{station_id}/status"
        self.publish(topic, status_data)

    def publish_fault_event(self, line_id, station_id, fault_type,
                            severity, action="injected"):
        """Publish a fault injection/clear event."""
        topic = f"factory/{line_id}/{station_id}/faults/event"
        self.publish(topic, {
            "fault_type": fault_type,
            "severity": severity,
            "action": action,
            "station": station_id,
            "line": line_id,
        })

    def publish_production_event(self, line_id, station_id, event_data):
        """Publish production event (cycle complete, product pass/fail)."""
        topic = f"factory/{line_id}/production"
        event_data["station"] = station_id
        self.publish(topic, event_data)

    def publish_twin_summary(self, l1_stats, l2_stats):
        """Publish cross-line summary."""
        self.publish("factory/twin/summary", {
            "line1": l1_stats,
            "line2": l2_stats,
        })

    def stop(self):
        self._running = False


# ═══════════════════════════════════════════════════════════════════════════
# TELEMETRY COLLECTOR THREAD
# ═══════════════════════════════════════════════════════════════════════════

class TelemetryCollector(threading.Thread):
    """
    Background thread that periodically collects status from ALL stations
    on BOTH lines and publishes via MQTT.

    Interval: 500ms for sensor data, 5s for summary.
    """

    def __init__(self, publisher, lines_stations, interval=0.5,
                 summary_interval=5.0):
        super().__init__(daemon=True, name="TelemetryCollector")
        self.publisher = publisher
        self.lines_stations = lines_stations  # {"line1": {...}, "line2": {...}}
        self.interval = interval
        self.summary_interval = summary_interval
        self._running = True

    def run(self):
        last_summary = 0
        while self._running:
            now = time.time()

            for line_id, stations in self.lines_stations.items():
                for stn_name, stn_obj in stations.items():
                    try:
                        status = stn_obj.get_status()
                        self.publisher.publish_status(
                            line_id, stn_name, status
                        )
                    except Exception:
                        pass

            # Summary every 5s
            if now - last_summary >= self.summary_interval:
                try:
                    l1_stats = self._collect_line_stats("line1")
                    l2_stats = self._collect_line_stats("line2")
                    self.publisher.publish_twin_summary(l1_stats, l2_stats)
                except Exception:
                    pass
                last_summary = now

            time.sleep(self.interval)

    def _collect_line_stats(self, line_id):
        """Collect aggregate stats for a line."""
        stations = self.lines_stations.get(line_id, {})
        total_produced = 0
        total_faults = 0
        station_states = {}

        for name, stn in stations.items():
            try:
                st = stn.get_status()
                station_states[name] = st.get("state", "unknown")
                counters = st.get("counters", {})
                total_produced += counters.get(
                    "products_completed",
                    counters.get("products_stored",
                                 counters.get("products_sorted", 0))
                )
                faults = st.get("faults", {})
                if faults.get("has_fault"):
                    total_faults += len(faults.get("active", []))
            except Exception:
                station_states[name] = "error"

        return {
            "total_produced": total_produced,
            "active_faults": total_faults,
            "station_states": station_states,
        }

    def stop(self):
        self._running = False


# ═══════════════════════════════════════════════════════════════════════════
# CROSS-LINE EMITTER SYNCHRONIZER
# ═══════════════════════════════════════════════════════════════════════════

class TwinLineSynchronizer:
    """
    Synchronizes ALL 4 machining centers across BOTH lines to emit
    at the EXACT same time using a shared Barrier(4).

    Trigger flow:
      1. Line 1 STN2 detects base at sensor_station → trigger_line1()
      2. Line 2 STN2 detects base at sensor_station → trigger_line2()
      3. Each MC checks its flag, then waits at Barrier(4)
      4. When all 4 arrive → barrier opens → all emit simultaneously

    First cycle: all 4 skip the trigger wait (emit immediately to prime).
    """

    def __init__(self):
        self.lock = threading.Lock()
        self._emit_barrier = threading.Barrier(4)

        self._ready = {
            'l1_a': False, 'l1_b': False,
            'l2_a': False, 'l2_b': False,
        }
        self._first = {
            'l1_a': True, 'l1_b': True,
            'l2_a': True, 'l2_b': True,
        }

    def _wait(self, mc_id, controller):
        """Generic wait: skip trigger on first cycle, then barrier."""
        if not self._first[mc_id]:
            logger.debug(f"{controller.STATION_ID} ┃ Waiting for STN2 trigger...")
            while controller.is_running:
                with self.lock:
                    if self._ready[mc_id]:
                        self._ready[mc_id] = False
                        break
                time.sleep(0.1)
            if not controller.is_running:
                return
        else:
            self._first[mc_id] = False

        logger.debug(f"{controller.STATION_ID} ┃ At emit gate — waiting for all MCs...")
        try:
            self._emit_barrier.wait(timeout=180)
        except threading.BrokenBarrierError:
            return
        logger.debug(f"{controller.STATION_ID} ┃ Gate open — emitting NOW!")

    def wait_l1_a(self, controller):
        self._wait('l1_a', controller)

    def wait_l1_b(self, controller):
        self._wait('l1_b', controller)

    def wait_l2_a(self, controller):
        self._wait('l2_a', controller)

    def wait_l2_b(self, controller):
        self._wait('l2_b', controller)

    def trigger_line1(self):
        with self.lock:
            self._ready['l1_a'] = True
            self._ready['l1_b'] = True

    def trigger_line2(self):
        with self.lock:
            self._ready['l2_a'] = True
            self._ready['l2_b'] = True

    def abort(self):
        try:
            self._emit_barrier.abort()
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# REAL FAULT SCENARIO DEFINITIONS
#
# Each fault is modeled after documented industrial failure modes with
# realistic probability curves and severity-dependent effects.
#
# Sources: ISO 13849 (safety), MTBF data from Siemens/ABB/Fanuc catalogs,
# FMEA templates from automotive Tier-1 suppliers.
# ═══════════════════════════════════════════════════════════════════════════

FAULT_CATALOG = {
    # ── MACHINING CENTERS ──
    "machining": {
        "overheat": {
            "real_cause": "Spindle bearing inner race wear → friction coefficient "
                          "rises from 0.0015 to 0.008. Coolant pump impeller "
                          "cavitation reduces flow 30-60%. Thermal expansion of "
                          "spindle shaft >15μm causes runout.",
            "mtbf_hours": 4000,
            "effect": "cycle_time_multiplier",
            "severity_map": {
                1: {"multiplier": 1.15, "description": "Bearing preload shift — "
                    "slight warmth, 15% slower"},
                2: {"multiplier": 1.35, "description": "Coolant flow reduced 20% — "
                    "thermal growth visible"},
                3: {"multiplier": 1.60, "description": "Spindle temp >55°C — "
                    "thermal compensation active"},
                4: {"multiplier": 2.00, "description": "Spindle temp >70°C — "
                    "feed rate auto-reduced 50%"},
                5: {"multiplier": 2.50, "description": "Spindle temp >85°C — "
                    "CRITICAL: approaching bearing seizure"},
            },
        },
        "power": {
            "real_cause": "VFD DC bus capacitor ESR increase (aging at 85°C "
                          "halves life per 10°C). Input rectifier diode forward "
                          "voltage drop causes voltage sag. Mains voltage "
                          "fluctuation ±10% outside IEC 61000-4-11.",
            "mtbf_hours": 8000,
            "effect": "brownout",
            "severity_map": {
                1: {"prob": 0.03, "duration": 0.3,
                    "description": "Occasional voltage dip — relay chatter"},
                2: {"prob": 0.06, "duration": 0.4,
                    "description": "Capacitor ESR rising — bus ripple >5%"},
                3: {"prob": 0.10, "duration": 0.5,
                    "description": "VFD undervoltage fault — auto-restart"},
                4: {"prob": 0.15, "duration": 0.6,
                    "description": "Frequent bus dips — drive faults"},
                5: {"prob": 0.20, "duration": 0.8,
                    "description": "CRITICAL: capacitor bank near failure"},
            },
        },
        "cnc_jam": {
            "real_cause": "Carbide insert chipping (flank wear >0.3mm VB). "
                          "Built-up edge formation on rake face. Chip packing "
                          "in helical flutes during deep pocket milling. "
                          "Ball screw nut backlash >0.02mm.",
            "mtbf_hours": 2000,
            "effect": "command_dropped",
            "severity_map": {
                1: {"prob": 0.04, "description": "Minor insert chip — "
                    "surface finish degraded (Ra >1.6μm)"},
                2: {"prob": 0.08, "description": "Built-up edge — "
                    "dimensional error +0.05mm"},
                3: {"prob": 0.12, "description": "Chip evacuation blockage — "
                    "tool path interrupted"},
                4: {"prob": 0.18, "description": "Tool breakage — "
                    "automatic tool change required"},
                5: {"prob": 0.25, "description": "CRITICAL: spindle overload — "
                    "emergency stop triggered"},
            },
        },
        "sensor_drift": {
            "real_cause": "Rotary encoder glass disk contamination (cutting "
                          "fluid mist). Resolver coupling set screw loosening "
                          "from vibration (torque <0.5Nm). Absolute encoder "
                          "battery voltage <2.8V (backup position lost).",
            "mtbf_hours": 6000,
            "effect": "wrong_reading",
            "severity_map": {
                1: {"prob": 0.03, "description": "Encoder dust — "
                    "occasional count error (±1 pulse)"},
                2: {"prob": 0.06, "description": "Resolver coupling slip — "
                    "position error ±0.02°"},
                3: {"prob": 0.10, "description": "Encoder battery low — "
                    "reference drift ±5 counts"},
                4: {"prob": 0.15, "description": "Glass disk scratched — "
                    "frequent miscounts"},
                5: {"prob": 0.20, "description": "CRITICAL: encoder failure — "
                    "position unreliable"},
            },
        },
        "material_error": {
            "real_cause": "Raw stock hardness variation (±15% from spec HRC). "
                          "Internal porosity from casting defects. Residual "
                          "stress from prior heat treatment causing distortion "
                          "during machining (>0.1mm bow).",
            "mtbf_hours": 5000,
            "effect": "bad_output",
            "severity_map": {
                1: {"prob": 0.05, "description": "Hardness +5% — "
                    "tool life reduced, part OK"},
                2: {"prob": 0.08, "description": "Surface porosity — "
                    "cosmetic defect only"},
                3: {"prob": 0.12, "description": "Hardness variation ±10% — "
                    "dimensional drift"},
                4: {"prob": 0.18, "description": "Internal void >1mm — "
                    "structural weakness"},
                5: {"prob": 0.25, "description": "CRITICAL: casting crack — "
                    "part fracture during machining"},
            },
        },
    },

    # ── STATION 1: CHASSIS INSPECTION ──
    "station1": {
        "overheat": {
            "real_cause": "Belt motor winding insulation class F degradation. "
                          "Ambient temperature >40°C with motor in enclosed "
                          "cabinet. Thermal resistance of heatsink increased "
                          "by dust buildup (>3mm layer).",
            "mtbf_hours": 12000,
            "effect": "timing_multiplier",
            "severity_map": {
                1: {"multiplier": 1.10, "description": "Motor warm — "
                    "slight derating, 10% slower inspection"},
                2: {"multiplier": 1.25, "description": "Cabinet temp >45°C — "
                    "fan at 100%, 25% slower"},
                3: {"multiplier": 1.50, "description": "Motor winding >100°C — "
                    "thermal protection engaged"},
                4: {"multiplier": 1.80, "description": "Insulation resistance "
                    "dropping — motor derated 45%"},
                5: {"multiplier": 2.50, "description": "CRITICAL: winding "
                    "hotspot >130°C — imminent failure"},
            },
        },
        "vibration": {
            "real_cause": "Belt roller bearing BPFO defect frequency at "
                          "3.2× shaft speed. Inner race spalling diameter "
                          ">2mm. Dynamic imbalance of drive pulley >5g·mm. "
                          "Shaft misalignment >0.05mm.",
            "mtbf_hours": 8000,
            "effect": "blade_chatter",
            "severity_map": {
                1: {"prob": 0.04, "description": "Bearing roughness — "
                    "vibration 12mm/s RMS (ISO 10816 Zone B)"},
                2: {"prob": 0.08, "description": "BPFO visible in spectrum — "
                    "vibration 18mm/s (Zone C)"},
                3: {"prob": 0.12, "description": "Spalling started — "
                    "vibration 28mm/s (Zone D)"},
                4: {"prob": 0.18, "description": "Cage wear — "
                    "random impacts, blade chatters"},
                5: {"prob": 0.25, "description": "CRITICAL: bearing cage "
                    "disintegration — severe chatter"},
            },
        },
        "power": {
            "real_cause": "24VDC power supply output ripple >5% (filter "
                          "capacitor ESR increase). Contactor auxiliary contact "
                          "bounce (>5ms). Loose wire terminal on DIN rail "
                          "block (torque <0.5Nm).",
            "mtbf_hours": 15000,
            "effect": "brownout",
            "severity_map": {
                1: {"prob": 0.02, "duration": 0.3,
                    "description": "PSU ripple 6% — relay occasional chatter"},
                2: {"prob": 0.04, "duration": 0.4,
                    "description": "Terminal resistance rising — voltage drop"},
                3: {"prob": 0.06, "duration": 0.5,
                    "description": "Contactor bounce — motor cuts 0.5s"},
                4: {"prob": 0.10, "duration": 0.6,
                    "description": "PSU capacitor failing — bus sags 15%"},
                5: {"prob": 0.15, "duration": 0.8,
                    "description": "CRITICAL: PSU near failure — frequent drops"},
            },
        },
        "belt_slip": {
            "real_cause": "Belt surface glazing from heat (friction coefficient "
                          "drops from 0.35 to 0.20). Tension spring fatigue "
                          "(free length increased >10%). Drive pulley lagging "
                          "rubber hardened (Shore A >80 vs spec 60).",
            "mtbf_hours": 6000,
            "effect": "stutter",
            "severity_map": {
                1: {"prob": 0.04, "on": 0.15, "off": 0.10,
                    "description": "Slight glazing — occasional micro-slip"},
                2: {"prob": 0.08, "on": 0.15, "off": 0.15,
                    "description": "Tension low — visible product hesitation"},
                3: {"prob": 0.12, "on": 0.20, "off": 0.20,
                    "description": "Lagging hardened — regular stuttering"},
                4: {"prob": 0.18, "on": 0.25, "off": 0.25,
                    "description": "Belt tracking off — product misaligned"},
                5: {"prob": 0.25, "on": 0.30, "off": 0.30,
                    "description": "CRITICAL: belt barely gripping — "
                    "frequent product jams"},
            },
        },
        "sensor_drift": {
            "real_cause": "Photoelectric diffuse sensor lens dust accumulation "
                          "(optical attenuation >30%). LED emitter degradation "
                          "(luminous flux -20% after 50k hours). Background "
                          "suppression reference shift from temperature.",
            "mtbf_hours": 10000,
            "effect": "wrong_reading",
            "severity_map": {
                1: {"prob": 0.03, "description": "Lens slightly dusty — "
                    "sensing range reduced 10%"},
                2: {"prob": 0.06, "description": "LED aging — "
                    "threshold margin reduced 25%"},
                3: {"prob": 0.10, "description": "Dust layer — "
                    "occasional false negatives"},
                4: {"prob": 0.15, "description": "Reference drift — "
                    "unreliable at edge of range"},
                5: {"prob": 0.20, "description": "CRITICAL: lens obscured — "
                    "frequent false readings"},
            },
        },
    },

    # ── STATION 2: PCB ASSEMBLY ──
    "station2": {
        "overheat": {
            "real_cause": "Stepper motor phase current >rated (microstepping "
                          "at high speed increases iron losses). Driver MOSFET "
                          "junction temperature >125°C. Inadequate heatsinking "
                          "in enclosed P&P housing.",
            "mtbf_hours": 10000,
            "effect": "timing_multiplier",
            "severity_map": {
                1: {"multiplier": 1.12, "description": "Motor warm — "
                    "holding torque reduced 5%"},
                2: {"multiplier": 1.30, "description": "Driver thermal flag — "
                    "current reduced 15%"},
                3: {"multiplier": 1.55, "description": "Stepper missing steps — "
                    "slower acceleration needed"},
                4: {"multiplier": 1.85, "description": "Thermal shutdown risk — "
                    "speed halved"},
                5: {"multiplier": 2.40, "description": "CRITICAL: demagnetization "
                    "risk — motor barely functional"},
            },
        },
        "power": {
            "real_cause": "Pneumatic compressor pressure drop below 4 bar "
                          "(regulator diaphragm fatigue). Air dryer desiccant "
                          "saturated — moisture in lines. FRL unit filter "
                          "element blocked (ΔP >0.5 bar).",
            "mtbf_hours": 12000,
            "effect": "brownout",
            "severity_map": {
                1: {"prob": 0.02, "duration": 0.3,
                    "description": "Pressure dip to 5.5 bar — "
                    "gripper slightly slow"},
                2: {"prob": 0.05, "duration": 0.4,
                    "description": "Regulator hunting — "
                    "pressure oscillation ±0.3 bar"},
                3: {"prob": 0.08, "duration": 0.5,
                    "description": "Filter restriction — "
                    "flow rate insufficient"},
                4: {"prob": 0.12, "duration": 0.6,
                    "description": "Moisture in lines — "
                    "valve sticking intermittently"},
                5: {"prob": 0.18, "duration": 0.8,
                    "description": "CRITICAL: pressure <4 bar — "
                    "gripper cannot hold"},
            },
        },
        "belt_slip": {
            "real_cause": "Belt tracking misalignment >2mm (crowned pulley "
                          "wear). Conveyor frame twist from thermal expansion "
                          "(steel, ΔT=20°C → 0.24mm/m). Belt joint vulcanization "
                          "degradation.",
            "mtbf_hours": 7000,
            "effect": "stutter",
            "severity_map": {
                1: {"prob": 0.04, "on": 0.12, "off": 0.10,
                    "description": "Tracking drift 1mm — occasional slip"},
                2: {"prob": 0.07, "on": 0.15, "off": 0.15,
                    "description": "Frame twist — belt rides edge"},
                3: {"prob": 0.11, "on": 0.20, "off": 0.20,
                    "description": "Joint opening — regular stutter"},
                4: {"prob": 0.16, "on": 0.25, "off": 0.25,
                    "description": "Belt edge fraying — product offset"},
                5: {"prob": 0.22, "on": 0.30, "off": 0.30,
                    "description": "CRITICAL: belt about to derail"},
            },
        },
        "sensor_drift": {
            "real_cause": "Inductive proximity sensor temperature coefficient "
                          "(±10% sensing distance over 0-60°C range). EMI from "
                          "stepper drivers coupling into sensor cable (unshielded "
                          ">300mm). Target material permeability change.",
            "mtbf_hours": 10000,
            "effect": "wrong_reading",
            "severity_map": {
                1: {"prob": 0.03, "description": "Temp drift — "
                    "sensing distance -5%"},
                2: {"prob": 0.06, "description": "EMI coupling — "
                    "occasional noise trigger"},
                3: {"prob": 0.10, "description": "Cable shield broken — "
                    "stepper noise induces false triggers"},
                4: {"prob": 0.15, "description": "Sensor face damaged — "
                    "unreliable detection"},
                5: {"prob": 0.20, "description": "CRITICAL: sensor output "
                    "intermittent — wiring fault"},
            },
        },
        "gripper": {
            "real_cause": "Vacuum cup Shore A hardness drop (from 55 to 40 "
                          "after 500k cycles). Cup lip deformation (permanent "
                          "set >0.5mm). Vacuum generator venturi orifice wear "
                          "(flow reduced 25%). Suction cup surface contamination.",
            "mtbf_hours": 3000,
            "effect": "drop_item",
            "severity_map": {
                1: {"prob": 0.04, "description": "Cup aging — "
                    "seal time increased, still grips"},
                2: {"prob": 0.08, "description": "Lip deformation — "
                    "vacuum level -15% (from -0.7 to -0.6 bar)"},
                3: {"prob": 0.12, "description": "Venturi worn — "
                    "vacuum build time doubled"},
                4: {"prob": 0.18, "description": "Cup cracked — "
                    "vacuum leak, drops during transfer"},
                5: {"prob": 0.25, "description": "CRITICAL: cup torn — "
                    "cannot maintain grip >2s"},
            },
        },
        "pp_jam": {
            "real_cause": "Linear guide ball screw backlash >0.1mm from wear. "
                          "Guide rail lubrication interval exceeded (grease "
                          "thickening). Particulate contamination in ball nut "
                          "(metal chips from nearby machining).",
            "mtbf_hours": 5000,
            "effect": "axis_stuck",
            "severity_map": {
                1: {"prob": 0.03, "description": "Backlash 0.05mm — "
                    "positioning repeatability degraded"},
                2: {"prob": 0.06, "description": "Lubrication thickening — "
                    "higher friction, occasional stick"},
                3: {"prob": 0.10, "description": "Particulate ingress — "
                    "axis binds intermittently"},
                4: {"prob": 0.15, "description": "Ball nut worn — "
                    "axis stalls under load"},
                5: {"prob": 0.22, "description": "CRITICAL: guide rail "
                    "scoring — axis may seize"},
            },
        },
    },

    # ── STATION 3: DISPLAY PANEL MOUNTING ──
    "station3": {
        "overheat": {
            "real_cause": "Solenoid coil continuous duty I²R heating "
                          "(20W at 24VDC, 0.83A). Duty cycle >60% exceeds "
                          "ED rating. Ambient temperature in cabinet >50°C "
                          "with poor ventilation.",
            "mtbf_hours": 15000,
            "effect": "timing_multiplier",
            "severity_map": {
                1: {"multiplier": 1.08, "description": "Solenoid warm — "
                    "response time +10ms"},
                2: {"multiplier": 1.20, "description": "Coil resistance up 8% — "
                    "pulling force reduced"},
                3: {"multiplier": 1.40, "description": "Armature sluggish — "
                    "clamp cycle 40% slower"},
                4: {"multiplier": 1.65, "description": "Coil insulation "
                    "degrading — intermittent operation"},
                5: {"multiplier": 2.00, "description": "CRITICAL: coil near "
                    "burnout — operation unreliable"},
            },
        },
        "power": {
            "real_cause": "Relay contact pitting from inductive load switching "
                          "(arc erosion >0.1mm). Contact resistance >100mΩ "
                          "(vs spec <50mΩ). AC contactor shading ring cracked.",
            "mtbf_hours": 20000,
            "effect": "brownout",
            "severity_map": {
                1: {"prob": 0.02, "duration": 0.3,
                    "description": "Contact pitting — occasional chatter"},
                2: {"prob": 0.04, "duration": 0.4,
                    "description": "Resistance rising — voltage drop >0.5V"},
                3: {"prob": 0.07, "duration": 0.5,
                    "description": "Arc damage — contact welding risk"},
                4: {"prob": 0.11, "duration": 0.6,
                    "description": "Shading ring crack — contactor buzzing"},
                5: {"prob": 0.16, "duration": 0.8,
                    "description": "CRITICAL: contact near failure"},
            },
        },
        "belt_slip": {
            "real_cause": "Crowned pulley crown height worn flat (<0.5mm "
                          "remaining). Belt splice degradation under cyclic "
                          "flexing. Drive motor slip >5% from rotor bar crack.",
            "mtbf_hours": 8000,
            "effect": "stutter",
            "severity_map": {
                1: {"prob": 0.03, "on": 0.12, "off": 0.10,
                    "description": "Crown wear — belt drifts occasionally"},
                2: {"prob": 0.06, "on": 0.15, "off": 0.15,
                    "description": "Splice loosening — bump at joint"},
                3: {"prob": 0.10, "on": 0.18, "off": 0.20,
                    "description": "Rotor bar crack — speed fluctuation"},
                4: {"prob": 0.15, "on": 0.22, "off": 0.25,
                    "description": "Belt tracking unstable — product shifts"},
                5: {"prob": 0.20, "on": 0.28, "off": 0.30,
                    "description": "CRITICAL: belt derailment imminent"},
            },
        },
        "sensor_drift": {
            "real_cause": "Capacitive sensor dielectric reference drift from "
                          "humidity change (ε of air varies with RH). Sensing "
                          "face contamination from panel adhesive outgassing.",
            "mtbf_hours": 12000,
            "effect": "wrong_reading",
            "severity_map": {
                1: {"prob": 0.02, "description": "Humidity drift — "
                    "threshold shift 3%"},
                2: {"prob": 0.05, "description": "Adhesive film on face — "
                    "reduced sensitivity"},
                3: {"prob": 0.08, "description": "Dielectric shift — "
                    "false triggers in humid conditions"},
                4: {"prob": 0.13, "description": "Face contaminated — "
                    "intermittent detection"},
                5: {"prob": 0.18, "description": "CRITICAL: sensor unreliable"},
            },
        },
        "positioner_jam": {
            "real_cause": "Cylinder rod seal extrusion (O-ring hardness drop "
                          "from 70 to 50 Shore A). Piston rod chrome plating "
                          "flaking (surface roughness Ra >0.4μm). Cushion "
                          "needle valve clogged with debris.",
            "mtbf_hours": 5000,
            "effect": "bar_stuck",
            "severity_map": {
                1: {"prob": 0.04, "description": "Seal wear — "
                    "slight air leak, slow extension"},
                2: {"prob": 0.08, "description": "Rod scoring — "
                    "friction increased, jerky motion"},
                3: {"prob": 0.12, "description": "Cushion blocked — "
                    "hard stop at end of stroke"},
                4: {"prob": 0.18, "description": "Seal extruded — "
                    "pressure loss, bar won't clamp"},
                5: {"prob": 0.25, "description": "CRITICAL: piston stuck — "
                    "cylinder seized"},
            },
        },
    },

    # ── STATION 6: QUALITY CONTROL ──
    "station6": {
        "overheat": {
            "real_cause": "Vision system CPU thermal throttling (TDP exceeded "
                          "at >85°C junction). Camera CMOS sensor dark current "
                          "doubles per 8°C rise. Inspection lighting LED "
                          "driver thermal foldback.",
            "mtbf_hours": 20000,
            "effect": "inspect_time_multiplier",
            "severity_map": {
                1: {"multiplier": 1.15, "description": "CPU at 75°C — "
                    "image processing 15% slower"},
                2: {"multiplier": 1.35, "description": "CPU at 80°C — "
                    "throttling begins"},
                3: {"multiplier": 1.65, "description": "CPU at 85°C — "
                    "frame rate reduced to 15fps"},
                4: {"multiplier": 2.10, "description": "LED foldback — "
                    "exposure time doubled"},
                5: {"multiplier": 3.00, "description": "CRITICAL: CPU at 95°C — "
                    "thermal emergency, 3× slower"},
            },
        },
        "power": {
            "real_cause": "LED driver PWM controller fault — duty cycle "
                          "oscillation. Camera power supply noise >50mVpp "
                          "on 12V rail. Backlight power MOSFET Rds(on) "
                          "increasing with temperature.",
            "mtbf_hours": 25000,
            "effect": "brownout",
            "severity_map": {
                1: {"prob": 0.02, "duration": 0.3,
                    "description": "LED flicker — slight exposure variation"},
                2: {"prob": 0.04, "duration": 0.4,
                    "description": "PSU noise — image noise floor rises"},
                3: {"prob": 0.07, "duration": 0.5,
                    "description": "PWM fault — lighting inconsistent"},
                4: {"prob": 0.11, "duration": 0.6,
                    "description": "Power MOSFET degrading — belt drops"},
                5: {"prob": 0.16, "duration": 0.8,
                    "description": "CRITICAL: driver circuit failing"},
            },
        },
        "belt_slip": {
            "real_cause": "Flat belt surface oil contamination from upstream "
                          "machining center coolant carryover. Belt surface "
                          "coefficient of friction reduced from 0.4 to 0.2 "
                          "by hydrocarbon film.",
            "mtbf_hours": 9000,
            "effect": "stutter",
            "severity_map": {
                1: {"prob": 0.03, "on": 0.12, "off": 0.10,
                    "description": "Slight oil film — micro-slip"},
                2: {"prob": 0.06, "on": 0.15, "off": 0.15,
                    "description": "Oil spreading — visible hesitation"},
                3: {"prob": 0.10, "on": 0.20, "off": 0.20,
                    "description": "Belt contaminated — product slides"},
                4: {"prob": 0.15, "on": 0.25, "off": 0.25,
                    "description": "Heavy contamination — product mispositioned"},
                5: {"prob": 0.20, "on": 0.30, "off": 0.30,
                    "description": "CRITICAL: belt cannot convey reliably"},
            },
        },
        "sensor_drift": {
            "real_cause": "Diffuse reflective sensor retro-reflector degradation "
                          "(UV exposure reduces retroreflective efficiency 2%/year). "
                          "Sensor LED wavelength shift with temperature "
                          "(880nm ± 20nm).",
            "mtbf_hours": 15000,
            "effect": "wrong_reading",
            "severity_map": {
                1: {"prob": 0.02, "description": "Reflector aging — "
                    "margin reduced 10%"},
                2: {"prob": 0.05, "description": "Wavelength shift — "
                    "detection threshold drift"},
                3: {"prob": 0.08, "description": "Reflector degraded — "
                    "occasional miss (dark products)"},
                4: {"prob": 0.13, "description": "Multiple factors — "
                    "unreliable detection"},
                5: {"prob": 0.18, "description": "CRITICAL: reflector failed — "
                    "frequent false readings"},
            },
        },
        "vision_error": {
            "real_cause": "Camera CCD/CMOS hot pixel development (radiation "
                          "damage accumulation). Lens coating delamination "
                          "(anti-reflection layer). Focus drift from thermal "
                          "expansion of lens barrel (aluminum, CTE 23μm/m/°C). "
                          "Color calibration drift from LED spectral aging.",
            "mtbf_hours": 15000,
            "effect": "wrong_vision_value",
            "severity_map": {
                1: {"prob": 0.05, "description": "1-2 hot pixels — "
                    "edge detection slightly affected"},
                2: {"prob": 0.10, "description": "Focus shift 10μm — "
                    "fine features blurred"},
                3: {"prob": 0.15, "description": "Color calibration off — "
                    "wrong product classification"},
                4: {"prob": 0.22, "description": "Lens coating damage — "
                    "glare causes misreads"},
                5: {"prob": 0.30, "description": "CRITICAL: camera degraded — "
                    "QC decisions unreliable"},
            },
        },
    },

    # ── STATION 7: SORTING ──
    "station7": {
        "overheat": {
            "real_cause": "Pivot actuator seal thermal expansion (NBR compound "
                          "swell >15% at >60°C). Lubricant viscosity drop "
                          "(ISO VG32 oil thins to VG22 at 50°C). Solenoid "
                          "valve coil copper resistance +40% at 100°C.",
            "mtbf_hours": 10000,
            "effect": "arm_time_multiplier",
            "severity_map": {
                1: {"multiplier": 1.12, "description": "Seal expanding — "
                    "arm response +12%"},
                2: {"multiplier": 1.30, "description": "Oil thinning — "
                    "damping reduced, arm overshoots"},
                3: {"multiplier": 1.55, "description": "Valve coil hot — "
                    "reduced solenoid force"},
                4: {"multiplier": 1.85, "description": "Seal swollen — "
                    "high friction, arm sluggish"},
                5: {"multiplier": 2.30, "description": "CRITICAL: components "
                    "at thermal limit"},
            },
        },
        "power": {
            "real_cause": "Solenoid valve coil partial short (turn-to-turn "
                          "insulation breakdown). Connector pin corrosion "
                          "(contact resistance >500mΩ). DIN valve plug "
                          "water ingress (IP65 seal failed).",
            "mtbf_hours": 18000,
            "effect": "brownout",
            "severity_map": {
                1: {"prob": 0.02, "duration": 0.3,
                    "description": "Connector oxidation — occasional dropout"},
                2: {"prob": 0.04, "duration": 0.4,
                    "description": "Pin corrosion — intermittent contact"},
                3: {"prob": 0.07, "duration": 0.5,
                    "description": "Coil partial short — reduced pull force"},
                4: {"prob": 0.11, "duration": 0.6,
                    "description": "Water ingress — electrical leakage"},
                5: {"prob": 0.16, "duration": 0.8,
                    "description": "CRITICAL: coil near burnout"},
            },
        },
        "belt_slip": {
            "real_cause": "Sorting belt surface material transfer from products "
                          "(adhesive residue buildup). Belt edge abrasion from "
                          "misalignment with sorter guides. Idler roller flat "
                          "spot from static parking.",
            "mtbf_hours": 7000,
            "effect": "stutter",
            "severity_map": {
                1: {"prob": 0.04, "on": 0.12, "off": 0.10,
                    "description": "Residue spots — occasional slip"},
                2: {"prob": 0.07, "on": 0.15, "off": 0.15,
                    "description": "Edge wear — belt wanders"},
                3: {"prob": 0.11, "on": 0.20, "off": 0.20,
                    "description": "Flat spot — belt thumps rhythmically"},
                4: {"prob": 0.16, "on": 0.25, "off": 0.25,
                    "description": "Heavy residue — product position uncertain"},
                5: {"prob": 0.22, "on": 0.30, "off": 0.30,
                    "description": "CRITICAL: sorting accuracy compromised"},
            },
        },
        "sensor_drift": {
            "real_cause": "Through-beam sensor alignment vibration (mounting "
                          "bracket resonance at 47Hz from nearby compressor). "
                          "Receiver lens contamination from sorting debris. "
                          "Fiber optic cable micro-bend loss (>1dB).",
            "mtbf_hours": 12000,
            "effect": "wrong_reading",
            "severity_map": {
                1: {"prob": 0.03, "description": "Slight misalignment — "
                    "signal margin reduced 15%"},
                2: {"prob": 0.06, "description": "Lens dusty — "
                    "small products occasionally missed"},
                3: {"prob": 0.10, "description": "Vibration-induced — "
                    "beam intermittently broken"},
                4: {"prob": 0.15, "description": "Fiber bend — "
                    "signal strength halved"},
                5: {"prob": 0.20, "description": "CRITICAL: alignment lost — "
                    "products frequently missed"},
            },
        },
        "sorter_jam": {
            "real_cause": "Pivot bearing grease breakdown (base oil separation "
                          "after 2000 hours at >50°C). Bearing cage pocket wear "
                          "(clearance >0.1mm). Actuator rod end spherical "
                          "bearing dry (Teflon liner worn through).",
            "mtbf_hours": 4000,
            "effect": "arm_stuck",
            "severity_map": {
                1: {"prob": 0.04, "description": "Grease thickening — "
                    "arm slightly slower to respond"},
                2: {"prob": 0.08, "description": "Bearing roughness — "
                    "arm hesitates at start of travel"},
                3: {"prob": 0.13, "description": "Cage wear — "
                    "arm sticks at random positions"},
                4: {"prob": 0.19, "description": "Rod end dry — "
                    "arm often ignores command"},
                5: {"prob": 0.26, "description": "CRITICAL: bearing seizure — "
                    "arm locked"},
            },
        },
        "misroute": {
            "real_cause": "Pneumatic 5/2 directional valve spool sticking "
                          "(contaminated air supply). Spring return force "
                          "degraded (spring free length +5%). Pilot pressure "
                          "insufficient from upstream regulator fault.",
            "mtbf_hours": 6000,
            "effect": "direction_inverted",
            "severity_map": {
                1: {"prob": 0.05, "description": "Spool hesitation — "
                    "occasional wrong position on fast switching"},
                2: {"prob": 0.10, "description": "Spring weakened — "
                    "valve doesn't fully return"},
                3: {"prob": 0.15, "description": "Spool contamination — "
                    "random position errors"},
                4: {"prob": 0.22, "description": "Pilot pressure low — "
                    "valve response unpredictable"},
                5: {"prob": 0.30, "description": "CRITICAL: valve failed — "
                    "arm goes random direction"},
            },
        },
    },

    # ── TRANSFER STATION ──
    "transfer": {
        "overheat": {
            "real_cause": "Servo amplifier thermal derating (ambient >45°C "
                          "reduces continuous current by 2%/°C). Motor winding "
                          "temperature rise from high duty cycle P&P operation. "
                          "Brake resistor temperature >150°C.",
            "mtbf_hours": 12000,
            "effect": "timing_multiplier",
            "severity_map": {
                1: {"multiplier": 1.10, "description": "Amplifier warm — "
                    "peak current limited 5%"},
                2: {"multiplier": 1.25, "description": "Motor thermal flag — "
                    "acceleration derated"},
                3: {"multiplier": 1.45, "description": "Brake resistor hot — "
                    "deceleration limited"},
                4: {"multiplier": 1.70, "description": "Servo derating 30% — "
                    "moves significantly slower"},
                5: {"multiplier": 2.20, "description": "CRITICAL: thermal "
                    "protection active — minimum speed only"},
            },
        },
        "power": {
            "real_cause": "Main contactor auxiliary contact micro-welding "
                          "(inrush current >10× rated). Control transformer "
                          "core saturation from DC offset. Emergency circuit "
                          "monitoring relay false trip.",
            "mtbf_hours": 15000,
            "effect": "brownout",
            "severity_map": {
                1: {"prob": 0.02, "duration": 0.3,
                    "description": "Contactor bounce — brief power interrupt"},
                2: {"prob": 0.04, "duration": 0.4,
                    "description": "Transformer hum — voltage sag 3%"},
                3: {"prob": 0.07, "duration": 0.5,
                    "description": "Monitoring relay drift — nuisance trips"},
                4: {"prob": 0.11, "duration": 0.6,
                    "description": "Contactor pitting — unreliable pull-in"},
                5: {"prob": 0.16, "duration": 0.8,
                    "description": "CRITICAL: main contactor failing"},
            },
        },
        "belt_slip": {
            "real_cause": "Drive roller lagging rubber delamination (adhesive "
                          "failure at rubber-steel interface). Belt tension "
                          "take-up screw thread worn (cannot maintain tension). "
                          "Snub roller bearing seized.",
            "mtbf_hours": 8000,
            "effect": "stutter",
            "severity_map": {
                1: {"prob": 0.03, "on": 0.12, "off": 0.10,
                    "description": "Lagging edge lifting — micro-slip"},
                2: {"prob": 0.06, "on": 0.15, "off": 0.15,
                    "description": "Tension loss — belt sags on return"},
                3: {"prob": 0.10, "on": 0.20, "off": 0.20,
                    "description": "Snub roller drag — belt stutters"},
                4: {"prob": 0.15, "on": 0.25, "off": 0.25,
                    "description": "Lagging peeling — product slippage"},
                5: {"prob": 0.20, "on": 0.30, "off": 0.30,
                    "description": "CRITICAL: belt barely driven"},
            },
        },
        "sensor_drift": {
            "real_cause": "Retroreflective sensor polarization filter aging "
                          "(UV degradation). Reflector prism array contamination "
                          "(adhesive from tape labels). Cable connector "
                          "pin oxidation (tin whisker growth).",
            "mtbf_hours": 10000,
            "effect": "wrong_reading",
            "severity_map": {
                1: {"prob": 0.03, "description": "Filter aging — "
                    "signal margin reduced 12%"},
                2: {"prob": 0.06, "description": "Reflector contaminated — "
                    "shiny objects cause false trigger"},
                3: {"prob": 0.10, "description": "Pin oxidation — "
                    "intermittent signal dropout"},
                4: {"prob": 0.15, "description": "Multiple degradation — "
                    "unreliable presence detection"},
                5: {"prob": 0.20, "description": "CRITICAL: sensor output "
                    "random"},
            },
        },
        "pp2_jam": {
            "real_cause": "Ball screw nut preload loss (>0.05mm axial play "
                          "from 500k cycles). Linear guide block seal wear "
                          "(particulate ingress). Motor encoder Z-pulse "
                          "reference loss.",
            "mtbf_hours": 4000,
            "effect": "axis_stuck",
            "severity_map": {
                1: {"prob": 0.03, "description": "Preload shift — "
                    "positioning noise ±0.02mm"},
                2: {"prob": 0.06, "description": "Guide seal worn — "
                    "friction increasing"},
                3: {"prob": 0.10, "description": "Particulate ingress — "
                    "axis binds occasionally"},
                4: {"prob": 0.16, "description": "Ball nut worn — "
                    "following error increasing"},
                5: {"prob": 0.23, "description": "CRITICAL: guide scored — "
                    "axis may seize under load"},
            },
        },
        "grab_failure": {
            "real_cause": "Venturi vacuum generator orifice wear (flow area "
                          "+15% → vacuum level drops from -0.8 to -0.5 bar). "
                          "Suction cup lip permanent deformation (creep). "
                          "Vacuum line kink from repeated P&P motion.",
            "mtbf_hours": 3000,
            "effect": "suction_lost",
            "severity_map": {
                1: {"prob": 0.04, "description": "Orifice wear — "
                    "vacuum build time +30%"},
                2: {"prob": 0.08, "description": "Cup lip deformation — "
                    "seal on smooth surfaces only"},
                3: {"prob": 0.13, "description": "Vacuum line restricted — "
                    "grip time limited to 5s"},
                4: {"prob": 0.19, "description": "Cup degraded — "
                    "drops product during acceleration"},
                5: {"prob": 0.26, "description": "CRITICAL: vacuum system "
                    "failed — cannot grip"},
            },
        },
    },

    # ── WAREHOUSE ──
    "warehouse": {
        "overheat": {
            "real_cause": "Crane hoist motor thermal protection (PTC thermistor "
                          "in winding). Frequent start/stop cycles exceed motor "
                          "duty cycle S4-60%. Brake disc temperature >200°C "
                          "from continuous lowering.",
            "mtbf_hours": 8000,
            "effect": "timing_multiplier",
            "severity_map": {
                1: {"multiplier": 1.12, "description": "Motor warm — "
                    "acceleration limited 10%"},
                2: {"multiplier": 1.28, "description": "PTC warning — "
                    "speed reduced 20%"},
                3: {"multiplier": 1.50, "description": "Brake disc hot — "
                    "longer deceleration ramps"},
                4: {"multiplier": 1.80, "description": "Motor thermal trip — "
                    "cool-down pause required"},
                5: {"multiplier": 2.50, "description": "CRITICAL: motor at "
                    "thermal limit — minimum speed"},
            },
        },
        "power": {
            "real_cause": "Regenerative braking resistor open circuit (wire "
                          "element burnout). DC bus overvoltage during lowering "
                          "(>400V on 320V bus). Input filter capacitor aging.",
            "mtbf_hours": 12000,
            "effect": "brownout",
            "severity_map": {
                1: {"prob": 0.02, "duration": 0.3,
                    "description": "Regen resistor warm — occasional trip"},
                2: {"prob": 0.04, "duration": 0.4,
                    "description": "Bus voltage spike during lowering"},
                3: {"prob": 0.07, "duration": 0.5,
                    "description": "Filter capacitor aging — bus ripple"},
                4: {"prob": 0.11, "duration": 0.6,
                    "description": "Regen element degraded — frequent OV trips"},
                5: {"prob": 0.16, "duration": 0.8,
                    "description": "CRITICAL: DC bus capacitor failing"},
            },
        },
        "crane_drift": {
            "real_cause": "Absolute encoder battery backup voltage <2.8V "
                          "(position lost on power cycle). Encoder mounting "
                          "coupling slip from vibration. Drive wheel diameter "
                          "change from wear (−0.5mm → position error accumulates "
                          "over distance).",
            "mtbf_hours": 5000,
            "effect": "wrong_cell",
            "severity_map": {
                1: {"offset_range": 1, "description": "Encoder coupling slight "
                    "slip — ±1 cell error occasionally"},
                2: {"offset_range": 1, "description": "Wheel wear 0.2mm — "
                    "±1 cell error, accumulates over rack"},
                3: {"offset_range": 2, "description": "Battery low — "
                    "reference drift ±2 cells"},
                4: {"offset_range": 2, "description": "Coupling loose — "
                    "large position errors"},
                5: {"offset_range": 3, "description": "CRITICAL: encoder "
                    "battery dead — position unreliable"},
            },
        },
        "sensor_drift": {
            "real_cause": "Inductive limit switch sensing distance drift with "
                          "temperature (−10% at −10°C, +15% at 60°C). Target "
                          "surface contamination reducing permeability. "
                          "Mounting bracket flex under crane acceleration.",
            "mtbf_hours": 15000,
            "effect": "wrong_reading",
            "severity_map": {
                1: {"prob": 0.02, "description": "Temperature drift — "
                    "trigger point shifted 5%"},
                2: {"prob": 0.05, "description": "Target contaminated — "
                    "reduced sensing margin"},
                3: {"prob": 0.08, "description": "Bracket flex — "
                    "limit triggers early/late"},
                4: {"prob": 0.13, "description": "Combined factors — "
                    "crane position uncertain"},
                5: {"prob": 0.18, "description": "CRITICAL: limits unreliable — "
                    "crane may overshoot"},
            },
        },
        "fork_jam": {
            "real_cause": "Fork chain elongation >2% (ANSI/ASME B29.1 "
                          "replacement threshold). Chain roller bearing "
                          "wear causing tight spots. Fork carriage guide "
                          "roller flat spot from overloading.",
            "mtbf_hours": 6000,
            "effect": "command_dropped",
            "severity_map": {
                1: {"prob": 0.03, "description": "Chain stretch 1% — "
                    "fork slightly overshoots"},
                2: {"prob": 0.06, "description": "Roller tight spot — "
                    "fork hesitates during extension"},
                3: {"prob": 0.10, "description": "Chain stretch 1.5% — "
                    "positioning error, fork slips"},
                4: {"prob": 0.16, "description": "Guide roller flat — "
                    "fork binds under load"},
                5: {"prob": 0.23, "description": "CRITICAL: chain at 2% — "
                    "fork may skip teeth"},
            },
        },
    },
}


# ═══════════════════════════════════════════════════════════════════════════
# FAULT INJECTION MANAGER
# ═══════════════════════════════════════════════════════════════════════════

class FaultInjectionManager:
    """
    Manages fault injection for BOTH lines — routes commands to the
    correct station and publishes fault events via MQTT.

    Supports:
      - Per-station fault injection with severity 1-5
      - Per-line broadcast (all stations on one line)
      - Global broadcast (all stations on both lines)
      - MQTT fault routing (subscribe to injection topics)
      - Real-time fault status reporting
    """

    def __init__(self, line1_stations, line2_stations,
                 mqtt_publisher=None):
        self.l1 = line1_stations  # {"mc_a": obj, "mc_b": obj, "stn1": obj, ...}
        self.l2 = line2_stations
        self.publisher = mqtt_publisher
        self._lock = threading.Lock()

    def inject(self, line_id, station_key, fault_type, severity=3):
        """
        Inject a fault into a specific station.

        Args:
            line_id: "line1" or "line2"
            station_key: "mc_a", "stn1", "stn2", "stn3", "stn6", "stn7",
                         "transfer", "warehouse"
            fault_type: fault name from FAULT_CATALOG
            severity: 1-5
        """
        stations = self.l1 if line_id == "line1" else self.l2
        station = stations.get(station_key)
        if not station:
            logger.warning(f"Unknown station: {line_id}/{station_key}")
            return False

        severity = min(max(int(severity), 1), 5)

        try:
            station.inject_fault(fault_type, severity)
            logger.info(f"⚡ {line_id}/{station_key}: "
                        f"'{fault_type}' severity {severity}")

            # Publish MQTT event
            if self.publisher:
                # Get description from catalog
                stn_type = self._station_type(station_key)
                catalog_entry = FAULT_CATALOG.get(stn_type, {}).get(fault_type, {})
                sev_info = catalog_entry.get("severity_map", {}).get(severity, {})
                desc = sev_info.get("description", "")
                real_cause = catalog_entry.get("real_cause", "")

                self.publisher.publish_fault_event(
                    line_id, station_key, fault_type, severity, action="injected"
                )
                self.publisher.publish(
                    f"factory/{line_id}/{station_key}/faults/detail", {
                        "fault_type": fault_type,
                        "severity": severity,
                        "real_cause": real_cause,
                        "effect_description": desc,
                        "mtbf_hours": catalog_entry.get("mtbf_hours", 0),
                    }
                )
            return True
        except Exception as e:
            logger.error(f"Fault injection failed: {e}")
            return False

    def clear(self, line_id, station_key, fault_type="all"):
        """Clear fault(s) from a station."""
        stations = self.l1 if line_id == "line1" else self.l2
        station = stations.get(station_key)
        if not station:
            return False

        try:
            station.clear_fault(fault_type)
            if self.publisher:
                self.publisher.publish_fault_event(
                    line_id, station_key, fault_type, 0, action="cleared"
                )
            return True
        except Exception as e:
            logger.error(f"Fault clear failed: {e}")
            return False

    def clear_all(self):
        """Clear all faults on both lines."""
        for line_id, stations in [("line1", self.l1), ("line2", self.l2)]:
            for key, station in stations.items():
                try:
                    station.clear_fault("all")
                except Exception:
                    pass
        logger.info("✅ All faults cleared on both lines")
        if self.publisher:
            self.publisher.publish("factory/faults/event", {
                "action": "all_cleared",
            })

    def inject_line(self, line_id, fault_type, severity=3):
        """Inject same fault on ALL stations of a line."""
        stations = self.l1 if line_id == "line1" else self.l2
        for key in stations:
            self.inject(line_id, key, fault_type, severity)

    def inject_global(self, fault_type, severity=3):
        """Inject same fault on ALL stations of BOTH lines."""
        self.inject_line("line1", fault_type, severity)
        self.inject_line("line2", fault_type, severity)

    def get_fault_summary(self):
        """Get fault summary for both lines."""
        summary = {"line1": {}, "line2": {}}
        for line_id, stations in [("line1", self.l1), ("line2", self.l2)]:
            for key, station in stations.items():
                try:
                    status = station.get_status()
                    faults = status.get("faults", {})
                    if faults.get("has_fault"):
                        summary[line_id][key] = faults.get("active", [])
                except Exception:
                    pass
        return summary

    def _station_type(self, key):
        """Map station key to FAULT_CATALOG type."""
        mapping = {
            "mc_a": "machining", "mc_b": "machining",
            "stn1": "station1", "stn2": "station2",
            "stn3": "station3", "stn6": "station6",
            "stn7": "station7",
            "transfer": "transfer", "warehouse": "warehouse",
        }
        return mapping.get(key, key)

    def setup_mqtt_listeners(self, mqtt_client):
        """
        Subscribe to MQTT fault injection topics.

        Topics:
          factory/line1/station_X/faults/inject
          factory/line2/station_X/faults/inject
          factory/line1/faults/inject  (line broadcast)
          factory/line2/faults/inject  (line broadcast)
          factory/faults/inject        (global broadcast)

        Payload: {"fault": "type", "severity": N}
              or {"clear": "type"}  (or "all")
        """
        if not mqtt_client:
            return

        all_keys = ["mc_a", "mc_b", "stn1", "stn2", "stn3",
                     "stn6", "stn7", "transfer", "warehouse"]

        def _handler(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode())
                topic = msg.topic

                # Parse topic to determine target
                parts = topic.split("/")

                if topic == "factory/faults/inject":
                    # Global broadcast
                    if "clear" in payload:
                        self.clear_all()
                    elif "fault" in payload:
                        self.inject_global(
                            payload["fault"],
                            payload.get("severity", 3)
                        )
                    return

                if len(parts) >= 3 and parts[2] == "faults":
                    # Line broadcast: factory/line1/faults/inject
                    line_id = parts[1]
                    if "clear" in payload:
                        for key in all_keys:
                            self.clear(line_id, key, payload["clear"])
                    elif "fault" in payload:
                        self.inject_line(
                            line_id,
                            payload["fault"],
                            payload.get("severity", 3)
                        )
                    return

                if len(parts) >= 4:
                    # Per-station: factory/line1/stn1/faults/inject
                    line_id = parts[1]
                    station_key = parts[2]
                    if "clear" in payload:
                        self.clear(line_id, station_key, payload["clear"])
                    elif "fault" in payload:
                        self.inject(
                            line_id, station_key,
                            payload["fault"],
                            payload.get("severity", 3)
                        )

            except Exception as e:
                logger.debug(f"MQTT fault handler error: {e}")

        # Subscribe to all topics
        topics = ["factory/faults/inject"]
        for line_id in ["line1", "line2"]:
            topics.append(f"factory/{line_id}/faults/inject")
            for key in all_keys:
                topics.append(f"factory/{line_id}/{key}/faults/inject")

        for topic in topics:
            try:
                mqtt_client.subscribe(topic, _handler)
            except Exception:
                pass

        logger.info(f"📡 MQTT fault listeners active on {len(topics)} topics")


# ═══════════════════════════════════════════════════════════════════════════
# COMMAND HANDLER — Receives AI agent repair commands via MQTT
# ═══════════════════════════════════════════════════════════════════════════

class CommandHandler:
    """
    Listens on MQTT for repair commands from the execution agent and
    routes them to the appropriate station controller.

    Topics:
      factory/{line_id}/{station_key}/commands/apply  — apply parameter changes
      factory/{line_id}/{station_key}/commands/clear   — clear active faults

    Payload (apply):
      {"parameters": {...}, "station_id": "stn1", "line_id": "line1"}

    Payload (clear):
      {"action": "clear", "fault_type": "overheat"|"all", ...}
    """

    def __init__(self, line1_stations, line2_stations, mqtt_client=None):
        self.l1 = line1_stations
        self.l2 = line2_stations
        self.mqtt = mqtt_client
        self._lock = threading.Lock()

    def setup_listeners(self, mqtt_client=None):
        """Subscribe to command topics for all stations on both lines."""
        client = mqtt_client or self.mqtt
        if not client:
            logger.warning("CommandHandler: No MQTT client — skipping setup")
            return

        all_keys = ["mc_a", "mc_b", "stn1", "stn2", "stn3",
                     "stn6", "stn7", "transfer", "warehouse"]

        def _on_command(client_obj, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode())
                topic = msg.topic
                parts = topic.split("/")

                # Expected: factory/{line_id}/{station_key}/commands/{action}
                if len(parts) < 5 or parts[3] != "commands":
                    return

                line_id = parts[1]
                station_key = parts[2]
                action = parts[4]  # "apply" or "clear"

                stations = self.l1 if line_id == "line1" else self.l2
                station = stations.get(station_key)
                if not station:
                    logger.warning(f"CommandHandler: Unknown station {line_id}/{station_key}")
                    return

                with self._lock:
                    if action == "clear":
                        fault_type = payload.get("fault_type", "all")
                        station.clear_fault(fault_type)
                        logger.info(f"CommandHandler: Cleared '{fault_type}' on "
                                    f"{line_id}/{station_key}")

                    elif action == "apply":
                        params = payload.get("parameters", {})
                        if hasattr(station, "apply_parameters"):
                            station.apply_parameters(params)
                            logger.info(f"CommandHandler: Applied params to "
                                        f"{line_id}/{station_key}: {params}")
                        else:
                            # Fallback: just clear faults if station lacks apply_parameters
                            if params.get("clear_fault"):
                                ft = params.get("clear_fault", "all")
                                station.clear_fault(ft if isinstance(ft, str) else "all")
                            logger.warning(f"CommandHandler: {station_key} has no "
                                           f"apply_parameters — used fallback")

            except Exception as e:
                logger.error(f"CommandHandler error: {e}")

        # Subscribe to wildcard topics for both lines
        topics = []
        for line_id in ["line1", "line2"]:
            for key in all_keys:
                topics.append(f"factory/{line_id}/{key}/commands/apply")
                topics.append(f"factory/{line_id}/{key}/commands/clear")

        for topic in topics:
            try:
                client.subscribe(topic, _on_command)
            except Exception:
                pass

        logger.info(f"📡 CommandHandler active on {len(topics)} command topics")


# ═══════════════════════════════════════════════════════════════════════════
# LINE SPAWNER
# ═══════════════════════════════════════════════════════════════════════════

def init_transition_belts(modbus, io_offset=0):
    """Turn on all 5 transition belts for a line."""
    belts = [
        (1 + io_offset, "Stn1→Stn2"),
        (10 + io_offset, "Stn2→Stn3"),
        (14 + io_offset, "Stn3→Stn6"),
        (20 + io_offset, "Stn6→Stn7"),
        (27 + io_offset, "Stn7→Transfer"),
    ]
    for addr, _ in belts:
        modbus.write_output(addr, True)
    label = "Line 2" if io_offset else "Line 1"
    logger.info(f"  🔄 {label} transition belts ON: "
                + ", ".join(f"{a}({d})" for a, d in belts))


def spawn_line(modbus_wrapper, mqtt_client, line_id="LINE1",
               wait_to_emit_a=None, wait_to_emit_b=None,
               emit_trigger_fn=None):
    """
    Spawn a complete assembly line with all stations.

    Returns:
      (stations_start_order, stations_dict, mc_sync_local)

    stations_start_order: list of (name, station_obj) in downstream-first order
    stations_dict: {"mc_a": obj, "stn1": obj, ...} for fault manager
    """
    is_l2 = (line_id == "LINE2")
    io_offset = 100 if is_l2 else 0
    reg_offset = 10 if is_l2 else 0

    cfg_s1 = S1_L2 if is_l2 else STATION1_CONFIG
    cfg_s2 = S2_L2 if is_l2 else STATION2_CONFIG
    cfg_s3 = S3_L2 if is_l2 else STATION3_CONFIG
    cfg_s6 = S6_L2 if is_l2 else STATION6_CONFIG
    cfg_s7 = S7_L2 if is_l2 else STATION7_CONFIG
    cfg_ma = MA_L2 if is_l2 else MACHINING_A_CONFIG
    cfg_mb = MB_L2 if is_l2 else MACHINING_B_CONFIG

    # Sync events
    sync_a_ready = threading.Event()
    sync_lid_ready = threading.Event()
    sync_1_ready = threading.Event()
    sync_2_ready = threading.Event()
    sync_3_ready = threading.Event()
    sync_6_ready = threading.Event()
    sync_7_ready = threading.Event()
    pallet_ready = threading.Event()
    product_placed = threading.Event()

    mc_sync_local = None
    if wait_to_emit_a is None:
        mc_sync_local = MachiningSynchronizer()
        wait_to_emit_a = mc_sync_local.wait_a
        wait_to_emit_b = mc_sync_local.wait_b
        emit_trigger_fn = mc_sync_local.trigger

    transfer_sensor_addr = 12 + io_offset
    stacker_register = 0 + reg_offset

    line_label = f"Line {'2' if is_l2 else '1'}"
    transfer_name = f"Transfer-{line_label}"

    logger.info(f"")
    logger.info(f"{'═' * 60}")
    logger.info(f"  📺 Spawning {line_label}")
    logger.info(f"     IO offset: +{io_offset}  Reg offset: +{reg_offset}")
    logger.info(f"{'═' * 60}")

    # Create stations
    stn_mach_a = MachiningBaseController(
        modbus_wrapper, mqtt_client,
        downstream_ready=sync_a_ready,
        wait_to_emit_fn=wait_to_emit_a,
        config=cfg_ma,
    )
    stn_mach_b = MachiningLidController(
        modbus_wrapper, mqtt_client,
        lid_ready_event=sync_lid_ready,
        wait_to_emit_fn=wait_to_emit_b,
        config=cfg_mb,
    )
    stn1 = SyncedConfigStation1(
        modbus_wrapper, mqtt_client,
        config=cfg_s1,
        downstream_ready=sync_1_ready,
        upstream_ready=sync_a_ready,
    )
    stn2 = SyncedConfigStation2(
        modbus_wrapper, mqtt_client,
        config=cfg_s2,
        upstream_ready=sync_1_ready,
        downstream_ready=sync_2_ready,
        lid_ready=sync_lid_ready,
        emit_trigger_fn=emit_trigger_fn,
    )
    stn3 = SyncedConfigStation3(
        modbus_wrapper, mqtt_client,
        config=cfg_s3,
        upstream_ready=sync_2_ready,
        downstream_ready=sync_3_ready,
    )
    stn6 = LineStation6(
        modbus_wrapper, mqtt_client,
        upstream_ready_event=sync_3_ready,
        downstream_ready_event=sync_6_ready,
        config=cfg_s6,
    )
    stn7 = LineStation7(
        modbus_wrapper,
        station6_ref=stn6,
        mqtt_client=mqtt_client,
        upstream_ready_event=sync_6_ready,
        config=cfg_s7,
        transfer_sensor_addr=transfer_sensor_addr,
    )
    stn_transfer = LineTransferStation(
        modbus_wrapper, mqtt_client,
        pallet_ready_event=pallet_ready,
        product_placed_event=product_placed,
        station_name=transfer_name,
        stacker_register=stacker_register,
    )
    stn_warehouse = LineWarehouse(
        modbus_wrapper, mqtt_client,
        pallet_ready_event=pallet_ready,
        product_placed_event=product_placed,
        io_offset=io_offset,
        reg_offset=reg_offset,
    )

    # Start order (downstream first)
    stations_start_order = [
        ("Warehouse", stn_warehouse),
        ("Transfer", stn_transfer),
        ("Station 7", stn7),
        ("Station 6", stn6),
        ("Station 3", stn3),
        ("Station 2", stn2),
        ("Station 1", stn1),
        ("MC-A", stn_mach_a),
        ("MC-B", stn_mach_b),
    ]

    # Dict for fault manager
    stations_dict = {
        "mc_a": stn_mach_a,
        "mc_b": stn_mach_b,
        "stn1": stn1,
        "stn2": stn2,
        "stn3": stn3,
        "stn6": stn6,
        "stn7": stn7,
        "transfer": stn_transfer,
        "warehouse": stn_warehouse,
    }

    logger.info(f"  ✅ {line_label} — ALL stations created!")
    return stations_start_order, stations_dict, mc_sync_local


# ═══════════════════════════════════════════════════════════════════════════
# THREAD LAUNCHER
# ═══════════════════════════════════════════════════════════════════════════

def start_all_threads(stations_l1, stations_l2):
    """Start ALL threads with a shared gate for simultaneous launch."""
    start_event = threading.Event()

    def gated_run(station, start_evt):
        start_evt.wait()
        station.run()

    all_threads = []

    for name, station in stations_l1:
        t = threading.Thread(
            target=gated_run, args=(station, start_event),
            daemon=True, name=f"L1-{name}",
        )
        t.start()
        all_threads.append((station, t))
        logger.info(f"  ▶ Line 1 — {name} thread ready")

    for name, station in stations_l2:
        t = threading.Thread(
            target=gated_run, args=(station, start_event),
            daemon=True, name=f"L2-{name}",
        )
        t.start()
        all_threads.append((station, t))
        logger.info(f"  ▶ Line 2 — {name} thread ready")

    logger.info("")
    logger.info("🚀 ALL threads ready — starting BOTH lines NOW!")
    start_event.set()

    return all_threads


# ═══════════════════════════════════════════════════════════════════════════
# INTERACTIVE FAULT INJECTION CONSOLE
# ═══════════════════════════════════════════════════════════════════════════

def print_fault_menu():
    """Print the interactive fault injection menu."""
    print()
    print("  ┌─────────────────────────────────────────────────────────────────────────────────────┐")
    print("  │  📺 TWIN ASSEMBLY LINES — Real Fault Injection Console ⚡                            │")
    print("  │                                                                                      │")
    print("  │  FORMAT:  <line><station><fault> [severity]     Example: 1Af1 3                      │")
    print("  │           Line: 1 or 2     Severity: 1-5 (default 3)                                │")
    print("  │                                                                                      │")
    print("  │  MACHINING CENTERS:              STATION 1 (Inspect):     STATION 2 (Assembly):      │")
    print("  │  ?Af1 = Spindle overheat         ?1f1 = Motor overheat    ?2f1 = Stepper overheat   │")
    print("  │  ?Af3 = VFD power sag            ?1f2 = Bearing vibration ?2f3 = Pneumatic drop     │")
    print("  │  ?Af4 = Tool breakage/CNC jam    ?1f3 = PSU brownout      ?2f4 = Belt tracking slip │")
    print("  │  ?Af5 = Encoder drift            ?1f4 = Belt glazing slip ?2f5 = Proximity drift    │")
    print("  │  ?Af6 = Material hardness error  ?1f5 = Lens dust drift   ?2f6 = Vacuum cup fail    │")
    print("  │  ?Bf1-6 = Same for MC-B                                   ?2f7 = Ball screw jam     │")
    print("  │                                                                                      │")
    print("  │  STATION 3 (Panel):        STATION 6 (QC):             STATION 7 (Sorting):         │")
    print("  │  ?3f1 = Solenoid overheat  ?6f1 = Vision CPU overheat  ?7f1 = Actuator overheat    │")
    print("  │  ?3f3 = Relay contact pit  ?6f3 = LED driver fault     ?7f3 = Valve coil short     │")
    print("  │  ?3f4 = Pulley wear slip   ?6f4 = Oil contamination    ?7f4 = Residue buildup slip │")
    print("  │  ?3f5 = Capacitive drift   ?6f5 = Reflector aging      ?7f5 = Beam misalignment    │")
    print("  │  ?3f6 = Cylinder seal jam  ?6f6 = CCD pixel/lens fault ?7f6 = Pivot bearing jam    │")
    print("  │                                                         ?7f7 = 5/2 valve misroute  │")
    print("  │                                                                                      │")
    print("  │  TRANSFER (8):               WAREHOUSE (9):                                         │")
    print("  │  ?8f1 = Servo overheat       ?9f1 = Crane motor overheat                            │")
    print("  │  ?8f3 = Contactor weld       ?9f3 = Regen resistor fail                             │")
    print("  │  ?8f4 = Lagging delam slip   ?9f4 = Encoder drift → wrong cell                     │")
    print("  │  ?8f5 = Retro filter aging   ?9f5 = Limit switch drift                              │")
    print("  │  ?8f6 = Ball screw jam       ?9f6 = Fork chain elongation                           │")
    print("  │  ?8f7 = Venturi wear grab                                                           │")
    print("  │                                                                                      │")
    print("  │  COMMANDS:                                                                           │")
    print("  │  fc       = Clear ALL faults (both lines)                                           │")
    print("  │  1fc / 2fc = Clear all faults on Line 1 / Line 2                                    │")
    print("  │  st       = Status summary (both lines)                                             │")
    print("  │  1st / 2st = Status for Line 1 / Line 2 only                                       │")
    print("  │  rp       = Full reports (both lines)                                               │")
    print("  │  1rp / 2rp = Reports for Line 1 / Line 2 only                                      │")
    print("  │  fe       = Fault effects counters (both lines)                                     │")
    print("  │  cat <type>= Show fault catalog for station type                                    │")
    print("  │  sc <N> <fault> <sev> = Scenario: inject across both lines                         │")
    print("  │  q        = Quit                                                                    │")
    print("  │                                                                                      │")
    print("  │  ? = line number (1 or 2).  Example: 1Af4 5 = Line1 MC-A cnc_jam severity 5        │")
    print("  └─────────────────────────────────────────────────────────────────────────────────────┘")
    print()


def fault_console(fault_manager, all_threads, twin_sync):
    """Interactive fault injection console for both lines."""

    # Fault code mapping
    station_faults = {
        "A": {"1": "overheat", "3": "power", "4": "cnc_jam",
               "5": "sensor_drift", "6": "material_error"},
        "B": {"1": "overheat", "3": "power", "4": "cnc_jam",
               "5": "sensor_drift", "6": "material_error"},
        "1": {"1": "overheat", "2": "vibration", "3": "power",
               "4": "belt_slip", "5": "sensor_drift"},
        "2": {"1": "overheat", "3": "power", "4": "belt_slip",
               "5": "sensor_drift", "6": "gripper", "7": "pp_jam"},
        "3": {"1": "overheat", "3": "power", "4": "belt_slip",
               "5": "sensor_drift", "6": "positioner_jam"},
        "6": {"1": "overheat", "3": "power", "4": "belt_slip",
               "5": "sensor_drift", "6": "vision_error"},
        "7": {"1": "overheat", "3": "power", "4": "belt_slip",
               "5": "sensor_drift", "6": "sorter_jam", "7": "misroute"},
        "8": {"1": "overheat", "3": "power", "4": "belt_slip",
               "5": "sensor_drift", "6": "pp2_jam", "7": "grab_failure"},
        "9": {"1": "overheat", "3": "power", "4": "crane_drift",
               "5": "sensor_drift", "6": "fork_jam"},
    }

    station_key_map = {
        "A": "mc_a", "B": "mc_b",
        "1": "stn1", "2": "stn2", "3": "stn3",
        "6": "stn6", "7": "stn7",
        "8": "transfer", "9": "warehouse",
    }

    print_fault_menu()

    while any(t.is_alive() for _, t in all_threads):
        try:
            cmd = input("⚡ > ").strip()
            if not cmd:
                continue

            # ── Quit ──
            if cmd.lower() == "q":
                twin_sync.abort()
                for station, _ in all_threads:
                    station.is_running = False
                break

            # ── Clear all ──
            if cmd.lower() == "fc":
                fault_manager.clear_all()
                continue

            # ── Clear per line ──
            if cmd.lower() in ("1fc", "2fc"):
                line_id = "line1" if cmd[0] == "1" else "line2"
                stations = fault_manager.l1 if line_id == "line1" \
                    else fault_manager.l2
                for key in stations:
                    fault_manager.clear(line_id, key, "all")
                print(f"  ✅ {line_id}: All faults cleared")
                continue

            # ── Status ──
            if cmd.lower() in ("st", "1st", "2st"):
                lines_to_show = []
                if cmd.lower() in ("st", "1st"):
                    lines_to_show.append(("line1", fault_manager.l1))
                if cmd.lower() in ("st", "2st"):
                    lines_to_show.append(("line2", fault_manager.l2))

                print()
                for line_id, stations in lines_to_show:
                    print(f"  {'═' * 65}")
                    print(f"  📊 {line_id.upper()} STATUS")
                    print(f"  {'═' * 65}")
                    for key, stn in stations.items():
                        try:
                            s = stn.get_status()
                            state = s.get("state", "?")
                            c = s.get("counters", {})
                            done = c.get(
                                "products_completed",
                                c.get("products_stored",
                                      c.get("products_sorted", 0))
                            )
                            faults = s.get("faults", {})
                            fault_str = (
                                ",".join(faults["active"])
                                if faults.get("has_fault")
                                else "none"
                            )
                            # Extra info per station type
                            extra = ""
                            if "qc" in s:
                                extra = (f"  pass_rate={s['qc']['pass_rate']}%"
                                         f"  last={s['qc'].get('last_result','?')}")
                            elif "sorting" in s:
                                extra = (f"  good_rate="
                                         f"{s['sorting']['good_rate']}%")
                            elif "warehouse" in s:
                                wh = s["warehouse"]
                                extra = (f"  fill={wh['fill_percent']}%"
                                         f"  next={wh['next_cell']}")
                            elif "pick_and_place" in s:
                                extra = (f"  pp={s['pick_and_place']['phase']}")
                            elif "machining" in s:
                                extra = (f"  progress="
                                         f"{s['machining']['progress']:.0f}%")

                            print(f"    {key:12s} │ {state:22s} │ "
                                  f"done={done:3d} │ "
                                  f"faults=[{fault_str}]{extra}")
                        except Exception as e:
                            print(f"    {key:12s} │ ERROR: {e}")
                    print()
                continue

            # ── Reports ──
            if cmd.lower() in ("rp", "1rp", "2rp"):
                lines_to_show = []
                if cmd.lower() in ("rp", "1rp"):
                    lines_to_show.append(("line1", fault_manager.l1))
                if cmd.lower() in ("rp", "2rp"):
                    lines_to_show.append(("line2", fault_manager.l2))

                for line_id, stations in lines_to_show:
                    print(f"\n{'═' * 70}")
                    print(f"  📊 {line_id.upper()} — FULL REPORTS")
                    print(f"{'═' * 70}")
                    for key, stn in stations.items():
                        try:
                            print(stn.get_full_report())
                        except Exception as e:
                            print(f"  {key}: Report error: {e}")
                continue

            # ── Fault effects counters ──
            if cmd.lower() == "fe":
                for line_id, stations in [("line1", fault_manager.l1),
                                          ("line2", fault_manager.l2)]:
                    print(f"\n  ⚡ {line_id.upper()} Fault Effect Counters:")
                    for key, stn in stations.items():
                        try:
                            fc = stn._fault_counters
                            counts = " ".join(
                                f"{k}={v}" for k, v in fc.items() if v > 0
                            )
                            if counts:
                                print(f"    {key:12s} │ {counts}")
                        except AttributeError:
                            pass
                print()
                continue

            # ── Catalog lookup ──
            if cmd.lower().startswith("cat "):
                stn_type = cmd[4:].strip()
                catalog = FAULT_CATALOG.get(stn_type)
                if not catalog:
                    print(f"  Unknown type. Available: "
                          f"{list(FAULT_CATALOG.keys())}")
                    continue
                print(f"\n  📖 FAULT CATALOG: {stn_type}")
                print(f"  {'─' * 60}")
                for fault_name, info in catalog.items():
                    print(f"  {fault_name}:")
                    print(f"    Cause: {info['real_cause'][:80]}...")
                    print(f"    MTBF:  {info['mtbf_hours']} hours")
                    for sev, details in info["severity_map"].items():
                        desc = details.get("description", "")
                        print(f"    Sev {sev}: {desc}")
                    print()
                continue

            # ── Scenario injection ──
            if cmd.lower().startswith("sc "):
                parts = cmd.split()
                if len(parts) < 3:
                    print("  Usage: sc <station_code> <fault_code> [severity]")
                    print("  Example: sc A 4 5  → both lines MC-A cnc_jam sev 5")
                    continue
                stn_code = parts[1].upper()
                fault_code = parts[2]
                sev = int(parts[3]) if len(parts) > 3 else 3
                stn_key = station_key_map.get(stn_code)
                fault_map = station_faults.get(stn_code, {})
                fault_type = fault_map.get(fault_code)
                if not stn_key or not fault_type:
                    print(f"  Invalid station '{stn_code}' or fault '{fault_code}'")
                    continue
                fault_manager.inject("line1", stn_key, fault_type, sev)
                fault_manager.inject("line2", stn_key, fault_type, sev)
                print(f"  ⚡ SCENARIO: {fault_type} sev {sev} → both lines {stn_key}")
                continue

            # ── Per-station fault injection: <line><station>f<fault> [sev] ──
            # Format: 1Af1 3  or  2 7f6  or  16f6 5
            try:
                parts = cmd.split()
                code = parts[0]
                sev = int(parts[1]) if len(parts) > 1 else 3

                if len(code) < 3:
                    print(f"  Unknown command: {cmd}")
                    print("  Type 'h' for help")
                    continue

                # Parse: first char = line, then station code, 'f', fault number
                line_num = code[0]
                if line_num not in ("1", "2"):
                    print(f"  Line must be 1 or 2, got '{line_num}'")
                    continue
                line_id = "line1" if line_num == "1" else "line2"

                # Find 'f' separator
                f_idx = code.find("f", 1)
                if f_idx < 0:
                    print(f"  No 'f' found in '{code}'. Format: <line><stn>f<fault>")
                    continue

                stn_code = code[1:f_idx].upper()
                fault_code = code[f_idx + 1:]

                stn_key = station_key_map.get(stn_code)
                if not stn_key:
                    print(f"  Unknown station code '{stn_code}'. "
                          f"Available: {list(station_key_map.keys())}")
                    continue

                fault_map = station_faults.get(stn_code, {})
                fault_type = fault_map.get(fault_code)
                if not fault_type:
                    print(f"  Unknown fault '{fault_code}' for station '{stn_code}'. "
                          f"Available: {fault_map}")
                    continue

                # Look up real cause from catalog for user feedback
                stn_type = fault_manager._station_type(stn_key)
                catalog = FAULT_CATALOG.get(stn_type, {}).get(fault_type, {})
                sev_info = catalog.get("severity_map", {}).get(sev, {})
                desc = sev_info.get("description", "")
                cause = catalog.get("real_cause", "")[:100]

                fault_manager.inject(line_id, stn_key, fault_type, sev)

                print(f"  ⚡ {line_id}/{stn_key}: {fault_type} severity {sev}")
                if desc:
                    print(f"     Effect: {desc}")
                if cause:
                    print(f"     Cause:  {cause}...")
                print()

            except (ValueError, IndexError) as e:
                print(f"  Parse error: {e}")
                print("  Format: <line><station>f<fault> [severity]")
                print("  Example: 1Af4 5  = Line1, MC-A, cnc_jam, severity 5")
            except Exception as e:
                print(f"  Error: {e}")

        except EOFError:
            break
        except KeyboardInterrupt:
            twin_sync.abort()
            for station, _ in all_threads:
                station.is_running = False
            break


# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    print()
    print("═" * 75)
    print("  📺 TWIN TV ASSEMBLY LINES — Real Fault Injection + MQTT Telemetry")
    print("  🔗 Two independent lines, shared Modbus, concurrent operation")
    print("  📦 Line 1: addresses 0-55  |  Line 2: addresses +100/+10")
    print("  🔄 Cross-line emitter sync: Barrier(4) for gap-free emission")
    print("  ⚡ Real industrial fault models with VISIBLE Factory I/O effects")
    print("  📡 MQTT telemetry: sensor data, faults, production events")
    print("═" * 75)
    print()

    # ─── Connect to Factory I/O ───
    client = FactoryModbusClient("127.0.0.1", 502)
    if not client.connect():
        logger.error("❌ Could not connect to Modbus server.")
        logger.error("   Make sure Factory I/O is running with Modbus server enabled")
        return

    modbus_wrapper = ThreadSafeModbus(client)
    logger.info("🔒 Thread-safe Modbus wrapper active")

    # ─── Optional MQTT ───
    mqtt_client = None
    mqtt_publisher = None
    try:
        from core.mqtt_client import MQTTClient
        mqtt_client = MQTTClient("twin_assembly_lines")
        if mqtt_client.connect():
            mqtt_publisher = MQTTTelemetryPublisher(mqtt_client)
            logger.info("✅ MQTT Connected — telemetry publishing active")
            logger.info("📡 MQTT Topics:")
            logger.info("   factory/line{1,2}/{station}/telemetry")
            logger.info("   factory/line{1,2}/{station}/status")
            logger.info("   factory/line{1,2}/{station}/faults/event")
            logger.info("   factory/line{1,2}/{station}/faults/detail")
            logger.info("   factory/line{1,2}/{station}/faults/inject")
            logger.info("   factory/line{1,2}/faults/inject  (line broadcast)")
            logger.info("   factory/faults/inject  (global broadcast)")
            logger.info("   factory/line{1,2}/production")
            logger.info("   factory/twin/summary")
        else:
            mqtt_client = None
            logger.info("⚠️  MQTT not available — faults via console only")
    except Exception:
        mqtt_client = None
        logger.info("⚠️  MQTT not available — faults via console only")

    # ─── Quick sensor tests ───
    print()
    for label, reg in [("Vision Sensor L1", 0), ("Vision Sensor L2", 10),
                       ("Crane Register L1", 0), ("Crane Register L2", 10)]:
        if "Vision" in label:
            val = client.read_register(reg)
        else:
            val = client.read_holding_register(reg)
        status = f"✅ OK (value: {val})" if val is not None else "⚠️  FAILED"
        logger.info(f"  {label} (reg {reg}): {status}")

    # ─── Create shared cross-line synchronizer ───
    twin_sync = TwinLineSynchronizer()
    logger.info("")
    logger.info("🔄 TwinLineSynchronizer: Barrier(4) for all MCs")
    logger.info("   Trigger: STN2 sensor_station (input 3 / input 103)")

    # ─── Spawn both lines ───
    logger.info("")
    logger.info("Creating Line 1 stations...")
    stations_l1_order, stations_l1_dict, _ = spawn_line(
        modbus_wrapper, mqtt_client, "LINE1",
        wait_to_emit_a=twin_sync.wait_l1_a,
        wait_to_emit_b=twin_sync.wait_l1_b,
        emit_trigger_fn=twin_sync.trigger_line1,
    )

    logger.info("Creating Line 2 stations...")
    stations_l2_order, stations_l2_dict, _ = spawn_line(
        modbus_wrapper, mqtt_client, "LINE2",
        wait_to_emit_a=twin_sync.wait_l2_a,
        wait_to_emit_b=twin_sync.wait_l2_b,
        emit_trigger_fn=twin_sync.trigger_line2,
    )

    # ─── Initialize transition belts ───
    init_transition_belts(modbus_wrapper, 0)
    init_transition_belts(modbus_wrapper, 100)

    # ─── Create fault injection manager ───
    fault_manager = FaultInjectionManager(
        stations_l1_dict, stations_l2_dict,
        mqtt_publisher=mqtt_publisher,
    )

    # Setup MQTT fault listeners (allows remote fault injection)
    if mqtt_client:
        fault_manager.setup_mqtt_listeners(mqtt_client)

    # ─── Create command handler (receives AI agent repair commands) ───
    command_handler = CommandHandler(
        stations_l1_dict, stations_l2_dict,
        mqtt_client=mqtt_client,
    )
    if mqtt_client:
        command_handler.setup_listeners(mqtt_client)
        logger.info("📡 Command handler: AI agent repair commands active")

    # ─── Create telemetry collector ───
    telemetry_collector = None
    if mqtt_publisher:
        telemetry_stations = {
            "line1": stations_l1_dict,
            "line2": stations_l2_dict,
        }
        telemetry_collector = TelemetryCollector(
            mqtt_publisher, telemetry_stations,
            interval=0.5, summary_interval=5.0,
        )
        telemetry_collector.start()
        logger.info("📊 Telemetry collector started (500ms interval)")

    # ─── Start ALL threads simultaneously ───
    all_threads = start_all_threads(stations_l1_order, stations_l2_order)

    print()
    print("═" * 75)
    print("  ✅ BOTH LINES RUNNING SIMULTANEOUSLY!")
    print("  🔄 Emitters synced: all 4 MCs rendezvous at Barrier(4)")
    print("  📡 MQTT telemetry publishing (if connected)")
    print("  ⚡ Type fault commands below or press Ctrl+C to stop")
    print("═" * 75)

    # ─── Interactive fault console ───
    try:
        fault_console(fault_manager, all_threads, twin_sync)
    except Exception as e:
        logger.error(f"Console error: {e}")

    # ─── Shutdown ───
    logger.info("🛑 Stopping all stations...")

    twin_sync.abort()

    for station, thread in all_threads:
        station.is_running = False

    for station, thread in all_threads:
        thread.join(timeout=5.0)

    # Stop telemetry
    if telemetry_collector:
        telemetry_collector.stop()

    # ─── Final reports ───
    print()
    print("═" * 75)
    print("  📊 FINAL REPORTS — BOTH LINES")
    print("═" * 75)

    for line_id, stations in [("LINE 1", stations_l1_dict),
                               ("LINE 2", stations_l2_dict)]:
        print(f"\n{'═' * 70}")
        print(f"  {line_id}")
        print(f"{'═' * 70}")
        for key, stn in stations.items():
            try:
                print(stn.get_full_report())
            except Exception as e:
                print(f"  {key}: {e}")

    # ─── Fault effect summary ───
    print()
    print("═" * 75)
    print("  ⚡ FAULT EFFECT SUMMARY — ALL STATIONS")
    print("═" * 75)
    for line_id, stations in [("LINE 1", stations_l1_dict),
                               ("LINE 2", stations_l2_dict)]:
        print(f"\n  {line_id}:")
        for key, stn in stations.items():
            try:
                fc = stn._fault_counters
                total = sum(fc.values())
                if total > 0:
                    counts = " | ".join(f"{k}={v}" for k, v in fc.items()
                                        if v > 0)
                    print(f"    {key:12s} │ total={total:4d} │ {counts}")
            except AttributeError:
                pass
    print()

    # Publish final summary via MQTT
    if mqtt_publisher:
        try:
            l1_stats = {k: s.get_status() for k, s in stations_l1_dict.items()}
            l2_stats = {k: s.get_status() for k, s in stations_l2_dict.items()}
            mqtt_publisher.publish("factory/twin/final_report", {
                "line1": l1_stats,
                "line2": l2_stats,
                "event": "shutdown",
            })
        except Exception:
            pass

    # ─── Cleanup ───
    logger.info("🧹 Cleaning up...")

    try:
        for offset in [0, 100]:
            for addr in [1, 10, 14, 20, 27]:
                modbus_wrapper.write_output(addr + offset, False)
        logger.info("  ✅ Transition belts OFF")
    except Exception:
        pass

    try:
        if mqtt_client:
            mqtt_client.disconnect()
            logger.info("  ✅ MQTT disconnected")
    except Exception:
        pass

    try:
        client.disconnect()
        logger.info("  ✅ Modbus disconnected")
    except Exception:
        pass

    logger.info("  Done! 👋")


if __name__ == "__main__":
    main()