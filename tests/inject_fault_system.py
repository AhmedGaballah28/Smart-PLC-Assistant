"""
Fault Injection Tool — ALL 3 STATIONS
======================================
REAL Factory I/O Effects — not just numbers!

Every fault causes VISIBLE changes you can SEE in Factory I/O:
  - Belts stop/stutter
  - Power brownouts (outputs go OFF)
  - Blade chatters (flips up/down)
  - Gripper drops lid mid-transfer
  - Positioner bar jams
  - Sensors give WRONG readings → wrong control decisions
  - Emergency stops (entire station goes DEAD)

Run this in a SEPARATE terminal while run_line.py is running.
Sends fault commands via MQTT → Station controllers trigger REAL Modbus writes.

REQUIREMENTS:
  - run_line.py must be running (with MQTT enabled)
  - Mosquitto MQTT broker must be running
  - Factory I/O must be running and connected
"""

import json
import time
import sys
import os
import logging
import threading
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

from core.mqtt_client import MQTTClient


# ═══════════════════════════════════════════════════════════════
# FAULT CATALOG — What each fault ACTUALLY DOES in Factory I/O
# ═══════════════════════════════════════════════════════════════

FAULT_CATALOG = {
    # ─────────────────────────────────────────────────────────
    # STATION 1: Chassis Loading & Inspection
    # ─────────────────────────────────────────────────────────
    "station_1": {
        "name": "Station 1 — Chassis Loading & Inspection",
        "emoji": "📦",
        "faults": {
            "overheat": {
                "name": "🔥 Motor Overheating",
                "description": "Belt motor overheats → belt physically STOPS",
                "effects": {
                    1: "Belt 1 stutters ~1 every 17s (0.4s stop)",
                    2: "Belt 1 stutters ~1 every 8s  (0.6s stop)",
                    3: "Belt 1 stutters ~1 every 6s  (0.8s stop)",
                    4: "🚨 EMERGENCY STOP — belt, emitter, blade ALL OFF!",
                    5: "🚨 EMERGENCY STOP — belt, emitter, blade ALL OFF!",
                },
                "what_you_see": [
                    "Belt 1 STOPS moving in Factory I/O (belt 1b stays ON)",
                    "Products pile up or stop mid-transport",
                    "At severity 4-5: EVERYTHING stops (except belt 1b)",
                ],
            },
            "vibration": {
                "name": "📳 Vibration Anomaly",
                "description": "Motor vibration → stop blade chatters physically",
                "effects": {
                    1: "Dashboard vibration rises (MQTT only)",
                    2: "Dashboard vibration rises (MQTT only)",
                    3: "Stop blade CHATTERS — flips up/down randomly!",
                    4: "Stop blade CHATTERS frequently — products may escape!",
                    5: "🚨 EMERGENCY STOP — everything OFF!",
                },
                "what_you_see": [
                    "Stop blade visibly flips up and down in Factory I/O",
                    "Products may slip past the blade during chatter",
                    "At severity 5: complete shutdown",
                ],
            },
            "power": {
                "name": "⚡ Power Fluctuation",
                "description": "Power supply unstable → random blackouts",
                "effects": {
                    1: "Random brownout (~0.7s) — belt, emitter, blade go OFF",
                    2: "Random brownout (~1.1s) — everything goes OFF",
                    3: "Random brownout (~1.5s) — everything goes OFF",
                    4: "Frequent brownouts (~1.9s) — very disruptive",
                    5: "🚨 TOTAL POWER FAILURE — line goes DEAD!",
                },
                "what_you_see": [
                    "ALL outputs suddenly go OFF in Factory I/O",
                    "Belt stops, emitter off, blade drops — then recovers",
                    "Belt 1b (transition) stays ON — it's on a separate circuit",
                    "At severity 5: permanent shutdown until cleared",
                ],
            },
            "belt_slip": {
                "name": "🔄 Belt Slippage",
                "description": "Belt mechanical slippage → stops randomly",
                "effects": {
                    1: "Belt 1 stops randomly (~0.3s pauses), speed 85%",
                    2: "Belt 1 stops randomly (~0.5s pauses), speed 70%",
                    3: "Belt 1 stops frequently (~0.6s), speed 55%",
                    4: "Belt 1 stops very often (~0.8s), speed 40%",
                    5: "Belt 1 stops constantly (~1.0s), speed 25%",
                },
                "what_you_see": [
                    "Belt 1 jerks — stops and starts in Factory I/O",
                    "Products move in bursts instead of smoothly",
                    "Cycle times increase noticeably",
                ],
            },
            "sensor_drift": {
                "name": "📡 Sensor Drift",
                "description": "Sensors give WRONG readings → wrong decisions",
                "effects": {
                    1: " 5% misread rate — occasional wrong belt/blade actions",
                    2: "10% misread rate — belt or blade act unexpectedly",
                    3: "15% misread rate — frequent wrong decisions",
                    4: "20% misread rate — very unreliable behavior",
                    5: "25% misread rate — nearly random control!",
                },
                "what_you_see": [
                    "Belt may stop when nothing is there",
                    "Blade may raise/lower at wrong times",
                    "Products may pass through without inspection",
                    "The station makes WRONG decisions you can SEE",
                ],
            },
        },
    },

    # ─────────────────────────────────────────────────────────
    # STATION 2: PCB Board Installation (Pick & Place)
    # ─────────────────────────────────────────────────────────
    "station_2": {
        "name": "Station 2 — PCB Installation (Pick & Place)",
        "emoji": "🤖",
        "faults": {
            "overheat": {
                "name": "🔥 Motor Overheating",
                "description": "Belt motor overheats → belt STOPS randomly",
                "effects": {
                    1: "Belt 2 stutters occasionally (0.4s stop)",
                    2: "Belt 2 stutters more often (0.6s stop)",
                    3: "Belt 2 stutters frequently (0.8s stop)",
                    4: "🚨 EMERGENCY STOP — belt, P&P, everything OFF!",
                    5: "🚨 EMERGENCY STOP — everything OFF!",
                },
                "what_you_see": [
                    "Belt 2 stops moving in Factory I/O",
                    "Products stop mid-transport to/from P&P",
                    "Pick & Place operations may fail",
                ],
            },
            "power": {
                "name": "⚡ Power Fluctuation",
                "description": "Power unstable → random blackouts hit P&P too",
                "effects": {
                    1: "Random brownout (~0.7s) — belt, P&P, blade go OFF",
                    2: "Random brownout (~1.1s) — everything goes OFF",
                    3: "Random brownout (~1.5s) — MID-OPERATION P&P stops!",
                    4: "Frequent brownouts (~1.9s) — P&P may drop lid!",
                    5: "🚨 TOTAL POWER FAILURE — station DEAD!",
                },
                "what_you_see": [
                    "ALL Station 2 outputs suddenly go OFF",
                    "Pick & Place FREEZES mid-motion",
                    "Gripper may release during brownout → lid drops!",
                    "Belt stops, blade drops, emitter off",
                ],
            },
            "belt_slip": {
                "name": "🔄 Belt Slippage",
                "description": "Belt slips → products don't reach P&P properly",
                "effects": {
                    1: "Belt 2 stops randomly (~0.3s), speed 85%",
                    2: "Belt 2 stops randomly (~0.5s), speed 70%",
                    3: "Belt 2 stops frequently (~0.6s), speed 55%",
                    4: "Belt 2 stops very often (~0.8s), speed 40%",
                    5: "Belt 2 stops constantly (~1.0s), speed 25%",
                },
                "what_you_see": [
                    "Belt 2 jerks and stutters in Factory I/O",
                    "Product may not reach the stop blade properly",
                    "P&P placement may be misaligned",
                ],
            },
            "sensor_drift": {
                "name": "📡 Sensor Drift",
                "description": "Sensors give wrong readings → P&P acts on bad data",
                "effects": {
                    1: " 5% misread — occasional wrong P&P trigger",
                    2: "10% misread — P&P may start without product",
                    3: "15% misread — frequent wrong P&P operations",
                    4: "20% misread — P&P very unreliable",
                    5: "25% misread — P&P operates nearly randomly!",
                },
                "what_you_see": [
                    "P&P may try to pick when nothing is there",
                    "Belt may stop/start at wrong times",
                    "Products may pass through without PCB installation",
                ],
            },
            "gripper": {
                "name": "🔧 Gripper Failure",
                "description": "P&P gripper loses grip → DROPS lid mid-transfer!",
                "effects": {
                    1: "Rare grip loss — lid occasionally falls",
                    2: "Occasional grip loss during transfer",
                    3: "Frequent grip loss — lids drop mid-air!",
                    4: "Very frequent — most lids get dropped!",
                    5: "Constant failure — gripper barely works!",
                },
                "what_you_see": [
                    "Gripper OPENS mid-transfer in Factory I/O!",
                    "Lid falls off the gripper visibly",
                    "Product exits Station 2 WITHOUT a PCB lid",
                    "Production quality drops dramatically",
                ],
            },
            "pp_jam": {
                "name": "🔩 Pick & Place Jam",
                "description": "P&P mechanical jam → EMERGENCY STOP immediately!",
                "effects": {
                    1: "🚨 EMERGENCY STOP — P&P axis jammed!",
                    2: "🚨 EMERGENCY STOP — P&P axis jammed!",
                    3: "🚨 EMERGENCY STOP — P&P axis jammed!",
                    4: "🚨 EMERGENCY STOP — P&P axis jammed!",
                    5: "🚨 EMERGENCY STOP — P&P axis jammed!",
                },
                "what_you_see": [
                    "ALL Station 2 outputs go OFF immediately",
                    "Pick & Place FREEZES wherever it is",
                    "Belt stops, blade drops, gripper may open",
                    "Station is DEAD until fault is cleared",
                    "⚠️ ANY severity = immediate emergency stop!",
                ],
            },
        },
    },

    # ─────────────────────────────────────────────────────────
    # STATION 3: Display Panel Mounting
    # ─────────────────────────────────────────────────────────
    "station_3": {
        "name": "Station 3 — Display Panel Mounting",
        "emoji": "📺",
        "faults": {
            "overheat": {
                "name": "🔥 Motor Overheating",
                "description": "Belt motor overheats → belt STOPS randomly",
                "effects": {
                    1: "Belt 3 stutters occasionally (0.4s stop)",
                    2: "Belt 3 stutters more often (0.6s stop)",
                    3: "Belt 3 stutters frequently (0.8s stop)",
                    4: "🚨 EMERGENCY STOP — belt, positioner OFF!",
                    5: "🚨 EMERGENCY STOP — everything OFF!",
                },
                "what_you_see": [
                    "Belt 3 stops moving in Factory I/O",
                    "Products stop before/after the positioner",
                    "Mounting cycle gets interrupted",
                ],
            },
            "power": {
                "name": "⚡ Power Fluctuation",
                "description": "Power unstable → positioner may release mid-mount!",
                "effects": {
                    1: "Random brownout (~0.7s) — belt, positioner go OFF",
                    2: "Random brownout (~1.1s) — everything goes OFF",
                    3: "Random brownout (~1.5s) — MID-MOUNT positioner opens!",
                    4: "Frequent brownouts (~1.9s) — mounting fails often!",
                    5: "🚨 TOTAL POWER FAILURE — station DEAD!",
                },
                "what_you_see": [
                    "ALL Station 3 outputs suddenly go OFF",
                    "Positioner RELEASES product during mounting!",
                    "Product may shift position → bad mount",
                    "Belt stops, clamp opens, bar drops",
                ],
            },
            "belt_slip": {
                "name": "🔄 Belt Slippage",
                "description": "Belt slips → products don't reach positioner",
                "effects": {
                    1: "Belt 3 stops randomly (~0.3s), speed 85%",
                    2: "Belt 3 stops randomly (~0.5s), speed 70%",
                    3: "Belt 3 stops frequently (~0.6s), speed 55%",
                    4: "Belt 3 stops very often (~0.8s), speed 40%",
                    5: "Belt 3 stops constantly (~1.0s), speed 25%",
                },
                "what_you_see": [
                    "Belt 3 jerks in Factory I/O",
                    "Product may not reach the positioner bar",
                    "Extra mounting time added to compensate",
                ],
            },
            "sensor_drift": {
                "name": "📡 Sensor Drift",
                "description": "Sensor 5 gives wrong readings → bad clamp timing",
                "effects": {
                    1: " 5% misread — occasional wrong clamp timing",
                    2: "10% misread — clamp triggers without product",
                    3: "15% misread — positioner acts unpredictably",
                    4: "20% misread — very unreliable mounting",
                    5: "25% misread — nearly random behavior!",
                },
                "what_you_see": [
                    "Positioner may clamp on empty belt",
                    "Product may pass through WITHOUT mounting",
                    "Belt may stop/start at wrong times",
                    "Clamp/raise sequence fires incorrectly",
                ],
            },
            "positioner_jam": {
                "name": "🔩 Positioner Bar Jam",
                "description": "Positioning bar mechanism jams!",
                "effects": {
                    1: "Clamp/raise takes 0.5s extra (visible delay)",
                    2: "Clamp/raise takes 1.0s extra (noticeable)",
                    3: "Clamp/raise takes 1.5s extra (slow operation)",
                    4: "🚨 EMERGENCY STOP — bar mechanism jammed!",
                    5: "🚨 EMERGENCY STOP — bar mechanism jammed!",
                },
                "what_you_see": [
                    "Positioner bar moves SLOWER than normal",
                    "Visible delay between clamp/raise commands",
                    "Cycle time increases noticeably",
                    "At severity 4-5: station goes DEAD",
                ],
            },
        },
    },
}

