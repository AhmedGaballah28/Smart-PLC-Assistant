"""
factory/stations/warehouse.py

Warehouse Controller — 3 Racks (54 cells)
Stacker Crane Numerical Mode

TWO MODES:
  STANDALONE: addresses start at 0 (for run_warehouse_test.py)
  INTEGRATED: addresses from actual Factory I/O config (for run_line.py)
    - No emitter (products arrive from transfer station)
    - No entry/exit sensors (uses timed waits)
    - No exit conveyors or remover (store only)

SEQUENCES:
  PICKUP:   LEFT → LIFT → MIDDLE → LIFT OFF
  STORE:    LIFT → RIGHT → LIFT OFF → MIDDLE
  RETRIEVE: LEFT → LIFT → MIDDLE → LIFT OFF
  PUTDOWN:  LIFT → RIGHT → LIFT OFF → MIDDLE
"""

import logging
import time

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# ADDRESS PRESETS
# ═══════════════════════════════════════════════════════════

# For standalone testing (run_warehouse_test.py)
STANDALONE_ADDRESSES = {
    'OUT': {
        'emitter':          0,
        'entry_roller':     1,
        'entry_loading':    2,
        'crane_left':       3,
        'crane_right':      4,
        'crane_lift':       5,
        'exit_loading':     6,
        'exit_roller':      7,
        'remover':          8,
    },
    'IN': {
        'entry_sensor':     0,
        'moving_x':         1,
        'moving_z':         2,
        'left_limit':       3,
        'middle_limit':     4,
        'right_limit':      5,
        'exit_sensor':      6,
    },
    'REG': {
        'target_position':  0,
    },
}

# For full assembly line (run_line.py)
# Matches actual Factory I/O driver configuration
#
# Coils:
#   35 = Stacker Crane 0 Lift
#   36 = Stacker Crane 0 (Left)
#   37 = Stacker Crane 0 (Right)
#   38 = Loading Conveyor 1
#   39 = Roller Conveyor 1 (warehouse)
#
# Inputs:
#   18 = Stacker Crane 0 Moving-X
#   19 = Stacker Crane 0 Moving-Z
#   20 = Stacker Crane 0 Left Limit
#   21 = Stacker Crane 0 Middle Limit
#   22 = Stacker Crane 0 Right Limit
#
# Holding Reg 0 = Stacker Crane 0 Target Position
# Input Reg 0   = Vision Sensor (different register space — no conflict)
#
INTEGRATED_ADDRESSES = {
    'OUT': {
        'crane_lift':       35,
        'crane_left':       36,
        'crane_right':      37,
        'entry_loading':    38,   # Loading Conveyor 1
        'entry_roller':     39,   # Roller Conveyor 1 (warehouse)
    },
    'IN': {
        'entry_sensor':     23,
        'moving_x':         18,
        'moving_z':         19,
        'left_limit':       20,
        'middle_limit':     21,
        'right_limit':      22,
    },
    'REG': {
        'target_position':  0,    # Holding Reg 0
    },
}


