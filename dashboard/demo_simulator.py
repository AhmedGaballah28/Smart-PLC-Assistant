"""
Demo Simulator — generates realistic live data without Factory I/O hardware.
Used by dashboard pages when MQTT / Factory I/O is not connected.
"""

import time
import math
import random
import threading
from datetime import datetime
from typing import Dict, List


STATION_DEFS = [
    {"id": "station_1", "name": "Chassis Loading",       "cycle": 6},
    {"id": "station_2", "name": "PCB Installation",      "cycle": 15},
    {"id": "station_3", "name": "Display Panel Mount",   "cycle": 8},
    {"id": "station_4", "name": "Wiring Connection",     "cycle": 5},
    {"id": "station_5", "name": "Back Cover Assembly",   "cycle": 7},
    {"id": "station_6", "name": "Quality Control",       "cycle": 6},
    {"id": "station_7", "name": "Sorting & Output",      "cycle": 4},
]

STATES_CYCLE = [
    "s_wait_product", "s_arrived", "s_processing",
    "s_releasing", "s_exit", "s_wait_product",
]


class StationSimulator:
    def __init__(self, defn: dict):
        self.station_id = defn["id"]
        self.name = defn["name"]
        self.cycle_time = defn["cycle"]
        self._start = time.time() + random.uniform(0, defn["cycle"])
        self._products = random.randint(0, 20)
        self._pass = 0
        self._fail = 0
        self._faults: List[str] = []
        self._temperature = random.uniform(24, 32)
        self._vibration = random.uniform(3, 8)
        self._power = random.uniform(0.6, 2.0)

    def _phase(self) -> float:
        return ((time.time() - self._start) % self.cycle_time) / self.cycle_time

    def get_state(self) -> str:
        idx = int(self._phase() * (len(STATES_CYCLE) - 1))
        return STATES_CYCLE[min(idx, len(STATES_CYCLE) - 1)]

    def tick(self):
        """Advance simulator one tick (call ~1/s)."""
        p = self._phase()
        # Complete a cycle
        if p < 0.02:
            self._products += 1
            result = random.random()
            if result > 0.05:
                self._pass += 1
            else:
                self._fail += 1

        # Realistic sensor drift
        self._temperature += random.gauss(0, 0.3)
        self._temperature = max(22, min(55 + (10 if self._faults else 0), self._temperature))
        self._vibration  += random.gauss(0, 0.5)
        self._vibration   = max(1, min(40 + (20 if self._faults else 0), self._vibration))
        self._power      += random.gauss(0, 0.05)
        self._power       = max(0.1, min(4.5, self._power))

    def inject_fault(self, fault_type: str):
        if fault_type not in self._faults:
            self._faults.append(fault_type)

    def clear_faults(self):
        self._faults = []

    def get_status(self) -> dict:
        state = self.get_state()
        oee = round(random.uniform(72, 94), 1) if not self._faults else round(random.uniform(50, 70), 1)
        return {
            "station": self.station_id,
            "name": self.name,
            "state": state,
            "is_running": True,
            "emergency_active": False,
            "emergency_reason": "",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "sensors": {
                "temperature": round(self._temperature, 1),
                "vibration":   round(self._vibration, 1),
                "power_kw":    round(self._power, 2),
                "belt_speed_pct": round(90 + random.gauss(0, 3), 1),
            },
            "counters": {
                "products_completed": self._products,
                "avg_cycle_time": round(self.cycle_time + random.gauss(0, 0.5), 1),
                "oee": oee,
            },
            "faults": {
                "has_fault": bool(self._faults),
                "active": list(self._faults),
            },
        }