SEVERITY_LABELS = {
    1: "Minor      (rare, small effect)",
    2: "Low        (occasional effect)",
    3: "Medium     (frequent, noticeable)",
    4: "High ⚠️     (very frequent / EMERGENCY)",
    5: "CRITICAL 🚨 (constant / EMERGENCY STOP)",
}

SEVERITY_COLORS = {
    1: "",
    2: "",
    3: "⚠️ ",
    4: "⚠️⚠️ ",
    5: "🚨🚨🚨 ",
}


# ═══════════════════════════════════════════════════════════════
# LIVE EFFECTS MONITOR — Shows real-time fault effects
# ═══════════════════════════════════════════════════════════════

class LiveEffectsMonitor:
    """
    Subscribes to MQTT topics from all 3 stations.
    Prints real-time fault effects as they happen in Factory I/O.
    """

    def __init__(self, mqtt: MQTTClient):
        self.mqtt = mqtt
        self._station_status = {}
        self._effect_count = 0
        self._lock = threading.Lock()

        # Subscribe to all stations
        for stn_num in range(1, 4):
            mqtt.subscribe(
                f"factory/station{stn_num}/status",
                lambda topic, data, n=stn_num: self._on_status(n, data),
            )
            mqtt.subscribe(
                f"factory/station{stn_num}/fault_effect",
                lambda topic, data, n=stn_num: self._on_effect(n, data),
            )
            mqtt.subscribe(
                f"factory/station{stn_num}/emergency",
                lambda topic, data, n=stn_num: self._on_emergency(n, data),
            )
            mqtt.subscribe(
                f"factory/station{stn_num}/fault_injected",
                lambda topic, data, n=stn_num: self._on_injected(n, data),
            )
            mqtt.subscribe(
                f"factory/station{stn_num}/fault_cleared",
                lambda topic, data, n=stn_num: self._on_cleared(n, data),
            )

    def _parse(self, data):
        if isinstance(data, str):
            return json.loads(data)
        return data if isinstance(data, dict) else {}

    def _on_status(self, station_num: int, data):
        with self._lock:
            self._station_status[station_num] = self._parse(data)

    def _on_effect(self, station_num: int, data):
        """Print real-time fault effects as they happen."""
        data = self._parse(data)
        self._effect_count += 1

        effect = data.get("effect", "?")
        reason = data.get("reason", "")
        duration = data.get("duration", 0)
        writes = data.get("real_modbus_writes", [])
        belt1b = data.get("belt1b", "")

        print()
        print(f"  ⚡ ──── REAL EFFECT #{self._effect_count} "
              f"(Station {station_num}) ────")
        print(f"  ⚡ Type:     {effect}"
              f"{f' ({reason})' if reason else ''}")
        print(f"  ⚡ Duration: {duration:.2f}s")
        print(f"  ⚡ Modbus:   {', '.join(writes)}")
        if belt1b:
            print(f"  ⚡ Belt 1b:  {belt1b}")
        print(f"  ⚡ ─────────────────────────────────────────")
        print()

    def _on_emergency(self, station_num: int, data):
        data = self._parse(data)
        if not data.get("active"):
            return

        reason = data.get("reason", "?")
        details = data.get("details", "")
        writes = data.get("real_modbus_writes", [])

        print()
        print("  🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨")
        print(f"  🚨  EMERGENCY STOP — STATION {station_num}!")
        print(f"  🚨  Reason:  {reason}")
        print(f"  🚨  Details: {details}")
        print(f"  🚨  Modbus:  {', '.join(writes)}")
        print(f"  🚨")
        print(f"  🚨  Factory I/O: Station {station_num} is DEAD!")
        print(f"  🚨  Type 'c' or 'c{station_num}' to clear and resume")
        print("  🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨")
        print()

    def _on_injected(self, station_num: int, data):
        data = self._parse(data)
        real = data.get("real_effects", False)
        fault = data.get("fault_type", "?")
        sev = data.get("severity", "?")
        if real:
            print(f"  ✅ Station {station_num} confirmed: "
                  f"{fault}(sev={sev}) → REAL effects active")

    def _on_cleared(self, station_num: int, data):
        data = self._parse(data)
        fault = data.get("fault_type", "?")
        print(f"  ✅ Station {station_num}: {fault} CLEARED — resuming")

    def get_status(self, station_num: int) -> dict:
        with self._lock:
            return self._station_status.get(station_num, {})

    def get_all_status(self) -> dict:
        with self._lock:
            return dict(self._station_status)


