"""
Machining Center Controllers — TV Assembly Production Line

Machining Center A: Blue Raw Material → CNC (3s) → Blue Product Base → Station 1
Machining Center B: Green Raw Material → CNC (6s) → Green Product Lid → Station 2 P&P

MQTT TOPICS:
  factory/machining_a/faults/inject   factory/machining_b/faults/inject
  factory/faults/inject (broadcast)
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
from factory.config import MACHINING_A_CONFIG, MACHINING_B_CONFIG, FAULT_CONFIG
from factory.stations.station1 import (
    TemperatureSimulator, VibrationSimulator, PowerSimulator,
    ProductionStats, FaultState,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# MACHINING FAULT STATE
# ═══════════════════════════════════════════════════════════

@dataclass
class MachiningFaultState(FaultState):
    cnc_jam: bool = False
    cnc_jam_severity: int = 0
    material_error: bool = False
    material_error_severity: int = 0

    @property
    def has_any_fault(self) -> bool:
        return super().has_any_fault or self.cnc_jam or self.material_error

    @property
    def active_faults(self) -> List[str]:
        faults = super().active_faults
        if self.cnc_jam:
            faults.append(f"cnc_jam(sev={self.cnc_jam_severity})")
        if self.material_error:
            faults.append(f"material_error(sev={self.material_error_severity})")
        return faults


# ═══════════════════════════════════════════════════════════
# MACHINING CENTER CONTROLLER (Base Class)
# ═══════════════════════════════════════════════════════════

class MachiningCenterController:
    """
    Base controller for Factory I/O Machining Center.

    State Machine:
      INIT  → reset, set production type, start station
      EMIT  → emit raw material into entry bay
      LOAD  → wait for robot to load CNC (Is Busy = True)
      MACHINE → CNC processing, monitor progress 0→100
      EXIT  → product on exit bay, subclass handles exit
    """

    MQTT_PUBLISH_INTERVAL = 1.0

    def __init__(self, config: dict, modbus_client, mqtt_client=None, wait_to_emit_fn=None):
        self.modbus = modbus_client
        self.mqtt = mqtt_client
        self._wait_to_emit_fn = wait_to_emit_fn
        self._config = config
        self.STATION_ID = config["station_id"]
        self._produce_lids = config["produce_lids"]
        self._machining_time = config["machining_time"]
        self._io = config["io"]
        self._regs = config["registers"]
        self._timing = config["timing"]
        self._sim_cfg = config["simulation"]
        self._fault_config = FAULT_CONFIG

        self.state = "stopped"
        self.is_running = False
        self._last_progress = 0.0

        self.temperature = TemperatureSimulator(
            ambient=self._sim_cfg["normal_temperature"],
            current=self._sim_cfg["normal_temperature"],
            noise=self._sim_cfg["temperature_noise"],
        )
        self.vibration = VibrationSimulator(
            base_level=self._sim_cfg["normal_vibration"],
            noise=self._sim_cfg["vibration_noise"],
        )
        self.power = PowerSimulator(running_power=self._sim_cfg["cnc_motor_power"])
        self.stats = ProductionStats()
        self.faults = MachiningFaultState()

        self._fault_override_active = False
        self._fault_override_until = 0.0
        self._fault_override_type = ""
        self._emergency_active = False
        self._emergency_reason = ""
        self._fault_counters = {
            "stutters": 0, "brownouts": 0, "cnc_jams": 0,
            "material_errors": 0, "emergency_stops": 0,
            "sensor_misreads": 0, "total_fault_downtime": 0.0,
        }
        self._fault_events = []
        self._fault_downtime_start = 0.0
        self._last_mqtt_publish = 0.0

        product = "lids" if self._produce_lids else "bases"
        logger.info(f"✅ {self.STATION_ID} initialized (produces {product})")

    # =================================================================
    # MQTT FAULT ROUTING
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
        logger.info(f"📡 {self.STATION_ID}: MQTT fault listener active")

    # =================================================================
    # I/O METHODS
    # =================================================================

    def _addr(self, name: str) -> int:
        return self._io[name]["address"]

    def _write(self, name: str, value: bool):
        self.modbus.write_output(self._addr(name), value)

    def _read(self, name: str) -> bool:
        inputs = self.modbus.read_inputs(self._addr(name), 1)
        return inputs[0] if inputs else False

    def emitter(self, on: bool):
        self._write("emitter", on)
        logger.info(f"   {self.STATION_ID} EMITTER: {'ON' if on else 'OFF'}")

    def mc_start(self, on: bool):
        self._write("start", on)

    def mc_stop(self, on: bool):
        self._write("stop", on)

    def mc_reset(self, on: bool):
        self._write("reset", on)

    def mc_produce_lids(self, on: bool):
        self._write("produce_lids", on)

    def read_is_busy(self) -> bool:
        val = self._read("is_busy")
        if self.faults.sensor_drift and random.random() < self.faults.sensor_drift_amount:
            val = not val
            self._fault_counters["sensor_misreads"] += 1
            logger.warning(f"   📡 DRIFT: {self.STATION_ID} Is Busy misread!")
        return val

    def read_has_error(self) -> bool:
        return self._read("has_error")

    def read_exit_sensor(self) -> bool:
        if "exit_sensor" not in self._io:
            return False
        return self._read("exit_sensor")

    def read_progress(self) -> float:
        val = self.modbus.read_register(self._regs["progress"])
        if val is not None:
            self._last_progress = float(val)
        return self._last_progress

    def all_off(self):
        for name, info in self._io.items():
            if info["type"] == "output":
                self.modbus.write_output(info["address"], False)

    # =================================================================
    # WAIT HELPERS
    # =================================================================

    def _wait_for(self, condition_fn, timeout=30.0, state_name="waiting") -> bool:
        self.state = state_name
        deadline = time.time() + timeout
        while self.is_running:
            self._update_simulations(True)
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
                deadline = time.time() + timeout
            if condition_fn():
                return True
            if time.time() > deadline:
                logger.error(f"❌ {self.STATION_ID} TIMEOUT in {state_name}!")
                return False
            time.sleep(0.05)
        return False

    def _wait_seconds(self, seconds, state_name="waiting"):
        self.state = state_name
        end = time.time() + seconds
        while self.is_running and time.time() < end:
            self._update_simulations(True)
            self._fault_tick()
            self._publish_mqtt()
            if self._emergency_active:
                saved = self.state
                self.state = "EMERGENCY_STOP"
                p = time.time()
                while self._emergency_active and self.is_running:
                    self._update_simulations(False)
                    self._publish_mqtt()
                    time.sleep(0.1)
                if not self.is_running:
                    return
                end += (time.time() - p)
                self.state = saved
            time.sleep(0.05)

    # =================================================================
    # FAULT INJECTION
    # =================================================================

    def inject_fault(self, fault_type: str, severity: int = 3):
        severity = max(1, min(5, severity))
        threshold = self._fault_config["emergency_threshold"]
        logger.warning(f"🚨 {self.STATION_ID} FAULT: {fault_type} (severity {severity})")

        if fault_type == "overheat":
            self.faults.motor_overheat = True
            self.faults.motor_overheat_severity = severity
            self.temperature.inject_fault(severity)
            if severity >= threshold:
                self._trigger_emergency("OVERHEAT", "CNC motor critical!")
        elif fault_type == "power":
            self.faults.power_fluctuation = True
            self.faults.power_severity = severity
            self.power.inject_fault(severity)
            if severity >= 5:
                self._trigger_emergency("POWER_FAILURE", "Total power loss!")
        elif fault_type == "sensor_drift":
            self.faults.sensor_drift = True
            self.faults.sensor_drift_amount = severity * 0.05
        elif fault_type == "cnc_jam":
            self.faults.cnc_jam = True
            self.faults.cnc_jam_severity = severity
            if severity >= threshold:
                self._trigger_emergency("CNC_JAM", "Mechanical jam!")
        elif fault_type == "material_error":
            self.faults.material_error = True
            self.faults.material_error_severity = severity
        else:
            logger.warning(f"   ⚠️ Unknown fault: {fault_type}")
            return

        self._log_fault_event("inject", f"{fault_type} sev={severity}")
        if self.mqtt and self.mqtt.is_connected:
            self.mqtt.publish(f"factory/{self.STATION_ID}/fault_injected", {
                "fault_type": fault_type, "severity": severity,
                "station": self.STATION_ID, "timestamp": datetime.now().isoformat(),
            })

    def clear_fault(self, fault_type: str = "all"):
        logger.info(f"✅ {self.STATION_ID}: Clearing: {fault_type}")
        if fault_type in ("overheat", "all"):
            self.faults.motor_overheat = False
            self.faults.motor_overheat_severity = 0
            self.temperature.clear_fault()
        if fault_type in ("power", "all"):
            self.faults.power_fluctuation = False
            self.faults.power_severity = 0
            self.power.clear_fault()
        if fault_type in ("sensor_drift", "all"):
            self.faults.sensor_drift = False
            self.faults.sensor_drift_amount = 0.0
        if fault_type in ("cnc_jam", "all"):
            self.faults.cnc_jam = False
            self.faults.cnc_jam_severity = 0
        if fault_type in ("material_error", "all"):
            self.faults.material_error = False
            self.faults.material_error_severity = 0
        if self._emergency_active:
            self._emergency_active = False
            self._emergency_reason = ""
            if self._fault_downtime_start > 0:
                self._fault_counters["total_fault_downtime"] += time.time() - self._fault_downtime_start
                self._fault_downtime_start = 0.0
        if self._fault_override_active:
            self._fault_override_active = False
            if self._fault_downtime_start > 0:
                self._fault_counters["total_fault_downtime"] += time.time() - self._fault_downtime_start
                self._fault_downtime_start = 0.0
        self._log_fault_event("clear", fault_type)

    # =================================================================
    # FAULT EFFECTS ENGINE
    # =================================================================

    def _fault_tick(self):
        now = time.time()
        if self._fault_override_active and now >= self._fault_override_until:
            self._fault_override_active = False
            if self._fault_downtime_start > 0:
                self._fault_counters["total_fault_downtime"] += now - self._fault_downtime_start
                self._fault_downtime_start = 0.0
            return
        if self._fault_override_active or self._emergency_active:
            return

        probs = self._fault_config["probabilities"]
        durs = self._fault_config["durations"]
        threshold = self._fault_config["emergency_threshold"]

        if self.faults.motor_overheat:
            sev = self.faults.motor_overheat_severity
            if sev >= threshold:
                self._trigger_emergency("OVERHEAT", "CNC motor critical!")
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
        if self.faults.cnc_jam:
            sev = self.faults.cnc_jam_severity
            if random.random() < sev * 0.03:
                dur = 1.0 + sev * 0.5
                self._fault_override_active = True
                self._fault_override_until = time.time() + dur
                self._fault_override_type = "cnc_jam"
                self._fault_downtime_start = time.time()
                self._fault_counters["cnc_jams"] += 1
                logger.warning(f"   🔧 CNC JAM: paused {dur:.1f}s")

    def _trigger_brownout(self, duration):
        self._fault_override_active = True
        self._fault_override_until = time.time() + duration
        self._fault_override_type = "brownout"
        self._fault_downtime_start = time.time()
        self._fault_counters["brownouts"] += 1
        logger.warning(f"   ⚡ BROWNOUT: {self.STATION_ID} paused {duration:.2f}s!")

    def _trigger_emergency(self, reason, details):
        if self._emergency_active:
            return
        self._emergency_active = True
        self._emergency_reason = f"{reason}: {details}"
        self._fault_downtime_start = time.time()
        self._fault_override_active = False
        self.mc_stop(True)
        self._fault_counters["emergency_stops"] += 1
        logger.error(f"🚨 {self.STATION_ID} EMERGENCY: {reason} — {details}")
        self._log_fault_event("emergency", f"{reason}: {details}")

    def _log_fault_event(self, event_type, details):
        self._fault_events.append({
            "time": datetime.now().isoformat(), "type": event_type, "details": details,
        })
        if len(self._fault_events) > 50:
            self._fault_events.pop(0)

    # =================================================================
    # SIMULATIONS
    # =================================================================

    def _update_simulations(self, cnc_running):
        self.temperature.update(cnc_running)
        self.vibration.update(cnc_running, 1.0 if cnc_running else 0.0)
        self.power.update(cnc_running)

    def _publish_mqtt(self, force=False):
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
        product = "BASES" if not self._produce_lids else "LIDS"
        logger.info(f"🚀 {self.STATION_ID} starting — Producing {product}")
        self._setup_mqtt_fault_listener()

        # ── INIT: Reset → configure → start ──
        logger.info(f"{self.STATION_ID}: Initializing...")
        self.mc_stop(False)
        self.mc_reset(True)
        self._wait_seconds(self._timing["reset_pulse"], "mc_reset")
        self.mc_reset(False)
        self._wait_seconds(0.5, "mc_post_reset")
        self.mc_produce_lids(self._produce_lids)
        self._wait_seconds(0.3, "mc_config")
        self.mc_start(True)
        self._wait_seconds(0.5, "mc_starting")
        logger.info(f"{self.STATION_ID}: ✅ Started!")

        try:
            while self.is_running:
                cycle_start = time.time()

                # ─── STATE 1: EMIT RAW MATERIAL ───
                logger.info("")
                logger.info("═" * 55)

                if self._wait_to_emit_fn:
                    self.state = "wait_sync"
                    # Wait here until the synchronizer allows emission
                    self._wait_to_emit_fn(self)
                    if not self.is_running:
                        break

                sync_delay = self._timing.get("emit_sync_delay", 0.0)
                if sync_delay > 0:
                    self._wait_seconds(sync_delay, "emit_sync_delay")

                logger.info(f"{self.STATION_ID} ┃ STATE 1: Emitting raw material...")
                self.state = "emitting"

                if self.faults.material_error:
                    extra = self.faults.material_error_severity * 0.3
                    logger.warning(f"   ⚠️ Material feed error! Extra delay: {extra:.1f}s")
                    self._fault_counters["material_errors"] += 1
                    self._wait_seconds(extra, "material_error_delay")

                self.emitter(True)
                self._wait_seconds(self._timing["emitter_pulse"], "emitting")
                self.emitter(False)
                self.stats.products_created += 1
                logger.info(f"{self.STATION_ID} ┃ Raw material emitted ✅")

                # ─── STATE 2: WAIT FOR LOADING ───
                logger.info(f"{self.STATION_ID} ┃ STATE 2: Waiting for robot to load CNC...")
                if not self._wait_for(
                    self.read_is_busy,
                    timeout=self._timing["load_timeout"],
                    state_name="wait_loading",
                ):
                    if not self.is_running:
                        break
                    if self.read_has_error():
                        logger.error(f"{self.STATION_ID} ┃ ❌ HAS ERROR — resetting...")
                        self.mc_reset(True)
                        self._wait_seconds(self._timing["reset_pulse"], "error_reset")
                        self.mc_reset(False)
                        self._wait_seconds(0.5, "post_error_reset")
                        self.mc_start(True)
                        continue
                    logger.warning(f"{self.STATION_ID} ┃ ⚠️ Load timeout — retrying")
                    continue
                logger.info(f"{self.STATION_ID} ┃ CNC loaded ✅")

                # ─── STATE 3: MACHINING ───
                logger.info(f"{self.STATION_ID} ┃ STATE 3: Machining (~{self._machining_time}s)...")
                self.state = "machining"
                last_log_pct = -10

                while self.is_running:
                    self._update_simulations(True)
                    self._fault_tick()
                    self._publish_mqtt()

                    if self._emergency_active:
                        saved = self.state
                        self.state = "EMERGENCY_STOP"
                        self.mc_stop(True)
                        while self._emergency_active and self.is_running:
                            self._update_simulations(False)
                            self._publish_mqtt()
                            time.sleep(0.1)
                        if not self.is_running:
                            break
                        self.mc_stop(False)
                        self.mc_start(True)
                        self.state = saved

                    progress = self.read_progress()
                    if progress - last_log_pct >= 25:
                        logger.info(f"   ⚙️ Progress: {progress:.0f}%")
                        last_log_pct = progress

                    if not self.read_is_busy():
                        break
                    time.sleep(0.1)

                if not self.is_running:
                    break
                logger.info(f"{self.STATION_ID} ┃ ✅ Machining COMPLETE!")

                # ─── STATE 4: EXIT (subclass handles) ───
                self._handle_exit(cycle_start)
                if not self.is_running:
                    break

                # ─── Cycle done ───
                cycle_time = time.time() - cycle_start
                self.stats.products_completed += 1
                self.stats.add_cycle(cycle_time)
                logger.info(f"✅ {self.STATION_ID}: Product #{self.stats.products_completed} "
                            f"COMPLETE! ({cycle_time:.1f}s)")
                if self.faults.has_any_fault:
                    logger.warning(f"   ⚠️ {self.faults.active_faults}")
                self._publish_mqtt(force=True)

        except KeyboardInterrupt:
            logger.info(f"{self.STATION_ID} interrupted")
        finally:
            self.is_running = False
            self.mc_stop(True)
            self.all_off()

    def _handle_exit(self, cycle_start):
        """Override in subclass."""
        self._wait_seconds(1.0, "exit_settle")

    # =================================================================
    # STATUS & REPORTS
    # =================================================================

    def start(self):
        pass

    def stop(self):
        self.mc_stop(True)
        self.is_running = False

    def get_status(self) -> Dict:
        return {
            "station": self.STATION_ID,
            "name": self._config["name"],
            "state": self.state,
            "is_running": self.is_running,
            "emergency_active": self._emergency_active,
            "emergency_reason": self._emergency_reason,
            "timestamp": datetime.now().isoformat(),
            "machining": {
                "produce_lids": self._produce_lids,
                "progress": self._last_progress,
            },
            "sensors": {
                "cnc_temperature": round(self.temperature.current, 2),
                "vibration": round(self.vibration.current, 2),
                "power_consumption": round(self.power.current, 3),
            },
            "counters": {
                "products_created": self.stats.products_created,
                "products_completed": self.stats.products_completed,
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
            },
        }

    def get_full_report(self) -> str:
        s = self.get_status()
        cnt = s["counters"]
        fc = s["fault_effects"]["counters"]
        product_type = "Green Lids" if self._produce_lids else "Blue Bases"
        return f"""
