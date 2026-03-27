"""
Run Station 1 + Station 2 + Station 3 together (SYNCHRONIZED)

SYNC CHAIN:
  Station 3 signals 'ready' → Station 2 releases product
  Station 2 signals 'ready' → Station 1 releases product

Each station waits for the DOWNSTREAM station to be ready before releasing.

START ORDER: Downstream first!
  1. Station 3 starts (most downstream)
  2. Station 2 starts
  3. Station 1 starts (most upstream — creates products)

FIXES:
  - Thread-safe Modbus (Lock prevents simultaneous read/write)
  - Sensor-clear checks before waiting for product
  - Downstream sync: each station waits for next station before releasing
  - DO NOT clear ready events in main() — blade() overrides handle clearing
  - Clean MQTT shutdown
  - MQTT fault routing: each station listens on dedicated + broadcast topics

MQTT FAULT TOPICS:
  factory/station_1/faults/inject  → Station 1 only
  factory/station_2/faults/inject  → Station 2 only
  factory/station_3/faults/inject  → Station 3 only
  factory/faults/inject            → Broadcast (station field filters)
"""

import logging
import sys
import os
import threading
import time
import json
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from factory.modbus_client import FactoryModbusClient
from factory.stations.station1 import Station1Controller
from factory.stations.station2 import Station2Controller
from factory.stations.station3 import Station3Controller

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

    # Pass through any other methods/attributes
    def __getattr__(self, name):
        return getattr(self._client, name)


# ═══════════════════════════════════════════════════════════
# TRANSITION BELT ADDRESSES
# ═══════════════════════════════════════════════════════════

BELT_1B = 1      # Transition belt: Station 1 → Station 2
BELT_2B = 10     # Transition belt: Station 2 → Station 3


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
                # Keep simulations and faults running
                belt_on = (self._intended.get("belt1", False)
                           and not self._fault_override_active
                           and not self._emergency_active)
                self._update_simulations(belt_on)
                self._fault_tick()
                self._publish_mqtt()

                # Handle emergency during wait
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

                # Log every 5 seconds
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

        # Call original blade()
        super().blade(up)


# ═══════════════════════════════════════════════════════════
# SYNCED STATION 2 — Waits for Station 3 before releasing
# ═══════════════════════════════════════════════════════════