# ═══════════════════════════════════════════════════════════════
# SCENARIO PRESETS — Pre-built fault combinations
# ═══════════════════════════════════════════════════════════════

SCENARIOS = {
    "cascade": {
        "name": "🌊 Cascading Power Failure",
        "description": "Power problems spread from Station 1 → 2 → 3",
        "steps": [
            {"delay": 0, "station": "station_1", "fault": "power", "severity": 2},
            {"delay": 3, "station": "station_2", "fault": "power", "severity": 3},
            {"delay": 3, "station": "station_3", "fault": "power", "severity": 3},
        ],
    },
    "overheat": {
        "name": "🔥 Line-Wide Overheating",
        "description": "All motors overheat simultaneously",
        "steps": [
            {"delay": 0, "station": "station_1", "fault": "overheat", "severity": 3},
            {"delay": 0, "station": "station_2", "fault": "overheat", "severity": 3},
            {"delay": 0, "station": "station_3", "fault": "overheat", "severity": 3},
        ],
    },
    "sensor_chaos": {
        "name": "📡 Sensor Chaos",
        "description": "All sensors drift → stations make wrong decisions",
        "steps": [
            {"delay": 0, "station": "station_1", "fault": "sensor_drift", "severity": 3},
            {"delay": 0, "station": "station_2", "fault": "sensor_drift", "severity": 3},
            {"delay": 0, "station": "station_3", "fault": "sensor_drift", "severity": 3},
        ],
    },
    "mechanical": {
        "name": "🔩 Mechanical Failures",
        "description": "Station-specific mechanical failures",
        "steps": [
            {"delay": 0, "station": "station_1", "fault": "vibration", "severity": 4},
            {"delay": 2, "station": "station_2", "fault": "gripper", "severity": 3},
            {"delay": 2, "station": "station_3", "fault": "positioner_jam", "severity": 3},
        ],
    },
    "total_meltdown": {
        "name": "💥 Total Meltdown",
        "description": "EVERYTHING fails — all stations emergency stop!",
        "steps": [
            {"delay": 0, "station": "station_1", "fault": "power", "severity": 5},
            {"delay": 0, "station": "station_2", "fault": "pp_jam", "severity": 5},
            {"delay": 0, "station": "station_3", "fault": "power", "severity": 5},
        ],
    },
    "gradual": {
        "name": "📈 Gradual Degradation",
        "description": "Problems slowly build up across the line",
        "steps": [
            {"delay": 0,  "station": "station_1", "fault": "belt_slip", "severity": 1},
            {"delay": 5,  "station": "station_2", "fault": "sensor_drift", "severity": 1},
            {"delay": 5,  "station": "station_3", "fault": "belt_slip", "severity": 2},
            {"delay": 5,  "station": "station_1", "fault": "overheat", "severity": 2},
            {"delay": 5,  "station": "station_2", "fault": "gripper", "severity": 2},
            {"delay": 5,  "station": "station_3", "fault": "overheat", "severity": 3},
        ],
    },
    "gripper_hell": {
        "name": "🔧 Gripper From Hell",
        "description": "Station 2 gripper fails + sensors drift everywhere",
        "steps": [
            {"delay": 0, "station": "station_2", "fault": "gripper", "severity": 4},
            {"delay": 2, "station": "station_2", "fault": "sensor_drift", "severity": 2},
            {"delay": 2, "station": "station_1", "fault": "sensor_drift", "severity": 2},
        ],
    },
    "brownout_storm": {
        "name": "⚡ Brownout Storm",
        "description": "All stations suffer power brownouts",
        "steps": [
            {"delay": 0, "station": "station_1", "fault": "power", "severity": 3},
            {"delay": 1, "station": "station_2", "fault": "power", "severity": 3},
            {"delay": 1, "station": "station_3", "fault": "power", "severity": 3},
        ],
    },
}


