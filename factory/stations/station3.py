"""
Station 3: Display Panel Mounting
TV Assembly Production Line

MQTT TOPICS:
  Listens on: factory/station_3/faults/inject  (dedicated)
              factory/faults/inject              (broadcast, filtered by station field)
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
from factory.config import FAULT_CONFIG

from factory.stations.station1 import (
    TemperatureSimulator,
    VibrationSimulator,
    PowerSimulator,
    ProductionStats,
    FaultState,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# STATION 3 FAULT STATE
# ═══════════════════════════════════════════════════════════

@dataclass
class Station3FaultState(FaultState):
    positioner_jam: bool = False
    positioner_jam_severity: int = 0

    @property
    def has_any_fault(self) -> bool:
        return (super().has_any_fault or self.positioner_jam)

    @property
    def active_faults(self) -> List[str]:
        faults = super().active_faults
        if self.positioner_jam:
            faults.append(f"positioner_jam(sev={self.positioner_jam_severity})")
        return faults


# ═══════════════════════════════════════════════════════════
# STATION 3 I/O CONFIG
# ═══════════════════════════════════════════════════════════

STATION3_IO_CONFIG = {
    "name": "Station 3 — Display Panel Mounting",
    "io": {
        "belt":        {"address": 11, "type": "output"},
        "pos_raise":   {"address": 12, "type": "output"},
        "pos_clamp":   {"address": 13, "type": "output"},
        "sensor":      {"address": 9,  "type": "input"},
        "pos_clamped": {"address": 7,  "type": "input"},
        "pos_limit":   {"address": 8,  "type": "input"},
    },
    "timing": {
        "mount_time": 5.0,
        "exit_time": 1.5,
        "mechanical_timeout": 5.0,
        "product_timeout": 120.0,
        "debounce_time": 0.3,
        "settle_time": 0.3,
    },
    "simulation": {
        "normal_temperature": 22.0,
        "temperature_noise": 0.3,
        "normal_vibration": 1.0,
        "vibration_noise": 0.2,
        "belt_motor_power": 0.8,
    },
}


# ═══════════════════════════════════════════════════════════
# STATION 3 CONTROLLER
# ═══════════════════════════════════════════════════════════

class Station3Controller:
    """
    Station 3: Display Panel Mounting using Positioning Left Bar.

    MQTT TOPICS:
      Listens on: factory/station_3/faults/inject  (dedicated)
                  factory/faults/inject              (broadcast, filtered)
    """

    STATION_ID = "station_3"

    def __init__(self, modbus_client: FactoryModbusClient,
                 mqtt_client=None,
                 upstream_ready: Optional[threading.Event] = None):
        self.modbus = modbus_client
        self.mqtt = mqtt_client
        self._upstream_ready = upstream_ready

        self._io = STATION3_IO_CONFIG["io"]
        self._timing = STATION3_IO_CONFIG["timing"]
        self._sim_config = STATION3_IO_CONFIG["simulation"]
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
        self.faults = Station3FaultState()

        # ─── Intended output states ───
        self._intended = {
            "belt": False,
            "pos_raise": False,
            "pos_clamp": False,
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
            "positioner_jams": 0,
            "emergency_stops": 0,
            "sensor_misreads": 0,
            "total_fault_downtime": 0.0,
        }
        self._fault_events = []
        self._fault_downtime_start = 0.0

        # ─── Belt ───
        self._belt_speed = 0.0
        self._target_belt_speed = 100.0

        # ─── MQTT ───
        self._last_mqtt_publish = 0.0
        self.MQTT_PUBLISH_INTERVAL = 1.0

        logger.info(f"✅ Station 3 initialized (ID={self.STATION_ID})")

    # =================================================================
    # MQTT FAULT ROUTING
    # =================================================================

    def _setup_mqtt_fault_listener(self):
        """
        Subscribe to BOTH:
          - factory/station_3/faults/inject  (dedicated topic)
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
        logger.info(f"   BELT 3: {'ON' if on else 'OFF'}")

    def positioner_raise(self, up: bool):
        self._intended["pos_raise"] = up
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("pos_raise", up)
        logger.info(f"   POS BAR: {'RAISED' if up else 'LOWERED'}")

    def positioner_clamp(self, clamp: bool):
        self._intended["pos_clamp"] = clamp
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("pos_clamp", clamp)
        logger.info(f"   POS CLAMP: {'CLAMPED' if clamp else 'OPEN'}")

    def read_sensor(self) -> bool:
        addr = self._in_addr("sensor")
        inputs = self.modbus.read_inputs(addr, 1)
        value = inputs[0] if inputs else False
        if self.faults.sensor_drift:
            if random.random() < self.faults.sensor_drift_amount:
                value = not value
                self._fault_counters["sensor_misreads"] += 1
                logger.warning("   📡 DRIFT: Sensor 5 misread!")
        return value

    def read_clamped(self) -> bool:
        addr = self._in_addr("pos_clamped")
        inputs = self.modbus.read_inputs(addr, 1)
        return inputs[0] if inputs else False

    def read_limit(self) -> bool:
        addr = self._in_addr("pos_limit")
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
            logger.info("   📡 Signaled upstream: Station 3 READY!")

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
        end_time = time.time() + seconds

        while self.is_running and time.time() < end_time:
            belt_on = (self._intended["belt"]
                       and not self._fault_override_active
                       and not self._emergency_active)
            self._update_simulations(belt_on)
            self._fault_tick()
            self._publish_mqtt()

            if self._emergency_active:
                saved = self.state
                self.state = "EMERGENCY_STOP"
                pause_start = time.time()
                while self._emergency_active and self.is_running:
                    self._update_simulations(False)
                    self._publish_mqtt()
                    time.sleep(0.1)
                if not self.is_running:
                    return
                end_time += (time.time() - pause_start)
                self.state = saved

            time.sleep(0.05)

    # =================================================================
    # FAULT INJECTION
    # =================================================================

    def inject_fault(self, fault_type: str, severity: int = 3):
        severity = max(1, min(5, severity))
        threshold = self._fault_config["emergency_threshold"]

        logger.warning("")
        logger.warning("🚨 ═══════════════════════════════════════════")
        logger.warning(f"🚨  STN3 FAULT: {fault_type} (severity {severity})")
        logger.warning("🚨 ═══════════════════════════════════════════")

        if fault_type == "overheat":
            self.faults.motor_overheat = True
            self.faults.motor_overheat_severity = severity
            self.temperature.inject_fault(severity)
            if severity >= threshold:
                self._trigger_emergency("OVERHEAT", f"Motor critical!")

        elif fault_type == "power":
            self.faults.power_fluctuation = True
            self.faults.power_severity = severity
            self.power.inject_fault(severity)
            if severity >= 5:
                self._trigger_emergency("POWER_FAILURE", f"Total power loss!")

        elif fault_type == "belt_slip":
            self.faults.belt_slippage = True
            self.faults.belt_slippage_severity = severity
            self._target_belt_speed = max(20, 100 - (severity * 15))

        elif fault_type == "sensor_drift":
            self.faults.sensor_drift = True
            self.faults.sensor_drift_amount = severity * 0.05

        elif fault_type == "positioner_jam":
            self.faults.positioner_jam = True
            self.faults.positioner_jam_severity = severity
            if severity >= threshold:
                self._trigger_emergency("POSITIONER_JAM", f"Mechanical jam!")

        else:
            logger.warning(f"   ⚠️ Unknown fault type for Station 3: {fault_type}")
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
        logger.info(f"✅ STN3: Clearing: {fault_type}")

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
        if fault_type in ("positioner_jam", "all"):
            self.faults.positioner_jam = False
            self.faults.positioner_jam_severity = 0

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
                "real_modbus_writes": ["belt=OFF", "pos_raise=OFF", "pos_clamp=OFF"],
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
        logger.error(f"🚨 STN3 EMERGENCY: {reason} — {details}")
        self._log_fault_event("emergency", f"{reason}: {details}")

        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/emergency", {
                "active": True,
                "reason": reason,
                "details": details,
                "real_modbus_writes": ["belt=OFF", "pos_raise=OFF", "pos_clamp=OFF"],
                "station": self.STATION_ID,
                "timestamp": datetime.now().isoformat(),
            })

    def _restore_intended(self):
        for name, value in self._intended.items():
            self._write_raw(name, value)
        logger.info("   🔧 STN3 outputs RESTORED")

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
        logger.info("🚀 Station 3 starting — Display Panel Mounting")

        # ── Setup MQTT fault listener (NEW: proper routing) ──
        self._setup_mqtt_fault_listener()

        # Initialize bar
        logger.info("STN3: Initializing positioning bar...")
        self.positioner_clamp(False)
        self.positioner_raise(False)
        self._wait_seconds(1.0, "s3_init")

        try:
            while self.is_running:
                cycle_start = time.time()

                # ─── STATE 0: Wait for product ───
                logger.info("")
                logger.info("═" * 55)
                logger.info("STN3 ┃ STATE 0: Waiting for product...")
                self.belt(True)
                self.positioner_raise(False)
                self.positioner_clamp(False)

                if self.read_sensor():
                    logger.info("STN3 ┃ Sensor still active — waiting to clear...")
                    if not self._wait_for(
                        lambda: not self.read_sensor(),
                        timeout=30.0,
                        state_name="s3_wait_clear",
                    ):
                        if not self.is_running:
                            break
                        continue
                    self._wait_seconds(self._timing["debounce_time"], "s3_debounce")

                self._signal_ready()

                if not self._wait_for(
                    self.read_sensor,
                    timeout=self._timing["product_timeout"],
                    state_name="s3_wait_product",
                ):
                    if not self.is_running:
                        break
                    continue

                # ─── STATE 1: Product arrived ───
                logger.info("STN3 ┃ STATE 1: ✅ Product arrived!")
                self.belt(False)
                self._wait_seconds(self._timing["settle_time"], "s3_settle")

                # ─── STATE 2: CLAMP ───
                logger.info("STN3 ┃ STATE 2: 🔧 Clamping...")
                self.positioner_clamp(True)

                if self.faults.positioner_jam:
                    sev = self.faults.positioner_jam_severity
                    extra = sev * 0.5
                    logger.warning(f"   ⚠️ Positioner jam! Extra delay: {extra:.1f}s")
                    self._fault_counters["positioner_jams"] += 1
                    self._wait_seconds(extra, "s3_jam_delay")

                    if self.mqtt and self.mqtt.is_connected:
                        self.mqtt.publish(f"factory/{self.STATION_ID}/fault_effect", {
                            "effect": "positioner_jam",
                            "duration": extra,
                            "real_modbus_writes": ["pos_clamp=ON (delayed)"],
                            "station": self.STATION_ID,
                            "timestamp": datetime.now().isoformat(),
                        })

                if not self._wait_for(
                    self.read_clamped,
                    timeout=self._timing["mechanical_timeout"],
                    state_name="s3_clamping",
                ):
                    logger.warning("STN3: Clamp timeout — continuing")

                # ─── STATE 3: MOUNT (5 seconds) ───
                mount_time = self._timing["mount_time"]
                if self.faults.belt_slippage:
                    mount_time += self.faults.belt_slippage_severity * 0.3

                logger.info(f"STN3 ┃ STATE 3: 📺 MOUNTING ({mount_time:.1f}s)...")
                self._wait_seconds(mount_time, "s3_mounting")
                logger.info("STN3 ┃ ✅ Display MOUNTED!")

                # ─── STATE 4: UNCLAMP ───
                logger.info("STN3 ┃ STATE 4: 🔧 Unclamping...")
                self.positioner_clamp(False)
                if not self._wait_for(
                    lambda: not self.read_clamped(),
                    timeout=self._timing["mechanical_timeout"],
                    state_name="s3_unclamping",
                ):
                    logger.warning("STN3: Unclamp timeout — continuing")

                # ─── STATE 5: RAISE bar ───
                logger.info("STN3 ┃ STATE 5: ⬆️ Raising bar...")
                self.positioner_raise(True)

                if self.faults.positioner_jam:
                    sev = self.faults.positioner_jam_severity
                    extra = sev * 0.5
                    logger.warning(f"   ⚠️ Positioner jam on raise! Extra: {extra:.1f}s")
                    self._fault_counters["positioner_jams"] += 1
                    self._wait_seconds(extra, "s3_raise_jam")

                if not self._wait_for(
                    self.read_limit,
                    timeout=self._timing["mechanical_timeout"],
                    state_name="s3_raising",
                ):
                    logger.warning("STN3: Raise timeout — continuing")

                # ─── STATE 6: Exit ───
                logger.info("STN3 ┃ STATE 6: 🔄 Belt ON — exiting...")
                self.belt(True)

                if self.read_sensor():
                    if not self._wait_for(
                        lambda: not self.read_sensor(),
                        timeout=15.0,
                        state_name="s3_product_leaving",
                    ):
                        logger.warning("STN3: Exit timeout")

                self._wait_seconds(self._timing["exit_time"], "s3_product_clear")

                # ─── STATE 7: LOWER bar ───
                logger.info("STN3 ┃ STATE 7: ⬇️ Lowering bar...")
                self.positioner_raise(False)

                if not self._wait_for(
                    lambda: not self.read_limit(),
                    timeout=self._timing["mechanical_timeout"],
                    state_name="s3_lowering",
                ):
                    logger.warning("STN3: Lower timeout — continuing")

                # ─── Cycle complete ───
                cycle_time = time.time() - cycle_start
                self.stats.products_completed += 1
                self.stats.add_cycle(cycle_time)
                logger.info(f"✅ STN3: Product #{self.stats.products_completed}"
                            f" DISPLAY MOUNTED! ({cycle_time:.1f}s)")

                if self.faults.has_any_fault:
                    logger.warning(f"   ⚠️ {self.faults.active_faults}")

                self._publish_mqtt(force=True)

        except KeyboardInterrupt:
            logger.info("Station 3 interrupted")
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
            "name": STATION3_IO_CONFIG["name"],
            "state": self.state,
            "is_running": self.is_running,
            "emergency_active": self._emergency_active,
            "emergency_reason": self._emergency_reason,
            "timestamp": datetime.now().isoformat(),
            "positioning_bar": {
                "clamped": self._intended["pos_clamp"],
                "raised": self._intended["pos_raise"],
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
║       📺 STATION 3 — DISPLAY PANEL MOUNTING REPORT           ║
╠══════════════════════════════════════════════════════════════╣
║  Completed:  {cnt['products_completed']:5d}    Failed: {cnt['products_failed']:5d}                  ║
║  Avg Cycle:  {tim['average_cycle_time']:5.2f}s                                  ║
║  ⚡ Stutters: {fc['stutters']:4d}  Brownouts: {fc['brownouts']:4d}  Jams: {fc['positioner_jams']:4d}         ║
║  ⚡ E-Stops:  {fc['emergency_stops']:4d}  Misreads:  {fc['sensor_misreads']:4d}  Down: {fc['total_fault_downtime']:5.1f}s  ║
╚══════════════════════════════════════════════════════════════╝"""