class DemoSimulator:
    """
    Runs all 7 station simulators in a background thread.
    Dashboard pages call get_all_states() / get_alerts() to read data.
    """

    def __init__(self):
        self._stations = {d["id"]: StationSimulator(d) for d in STATION_DEFS}
        self._alerts: List[Dict] = []
        self._diagnoses: List[Dict] = []
        self._proposals: List[Dict] = []
        self._lock = threading.Lock()
        self._alert_counter = 0
        self._diag_counter = 0
        self._running = False
        self._thread = None
        self._start_time = time.time()

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            with self._lock:
                for s in self._stations.values():
                    s.tick()
                # Random alert every ~30s
                if random.random() < 0.033:
                    self._emit_random_alert()
            time.sleep(1.0)

    def _emit_random_alert(self):
        stn = random.choice(list(self._stations.values()))
        metric = random.choice(["temperature", "vibration", "power_kw"])
        level = random.choice(["WARNING", "CRITICAL"])
        self._alert_counter += 1
        alert = {
            "alert_id": f"ALT-{self._alert_counter:04d}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "station_id": stn.station_id,
            "station_name": stn.name,
            "alert_type": "sensor_threshold",
            "level": level,
            "metric": metric,
            "value": round(stn._temperature if metric == "temperature" else
                           stn._vibration   if metric == "vibration" else stn._power, 1),
            "threshold": 50 if metric == "temperature" else (30 if metric == "vibration" else 4.0),
            "unit": "°C" if metric == "temperature" else ("mm/s" if metric == "vibration" else "kW"),
            "sensor_snapshot": stn.get_status()["sensors"],
        }
        self._alerts.append(alert)
        if len(self._alerts) > 50:
            self._alerts.pop(0)

        # Simulate diagnosis after alert
        self._diag_counter += 1
        roots = {
            "temperature": "Belt motor overheating — possible bearing wear or blocked ventilation",
            "vibration":   "Mechanical vibration anomaly — bearing defect or belt misalignment",
            "power_kw":    "Power consumption elevated — possible motor overload or electrical fault",
        }
        diagnosis = {
            "diagnosis_id": f"DX-{self._diag_counter:04d}",
            "alert_id": alert["alert_id"],
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "station_id": stn.station_id,
            "station_name": stn.name,
            "level": level,
            "root_cause": roots.get(metric, "Unknown anomaly"),
            "confidence": random.randint(55, 90),
            "severity": level,
            "urgency": "HIGH" if level == "CRITICAL" else "MEDIUM",
            "recommended_action": "Inspect station and review sensor data",
            "llm_used": False,
        }
        self._diagnoses.append(diagnosis)
        if len(self._diagnoses) > 20:
            self._diagnoses.pop(0)

        proposal = {
            "proposal_id": f"RP-{self._diag_counter:04d}",
            "diagnosis_id": diagnosis["diagnosis_id"],
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "station_id": stn.station_id,
            "station_name": stn.name,
            "root_cause": diagnosis["root_cause"],
            "urgency": diagnosis["urgency"],
            "proposals": [
                {
                    "id": 1,
                    "name": "Inspect and Clean",
                    "description": f"Manual inspection of {stn.name} — clean sensors, check belt tension.",
                    "risk_level": "LOW",
                    "estimated_downtime_min": 20,
                    "expected_result": "Resolve sensor anomaly",
                },
            ],
        }
        self._proposals.append(proposal)
        if len(self._proposals) > 20:
            self._proposals.pop(0)

    # ── Public API ──

    def get_all_states(self) -> Dict[str, Dict]:
        with self._lock:
            return {sid: s.get_status() for sid, s in self._stations.items()}

    def get_alerts(self, limit: int = 20) -> List[Dict]:
        with self._lock:
            return list(reversed(self._alerts[-limit:]))

    def get_diagnoses(self, limit: int = 10) -> List[Dict]:
        with self._lock:
            return list(reversed(self._diagnoses[-limit:]))

    def get_proposals(self, limit: int = 10) -> List[Dict]:
        with self._lock:
            return list(reversed(self._proposals[-limit:]))

    def inject_fault(self, station_id: str, fault_type: str):
        with self._lock:
            if station_id in self._stations:
                self._stations[station_id].inject_fault(fault_type)

    def clear_faults(self, station_id: str = "all"):
        with self._lock:
            if station_id == "all":
                for s in self._stations.values():
                    s.clear_faults()
            elif station_id in self._stations:
                self._stations[station_id].clear_faults()

    def get_production_summary(self) -> Dict:
        with self._lock:
            total = sum(s._products for s in self._stations.values())
            passed = sum(s._pass for s in self._stations.values())
            failed = sum(s._fail for s in self._stations.values())
            elapsed = time.time() - self._start_time
            return {
                "total_products": total,
                "passed": passed,
                "failed": failed,
                "pass_rate": round((passed / max(total, 1)) * 100, 1),
                "throughput_per_hour": round((total / max(elapsed, 1)) * 3600, 1),
                "active_faults": sum(1 for s in self._stations.values() if s._faults),
                "runtime_seconds": round(elapsed),
            }


# Singleton instance shared across Streamlit pages via session state
_INSTANCE = None

def get_simulator() -> DemoSimulator:
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = DemoSimulator()
        _INSTANCE.start()
    return _INSTANCE