# ═══════════════════════════════════════════════════════════════
# DISPLAY HELPERS
# ═══════════════════════════════════════════════════════════════

def print_main_menu():
    print()
    print("═" * 72)
    print("  🧪 FAULT INJECTION TOOL — ALL 3 STATIONS ⚡")
    print("  📺 TV Assembly Line — REAL Factory I/O Effects!")
    print("═" * 72)
    print()
    print("  INJECT FAULTS BY STATION:")
    print("  ────────────────────────────────────────────────────────────")
    print("  Station 1 (📦 Chassis):     Station 2 (🤖 PCB P&P):")
    print("    1.1 [sev] Overheat          2.1 [sev] Overheat")
    print("    1.2 [sev] Vibration         2.2 [sev] Power")
    print("    1.3 [sev] Power             2.3 [sev] Belt Slip")
    print("    1.4 [sev] Belt Slip         2.4 [sev] Sensor Drift")
    print("    1.5 [sev] Sensor Drift      2.5 [sev] Gripper Fail ⚡")
    print("                                2.6 [sev] P&P Jam 🚨")
    print()
    print("  Station 3 (📺 Display):      SCENARIOS (pre-built combos):")
    print("    3.1 [sev] Overheat          sc cascade    — Power cascade")
    print("    3.2 [sev] Power             sc overheat   — Line overheating")
    print("    3.3 [sev] Belt Slip         sc sensor     — Sensor chaos")
    print("    3.4 [sev] Sensor Drift      sc mechanical — Mechanical fails")
    print("    3.5 [sev] Positioner Jam    sc meltdown   — TOTAL meltdown!")
    print("                                sc gradual    — Slow degradation")
    print("                                sc gripper    — Gripper from hell")
    print("                                sc brownout   — Brownout storm")
    print()
    print("  CONTROLS:")
    print("  ────────────────────────────────────────────────────────────")
    print("  c        Clear ALL faults (all stations)")
    print("  c1/c2/c3 Clear faults on specific station")
    print("  s        Show status of all stations")
    print("  e        Show fault effects summary")
    print("  d X.Y    Describe what a fault REALLY does")
    print("  h        Show this menu")
    print("  q        Quit")
    print()
    print("  SEVERITY: 1-5 (default=3)")
    print("    1=Minor  2=Low  3=Medium  4=High⚠️  5=CRITICAL🚨")
    print()
    print("  EXAMPLES:")
    print("    1.3 4     → Station 1 power fault, severity 4 (brownouts)")
    print("    2.5 3     → Station 2 gripper failure, severity 3")
    print("    3.5 2     → Station 3 positioner jam, severity 2")
    print("    sc cascade → Run cascading power failure scenario")
    print("    c          → Clear everything, resume normal operation")
    print()


