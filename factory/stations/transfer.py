"""
Transfer Station: Product-to-Pallet Transfer
Uses Two-Axis Pick & Place (Digital/Boolean) + Positioning Left Bar 2.

P&P Positioning:
    PICK  = X=TRUE  (far end of stroke, over Belt 6 / product)
    PLACE = X=FALSE (X=0 / home, over Roller 1 / pallet)

Product detection: Sensor 9 (Diffuse) on Belt 6
Pallet control: Timed wait after emit (no pallet sensor, no stop blade)
"""

import time
import threading


class TransferStation:
    """
    Transfer Station controller.

    Flow: Belt ON → product arrives (Sensor 9) → Bar clamps →
          Emit pallet → timed travel → P&P picks (X=TRUE) →
          P&P places (X=FALSE) → Roller ON → pallet exits to warehouse.

    I/O Mapping:
        INPUTS:
            12 - Sensor 9 (product on belt 6)
            13 - Pos Left Bar 2 (Clamped)
            14 - Pos Left Bar 2 (Limit)
            15 - 2-Axis P&P (Moving X)
            16 - 2-Axis P&P (Moving Z)
            17 - 2-Axis P&P (Detected)

        OUTPUTS:
            27 - Belt Conveyor 6
            28 - Roller Conveyor 1
            29 - Emitter 3 (pallets)
            30 - Pos Left Bar 2 (Clamp)
            31 - Pos Left Bar 2 (Raise)
            32 - 2-Axis P&P Z    (True=DOWN, False=UP)
            33 - 2-Axis P&P X    (True=PICK/far end, False=PLACE/X=0)
            34 - 2-Axis P&P Grab (True=suction ON)
    """
    def __init__(self, modbus_client, station_name="Transfer"):
        self.modbus = modbus_client
        self.name = station_name
        self.state = 0
        
        # Dynamic Offsets for Line 2
        io_offset = 100 if "Line 2" in station_name else 0
        reg_offset = 10 if "Line 2" in station_name else 0
        
        # --- Input addresses ---
        self.SENSOR_PRODUCT = 12 + io_offset
        self.BAR_CLAMPED = 13 + io_offset
        self.BAR_LIMIT = 14 + io_offset
        self.PP2_MOVING_X = 15 + io_offset
        self.PP2_MOVING_Z = 16 + io_offset
        self.PP2_DETECTED = 17 + io_offset

        # --- Output addresses ---
        self.BELT_6 = 27 + io_offset
        self.ROLLER_1 = 28 + io_offset
        self.EMITTER_3 = 29 + io_offset
        self.BAR_CLAMP = 30 + io_offset
        self.BAR_RAISE = 31 + io_offset
        self.PP2_Z = 32 + io_offset
        self.PP2_X = 33 + io_offset
        self.PP2_GRAB = 34 + io_offset
        
        self.STACKER_REG = 0 + reg_offset

        self.running = False
        self.cycle_count = 0
        self.state_entry_time = time.time()

        # Timing
        self.GRAB_SETTLE_TIME = 0.5
        self.RELEASE_SETTLE_TIME = 0.5
        self.EMITTER_PULSE_TIME = 0.3
        self.PALLET_TRAVEL_TIME = 3.0     # seconds for pallet to reach place position
        self.PALLET_EXIT_TIME = 3.0       # seconds for pallet to exit to warehouse

    # ─── I/O helpers ─────────────────────────────────────────────

    def _read_input(self, address):
        result = self.modbus.read_inputs(address, 1)
        if result and len(result) > 0:
            return result[0]
        return False

    def _write_output(self, address, value):
        self.modbus.write_output(address, value)

    # ─── Sensor reads ────────────────────────────────────────────

    def product_present(self):
        """Sensor 9: product on Belt 6."""
        return self._read_input(self.SENSOR_PRODUCT)

    def bar_is_clamped(self):
        return self._read_input(self.BAR_CLAMPED)

    def bar_at_limit(self):
        return self._read_input(self.BAR_LIMIT)

    def pp2_is_moving_x(self):
        return self._read_input(self.PP2_MOVING_X)

    def pp2_is_moving_z(self):
        return self._read_input(self.PP2_MOVING_Z)

    def pp2_item_detected(self):
        """P&P built-in sensor — verifies grab."""
        return self._read_input(self.PP2_DETECTED)

    # ─── Actuator controls ───────────────────────────────────────

    def belt_6(self, on):
        self._write_output(self.BELT_6, on)

    def roller_1(self, on):
        self._write_output(self.ROLLER_1, on)

    def emitter_3(self, on):
        self._write_output(self.EMITTER_3, on)

    def bar_clamp(self, on):
        self._write_output(self.BAR_CLAMP, on)

    def bar_raise(self, on):
        self._write_output(self.BAR_RAISE, on)

    def pp2_move_z(self, down):
        """Z axis: True = DOWN, False = UP"""
        self._write_output(self.PP2_Z, down)

    def pp2_move_x(self, to_pick):
        """X axis: True = PICK (far end), False = PLACE (X=0/home)"""
        self._write_output(self.PP2_X, to_pick)

    def pp2_grab(self, on):
        """Suction: True = activate, False = release"""
        self._write_output(self.PP2_GRAB, on)

    # ─── Reset ───────────────────────────────────────────────────

    def reset_all(self):
        """Turn off all outputs for a clean start."""
        self.belt_6(False)
        self.roller_1(False)
        self.emitter_3(False)
        self.bar_clamp(False)
        self.pp2_move_z(False)   # UP
        self.pp2_move_x(False)   # PLACE position (X=0)
        self.pp2_grab(False)     # Release
        time.sleep(0.5)

    # ─── Wait helpers ────────────────────────────────────────────

    def _wait_for(self, condition_fn, description, timeout=30):
        start = time.time()
        while self.running:
            if condition_fn():
                return True
            if time.time() - start > timeout:
                print(f"  ⚠️ [{self.name}] TIMEOUT waiting for: {description}")
                return False
            time.sleep(0.05)
        return False

    def _wait_pp2_z_done(self):
        time.sleep(0.1)
        self._wait_for(lambda: not self.pp2_is_moving_z(), "P&P Z stop")

    def _wait_pp2_x_done(self):
        time.sleep(0.1)
        self._wait_for(lambda: not self.pp2_is_moving_x(), "P&P X stop")

    # ─── State helper ────────────────────────────────────────────

    def _set_state(self, new_state, description=""):
        self.state = new_state
        self.state_entry_time = time.time()
        label = f" ({description})" if description else ""
        print(f"  [{self.name}] → STATE {new_state}{label}")

    # ─── Main state machine ─────────────────────────────────────

    def run(self):
        self.running = True
        print(f"\n{'='*60}")
        print(f"  🔄 {self.name} Station Starting")
        print(f"{'='*60}")
        print(f"  P&P: PICK=X=TRUE (far end)  PLACE=X=FALSE (X=0)")
        print(f"  Sensor 9 = product on Belt 6")
        print(f"  Sequence: Product → Clamp → Release → Pallet → P&P → Roller")
        print(f"{'='*60}\n")

        self.reset_all()

        # Home P&P: PLACE position (X=0), UP
        print(f"  [{self.name}] Homing P&P to PLACE (X=0), UP...")
        self.pp2_move_x(False)   # PLACE position (X=0)
        self.pp2_move_z(False)   # UP
        time.sleep(1.0)
        self._wait_pp2_x_done()
        self._wait_pp2_z_done()
        print(f"  [{self.name}] P&P homed ✅")

        self._set_state(0, "WAIT_PRODUCT")

        while self.running:
            try:
                if self.state == 0:
                    # ── STATE 0: BELT ON, WAIT FOR PRODUCT ──
                    self.bar_clamp(False)

                    self.belt_6(True)
                    print(f"  [{self.name}] Belt ON — waiting for product (Sensor 9)...")

                    self._wait_for(self.product_present, "Sensor 9 = TRUE (product)")
                    print(f"  [{self.name}] 📦 Product detected! ✅")

                    self._set_state(1, "CLAMP")

                elif self.state == 1:
                    # ── STATE 1: STOP BELT, CLAMP PRODUCT (align) ──
                    self.belt_6(False)
                    time.sleep(0.2)

                    self.bar_clamp(True)
                    print(f"  [{self.name}] Clamping product...")
                    self._wait_for(self.bar_is_clamped, "Bar clamped")
                    print(f"  [{self.name}] Product aligned ✅")
                    time.sleep(0.3)

                    self._set_state(2, "RELEASE_CLAMP")

                elif self.state == 2:
                    # ── STATE 2: RELEASE CLAMP ──
                    self.bar_clamp(False)
                    self._wait_for(lambda: not self.bar_is_clamped(), "Bar unclamped")
                    print(f"  [{self.name}] Clamp released ✅")
                    time.sleep(0.2)

                    self._set_state(3, "EMIT_PALLET")

                elif self.state == 3:
                    # ── STATE 3: EMIT PALLET (only when sensor input 12 confirms product) ──
                    if not self.product_present():
                        print(f"  [{self.name}] ⏳ Waiting for sensor (input 12) before emitting...")
                        self._wait_for(self.product_present, "Sensor 9 (input 12) = TRUE")
                    print(f"  [{self.name}] Sensor confirmed — emitting pallet...")
                    self.emitter_3(True)
                    time.sleep(self.EMITTER_PULSE_TIME)
                    self.emitter_3(False)

                    # Roller ON → pallet travels to place position
                    self.roller_1(True)
                    print(f"  [{self.name}] Roller ON — pallet traveling ({self.PALLET_TRAVEL_TIME}s)...")
                    time.sleep(self.PALLET_TRAVEL_TIME)
                    self.roller_1(False)
                    print(f"  [{self.name}] Pallet in position ✅")

                    self._set_state(4, "PP_PICK")

                elif self.state == 4:
                    # ── STATE 4: P&P TO PICK (FAR END), THEN DOWN ──
                    print(f"  [{self.name}] P&P → PICK (X=TRUE)...")
                    self.pp2_move_x(True)    # PICK = far end
                    self._wait_pp2_x_done()
                    print(f"  [{self.name}] P&P at PICK X ✅")
                    time.sleep(1.0)

                    self.pp2_move_z(True)    # DOWN to product
                    self._wait_pp2_z_done()
                    print(f"  [{self.name}] P&P down at product ✅")
                    time.sleep(1.0)

                    self._set_state(5, "GRAB")

                elif self.state == 5:
                    # ── STATE 5: GRAB PRODUCT ──
                    self.pp2_grab(True)
                    time.sleep(1.0)

                    if self.pp2_item_detected():
                        print(f"  [{self.name}] Product grabbed ✅")
                    else:
                        print(f"  [{self.name}] ⚠️ Grab but Detected=FALSE — continuing")

                    self._set_state(6, "LIFT")

                elif self.state == 6:
                    # ── STATE 6: LIFT P&P WITH PRODUCT ──
                    self.pp2_move_z(False)   # UP with product
                    self._wait_pp2_z_done()
                    print(f"  [{self.name}] Product lifted ✅")
                    time.sleep(1.0)

                    self._set_state(7, "MOVE_TO_PLACE")

                elif self.state == 7:
                    # ── STATE 7: MOVE TO PLACE (X=0, over pallet) ──
                    print(f"  [{self.name}] P&P → PLACE (X=FALSE)...")
                    self.pp2_move_x(False)   # PLACE = X=0 (over pallet)
                    self._wait_pp2_x_done()
                    print(f"  [{self.name}] P&P over pallet ✅")
                    time.sleep(1.0)

                    self._set_state(8, "PLACE_DOWN")

                elif self.state == 8:
                    # ── STATE 8: LOWER ONTO PALLET ──
                    self.pp2_move_z(True)    # DOWN onto pallet
                    self._wait_pp2_z_done()
                    print(f"  [{self.name}] P&P down on pallet ✅")
                    time.sleep(1.0)

                    self._set_state(9, "RELEASE_AND_LIFT")

                elif self.state == 9:
                    # ── STATE 9: RELEASE PRODUCT AND LIFT ──
                    self.pp2_grab(False)     # Release suction
                    time.sleep(self.RELEASE_SETTLE_TIME)
                    print(f"  [{self.name}] Product on pallet ✅")

                    self.pp2_move_z(False)   # UP immediately
                    self._wait_pp2_z_done()
                    print(f"  [{self.name}] P&P raised ✅")

                    self._set_state(11, "ROLLER_EXIT")

                elif self.state == 11:
                    # ── STATE 11: ROLLER ON → SEND PALLET TO WAREHOUSE ──
                    self.roller_1(True)
                    print(f"  [{self.name}] Pallet → warehouse ({self.PALLET_EXIT_TIME}s)...")
                    time.sleep(self.PALLET_EXIT_TIME)
                    self.roller_1(False)

                    self.cycle_count += 1
                    print(f"\n  [{self.name}] ✅ CYCLE {self.cycle_count} COMPLETE")

                    # Wait for stacker crane to return (holding register 0 == 55)
                    print(f"  [{self.name}] ⏳ Waiting for stacker to return (reg {self.STACKER_REG} == 55)...")
                    while self.running:
                        try:
                            reg_val = self.modbus.read_holding_register(self.STACKER_REG)
                            if reg_val == 55:
                                break
                        except Exception:
                            pass
                        time.sleep(0.2)
                    print(f"  [{self.name}] ✅ Stacker returned!\n")

                    self._set_state(0, "WAIT_PRODUCT")

                time.sleep(0.05)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"  [{self.name}] ❌ ERROR state {self.state}: {e}")
                time.sleep(1)

        self.stop()

    def stop(self):
        self.running = False
        print(f"  [{self.name}] Shutting down...")
        self.reset_all()
        print(f"  [{self.name}] Stopped ✅")


