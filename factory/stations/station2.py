"""
Station 2: PCB Board Installation (Pick & Place)
TV Assembly Production Line

MQTT TOPICS:
  Listens on: factory/station2/faults/inject  (dedicated)
              factory/faults/inject            (broadcast, filtered by station field)
"""

import time
import random
import logging
import json
import threading
from typing import Dict, List, Callable, Optional
from datetime import datetime
from dataclasses import dataclass, field

from factory.modbus_client import FactoryModbusClient
from factory.config import STATION2_CONFIG, FAULT_CONFIG

from factory.stations.station1 import (
    TemperatureSimulator,
    VibrationSimulator,
    PowerSimulator,
    ProductionStats,
    FaultState,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# EXTENDED FAULT STATE
# ═══════════════════════════════════════════════════════════

@dataclass
class Station2FaultState(FaultState):
    gripper_failure: bool = False
    gripper_failure_severity: int = 0
    pp_jam: bool = False
    pp_jam_severity: int = 0

    @property
    def has_any_fault(self) -> bool:
        return (super().has_any_fault
                or self.gripper_failure
                or self.pp_jam)

    @property
    def active_faults(self) -> List[str]:
        faults = super().active_faults
        if self.gripper_failure:
            faults.append(f"gripper_failure(sev={self.gripper_failure_severity})")
        if self.pp_jam:
            faults.append(f"pp_jam(sev={self.pp_jam_severity})")
        return faults


# ═══════════════════════════════════════════════════════════
# STATION 2 CONTROLLER
# ═══════════════════════════════════════════════════════════

class Station2Controller:
    """
    Station 2: PCB Installation using Pick & Place (X + Z axes).

    MQTT TOPICS:
      Listens on: factory/station_2/faults/inject  (dedicated)
                  factory/faults/inject              (broadcast, filtered)
    """

    STATION_ID = "station_2"

    def __init__(self, modbus_client: FactoryModbusClient,
                 mqtt_client=None,
                 upstream_ready: Optional[threading.Event] = None):
        self.modbus = modbus_client
        self.mqtt = mqtt_client
        self._upstream_ready = upstream_ready

        self._io = STATION2_CONFIG["io"]
        self._timing = STATION2_CONFIG["timing"]
        self._pp_config = STATION2_CONFIG["pick_and_place"]
        self._sim_config = STATION2_CONFIG["simulation"]
        self._fault_config = FAULT_CONFIG

        # ─── State ───
        self.state = "stopped"
        self.is_running = False

        # ─── Simulated sensors ───
        self.temperature = TemperatureSimulator(
            ambient=self._sim_config["normal_temperature"],
            current=self._sim_config["normal_temperature"],
            noise=self._sim_config["temperature_noise"],
        )
        self.vibration = VibrationSimulator(
            base_level=self._sim_config["normal_vibration"],
            noise=self._sim_config["vibration_noise"],
        )
        self.power = PowerSimulator(
            running_power=self._sim_config["belt_motor_power"],
        )
        self.stats = ProductionStats()

        # ─── Faults ───
        self.faults = Station2FaultState()

        # ─── Intended output states ───
        self._intended = {
            "belt": False,
            "stop_blade": False,
            "emitter": False,
            "pp_move_x": False,
            "pp_move_z": False,
            "pp_grab": False,
        }

        # ─── Fault override ───
        self._fault_override_active = False
        self._fault_override_until = 0.0
        self._fault_override_type = ""
        self._emergency_active = False
        self._emergency_reason = ""

        # ─── Fault tracking ───
        self._fault_counters = {
            "stutters": 0,
            "brownouts": 0,
            "gripper_failures": 0,
            "pp_jams": 0,
            "emergency_stops": 0,
            "sensor_misreads": 0,
            "total_fault_downtime": 0.0,
        }
        self._fault_events = []
        self._fault_downtime_start = 0.0

        # ─── P&P tracking ───
        self._pp_has_item = False
        self._pp_phase = "idle"

        # ─── Belt ───
        self._belt_speed = 0.0
        self._target_belt_speed = 100.0

        # ─── MQTT ───
        self._last_mqtt_publish = 0.0
        self.MQTT_PUBLISH_INTERVAL = 1.0

        logger.info(f"✅ Station 2 initialized (ID={self.STATION_ID})")

    # =================================================================
    # MQTT FAULT ROUTING
    # =================================================================

    def _setup_mqtt_fault_listener(self):
        """
        Subscribe to BOTH:
          - factory/station_2/faults/inject  (dedicated topic)
          - factory/faults/inject              (broadcast, filtered)
        """
        if not self.mqtt or not self.mqtt.is_connected:
            return

        def on_fault_command(topic, data):
            try:
                if isinstance(data, str):
                    data = json.loads(data)

                # Filter: broadcast topic requires matching station
                if self.STATION_ID not in topic:
                    station = data.get("station", "")
                    if station and station != self.STATION_ID:
                        return

                action = data.get("action", "")
                fault_type = data.get("fault_type", "")
                severity = data.get("severity", 3)

                if action == "inject":
                    self.inject_fault(fault_type, severity)
                elif action == "clear":
                    self.clear_fault(fault_type)

            except Exception as e:
                logger.error(f"Error processing fault command: {e}")

        self.mqtt.subscribe(
            f"factory/{self.STATION_ID}/faults/inject",
            on_fault_command,
        )
        self.mqtt.subscribe(
            "factory/faults/inject",
            on_fault_command,
        )
        logger.info(f"📡 {self.STATION_ID}: Listening for faults on dedicated + broadcast topics")

    # =================================================================
    # HELPERS
    # =================================================================

    def _out_addr(self, name: str) -> int:
        return self._io[name]["address"]

    def _in_addr(self, name: str) -> int:
        return self._io[name]["address"]

    # =================================================================
    # I/O METHODS
    # =================================================================

    def _write_raw(self, output_name: str, value: bool):
        self.modbus.write_output(self._out_addr(output_name), value)

    def belt(self, on: bool):
        self._intended["belt"] = on
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("belt", on)
        if on:
            self.stats.start_runtime()
        else:
            self.stats.start_downtime()
        logger.info(f"   BELT 2: {'ON' if on else 'OFF'}")

    def blade(self, up: bool):
        self._intended["stop_blade"] = up
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("stop_blade", up)
        logger.info(f"   BLADE 2: {'UP' if up else 'DOWN'}")

    def emitter(self, on: bool):
        self._intended["emitter"] = on
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("emitter", on)
        logger.info(f"   EMITTER 2: {'ON' if on else 'OFF'}")

    def pp_move_x(self, to_place: bool):
        value = (self._pp_config["x_place_value"] if to_place
                 else self._pp_config["x_pick_value"])
        self._intended["pp_move_x"] = value
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("pp_move_x", value)
        pos = "→ PLACE (over belt)" if to_place else "→ PICK (over emitter)"
        logger.info(f"   P&P X: {pos} (raw={value})")

    def pp_move_z(self, down: bool):
        value = (self._pp_config["z_down_value"] if down
                 else self._pp_config["z_up_value"])
        self._intended["pp_move_z"] = value
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("pp_move_z", value)
        logger.info(f"   P&P Z: {'↓ DOWN' if down else '↑ UP'} (raw={value})")

    def pp_grab(self, close: bool):
        value = (self._pp_config["grab_close_value"] if close
                 else self._pp_config["grab_open_value"])
        self._intended["pp_grab"] = value
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("pp_grab", value)
        self._pp_has_item = close
        logger.info(f"   P&P GRAB: {'CLOSED' if close else 'OPEN'} (raw={value})")

    def read_sensor_entry(self) -> bool:
        addr = self._in_addr("sensor_entry")
        inputs = self.modbus.read_inputs(addr, 1)
        value = inputs[0] if inputs else False
        if self.faults.sensor_drift:
            if random.random() < self.faults.sensor_drift_amount:
                value = not value
                self._fault_counters["sensor_misreads"] += 1
                logger.warning("   📡 DRIFT: Sensor 3 misread!")
        return value

    def read_sensor_station(self) -> bool:
        addr = self._in_addr("sensor_station")
        inputs = self.modbus.read_inputs(addr, 1)
        value = inputs[0] if inputs else False
        if self.faults.sensor_drift:
            if random.random() < self.faults.sensor_drift_amount:
                value = not value
                self._fault_counters["sensor_misreads"] += 1
                logger.warning("   📡 DRIFT: Sensor 4 misread!")
        return value

    def read_pp_moving_x(self) -> bool:
        addr = self._in_addr("pp_moving_x")
        inputs = self.modbus.read_inputs(addr, 1)
        return inputs[0] if inputs else False

    def read_pp_moving_z(self) -> bool:
        addr = self._in_addr("pp_moving_z")
        inputs = self.modbus.read_inputs(addr, 1)
        return inputs[0] if inputs else False

    def read_pp_item_detected(self) -> bool:
        addr = self._in_addr("pp_item_detected")
        inputs = self.modbus.read_inputs(addr, 1)
        return inputs[0] if inputs else False

    def all_off(self):
        for name, info in self._io.items():
            if info["type"] == "output":
                self.modbus.write_output(info["address"], False)

    # =================================================================
    # SYNCHRONIZATION
    # =================================================================

    def _signal_ready(self):
        if self._upstream_ready is not None:
            self._upstream_ready.set()
            logger.info("   📡 Signaled upstream: READY for product!")

    # =================================================================
    # WAIT HELPERS
    # =================================================================

    def _wait_for(self, condition_fn: Callable[[], bool],
                  timeout: float = 30.0,
                  state_name: str = "waiting") -> bool:
        self.state = state_name
        timeout_time = time.time() + timeout

        while self.is_running:
            belt_on = (self._intended["belt"]
                       and not self._fault_override_active
                       and not self._emergency_active)
            self._update_simulations(belt_on)
            self._fault_tick()
            self._publish_mqtt()

            if self._emergency_active:
                saved = self.state
                self.state = "EMERGENCY_STOP"
                while self._emergency_active and self.is_running:
                    self._update_simulations(False)
                    self._publish_mqtt()
                    time.sleep(0.1)
                if not self.is_running:
                    return False
                self.state = saved
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
            belt_on = (self._intended["belt"]
                       and not self._fault_override_active
                       and not self._emergency_active)
            self._update_simulations(belt_on)
            self._fault_tick()
            self._publish_mqtt()

            if self._emergency_active:
                saved = self.state
                self.state = "EMERGENCY_STOP"
                while self._emergency_active and self.is_running:
                    self._update_simulations(False)
                    self._publish_mqtt()
                    time.sleep(0.1)
                if not self.is_running:
                    return
                self.state = saved
                continue

            time.sleep(0.05)
            remaining -= (time.time() - tick_start)

    def _wait_pp_move(self, axis: str, state_name: str = "pp_moving") -> bool:
        self._wait_seconds(self._timing["pp_move_start_delay"], state_name)
        timeout = self._timing["pp_move_timeout"]

        if axis == "x":
            return self._wait_for(
                lambda: not self.read_pp_moving_x(),
                timeout=timeout, state_name=state_name,
            )
        elif axis == "z":
            return self._wait_for(
                lambda: not self.read_pp_moving_z(),
                timeout=timeout, state_name=state_name,
            )
        return False

    # =================================================================
    # FAULT INJECTION
    # =================================================================

    def inject_fault(self, fault_type: str, severity: int = 3):
        severity = max(1, min(5, severity))
        threshold = self._fault_config["emergency_threshold"]

        logger.warning("")
        logger.warning("🚨 ═══════════════════════════════════════════")
        logger.warning(f"🚨  STN2 FAULT: {fault_type} (severity {severity})")
        logger.warning("🚨 ═══════════════════════════════════════════")

        if fault_type == "overheat":
            self.faults.motor_overheat = True
            self.faults.motor_overheat_severity = severity
            self.temperature.inject_fault(severity)
            if severity >= threshold:
                self._trigger_emergency("OVERHEAT",
                    f"Motor critical! Severity {severity}/5")

        elif fault_type == "power":
            self.faults.power_fluctuation = True
            self.faults.power_severity = severity
            self.power.inject_fault(severity)
            if severity >= 5:
                self._trigger_emergency("POWER_FAILURE",
                    f"Total power loss! Severity {severity}/5")

        elif fault_type == "belt_slip":
            self.faults.belt_slippage = True
            self.faults.belt_slippage_severity = severity
            self._target_belt_speed = max(20, 100 - (severity * 15))

        elif fault_type == "sensor_drift":
            self.faults.sensor_drift = True
            self.faults.sensor_drift_amount = severity * 0.05

        elif fault_type == "gripper":
            self.faults.gripper_failure = True
            self.faults.gripper_failure_severity = severity

        elif fault_type == "pp_jam":
            self.faults.pp_jam = True
            self.faults.pp_jam_severity = severity
            self._trigger_emergency("PP_JAM",
                f"Pick & Place mechanical jam! Severity {severity}/5")

        else:
            logger.warning(f"   ⚠️ Unknown fault type for Station 2: {fault_type}")
            return

        self._log_fault_event("inject", f"{fault_type} sev={severity}")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/fault_injected", {
                "fault_type": fault_type,
                "severity": severity,
                "real_effects": True,
                "station": self.STATION_ID,
                "timestamp": datetime.now().isoformat(),
            })

    def clear_fault(self, fault_type: str = "all"):
        logger.info(f"✅ STN2: Clearing: {fault_type}")

        if fault_type in ("overheat", "all"):
            self.faults.motor_overheat = False
            self.faults.motor_overheat_severity = 0
            self.temperature.clear_fault()
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
        if fault_type in ("gripper", "all"):
            self.faults.gripper_failure = False
            self.faults.gripper_failure_severity = 0
        if fault_type in ("pp_jam", "all"):
            self.faults.pp_jam = False
            self.faults.pp_jam_severity = 0

        if self._emergency_active:
            self._emergency_active = False
            self._emergency_reason = ""
            if self._fault_downtime_start > 0:
                dt = time.time() - self._fault_downtime_start
                self._fault_counters["total_fault_downtime"] += dt
                self._fault_downtime_start = 0.0
            self._restore_intended()

        if self._fault_override_active:
            self._fault_override_active = False
            if self._fault_downtime_start > 0:
                dt = time.time() - self._fault_downtime_start
                self._fault_counters["total_fault_downtime"] += dt
                self._fault_downtime_start = 0.0
            self._restore_intended()

        self._log_fault_event("clear", fault_type)

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
            self._fault_override_active = False
            if self._fault_downtime_start > 0:
                dt = now - self._fault_downtime_start
                self._fault_counters["total_fault_downtime"] += dt
                self._fault_downtime_start = 0.0
            self._restore_intended()
            return

        if self._fault_override_active or self._emergency_active:
            return

        probs = self._fault_config["probabilities"]
        durs = self._fault_config["durations"]
        threshold = self._fault_config["emergency_threshold"]

        if self.faults.motor_overheat:
            sev = self.faults.motor_overheat_severity
            if sev >= threshold and not self._emergency_active:
                self._trigger_emergency("OVERHEAT", "Motor critical!")
                return
            if self._intended["belt"]:
                if random.random() < sev * probs["belt_stutter"]:
                    base, per = durs["belt_stutter"]
                    self._trigger_stutter(base + sev * per, "overheat")
                    return

        if self.faults.belt_slippage:
            sev = self.faults.belt_slippage_severity
            if self._intended["belt"]:
                if random.random() < sev * probs["belt_stutter"]:
                    base, per = durs["belt_stutter"]
                    self._trigger_stutter(base + sev * per, "belt_slip")
                    return

        if self.faults.power_fluctuation:
            sev = self.faults.power_severity
            if random.random() < sev * probs["power_brownout"]:
                if sev >= 5:
                    self._trigger_emergency("POWER_FAILURE", "Total loss!")
                else:
                    base, per = durs["power_brownout"]
                    self._trigger_brownout(base + sev * per)
                return

        if self.faults.gripper_failure and self._pp_has_item:
            sev = self.faults.gripper_failure_severity
            if self._pp_phase == "transferring":
                if random.random() < sev * probs["gripper_drop"]:
                    self._trigger_gripper_drop()
                    return

    def _trigger_stutter(self, duration: float, reason: str):
        self._fault_override_active = True
        self._fault_override_until = time.time() + duration
        self._fault_override_type = f"stutter({reason})"
        self._fault_downtime_start = time.time()
        self._write_raw("belt", False)
        self._fault_counters["stutters"] += 1
        logger.warning(f"   ⚡ STUTTER ({reason}): Belt OFF {duration:.2f}s")
        self._log_fault_event("stutter", f"{reason} {duration:.2f}s")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/fault_effect", {
                "effect": "stutter",
                "reason": reason,
                "duration": duration,
                "real_modbus_writes": ["belt=OFF"],
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
        logger.warning(f"   ⚡ BROWNOUT: All OFF {duration:.2f}s!")
        self._log_fault_event("brownout", f"All off {duration:.2f}s")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/fault_effect", {
                "effect": "brownout",
                "duration": duration,
                "real_modbus_writes": ["belt=OFF", "emitter=OFF", "stop_blade=OFF",
                                       "pp_move_x=OFF", "pp_move_z=OFF", "pp_grab=OFF"],
                "station": self.STATION_ID,
                "timestamp": datetime.now().isoformat(),
            })

    def _trigger_gripper_drop(self):
        self._write_raw("pp_grab", self._pp_config["grab_open_value"])
        self._pp_has_item = False
        self._fault_counters["gripper_failures"] += 1
        logger.warning("   🔧 GRIPPER FAILURE! Lid DROPPED!")
        self._log_fault_event("gripper_drop", "Lid dropped!")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/fault_effect", {
                "effect": "gripper_drop",
                "duration": 0,
                "real_modbus_writes": ["pp_grab=OPEN"],
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
        self.all_off()
        self._fault_counters["emergency_stops"] += 1
        logger.error(f"🚨 STN2 EMERGENCY: {reason} — {details}")
        self._log_fault_event("emergency", f"{reason}: {details}")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/emergency", {
                "active": True,
                "reason": reason,
                "details": details,
                "real_modbus_writes": ["belt=OFF", "emitter=OFF", "stop_blade=OFF",
                                       "pp_move_x=OFF", "pp_move_z=OFF", "pp_grab=OFF"],
                "station": self.STATION_ID,
                "timestamp": datetime.now().isoformat(),
            })

    def _restore_intended(self):
        for name, value in self._intended.items():
            self._write_raw(name, value)
        logger.info("   🔧 STN2 outputs RESTORED")

    def _log_fault_event(self, event_type: str, details: str):
        self._fault_events.append({
            "time": datetime.now().isoformat(),
            "type": event_type,
            "details": details,
        })
        if len(self._fault_events) > 50:
            self._fault_events.pop(0)

    # =================================================================
    # SIMULATIONS
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
        self.mqtt.publish(f"factory/{self.STATION_ID}/status", self.get_status())

    # =================================================================
    # MAIN RUN LOOP
    # =================================================================

    def run(self):
        self.is_running = True
        logger.info("🚀 Station 2 starting — PCB Installation")

        # ── Setup MQTT fault listener (NEW: proper routing) ──
        self._setup_mqtt_fault_listener()

        # Home P&P
        logger.info("STN2: Homing Pick & Place...")
        self.pp_grab(False)
        self.pp_move_z(False)
        self._wait_seconds(1.0, "s2_homing_z")
        self.pp_move_x(False)
        self._wait_seconds(1.0, "s2_homing_x")
        logger.info("STN2: ✅ P&P at home")

        try:
            while self.is_running:
                cycle_start = time.time()

                # ─── STATE 0: Wait for product ───
                logger.info("")
                logger.info("═" * 55)
                logger.info("STN2 ┃ STATE 0: Waiting for product...")
                self.belt(True)
                self.blade(True)
                self._pp_phase = "idle"
                self._signal_ready()

                if not self._wait_for(
                    self.read_sensor_station,
                    timeout=self._timing["product_timeout"],
                    state_name="s2_wait_product",
                ):
                    if not self.is_running:
                        break
                    logger.warning("STN2: Timeout, retrying...")
                    continue

                # ─── STATE 1: Product arrived ───
                logger.info("STN2 ┃ STATE 1: ✅ Product arrived!")
                self.belt(False)

                logger.info("STN2 ┃ Creating PCB lid...")
                self.emitter(True)
                self._wait_seconds(self._timing["lid_creation_time"], "s2_creating_lid")
                self.emitter(False)
                self._wait_seconds(self._timing["lid_settle_time"], "s2_lid_settle")

                # ─── STATE 2-9: P&P cycle ───
                logger.info("STN2 ┃ STATE 2: P&P ↓ DOWN to lid...")
                self._pp_phase = "picking"
                self.pp_move_z(True)
                if not self._wait_pp_move("z", "s2_pick_down"):
                    break

                logger.info("STN2 ┃ STATE 3: P&P GRAB...")
                self.pp_grab(True)
                self._wait_seconds(self._timing["grab_settle_time"], "s2_grabbing")
                self._pp_has_item = True

                logger.info("STN2 ┃ STATE 4: P&P ↑ UP...")
                self.pp_move_z(False)
                if not self._wait_pp_move("z", "s2_pick_up"):
                    break

                logger.info("STN2 ┃ STATE 5: P&P → PLACE...")
                self._pp_phase = "transferring"
                self.pp_move_x(True)
                if not self._wait_pp_move("x", "s2_transfer"):
                    break

                logger.info("STN2 ┃ STATE 6: P&P ↓ placing...")
                self._pp_phase = "placing"
                self.pp_move_z(True)
                if not self._wait_pp_move("z", "s2_place_down"):
                    break

                logger.info("STN2 ┃ STATE 7: P&P RELEASE...")
                self.pp_grab(False)
                self._pp_has_item = False
                self._pp_phase = "idle"
                self._wait_seconds(self._timing["release_settle_time"], "s2_releasing")

                logger.info("STN2 ┃ STATE 8: P&P ↑ UP...")
                self.pp_move_z(False)
                if not self._wait_pp_move("z", "s2_return_up"):
                    break

                logger.info("STN2 ┃ STATE 9: P&P → HOME...")
                self.pp_move_x(False)
                if not self._wait_pp_move("x", "s2_return_home"):
                    break

                # ─── STATE 10: Release product ───
                logger.info("STN2 ┃ STATE 10: Blade DOWN...")
                self.blade(False)
                self._wait_seconds(self._timing["blade_lower_time"], "s2_blade_lower")

                # ─── STATE 11: Send out ───
                logger.info("STN2 ┃ STATE 11: Belt ON → next station")
                self.belt(True)

                if self.read_sensor_station():
                    self._wait_for(
                        lambda: not self.read_sensor_station(),
                        timeout=15.0,
                        state_name="s2_product_leaving",
                    )
                self._wait_seconds(self._timing["product_exit_time"], "s2_product_clear")

                cycle_time = time.time() - cycle_start
                self.stats.products_completed += 1
                self.stats.add_cycle(cycle_time)
                logger.info(f"✅ STN2: Product #{self.stats.products_completed} ASSEMBLED! ({cycle_time:.1f}s)")

                if self.faults.has_any_fault:
                    logger.warning(f"   ⚠️ {self.faults.active_faults}")

                self._publish_mqtt(force=True)

        except KeyboardInterrupt:
            logger.info("Station 2 interrupted")
        finally:
            self.is_running = False
            self.all_off()

    # =================================================================
    # STATUS
    # =================================================================

    def start(self):
        pass

    def stop(self):
        self.all_off()
        self.is_running = False

    def get_status(self) -> Dict:
        return {
            "station": self.STATION_ID,
            "name": STATION2_CONFIG["name"],
            "state": self.state,
            "is_running": self.is_running,
            "emergency_active": self._emergency_active,
            "emergency_reason": self._emergency_reason,
            "timestamp": datetime.now().isoformat(),
            "pick_and_place": {
                "phase": self._pp_phase,
                "has_item": self._pp_has_item,
            },
            "sensors": {
                "motor_temperature": round(self.temperature.current, 2),
                "vibration": round(self.vibration.current, 2),
                "power_consumption": round(self.power.current, 3),
                "belt_speed": round(self._belt_speed, 1),
            },
            "counters": {
                "products_completed": self.stats.products_completed,
                "products_failed": self.stats.products_failed,
            },
            "timing": {
                "average_cycle_time": round(self.stats.average_cycle_time, 2),
            },
            "faults": {
                "has_fault": self.faults.has_any_fault,
                "active_faults": self.faults.active_faults,
            },
            "fault_effects": {
                "counters": dict(self._fault_counters),
                "recent_events": self._fault_events[-10:],
            },
        }

    def get_full_report(self) -> str:
        s = self.get_status()
        cnt = s["counters"]
        tim = s["timing"]
        fc = s["fault_effects"]["counters"]

        return f"""
╔══════════════════════════════════════════════════════════════╗
║       📺 STATION 2 — PCB INSTALLATION REPORT                ║
╠══════════════════════════════════════════════════════════════╣
║  Assembled:  {cnt['products_completed']:5d}    Failed: {cnt['products_failed']:5d}                  ║
║  Avg Cycle:  {tim['average_cycle_time']:5.2f}s                                  ║
║  ⚡ Stutters: {fc['stutters']:4d}  Brownouts: {fc['brownouts']:4d}  Grip: {fc['gripper_failures']:4d}         ║
║  ⚡ E-Stops:  {fc['emergency_stops']:4d}  Misreads:  {fc['sensor_misreads']:4d}  Down: {fc['total_fault_downtime']:5.1f}s  ║
╚══════════════════════════════════════════════════════════════╝"""