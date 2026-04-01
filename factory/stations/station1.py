"""
Station 1: Chassis Loading & Inspection
TV Assembly Production Line

REAL Fault Effects — faults cause VISIBLE changes in Factory I/O:
  - Belt stutters (stops/restarts)
  - Power brownouts (everything OFF briefly)
  - Blade chatters (flips up/down)
  - Emergency stops (everything OFF until cleared)
  - Sensor misreads (wrong control decisions)

NOTE: Belt 1b (transition belt) is ALWAYS ON.
      It is turned ON once at startup and never stopped.
      Faults, brownouts, and emergency stops do NOT affect belt 1b.

FIX: MQTT fault commands now use per-station topics:
     factory/station1/faults/inject  (only Station 1 listens)
     factory/station2/faults/inject  (only Station 2 listens)
     factory/station3/faults/inject  (only Station 3 listens)
     factory/faults/inject           (broadcast — station field required)
"""

import time
import random
import logging
import json
from typing import Dict, List, Callable
from datetime import datetime
from dataclasses import dataclass, field

from factory.modbus_client import FactoryModbusClient
from factory.config import STATION1_CONFIG

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# DATA CLASSES — Simulated Sensors (for MQTT dashboards)
# ═══════════════════════════════════════════════════════════════

@dataclass
class TemperatureSimulator:
    ambient: float = 25.0
    current: float = 25.0
    heating_rate: float = 0.15
    cooling_rate: float = 0.05
    noise: float = 0.3
    max_temp: float = 80.0
    fault_offset: float = 0.0

    def update(self, is_running: bool, dt: float = 0.1):
        if is_running:
            target = 45.0 + self.fault_offset
            diff = target - self.current
            self.current += diff * self.heating_rate * dt
        else:
            diff = self.current - self.ambient
            self.current -= diff * self.cooling_rate * dt
        self.current += random.gauss(0, self.noise * dt)
        self.current = max(self.ambient - 2, min(self.max_temp, self.current))
        return round(self.current, 2)

    def inject_fault(self, severity: int):
        self.fault_offset = severity * 8.0

    def clear_fault(self):
        self.fault_offset = 0.0


@dataclass
class VibrationSimulator:
    base_level: float = 5.0
    current: float = 0.0
    noise: float = 2.0
    fault_offset: float = 0.0

    def update(self, is_running: bool, speed_factor: float = 1.0):
        if is_running:
            self.current = (self.base_level * speed_factor
                            + self.fault_offset
                            + random.gauss(0, self.noise))
        else:
            self.current = 1.0 + random.gauss(0, 0.3)
        self.current = max(0, self.current)
        return round(self.current, 2)

    def inject_fault(self, severity: int):
        self.fault_offset = severity * 10.0

    def clear_fault(self):
        self.fault_offset = 0.0


@dataclass
class PowerSimulator:
    idle_power: float = 0.1
    running_power: float = 2.2
    current: float = 0.0
    noise: float = 0.1
    total_energy: float = 0.0
    fault_multiplier: float = 1.0
    _last_update: float = field(default_factory=time.time)

    def update(self, is_running: bool):
        now = time.time()
        dt = now - self._last_update
        self._last_update = now
        if is_running:
            self.current = (self.running_power * self.fault_multiplier
                            + random.gauss(0, self.noise))
        else:
            self.current = self.idle_power + random.gauss(0, 0.02)
        self.current = max(0, self.current)
        self.total_energy += (self.current * dt) / 3600.0
        return round(self.current, 3)

    def inject_fault(self, severity: int):
        self.fault_multiplier = 1.0 + (severity * 0.3)

    def clear_fault(self):
        self.fault_multiplier = 1.0