class SyncedTransferStation(TransferStation):
    """
    Transfer with upstream synchronization.
    Waits for product FIRST, then emits pallet, then P&P transfers.
    Signals ready when pallet is in position and waiting for product (STATE 1).
    """

    def __init__(self, modbus_client, upstream_ready_event=None, station_name="Transfer-Sync"):
        super().__init__(modbus_client, station_name)
        self.upstream_ready = upstream_ready_event or threading.Event()

    def _signal_ready(self):
        self.upstream_ready.set()
        print(f"  [{self.name}] 📢 Signaled READY for next product")

    def run(self):
        self.running = True
        print(f"\n{'='*60}")
        print(f"  🔄 {self.name} Station Starting (SYNCED)")
        print(f"{'='*60}")
        print(f"  P&P: PICK=X=TRUE (far end)  PLACE=X=FALSE (X=0)")
        print(f"  Sensor 9 = product on Belt 6")
        print(f"  Sequence: Product → Clamp → Release → Pallet → P&P → Roller")
        print(f"{'='*60}\n")

        self.reset_all()

        # Home P&P
        print(f"  [{self.name}] Homing P&P to PLACE (X=0), UP...")
        self.pp2_move_x(False)
        self.pp2_move_z(False)
        time.sleep(1.0)
        self._wait_pp2_x_done()
        self._wait_pp2_z_done()
        print(f"  [{self.name}] P&P homed ✅")

        self._set_state(0, "WAIT_PRODUCT")

        while self.running:
            try:
                if self.state == 0:
                    # ── STATE 0: BELT ON, SYNC, WAIT FOR PRODUCT ──
                    self.bar_clamp(False)

                    self.belt_6(True)

                    # Wait for sensor clear before signaling
                    self._wait_for(lambda: not self.product_present(), "Sensor 9 clear")
                    self._signal_ready()

                    print(f"  [{self.name}] Waiting for product (Sensor 9)...")
                    self._wait_for(self.product_present, "Sensor 9 = TRUE")
                    print(f"  [{self.name}] 📦 Product detected! ✅")

                    self._set_state(1, "CLAMP")

                elif self.state == 1:
                    # ── STATE 1: STOP BELT, CLAMP (align) ──
                    self.belt_6(False)
                    time.sleep(0.2)

                    self.bar_clamp(True)
                    print(f"  [{self.name}] Clamping...")
                    self._wait_for(self.bar_is_clamped, "Bar clamped")
                    print(f"  [{self.name}] Aligned ✅")
                    time.sleep(0.3)

                    self._set_state(2, "RELEASE_CLAMP")

                elif self.state == 2:
                    # ── STATE 2: RELEASE CLAMP ──
                    self.bar_clamp(False)
                    self._wait_for(lambda: not self.bar_is_clamped(), "Bar unclamped")
                    print(f"  [{self.name}] Clamp released ✅")
                    time.sleep(0.2)

                    self._set_state(3, "EMIT_PALLET")

                elif self.state == 3:
                    # ── STATE 3: EMIT PALLET (only when sensor input 12 confirms product) ──
                    if not self.product_present():
                        print(f"  [{self.name}] ⏳ Waiting for sensor (input 12) before emitting...")
                        self._wait_for(self.product_present, "Sensor 9 (input 12) = TRUE")
                    print(f"  [{self.name}] Sensor confirmed — emitting pallet...")
                    self.emitter_3(True)
                    time.sleep(self.EMITTER_PULSE_TIME)
                    self.emitter_3(False)

                    self.roller_1(True)
                    print(f"  [{self.name}] Pallet traveling ({self.PALLET_TRAVEL_TIME}s)...")
                    time.sleep(self.PALLET_TRAVEL_TIME)
                    self.roller_1(False)
                    print(f"  [{self.name}] Pallet in position ✅")

                    self._set_state(4, "PP_PICK")

                elif self.state == 4:
                    # ── STATE 4: P&P TO PICK, DOWN ──
                    print(f"  [{self.name}] P&P → PICK (X=TRUE)...")
                    self.pp2_move_x(True)
                    self._wait_pp2_x_done()
                    print(f"  [{self.name}] P&P at PICK X ✅")
                    time.sleep(1.0)

                    self.pp2_move_z(True)
                    self._wait_pp2_z_done()
                    print(f"  [{self.name}] P&P down at product ✅")
                    time.sleep(1.0)

                    self._set_state(5, "GRAB")

                elif self.state == 5:
                    # ── STATE 5: GRAB ──
                    self.pp2_grab(True)
                    time.sleep(1.0)

                    if self.pp2_item_detected():
                        print(f"  [{self.name}] Grabbed ✅")
                    else:
                        print(f"  [{self.name}] ⚠️ Detected=FALSE — continuing")

                    self._set_state(6, "LIFT")

                elif self.state == 6:
                    # ── STATE 6: LIFT P&P WITH PRODUCT ──
                    self.pp2_move_z(False)
                    self._wait_pp2_z_done()
                    print(f"  [{self.name}] Lifted ✅")
                    time.sleep(1.0)

                    self._set_state(7, "MOVE_TO_PLACE")

                elif self.state == 7:
                    # ── STATE 7: MOVE TO PLACE ──
                    print(f"  [{self.name}] P&P → PLACE (X=FALSE)...")
                    self.pp2_move_x(False)
                    self._wait_pp2_x_done()
                    print(f"  [{self.name}] Over pallet ✅")
                    time.sleep(1.0)

                    self._set_state(8, "PLACE_DOWN")

                elif self.state == 8:
                    # ── STATE 8: LOWER ONTO PALLET ──
                    self.pp2_move_z(True)
                    self._wait_pp2_z_done()
                    print(f"  [{self.name}] Down on pallet ✅")
                    time.sleep(1.0)

                    self._set_state(9, "RELEASE_AND_LIFT")

                elif self.state == 9:
                    # ── STATE 9: RELEASE AND LIFT P&P ──
                    self.pp2_grab(False)
                    time.sleep(self.RELEASE_SETTLE_TIME)
                    print(f"  [{self.name}] Released ✅")

                    self.pp2_move_z(False)
                    self._wait_pp2_z_done()
                    print(f"  [{self.name}] P&P up ✅")

                    self._set_state(11, "ROLLER_EXIT")

                elif self.state == 11:
                    # ── STATE 11: ROLLER ON → EXIT PALLET ──
                    self.roller_1(True)
                    print(f"  [{self.name}] Pallet → warehouse ({self.PALLET_EXIT_TIME}s)...")
                    time.sleep(self.PALLET_EXIT_TIME)
                    self.roller_1(False)

                    self.cycle_count += 1
                    print(f"\n  [{self.name}] ✅ CYCLE {self.cycle_count} COMPLETE")

                    # Wait for stacker crane to return (holding register {self.STACKER_REG} == 55)
                    print(f"  [{self.name}] ⏳ Waiting for stacker to return (reg {self.STACKER_REG} == 55)...")
                    while self.running:
                        try:
                            reg_val = self.modbus.read_holding_register(self.STACKER_REG)
                            if reg_val == 55:
                                break
                        except Exception:
                            pass
                        time.sleep(0.2)
                    print(f"  [{self.name}] ✅ Stacker returned!\n")

                    self._set_state(0, "WAIT_PRODUCT")

                time.sleep(0.05)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"  [{self.name}] ❌ ERROR state {self.state}: {e}")
                time.sleep(1)

        self.stop()