class WarehouseController:

    TIMING = {
        'emitter_pulse':    0.5,
        'emitter_settle':   0.5,
        'entry_timeout':   30.0,
        'entry_timed_wait': 8.0,   # seconds to wait when no entry sensor
        'load_extra':       2.0,
        'load_settle':      1.0,
        'crane_timeout':   30.0,
        'crane_start':      1.0,
        'crane_settle':     0.5,
        'forks_timeout':   10.0,
        'lift_time':        1.0,
        'lift_settle':      0.5,
        'exit_timeout':    15.0,
        'exit_clear':       3.0,
        'settle':           0.5,
        'product_timeout': 120.0,
    }

    MAX_CELLS = 54

    def __init__(self, modbus_client, mqtt_client=None, integrated=False, config=None):
        """
        Args:
            modbus_client: Modbus connection (or ThreadSafeModbus wrapper)
            mqtt_client: Optional MQTT client
            integrated: False = standalone (addr 0+), True = assembly line
            config: Optional config dict for dynamic offsets (e.g. twin line)
        """
        self.modbus = modbus_client
        self.mqtt = mqtt_client
        self.running = False
        self.state = "idle"
        self.next_cell = 1
        self.occupied = set()
        self.products_stored = 0
        self.products_retrieved = 0
        self.store_errors = 0
        self.last_cell_used = 0
        self.integrated = integrated
        self.config = config or {}
        
        self.WH_ID = self.config.get("id", "warehouse")
        is_line2 = "line2" in self.WH_ID.lower()
        
        io_offset = 100 if is_line2 else 0
        reg_offset = 10 if is_line2 else 0

        # Pick address set based on mode
        if integrated:
            # Apply offsets to INTEGRATED_ADDRESSES
            addrs = {
                'OUT': {k: v + io_offset for k, v in INTEGRATED_ADDRESSES['OUT'].items()},
                'IN': {k: v + io_offset for k, v in INTEGRATED_ADDRESSES['IN'].items()},
                'REG': {k: v + reg_offset for k, v in INTEGRATED_ADDRESSES['REG'].items()}
            }
            logger.info(f"WH ({self.WH_ID}): 🔗 INTEGRATED mode")
            logger.info(f"     Crane:  Coils {35+io_offset}-{37+io_offset}  Inputs {18+io_offset}-{22+io_offset}")
            logger.info(f"     Convey: Coils {38+io_offset}-{39+io_offset}  (Loading + Roller)")
            logger.info(f"     Reg:    Holding Reg {0+reg_offset} (Target Position)")
            logger.info(f"     ⚠️ No entry/exit sensors — using timed waits")
            logger.info(f"     ⚠️ No exit conveyors — store only")
        else:
            addrs = STANDALONE_ADDRESSES
            logger.info(f"WH ({self.WH_ID}): 🔧 STANDALONE mode")
            logger.info(f"     Coils: 0-8, Inputs: 0-6, Register: 0")

        self.OUT = dict(addrs['OUT'])
        self.IN = dict(addrs['IN'])
        self.REG = dict(addrs['REG'])

        # Track what's available
        self.has_entry_sensor = 'entry_sensor' in self.IN
        self.has_exit_sensor = 'exit_sensor' in self.IN
        self.has_emitter = 'emitter' in self.OUT
        self.has_exit_loading = 'exit_loading' in self.OUT
        self.has_exit_roller = 'exit_roller' in self.OUT
        self.has_remover = 'remover' in self.OUT

    # ═══════════════════════════════════════════
    # ACTUATORS
    # ═══════════════════════════════════════════

    def emitter(self, on):
        """Only works in standalone mode."""
        if self.has_emitter:
            self.modbus.write_output(self.OUT['emitter'], on)

    def entry_roller(self, on):
        self.modbus.write_output(self.OUT['entry_roller'], on)

    def entry_loading(self, on):
        self.modbus.write_output(self.OUT['entry_loading'], on)

    def entry_all(self, on):
        self.entry_roller(on)
        self.entry_loading(on)

    def crane_left(self, on):
        self.modbus.write_output(self.OUT['crane_left'], on)

    def crane_right(self, on):
        self.modbus.write_output(self.OUT['crane_right'], on)

    def crane_lift(self, on):
        self.modbus.write_output(self.OUT['crane_lift'], on)

    def exit_loading(self, on):
        if self.has_exit_loading:
            self.modbus.write_output(self.OUT['exit_loading'], on)

    def exit_roller(self, on):
        if self.has_exit_roller:
            self.modbus.write_output(self.OUT['exit_roller'], on)

    def exit_all(self, on):
        self.exit_loading(on)
        self.exit_roller(on)

    def remover(self, on):
        if self.has_remover:
            self.modbus.write_output(self.OUT['remover'], on)

    def set_target(self, cell):
        cell = int(cell)
        reg_addr = self.REG['target_position']
        logger.info(f"WH: 📍 set_target({cell}) → Holding Reg {reg_addr}")
        success = self.modbus.write_register(reg_addr, cell)
        if not success:
            logger.error("WH: ❌ FAILED to write Target Position!")
            return False

        # Readback verification (may not work in integrated mode
        # because read_register might read Input Reg instead of Holding Reg)
        if not self.integrated:
            readback = self.modbus.read_register(reg_addr)
            if readback is not None and readback == cell:
                logger.info(f"WH: ✅ Target verified: {readback}")
            elif readback is not None:
                logger.warning(f"WH: ⚠️ Wrote {cell}, read {readback}")
        else:
            logger.info(f"WH: ✅ Target set to {cell}")

        return True

    # ═══════════════════════════════════════════
    # SENSORS
    # ═══════════════════════════════════════════

    def _read_sensor(self, name):
        if name not in self.IN:
            return False
        addr = self.IN[name]
        result = self.modbus.read_inputs(addr, 1)
        if result is not None and len(result) > 0:
            return bool(result[0])
        return False

    def entry_sensor(self):
        return self._read_sensor('entry_sensor')

    def moving_x(self):
        return self._read_sensor('moving_x')

    def moving_z(self):
        return self._read_sensor('moving_z')

    def left_limit(self):
        return self._read_sensor('left_limit')

    def middle_limit(self):
        return self._read_sensor('middle_limit')

    def right_limit(self):
        return self._read_sensor('right_limit')

    def exit_sensor(self):
        return self._read_sensor('exit_sensor')

    def crane_busy(self):
        return self.moving_x() or self.moving_z()

    def read_all_sensors(self):
        return {name: self._read_sensor(name) for name in self.IN}

    # ═══════════════════════════════════════════
    # WAIT HELPERS
    # ═══════════════════════════════════════════

    def _wait_for(self, condition_fn, timeout, desc="condition"):
        start = time.time()
        while not condition_fn() and self.running:
            if time.time() - start > timeout:
                logger.warning(f"WH: ⏰ Timeout: {desc} ({timeout:.0f}s)")
                return False
            time.sleep(0.1)
        return self.running

    def _wait_until_clear(self, condition_fn, timeout, desc="clear"):
        return self._wait_for(lambda: not condition_fn(), timeout, desc)

    def _wait_seconds(self, seconds, desc="delay"):
        start = time.time()
        while (time.time() - start) < seconds and self.running:
            time.sleep(0.05)
        return self.running

    def _wait_crane_stopped(self, timeout=None):
        if timeout is None:
            timeout = self.TIMING['crane_timeout']
        self._wait_seconds(self.TIMING['crane_start'], "crane_start")
        if not self.crane_busy():
            logger.info("WH:    ℹ️ Crane already at target")
            self._wait_seconds(self.TIMING['crane_settle'], "settle")
            return True
        logger.info("WH:    ⏳ Crane moving...")
        start = time.time()
        last_log = 0
        while self.crane_busy() and self.running:
            elapsed = time.time() - start
            if elapsed > timeout:
                logger.error("WH: ❌ Crane timeout!")
                return False
            if elapsed - last_log >= 3.0:
                logger.info(f"WH:    ⏳ X={self.moving_x()} "
                            f"Z={self.moving_z()} ({elapsed:.0f}s)")
                last_log = elapsed
            time.sleep(0.1)
        elapsed = time.time() - start
        logger.info(f"WH:    ✅ Arrived! ({elapsed:.1f}s)")
        self._wait_seconds(self.TIMING['crane_settle'], "settle")
        return True

    def _wait_forks_left(self):
        logger.info("WH:    ⏳ Forks → LEFT...")
        if self._wait_for(self.left_limit, self.TIMING['forks_timeout'], "left"):
            logger.info("WH:    ✅ Left Limit")
            return True
        logger.warning("WH:    ⚠️ Left timeout")
        return True

    def _wait_forks_right(self):
        logger.info("WH:    ⏳ Forks → RIGHT...")
        if self._wait_for(self.right_limit, self.TIMING['forks_timeout'], "right"):
            logger.info("WH:    ✅ Right Limit")
            return True
        logger.warning("WH:    ⚠️ Right timeout")
        return True

    def _wait_forks_middle(self):
        logger.info("WH:    ⏳ Forks → MIDDLE...")
        if self._wait_for(self.middle_limit, self.TIMING['forks_timeout'], "middle"):
            logger.info("WH:    ✅ Middle Limit")
            return True
        logger.warning("WH:    ⚠️ Middle timeout")
        return True

    # ═══════════════════════════════════════════
    # FORK SEQUENCES
    # ═══════════════════════════════════════════

    def _pickup_from_conveyor(self):
        """LEFT → LIFT → MIDDLE → LIFT OFF"""
        logger.info("WH ┃ ── PICKUP: LEFT → LIFT → MIDDLE → LIFT OFF ──")
        self.crane_left(True)
        self._wait_forks_left()
        self._wait_seconds(self.TIMING['settle'], "s")
        self.crane_lift(True)
        self._wait_seconds(self.TIMING['lift_time'], "lift")
        self.crane_left(False)
        self._wait_forks_middle()
        self._wait_seconds(self.TIMING['settle'], "s")
        self.crane_lift(False)
        self._wait_seconds(self.TIMING['lift_settle'], "s")
        logger.info("WH ┃ ── ✅ PICKUP done ──")

    def _store_into_rack(self):
        """LIFT → RIGHT → LIFT OFF → MIDDLE"""
        logger.info("WH ┃ ── STORE: LIFT → RIGHT → LIFT OFF → MIDDLE ──")
        self.crane_lift(True)
        self._wait_seconds(self.TIMING['lift_time'], "lift")
        self.crane_right(True)
        self._wait_forks_right()
        self._wait_seconds(self.TIMING['settle'], "s")
        self.crane_lift(False)
        self._wait_seconds(self.TIMING['lift_settle'], "s")
        self.crane_right(False)
        self._wait_forks_middle()
        self._wait_seconds(self.TIMING['settle'], "s")
        logger.info("WH ┃ ── ✅ STORE done ──")

    def _retrieve_from_rack(self):
        """LEFT → LIFT → MIDDLE → LIFT OFF"""
        logger.info("WH ┃ ── RETRIEVE: LEFT → LIFT → MIDDLE → LIFT OFF ──")
        self.crane_left(True)
        self._wait_forks_left()
        self._wait_seconds(self.TIMING['settle'], "s")
        self.crane_lift(True)
        self._wait_seconds(self.TIMING['lift_time'], "lift")
        self.crane_left(False)
        self._wait_forks_middle()
        self._wait_seconds(self.TIMING['settle'], "s")
        self.crane_lift(False)
        self._wait_seconds(self.TIMING['lift_settle'], "s")
        logger.info("WH ┃ ── ✅ RETRIEVE done ──")

    def _putdown_onto_conveyor(self):
        """LIFT → RIGHT → LIFT OFF → MIDDLE"""
        logger.info("WH ┃ ── PUTDOWN: LIFT → RIGHT → LIFT OFF → MIDDLE ──")
        self.crane_lift(True)
        self._wait_seconds(self.TIMING['lift_time'], "lift")
        self.crane_right(True)
        self._wait_forks_right()
        self._wait_seconds(self.TIMING['settle'], "s")
        self.crane_lift(False)
        self._wait_seconds(self.TIMING['lift_settle'], "s")
        self.crane_right(False)
        self._wait_forks_middle()
        self._wait_seconds(self.TIMING['settle'], "s")
        logger.info("WH ┃ ── ✅ PUTDOWN done ──")

    # ═══════════════════════════════════════════
    # EMIT (standalone only)
    # ═══════════════════════════════════════════

    def emit_product(self):
        if not self.has_emitter:
            logger.warning("WH: No emitter in integrated mode!")
            return
        logger.info("WH: 📦 Creating product...")
        self.emitter(True)
        self._wait_seconds(self.TIMING['emitter_pulse'], "em")
        self.emitter(False)
        self._wait_seconds(self.TIMING['emitter_settle'], "s")
        logger.info("WH: ✅ Created!")

    # ═══════════════════════════════════════════
    # REGISTER TEST
    # ═══════════════════════════════════════════

    def test_register(self):
        reg_addr = self.REG['target_position']
        print(f"\n  🔍 REGISTER TEST — Holding Reg {reg_addr}")
        print(f"  {'─' * 40}")
        current = self.modbus.read_register(reg_addr)
        print(f"  1. Current: {current}")
        if current is None:
            print("  ❌ Read failed!"); return False
        success = self.modbus.write_register(reg_addr, 1)
        print(f"  2. Write 1: {success}")
        if not success:
            print("  ❌ Write failed!"); return False
        time.sleep(0.5)
        rb = self.modbus.read_register(reg_addr)
        print(f"  3. Readback: {rb}")
        if rb != 1:
            print(f"  ⚠️ Mismatch (may be normal in integrated mode)")
        else:
            print("  ✅ Register works!")
        time.sleep(1.0)
        print(f"  4. Crane: X={self.moving_x()} Z={self.moving_z()}")
        self.modbus.write_register(reg_addr, 0)
        print(f"  5. Reset to 0")
        print(f"  {'─' * 40}")
        return True

    # ═══════════════════════════════════════════
    # STORE CYCLE
    # ═══════════════════════════════════════════

    def store_product(self, use_emitter=False):
        """
        Full store cycle.

        In integrated mode:
          - No emitter (products arrive from transfer station)
          - No entry sensor (uses timed wait)
        """
        if self.next_cell > self.MAX_CELLS:
            logger.warning("WH: ❌ FULL!")
            self.state = "full"
            return False

        cell = self.next_cell
        cycle_start = time.time()

        logger.info("")
        logger.info("═" * 55)
        logger.info(f"WH ┃ STORE — Cell {cell} / {self.MAX_CELLS}")
        logger.info("═" * 55)

        # ══════ PHASE 1: PREPARE ══════

        if use_emitter and self.has_emitter:
            self.state = "emitting"
            self.emit_product()

        self.state = "preparing"
        logger.info("WH ┃ PHASE 1: Prepare crane at rest...")
        self.set_target(55)
        if not self._wait_crane_stopped():
            logger.warning("WH: ⚠️ Crane didn't reach rest")

        self.crane_lift(False)
        if not self.middle_limit():
            logger.info("WH ┃ Retracting forks...")
            self.crane_left(False)
            self.crane_right(False)
            self._wait_forks_middle()

        # ══════ PHASE 2: PRODUCT → PLATFORM ══════

        self.state = "wait_entry"
        self.entry_all(True)

        if self.has_entry_sensor:
            # Standalone mode: wait for entry sensor
            if self.integrated:
                logger.info("WH ┃ PHASE 2: Waiting for product from assembly line...")
            else:
                logger.info("WH ┃ PHASE 2: Entry conveyors ON, waiting for sensor...")

            timeout = self.TIMING['product_timeout'] if self.integrated else self.TIMING['entry_timeout']
            if not self._wait_for(self.entry_sensor, timeout, "entry sensor"):
                if not self.running:
                    return False
                logger.warning("WH: ❌ No product!")
                self.entry_all(False)
                self.store_errors += 1
                return False

            logger.info("WH ┃ ✅ Entry sensor!")
        else:
            # Integrated mode: no entry sensor — timed wait
            logger.info("WH ┃ PHASE 2: Entry conveyors ON (no sensor — timed wait)...")
            logger.info(f"WH ┃ Waiting {self.TIMING['entry_timed_wait']}s for pallet to arrive...")
            self._wait_seconds(self.TIMING['entry_timed_wait'], "entry_timed")
            logger.info("WH ┃ ✅ Timed wait complete — assuming pallet on platform")

        self.state = "loading"
        logger.info("WH ┃ Pushing onto platform...")
        self._wait_seconds(self.TIMING['load_extra'], "push")
        self.entry_all(False)
        self._wait_seconds(self.TIMING['load_settle'], "settle")
        logger.info("WH ┃ ✅ Product on platform!")

        # ══════ PHASE 3: PICKUP ══════

        self.state = "pickup"
        logger.info("")
        logger.info("WH ┃ PHASE 3: PICKUP from conveyor")
        self._pickup_from_conveyor()
        logger.info("WH ┃ ✅ Product on forks!")
        logger.info("")

        # ══════ PHASE 4: CRANE → CELL ══════

        self.state = f"crane_to_{cell}"
        logger.info(f"WH ┃ PHASE 4: Crane → cell {cell}...")

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

        # ══════ PHASE 5: STORE ══════

        self.state = "storing"
        logger.info("")
        logger.info("WH ┃ PHASE 5: STORE into rack")
        self._store_into_rack()
        logger.info("WH ┃ ✅ Product on shelf!")
        logger.info("")

        # ══════ PHASE 6: HOME ══════

        self.state = "returning"
        logger.info("WH ┃ PHASE 6: Crane → rest...")
        self.set_target(55)
        if not self._wait_crane_stopped():
            logger.warning("WH: ⚠️ Slow return")

        # ══════ DONE ══════

        self.state = "idle"
        self.occupied.add(cell)
        self.last_cell_used = cell
        self.next_cell = cell + 1
        self.products_stored += 1

        elapsed = time.time() - cycle_start
        filled = len(self.occupied)
        pct = filled / self.MAX_CELLS * 100

        logger.info("")
        logger.info(f"✅ Product #{self.products_stored} → cell {cell} ({elapsed:.1f}s)")
        logger.info(f"   📦 {filled}/{self.MAX_CELLS} ({pct:.0f}%)")
        logger.info("")
        return True

    # ═══════════════════════════════════════════
    # RETRIEVE CYCLE
    # ═══════════════════════════════════════════

    def retrieve_product(self, cell):
        """
        Retrieve from rack. Only works fully in standalone mode
        (integrated mode has no exit conveyors).
        """
        if cell not in self.occupied:
            logger.warning(f"WH: Cell {cell} EMPTY!")
            return False

        cycle_start = time.time()

        logger.info("")
        logger.info("═" * 55)
        logger.info(f"WH ┃ RETRIEVE — Cell {cell}")
        logger.info("═" * 55)

        self.crane_lift(False)
        if not self.middle_limit():
            self.crane_left(False)
            self.crane_right(False)
            self._wait_forks_middle()

        self.state = f"retrieve_{cell}"
        logger.info(f"WH ┃ PHASE 1: Crane → cell {cell}...")
        if not self.set_target(cell):
            return False
        if not self._wait_crane_stopped():
            return False

        self.state = "retrieving"
        logger.info("WH ┃ PHASE 2: RETRIEVE from rack")
        self._retrieve_from_rack()

        self.state = "retrieve_return"
        logger.info("WH ┃ PHASE 3: Crane → rest...")
        self.set_target(55)
        if not self._wait_crane_stopped():
            logger.warning("WH: ⚠️ Slow return")

        self.state = "retrieve_putdown"
        logger.info("WH ┃ PHASE 4: PUTDOWN onto exit conveyor")
        self._putdown_onto_conveyor()

        if self.has_exit_loading or self.has_exit_roller:
            self.state = "retrieve_exit"
            logger.info("WH ┃ PHASE 5: Exit conveyors ON...")
            self.exit_all(True)

            if self.has_exit_sensor:
                if self._wait_for(self.exit_sensor, self.TIMING['exit_timeout'], "exit"):
                    logger.info("WH ┃ ✅ Exit sensor!")
                    self._wait_seconds(self.TIMING['exit_clear'], "clear")
                else:
                    logger.warning("WH: ⚠️ Exit timeout")
                    self._wait_seconds(5.0, "fallback")
            else:
                logger.info("WH ┃ No exit sensor — timed wait...")
                self._wait_seconds(5.0, "exit_timed")

            self.exit_all(False)
        else:
            logger.info("WH ┃ No exit conveyors available (integrated mode)")
            logger.info("WH ┃ Product on crane forks at rest position")

        self.state = "idle"
        self.occupied.discard(cell)
        self.products_retrieved += 1

        elapsed = time.time() - cycle_start
        logger.info(f"✅ Retrieved cell {cell}! ({elapsed:.1f}s)")
        return True

    # ═══════════════════════════════════════════
    # ALL OFF
    # ═══════════════════════════════════════════

    def all_off(self):
        logger.info("WH: 🛑 All OFF")
        for addr in self.OUT.values():
            try:
                self.modbus.write_output(addr, False)
            except Exception:
                pass
        try:
            self.modbus.write_register(self.REG['target_position'], 0)
        except Exception:
            pass

    # ═══════════════════════════════════════════
    # MAIN LOOP
    # ═══════════════════════════════════════════

    def main(self, use_emitter=False):
        self.running = True
        if self.integrated:
            logger.info("🏭 Warehouse starting (LINE FEED — no emitter)")
            logger.info("   Products arrive from transfer station on pallet")
            logger.info("   Entry: Roller (Coil 39) → Loading (Coil 38) → Crane")
            logger.info("   No entry sensor — timed wait")
        else:
            mode = "EMITTER" if use_emitter else "EXTERNAL"
            logger.info(f"🏭 Warehouse starting ({mode})")
        logger.info(f"   {self.MAX_CELLS} cells (3 racks)")
        logger.info(f"   PICKUP:  LEFT → LIFT → MIDDLE → LIFT OFF")
        logger.info(f"   STORE:   LIFT → RIGHT → LIFT OFF → MIDDLE")

        try:
            while self.running:
                if self.next_cell > self.MAX_CELLS:
                    logger.warning("WH: FULL!")
                    self._wait_seconds(5.0, "full")
                    continue
                success = self.store_product(
                    use_emitter=use_emitter and self.has_emitter
                )
                if not success and self.running:
                    self._wait_seconds(3.0, "retry")
        except KeyboardInterrupt:
            pass
        finally:
            self.running = False
            self.all_off()

    @property
    def is_running(self):
        return self.running

    @is_running.setter
    def is_running(self, value):
        self.running = value

    def run(self, use_emitter=False):
        self.is_running = True
        self.main(use_emitter=use_emitter)

    def stop(self):
        self.running = False
        self.is_running = False

    # ─── Fault Injection / Clearing ──────────────────────────────

    def inject_fault(self, fault_type, severity=3):
        """Inject a fault into this station.

        Supported fault types: overheat, power, belt_slip, sensor_drift, crane_jam, stacker_error
        Severity: 1-5
        """
        severity = max(1, min(5, int(severity)))
        if not hasattr(self, "active_faults"):
            self.active_faults = {}
        if not hasattr(self, "fault_counters"):
            self.fault_counters = {}
        self.active_faults[fault_type] = severity
        self.fault_counters[fault_type] = self.fault_counters.get(fault_type, 0) + 1
        logger.info(f"WH ({self.WH_ID}) ⚡ FAULT INJECTED: {fault_type} severity={severity}")

    def clear_fault(self, fault_type="all"):
        """Clear active fault(s) and reset station state if stuck."""
        if not hasattr(self, "active_faults"):
            self.active_faults = {}
        if fault_type == "all":
            cleared = list(self.active_faults.keys())
            self.active_faults.clear()
            logger.info(f"WH ({self.WH_ID}) ✅ ALL faults cleared: {cleared}")
        elif fault_type in self.active_faults:
            del self.active_faults[fault_type]
            logger.info(f"WH ({self.WH_ID}) ✅ Fault cleared: {fault_type}")
        else:
            logger.info(f"WH ({self.WH_ID}) ⚠️ No active fault '{fault_type}' to clear")

        # Reset state if stuck
        if self.state not in ("idle", "wait_product") and not getattr(self, "active_faults", {}):
            old_state = self.state
            self.state = "idle"
            logger.info(f"WH ({self.WH_ID}) 🔄 State reset from {old_state} → idle (recovery)")

    def apply_parameters(self, params: dict):
        """Apply runtime parameter changes from the AI agent.

        Supported keys:
          clear_fault (str|bool): fault type to clear, or True for "all"
          fan_speed (float): cooling fan percentage 0-100
          speed_factor (float): crane speed multiplier 0.1-2.0
        """
        logger.info(f"WH ({self.WH_ID}) 🔧 apply_parameters: {params}")

        cf = params.get("clear_fault")
        if cf:
            fault_type = cf if isinstance(cf, str) and cf not in ("True", "true") else "all"
            self.clear_fault(fault_type)

        if "fan_speed" in params:
            fan = max(0, min(100, float(params["fan_speed"])))
            logger.info(f"WH ({self.WH_ID})   Fan speed → {fan}%")

        if "speed_factor" in params:
            sf = max(0.1, min(2.0, float(params["speed_factor"])))
            logger.info(f"WH ({self.WH_ID})   Speed factor → {sf}")

    def get_status(self):
        filled = len(self.occupied)
        pct = (filled / self.MAX_CELLS * 100) if self.MAX_CELLS > 0 else 0
        faults = getattr(self, "active_faults", {})
        return {
            'station_id': self.WH_ID,
            'state': self.state,
            'running': self.running,
            'counters': {
                'products_stored': self.products_stored,
                'products_retrieved': self.products_retrieved,
                'store_errors': self.store_errors,
            },
            'warehouse': {
                'next_cell': self.next_cell,
                'occupied_count': filled,
                'capacity': self.MAX_CELLS,
                'fill_percent': round(pct, 1),
                'last_cell': self.last_cell_used,
            },
            'faults': {
                'has_fault': bool(faults),
                'active': list(faults.keys()),
                'details': dict(faults),
            },
        }

    def get_full_report(self):
        filled = len(self.occupied)
        pct = (filled / self.MAX_CELLS * 100) if self.MAX_CELLS > 0 else 0
        cells = sorted(self.occupied) if self.occupied else ["(none)"]

        if self.integrated:
            mode = "INTEGRATED"
            io_info = (f"Crane: Coils 35-37, Inputs 18-22\n"
                       f"  Conveyors:          Coils 38-39 (Loading + Roller)\n"
                       f"  Target Register:    Holding Reg 0\n"
                       f"  Entry Sensor:       None (timed wait)\n"
                       f"  Exit Conveyors:     None (store only)")
        else:
            mode = "STANDALONE"
            io_info = (f"Coils 0-8, Inputs 0-6, Register 0")

        return f"""
╔══════════════════════════════════════╗
║  Warehouse: 3-Rack Stacker Crane    ║
╠══════════════════════════════════════╣
  Mode:               {mode}
  I/O:                {io_info}

  Products Stored:    {self.products_stored}
  Products Retrieved: {self.products_retrieved}
  Store Errors:       {self.store_errors}

  Next Cell:          {self.next_cell}
  Cells Occupied:     {filled} / {self.MAX_CELLS} ({pct:.0f}%)
  Last Cell Used:     {self.last_cell_used}
  Occupied Cells:     {cells}
╚══════════════════════════════════════╝"""