@dataclass
class ProductionStats:
    products_created: int = 0
    products_completed: int = 0
    products_failed: int = 0
    cycle_times: List[float] = field(default_factory=list)
    total_runtime: float = 0.0
    total_downtime: float = 0.0
    total_inspection_time: float = 0.0
    _runtime_start: float = 0.0
    _downtime_start: float = 0.0
    _is_tracking_runtime: bool = False

    @property
    def average_cycle_time(self) -> float:
        return sum(self.cycle_times) / len(self.cycle_times) if self.cycle_times else 0.0

    @property
    def min_cycle_time(self) -> float:
        return min(self.cycle_times) if self.cycle_times else 0.0

    @property
    def max_cycle_time(self) -> float:
        return max(self.cycle_times) if self.cycle_times else 0.0

    @property
    def pass_rate(self) -> float:
        total = self.products_completed + self.products_failed
        return (self.products_completed / total) * 100 if total > 0 else 0.0

    @property
    def throughput_per_minute(self) -> float:
        total_time = self.total_runtime + self.total_downtime
        return (self.products_completed / total_time) * 60 if total_time > 60 else 0.0

    @property
    def availability(self) -> float:
        total = self.total_runtime + self.total_downtime
        return (self.total_runtime / total) * 100 if total > 0 else 0.0

    @property
    def performance(self) -> float:
        ideal_cycle = 6.0
        return min(100, (ideal_cycle / self.average_cycle_time) * 100) if self.average_cycle_time > 0 else 0.0

    @property
    def quality(self) -> float:
        return self.pass_rate

    @property
    def oee(self) -> float:
        return (self.availability * self.performance * self.quality) / 10000

    def start_runtime(self):
        if not self._is_tracking_runtime:
            self._runtime_start = time.time()
            self._is_tracking_runtime = True
            if self._downtime_start > 0:
                self.total_downtime += time.time() - self._downtime_start
                self._downtime_start = 0

    def start_downtime(self):
        if self._is_tracking_runtime:
            self.total_runtime += time.time() - self._runtime_start
            self._runtime_start = 0
            self._is_tracking_runtime = False
            self._downtime_start = time.time()

    def add_cycle(self, cycle_time: float):
        self.cycle_times.append(cycle_time)
        if len(self.cycle_times) > 100:
            self.cycle_times.pop(0)


@dataclass
class FaultState:
    motor_overheat: bool = False
    motor_overheat_severity: int = 0
    vibration_anomaly: bool = False
    vibration_severity: int = 0
    power_fluctuation: bool = False
    power_severity: int = 0
    belt_slippage: bool = False
    belt_slippage_severity: int = 0
    sensor_drift: bool = False
    sensor_drift_amount: float = 0.0

    @property
    def has_any_fault(self) -> bool:
        return any([self.motor_overheat, self.vibration_anomaly,
                    self.power_fluctuation, self.belt_slippage,
                    self.sensor_drift])

    @property
    def active_faults(self) -> List[str]:
        faults = []
        if self.motor_overheat:
            faults.append(f"motor_overheat(sev={self.motor_overheat_severity})")
        if self.vibration_anomaly:
            faults.append(f"vibration(sev={self.vibration_severity})")
        if self.power_fluctuation:
            faults.append(f"power(sev={self.power_severity})")
        if self.belt_slippage:
            faults.append(f"belt_slip(sev={self.belt_slippage_severity})")
        if self.sensor_drift:
            faults.append(f"sensor_drift({self.sensor_drift_amount * 100:.0f}%)")
        return faults


# ═══════════════════════════════════════════════════════════════
# STATION 1 CONTROLLER — WITH REAL FAULT EFFECTS
# ═══════════════════════════════════════════════════════════════

