"""
Station 7: Sorting & Output
Routes products based on QC result from Station 6.

Pivot Arm Sorter has 3 controls:
  Turn:   FALSE=straight (good), TRUE=divert 45° (reject)
  Belt+:  TRUE=sorter belt runs forward (pushes product)
  Belt-:  TRUE=sorter belt runs backward (unused)

Removers auto-delete products at end of each path.
"""

import time
import json
import threading


class Station7:
    """Sorting & Output station — routes products by QC result"""

    # === Output Addresses (Coils) ===
    BELT_4B = 20                # Transition belt Stn6→Stn7 (always ON)
    BELT_5 = 21                 # Main belt before sorter
    SORTER_TURN = 22            # Pivot Arm: FALSE=straight, TRUE=turn
    SORTER_BELT_FWD = 23        # Pivot Arm belt forward (+)
    SORTER_BELT_REV = 24        # Pivot Arm belt reverse (-) (unused)
    LIGHT_GOOD = 25             # Green light (good bin)
    LIGHT_REJECT = 26           # Red light (reject bin)

    # === Input Addresses (Discrete Inputs) ===
    SENSOR_7 = 11               # Diffuse sensor — product detection

    # === Timing ===
    SETTLE_TIME = 0.3           # Settle after detection
    ARM_MOVE_TIME = 0.5         # Time for sorter arm to rotate
    ARM_RETURN_TIME = 0.5       # Time for arm to return to straight
    EXIT_WAIT = 1.0             # Wait after sensor clears

    def __init__(self, modbus_client, station6_ref=None, mqtt_client=None):
        self.modbus = modbus_client
        self.station6 = station6_ref
        self.mqtt = mqtt_client

        # State
        self.state = 0
        self.running = False
        self.cycle_start_time = None

        # Counters
        self.product_count = 0
        self.good_count = 0
        self.reject_count = 0
        self.last_sort_result = None

        # Fault injection
        self.active_faults = {}
        self.fault_counters = {}

    # ──────────────────────────────────────
    # Output Controls
    # ──────────────────────────────────────
    def belt(self, on):
        self.modbus.write_output(self.BELT_5, on)

    def transition_belt(self, on):
        self.modbus.write_output(self.BELT_4B, on)

    def sorter_turn(self, turn):
        """FALSE = straight (good path), TRUE = turn 45° (reject path)"""
        self.modbus.write_output(self.SORTER_TURN, turn)

    def sorter_belt(self, on):
        """Sorter belt forward — pushes product through/off the arm"""
        self.modbus.write_output(self.SORTER_BELT_FWD, on)

    def light_good(self, on):
        self.modbus.write_output(self.LIGHT_GOOD, on)

    def light_reject(self, on):
        self.modbus.write_output(self.LIGHT_REJECT, on)

    def lights_off(self):
        self.light_good(False)
        self.light_reject(False)

    # ──────────────────────────────────────
    # Input Reading
    # ──────────────────────────────────────
    def read_sensors(self):
        values = self.modbus.read_inputs(self.SENSOR_7, 1)
        if values is None:
            return {"sensor_7": False}
        return {"sensor_7": values[0]}

    # ──────────────────────────────────────
    # Sorting Logic
    # ──────────────────────────────────────
    def get_qc_result(self):
        """Read QC result from Station 6"""
        if self.station6 is not None and self.station6.last_qc_result is not None:
            return self.station6.last_qc_result
        return "PASS"

    # ──────────────────────────────────────
    # MQTT
    # ──────────────────────────────────────
    def publish_status(self):
        if not self.mqtt:
            return
        try:
            payload = json.dumps({
                "station": 7,
                "name": "Sorting_Output",
                "state": self.state,
                "product_count": self.product_count,
                "good_count": self.good_count,
                "reject_count": self.reject_count,
                "last_sort_result": self.last_sort_result,
                "running": self.running
            })
            self.mqtt.publish("factory/station7/status", payload)
        except Exception:
            pass

    # ──────────────────────────────────────
    # State Machine
    # ──────────────────────────────────────
    def main(self):
        self.running = True
        self.transition_belt(True)
        print("[STN7] 📦 Sorting & Output Station starting...")

        while self.running:
            sensors = self.read_sensors()

            # ── STATE 0: READY ──
            if self.state == 0:
                self.belt(True)
                self.sorter_turn(False)         # Straight (default)
                self.sorter_belt(True)          # Sorter belt running
                self.lights_off()

                # Wait for sensor clear
                if sensors["sensor_7"]:
                    time.sleep(0.05)
                    continue

                print("[STN7] ⏳ Waiting for product...")
                while self.running:
                    sensors = self.read_sensors()
                    if sensors["sensor_7"]:
                        break
                    time.sleep(0.05)

                if not self.running:
                    break

                self.cycle_start_time = time.time()
                print("[STN7] 📦 Product detected!")
                self.state = 1

            # ── STATE 1: SORTING ──
            elif self.state == 1:
                time.sleep(self.SETTLE_TIME)

                qc = self.get_qc_result()
                self.product_count += 1

                if qc == "PASS":
                    self.sorter_turn(False)      # Straight → good bin
                    self.last_sort_result = "GOOD"
                    self.good_count += 1
                    self.lights_off()
                    time.sleep(0.1)
                    self.light_good(True)
                    print(f"[STN7] ✅ Product #{self.product_count}: GOOD → straight path")
                else:
                    self.sorter_turn(True)       # Turn → reject bin
                    self.last_sort_result = "REJECT"
                    self.reject_count += 1
                    self.lights_off()
                    time.sleep(0.1)
                    self.light_reject(True)
                    print(f"[STN7] ❌ Product #{self.product_count}: REJECT → divert path")

                # Wait for arm to move into position
                time.sleep(self.ARM_MOVE_TIME)
                self.state = 2

            # ── STATE 2: PASSING ──
            elif self.state == 2:
                # Belt and sorter belt push product through
                self.belt(True)
                self.sorter_belt(True)

                # Wait for sensor to clear (product passed)
                while self.running:
                    sensors = self.read_sensors()
                    if not sensors["sensor_7"]:
                        break
                    time.sleep(0.05)

                if not self.running:
                    break

                print("[STN7] 🔄 Product passed through sorter...")
                self.state = 3

            # ── STATE 3: COMPLETE ──
            elif self.state == 3:
                time.sleep(self.EXIT_WAIT)

                # Return arm to straight position
                self.sorter_turn(False)
                time.sleep(self.ARM_RETURN_TIME)

                self.lights_off()

                ct = time.time() - self.cycle_start_time if self.cycle_start_time else 0
                print(f"[STN7] ✅ Cycle done | {ct:.1f}s | "
                      f"Good:{self.good_count} Reject:{self.reject_count} "
                      f"Total:{self.product_count}")

                self.publish_status()
                self.state = 0

            time.sleep(0.05)

        # Shutdown
        self.belt(False)
        self.sorter_turn(False)
        self.sorter_belt(False)
        self.lights_off()
        print("[STN7] 🛑 Sorting & Output stopped.")

    def stop(self):
        self.running = False