def print_station_status(monitor: LiveEffectsMonitor, station_num: int):
    """Print detailed status for one station."""
    s = monitor.get_status(station_num)
    if not s:
        print(f"  ⚠️  Station {station_num}: No status received yet")
        return

    catalog = FAULT_CATALOG.get(f"station_{station_num}", {})
    emoji = catalog.get("emoji", "?")
    name = catalog.get("name", f"Station {station_num}")

    state = s.get("state", "?")
    sensors = s.get("sensors", {})
    faults = s.get("faults", {})
    fx = s.get("fault_effects", {})
    counters = fx.get("counters", {})
    cnts = s.get("counters", {})

    print(f"  ┌──── {emoji} {name} ────")
    print(f"  │ State: {state}")

    if s.get("emergency_active"):
        reason = s.get("emergency_reason", "?")[:50]
        print(f"  │ 🚨 EMERGENCY: {reason}")

    print(f"  │ Temp: {sensors.get('motor_temperature', '?'):>6}°C"
          f"   Vibr: {sensors.get('vibration', '?'):>6} mm/s")
    print(f"  │ Power: {sensors.get('power_consumption', '?'):>5} kW"
          f"   Belt: {sensors.get('belt_speed', '?'):>5}%")

    # P&P info for Station 2
    pp = s.get("pick_and_place", {})
    if pp:
        print(f"  │ P&P: phase={pp.get('phase', '?')}"
              f"  item={pp.get('has_item', '?')}")

    # Positioner info for Station 3
    pos = s.get("positioning_bar", {})
    if pos:
        print(f"  │ Bar: clamped={pos.get('clamped', '?')}"
              f"  raised={pos.get('raised', '?')}")

    if faults.get("has_fault"):
        active = faults.get("active_faults", [])
        print(f"  │ ⚠️ FAULTS ({len(active)}):")
        for f in active:
            print(f"  │   • {f}")
    else:
        print(f"  │ ✅ No active faults")

    # Show real effect counters if any
    has_effects = any(
        v > 0 for k, v in counters.items()
        if isinstance(v, (int, float)) and k != "total_fault_downtime"
    )
    if has_effects:
        parts = []
        for key in ["stutters", "brownouts", "blade_chatters",
                     "gripper_failures", "positioner_jams",
                     "emergency_stops", "sensor_misreads"]:
            val = counters.get(key, 0)
            if val > 0:
                short = key.replace("_", "")[:6]
                parts.append(f"{short}={val}")
        downtime = counters.get("total_fault_downtime", 0)
        print(f"  │ ⚡ Effects: {', '.join(parts)}"
              f"  down={downtime:.1f}s")

    completed = cnts.get("products_completed", 0)
    failed = cnts.get("products_failed", 0)
    print(f"  │ Products: {completed} done, {failed} failed")
    print(f"  └────────────────────────────────────────────")