╔══════════════════════════════════════════════════════╗
║  🏭 {self.STATION_ID.upper():15s} — {product_type:15s}  ║
╠══════════════════════════════════════════════════════╣
  Created: {cnt['products_created']:5d}   Completed: {cnt['products_completed']:5d}
  Avg Cycle: {s['timing']['average_cycle_time']:5.2f}s
  CNC Jams: {fc['cnc_jams']:4d}   Material Errors: {fc['material_errors']:4d}
  Brownouts: {fc['brownouts']:4d}  E-Stops: {fc['emergency_stops']:4d}
  Sensor Misreads: {fc['sensor_misreads']:4d}
  Downtime: {fc['total_fault_downtime']:5.1f}s
╚══════════════════════════════════════════════════════╝"""


# ═══════════════════════════════════════════════════════════
# MACHINING CENTER A — Blue Base Producer
# ═══════════════════════════════════════════════════════════

class MachiningBaseController(MachiningCenterController):
    """
    Produces Blue Bases. Exit: sends base via belt toward Station 1.
    """

    def __init__(self, modbus_client, mqtt_client=None, downstream_ready=None, wait_to_emit_fn=None, config=None):
        if config is None:
            config = MACHINING_A_CONFIG
        super().__init__(config, modbus_client, mqtt_client, wait_to_emit_fn)
        self._downstream_ready = downstream_ready

    def exit_belt(self, on: bool):
        self._write("exit_belt", on)

    def _handle_exit(self, cycle_start):
        logger.info(f"{self.STATION_ID} ┃ STATE 4: Blue Base → Station 1")
        self.state = "exit_to_stn1"

        if self._downstream_ready is not None:
            logger.info(f"{self.STATION_ID} ┃ ⏳ Waiting for Station 1 ready...")
            while self.is_running and not self._downstream_ready.is_set():
                self._update_simulations(False)
                self._publish_mqtt()
                time.sleep(0.1)
            if not self.is_running:
                return
            self._downstream_ready.clear()
            logger.info(f"{self.STATION_ID} ┃ ✅ Station 1 ready!")

        self.exit_belt(True)
        if "exit_sensor" in self._io:
            self._wait_for(self.read_exit_sensor, timeout=self._timing["exit_timeout"],
                           state_name="wait_exit_detect")
            self._wait_for(lambda: not self.read_exit_sensor(),
                           timeout=self._timing["exit_timeout"],
                           state_name="wait_exit_clear")
        else:
            self._wait_seconds(4.0, "exit_travel")
        self.exit_belt(False)
        logger.info(f"{self.STATION_ID} ┃ ✅ Base sent to Station 1!")


# ═══════════════════════════════════════════════════════════
# MACHINING CENTER B — Green Lid Producer
# ═══════════════════════════════════════════════════════════

class MachiningLidController(MachiningCenterController):
    """
    Produces Green Lids. Exit: signals lid_ready, waits for P&P pickup.
    """

    def __init__(self, modbus_client, mqtt_client=None, lid_ready_event=None, wait_to_emit_fn=None, config=None):
        if config is None:
            config = MACHINING_B_CONFIG
        super().__init__(config, modbus_client, mqtt_client, wait_to_emit_fn)
        self._lid_ready = lid_ready_event

    def _handle_exit(self, cycle_start):
        logger.info(f"{self.STATION_ID} ┃ STATE 4: Green Lid on exit bay")
        self.state = "wait_pickup"

        if self._lid_ready is not None:
            self._lid_ready.set()
            logger.info(f"{self.STATION_ID} ┃ 📢 Signaled STN2: lid ready!")

            if "exit_sensor" in self._io:
                logger.info(f"{self.STATION_ID} ┃ ⏳ Waiting for P&P pickup...")
                self._wait_for(self.read_exit_sensor, timeout=self._timing["exit_timeout"],
                               state_name="wait_lid_on_bay")
                self._wait_for(lambda: not self.read_exit_sensor(),
                               timeout=self._timing["exit_timeout"],
                               state_name="wait_pickup")
            else:
                logger.info(f"{self.STATION_ID} ┃ ⏳ Waiting for lid_ready consumed...")
                while self.is_running and self._lid_ready.is_set():
                    self._update_simulations(False)
                    self._publish_mqtt()
                    time.sleep(0.1)
        else:
            self._wait_seconds(5.0, "wait_pickup_timed")

        if self.is_running:
            logger.info(f"{self.STATION_ID} ┃ ✅ Lid picked up!")
