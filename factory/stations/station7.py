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

    def __init__(self, modbus_client, station6_ref=None, mqtt_client=None, config=None):
        self.modbus = modbus_client
        self.station6 = station6_ref
        self.mqtt = mqtt_client

        if config is None:
            self.BELT_4B = 20
            self.BELT_5 = 21
            self.SORTER_TURN = 22
            self.SORTER_BELT_FWD = 23
            self.SORTER_BELT_REV = 24
            self.LIGHT_GOOD = 25
            self.LIGHT_REJECT = 26
            self.SENSOR_7 = 11
            self.STATION_ID = "station_7"
            self.STATION_NAME = "Sorting_Output"
        else:
            io = config.get("io", {})
            self.STATION_ID = config.get("id", "station_7")
            self.STATION_NAME = config.get("name", "Sorting_Output")
            
            offset = 100 if "Line 2" in self.STATION_NAME else 0
            
            # Use offset logic for hardcoded addresses, or grab from config if they exist
            self.BELT_4B = io.get("belt_4b", {}).get("address", 20 + offset)
            self.BELT_5 = io.get("belt", {}).get("address", 21 + offset) # Wait, config had 30 before? Use what's right.
            self.SORTER_TURN = io.get("sorter", {}).get("address", 22 + offset)
            self.SORTER_BELT_FWD = io.get("sorter_belt_fwd", {}).get("address", 23 + offset)
            self.SORTER_BELT_REV = io.get("sorter_belt_rev", {}).get("address", 24 + offset)
            self.LIGHT_GOOD = io.get("light_green", {}).get("address", 25 + offset)
            self.LIGHT_REJECT = io.get("light_red", {}).get("address", 26 + offset)
            self.SENSOR_7 = io.get("sensor_entry", {}).get("address", 11 + offset)

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
            self.mqtt.publish(f"factory/{self.STATION_ID}/status", payload)
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
                while self.running and self.state == 2:
                    sensors = self.read_sensors()
                    if not sensors["sensor_7"]:
                        break
                    time.sleep(0.05)

                if not self.running or self.state != 2:
                    continue

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

    # ──────────────────────────────────────
    # Fault Injection / Clearing
    # ──────────────────────────────────────
    def inject_fault(self, fault_type, severity=3):
        """Inject a fault into this station.

        Supported fault types: overheat, power, belt_slip, sensor_drift, sorter_jam, misroute
        Severity: 1-5
        """
        severity = max(1, min(5, int(severity)))
        self.active_faults[fault_type] = severity
        self.fault_counters[fault_type] = self.fault_counters.get(fault_type, 0) + 1
        print(f"[STN7] ⚡ FAULT INJECTED: {fault_type} severity={severity}")

    def clear_fault(self, fault_type="all"):
        """Clear active fault(s) and reset station state if stuck.

        Args:
            fault_type: specific fault name or "all" to clear everything
        """
        if fault_type == "all":
            cleared = list(self.active_faults.keys())
            self.active_faults.clear()
            print(f"[STN7] ✅ ALL faults cleared: {cleared}")
        elif fault_type in self.active_faults:
            del self.active_faults[fault_type]
            print(f"[STN7] ✅ Fault cleared: {fault_type}")
        else:
            print(f"[STN7] ⚠️ No active fault '{fault_type}' to clear")

        # If station is stuck (state != 0 and not actively processing),
        # reset state machine to allow recovery
        if self.state != 0 and not self.active_faults:
            old_state = self.state
            self.state = 0
            print(f"[STN7] 🔄 State reset from {old_state} → 0 (recovery)")

    def get_status(self):
        """Return current station status for telemetry and fault manager."""
        rate = (self.good_count / self.product_count * 100) if self.product_count > 0 else 100.0
        return {
            "station_id": getattr(self, "STATION_ID", "station_7"),
            "state": self.state,
            "running": self.running,
            "product_count": self.product_count,
            "good_count": self.good_count,
            "reject_count": self.reject_count,
            "good_rate": round(rate, 1),
            "last_sort_result": self.last_sort_result,
            "faults": {
                "has_fault": bool(self.active_faults),
                "active": list(self.active_faults.keys()),
                "details": dict(self.active_faults),
            },
        }

    def apply_parameters(self, params: dict):
        """Apply runtime parameter changes from the AI agent.

        Supported keys:
          clear_fault (str|bool): fault type to clear, or True for "all"
          fan_speed (float): cooling fan percentage 0-100
          speed_factor (float): sorting speed multiplier 0.1-2.0
          target_belt_speed (float): belt speed target 10-100
        """
        print(f"[STN7] 🔧 apply_parameters: {params}")

        # Clear faults
        cf = params.get("clear_fault")
        if cf:
            fault_type = cf if isinstance(cf, str) and cf not in ("True", "true") else "all"
            self.clear_fault(fault_type)

        # Fan speed
        if "fan_speed" in params:
            fan = max(0, min(100, float(params["fan_speed"])))
            print(f"[STN7]   Fan speed → {fan}%")

        # Speed factor — affects arm timing
        if "speed_factor" in params:
            sf = max(0.1, min(2.0, float(params["speed_factor"])))
            self.ARM_MOVE_TIME = 0.5 / sf
            self.ARM_RETURN_TIME = 0.5 / sf
            print(f"[STN7]   Speed factor → {sf} (arm_time={self.ARM_MOVE_TIME:.2f}s)")

        # Belt speed target
        if "target_belt_speed" in params:
            tbs = max(10, min(100, float(params["target_belt_speed"])))
            print(f"[STN7]   Belt speed target → {tbs}%")


