"""
Run Station 1 + Station 2 + Station 3 + Station 6 + Station 7 together (SYNCHRONIZED)

SYNC CHAIN:
  Station 7 signals 'ready' → Station 6 releases product
  Station 6 signals 'ready' → Station 3 releases product
  Station 3 signals 'ready' → Station 2 releases product
  Station 2 signals 'ready' → Station 1 releases product

START ORDER: Downstream first!
  1. Station 7 starts (most downstream — sorting & output)
  2. Station 6 starts (QC inspection)
  3. Station 3 starts
  4. Station 2 starts
  5. Station 1 starts (most upstream — creates products)

PRODUCT FLOW:
  STN1 (Chassis) → STN2 (PCB) → STN3 (Display) → STN6 (QC) → STN7 (Sort) → Good/Reject

FAULT INJECTION — ALL REAL EFFECTS:
  Station 1: overheat, vibration, power, belt_slip, sensor_drift
  Station 2: overheat, power, belt_slip, sensor_drift, gripper, pp_jam
  Station 3: overheat, power, belt_slip, sensor_drift, positioner_jam
  Station 6: overheat, power, belt_slip, sensor_drift, vision_error
  Station 7: overheat, power, belt_slip, sensor_drift, sorter_jam, misroute
    - overheat:     REAL — increases arm move / inspect time (station slows down)
    - power:        REAL — belt randomly turns OFF (brownout in Factory I/O)
    - belt_slip:    REAL — belt stutters (visible product jerking)
    - sensor_drift: REAL — diffuse sensor returns wrong value
    - vision_error: REAL — vision sensor returns wrong value (wrong QC decisions)
    - sorter_jam:   REAL — pivot arm ignores command (product goes wrong bin!)
    - misroute:     REAL — pivot arm inverted (good→reject, reject→good!)

MQTT FAULT TOPICS:
  factory/station_1/faults/inject
  factory/station_2/faults/inject
  factory/station_3/faults/inject
  factory/station_6/faults/inject
  factory/station_7/faults/inject
  factory/faults/inject (broadcast)
"""

import logging
import sys
import os
import threading
import time
import json
import random
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from factory.modbus_client import FactoryModbusClient
from factory.stations.station1 import Station1Controller
from factory.stations.station2 import Station2Controller
from factory.stations.station3 import Station3Controller
from factory.stations.station6 import Station6, SyncedStation6, VISION_ITEMS
from factory.stations.station7 import Station7, SyncedStation7
from factory.stations.transfer import TransferStation, SyncedTransferStation
from factory.stations.warehouse import WarehouseController

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# THREAD-SAFE MODBUS WRAPPER
# ═══════════════════════════════════════════════════════════

class ThreadSafeModbus:
    """
    Wraps FactoryModbusClient with a threading.Lock.

    Without this, two threads calling write_output() or read_inputs()
    at the same time causes "Failed to write/read" errors because
    the underlying Modbus TCP socket gets corrupted.

    This wrapper ensures only ONE thread talks to Factory I/O at a time.
    """

    def __init__(self, modbus_client: FactoryModbusClient):
        self._client = modbus_client
        self._lock = threading.Lock()

    def connect(self):
        return self._client.connect()

    def disconnect(self):
        with self._lock:
            return self._client.disconnect()

    def write_output(self, address, value):
        with self._lock:
            return self._client.write_output(address, value)

    def read_inputs(self, address, count):
        with self._lock:
            return self._client.read_inputs(address, count)

    def read_register(self, address):
        with self._lock:
            return self._client.read_register(address)

    def write_register(self, address, value):
        with self._lock:
            return self._client.write_register(address, value)

    def read_holding_register(self, address):
        with self._lock:
            return self._client.read_holding_register(address)

    # Pass through any other methods/attributes
    def __getattr__(self, name):
        return getattr(self._client, name)


# ═══════════════════════════════════════════════════════════
# TRANSITION BELT ADDRESSES
# ═══════════════════════════════════════════════════════════

BELT_1B = 1      # Transition belt: Station 1 → Station 2
BELT_2B = 10     # Transition belt: Station 2 → Station 3
BELT_3B = 14     # Transition belt: Station 3 → Station 6
BELT_4B = 20     # Transition belt: Station 6 → Station 7
BELT_5B = 27     # Transition belt: Station 7 → Transfer/Warehouse


# ═══════════════════════════════════════════════════════════
# SYNCED STATION 1 — Waits for Station 2 before releasing
# ═══════════════════════════════════════════════════════════