class SyncedStation2(Station2Controller):
    """
    Station 2 with:
      1. Sensor-clear check before waiting for new product
      2. Downstream sync — waits for Station 3 before releasing

    Overrides:
      - blade(): waits for Station 3 before releasing product
      - run(): adds sensor-clear check at STATE 0 + calls
               _setup_mqtt_fault_listener()
    """

    def __init__(self, modbus_client, mqtt_client=None,
                 upstream_ready=None, downstream_ready=None):
        super().__init__(modbus_client, mqtt_client=mqtt_client,
                         upstream_ready=upstream_ready)
        self._downstream_ready = downstream_ready
        if downstream_ready:
            logger.info("   🔗 STN2: Downstream sync ENABLED (waits for Station 3)")

    def blade(self, up):
        """
        Override: wait for Station 3 before releasing product.

        Only waits when blade goes UP→DOWN (releasing):
          - _intended["stop_blade"] was True (UP, holding product)
          - up = False (going DOWN, releasing)
        """
        is_releasing = (not up) and self._intended.get("stop_blade", False)

        if is_releasing and self._downstream_ready is not None:
            logger.info("")
            logger.info("   ⏸️  STN2: Waiting for Station 3 to be ready...")
            self.state = "wait_downstream"

            wait_start = time.time()
            last_log = 0

            while not self._downstream_ready.is_set() and self.is_running:
                # Keep simulations and faults running
                belt_on = (self._intended.get("belt", False)
                           and not self._fault_override_active
                           and not self._emergency_active)
                self._update_simulations(belt_on)
                self._fault_tick()
                self._publish_mqtt()

                # Handle emergency during wait
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

                # Log every 5 seconds
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

        # Call original blade()
        super().blade(up)

    def run(self):
        """
        Same as Station2Controller.run() but adds a sensor-clear
        check at STATE 0 before waiting for product arrival.

        Calls _setup_mqtt_fault_listener() for proper MQTT routing.
        """
        self.is_running = True
        logger.info("🚀 Station 2 starting — PCB Installation")

        # ═══════════════════════════════════════════════
        # Setup MQTT fault listener (dedicated + broadcast)
        # ═══════════════════════════════════════════════
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

                # ─── STATE 0: Prepare to receive ───
                logger.info("")
                logger.info("═" * 55)
                logger.info("STN2 ┃ STATE 0: Preparing...")
                self.belt(True)
                self.blade(True)
                self._pp_phase = "idle"

                # ════════════════════════════════════════
                # FIX: Wait for sensor to be CLEAR first
                # ════════════════════════════════════════
                if self.read_sensor_station():
                    logger.info("STN2 ┃ Sensor still active — waiting for it to clear...")
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

                # Signal upstream: ready for product
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

                # ─── STATE 1: Product arrived ───
                logger.info("STN2 ┃ STATE 1: ✅ Product arrived!")
                self.belt(False)

                logger.info("STN2 ┃ Creating PCB lid...")
                self.emitter(True)
                self._wait_seconds(self._timing["lid_creation_time"], "s2_creating_lid")
                self.emitter(False)
                self._wait_seconds(self._timing["lid_settle_time"], "s2_lid_settle")

                # ─── STATE 2: Pick Z DOWN ───
                logger.info("STN2 ┃ STATE 2: P&P ↓ DOWN to lid...")
                self._pp_phase = "picking"
                self.pp_move_z(True)
                if not self._wait_pp_move("z", "s2_pick_down"):
                    logger.error("STN2: P&P Z failed!")
                    break

                # ─── STATE 3: Grab ───
                logger.info("STN2 ┃ STATE 3: P&P GRAB...")
                self.pp_grab(True)
                self._wait_seconds(self._timing["grab_settle_time"], "s2_grabbing")

                if self.read_pp_item_detected():
                    logger.info("STN2 ┃ ✅ Item in gripper!")
                    self._pp_has_item = True
                else:
                    logger.warning("STN2 ┃ ⚠️ Item NOT detected, continuing...")
                    self._pp_has_item = True

                # ─── STATE 4: Pick Z UP ───
                logger.info("STN2 ┃ STATE 4: P&P ↑ UP with lid...")
                self.pp_move_z(False)
                if not self._wait_pp_move("z", "s2_pick_up"):
                    break

                # ─── STATE 5: Transfer X ───
                logger.info("STN2 ┃ STATE 5: P&P → PLACE position...")
                self._pp_phase = "transferring"
                self.pp_move_x(True)
                if not self._wait_pp_move("x", "s2_transfer"):
                    break

                if self.faults.gripper_failure and not self.read_pp_item_detected():
                    logger.warning("STN2 ┃ ⚠️ Lid DROPPED during transfer!")
                    self.stats.products_failed += 1

                # ─── STATE 6: Place Z DOWN ───
                logger.info("STN2 ┃ STATE 6: P&P ↓ placing lid...")
                self._pp_phase = "placing"
                self.pp_move_z(True)
                if not self._wait_pp_move("z", "s2_place_down"):
                    break

                # ─── STATE 7: Release ───
                logger.info("STN2 ┃ STATE 7: P&P RELEASE...")
                self.pp_grab(False)
                self._pp_has_item = False
                self._pp_phase = "idle"
                self._wait_seconds(self._timing["release_settle_time"], "s2_releasing")
                logger.info("STN2 ┃ ✅ Lid placed! (Base + Lid = Assembled!)")

                # ─── STATE 8: Return Z UP ───
                logger.info("STN2 ┃ STATE 8: P&P ↑ UP...")
                self.pp_move_z(False)
                if not self._wait_pp_move("z", "s2_return_up"):
                    break

                # ─── STATE 9: Return X HOME ───
                logger.info("STN2 ┃ STATE 9: P&P → PICK position...")
                self.pp_move_x(False)
                if not self._wait_pp_move("x", "s2_return_home"):
                    break
                logger.info("STN2 ┃ ✅ P&P home")

                # ─── STATE 10: Release product ───
                # blade(False) will WAIT for Station 3 to be ready
                logger.info("STN2 ┃ STATE 10: Blade DOWN...")
                self.blade(False)
                self._wait_seconds(self._timing["blade_lower_time"], "s2_blade_lower")

                # ─── STATE 11: Send out ───
                logger.info("STN2 ┃ STATE 11: Belt ON → Station 3")
                self.belt(True)

                if self.read_sensor_station():
                    self._wait_for(
                        lambda: not self.read_sensor_station(),
                        timeout=15.0,
                        state_name="s2_product_leaving",
                    )
                self._wait_seconds(self._timing["product_exit_time"], "s2_product_clear")

                # ─── Cycle complete ───
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
# SYNCED STATION 3 — Signals upstream when ready
# ═══════════════════════════════════════════════════════════