# ═══════════════════════════════════════════════════════
# Synced version (for multi-station line)
# ═══════════════════════════════════════════════════════

class SyncedStation7(Station7):
    """Station 7 with upstream synchronization"""

    def __init__(self, modbus_client, station6_ref=None, mqtt_client=None,
                 upstream_ready_event=None, config=None,
                 transfer_sensor_addr=None):
        super().__init__(modbus_client, station6_ref, mqtt_client, config)
        self.upstream_ready = upstream_ready_event or threading.Event()

        # Transfer sensor address — auto-detect from config offset or default to 12
        if transfer_sensor_addr is not None:
            self.TRANSFER_SENSOR_ADDR = transfer_sensor_addr
        else:
            io_offset = 100 if (config and "Line 2" in config.get("name", "")) else 0
            self.TRANSFER_SENSOR_ADDR = 12 + io_offset

    def _signal_ready(self):
        """Tell upstream (Station 6) we're ready"""
        self.upstream_ready.set()
        print("[STN7] 🟢 Ready — signaled upstream")

    def run(self):
        """Alias for main() to be compatible with thread targets in master script"""
        self.main()

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
                while self.running and self.state == 0:
                    sensors = self.read_sensors()
                    if sensors["sensor_7"]:
                        break
                    time.sleep(0.05)

                if not self.running or self.state != 0:
                    continue

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

                while self.running and self.state == 2:
                    sensors = self.read_sensors()
                    if not sensors["sensor_7"]:
                        break
                    time.sleep(0.05)

                if not self.running or self.state != 2:
                    continue

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
                    xfer_addr = self.TRANSFER_SENSOR_ADDR
                    print(f"[STN7] ⏳ Waiting for product to reach Transfer station (input {xfer_addr})...")
                    start_wait = time.time()
                    while self.running and (time.time() - start_wait) < 15.0:
                        res = self.modbus.read_inputs(xfer_addr, 1)
                        if res and res[0]:
                            break
                        time.sleep(0.1)

                    if self.running:
                        print(f"[STN7] ⏳ Product at Transfer, waiting for Transfer to pick it (input {xfer_addr} clears)...")
                        while self.running:
                            res = self.modbus.read_inputs(xfer_addr, 1)
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