# ═══════════════════════════════════════════════════════════════
# FAULT COMMAND MAPPING
# ═══════════════════════════════════════════════════════════════

# Maps "X.Y" → (station, fault_type)
FAULT_COMMANDS = {
    # Station 1
    "1.1": ("station_1", "overheat"),
    "1.2": ("station_1", "vibration"),
    "1.3": ("station_1", "power"),
    "1.4": ("station_1", "belt_slip"),
    "1.5": ("station_1", "sensor_drift"),
    # Station 2
    "2.1": ("station_2", "overheat"),
    "2.2": ("station_2", "power"),
    "2.3": ("station_2", "belt_slip"),
    "2.4": ("station_2", "sensor_drift"),
    "2.5": ("station_2", "gripper"),
    "2.6": ("station_2", "pp_jam"),
    # Station 3
    "3.1": ("station_3", "overheat"),
    "3.2": ("station_3", "power"),
    "3.3": ("station_3", "belt_slip"),
    "3.4": ("station_3", "sensor_drift"),
    "3.5": ("station_3", "positioner_jam"),
}

SCENARIO_ALIASES = {
    "cascade": "cascade",
    "overheat": "overheat",
    "sensor": "sensor_chaos",
    "sensor_chaos": "sensor_chaos",
    "mechanical": "mechanical",
    "meltdown": "total_meltdown",
    "total_meltdown": "total_meltdown",
    "gradual": "gradual",
    "gripper": "gripper_hell",
    "gripper_hell": "gripper_hell",
    "brownout": "brownout_storm",
    "brownout_storm": "brownout_storm",
}


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    print_main_menu()

    # ─── Connect MQTT ───
    mqtt = MQTTClient("fault_injector_v2")
    if not mqtt.connect():
        print("  ❌ Cannot connect to MQTT broker!")
        print("  Make sure Mosquitto is running:")
        print("    Windows: net start mosquitto")
        print("    Linux:   sudo systemctl start mosquitto")
        sys.exit(1)
    print("  ✅ Connected to MQTT broker")

    # ─── Start live effects monitor ───
    monitor = LiveEffectsMonitor(mqtt)
    print("  📡 Listening for real-time effects from all 3 stations...")
    print()

    # Give MQTT subscriptions time to establish
    time.sleep(0.5)

    # ─── Scenario runner (for delayed steps) ───
    scenario_thread = None
    scenario_stop = threading.Event()

    def run_scenario(scenario_key: str):
        """Run a fault scenario with timed steps."""
        scenario = SCENARIOS[scenario_key]
        steps = scenario["steps"]

        print()
        print(f"  🎬 ═══════════════════════════════════════════════════")
        print(f"  🎬 SCENARIO: {scenario['name']}")
        print(f"  🎬 {scenario['description']}")
        print(f"  🎬 Steps: {len(steps)}")
        print(f"  🎬 ═══════════════════════════════════════════════════")

        for i, step in enumerate(steps):
            if scenario_stop.is_set():
                print(f"  🎬 Scenario ABORTED")
                return

            delay = step["delay"]
            if delay > 0:
                print(f"  🎬 ... waiting {delay}s before next step ...")
                for _ in range(int(delay * 10)):
                    if scenario_stop.is_set():
                        print(f"  🎬 Scenario ABORTED")
                        return
                    time.sleep(0.1)

            station = step["station"]
            fault = step["fault"]
            severity = step["severity"]

            stn_num = int(station.split("_")[1])
            catalog = FAULT_CATALOG[station]["faults"][fault]

            print()
            print(f"  🎬 Step {i+1}/{len(steps)}: "
                  f"Station {stn_num} → {catalog['name']} "
                  f"(severity {severity})")
            print(f"  🎬 Effect: {catalog['effects'][severity]}")

            mqtt.publish("factory/faults/inject", {
                "action": "inject",
                "station": station,
                "fault_type": fault,
                "severity": severity,
                "timestamp": datetime.now().isoformat(),
            })

        print()
        print(f"  🎬 ═══════════════════════════════════════════════════")
        print(f"  🎬 SCENARIO COMPLETE — all faults injected!")
        print(f"  🎬 Watch Factory I/O for REAL effects!")
        print(f"  🎬 Type 'c' to clear all faults when done")
        print(f"  🎬 ═══════════════════════════════════════════════════")
        print()

    try:
        while True:
            try:
                cmd = input("  🧪 > ").strip()
            except EOFError:
                break

            if not cmd:
                continue

            parts = cmd.split()
            base = parts[0].lower()

            # ─── QUIT ───
            if base == "q":
                print("  Clearing faults and exiting...")
                mqtt.publish("factory/faults/inject", {
                    "action": "clear",
                    "station": "station_1",
                    "fault_type": "all",
                })
                mqtt.publish("factory/faults/inject", {
                    "action": "clear",
                    "station": "station_2",
                    "fault_type": "all",
                })
                mqtt.publish("factory/faults/inject", {
                    "action": "clear",
                    "station": "station_3",
                    "fault_type": "all",
                })
                time.sleep(0.5)
                break

            # ─── HELP ───
            elif base == "h":
                print_main_menu()

            # ─── CLEAR ALL ───
            elif base == "c":
                scenario_stop.set()
                for stn in ["station_1", "station_2", "station_3"]:
                    mqtt.publish("factory/faults/inject", {
                        "action": "clear",
                        "station": stn,
                        "fault_type": "all",
                    })
                print()
                print("  ✅ Clear ALL faults sent to ALL stations!")
                print("  ✅ Emergency stops will be cleared")
                print("  ✅ All stations will resume normal operation")
                print()
                scenario_stop.clear()

            # ─── CLEAR SPECIFIC STATION ───
            elif base in ("c1", "c2", "c3"):
                stn_num = base[1]
                mqtt.publish("factory/faults/inject", {
                    "action": "clear",
                    "station": f"station_{stn_num}",
                    "fault_type": "all",
                })
                print(f"  ✅ Cleared all faults on Station {stn_num}")

            # ─── STATUS ───
            elif base == "s":
                print()
                for stn_num in range(1, 4):
                    print_station_status(monitor, stn_num)
                print()

            # ─── EFFECTS SUMMARY ───
            elif base == "e":
                print()
                print("  ⚡ REAL FAULT EFFECTS ACROSS ALL STATIONS:")
                print("  ─────────────────────────────────────────────")
                for stn_num in range(1, 4):
                    s = monitor.get_status(stn_num)
                    if not s:
                        print(f"  Station {stn_num}: No data")
                        continue
                    fx = s.get("fault_effects", {})
                    counters = fx.get("counters", {})
                    events = fx.get("recent_events", [])

                    parts_list = []
                    for key in ["stutters", "brownouts", "blade_chatters",
                                "gripper_failures", "positioner_jams",
                                "emergency_stops", "sensor_misreads"]:
                        val = counters.get(key, 0)
                        if val > 0:
                            parts_list.append(f"{key}={val}")
                    downtime = counters.get("total_fault_downtime", 0)

                    if parts_list or downtime > 0:
                        print(f"  Station {stn_num}: "
                              f"{', '.join(parts_list)}"
                              f"  downtime={downtime:.1f}s")
                    else:
                        print(f"  Station {stn_num}: No effects yet")

                    if events:
                        for ev in events[-3:]:
                            t = ev.get("time", "?")
                            if "T" in str(t):
                                t = t.split("T")[1][:8]
                            print(f"    {t} │ {ev.get('type', '?')}: "
                                  f"{ev.get('details', '')}")
                print()

            # ─── DESCRIBE FAULT ───
            elif base == "d" and len(parts) >= 2:
                fault_key = parts[1]
                if fault_key in FAULT_COMMANDS:
                    station, fault_type = FAULT_COMMANDS[fault_key]
                    catalog = FAULT_CATALOG[station]["faults"][fault_type]
                    stn_name = FAULT_CATALOG[station]["name"]

                    print()
                    print(f"  ┌──── {catalog['name']} ────")
                    print(f"  │ Station: {stn_name}")
                    print(f"  │")
                    print(f"  │ {catalog['description']}")
                    print(f"  │")
                    print(f"  │ EFFECTS BY SEVERITY:")
                    for sev in range(1, 6):
                        print(f"  │   {sev}: {catalog['effects'][sev]}")
                    print(f"  │")
                    print(f"  │ WHAT YOU SEE IN FACTORY I/O:")
                    for line in catalog["what_you_see"]:
                        print(f"  │   → {line}")
                    print(f"  └────────────────────────────────────────")
                    print()
                else:
                    print(f"  ❌ Unknown fault: {fault_key}")
                    print(f"  Use format: d X.Y  (e.g., d 1.3, d 2.5)")

            # ─── SCENARIOS ───
            elif base == "sc" and len(parts) >= 2:
                scenario_name = parts[1].lower()
                scenario_key = SCENARIO_ALIASES.get(scenario_name)

                if scenario_key and scenario_key in SCENARIOS:
                    scenario_stop.clear()
                    scenario_thread = threading.Thread(
                        target=run_scenario,
                        args=(scenario_key,),
                        daemon=True,
                    )
                    scenario_thread.start()
                else:
                    print(f"  ❌ Unknown scenario: {scenario_name}")
                    print(f"  Available: {', '.join(SCENARIO_ALIASES.keys())}")

            # ─── INJECT FAULT ───
            elif base in FAULT_COMMANDS:
                station, fault_type = FAULT_COMMANDS[base]
                severity = int(parts[1]) if len(parts) > 1 else 3
                severity = max(1, min(5, severity))

                stn_num = int(station.split("_")[1])
                catalog = FAULT_CATALOG[station]["faults"][fault_type]
                effect_desc = catalog["effects"][severity]
                sev_label = SEVERITY_LABELS[severity]

                # Send via MQTT
                mqtt.publish("factory/faults/inject", {
                    "action": "inject",
                    "station": station,
                    "fault_type": fault_type,
                    "severity": severity,
                    "timestamp": datetime.now().isoformat(),
                })

                print()
                print(f"  🚨 ═══════════════════════════════════════════")
                print(f"  🚨 FAULT INJECTED → Station {stn_num}!")
                print(f"  🚨")
                print(f"  🚨 Type:     {catalog['name']}")
                print(f"  🚨 Severity: {severity}/5 ({sev_label})")
                print(f"  🚨")
                print(f"  🚨 ⚡ REAL EFFECT in Factory I/O:")
                print(f"  🚨 {effect_desc}")

                # Show what you'll see
                print(f"  🚨")
                print(f"  🚨 👁️ WATCH FOR:")
                for line in catalog["what_you_see"][:3]:
                    print(f"  🚨   → {line}")

                if severity >= 4:
                    print(f"  🚨")
                    print(f"  🚨 ⚠️  HIGH SEVERITY — may cause EMERGENCY STOP!")
                    print(f"  🚨 ⚠️  Type 'c' or 'c{stn_num}' to clear")

                print(f"  🚨 ═══════════════════════════════════════════")
                print()

            else:
                print(f"  ❌ Unknown command: {cmd}")
                print(f"  Type 'h' for help")

    except KeyboardInterrupt:
        print("\n  Clearing faults and exiting...")
        for stn in ["station_1", "station_2", "station_3"]:
            mqtt.publish("factory/faults/inject", {
                "action": "clear",
                "station": stn,
                "fault_type": "all",
            })
        time.sleep(0.3)

    finally:
        scenario_stop.set()
        try:
            mqtt.disconnect()
        except Exception:
            pass
        print("  Done!")


if __name__ == "__main__":
    main()