class Station1Controller:
    """
    Controls Station 1 (Chassis Loading & Inspection).

    BELT 1b BEHAVIOR:
    Belt 1b (belt2) is turned ON once at startup and NEVER stopped.

    MQTT TOPICS:
    Listens on: factory/station1/faults/inject  (dedicated)
                factory/faults/inject            (broadcast, filtered by station field)
    """

    FAULT_PROB = {
        "overheat_stutter": 0.003,
        "belt_slip_stutter": 0.004,
        "power_brownout": 0.002,
        "vibration_chatter": 0.002,
    }

    FAULT_DURATION = {
        "overheat_stutter": (0.2, 0.2),
        "belt_slip_stutter": (0.1, 0.18),
        "power_brownout": (0.3, 0.4),
        "vibration_chatter": (0.15, 0.0),
    }

    EMERGENCY_THRESHOLD = 4

    def __init__(self, modbus_client: FactoryModbusClient, mqtt_client=None, config=None):
        if config is None:
            config = STATION1_CONFIG
        self.modbus = modbus_client
        self.mqtt = mqtt_client
        self._io = config["io"]
        self.STATION_ID = config.get("id", "station_1")

        # ─── State ───
        self.state = "stopped"
        self.is_running = False
        self.has_error = False
        self.error_message = ""

        # ─── Simulated sensors ───
        self.temperature = TemperatureSimulator()
        self.vibration = VibrationSimulator()
        self.power = PowerSimulator()

        # ─── Production stats ───
        self.stats = ProductionStats()

        # ─── Fault injection state ───
        self.faults = FaultState()

        # ─── INTENDED output states ───
        self._intended = {
            "belt1": False,
            "emitter": False,
            "stop_blade": False,
        }

        # ─── Fault override state ───
        self._fault_override_active = False
        self._fault_override_until = 0.0
        self._fault_override_type = ""

        # ─── Emergency stop state ───
        self._emergency_active = False
        self._emergency_reason = ""

        # ─── Fault effects tracking ───
        self._fault_counters = {
            "stutters": 0,
            "brownouts": 0,
            "blade_chatters": 0,
            "emergency_stops": 0,
            "sensor_misreads": 0,
            "total_fault_downtime": 0.0,
        }
        self._fault_events = []
        self._fault_downtime_start = 0.0

        # ─── Belt / motor tracking ───
        self._belt_speed = 0.0
        self._target_belt_speed = 100.0
        self._motor_start_time = None
        self._total_motor_runtime = 0.0

        # ─── MQTT timing ───
        self._last_mqtt_publish = 0.0
        self.MQTT_PUBLISH_INTERVAL = 1.0

        logger.info(f"✅ Station 1 initialized (ID={self.STATION_ID})")

    # =================================================================
    # MQTT FAULT ROUTING
    # =================================================================

    def _setup_mqtt_fault_listener(self):
        """
        Subscribe to BOTH:
          - factory/station1/faults/inject  (dedicated topic)
          - factory/faults/inject            (broadcast, filtered)
        """
        if not self.mqtt or not self.mqtt.is_connected:
            return

        def on_fault_command(topic, data):
            try:
                if isinstance(data, str):
                    data = json.loads(data)

                # ── Filter: broadcast topic requires matching station ──
                if "station1" not in topic:
                    # This came from the broadcast topic
                    station = data.get("station", "")
                    if station and station != self.STATION_ID:
                        return  # Not for us

                action = data.get("action", "")
                fault_type = data.get("fault_type", "")
                severity = data.get("severity", 3)

                if action == "inject":
                    self.inject_fault(fault_type, severity)
                elif action == "clear":
                    self.clear_fault(fault_type)

            except Exception as e:
                logger.error(f"Error processing fault command: {e}")

        # Dedicated topic — only Station 1 listens
        self.mqtt.subscribe(
            f"factory/{self.STATION_ID}/faults/inject",
            on_fault_command,
        )
        # Broadcast topic — filtered by station field
        self.mqtt.subscribe(
            "factory/faults/inject",
            on_fault_command,
        )
        logger.info(f"📡 {self.STATION_ID}: Listening for faults on dedicated + broadcast topics")

    # =================================================================
    # I/O METHODS
    # =================================================================

    def _write_raw(self, output_name: str, value: bool):
        self.modbus.write_output(self._io[output_name]["address"], value)

    def _belt1b_on(self):
        self._write_raw("belt2", True)
        logger.info("   BELT 1b: ON (transition belt — stays ON forever)")

    def belt1(self, on: bool):
        self._intended["belt1"] = on
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("belt1", on)
        if on:
            self.stats.start_runtime()
            if self._motor_start_time is None:
                self._motor_start_time = time.time()
        else:
            self.stats.start_downtime()
            if self._motor_start_time is not None:
                self._total_motor_runtime += time.time() - self._motor_start_time
                self._motor_start_time = None
        logger.info(f"   BELT 1: {'ON' if on else 'OFF'}")

    def belt2(self, on: bool):
        self._write_raw("belt2", on)
        logger.info(f"   BELT 1b: {'ON' if on else 'OFF'}")

    def emitter(self, on: bool):
        self._intended["emitter"] = on
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("emitter", on)
        logger.info(f"   EMITTER: {'ON' if on else 'OFF'}")

    def blade(self, up: bool):
        self._intended["stop_blade"] = up
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("stop_blade", up)
        logger.info(f"   BLADE: {'UP' if up else 'DOWN'}")

    def read_sensor_1(self) -> bool:
        addr = self._io["sensor_entry"]["address"]
        inputs = self.modbus.read_inputs(addr, 1)
        value = inputs[0] if inputs else False
        if self.faults.sensor_drift:
            if random.random() < self.faults.sensor_drift_amount:
                value = not value
                self._fault_counters["sensor_misreads"] += 1
                logger.warning(f"   📡 SENSOR DRIFT: Sensor 1 misread!")
        return value

    def read_sensor_2(self) -> bool:
        addr = self._io["sensor_station"]["address"]
        inputs = self.modbus.read_inputs(addr, 1)
        value = inputs[0] if inputs else False
        if self.faults.sensor_drift:
            if random.random() < self.faults.sensor_drift_amount:
                value = not value
                self._fault_counters["sensor_misreads"] += 1
                logger.warning(f"   📡 SENSOR DRIFT: Sensor 2 misread!")
        return value

    def all_off(self):
        self._write_raw("belt1", False)
        self._write_raw("emitter", False)
        self._write_raw("stop_blade", False)

    # =================================================================
    # FAULT INJECTION
    # =================================================================

    def inject_fault(self, fault_type: str, severity: int = 3):
        severity = max(1, min(5, severity))

        logger.warning("")
        logger.warning("🚨 ═══════════════════════════════════════════")
        logger.warning(f"🚨  STN1 FAULT INJECTED: {fault_type}")
        logger.warning(f"🚨  Severity: {severity}/5")
        logger.warning("🚨 ═══════════════════════════════════════════")

        if fault_type == "overheat":
            self.faults.motor_overheat = True
            self.faults.motor_overheat_severity = severity
            self.temperature.inject_fault(severity)
            if severity >= self.EMERGENCY_THRESHOLD:
                self._trigger_emergency(
                    "OVERHEAT",
                    f"Motor temperature critical! Severity {severity}/5"
                )

        elif fault_type == "vibration":
            self.faults.vibration_anomaly = True
            self.faults.vibration_severity = severity
            self.vibration.inject_fault(severity)
            if severity >= 5:
                self._trigger_emergency(
                    "VIBRATION",
                    f"Vibration exceeds safety limit! Severity {severity}/5"
                )

        elif fault_type == "power":
            self.faults.power_fluctuation = True
            self.faults.power_severity = severity
            self.power.inject_fault(severity)
            if severity >= 5:
                self._trigger_emergency(
                    "POWER_FAILURE",
                    "Complete power loss! Severity 5/5"
                )

        elif fault_type == "belt_slip":
            self.faults.belt_slippage = True
            self.faults.belt_slippage_severity = severity
            self._target_belt_speed = max(20, 100 - (severity * 15))

        elif fault_type == "sensor_drift":
            self.faults.sensor_drift = True
            self.faults.sensor_drift_amount = severity * 0.05

        else:
            logger.warning(f"   ⚠️ Unknown fault type for Station 1: {fault_type}")
            return

        self._log_fault_event("inject", f"{fault_type} severity={severity}")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/fault_injected", {
                "fault_type": fault_type,
                "severity": severity,
                "real_effects": True,
                "station": self.STATION_ID,
                "timestamp": datetime.now().isoformat(),
            })

    def clear_fault(self, fault_type: str = "all"):
        logger.info(f"✅ STN1: Clearing fault: {fault_type}")

        if fault_type in ("overheat", "all"):
            self.faults.motor_overheat = False
            self.faults.motor_overheat_severity = 0
            self.temperature.clear_fault()

        if fault_type in ("vibration", "all"):
            self.faults.vibration_anomaly = False
            self.faults.vibration_severity = 0
            self.vibration.clear_fault()

        if fault_type in ("power", "all"):
            self.faults.power_fluctuation = False
            self.faults.power_severity = 0
            self.power.clear_fault()

        if fault_type in ("belt_slip", "all"):
            self.faults.belt_slippage = False
            self.faults.belt_slippage_severity = 0
            self._target_belt_speed = 100.0

        if fault_type in ("sensor_drift", "all"):
            self.faults.sensor_drift = False
            self.faults.sensor_drift_amount = 0.0

        if self._emergency_active:
            self._emergency_active = False
            self._emergency_reason = ""
            if self._fault_downtime_start > 0:
                dt = time.time() - self._fault_downtime_start
                self._fault_counters["total_fault_downtime"] += dt
                self._fault_downtime_start = 0.0
            logger.info("✅ EMERGENCY STOP CLEARED — restoring outputs...")
            self._restore_intended()
            self._log_fault_event("emergency_cleared", "Line resuming")

        if self._fault_override_active:
            self._fault_override_active = False
            self._fault_override_type = ""
            self._fault_override_until = 0.0
            if self._fault_downtime_start > 0:
                dt = time.time() - self._fault_downtime_start
                self._fault_counters["total_fault_downtime"] += dt
                self._fault_downtime_start = 0.0
            self._restore_intended()

        self._log_fault_event("clear", f"Cleared: {fault_type}")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/fault_cleared", {
                "fault_type": fault_type,
                "station": self.STATION_ID,
                "timestamp": datetime.now().isoformat(),
            })

    # =================================================================
    # FAULT EFFECTS ENGINE
    # =================================================================

    def _fault_tick(self):
        now = time.time()

        if self._fault_override_active and now >= self._fault_override_until:
            ended_type = self._fault_override_type
            self._fault_override_active = False
            self._fault_override_type = ""
            self._fault_override_until = 0.0

            if self._fault_downtime_start > 0:
                dt = now - self._fault_downtime_start
                self._fault_counters["total_fault_downtime"] += dt
                self._fault_downtime_start = 0.0

            self._restore_intended()
            logger.info(f"   ✅ {ended_type} ended → outputs restored")
            return

        if self._fault_override_active or self._emergency_active:
            return

        if self.faults.motor_overheat:
            sev = self.faults.motor_overheat_severity
            if sev >= self.EMERGENCY_THRESHOLD:
                if not self._emergency_active:
                    self._trigger_emergency(
                        "OVERHEAT",
                        f"Temperature {self.temperature.current:.1f}°C"
                    )
                return
            if self._intended["belt1"]:
                prob = sev * self.FAULT_PROB["overheat_stutter"]
                if random.random() < prob:
                    base, per_sev = self.FAULT_DURATION["overheat_stutter"]
                    duration = base + (sev * per_sev)
                    self._trigger_stutter(duration, "overheat")
                    return

        if self.faults.belt_slippage:
            sev = self.faults.belt_slippage_severity
            if self._intended["belt1"]:
                prob = sev * self.FAULT_PROB["belt_slip_stutter"]
                if random.random() < prob:
                    base, per_sev = self.FAULT_DURATION["belt_slip_stutter"]
                    duration = base + (sev * per_sev)
                    self._trigger_stutter(duration, "belt_slip")
                    return

        if self.faults.power_fluctuation:
            sev = self.faults.power_severity
            prob = sev * self.FAULT_PROB["power_brownout"]
            if random.random() < prob:
                if sev >= 5:
                    self._trigger_emergency(
                        "POWER_FAILURE",
                        "Complete power loss!"
                    )
                else:
                    base, per_sev = self.FAULT_DURATION["power_brownout"]
                    duration = base + (sev * per_sev)
                    self._trigger_brownout(duration)
                return

        if self.faults.vibration_anomaly:
            sev = self.faults.vibration_severity
            if sev >= 5:
                if not self._emergency_active:
                    self._trigger_emergency(
                        "VIBRATION",
                        f"Vibration critical!"
                    )
                return
            if sev >= 3:
                prob = sev * self.FAULT_PROB["vibration_chatter"]
                if random.random() < prob:
                    base, per_sev = self.FAULT_DURATION["vibration_chatter"]
                    duration = base + (sev * per_sev)
                    self._trigger_blade_chatter(duration)
                    return

    def _trigger_stutter(self, duration: float, reason: str):
        self._fault_override_active = True
        self._fault_override_until = time.time() + duration
        self._fault_override_type = f"stutter({reason})"
        self._fault_downtime_start = time.time()
        self._write_raw("belt1", False)
        self._fault_counters["stutters"] += 1
        logger.warning(f"   ⚡ STUTTER ({reason}): Belt 1 OFF {duration:.2f}s")
        self._log_fault_event("stutter", f"{reason} — belt1 off {duration:.2f}s")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/fault_effect", {
                "effect": "stutter",
                "reason": reason,
                "duration": duration,
                "real_modbus_writes": ["belt1=OFF"],
                "belt1b": "stays ON",
                "station": self.STATION_ID,
                "timestamp": datetime.now().isoformat(),
            })

    def _trigger_brownout(self, duration: float):
        self._fault_override_active = True
        self._fault_override_until = time.time() + duration
        self._fault_override_type = "brownout"
        self._fault_downtime_start = time.time()
        self.all_off()
        self._fault_counters["brownouts"] += 1
        logger.warning(f"   ⚡ BROWNOUT: All OFF {duration:.2f}s (belt 1b stays ON)")
        self._log_fault_event("brownout", f"All off (except belt1b) {duration:.2f}s")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/fault_effect", {
                "effect": "brownout",
                "duration": duration,
                "real_modbus_writes": ["belt1=OFF", "emitter=OFF", "stop_blade=OFF"],
                "belt1b": "stays ON",
                "station": self.STATION_ID,
                "timestamp": datetime.now().isoformat(),
            })

    def _trigger_blade_chatter(self, duration: float):
        self._fault_override_active = True
        self._fault_override_until = time.time() + duration
        self._fault_override_type = "blade_chatter"

        current_blade = self._intended["stop_blade"]
        self._write_raw("stop_blade", not current_blade)
        self._fault_counters["blade_chatters"] += 1

        action = "UP→DOWN" if current_blade else "DOWN→UP"
        logger.warning(f"   📳 BLADE CHATTER: {action} for {duration:.2f}s")
        self._log_fault_event("blade_chatter", f"Blade {action}")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/fault_effect", {
                "effect": "blade_chatter",
                "duration": duration,
                "real_modbus_writes": [f"stop_blade={'DOWN' if current_blade else 'UP'}"],
                "station": self.STATION_ID,
                "timestamp": datetime.now().isoformat(),
            })

    def _trigger_emergency(self, reason: str, details: str):
        if self._emergency_active:
            return
        self._emergency_active = True
        self._emergency_reason = f"{reason}: {details}"
        self._fault_downtime_start = time.time()
        self._fault_override_active = False
        self._fault_override_type = ""
        self._fault_override_until = 0.0
        self.all_off()
        self._fault_counters["emergency_stops"] += 1

        logger.error(f"🚨 STN1 EMERGENCY: {reason} — {details}")
        self._log_fault_event("emergency_stop", f"{reason}: {details}")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/emergency", {
                "active": True,
                "reason": reason,
                "details": details,
                "real_modbus_writes": ["belt1=OFF", "emitter=OFF", "stop_blade=OFF"],
                "belt1b": "stays ON",
                "station": self.STATION_ID,
                "timestamp": datetime.now().isoformat(),
            })

    def _restore_intended(self):
        for name, value in self._intended.items():
            self._write_raw(name, value)
        logger.info(
            f"   🔧 Outputs RESTORED → "
            f"Belt1={'ON' if self._intended['belt1'] else 'OFF'}, "
            f"Belt1b=ON (always), "
            f"Emitter={'ON' if self._intended['emitter'] else 'OFF'}, "
            f"Blade={'UP' if self._intended['stop_blade'] else 'DOWN'}"
        )

    def _log_fault_event(self, event_type: str, details: str):
        self._fault_events.append({
            "time": datetime.now().isoformat(),
            "type": event_type,
            "details": details,
        })
        if len(self._fault_events) > 50:
            self._fault_events.pop(0)

    # =================================================================
    # WAIT HELPERS
    # =================================================================

    def _wait_for(self, condition_fn: Callable[[], bool],
                  timeout: float = 30.0,
                  state_name: str = "waiting") -> bool:
        self.state = state_name
        timeout_time = time.time() + timeout

        while self.is_running:
            belt_on = (self._intended["belt1"]
                       and not self._fault_override_active
                       and not self._emergency_active)
            self._update_simulations(belt_on)
            self._fault_tick()
            self._publish_mqtt()

            if self._emergency_active:
                saved_state = self.state
                self.state = "EMERGENCY_STOP"
                while self._emergency_active and self.is_running:
                    self._update_simulations(False)
                    self._publish_mqtt()
                    time.sleep(0.1)
                if not self.is_running:
                    return False
                logger.info("✅ Emergency cleared — resuming...")
                self.state = saved_state
                timeout_time = time.time() + timeout

            if condition_fn():
                return True
            if time.time() > timeout_time:
                logger.error(f"❌ TIMEOUT in {state_name}!")
                return False
            time.sleep(0.05)

        return False

    def _wait_seconds(self, seconds: float, state_name: str = "waiting"):
        self.state = state_name
        remaining = seconds

        while self.is_running and remaining > 0:
            tick_start = time.time()
            belt_on = (self._intended["belt1"]
                       and not self._fault_override_active
                       and not self._emergency_active)
            self._update_simulations(belt_on)
            self._fault_tick()
            self._publish_mqtt()

            if self._emergency_active:
                saved_state = self.state
                self.state = "EMERGENCY_STOP"
                while self._emergency_active and self.is_running:
                    self._update_simulations(False)
                    self._publish_mqtt()
                    time.sleep(0.1)
                if not self.is_running:
                    return
                self.state = saved_state
                continue

            time.sleep(0.05)
            remaining -= (time.time() - tick_start)

    # =================================================================
    # SIMULATION
    # =================================================================

    def _update_simulations(self, belt_running: bool):
        speed_diff = self._target_belt_speed - self._belt_speed
        self._belt_speed += speed_diff * 0.1
        if not belt_running:
            self._belt_speed = 0.0
        speed_factor = self._belt_speed / 100.0
        self.temperature.update(belt_running)
        self.vibration.update(belt_running, speed_factor)
        self.power.update(belt_running)

    def _publish_mqtt(self, force: bool = False):
        if not self.mqtt or not self.mqtt.is_connected:
            return
        now = time.time()
        if not force and (now - self._last_mqtt_publish) < self.MQTT_PUBLISH_INTERVAL:
            return
        self._last_mqtt_publish = now

        self.mqtt.publish("factory/sensors/motor/temperature", {
            "sensor": "motor_temperature",
            "value": self.temperature.current,
            "unit": "°C",
            "station": self.STATION_ID,
        })
        self.mqtt.publish("factory/sensors/motor/vibration", {
            "sensor": "vibration",
            "value": self.vibration.current,
            "unit": "mm/s",
            "station": self.STATION_ID,
        })
        self.mqtt.publish("factory/sensors/system/power", {
            "sensor": "power_consumption",
            "value": self.power.current,
            "unit": "kW",
            "station": self.STATION_ID,
        })
        self.mqtt.publish("factory/sensors/motor/speed", {
            "sensor": "belt_speed",
            "value": self._belt_speed,
            "unit": "%",
            "station": self.STATION_ID,
        })
        self.mqtt.publish(f"factory/{self.STATION_ID}/status", self.get_status())

        if self.faults.has_any_fault:
            self.mqtt.publish(f"factory/{self.STATION_ID}/faults", {
                "has_fault": True,
                "active_faults": self.faults.active_faults,
                "real_effects": dict(self._fault_counters),
                "station": self.STATION_ID,
            })

    # =================================================================
    # MAIN RUN LOOP
    # =================================================================

    def run(self):
        self.is_running = True
        first_product = True

        self._belt1b_on()

        # ── Setup MQTT fault listener (NEW: proper routing) ──
        self._setup_mqtt_fault_listener()

        try:
            while self.is_running:
                cycle_start = time.time()

                # ─── STEP 1: Create product ───
                logger.info("═" * 55)
                if first_product:
                    logger.info("STEP 1: Creating FIRST product...")
                    self.stats.products_created += 1
                    logger.info(f"   Product #{self.stats.products_created}")
                    self.emitter(True)
                    self.belt1(True)
                    self.blade(False)
                    first_product = False
                else:
                    logger.info("STEP 1: Product already created, belt running")
                    logger.info(f"   Product #{self.stats.products_created}")

                # ─── STEP 2: Wait for Sensor 1 ───
                logger.info("STEP 2: Waiting for Sensor 1...")
                if not self._wait_for(
                    self.read_sensor_1, timeout=30.0,
                    state_name="wait_sensor_1",
                ):
                    break

                logger.info("STEP 2: ✅ Sensor 1 TRIGGERED!")
                self.emitter(False)
                self.blade(True)

                # ─── STEP 3: Wait for Sensor 2 ───
                logger.info("STEP 3: Waiting for Sensor 2...")
                if not self._wait_for(
                    self.read_sensor_2, timeout=30.0,
                    state_name="wait_sensor_2",
                ):
                    break

                logger.info("STEP 3: ✅ Sensor 2 TRIGGERED!")
                self.belt1(False)

                # ─── STEP 3b: Inspection ───
                logger.info("STEP 3: 🔍 Inspecting for 3 seconds...")
                inspection_start = time.time()
                for countdown in range(3, 0, -1):
                    logger.info(f"   ⏱️ {countdown} seconds remaining...")
                    self._wait_seconds(1.0, state_name="inspecting")
                self.stats.total_inspection_time += time.time() - inspection_start
                logger.info("STEP 3: ✅ Inspection DONE!")

                # ─── STEP 4a: Blade down ───
                logger.info("STEP 4: Lowering blade FIRST...")
                self.blade(False)
                self._wait_seconds(1.0, state_name="blade_lowering")

                # ─── STEP 4b: Restart ───
                logger.info("STEP 4: Starting belt and emitter...")
                self.belt1(True)
                self.emitter(True)

                # ─── Cycle complete ───
                cycle_time = time.time() - cycle_start
                self.stats.products_completed += 1
                self.stats.add_cycle(cycle_time)

                logger.info(f"✅ Product #{self.stats.products_completed} COMPLETE! ({cycle_time:.1f}s)")

                if self.faults.has_any_fault:
                    logger.warning(f"   ⚠️  FAULTS: {self.faults.active_faults}")

                self.stats.products_created += 1
                logger.info(f"📦 Product #{self.stats.products_created} being created...")

                self._publish_mqtt(force=True)

        except KeyboardInterrupt:
            logger.info("Interrupted by user")
        finally:
            self.is_running = False
            self.all_off()
            if self._motor_start_time is not None:
                self._total_motor_runtime += time.time() - self._motor_start_time

    # =================================================================
    # STATUS & REPORTS
    # =================================================================

    def start(self):
        pass

    def stop(self):
        self.all_off()
        self.is_running = False

    def get_status(self) -> Dict:
        return {
            "station": self.STATION_ID,
            "name": "Chassis Loading & Inspection",
            "state": self.state,
            "is_running": self.is_running,
            "emergency_active": self._emergency_active,
            "emergency_reason": self._emergency_reason,
            "timestamp": datetime.now().isoformat(),
            "sensors": {
                "motor_temperature": round(self.temperature.current, 2),
                "vibration": round(self.vibration.current, 2),
                "power_consumption": round(self.power.current, 3),
                "belt_speed": round(self._belt_speed, 1),
            },
            "counters": {
                "products_created": self.stats.products_created,
                "products_completed": self.stats.products_completed,
                "products_failed": self.stats.products_failed,
                "pass_rate": round(self.stats.pass_rate, 1),
            },
            "timing": {
                "average_cycle_time": round(self.stats.average_cycle_time, 2),
                "min_cycle_time": round(self.stats.min_cycle_time, 2),
                "max_cycle_time": round(self.stats.max_cycle_time, 2),
                "total_runtime": round(self.stats.total_runtime, 1),
                "total_downtime": round(self.stats.total_downtime, 1),
                "motor_runtime_hours": round(self._total_motor_runtime / 3600, 3),
            },
            "oee": {
                "availability": round(self.stats.availability, 1),
                "performance": round(self.stats.performance, 1),
                "quality": round(self.stats.quality, 1),
                "oee": round(self.stats.oee, 1),
            },
            "energy": {
                "current_power": round(self.power.current, 3),
                "total_energy_kwh": round(self.power.total_energy, 4),
            },
            "faults": {
                "has_fault": self.faults.has_any_fault,
                "active_faults": self.faults.active_faults,
            },
            "fault_effects": {
                "override_active": self._fault_override_active,
                "override_type": self._fault_override_type,
                "emergency_active": self._emergency_active,
                "counters": dict(self._fault_counters),
                "recent_events": self._fault_events[-10:],
            },
        }

    def get_full_report(self) -> str:
        s = self.get_status()
        cnt = s["counters"]
        tim = s["timing"]
        oee = s["oee"]
        eng = s["energy"]
        sen = s["sensors"]
        flt = s["faults"]
        fx = s["fault_effects"]
        fc = fx["counters"]

        report = f"""
╔══════════════════════════════════════════════════════════════╗
║       📺 STATION 1 — FULL PRODUCTION REPORT                 ║
╠══════════════════════════════════════════════════════════════╣
║  Products Created:     {cnt['products_created']:5d}    Completed: {cnt['products_completed']:5d}          ║
║  Pass Rate:            {cnt['pass_rate']:5.1f}%                           ║
║  Average Cycle Time:   {tim['average_cycle_time']:5.2f}s                           ║
║  OEE:                  {oee['oee']:5.1f}%                           ║
║  ⚡ Stutters: {fc['stutters']:4d}  Brownouts: {fc['brownouts']:4d}  Chatters: {fc['blade_chatters']:4d}    ║
║  ⚡ E-Stops:  {fc['emergency_stops']:4d}  Misreads:  {fc['sensor_misreads']:4d}  Down: {fc['total_fault_downtime']:5.1f}s  ║
╚══════════════════════════════════════════════════════════════╝"""
        return report