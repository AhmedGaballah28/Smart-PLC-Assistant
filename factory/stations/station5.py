"""
Station 5: Back Cover Assembly
TV Assembly Production Line

Simulates back cover pressing using a Pusher mechanism.
Cycle: Stop product → Wait 1.5s → Pusher EXTEND → Wait 2.5s → Retract → Release.

Components:
  - Belt Conveyor 5    (output 16)
  - Stop Blade 5       (output 17)
  - Pusher             (output 18)  — extend/retract
  - Stack Light Green  (output 24)  — processing
  - Stack Light Red    (output 25)  — fault
  - Entry Sensor 5     (input  12)
  - Station Sensor 5   (input  13)
  - Pusher Extended    (input  14)  — limit switch (TRUE = fully extended)
  - Pusher Retracted   (input  15)  — limit switch (TRUE = fully retracted)

FAULTS:
  overheat, power, belt_slip, sensor_drift, pusher_jam

MQTT TOPICS:
  Listens on: factory/station_5/faults/inject  (dedicated)
              factory/faults/inject              (broadcast, filtered)
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
# STATION 5 FAULT STATE
# ═══════════════════════════════════════════════════════════

@dataclass
class Station5FaultState(FaultState):
    pusher_jam: bool = False
    pusher_jam_severity: int = 0

    @property
    def has_any_fault(self) -> bool:
        return super().has_any_fault or self.pusher_jam

    @property
    def active_faults(self) -> List[str]:
        faults = super().active_faults
        if self.pusher_jam:
            faults.append(f"pusher_jam(sev={self.pusher_jam_severity})")
        return faults


# ═══════════════════════════════════════════════════════════
# STATION 5 CONFIG
# ═══════════════════════════════════════════════════════════

STATION5_IO_CONFIG = {
    "name": "Station 5 — Back Cover Assembly",
    "id": "station_5",
    "io": {
        "belt":             {"address": 16, "type": "output"},
        "stop_blade":       {"address": 17, "type": "output"},
        "pusher":           {"address": 18, "type": "output"},
        "light_green":      {"address": 24, "type": "output"},
        "light_red":        {"address": 25, "type": "output"},
        "sensor_entry":     {"address": 12, "type": "input"},
        "sensor_station":   {"address": 13, "type": "input"},
        "pusher_extended":  {"address": 14, "type": "input"},
        "pusher_retracted": {"address": 15, "type": "input"},
    },
    "timing": {
        "pre_push_wait":        1.5,    # Wait before extending pusher
        "push_hold_time":       2.5,    # Hold time while pusher extended
        "retract_settle_time":  0.5,    # Settle after retraction
        "exit_time":            1.0,
        "product_timeout":      120.0,
        "mechanical_timeout":   5.0,
        "sensor_clear_timeout": 30.0,
        "debounce_time":        0.3,
        "settle_time":          0.3,
    },
    "simulation": {
        "normal_temperature": 26.0,
        "temperature_noise":  0.3,
        "normal_vibration":   4.0,
        "vibration_noise":    0.8,
        "belt_motor_power":   0.9,
    },
}


# ═══════════════════════════════════════════════════════════
# STATION 5 CONTROLLER
# ═══════════════════════════════════════════════════════════

class Station5Controller:
    """
    Station 5: Back Cover Assembly with Pusher mechanism.

    State machine:
      STATE 0: Wait for product (belt ON, blade UP)
      STATE 1: Product arrived → Belt OFF → settle
      STATE 2: Pre-push wait (1.5s)
      STATE 3: PUSHER EXTEND → wait for extended limit switch
      STATE 4: Hold (2.5s simulated cover press)
      STATE 5: PUSHER RETRACT → wait for retract limit switch
      STATE 6: Belt ON → product exits
      (→ back to STATE 0)
    """

    def __init__(self, modbus_client: FactoryModbusClient,
                 mqtt_client=None,
                 upstream_ready: Optional[threading.Event] = None,
                 config: Optional[Dict] = None):
        if config is None:
            config = STATION5_IO_CONFIG
        self.modbus = modbus_client
        self.mqtt = mqtt_client
        self._upstream_ready = upstream_ready
        self.STATION_ID = config.get("id", "station_5")

        self._io = config["io"]
        self._timing = config["timing"]
        self._sim_config = config["simulation"]
        self._fault_config = FAULT_CONFIG

        # ─── State ───
        self.state = "stopped"
        self.is_running = False
        self._pusher_extended = False

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
        self.faults = Station5FaultState()

        # ─── Intended output states ───
        self._intended = {
            "belt": False,
            "stop_blade": False,
            "pusher": False,
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
            "pusher_jams": 0,
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

        logger.info(f"✅ Station 5 initialized (ID={self.STATION_ID})")

    # =================================================================
    # MQTT FAULT LISTENER
    # =================================================================

    def _setup_mqtt_fault_listener(self):
        if not self.mqtt or not self.mqtt.is_connected:
            return

        def on_fault_command(topic, data):
            try:
                if isinstance(data, str):
                    data = json.loads(data)
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

        self.mqtt.subscribe(f"factory/{self.STATION_ID}/faults/inject", on_fault_command)
        self.mqtt.subscribe("factory/faults/inject", on_fault_command)
        logger.info(f"📡 {self.STATION_ID}: Listening for faults")

    # =================================================================
    # I/O
    # =================================================================

    def _out_addr(self, name: str) -> int:
        return self._io[name]["address"]

    def _in_addr(self, name: str) -> int:
        return self._io[name]["address"]

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
        logger.info(f"   BELT 5: {'ON' if on else 'OFF'}")

    def blade(self, up: bool):
        self._intended["stop_blade"] = up
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("stop_blade", up)
        logger.info(f"   BLADE 5: {'UP' if up else 'DOWN'}")

    def pusher(self, extend: bool):
        self._intended["pusher"] = extend
        if not self._fault_override_active and not self._emergency_active:
            self._write_raw("pusher", extend)
        self._pusher_extended = extend
        logger.info(f"   PUSHER: {'EXTEND' if extend else 'RETRACT'}")

    def light_green(self, on: bool):
        self._write_raw("light_green", on)

    def light_red(self, on: bool):
        self._write_raw("light_red", on)

    def lights_off(self):
        self._write_raw("light_green", False)
        self._write_raw("light_red", False)

    def read_sensor_station(self) -> bool:
        addr = self._in_addr("sensor_station")
        inputs = self.modbus.read_inputs(addr, 1)
        value = inputs[0] if inputs else False
        if self.faults.sensor_drift:
            if random.random() < self.faults.sensor_drift_amount:
                value = not value
                self._fault_counters["sensor_misreads"] += 1
        return value

    def read_pusher_extended(self) -> bool:
        addr = self._in_addr("pusher_extended")
        inputs = self.modbus.read_inputs(addr, 1)
        return inputs[0] if inputs else False

    def read_pusher_retracted(self) -> bool:
        addr = self._in_addr("pusher_retracted")
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
            logger.info("   📡 Signaled upstream: Station 5 READY!")

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
        logger.warning(f"🚨 STN5 FAULT: {fault_type} (severity {severity})")

        if fault_type == "overheat":
            self.faults.motor_overheat = True
            self.faults.motor_overheat_severity = severity
            self.temperature.inject_fault(severity)
            if severity >= threshold:
                self._trigger_emergency("OVERHEAT", "Motor critical!")
        elif fault_type == "power":
            self.faults.power_fluctuation = True
            self.faults.power_severity = severity
            self.power.inject_fault(severity)
            if severity >= 5:
                self._trigger_emergency("POWER_FAILURE", "Total power loss!")
        elif fault_type == "belt_slip":
            self.faults.belt_slippage = True
            self.faults.belt_slippage_severity = severity
            self._target_belt_speed = max(20, 100 - (severity * 15))
        elif fault_type == "sensor_drift":
            self.faults.sensor_drift = True
            self.faults.sensor_drift_amount = severity * 0.05
        elif fault_type == "pusher_jam":
            self.faults.pusher_jam = True
            self.faults.pusher_jam_severity = severity
            if severity >= threshold:
                self._trigger_emergency("PUSHER_JAM", "Mechanical jam!")
        else:
            logger.warning(f"   ⚠️ Unknown fault type for Station 5: {fault_type}")
            return

        self._log_fault_event("inject", f"{fault_type} sev={severity}")
        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/fault_injected", {
                "fault_type": fault_type, "severity": severity,
                "station": self.STATION_ID, "timestamp": datetime.now().isoformat(),
            })

    def clear_fault(self, fault_type: str = "all"):
        logger.info(f"✅ STN5: Clearing: {fault_type}")
        if fault_type in ("overheat", "all"):
            self.faults.motor_overheat = False; self.temperature.clear_fault()
        if fault_type in ("power", "all"):
            self.faults.power_fluctuation = False; self.power.clear_fault()
        if fault_type in ("belt_slip", "all"):
            self.faults.belt_slippage = False; self._target_belt_speed = 100.0
        if fault_type in ("sensor_drift", "all"):
            self.faults.sensor_drift = False; self.faults.sensor_drift_amount = 0.0
        if fault_type in ("pusher_jam", "all"):
            self.faults.pusher_jam = False; self.faults.pusher_jam_severity = 0
        if self._emergency_active:
            self._emergency_active = False
            self._restore_intended()
        if self._fault_override_active:
            self._fault_override_active = False
            self._restore_intended()
        self._log_fault_event("clear", fault_type)

    def _fault_tick(self):
        now = time.time()
        if self._fault_override_active and now >= self._fault_override_until:
            self._fault_override_active = False
            if self._fault_downtime_start > 0:
                self._fault_counters["total_fault_downtime"] += now - self._fault_downtime_start
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
                self._trigger_emergency("OVERHEAT", "Motor critical!"); return
            if self._intended["belt"] and random.random() < sev * probs["belt_stutter"]:
                base, per = durs["belt_stutter"]
                self._trigger_stutter(base + sev * per, "overheat"); return
        if self.faults.belt_slippage:
            sev = self.faults.belt_slippage_severity
            if self._intended["belt"] and random.random() < sev * probs["belt_stutter"]:
                base, per = durs["belt_stutter"]
                self._trigger_stutter(base + sev * per, "belt_slip"); return
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
        logger.warning(f"   ⚡ STN5 STUTTER ({reason}): Belt OFF {duration:.2f}s")
        self._log_fault_event("stutter", f"{reason} {duration:.2f}s")

    def _trigger_brownout(self, duration: float):
        self._fault_override_active = True
        self._fault_override_until = time.time() + duration
        self._fault_override_type = "brownout"
        self._fault_downtime_start = time.time()
        self.all_off()
        self._fault_counters["brownouts"] += 1
        logger.warning(f"   ⚡ STN5 BROWNOUT: All OFF {duration:.2f}s")
        self._log_fault_event("brownout", f"All off {duration:.2f}s")

    def _trigger_emergency(self, reason: str, details: str):
        if self._emergency_active:
            return
        self._emergency_active = True
        self._emergency_reason = f"{reason}: {details}"
        self._fault_downtime_start = time.time()
        self._fault_override_active = False
        self.all_off()
        self._fault_counters["emergency_stops"] += 1
        logger.error(f"🚨 STN5 EMERGENCY: {reason} — {details}")
        self._log_fault_event("emergency", f"{reason}: {details}")

    def _restore_intended(self):
        for name, value in self._intended.items():
            self._write_raw(name, value)
        logger.info("   🔧 STN5 outputs RESTORED")

    def _log_fault_event(self, event_type: str, details: str):
        self._fault_events.append({
            "time": datetime.now().isoformat(),
            "type": event_type, "details": details,
        })
        if len(self._fault_events) > 50:
            self._fault_events.pop(0)

    # =================================================================
    # SIMULATIONS + MQTT
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
        logger.info("🚀 Station 5 starting — Back Cover Assembly")
        self._setup_mqtt_fault_listener()

        # Initialize pusher to retracted position
        logger.info("STN5: Initializing pusher (retract)...")
        self.pusher(False)
        self._wait_seconds(0.5, "s5_init")

        try:
            while self.is_running:
                cycle_start = time.time()

                # ─── STATE 0: Wait for product ───
                logger.info("")
                logger.info("═" * 55)
                logger.info("STN5 ┃ STATE 0: Waiting for product...")
                self.belt(True)
                self.blade(True)
                self.pusher(False)
                self.lights_off()

                if self.read_sensor_station():
                    logger.info("STN5 ┃ Sensor still active — waiting to clear...")
                    if not self._wait_for(
                        lambda: not self.read_sensor_station(),
                        timeout=self._timing["sensor_clear_timeout"],
                        state_name="s5_wait_clear",
                    ):
                        if not self.is_running:
                            break
                        continue
                    self._wait_seconds(self._timing["debounce_time"], "s5_debounce")

                self._signal_ready()

                if not self._wait_for(
                    self.read_sensor_station,
                    timeout=self._timing["product_timeout"],
                    state_name="s5_wait_product",
                ):
                    if not self.is_running:
                        break
                    continue

                # ─── STATE 1: Product arrived ───
                logger.info("STN5 ┃ STATE 1: ✅ Product arrived!")
                self.belt(False)
                self._wait_seconds(self._timing["settle_time"], "s5_settle")

                # ─── STATE 2: Pre-push wait ───
                logger.info(f"STN5 ┃ STATE 2: ⏱️ Pre-push wait ({self._timing['pre_push_wait']}s)...")
                self.light_green(True)
                self._wait_seconds(self._timing["pre_push_wait"], "s5_pre_push")

                # ─── STATE 3: PUSHER EXTEND ───
                logger.info("STN5 ┃ STATE 3: 🔧 Pusher EXTENDING...")
                push_duration = self._timing["mechanical_timeout"]
                if self.faults.pusher_jam:
                    sev = self.faults.pusher_jam_severity
                    extra = sev * 0.8
                    logger.warning(f"   ⚠️ Pusher jam! Extra delay: {extra:.1f}s")
                    self._fault_counters["pusher_jams"] += 1
                    self._wait_seconds(extra, "s5_jam_delay")

                self.pusher(True)
                if not self._wait_for(
                    self.read_pusher_extended,
                    timeout=self._timing["mechanical_timeout"],
                    state_name="s5_extending",
                ):
                    logger.warning("STN5: Extend timeout — continuing")

                # ─── STATE 4: Hold (cover press) ───
                hold_time = self._timing["push_hold_time"]
                if self.faults.motor_overheat:
                    hold_time += self.faults.motor_overheat_severity * 0.4
                logger.info(f"STN5 ┃ STATE 4: 🏭 Pressing cover ({hold_time:.1f}s)...")
                self._wait_seconds(hold_time, "s5_pressing")
                logger.info("STN5 ┃ ✅ Back cover PRESSED!")

                # ─── STATE 5: PUSHER RETRACT ───
                logger.info("STN5 ┃ STATE 5: 🔧 Pusher RETRACTING...")
                self.pusher(False)
                if not self._wait_for(
                    self.read_pusher_retracted,
                    timeout=self._timing["mechanical_timeout"],
                    state_name="s5_retracting",
                ):
                    logger.warning("STN5: Retract timeout — continuing")
                self._wait_seconds(self._timing["retract_settle_time"], "s5_retract_settle")
                self.lights_off()

                # ─── STATE 6: Release ───
                logger.info("STN5 ┃ STATE 6: Blade DOWN → Belt ON")
                self.blade(False)
                self._wait_seconds(0.3, "s5_blade_lower")
                self.belt(True)

                if self.read_sensor_station():
                    self._wait_for(
                        lambda: not self.read_sensor_station(),
                        timeout=15.0,
                        state_name="s5_product_leaving",
                    )
                self._wait_seconds(self._timing["exit_time"], "s5_product_clear")

                # ─── Cycle complete ───
                cycle_time = time.time() - cycle_start
                self.stats.products_completed += 1
                self.stats.add_cycle(cycle_time)
                logger.info(f"✅ STN5: Product #{self.stats.products_completed}"
                            f" BACK COVER ASSEMBLED! ({cycle_time:.1f}s)")
                if self.faults.has_any_fault:
                    logger.warning(f"   ⚠️ {self.faults.active_faults}")
                self._publish_mqtt(force=True)

        except KeyboardInterrupt:
            logger.info("Station 5 interrupted")
        finally:
            self.is_running = False
            self.pusher(False)
            self.all_off()

    # =================================================================
    # STATUS
    # =================================================================

    def stop(self):
        self.all_off()
        self.is_running = False

    def get_status(self) -> Dict:
        return {
            "station": self.STATION_ID,
            "name": STATION5_IO_CONFIG["name"],
            "state": self.state,
            "is_running": self.is_running,
            "emergency_active": self._emergency_active,
            "emergency_reason": self._emergency_reason,
            "timestamp": datetime.now().isoformat(),
            "pusher": {
                "extended": self._pusher_extended,
            },
            "sensors": {
                "temperature": round(self.temperature.current, 2),
                "vibration": round(self.vibration.current, 2),
                "power_kw": round(self.power.current, 3),
                "belt_speed_pct": round(self._belt_speed, 1),
            },
            "counters": {
                "products_completed": self.stats.products_completed,
                "avg_cycle_time": round(self.stats.average_cycle_time, 2),
                "oee": round(self.stats.oee, 1),
            },
            "faults": {
                "has_fault": self.faults.has_any_fault,
                "active": self.faults.active_faults,
            },
        }

    def get_full_report(self) -> str:
        s = self.get_status()
        lines = [
            f"\n{'═'*55}",
            f"  STATION 5 — Back Cover Assembly  Report",
            f"{'═'*55}",
            f"  State      : {s['state']}",
            f"  Products   : {s['counters']['products_completed']}",
            f"  Avg Cycle  : {s['counters']['avg_cycle_time']}s",
            f"  OEE        : {s['counters']['oee']}%",
            f"  Temperature: {s['sensors']['temperature']}°C",
            f"  Vibration  : {s['sensors']['vibration']} mm/s",
            f"  Power      : {s['sensors']['power_kw']} kW",
            f"  Pusher     : {'EXTENDED' if s['pusher']['extended'] else 'RETRACTED'}",
            f"  Faults     : {s['faults']['active'] or 'none'}",
            f"  Fault Events (last 5):",
        ]
        for ev in self._fault_events[-5:]:
            lines.append(f"    [{ev['time'][11:19]}] {ev['type']}: {ev['details']}")
        lines.append(f"{'═'*55}\n")
        return "\n".join(lines)