class SyncedStation3(Station3Controller):
    """
    Station 3 — uses the base Station3Controller which already handles:
      - Sensor-clear check before waiting for product
      - upstream_ready signaling (tells Station 2 it's ready)
      - _setup_mqtt_fault_listener() called in run()

    No downstream sync needed yet (Station 3 is the last station).
    Does NOT override run() — inherits base which handles everything.
    """
    pass


# ═══════════════════════════════════════════════════════════
# FAULT INJECTION MENU (direct method calls, no MQTT needed)
# ═══════════════════════════════════════════════════════════

def fault_menu(station1, station2, station3):
    """Combined fault injection for all three stations."""
    print()
    print("  ┌────────────────────────────────────────────────────────────────────┐")
    print("  │  📺 TV ASSEMBLY LINE — Fault Injection ⚡                          │")
    print("  │                                                                    │")
    print("  │  STATION 1 (Chassis):   STATION 2 (PCB P&P):  STATION 3 (Panel):  │")
    print("  │  1f1 [s] = Overheat     2f1 [s] = Overheat    3f1 [s] = Overheat  │")
    print("  │  1f2 [s] = Vibration    2f3 [s] = Power       3f3 [s] = Power     │")
    print("  │  1f3 [s] = Power        2f4 [s] = Belt Slip   3f4 [s] = Belt Slip │")
    print("  │  1f4 [s] = Belt Slip    2f5 [s] = Sensor      3f5 [s] = Sensor    │")
    print("  │  1f5 [s] = Sensor       2f6 [s] = Gripper ⚡   3f6 [s] = Pos Jam   │")
    print("  │                         2f7 [s] = P&P Jam                         │")
    print("  │                                                                    │")
    print("  │  fc = Clear ALL    st = Status    q = Quit                         │")
    print("  │  1fe/2fe/3fe = Effects    1rp/2rp/3rp = Reports                    │")
    print("  └────────────────────────────────────────────────────────────────────┘")
    print()

    stn1_faults = {"1": "overheat", "2": "vibration", "3": "power",
                   "4": "belt_slip", "5": "sensor_drift"}
    stn2_faults = {"1": "overheat", "3": "power", "4": "belt_slip",
                   "5": "sensor_drift", "6": "gripper", "7": "pp_jam"}
    stn3_faults = {"1": "overheat", "3": "power", "4": "belt_slip",
                   "5": "sensor_drift", "6": "positioner_jam"}

    while station1.is_running or station2.is_running or station3.is_running:
        try:
            cmd = input().strip().lower()
            if not cmd:
                continue

            # Station 1 faults
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

            # Station 2 faults
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

            # Station 3 faults
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

            elif cmd == "fc":
                station1.clear_fault("all")
                station2.clear_fault("all")
                station3.clear_fault("all")
                print("  ✅ All faults cleared on all stations")

            elif cmd == "st":
                s1 = station1.get_status()
                s2 = station2.get_status()
                s3 = station3.get_status()
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
                print()

            elif cmd == "1rp":
                print(station1.get_full_report())
            elif cmd == "2rp":
                print(station2.get_full_report())
            elif cmd == "3rp":
                print(station3.get_full_report())

            elif cmd == "q":
                station1.is_running = False
                station2.is_running = False
                station3.is_running = False

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
    print("  📺 TV ASSEMBLY LINE — STATION 1 + STATION 2 + STATION 3")
    print("  ⚡ REAL Fault Effects Enabled!")
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
    print("  🔄 Transition belts ON (Belt 1b @ addr 1, Belt 2b @ addr 10)")

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
            print("     factory/faults/inject (broadcast)")
        else:
            mqtt = None
            print("  ⚠️  MQTT not available (faults still work via console)")
    except Exception:
        mqtt = None
        print("  ⚠️  MQTT not available (faults still work via console)")

    # ─── Synchronization events ───
    # Station 2 sets this when ready → Station 1 waits for it
    station2_ready = threading.Event()

    # Station 3 sets this when ready → Station 2 waits for it
    station3_ready = threading.Event()

    # ─── Create controllers (using thread-safe modbus) ───
    station1 = SyncedStation1(
        modbus,
        mqtt_client=mqtt,
        downstream_ready=station2_ready,   # Waits for Station 2
    )

    station2 = SyncedStation2(
        modbus,
        mqtt_client=mqtt,
        upstream_ready=station2_ready,     # Signals Station 1 when ready
        downstream_ready=station3_ready,   # Waits for Station 3
    )

    station3 = SyncedStation3(
        modbus,
        mqtt_client=mqtt,
        upstream_ready=station3_ready,     # Signals Station 2 when ready
    )

    print()
    print("  🔗 Synchronization Chain:")
    print("     Station 3 signals 'ready' ──► Station 2 releases product")
    print("     Station 2 signals 'ready' ──► Station 1 releases product")
    print()
    print("  📦 Product Flow:")
    print("     STN1 (Chassis) ──► STN2 (PCB) ──► STN3 (Display) ──► Exit")
    print()
    print("─" * 70)
    print("  Type fault commands below (or press Ctrl+C to stop)")
    print("  Type 'st' for status, 'fc' to clear faults, 'q' to quit")
    print("─" * 70)

    # ─── Fault injection menu (runs in background, reads stdin) ───
    menu_thread = threading.Thread(
        target=fault_menu,
        args=(station1, station2, station3),
        daemon=True,
    )
    menu_thread.start()

    # ═══════════════════════════════════════════════════════
    # START STATIONS — DOWNSTREAM FIRST!
    #
    # IMPORTANT: Do NOT clear the ready events after waiting!
    # The blade() overrides handle clearing during normal operation.
    # Clearing here causes a deadlock where Station 1 waits forever.
    # ═══════════════════════════════════════════════════════

    # ─── Start Station 3 FIRST (most downstream) ───
    thread3 = threading.Thread(
        target=station3.run,
        daemon=True,
        name="Station3",
    )
    thread3.start()

    # Wait for Station 3 to signal ready
    logger.info("⏳ Waiting for Station 3 to initialize...")
    if station3_ready.wait(timeout=15):
        logger.info("✅ Station 3 is ready!")
        # DO NOT CLEAR — Station 2's blade() will clear when it releases
    else:
        logger.warning("⚠️ Station 3 not ready in 15s, starting anyway...")

    # ─── Start Station 2 ───
    thread2 = threading.Thread(
        target=station2.run,
        daemon=True,
        name="Station2",
    )
    thread2.start()

    # Wait for Station 2 to signal ready
    logger.info("⏳ Waiting for Station 2 to initialize...")
    if station2_ready.wait(timeout=15):
        logger.info("✅ Station 2 is ready! Starting Station 1...")
        # DO NOT CLEAR — Station 1's blade() will clear when it releases
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
    logger.info("🏭 All 3 stations running! Product flow active.")
    logger.info("")

    # ─── Wait for all threads ───
    try:
        while thread1.is_alive() or thread2.is_alive() or thread3.is_alive():
            time.sleep(0.5)
    except KeyboardInterrupt:
        print()
        print("  Stopping all stations...")
        station1.is_running = False
        station2.is_running = False
        station3.is_running = False

    # Wait for threads to finish
    thread1.join(timeout=5)
    thread2.join(timeout=5)
    thread3.join(timeout=5)

    # ─── Final reports ───
    print()
    print("═" * 70)
    print("  📊 FINAL REPORTS")
    print("═" * 70)
    print(station1.get_full_report())
    print(station2.get_full_report())
    print(station3.get_full_report())

    # ─── Cleanup ───
    print("  🧹 Cleaning up...")

    # Turn off transition belts
    try:
        modbus.write_output(BELT_1B, False)
        modbus.write_output(BELT_2B, False)
        print("  ✅ Transition belts OFF")
    except Exception:
        pass

    # Disconnect MQTT
    try:
        if mqtt:
            mqtt.disconnect()
            print("  ✅ MQTT disconnected")
    except Exception:
        pass

    # Disconnect Modbus
    try:
        raw_modbus.disconnect()
        print("  ✅ Modbus disconnected")
    except Exception:
        pass

    print("  Done!")


if __name__ == "__main__":
    main()