# ═══════════════════════════════════════════════════════
# Synced version (for multi-station line)
# ═══════════════════════════════════════════════════════

class SyncedStation7(Station7):
    """Station 7 with upstream synchronization"""

    def __init__(self, modbus_client, station6_ref=None, mqtt_client=None,
                 upstream_ready_event=None):
        super().__init__(modbus_client, station6_ref, mqtt_client)
        self.upstream_ready = upstream_ready_event or threading.Event()

    def _signal_ready(self):
        """Tell upstream (Station 6) we're ready"""
        self.upstream_ready.set()
        print("[STN7] 🟢 Ready — signaled upstream")

    def main(self):
        self.running = True
        self.transition_belt(True)
        print("[STN7] 📦 Sorting & Output starting (synced)...")

        while self.running:
            sensors = self.read_sensors()

            # ── STATE 0: READY ──
            if self.state == 0:
                self.belt(True)
                self.sorter_turn(False)
                self.sorter_belt(True)
                self.lights_off()

                if sensors["sensor_7"]:
                    time.sleep(0.05)
                    continue

                # Signal upstream BEFORE waiting
                self._signal_ready()

                print("[STN7] ⏳ Waiting for product...")
                while self.running:
                    sensors = self.read_sensors()
                    if sensors["sensor_7"]:
                        break
                    time.sleep(0.05)

                if not self.running:
                    break

                self.cycle_start_time = time.time()
                print("[STN7] 📦 Product detected!")
                self.state = 1

            # ── STATE 1: SORTING ──
            elif self.state == 1:
                time.sleep(self.SETTLE_TIME)

                qc = self.get_qc_result()
                self.product_count += 1

                if qc == "PASS":
                    self.sorter_turn(False)
                    self.last_sort_result = "GOOD"
                    self.good_count += 1
                    self.lights_off()
                    time.sleep(0.1)
                    self.light_good(True)
                    print(f"[STN7] ✅ Product #{self.product_count}: GOOD → straight")
                else:
                    self.sorter_turn(True)
                    self.last_sort_result = "REJECT"
                    self.reject_count += 1
                    self.lights_off()
                    time.sleep(0.1)
                    self.light_reject(True)
                    print(f"[STN7] ❌ Product #{self.product_count}: REJECT → divert")

                time.sleep(self.ARM_MOVE_TIME)
                self.state = 2

            # ── STATE 2: PASSING ──
            elif self.state == 2:
                self.belt(True)
                self.sorter_belt(True)

                while self.running:
                    sensors = self.read_sensors()
                    if not sensors["sensor_7"]:
                        break
                    time.sleep(0.05)

                if not self.running:
                    break

                print("[STN7] 🔄 Product passed through sorter sensor...")
                
                # Check if we should wait for a divert/reject path
                # So the arm doesn't return to straight too early and hit the product
                clear_time = getattr(self, "PRODUCT_CLEAR_TIME", 0)
                if clear_time > 0 and getattr(self, "last_sort_result", "") == "REJECT":
                    print(f"[STN7] ⏳ Waiting {clear_time}s for REJECT product to clear the arm...")
                    time.sleep(clear_time)

                self.state = 3

            # ── STATE 3: COMPLETE ──
            elif self.state == 3:
                time.sleep(self.EXIT_WAIT)

                self.sorter_turn(False)
                time.sleep(self.ARM_RETURN_TIME)

                self.lights_off()

                if getattr(self, "last_sort_result", "") == "GOOD":
                    print("[STN7] ⏳ Waiting for product to reach Transfer station (input 12)...")
                    start_wait = time.time()
                    while self.running and (time.time() - start_wait) < 15.0:
                        res = self.modbus.read_inputs(12, 1)
                        if res and res[0]:
                            break
                        time.sleep(0.1)

                    if self.running:
                        print("[STN7] ⏳ Product at Transfer, waiting for Transfer to pick it (input 12 clears)...")
                        while self.running:
                            res = self.modbus.read_inputs(12, 1)
                            if res and not res[0]:
                                break
                            time.sleep(0.1)
                        print("[STN7] ✅ Transfer done!")

                ct = time.time() - self.cycle_start_time if getattr(self, "cycle_start_time", None) else 0
                print(f"[STN7] ✅ Cycle done | {ct:.1f}s | "
                      f"Good:{self.good_count} Reject:{self.reject_count} "
                      f"Total:{self.product_count}")

                self.publish_status()
                self.state = 0

            time.sleep(0.05)

        self.belt(False)
        self.sorter_turn(False)
        self.sorter_belt(False)
        self.lights_off()
        print("[STN7] 🛑 Sorting & Output stopped.")