class SyncedStation1(Station1Controller):
    """
    Station 1 with downstream synchronization.

    Overrides blade() to wait for Station 2 before releasing products.
    When blade goes UP→DOWN (releasing a product), it first waits
    for the downstream_ready event.

    Does NOT override run() — inherits base which calls
    _setup_mqtt_fault_listener() automatically.
    """

    def __init__(self, modbus_client, mqtt_client=None, downstream_ready=None):
        super().__init__(modbus_client, mqtt_client=mqtt_client)
        self._downstream_ready = downstream_ready
        if downstream_ready:
            logger.info("   🔗 STN1: Downstream sync ENABLED (waits for Station 2)")

    def blade(self, up):
        """
        Override: wait for Station 2 before releasing product.

        Only waits when blade goes UP→DOWN (releasing):
          - _intended["stop_blade"] was True (UP, holding product)
          - up = False (going DOWN, releasing)
        """
        is_releasing = (not up) and self._intended.get("stop_blade", False)

        if is_releasing and self._downstream_ready is not None:
            logger.info("")
            logger.info("   ⏸️  STN1: Waiting for Station 2 to be ready...")
            self.state = "wait_downstream"

            wait_start = time.time()
            last_log = 0

            while not self._downstream_ready.is_set() and self.is_running:
                belt_on = (self._intended.get("belt1", False)
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
                        break
                    self.state = saved

                elapsed = time.time() - wait_start
                if elapsed - last_log >= 5.0:
                    logger.info(f"   ⏸️  STN1: Still waiting... ({elapsed:.0f}s)")
                    last_log = elapsed

                time.sleep(0.1)

            if self.is_running:
                self._downstream_ready.clear()
                elapsed = time.time() - wait_start
                logger.info(f"   ✅ STN1: Station 2 READY! (waited {elapsed:.1f}s)")
                logger.info("")

        super().blade(up)


# ═══════════════════════════════════════════════════════════
# SYNCED STATION 2 — Waits for Station 3 before releasing
# ═══════════════════════════════════════════════════════════

class SyncedStation2(Station2Controller):
    """
    Station 2 with:
      1. Sensor-clear check before waiting for new product
      2. Downstream sync — waits for Station 3 before releasing
    """

    def __init__(self, modbus_client, mqtt_client=None,
                 upstream_ready=None, downstream_ready=None):
        super().__init__(modbus_client, mqtt_client=mqtt_client,
                         upstream_ready=upstream_ready)
        self._downstream_ready = downstream_ready
        if downstream_ready:
            logger.info("   🔗 STN2: Downstream sync ENABLED (waits for Station 3)")

    def blade(self, up):
        """Override: wait for Station 3 before releasing product."""
        is_releasing = (not up) and self._intended.get("stop_blade", False)

        if is_releasing and self._downstream_ready is not None:
            logger.info("")
            logger.info("   ⏸️  STN2: Waiting for Station 3 to be ready...")
            self.state = "wait_downstream"

            wait_start = time.time()
            last_log = 0

            while not self._downstream_ready.is_set() and self.is_running:
                belt_on = (self._intended.get("belt", False)
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
                        break
                    self.state = saved

                elapsed = time.time() - wait_start
                if elapsed - last_log >= 5.0:
                    logger.info(f"   ⏸️  STN2: Still waiting... ({elapsed:.0f}s)")
                    last_log = elapsed

                time.sleep(0.1)

            if self.is_running:
                self._downstream_ready.clear()
                elapsed = time.time() - wait_start
                logger.info(f"   ✅ STN2: Station 3 READY! (waited {elapsed:.1f}s)")
                logger.info("")

        super().blade(up)

    def run(self):
        """Same as Station2Controller.run() but adds sensor-clear check."""
        self.is_running = True
        logger.info("🚀 Station 2 starting — PCB Installation")

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

                logger.info("")
                logger.info("═" * 55)
                logger.info("STN2 ┃ STATE 0: Preparing...")
                self.belt(True)
                self.blade(True)
                self._pp_phase = "idle"

                # FIX: Wait for sensor to be CLEAR first
                if self.read_sensor_station():
                    logger.info("STN2 ┃ Sensor still active — waiting for clear...")
                    if not self._wait_for(
                        lambda: not self.read_sensor_station(),
                        timeout=30.0,
                        state_name="s2_wait_clear",
                    ):
                        if not self.is_running:
                            break
                        logger.warning("STN2: Sensor stuck, retrying...")
                        continue
                    logger.info("STN2 ┃ ✅ Sensor clear!")
                    self._wait_seconds(0.5, "s2_debounce")

                logger.info("STN2 ┃ Waiting for product from Station 1...")
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

                logger.info("STN2 ┃ STATE 1: ✅ Product arrived!")
                self.belt(False)

                logger.info("STN2 ┃ Creating PCB lid...")
                self.emitter(True)
                self._wait_seconds(self._timing["lid_creation_time"], "s2_creating_lid")
                self.emitter(False)
                self._wait_seconds(self._timing["lid_settle_time"], "s2_lid_settle")

                logger.info("STN2 ┃ STATE 2: P&P ↓ DOWN to lid...")
                self._pp_phase = "picking"
                self.pp_move_z(True)
                if not self._wait_pp_move("z", "s2_pick_down"):
                    logger.error("STN2: P&P Z failed!")
                    break

                logger.info("STN2 ┃ STATE 3: P&P GRAB...")
                self.pp_grab(True)
                self._wait_seconds(self._timing["grab_settle_time"], "s2_grabbing")

                if self.read_pp_item_detected():
                    logger.info("STN2 ┃ ✅ Item in gripper!")
                    self._pp_has_item = True
                else:
                    logger.warning("STN2 ┃ ⚠️ Item NOT detected, continuing...")
                    self._pp_has_item = True

                logger.info("STN2 ┃ STATE 4: P&P ↑ UP with lid...")
                self.pp_move_z(False)
                if not self._wait_pp_move("z", "s2_pick_up"):
                    break

                logger.info("STN2 ┃ STATE 5: P&P → PLACE position...")
                self._pp_phase = "transferring"
                self.pp_move_x(True)
                if not self._wait_pp_move("x", "s2_transfer"):
                    break

                if self.faults.gripper_failure and not self.read_pp_item_detected():
                    logger.warning("STN2 ┃ ⚠️ Lid DROPPED during transfer!")
                    self.stats.products_failed += 1

                logger.info("STN2 ┃ STATE 6: P&P ↓ placing lid...")
                self._pp_phase = "placing"
                self.pp_move_z(True)
                if not self._wait_pp_move("z", "s2_place_down"):
                    break

                logger.info("STN2 ┃ STATE 7: P&P RELEASE...")
                self.pp_grab(False)
                self._pp_has_item = False
                self._pp_phase = "idle"
                self._wait_seconds(self._timing["release_settle_time"], "s2_releasing")
                logger.info("STN2 ┃ ✅ Lid placed! (Base + Lid = Assembled!)")

                logger.info("STN2 ┃ STATE 8: P&P ↑ UP...")
                self.pp_move_z(False)
                if not self._wait_pp_move("z", "s2_return_up"):
                    break

                logger.info("STN2 ┃ STATE 9: P&P → PICK position...")
                self.pp_move_x(False)
                if not self._wait_pp_move("x", "s2_return_home"):
                    break
                logger.info("STN2 ┃ ✅ P&P home")

                logger.info("STN2 ┃ STATE 10: Blade DOWN...")
                self.blade(False)
                self._wait_seconds(self._timing["blade_lower_time"], "s2_blade_lower")

                logger.info("STN2 ┃ STATE 11: Belt ON → Station 3")
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

                logger.info("")
                logger.info(f"✅ STN2: Product #{self.stats.products_completed}"
                            f" ASSEMBLED! ({cycle_time:.1f}s)")

                if self.faults.has_any_fault:
                    logger.warning(f"   ⚠️ {self.faults.active_faults}")
                    fc = self._fault_counters
                    logger.warning(
                        f"   ⚡ stut={fc['stutters']} brown={fc['brownouts']} "
                        f"grip={fc['gripper_failures']} mis={fc['sensor_misreads']}"
                    )

                self._publish_mqtt(force=True)

        except KeyboardInterrupt:
            logger.info("Station 2 interrupted")
        finally:
            self.is_running = False
            self.all_off()


# ═══════════════════════════════════════════════════════════
# SYNCED STATION 3 — Waits for Station 6 before accepting
# ═══════════════════════════════════════════════════════════

class SyncedStation3(Station3Controller):
    """
    Station 3 with downstream synchronization to Station 6.

    Overrides _signal_ready() to wait for Station 6 before
    telling Station 2 it's ready to accept a new product.
    """

    def __init__(self, modbus_client, mqtt_client=None,
                 upstream_ready=None, downstream_ready=None):
        super().__init__(modbus_client, mqtt_client=mqtt_client,
                         upstream_ready=upstream_ready)
        self._downstream_ready = downstream_ready
        if downstream_ready:
            logger.info("   🔗 STN3: Downstream sync ENABLED (waits for Station 6)")

    def _signal_ready(self):
        """
        Override: wait for Station 6 before signaling upstream.

        Flow:
          1. Station 3 finishes processing → goes to STATE 0
          2. Before telling Station 2 "I'm ready", checks if Station 6 is ready
          3. Waits for station6_ready event
          4. Then signals station3_ready (upstream) → Station 2 can release
        """
        if self._downstream_ready is not None:
            logger.info("")
            logger.info("   ⏸️  STN3: Waiting for Station 6 to be ready...")
            self.state = "wait_downstream"

            wait_start = time.time()
            last_log = 0

            while not self._downstream_ready.is_set() and self.is_running:
                belt_on = (self._intended.get("belt", False)
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
                        break
                    self.state = saved

                elapsed = time.time() - wait_start
                if elapsed - last_log >= 5.0:
                    logger.info(f"   ⏸️  STN3: Still waiting... ({elapsed:.0f}s)")
                    last_log = elapsed

                time.sleep(0.1)

            if self.is_running:
                self._downstream_ready.clear()
                elapsed = time.time() - wait_start
                logger.info(f"   ✅ STN3: Station 6 READY! (waited {elapsed:.1f}s)")
                logger.info("")

        # Now signal upstream (Station 2) that we're ready
        super()._signal_ready()


# ═══════════════════════════════════════════════════════════
# LINE STATION 6 — Real fault injection + line integration
# ═══════════════════════════════════════════════════════════

class LineStation6(SyncedStation6):
    """
    Station 6 (Quality Control) with REAL fault injection + MQTT listener.
    """
    _station_num = 6

    def __init__(self, modbus_client, mqtt_client=None,
                 upstream_ready_event=None, downstream_ready_event=None):
        super().__init__(modbus_client, mqtt_client,
                         upstream_ready_event, downstream_ready_event)

        # Fault tracking
        self._active_faults = {}       # {fault_type: severity}
        self._fault_counters = {
            'vision_errors': 0,
            'brownouts': 0,
            'belt_stutters': 0,
            'sensor_misreads': 0,
            'inspect_delays': 0,
            'emergency_stops': 0,
        }
        self._original_inspect_time = self.INSPECT_TIME
        self._fault_lock = threading.Lock()

    # ── Compatibility properties ──

    @property
    def is_running(self):
        return self.running

    @is_running.setter
    def is_running(self, value):
        self.running = value

    def run(self):
        """Alias for main() — compatible with Station 1/2/3 threading"""
        self.is_running = True
        self._setup_mqtt_fault_listener()
        self.main()

    # ── MQTT Fault Listener ──

    def _setup_mqtt_fault_listener(self):
        if not self.mqtt:
            return
        topics = [
            f"factory/station_{self._station_num}/faults/inject",
            "factory/faults/inject"  # Broadcast
        ]
        def _on_fault_msg(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode())
                station_target = payload.get("station")
                if station_target is not None and station_target != self._station_num:
                    return  # Ignore if targeted to another station
                if "clear" in payload:
                    self.clear_fault(payload["clear"])
                elif "fault" in payload:
                    self.inject_fault(payload["fault"], payload.get("severity", 3))
            except Exception:
                pass
        for topic in topics:
            self.mqtt.subscribe(topic, _on_fault_msg)
        logger.info(f"  📡 STN{self._station_num}: MQTT fault listener active on {topics}")

    # ── REAL Fault Injection ──

    def inject_fault(self, fault_type, severity=3):
        with self._fault_lock:
            severity = min(max(int(severity), 1), 5)
            self._active_faults[fault_type] = severity
            logger.warning(f"  ⚡ STN6: Fault '{fault_type}' INJECTED (severity {severity})")

            if fault_type == "overheat":
                multiplier = 1 + severity * 0.5
                self.INSPECT_TIME = self._original_inspect_time * multiplier
                self._fault_counters['inspect_delays'] += 1
                logger.warning(f"  🌡️ STN6: Inspect time increased to {self.INSPECT_TIME:.1f}s "
                               f"(was {self._original_inspect_time:.1f}s)")
            elif fault_type == "vision_error":
                logger.warning(f"  📷 STN6: Vision sensor will return WRONG values "
                               f"({severity * 10}% chance per read)")
            elif fault_type == "power":
                logger.warning(f"  ⚡ STN6: Belt will suffer brownouts "
                               f"({severity * 6}% chance per activation)")
            elif fault_type == "belt_slip":
                logger.warning(f"  🔄 STN6: Belt will stutter "
                               f"({severity * 8}% chance per activation)")
            elif fault_type == "sensor_drift":
                logger.warning(f"  📡 STN6: Sensor will drift "
                               f"({severity * 5}% chance per read)")

    def clear_fault(self, fault_type):
        with self._fault_lock:
            if fault_type == "all":
                self._active_faults.clear()
                self.INSPECT_TIME = self._original_inspect_time
                logger.info("  ✅ STN6: All faults cleared")
                logger.info(f"  🔧 STN6: Inspect time restored to {self.INSPECT_TIME:.1f}s")
            elif fault_type in self._active_faults:
                del self._active_faults[fault_type]
                logger.info(f"  ✅ STN6: Fault '{fault_type}' cleared")
                if fault_type == "overheat":
                    self.INSPECT_TIME = self._original_inspect_time
                    logger.info(f"  🔧 STN6: Inspect time restored to {self.INSPECT_TIME:.1f}s")

    # ── Method overrides for REAL fault effects ──

    def belt(self, on):
        """Override: power brownout and belt slip affect actual belt output."""
        if on and "power" in self._active_faults:
            severity = self._active_faults["power"]
            if random.random() < severity * 0.06:
                self._fault_counters['brownouts'] += 1
                logger.warning("[STN6] ⚡ POWER BROWNOUT — belt OFF for 0.5s!")
                super().belt(False)
                time.sleep(0.5)

        if on and "belt_slip" in self._active_faults:
            severity = self._active_faults["belt_slip"]
            if random.random() < severity * 0.08:
                self._fault_counters['belt_stutters'] += 1
                logger.warning("[STN6] 🔄 BELT SLIP — stuttering!")
                super().belt(True)
                time.sleep(0.15)
                super().belt(False)
                time.sleep(0.2)
                super().belt(True)
                time.sleep(0.15)

        super().belt(on)

    def read_sensors(self):
        """Override: sensor drift returns inverted readings."""
        result = super().read_sensors()

        if "sensor_drift" in self._active_faults:
            severity = self._active_faults["sensor_drift"]
            if random.random() < severity * 0.05:
                self._fault_counters['sensor_misreads'] += 1
                original = result["sensor_6"]
                result["sensor_6"] = not original
                logger.warning(f"[STN6] 📡 SENSOR DRIFT — read {result['sensor_6']} "
                               f"(actual: {original})")

        return result

    def read_vision_sensor(self):
        """Override: vision error returns random wrong value."""
        real_value = super().read_vision_sensor()

        if "vision_error" in self._active_faults:
            severity = self._active_faults["vision_error"]
            if random.random() < severity * 0.10:
                self._fault_counters['vision_errors'] += 1
                wrong_values = [v for v in range(10) if v != real_value]
                wrong_value = random.choice(wrong_values)
                real_name = VISION_ITEMS.get(real_value, "?")
                wrong_name = VISION_ITEMS.get(wrong_value, "?")
                logger.warning(f"[STN6] 📷 VISION ERROR — read {wrong_value} ({wrong_name}) "
                               f"instead of {real_value} ({real_name})!")
                return wrong_value

        return real_value

    # ── Status & Reports ──

    def get_status(self):
        """Return status dict (compatible with Stations 1-3 format)."""
        rate = (self.pass_count / self.product_count * 100) if self.product_count > 0 else 0
        return {
            'state': str(self.state),
            'counters': {
                'products_completed': self.product_count,
                'products_passed': self.pass_count,
                'products_failed': self.fail_count,
            },
            'qc': {
                'pass_rate': round(rate, 1),
                'last_result': self.last_qc_result,
                'last_vision': self.last_vision_value,
                'last_vision_item': VISION_ITEMS.get(self.last_vision_value, "?"),
                'expected_value': self.EXPECTED_VALUE,
            },
            'faults': {
                'has_fault': len(self._active_faults) > 0,
                'active': list(self._active_faults.keys()),
            },
            'emergency_active': False,
        }

    def get_full_report(self):
        """Return formatted production report."""
        rate = (self.pass_count / self.product_count * 100) if self.product_count > 0 else 0
        fc = self._fault_counters
        faults = ", ".join(f"{k}(sev{v})" for k, v in self._active_faults.items()) or "None"
        return f"""
╔══════════════════════════════════════╗
║  Station 6: Quality Control Report  ║
╠══════════════════════════════════════╣
  Products Inspected: {self.product_count}
  Passed:             {self.pass_count}
  Failed:             {self.fail_count}
  Pass Rate:          {rate:.1f}%

  Inspect Time:       {self.INSPECT_TIME:.1f}s (base: {self._original_inspect_time:.1f}s)
  Expected Vision:    {self.EXPECTED_VALUE} ({VISION_ITEMS.get(self.EXPECTED_VALUE, '?')})
  Last Vision:        {self.last_vision_value} ({VISION_ITEMS.get(self.last_vision_value, '?')})
  Last Result:        {self.last_qc_result}
  Discovery Mode:     {self.discovery_mode}

  Active Faults:      {faults}

  REAL Fault Effects:
    Vision errors:    {fc['vision_errors']}  (wrong QC decisions!)
    Power brownouts:  {fc['brownouts']}  (belt went OFF)
    Belt stutters:    {fc['belt_stutters']}  (belt jerked)
    Sensor misreads:  {fc['sensor_misreads']}  (sensor inverted)
    Inspect delays:   {fc['inspect_delays']}  (overheat slowdown)
╚══════════════════════════════════════╝"""


# ═══════════════════════════════════════════════════════════
# LINE STATION 7 — Real fault injection + line integration
# ═══════════════════════════════════════════════════════════

class LineStation7(SyncedStation7):
    _station_num = 7

    def __init__(self, modbus_client, station6_ref=None, mqtt_client=None,
                 upstream_ready_event=None):
        super().__init__(modbus_client, station6_ref, mqtt_client,
                         upstream_ready_event)

        # ─── NEW: How long arm stays in divert position ───
        self.PRODUCT_CLEAR_TIME = 6.0   # seconds for product to pass the pivot arm

        # Fault tracking  (rest stays exactly the same)
        self._active_faults = {}
        self._fault_counters = {
            'brownouts': 0,
            'belt_stutters': 0,
            'sensor_misreads': 0,
            'sorter_jams': 0,
            'misroutes': 0,
            'arm_delays': 0,
        }
        self._original_arm_move_time = self.ARM_MOVE_TIME
        self._original_arm_return_time = self.ARM_RETURN_TIME
        self._fault_lock = threading.Lock()

    # ── Compatibility properties ──

    @property
    def is_running(self):
        return self.running

    @is_running.setter
    def is_running(self, value):
        self.running = value

    def run(self):
        """Alias for main() — compatible with other station threading"""
        self.is_running = True
        self._setup_mqtt_fault_listener()
        self.main()

    # ── MQTT Fault Listener ──

    def _setup_mqtt_fault_listener(self):
        if not self.mqtt:
            return
        topics = [
            f"factory/station_{self._station_num}/faults/inject",
            "factory/faults/inject"  # Broadcast
        ]
        def _on_fault_msg(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode())
                station_target = payload.get("station")
                if station_target is not None and station_target != self._station_num:
                    return  # Ignore if targeted to another station
                if "clear" in payload:
                    self.clear_fault(payload["clear"])
                elif "fault" in payload:
                    self.inject_fault(payload["fault"], payload.get("severity", 3))
            except Exception:
                pass
        for topic in topics:
            self.mqtt.subscribe(topic, _on_fault_msg)
        logger.info(f"  📡 STN{self._station_num}: MQTT fault listener active on {topics}")

    # ── REAL Fault Injection ──

    def inject_fault(self, fault_type, severity=3):
        with self._fault_lock:
            severity = min(max(int(severity), 1), 5)
            self._active_faults[fault_type] = severity
            logger.warning(f"  ⚡ STN7: Fault '{fault_type}' INJECTED (severity {severity})")

            if fault_type == "overheat":
                multiplier = 1 + severity * 0.4
                self.ARM_MOVE_TIME = self._original_arm_move_time * multiplier
                self.ARM_RETURN_TIME = self._original_arm_return_time * multiplier
                self._fault_counters['arm_delays'] += 1
                logger.warning(f"  🌡️ STN7: Arm move time → {self.ARM_MOVE_TIME:.2f}s "
                               f"(was {self._original_arm_move_time:.2f}s)")
                logger.warning(f"  🌡️ STN7: Arm return time → {self.ARM_RETURN_TIME:.2f}s "
                               f"(was {self._original_arm_return_time:.2f}s)")
            elif fault_type == "power":
                logger.warning(f"  ⚡ STN7: Belt will suffer brownouts "
                               f"({severity * 6}% chance per activation)")
            elif fault_type == "belt_slip":
                logger.warning(f"  🔄 STN7: Belt will stutter "
                               f"({severity * 8}% chance per activation)")
            elif fault_type == "sensor_drift":
                logger.warning(f"  📡 STN7: Sensor will drift "
                               f"({severity * 5}% chance per read)")
            elif fault_type == "sorter_jam":
                logger.warning(f"  🔧 STN7: Sorter arm will JAM — ignore commands "
                               f"({severity * 8}% chance per turn)")
                logger.warning(f"        Products will go to WRONG bin!")
            elif fault_type == "misroute":
                logger.warning(f"  🔀 STN7: Sorter arm will INVERT direction "
                               f"({severity * 10}% chance per turn)")
                logger.warning(f"        Good→reject, Reject→good!")

    def clear_fault(self, fault_type):
        with self._fault_lock:
            if fault_type == "all":
                self._active_faults.clear()
                self.ARM_MOVE_TIME = self._original_arm_move_time
                self.ARM_RETURN_TIME = self._original_arm_return_time
                logger.info("  ✅ STN7: All faults cleared")
                logger.info(f"  🔧 STN7: Arm times restored to "
                            f"move={self.ARM_MOVE_TIME:.2f}s return={self.ARM_RETURN_TIME:.2f}s")
            elif fault_type in self._active_faults:
                del self._active_faults[fault_type]
                logger.info(f"  ✅ STN7: Fault '{fault_type}' cleared")
                if fault_type == "overheat":
                    self.ARM_MOVE_TIME = self._original_arm_move_time
                    self.ARM_RETURN_TIME = self._original_arm_return_time
                    logger.info(f"  🔧 STN7: Arm times restored")

    # ── Method overrides for REAL fault effects ──

    def belt(self, on):
        """Override: power brownout and belt slip affect actual belt output."""
        if on and "power" in self._active_faults:
            severity = self._active_faults["power"]
            if random.random() < severity * 0.06:
                self._fault_counters['brownouts'] += 1
                logger.warning("[STN7] ⚡ POWER BROWNOUT — belt OFF for 0.5s!")
                super().belt(False)
                time.sleep(0.5)

        if on and "belt_slip" in self._active_faults:
            severity = self._active_faults["belt_slip"]
            if random.random() < severity * 0.08:
                self._fault_counters['belt_stutters'] += 1
                logger.warning("[STN7] 🔄 BELT SLIP — stuttering!")
                super().belt(True)
                time.sleep(0.15)
                super().belt(False)
                time.sleep(0.2)
                super().belt(True)
                time.sleep(0.15)

        super().belt(on)

    def read_sensors(self):
        """Override: sensor drift returns inverted readings."""
        result = super().read_sensors()

        if "sensor_drift" in self._active_faults:
            severity = self._active_faults["sensor_drift"]
            if random.random() < severity * 0.05:
                self._fault_counters['sensor_misreads'] += 1
                original = result["sensor_7"]
                result["sensor_7"] = not original
                logger.warning(f"[STN7] 📡 SENSOR DRIFT — read {result['sensor_7']} "
                               f"(actual: {original})")

        return result

    def sorter_turn(self, turn):
        """
        Override: sorter_jam and misroute affect actual arm position.

        sorter_jam:  Command silently dropped — arm stays where it was.
        misroute:    Direction inverted — arm goes opposite way.
        """
        if "sorter_jam" in self._active_faults:
            severity = self._active_faults["sorter_jam"]
            if random.random() < severity * 0.08:
                self._fault_counters['sorter_jams'] += 1
                direction = "REJECT path" if turn else "GOOD path"
                logger.warning(f"[STN7] 🔧 SORTER JAM — arm STUCK! "
                               f"Ignored command: turn={turn} ({direction})")
                return  # Command dropped — arm stays where it is

        if "misroute" in self._active_faults:
            severity = self._active_faults["misroute"]
            if random.random() < severity * 0.10:
                self._fault_counters['misroutes'] += 1
                turn = not turn
                direction = "REJECT path" if turn else "GOOD path"
                logger.warning(f"[STN7] 🔀 MISROUTE — arm sent to {direction} instead!")

        super().sorter_turn(turn)

    # ── Status & Reports ──

    def get_status(self):
        """Return status dict (compatible with other stations format)."""
        rate = (self.good_count / self.product_count * 100) if self.product_count > 0 else 0
        return {
            'state': str(self.state),
            'counters': {
                'products_completed': self.product_count,
                'products_good': self.good_count,
                'products_rejected': self.reject_count,
            },
            'sorting': {
                'good_rate': round(rate, 1),
                'last_result': self.last_sort_result,
            },
            'faults': {
                'has_fault': len(self._active_faults) > 0,
                'active': list(self._active_faults.keys()),
            },
            'emergency_active': False,
        }

    def get_full_report(self):
        """Return formatted production report."""
        rate = (self.good_count / self.product_count * 100) if self.product_count > 0 else 0
        fc = self._fault_counters
        faults = ", ".join(f"{k}(sev{v})" for k, v in self._active_faults.items()) or "None"
        return f"""
╔══════════════════════════════════════╗
║  Station 7: Sorting & Output Report ║
╠══════════════════════════════════════╣
  Products Sorted:    {self.product_count}
  Good (straight):    {self.good_count}
  Rejected (divert):  {self.reject_count}
  Good Rate:          {rate:.1f}%

  Arm Move Time:      {self.ARM_MOVE_TIME:.2f}s (base: {self._original_arm_move_time:.2f}s)
  Arm Return Time:    {self.ARM_RETURN_TIME:.2f}s (base: {self._original_arm_return_time:.2f}s)
  Last Sort Result:   {self.last_sort_result}

  Active Faults:      {faults}

  REAL Fault Effects:
    Sorter jams:      {fc['sorter_jams']}  (arm ignored command — wrong bin!)
    Misroutes:        {fc['misroutes']}  (arm inverted — wrong bin!)
    Power brownouts:  {fc['brownouts']}  (belt went OFF)
    Belt stutters:    {fc['belt_stutters']}  (belt jerked)
    Sensor misreads:  {fc['sensor_misreads']}  (sensor inverted)
    Arm delays:       {fc['arm_delays']}  (overheat slowdown)
╚══════════════════════════════════════╝"""


# ═══════════════════════════════════════════════════════════
# WAREHOUSE LINE ADDRESSES (from Factory I/O real wiring)
# ═══════════════════════════════════════════════════════════

LINE_WH_ADDRESSES = {
    'OUT': {
        'crane_lift':       35,
        'crane_left':       36,
        'crane_right':      37,
        'entry_loading':    38,   # Loading Conveyor 1 (crane platform)
        'entry_roller':     39,   # Roller Conveyor 1 (warehouse section)
    },
    'IN': {
        'moving_x':         18,
        'moving_z':         19,
        'left_limit':       20,
        'middle_limit':     21,
        'right_limit':      22,
    },
    'REG': {
        'target_position':  0,    # Holding Register 0
    },
}


# ═══════════════════════════════════════════════════════════
# LINE TRANSFER STATION — Real fault injection
# ═══════════════════════════════════════════════════════════

class LineTransferStation(SyncedTransferStation):
    """
    Transfer Station with REAL fault injection for line integration.

    Controls: Belt 6 (27), Roller (28), Emitter (29),
              Right Positioner (30,31), 2-Axis P&P (32,33,34)
    Inputs:   Sensor 9 (12), Positioner feedback (13,14),
              P&P feedback (15,16,17)

    Faults produce REAL effects in Factory I/O:
      overheat:      P&P moves take longer (visible slowdown)
      power:         Belt/Roller randomly turn OFF (brownout)
      belt_slip:     Belt stutters (visible jerking)
      sensor_drift:  Sensor 9 returns wrong value
      pp2_jam:       P&P axis command silently dropped (arm stuck!)
      grab_failure:  Suction randomly releases during transfer
    """
    _station_num = 8

    def __init__(self, modbus_client, mqtt_client=None,
                 upstream_ready_event=None,
                 pallet_ready_event=None, product_placed_event=None):
        super().__init__(modbus_client,
                         upstream_ready_event=upstream_ready_event,
                         station_name="Transfer-Line")
        self.mqtt = mqtt_client
        self._pallet_ready = pallet_ready_event
        self._product_placed = product_placed_event

        # Fault tracking
        self._active_faults = {}
        self._fault_counters = {
            'brownouts': 0,
            'belt_stutters': 0,
            'sensor_misreads': 0,
            'pp2_jams': 0,
            'grab_failures': 0,
            'move_delays': 0,
        }
        self._original_grab_settle = self.GRAB_SETTLE_TIME
        self._original_release_settle = self.RELEASE_SETTLE_TIME
        self._fault_lock = threading.Lock()

    # ── Compatibility ──

    @property
    def is_running(self):
        return self.running

    @is_running.setter
    def is_running(self, value):
        self.running = value

    # ── MQTT Fault Listener ──

    def _setup_mqtt_fault_listener(self):
        if not self.mqtt:
            return
        topics = [
            f"factory/station_{self._station_num}/faults/inject",
            "factory/faults/inject",
        ]
        def _on_fault_msg(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode())
                station_target = payload.get("station")
                if station_target is not None and station_target != self._station_num:
                    return
                if "clear" in payload:
                    self.clear_fault(payload["clear"])
                elif "fault" in payload:
                    self.inject_fault(payload["fault"], payload.get("severity", 3))
            except Exception:
                pass
        for topic in topics:
            self.mqtt.subscribe(topic, _on_fault_msg)
        logger.info(f"  📡 STN{self._station_num}: MQTT fault listener active on {topics}")

    # ── Fault Injection ──

    def inject_fault(self, fault_type, severity=3):
        with self._fault_lock:
            severity = min(max(int(severity), 1), 5)
            self._active_faults[fault_type] = severity
            logger.warning(f"  ⚡ TRANSFER: Fault '{fault_type}' INJECTED (severity {severity})")

            if fault_type == "overheat":
                self._fault_counters['move_delays'] += 1
                logger.warning(f"  🌡️ TRANSFER: P&P operations will be slower")
            elif fault_type == "power":
                logger.warning(f"  ⚡ TRANSFER: Belt/Roller brownouts "
                               f"({severity * 6}% chance)")
            elif fault_type == "belt_slip":
                logger.warning(f"  🔄 TRANSFER: Belt will stutter "
                               f"({severity * 8}% chance)")
            elif fault_type == "sensor_drift":
                logger.warning(f"  📡 TRANSFER: Sensor 9 will drift "
                               f"({severity * 5}% chance)")
            elif fault_type == "pp2_jam":
                logger.warning(f"  🔧 TRANSFER: P&P axis will JAM "
                               f"({severity * 6}% chance)")
            elif fault_type == "grab_failure":
                logger.warning(f"  ✋ TRANSFER: Grab will FAIL "
                               f"({severity * 8}% chance)")

    def clear_fault(self, fault_type):
        with self._fault_lock:
            if fault_type == "all":
                self._active_faults.clear()
                logger.info("  ✅ TRANSFER: All faults cleared")
            elif fault_type in self._active_faults:
                del self._active_faults[fault_type]
                logger.info(f"  ✅ TRANSFER: Fault '{fault_type}' cleared")

    # ── REAL Fault Effect Overrides ──

    def belt_6(self, on):
        """Override: brownout and belt slip produce REAL Factory I/O effects."""
        if on and "power" in self._active_faults:
            severity = self._active_faults["power"]
            if random.random() < severity * 0.06:
                self._fault_counters['brownouts'] += 1
                logger.warning("[TRANSFER] ⚡ POWER BROWNOUT — belt OFF for 0.5s!")
                super().belt_6(False)
                time.sleep(0.5)

        if on and "belt_slip" in self._active_faults:
            severity = self._active_faults["belt_slip"]
            if random.random() < severity * 0.08:
                self._fault_counters['belt_stutters'] += 1
                logger.warning("[TRANSFER] 🔄 BELT SLIP — stuttering!")
                super().belt_6(True)
                time.sleep(0.15)
                super().belt_6(False)
                time.sleep(0.2)
                super().belt_6(True)
                time.sleep(0.15)

        super().belt_6(on)

    def roller_1(self, on):
        """Override: brownout affects roller too."""
        if on and "power" in self._active_faults:
            severity = self._active_faults["power"]
            if random.random() < severity * 0.06:
                self._fault_counters['brownouts'] += 1
                logger.warning("[TRANSFER] ⚡ ROLLER BROWNOUT — OFF for 0.5s!")
                super().roller_1(False)
                time.sleep(0.5)
        super().roller_1(on)

    def product_present(self):
        """Override: sensor drift returns inverted reading."""
        result = super().product_present()
        if "sensor_drift" in self._active_faults:
            severity = self._active_faults["sensor_drift"]
            if random.random() < severity * 0.05:
                self._fault_counters['sensor_misreads'] += 1
                logger.warning(f"[TRANSFER] 📡 SENSOR DRIFT — read {not result} "
                               f"(actual: {result})")
                return not result
        return result

    def pp2_move_x(self, to_pick):
        """Override: pp2_jam silently drops X command."""
        if "pp2_jam" in self._active_faults:
            severity = self._active_faults["pp2_jam"]
            if random.random() < severity * 0.06:
                self._fault_counters['pp2_jams'] += 1
                direction = "PICK" if to_pick else "PLACE"
                logger.warning(f"[TRANSFER] 🔧 P&P JAM — X command to {direction} DROPPED!")
                return
        if "overheat" in self._active_faults:
            severity = self._active_faults["overheat"]
            delay = severity * 0.3
            time.sleep(delay)
        super().pp2_move_x(to_pick)

    def pp2_move_z(self, down):
        """Override: pp2_jam silently drops Z command."""
        if "pp2_jam" in self._active_faults:
            severity = self._active_faults["pp2_jam"]
            if random.random() < severity * 0.06:
                self._fault_counters['pp2_jams'] += 1
                direction = "DOWN" if down else "UP"
                logger.warning(f"[TRANSFER] 🔧 P&P JAM — Z command {direction} DROPPED!")
                return
        if "overheat" in self._active_faults:
            severity = self._active_faults["overheat"]
            delay = severity * 0.3
            time.sleep(delay)
        super().pp2_move_z(down)

    def pp2_grab(self, on):
        """Override: grab_failure randomly releases during grab."""
        super().pp2_grab(on)
        if on and "grab_failure" in self._active_faults:
            severity = self._active_faults["grab_failure"]
            if random.random() < severity * 0.08:
                self._fault_counters['grab_failures'] += 1
                logger.warning("[TRANSFER] ✋ GRAB FAILURE — suction lost!")
                time.sleep(0.3)
                super().pp2_grab(False)
                time.sleep(0.1)
                super().pp2_grab(True)  # Try to re-grab

    # ── Custom LINE run ──

    def run(self):
        """LINE mode run — coordinates with warehouse via events."""
        self.is_running = True
        self._setup_mqtt_fault_listener()

        logger.info("")
        logger.info("═" * 55)
        logger.info("  🔄 TRANSFER STATION Starting (LINE MODE)")
        logger.info("═" * 55)

        self.reset_all()

        # Home P&P
        logger.info("[TRANSFER] Homing P&P to PLACE (X=0), UP...")
        self.pp2_move_x(False)
        self.pp2_move_z(False)
        time.sleep(1.0)
        self._wait_pp2_x_done()
        self._wait_pp2_z_done()
        logger.info("[TRANSFER] P&P homed ✅")

        try:
            while self.running:
                cycle_start = time.time()

                # ── STATE 0: BELT ON, WAIT FOR PRODUCT ──
                self._set_state(0, "WAIT_PRODUCT")
                self.bar_clamp(False)
                self.belt_6(True)

                if self.product_present():
                    self._wait_for(lambda: not self.product_present(),
                                   "Sensor 9 clear")
                    time.sleep(0.3)

                logger.info("[TRANSFER] Waiting for product...")
                if not self._wait_for(self.product_present, "Sensor 9", timeout=120):
                    if not self.running:
                        break
                    logger.warning("[TRANSFER] Timeout, retrying...")
                    continue
                logger.info("[TRANSFER] 📦 Product detected! ✅")

                # ── STATE 1: CLAMP (align product) ──
                self._set_state(1, "CLAMP")
                self.belt_6(False)
                time.sleep(0.2)
                self.bar_clamp(True)
                self._wait_for(self.bar_is_clamped, "bar clamped")
                logger.info("[TRANSFER] Aligned ✅")
                time.sleep(0.3)

                # ── STATE 2: RELEASE CLAMP ──
                self._set_state(2, "RELEASE_CLAMP")
                self.bar_clamp(False)
                self._wait_for(lambda: not self.bar_is_clamped(), "unclamped")
                logger.info("[TRANSFER] Clamp released ✅")
                time.sleep(0.2)

                # WAIT FOR WAREHOUSE TO BE READY (STACKER AT HOME)
                if self._pallet_ready:
                    logger.info("[TRANSFER] ⏳ Waiting for Warehouse stacker to be at home position...")
                    while self.running and not self._pallet_ready.is_set():
                        time.sleep(0.1)
                    if not self.running: break
                    self._pallet_ready.clear()
                    logger.info("[TRANSFER] Warehouse stacker ready! ✅")
                    
                # ── STATE 3: EMIT PALLET (only when sensor input 12 confirms product) ──
                self._set_state(3, "EMIT_PALLET")

                # Verify sensor (input 12) before emitting pallet
                if not self.product_present():
                    logger.info("[TRANSFER] ⏳ Waiting for sensor (input 12) before emitting...")
                    self._wait_for(self.product_present, "Sensor 9 (input 12)", timeout=60)
                logger.info("[TRANSFER] Sensor confirmed — emitting pallet (coil 29)...")
                self.emitter_3(True)
                time.sleep(self.EMITTER_PULSE_TIME)
                self.emitter_3(False)
                self.roller_1(True)
                time.sleep(self.PALLET_TRAVEL_TIME)
                self.roller_1(False)
                logger.info("[TRANSFER] Pallet in position ✅")

                # ── STATE 4: P&P → PICK (far end), DOWN ──
                self._set_state(4, "PP_PICK")
                logger.info("[TRANSFER] P&P → PICK (X=TRUE)...")
                self.pp2_move_x(True)
                self._wait_pp2_x_done()
                logger.info("[TRANSFER] P&P at PICK X ✅")
                time.sleep(1.0)

                self.pp2_move_z(True)
                self._wait_pp2_z_done()
                logger.info("[TRANSFER] P&P down at product ✅")
                time.sleep(1.0)

                # ── STATE 5: GRAB ──
                self._set_state(5, "GRAB")
                self.pp2_grab(True)
                time.sleep(1.0)
                if self.pp2_item_detected():
                    logger.info("[TRANSFER] Grabbed ✅")
                else:
                    logger.warning("[TRANSFER] ⚠️ Detected=FALSE — continuing")

                # ── STATE 6: LIFT P&P WITH PRODUCT ──
                self._set_state(6, "LIFT")
                self.pp2_move_z(False)
                self._wait_pp2_z_done()
                logger.info("[TRANSFER] Lifted ✅")
                time.sleep(1.0)

                # ── STATE 7: MOVE TO PLACE ──
                self._set_state(7, "PP_PLACE")
                logger.info("[TRANSFER] P&P → PLACE (X=FALSE)...")
                self.pp2_move_x(False)
                self._wait_pp2_x_done()
                logger.info("[TRANSFER] Over pallet ✅")
                time.sleep(1.0)

                # ── STATE 8: LOWER ONTO PALLET ──
                self._set_state(8, "PP_DOWN")
                self.pp2_move_z(True)
                self._wait_pp2_z_done()
                logger.info("[TRANSFER] Down on pallet ✅")
                time.sleep(1.0)

                # ── STATE 9: RELEASE AND LIFT ──
                self._set_state(9, "RELEASE_AND_LIFT")
                self.pp2_grab(False)
                time.sleep(self.RELEASE_SETTLE_TIME)
                logger.info("[TRANSFER] Product on pallet ✅")

                self.pp2_move_z(False)
                self._wait_pp2_z_done()
                logger.info("[TRANSFER] P&P up ✅")

                # ── STATE 11: ROLLER ON → EXIT PALLET ──
                self._set_state(11, "ROLLER_EXIT")

                # Send pallet to warehouse via roller
                self.roller_1(True)
                logger.info(f"[TRANSFER] Pallet → warehouse ({self.PALLET_EXIT_TIME}s)...")
                time.sleep(self.PALLET_EXIT_TIME)
                self.roller_1(False)

                # Signal warehouse: product is on its way
                if self._product_placed:
                    self._product_placed.set()
                    logger.info("[TRANSFER] 📢 Signaled warehouse: product placed")

                self.cycle_count += 1
                cycle_time = time.time() - cycle_start

                logger.info("")
                logger.info(f"✅ TRANSFER: Cycle #{self.cycle_count} COMPLETE ({cycle_time:.1f}s)")

                if self._active_faults:
                    fc = self._fault_counters
                    logger.warning(f"   ⚡ brown={fc['brownouts']} stut={fc['belt_stutters']} "
                                   f"jam={fc['pp2_jams']} grab={fc['grab_failures']} "
                                   f"mis={fc['sensor_misreads']}")

                # Wait for stacker crane to return (holding register 0 == 55)
                logger.info("[TRANSFER] ⏳ Waiting for stacker to return (reg 0 == 55)...")
                while self.running:
                    try:
                        reg_val = self.modbus.read_holding_register(0)
                        if reg_val == 55:
                            break
                    except Exception:
                        pass
                    time.sleep(0.2)
                if self.running:
                    logger.info("[TRANSFER] ✅ Stacker returned!")

        except KeyboardInterrupt:
            logger.info("Transfer interrupted")
        finally:
            self.running = False
            self.reset_all()

    # ── Status & Reports ──

    def get_status(self):
        return {
            'state': str(self.state),
            'counters': {
                'products_completed': self.cycle_count,
            },
            'faults': {
                'has_fault': len(self._active_faults) > 0,
                'active': list(self._active_faults.keys()),
            },
            'emergency_active': False,
        }

    def get_full_report(self):
        fc = self._fault_counters
        faults = ", ".join(f"{k}(sev{v})" for k, v in self._active_faults.items()) or "None"
        return f"""
╔══════════════════════════════════════╗
║  Transfer Station Report            ║
╠══════════════════════════════════════╣
  Products Transferred: {self.cycle_count}

  Active Faults:      {faults}

  REAL Fault Effects:
    Power brownouts:  {fc['brownouts']}  (belt/roller went OFF)
    Belt stutters:    {fc['belt_stutters']}  (belt jerked)
    Sensor misreads:  {fc['sensor_misreads']}  (sensor inverted)
    P&P jams:         {fc['pp2_jams']}  (axis command dropped!)
    Grab failures:    {fc['grab_failures']}  (suction lost!)
    Move delays:      {fc['move_delays']}  (overheat slowdown)
╚══════════════════════════════════════╝"""


# ═══════════════════════════════════════════════════════════
# LINE WAREHOUSE — Real fault injection + line integration
# ═══════════════════════════════════════════════════════════

class LineWarehouse(WarehouseController):
    """
    Warehouse with REAL fault injection for line integration.

    Uses LINE_WH_ADDRESSES (Coils 35-39, Inputs 18-22, Holding Reg 0).
    No entry/exit sensors — uses timed conveyor operation.

    Coordinates with Transfer via events:
      pallet_ready:    Warehouse sets when pallet is in position
      product_placed:  Transfer sets when product is on pallet

    Faults produce REAL effects in Factory I/O:
      overheat:      Crane operations slower (timing multiplier)
      power:         Roller/Loading brownout (conveyor OFF)
      crane_drift:   Target cell offset ±1-2 (wrong shelf!)
      fork_jam:      Fork LEFT/RIGHT command dropped (arm stuck!)
      sensor_drift:  Crane limit sensors return wrong value
    """
    _station_num = 9

    def __init__(self, modbus_client, mqtt_client=None,
                 pallet_ready_event=None, product_placed_event=None):
        # Init as integrated, then override addresses
        super().__init__(modbus_client, mqtt_client, integrated=True)

        # Override with CORRECT line addresses
        self.OUT = dict(LINE_WH_ADDRESSES['OUT'])
        self.IN = dict(LINE_WH_ADDRESSES['IN'])
        self.REG = dict(LINE_WH_ADDRESSES['REG'])

        # Coordination events
        self._pallet_ready = pallet_ready_event
        self._product_placed = product_placed_event

        # Pallet emitter is on Transfer side (Coil 29)
        self.TRANSFER_EMITTER = 29
        self.TRANSFER_ROLLER = 28

        # Timing for timed entry (no entry sensor)
        self.PALLET_EMIT_PULSE = 0.3
        self.PALLET_TRAVEL_TO_PP = 3.0   # Roller → P&P place position
        self.ENTRY_TRAVEL_TIME = 5.0     # Roller → warehouse platform

        # Fault tracking
        self._active_faults = {}
        self._fault_counters = {
            'brownouts': 0,
            'crane_drifts': 0,
            'fork_jams': 0,
            'sensor_misreads': 0,
            'timing_delays': 0,
        }
        self._fault_lock = threading.Lock()

        logger.info("WH: 🔗 LINE mode — correct addresses:")
        logger.info(f"     Outputs: {self.OUT}")
        logger.info(f"     Inputs:  {self.IN}")
        logger.info(f"     Register: {self.REG}")

    # ── Compatibility ──

    @property
    def is_running(self):
        return self.running

    @is_running.setter
    def is_running(self, value):
        self.running = value

    # ── MQTT Fault Listener ──

    def _setup_mqtt_fault_listener(self):
        if not self.mqtt:
            return
        topics = [
            f"factory/station_{self._station_num}/faults/inject",
            "factory/faults/inject",
        ]
        def _on_fault_msg(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode())
                station_target = payload.get("station")
                if station_target is not None and station_target != self._station_num:
                    return
                if "clear" in payload:
                    self.clear_fault(payload["clear"])
                elif "fault" in payload:
                    self.inject_fault(payload["fault"], payload.get("severity", 3))
            except Exception:
                pass
        for topic in topics:
            self.mqtt.subscribe(topic, _on_fault_msg)
        logger.info(f"  📡 STN{self._station_num}: MQTT fault listener active on {topics}")

    # ── Fault Injection ──

    def inject_fault(self, fault_type, severity=3):
        with self._fault_lock:
            severity = min(max(int(severity), 1), 5)
            self._active_faults[fault_type] = severity
            logger.warning(f"  ⚡ WAREHOUSE: Fault '{fault_type}' INJECTED (severity {severity})")

            if fault_type == "overheat":
                self._fault_counters['timing_delays'] += 1
                logger.warning(f"  🌡️ WAREHOUSE: Crane operations will be slower")
            elif fault_type == "power":
                logger.warning(f"  ⚡ WAREHOUSE: Conveyor brownouts "
                               f"({severity * 6}% chance)")
            elif fault_type == "crane_drift":
                logger.warning(f"  🎯 WAREHOUSE: Crane will target WRONG cell "
                               f"(±{severity} offset)")
            elif fault_type == "fork_jam":
                logger.warning(f"  🔧 WAREHOUSE: Fork commands will JAM "
                               f"({severity * 6}% chance)")
            elif fault_type == "sensor_drift":
                logger.warning(f"  📡 WAREHOUSE: Limit sensors will drift "
                               f"({severity * 5}% chance)")

    def clear_fault(self, fault_type):
        with self._fault_lock:
            if fault_type == "all":
                self._active_faults.clear()
                logger.info("  ✅ WAREHOUSE: All faults cleared")
            elif fault_type in self._active_faults:
                del self._active_faults[fault_type]
                logger.info(f"  ✅ WAREHOUSE: Fault '{fault_type}' cleared")

    # ── REAL Fault Effect Overrides ──

    def entry_roller(self, on):
        """Override: power brownout on roller."""
        if on and "power" in self._active_faults:
            severity = self._active_faults["power"]
            if random.random() < severity * 0.06:
                self._fault_counters['brownouts'] += 1
                logger.warning("[WH] ⚡ ROLLER BROWNOUT — OFF for 0.5s!")
                super().entry_roller(False)
                time.sleep(0.5)
        super().entry_roller(on)

    def entry_loading(self, on):
        """Override: power brownout on loading conveyor."""
        if on and "power" in self._active_faults:
            severity = self._active_faults["power"]
            if random.random() < severity * 0.06:
                self._fault_counters['brownouts'] += 1
                logger.warning("[WH] ⚡ LOADING BROWNOUT — OFF for 0.5s!")
                super().entry_loading(False)
                time.sleep(0.5)
        super().entry_loading(on)

    def set_target(self, cell):
        """Override: crane_drift offsets target cell."""
        if "crane_drift" in self._active_faults and cell not in (0, 55):
            severity = self._active_faults["crane_drift"]
            offset = random.randint(-severity, severity)
            if offset != 0:
                original = cell
                cell = max(1, min(self.MAX_CELLS, cell + offset))
                self._fault_counters['crane_drifts'] += 1
                logger.warning(f"[WH] 🎯 CRANE DRIFT — target {original} → {cell} "
                               f"(offset {offset:+d})!")
        if "overheat" in self._active_faults:
            severity = self._active_faults["overheat"]
            delay = severity * 0.5
            self._fault_counters['timing_delays'] += 1
            logger.warning(f"[WH] 🌡️ OVERHEAT — extra {delay:.1f}s delay before move")
            time.sleep(delay)
        return super().set_target(cell)

    def crane_left(self, on):
        """Override: fork_jam drops LEFT command."""
        if on and "fork_jam" in self._active_faults:
            severity = self._active_faults["fork_jam"]
            if random.random() < severity * 0.06:
                self._fault_counters['fork_jams'] += 1
                logger.warning("[WH] 🔧 FORK JAM — LEFT command DROPPED!")
                return
        super().crane_left(on)

    def crane_right(self, on):
        """Override: fork_jam drops RIGHT command."""
        if on and "fork_jam" in self._active_faults:
            severity = self._active_faults["fork_jam"]
            if random.random() < severity * 0.06:
                self._fault_counters['fork_jams'] += 1
                logger.warning("[WH] 🔧 FORK JAM — RIGHT command DROPPED!")
                return
        super().crane_right(on)

    def left_limit(self):
        """Override: sensor_drift inverts limit sensor."""
        result = super().left_limit()
        if "sensor_drift" in self._active_faults:
            severity = self._active_faults["sensor_drift"]
            if random.random() < severity * 0.05:
                self._fault_counters['sensor_misreads'] += 1
                logger.warning(f"[WH] 📡 LEFT LIMIT DRIFT — {not result} (actual: {result})")
                return not result
        return result

    def middle_limit(self):
        """Override: sensor_drift inverts limit sensor."""
        result = super().middle_limit()
        if "sensor_drift" in self._active_faults:
            severity = self._active_faults["sensor_drift"]
            if random.random() < severity * 0.05:
                self._fault_counters['sensor_misreads'] += 1
                logger.warning(f"[WH] 📡 MIDDLE LIMIT DRIFT — {not result} (actual: {result})")
                return not result
        return result

    def right_limit(self):
        """Override: sensor_drift inverts limit sensor."""
        result = super().right_limit()
        if "sensor_drift" in self._active_faults:
            severity = self._active_faults["sensor_drift"]
            if random.random() < severity * 0.05:
                self._fault_counters['sensor_misreads'] += 1
                logger.warning(f"[WH] 📡 RIGHT LIMIT DRIFT — {not result} (actual: {result})")
                return not result
        return result

    # ── No entry/exit sensors in this scene ──

    def entry_sensor(self):
        """No entry sensor in line scene — always False."""
        return False

    def exit_sensor(self):
        """No exit sensor in line scene — always False."""
        return False

    # ── Pallet Management (emit + position for Transfer P&P) ──

    def _emit_and_position_pallet(self):
        """Emit a pallet and position it under the Transfer P&P."""
        logger.info("WH ┃ Emitting pallet for Transfer...")
        self.modbus.write_output(self.TRANSFER_EMITTER, True)
        self._wait_seconds(self.PALLET_EMIT_PULSE, "emit")
        self.modbus.write_output(self.TRANSFER_EMITTER, False)

        # Roller moves pallet to P&P place position
        self.modbus.write_output(self.TRANSFER_ROLLER, True)
        logger.info(f"WH ┃ Pallet traveling to P&P ({self.PALLET_TRAVEL_TO_PP}s)...")
        self._wait_seconds(self.PALLET_TRAVEL_TO_PP, "travel")
        self.modbus.write_output(self.TRANSFER_ROLLER, False)
        logger.info("WH ┃ Pallet in position ✅")

    def _pull_pallet_to_crane(self):
        """Pull pallet+product from Transfer area into warehouse crane."""
        logger.info("WH ┃ Pulling pallet into warehouse...")
        # Transfer roller (coil 28) + Warehouse roller (coil 39) + Loading conveyor 1 (coil 38) all ON
        self.modbus.write_output(self.TRANSFER_ROLLER, True)
        self.modbus.write_output(self.OUT['entry_roller'], True)
        self.modbus.write_output(38, True)   # Loading Conveyor 1 ON

        # Wait until sensor at input 23 detects the product on loading conveyor
        logger.info("WH ┃ Waiting for product on loading conveyor (input 23)...")
        start = time.time()
        while self.running:
            inputs = self.modbus.read_inputs(23, 1)
            if inputs and inputs[0]:
                logger.info("WH ┃ Product detected on loading conveyor ✅")
                # Stop ALL conveyors IMMEDIATELY to prevent overshooting
                self.modbus.write_output(38, False)
                self.modbus.write_output(self.TRANSFER_ROLLER, False)
                self.modbus.write_output(self.OUT['entry_roller'], False)
                break
            if time.time() - start > 30:
                logger.warning("WH ┃ ⚠️ Timeout waiting for loading conveyor sensor")
                break
            time.sleep(0.01)

        logger.info("WH ┃ Loading conveyor 1 (coil 38) STOPPED ✅")
        self._wait_seconds(self.TIMING['load_settle'], "settle")
        logger.info("WH ┃ Pallet on crane platform ✅")

    # ── LINE Store Cycle ──

    def store_product_line(self):
        """Full store cycle with Transfer coordination (no entry sensor).
        
        Transfer station handles pallet emission (after product arrives).
        Warehouse just waits for Transfer to signal product_placed.
        """
        if self.next_cell > self.MAX_CELLS:
            logger.warning("WH: ❌ FULL!")
            self.state = "full"
            return False

        cell = self.next_cell
        cycle_start = time.time()

        logger.info("")
        logger.info("═" * 55)
        logger.info(f"WH ┃ LINE STORE — Cell {cell} / {self.MAX_CELLS}")
        logger.info("═" * 55)

        # ══ PHASE 1: PREPARE CRANE ══
        self.state = "preparing"
        logger.info("WH ┃ PHASE 1: Prepare crane at rest...")
        self.set_target(55)
        if not self._wait_crane_stopped():
            logger.warning("WH: ⚠️ Crane didn't reach rest")

        self.crane_lift(False)
        if not self.middle_limit():
            self.crane_left(False)
            self.crane_right(False)
            self._wait_forks_middle()

        # Signal Transfer that warehouse stacker is at home position
        if self._pallet_ready:
            self._pallet_ready.set()

        # ══ PHASE 2: WAIT FOR TRANSFER TO PLACE PRODUCT ══
        # Transfer station handles: product detection → clamp → release →
        #   emit pallet (only when input 12 active) → P&P → roller exit
        self.state = "wait_transfer"
        if self._product_placed:
            logger.info("WH ┃ PHASE 2: Waiting for Transfer to place product...")
            while not self._product_placed.is_set() and self.running:
                time.sleep(0.1)
            if not self.running:
                return False
            self._product_placed.clear()
            logger.info("WH ┃ ✅ Transfer placed product!")
        else:
            logger.info("WH ┃ PHASE 2: No transfer event — timed wait...")
            self._wait_seconds(30.0, "transfer_wait")

        # ══ PHASE 3: PULL PALLET INTO CRANE ══
        self.state = "loading"
        logger.info("WH ┃ PHASE 3: Pull pallet into warehouse...")
        self._pull_pallet_to_crane()

        # ══ PHASE 4: PICKUP FROM CONVEYOR ══
        self.state = "pickup"
        logger.info("")
        logger.info("WH ┃ PHASE 4: PICKUP from conveyor")
        self._pickup_from_conveyor()
        logger.info("WH ┃ ✅ Product on forks!")

        # ══ PHASE 5: CRANE → CELL ══
        self.state = f"crane_to_{cell}"
        logger.info(f"WH ┃ PHASE 5: Crane → cell {cell}...")
        if not self.set_target(cell):
            self.store_errors += 1
            return False

        if not self._wait_crane_stopped():
            logger.error(f"WH: ❌ Crane didn't reach cell {cell}!")
            self.store_errors += 1
            self.set_target(55)
            self._wait_crane_stopped()
            return False
        logger.info(f"WH ┃ ✅ Crane at cell {cell}!")

        # ══ PHASE 6: STORE INTO RACK ══
        self.state = "storing"
        logger.info("")
        logger.info("WH ┃ PHASE 6: STORE into rack")
        self._store_into_rack()
        logger.info("WH ┃ ✅ Product on shelf!")

        # ══ PHASE 7: HOME ══
        self.state = "returning"
        logger.info("WH ┃ PHASE 7: Crane → rest...")
        self.set_target(55)
        if not self._wait_crane_stopped():
            logger.warning("WH: ⚠️ Slow return")

        # ══ DONE ══
        self.state = "idle"
        self.occupied.add(cell)
        self.last_cell_used = cell
        self.next_cell = cell + 1
        self.products_stored += 1

        elapsed = time.time() - cycle_start
        filled = len(self.occupied)
        pct = filled / self.MAX_CELLS * 100

        logger.info("")
        logger.info(f"✅ WH: Product #{self.products_stored} → cell {cell} ({elapsed:.1f}s)")
        logger.info(f"   📦 {filled}/{self.MAX_CELLS} ({pct:.0f}%)")
        return True

    # ── LINE Main Loop ──

    def run(self):
        """LINE mode main loop with Transfer coordination."""
        self.is_running = True
        self._setup_mqtt_fault_listener()

        logger.info("🏭 Warehouse starting (LINE MODE)")
        logger.info(f"   {self.MAX_CELLS} cells (3 racks)")
        logger.info(f"   Outputs: {self.OUT}")
        logger.info(f"   Inputs:  {self.IN}")

        try:
            while self.running:
                if self.next_cell > self.MAX_CELLS:
                    logger.warning("WH: FULL — signaling line to stop!")
                    self.state = "full"
                    return  # Will cause line to stop

                success = self.store_product_line()
                if not success and self.running:
                    self._wait_seconds(3.0, "retry")
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            self.all_off()

    def get_status(self):
        filled = len(self.occupied)
        pct = (filled / self.MAX_CELLS * 100) if self.MAX_CELLS > 0 else 0
        return {
            'state': str(self.state),
            'counters': {
                'products_stored': self.products_stored,
                'store_errors': self.store_errors,
            },
            'faults': {
                'has_fault': len(self._active_faults) > 0,
                'active': list(self._active_faults.keys()),
            },
            'warehouse': {
                'next_cell': self.next_cell,
                'fill_percent': round(pct, 1),
                'cells_occupied': filled,
                'max_cells': self.MAX_CELLS,
            },
            'emergency_active': False,
        }

    def get_full_report(self):
        filled = len(self.occupied)
        pct = (filled / self.MAX_CELLS * 100) if self.MAX_CELLS > 0 else 0
        cells = sorted(self.occupied) if self.occupied else ["(none)"]
        fc = self._fault_counters
        faults = ", ".join(f"{k}(sev{v})" for k, v in self._active_faults.items()) or "None"
        return f"""
╔══════════════════════════════════════╗
║  Warehouse: 3-Rack Stacker Crane   ║
╠══════════════════════════════════════╣
  Mode:               LINE (Coils 35-39, Inputs 18-22, Reg 0)
  Products Stored:    {self.products_stored}
  Store Errors:       {self.store_errors}

  Next Cell:          {self.next_cell}
  Cells Occupied:     {filled} / {self.MAX_CELLS} ({pct:.0f}%)
  Last Cell Used:     {self.last_cell_used}
  Occupied Cells:     {cells}

  Active Faults:      {faults}

  REAL Fault Effects:
    Power brownouts:  {fc['brownouts']}  (conveyor went OFF)
    Crane drifts:     {fc['crane_drifts']}  (wrong cell targeted!)
    Fork jams:        {fc['fork_jams']}  (fork command dropped!)
    Sensor misreads:  {fc['sensor_misreads']}  (limit sensor inverted)
    Timing delays:    {fc['timing_delays']}  (overheat slowdown)
╚══════════════════════════════════════╝"""


# ═══════════════════════════════════════════════════════════
# FAULT INJECTION MENU
# ═══════════════════════════════════════════════════════════

def fault_menu(station1, station2, station3, station6, station7, transfer, warehouse):
    """Combined fault injection for all seven stations + Transfer + Warehouse — ALL REAL EFFECTS."""
    print()
    print("  ┌─────────────────────────────────────────────────────────────────────────────────┐")
    print("  │  📺 TV ASSEMBLY LINE — Fault Injection ⚡  (ALL REAL EFFECTS)                    │")
    print("  │                                                                                 │")
    print("  │  STATION 1 (Chassis):   STATION 2 (PCB):     STATION 3 (Panel):                 │")
    print("  │  1f1 [s] = Overheat     2f1 [s] = Overheat   3f1 [s] = Overheat                │")
    print("  │  1f2 [s] = Vibration    2f3 [s] = Power      3f3 [s] = Power                   │")
    print("  │  1f3 [s] = Power        2f4 [s] = Belt Slip  3f4 [s] = Belt Slip                │")
    print("  │  1f4 [s] = Belt Slip    2f5 [s] = Sensor     3f5 [s] = Sensor                  │")
    print("  │  1f5 [s] = Sensor       2f6 [s] = Gripper ⚡  3f6 [s] = Pos Jam                  │")
    print("  │                         2f7 [s] = P&P Jam                                      │")
    print("  │                                                                                 │")
    print("  │  STATION 6 (QC):                  STATION 7 (Sorting):                          │")
    print("  │  6f1 [s] = Overheat               7f1 [s] = Overheat                            │")
    print("  │  6f3 [s] = Power                  7f3 [s] = Power                               │")
    print("  │  6f4 [s] = Belt Slip              7f4 [s] = Belt Slip                           │")
    print("  │  6f5 [s] = Sensor                 7f5 [s] = Sensor                              │")
    print("  │  6f6 [s] = Vision Error 📷         7f6 [s] = Sorter Jam 🔧                       │")
    print("  │                                   7f7 [s] = Misroute 🔀                          │")
    print("  │                                                                                 │")
    print("  │  TRANSFER (8):                    WAREHOUSE (9):                                 │")
    print("  │  8f1 [s] = Overheat               9f1 [s] = Overheat                            │")
    print("  │  8f3 [s] = Power                  9f3 [s] = Power                               │")
    print("  │  8f4 [s] = Belt Slip              9f4 [s] = Crane Drift 🎯                      │")
    print("  │  8f5 [s] = Sensor                 9f5 [s] = Sensor                              │")
    print("  │  8f6 [s] = P&P Jam 🔧              9f6 [s] = Fork Jam 🔧                         │")
    print("  │  8f7 [s] = Grab Fail ✋                                                          │")
    print("  │                                                                                 │")
    print("  │  fc = Clear ALL    st = Status    q = Quit                                      │")
    print("  │  1fe/2fe/3fe/6fe/7fe/8fe/9fe = Effects                                          │")
    print("  │  1rp/2rp/3rp/6rp/7rp/8rp/9rp = Reports                                        │")
    print("  │  [s] = optional severity 1-5 (default 3)  Example: 8f6 5                        │")
    print("  └─────────────────────────────────────────────────────────────────────────────────┘")
    print()

    stn1_faults = {"1": "overheat", "2": "vibration", "3": "power",
                   "4": "belt_slip", "5": "sensor_drift"}
    stn2_faults = {"1": "overheat", "3": "power", "4": "belt_slip",
                   "5": "sensor_drift", "6": "gripper", "7": "pp_jam"}
    stn3_faults = {"1": "overheat", "3": "power", "4": "belt_slip",
                   "5": "sensor_drift", "6": "positioner_jam"}
    stn6_faults = {"1": "overheat", "3": "power", "4": "belt_slip",
                   "5": "sensor_drift", "6": "vision_error"}
    stn7_faults = {"1": "overheat", "3": "power", "4": "belt_slip",
                   "5": "sensor_drift", "6": "sorter_jam", "7": "misroute"}
    stn8_faults = {"1": "overheat", "3": "power", "4": "belt_slip",
                   "5": "sensor_drift", "6": "pp2_jam", "7": "grab_failure"}
    stn9_faults = {"1": "overheat", "3": "power", "4": "crane_drift",
                   "5": "sensor_drift", "6": "fork_jam"}

    while (station1.is_running or station2.is_running
           or station3.is_running or station6.is_running
           or station7.is_running or transfer.is_running
           or warehouse.is_running):
        try:
            cmd = input().strip().lower()
            if not cmd:
                continue

            # ── Station 1 faults ──
            if cmd.startswith("1f") and len(cmd) >= 3:
                n = cmd[2]
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                if n == "e":
                    fc = station1._fault_counters
                    print(f"\n  ⚡ STN1: stut={fc['stutters']} brown={fc['brownouts']} "
                          f"chat={fc['blade_chatters']} estop={fc['emergency_stops']} "
                          f"mis={fc['sensor_misreads']}\n")
                elif n in stn1_faults:
                    station1.inject_fault(stn1_faults[n], sev)

            # ── Station 2 faults ──
            elif cmd.startswith("2f") and len(cmd) >= 3:
                n = cmd[2]
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                if n == "e":
                    fc = station2._fault_counters
                    print(f"\n  ⚡ STN2: stut={fc['stutters']} brown={fc['brownouts']} "
                          f"grip={fc['gripper_failures']} estop={fc['emergency_stops']} "
                          f"mis={fc['sensor_misreads']}\n")
                elif n in stn2_faults:
                    station2.inject_fault(stn2_faults[n], sev)

            # ── Station 3 faults ──
            elif cmd.startswith("3f") and len(cmd) >= 3:
                n = cmd[2]
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                if n == "e":
                    fc = station3._fault_counters
                    print(f"\n  ⚡ STN3: stut={fc['stutters']} brown={fc['brownouts']} "
                          f"jam={fc['positioner_jams']} estop={fc['emergency_stops']} "
                          f"mis={fc['sensor_misreads']}\n")
                elif n in stn3_faults:
                    station3.inject_fault(stn3_faults[n], sev)

            # ── Station 6 faults ──
            elif cmd.startswith("6f") and len(cmd) >= 3:
                n = cmd[2]
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                if n == "e":
                    fc = station6._fault_counters
                    print(f"\n  ⚡ STN6: vis_err={fc['vision_errors']} "
                          f"brown={fc['brownouts']} stut={fc['belt_stutters']} "
                          f"mis={fc['sensor_misreads']} delay={fc['inspect_delays']}\n")
                elif n in stn6_faults:
                    station6.inject_fault(stn6_faults[n], sev)

            # ── Station 7 faults ──
            elif cmd.startswith("7f") and len(cmd) >= 3:
                n = cmd[2]
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                if n == "e":
                    fc = station7._fault_counters
                    print(f"\n  ⚡ STN7: jams={fc['sorter_jams']} "
                          f"misroute={fc['misroutes']} "
                          f"brown={fc['brownouts']} stut={fc['belt_stutters']} "
                          f"mis={fc['sensor_misreads']} delay={fc['arm_delays']}\n")
                elif n in stn7_faults:
                    station7.inject_fault(stn7_faults[n], sev)

            # ── Transfer faults (8) ──
            elif cmd.startswith("8f") and len(cmd) >= 3:
                n = cmd[2]
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                if n == "e":
                    fc = transfer._fault_counters
                    print(f"\n  ⚡ TRANSFER: brown={fc['brownouts']} "
                          f"stut={fc['belt_stutters']} jam={fc['pp2_jams']} "
                          f"grab={fc['grab_failures']} "
                          f"mis={fc['sensor_misreads']} delay={fc['move_delays']}\n")
                elif n in stn8_faults:
                    transfer.inject_fault(stn8_faults[n], sev)

            # ── Warehouse faults (9) ──
            elif cmd.startswith("9f") and len(cmd) >= 3:
                n = cmd[2]
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                if n == "e":
                    fc = warehouse._fault_counters
                    print(f"\n  ⚡ WAREHOUSE: brown={fc['brownouts']} "
                          f"drift={fc['crane_drifts']} jam={fc['fork_jams']} "
                          f"mis={fc['sensor_misreads']} delay={fc['timing_delays']}\n")
                elif n in stn9_faults:
                    warehouse.inject_fault(stn9_faults[n], sev)

            elif cmd == "fc":
                station1.clear_fault("all")
                station2.clear_fault("all")
                station3.clear_fault("all")
                station6.clear_fault("all")
                station7.clear_fault("all")
                transfer.clear_fault("all")
                warehouse.clear_fault("all")
                print("  ✅ All faults cleared on all stations")

            elif cmd == "st":
                s1 = station1.get_status()
                s2 = station2.get_status()
                s3 = station3.get_status()
                s6 = station6.get_status()
                s7 = station7.get_status()
                s8 = transfer.get_status()
                s9 = warehouse.get_status()
                print()
                print(f"  STN1: {s1['state']:20s}  done={s1['counters']['products_completed']}"
                      f"  faults={s1['faults']['has_fault']}"
                      f"  emergency={s1['emergency_active']}")
                print(f"  STN2: {s2['state']:20s}  done={s2['counters']['products_completed']}"
                      f"  P&P={s2['pick_and_place']['phase']}"
                      f"  faults={s2['faults']['has_fault']}"
                      f"  emergency={s2['emergency_active']}")
                print(f"  STN3: {s3['state']:20s}  done={s3['counters']['products_completed']}"
                      f"  bar_clamp={s3['positioning_bar']['clamped']}"
                      f"  faults={s3['faults']['has_fault']}"
                      f"  emergency={s3['emergency_active']}")
                print(f"  STN6: {s6['state']:20s}  done={s6['counters']['products_completed']}"
                      f"  pass={s6['counters']['products_passed']}"
                      f"  fail={s6['counters']['products_failed']}"
                      f"  rate={s6['qc']['pass_rate']}%"
                      f"  faults={s6['faults']['has_fault']}")
                print(f"  STN7: {s7['state']:20s}  done={s7['counters']['products_completed']}"
                      f"  good={s7['counters']['products_good']}"
                      f"  reject={s7['counters']['products_rejected']}"
                      f"  rate={s7['sorting']['good_rate']}%"
                      f"  faults={s7['faults']['has_fault']}")
                print(f"  XFER: {s8['state']:20s}  done={s8['counters']['products_completed']}"
                      f"  faults={s8['faults']['has_fault']}")
                print(f"  WH:   {s9['state']:20s}  stored={s9['counters']['products_stored']}"
                      f"  fill={s9['warehouse']['fill_percent']}%"
                      f"  next={s9['warehouse']['next_cell']}")
                print()

            elif cmd == "1rp":
                print(station1.get_full_report())
            elif cmd == "2rp":
                print(station2.get_full_report())
            elif cmd == "3rp":
                print(station3.get_full_report())
            elif cmd == "6rp":
                print(station6.get_full_report())
            elif cmd == "7rp":
                print(station7.get_full_report())
            elif cmd == "8rp":
                print(transfer.get_full_report())
            elif cmd == "9rp":
                print(warehouse.get_full_report())

            elif cmd == "q":
                station1.is_running = False
                station2.is_running = False
                station3.is_running = False
                station6.is_running = False
                station7.is_running = False
                transfer.is_running = False
                warehouse.is_running = False

        except (EOFError, ValueError):
            pass
        except Exception as e:
            print(f"  Error: {e}")


# ═══════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    print()
    print("═" * 70)
    print("  📺 TV ASSEMBLY LINE — FULL LINE + TRANSFER + WAREHOUSE")
    print("  ⚡ REAL Fault Effects on ALL Stations!")
    print("  🔗 Synchronized + Thread-Safe Modbus")
    print("  📡 MQTT Fault Routing: dedicated + broadcast topics")
    print("═" * 70)
    print()

    # ─── Connect to Factory I/O ───
    raw_modbus = FactoryModbusClient()
    if not raw_modbus.connect():
        print("  ❌ Cannot connect to Factory I/O!")
        print("  Make sure Factory I/O is running with Modbus server enabled")
        sys.exit(1)

    # ═══════════════════════════════════════════
    # WRAP with thread-safe lock
    # ═══════════════════════════════════════════
    modbus = ThreadSafeModbus(raw_modbus)
    print("  🔒 Thread-safe Modbus wrapper active")

    # ─── Turn on transition belts ───
    modbus.write_output(BELT_1B, True)
    modbus.write_output(BELT_2B, True)
    modbus.write_output(BELT_3B, True)
    modbus.write_output(BELT_4B, True)
    modbus.write_output(BELT_5B, True)
    print("  🔄 Transition belts ON:")
    print(f"     Belt 1b (addr {BELT_1B}): Stn1 → Stn2")
    print(f"     Belt 2b (addr {BELT_2B}): Stn2 → Stn3")
    print(f"     Belt 3b (addr {BELT_3B}): Stn3 → Stn6")
    print(f"     Belt 4b (addr {BELT_4B}): Stn6 → Stn7")
    print(f"     Belt 5b (addr {BELT_5B}): Stn7 → Transfer")

    # ─── Quick Vision Sensor test ───
    print()
    print("  📷 Testing Vision Sensor...")
    val = raw_modbus.read_register(0)
    if val is not None:
        print(f"  ✅ Vision Sensor register read OK (value: {val})")
    else:
        print("  ⚠️  Vision Sensor register read FAILED!")
        print("     Check: All Numerical config + Register Input 0")

    # ─── Quick Crane Register test ───
    print("  🏗️ Testing Crane Register...")
    crane_val = raw_modbus.read_holding_register(0)
    if crane_val is not None:
        print(f"  ✅ Crane Target register read OK (value: {crane_val})")
    else:
        print("  ⚠️  Crane Target register read FAILED!")

    # ─── Optional MQTT ───
    mqtt = None
    try:
        from core.mqtt_client import MQTTClient
        mqtt = MQTTClient("assembly_line")
        if mqtt.connect():
            print("  ✅ MQTT Connected")
            print("  📡 Fault topics:")
            print("     factory/station_1/faults/inject")
            print("     factory/station_2/faults/inject")
            print("     factory/station_3/faults/inject")
            print("     factory/station_6/faults/inject")
            print("     factory/station_7/faults/inject")
            print("     factory/station_8/faults/inject  (Transfer)")
            print("     factory/station_9/faults/inject  (Warehouse)")
            print("     factory/faults/inject (broadcast)")
        else:
            mqtt = None
            print("  ⚠️  MQTT not available (faults still work via console)")
    except Exception:
        mqtt = None
        print("  ⚠️  MQTT not available (faults still work via console)")

    # ─── Synchronization events ───
    station2_ready = threading.Event()   # Stn2 → Stn1
    station3_ready = threading.Event()   # Stn3 → Stn2
    station6_ready = threading.Event()   # Stn6 → Stn3
    station7_ready = threading.Event()   # Stn7 → Stn6
    pallet_ready = threading.Event()     # Warehouse → Transfer
    product_placed = threading.Event()   # Transfer → Warehouse

    # ─── Create controllers ───
    station1 = SyncedStation1(
        modbus,
        mqtt_client=mqtt,
        downstream_ready=station2_ready,
    )

    station2 = SyncedStation2(
        modbus,
        mqtt_client=mqtt,
        upstream_ready=station2_ready,
        downstream_ready=station3_ready,
    )

    station3 = SyncedStation3(
        modbus,
        mqtt_client=mqtt,
        upstream_ready=station3_ready,
        downstream_ready=station6_ready,
    )

    station6 = LineStation6(
        modbus,
        mqtt_client=mqtt,
        upstream_ready_event=station6_ready,
        downstream_ready_event=station7_ready,
    )

    station7 = LineStation7(
        modbus,
        station6_ref=station6,
        mqtt_client=mqtt,
        upstream_ready_event=station7_ready,
    )

    transfer = LineTransferStation(
        modbus,
        mqtt_client=mqtt,
        pallet_ready_event=pallet_ready,
        product_placed_event=product_placed,
    )

    warehouse = LineWarehouse(
        modbus,
        mqtt_client=mqtt,
        pallet_ready_event=pallet_ready,
        product_placed_event=product_placed,
    )

    print()
    print("  🔗 Synchronization Chain:")
    print("     Station 7 signals 'ready' ──► Station 6 releases product")
    print("     Station 6 signals 'ready' ──► Station 3 accepts product")
    print("     Station 3 signals 'ready' ──► Station 2 releases product")
    print("     Station 2 signals 'ready' ──► Station 1 releases product")
    print("     Belt flow: Stn7 good ──► Transfer belt ──► Transfer P&P")
    print("     Warehouse emits pallet ──► Transfer places ──► Warehouse stores")
    print()
    print("  📦 Product Flow:")
    print("     STN1 (Chassis) ──► STN2 (PCB) ──► STN3 (Display) ──► "
          "STN6 (QC) ──► STN7 (Sort)")
    print("     GOOD ──► Transfer (P&P to pallet) ──► Warehouse (Stacker Crane)")
    print("     REJECT ──► Remover")
    print()
    print("  📷 Vision Sensor: EXPECTED_VALUE = 5 (Green Product Lid = assembled)")
    print()
    print("─" * 70)
    print("  Type fault commands below (or press Ctrl+C to stop)")
    print("  Type 'st' for status, 'fc' to clear faults, 'q' to quit")
    print("─" * 70)

    # ─── Fault injection menu (background thread) ───
    menu_thread = threading.Thread(
        target=fault_menu,
        args=(station1, station2, station3, station6, station7, transfer, warehouse),
        daemon=True,
    )
    menu_thread.start()

    # ═══════════════════════════════════════════════════════
    # START STATIONS — DOWNSTREAM FIRST!
    # ═══════════════════════════════════════════════════════

    # ─── Start Warehouse FIRST (most downstream) ───
    thread_wh = threading.Thread(
        target=warehouse.run,
        daemon=True,
        name="Warehouse",
    )
    thread_wh.start()
    logger.info("✅ Warehouse started!")
    time.sleep(1.0)  # Let warehouse initialize

    # ─── Start Transfer ───
    thread_xfer = threading.Thread(
        target=transfer.run,
        daemon=True,
        name="Transfer",
    )
    thread_xfer.start()
    logger.info("✅ Transfer started!")
    time.sleep(1.0)

    # ─── Start Station 7 ───
    thread7 = threading.Thread(
        target=station7.run,
        daemon=True,
        name="Station7",
    )
    thread7.start()

    logger.info("⏳ Waiting for Station 7 to initialize...")
    if station7_ready.wait(timeout=15):
        logger.info("✅ Station 7 (Sorting) is ready!")
    else:
        logger.warning("⚠️ Station 7 not ready in 15s, starting anyway...")

    # ─── Start Station 6 ───
    thread6 = threading.Thread(
        target=station6.run,
        daemon=True,
        name="Station6",
    )
    thread6.start()

    logger.info("⏳ Waiting for Station 6 to initialize...")
    if station6_ready.wait(timeout=15):
        logger.info("✅ Station 6 (QC) is ready!")
    else:
        logger.warning("⚠️ Station 6 not ready in 15s, starting anyway...")

    # ─── Start Station 3 ───
    thread3 = threading.Thread(
        target=station3.run,
        daemon=True,
        name="Station3",
    )
    thread3.start()

    logger.info("⏳ Waiting for Station 3 to initialize...")
    if station3_ready.wait(timeout=15):
        logger.info("✅ Station 3 is ready!")
    else:
        logger.warning("⚠️ Station 3 not ready in 15s, starting anyway...")

    # ─── Start Station 2 ───
    thread2 = threading.Thread(
        target=station2.run,
        daemon=True,
        name="Station2",
    )
    thread2.start()

    logger.info("⏳ Waiting for Station 2 to initialize...")
    if station2_ready.wait(timeout=15):
        logger.info("✅ Station 2 is ready! Starting Station 1...")
    else:
        logger.warning("⚠️ Station 2 not ready in 15s, starting anyway...")

    # ─── Start Station 1 (most upstream — starts last) ───
    thread1 = threading.Thread(
        target=station1.run,
        daemon=True,
        name="Station1",
    )
    thread1.start()
    logger.info("✅ Station 1 started!")

    logger.info("")
    logger.info("🏭 All 7 stations + Transfer + Warehouse running!")
    logger.info("📦 STN1 → STN2 → STN3 → STN6 → STN7 → Transfer → Warehouse")
    logger.info("")

    # ─── Wait for all threads ───
    all_threads = [thread1, thread2, thread3, thread6, thread7, thread_xfer, thread_wh]
    try:
        while any(t.is_alive() for t in all_threads):
            # Check if warehouse is full → stop the line
            if warehouse.state == "full":
                logger.warning("🛑 WAREHOUSE FULL — stopping all stations!")
                station1.is_running = False
                station2.is_running = False
                station3.is_running = False
                station6.is_running = False
                station7.is_running = False
                transfer.is_running = False
                warehouse.is_running = False
                break
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
        print("  Stopping all stations...")
        station1.is_running = False
        station2.is_running = False
        station3.is_running = False
        station6.is_running = False
        station7.is_running = False
        transfer.is_running = False
        warehouse.is_running = False

    # Wait for threads to finish
    for t in all_threads:
        t.join(timeout=5)

    # ─── Final reports ───
    print()
    print("═" * 70)
    print("  📊 FINAL REPORTS")
    print("═" * 70)
    print(station1.get_full_report())
    print(station2.get_full_report())
    print(station3.get_full_report())
    print(station6.get_full_report())
    print(station7.get_full_report())
    print(transfer.get_full_report())
    print(warehouse.get_full_report())

    # ─── Cleanup ───
    print("  🧹 Cleaning up...")

    try:
        modbus.write_output(BELT_1B, False)
        modbus.write_output(BELT_2B, False)
        modbus.write_output(BELT_3B, False)
        modbus.write_output(BELT_4B, False)
        modbus.write_output(BELT_5B, False)
        print("  ✅ Transition belts OFF")
    except Exception:
        pass

    try:
        if mqtt:
            mqtt.disconnect()
            print("  ✅ MQTT disconnected")
    except Exception:
        pass

    try:
        raw_modbus.disconnect()
        print("  ✅ Modbus disconnected")
    except Exception:
        pass

    print("  Done!")


if __name__ == "__main__":
    main()
