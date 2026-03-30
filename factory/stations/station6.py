"""
Station 6: Quality Control
Uses Vision Sensor (All Numerical mode) to inspect products.

Vision Sensor values (All Numerical):
  0 = Nothing
  1 = Blue Raw Material
  2 = Blue Product Lid
  3 = Blue Product Base
  4 = Green Raw Material
  5 = Green Product Lid    ← assembled product (lid visible on top)
  6 = Green Product Base
  7 = Metal Raw Material
  8 = Metal Product Lid
  9 = Metal Product Base

QC Logic:
  Vision == 5 (Green Lid on top) → PASS (properly assembled)
  Vision == 3 (Blue Base only)   → FAIL (lid missing)
  Vision == 0 (nothing)          → FAIL (no product)
  Anything else                  → FAIL (wrong product type)
"""

import time
import json
import threading


VISION_ITEMS = {
    0: "Nothing",
    1: "Blue Raw Material",
    2: "Blue Product Lid",
    3: "Blue Product Base",
    4: "Green Raw Material",
    5: "Green Product Lid",
    6: "Green Product Base",
    7: "Metal Raw Material",
    8: "Metal Product Lid",
    9: "Metal Product Base",
}


class Station6:
    """Quality Control station with Vision Sensor"""

    # === Output Addresses (Coils) ===
    BELT_3B = 14            # Transition belt Stn3→Stn6 (always ON)
    BELT_4 = 15             # Main QC belt
    STOP_BLADE_3 = 16       # Stop blade
    LIGHT_GREEN = 17        # Stack light — PASS
    LIGHT_YELLOW = 18       # Stack light — Inspecting
    LIGHT_RED = 19          # Stack light — FAIL

    # === Input Addresses (Discrete Inputs) ===
    SENSOR_6 = 10           # Diffuse sensor — product detection

    # === Register Addresses (Input Registers) ===
    VISION_SENSOR = 0       # Vision Sensor output register

    # === Timing ===
    INSPECT_TIME = 3.0      # Inspection duration
    RESULT_DISPLAY = 1.0    # How long pass/fail light stays
    SETTLE_TIME = 0.3       # Settle after belt stops
    RELEASE_DELAY = 0.5     # Delay after blade opens

    # === QC Parameters ===
    # 5 = Green Product Lid visible on top = properly assembled
    # Set to None to run in discovery mode (logs values without judging)
    EXPECTED_VALUE = 5

    def __init__(self, modbus_client, mqtt_client=None):
        self.modbus = modbus_client
        self.mqtt = mqtt_client

        # State
        self.state = 0
        self.running = False
        self.cycle_start_time = None

        # Discovery mode — if EXPECTED_VALUE is None, log only
        self.discovery_mode = (self.EXPECTED_VALUE is None)

        # QC tracking
        self.product_count = 0
        self.pass_count = 0
        self.fail_count = 0
        self.last_qc_result = None      # "PASS" or "FAIL"
        self.last_vision_value = None   # Raw vision sensor reading (0-9)
        self.last_fail_reason = None    # Reason string for failures

        # Fault injection
        self.active_faults = {}
        self.fault_counters = {}

    # ──────────────────────────────────────
    # Output Controls
    # ──────────────────────────────────────
    def belt(self, on):
        self.modbus.write_output(self.BELT_4, on)

    def blade(self, up):
        self.modbus.write_output(self.STOP_BLADE_3, up)

    def transition_belt(self, on):
        self.modbus.write_output(self.BELT_3B, on)

    def light_green(self, on):
        self.modbus.write_output(self.LIGHT_GREEN, on)

    def light_yellow(self, on):
        self.modbus.write_output(self.LIGHT_YELLOW, on)

    def light_red(self, on):
        self.modbus.write_output(self.LIGHT_RED, on)

    def lights_off(self):
        self.light_green(False)
        self.light_yellow(False)
        self.light_red(False)

    # ──────────────────────────────────────
    # Input Reading
    # ──────────────────────────────────────
    def read_sensors(self):
        values = self.modbus.read_inputs(self.SENSOR_6, 1)
        if values is None:
            return {"sensor_6": False}
        return {"sensor_6": values[0]}

    def read_vision_sensor(self):
        """Read vision sensor register — returns 0-9 or None"""
        value = self.modbus.read_register(self.VISION_SENSOR)
        return value

    # ──────────────────────────────────────
    # QC Logic
    # ──────────────────────────────────────
    def perform_inspection(self):
        """
        Read Vision Sensor and determine PASS/FAIL.

        The sensor looks DOWN from above. On an assembled product,
        the Green Product Lid is on top → value = 5.
        If the lid is missing (assembly failed), only the
        Blue Product Base is visible → value = 3.
        """
        self.product_count += 1

        self.last_vision_value = self.read_vision_sensor()
        item_name = VISION_ITEMS.get(self.last_vision_value, f"Unknown({self.last_vision_value})")
        print(f"[STN6] 📷 Vision Sensor: {self.last_vision_value} = {item_name}")

        # ── DISCOVERY MODE ──
        if self.discovery_mode:
            print(f"[STN6] 🔬 DISCOVERY MODE — Record this value!")
            print(f"[STN6] 💡 If this is a good product, set EXPECTED_VALUE = {self.last_vision_value}")
            self.last_qc_result = "PASS"
            self.last_fail_reason = None
            self.pass_count += 1
            return self.last_qc_result

        # ── REAL QC MODE ──
        if self.last_vision_value is None:
            self.last_qc_result = "FAIL"
            self.last_fail_reason = "sensor_error"
            self.fail_count += 1

        elif self.last_vision_value == self.EXPECTED_VALUE:
            # Green Lid on top = properly assembled
            self.last_qc_result = "PASS"
            self.last_fail_reason = None
            self.pass_count += 1

        elif self.last_vision_value == 3:
            # Blue Base only = lid missing, assembly failed
            self.last_qc_result = "FAIL"
            self.last_fail_reason = "lid_missing_base_only"
            self.fail_count += 1

        elif self.last_vision_value == 0:
            # Nothing detected
            self.last_qc_result = "FAIL"
            self.last_fail_reason = "nothing_detected"
            self.fail_count += 1

        else:
            # Some other product type
            self.last_qc_result = "FAIL"
            self.last_fail_reason = f"wrong_type_{item_name}"
            self.fail_count += 1

        return self.last_qc_result

    # ──────────────────────────────────────
    # MQTT
    # ──────────────────────────────────────
    def publish_status(self):
        if not self.mqtt:
            return
        try:
            rate = (self.pass_count / self.product_count * 100) if self.product_count > 0 else 0
            payload = json.dumps({
                "station": 6,
                "name": "Quality_Control",
                "state": self.state,
                "product_count": self.product_count,
                "pass_count": self.pass_count,
                "fail_count": self.fail_count,
                "pass_rate_pct": round(rate, 1),
                "last_qc_result": self.last_qc_result,
                "last_vision_value": self.last_vision_value,
                "last_vision_item": VISION_ITEMS.get(self.last_vision_value, "Unknown"),
                "last_fail_reason": self.last_fail_reason,
                "discovery_mode": self.discovery_mode,
                "running": self.running
            })
            self.mqtt.publish("factory/station6/status", payload)
        except Exception:
            pass

    # ──────────────────────────────────────
    # State Machine
    # ──────────────────────────────────────
    def main(self):
        self.running = True
        self.transition_belt(True)

        if self.discovery_mode:
            print("[STN6] 🔍 Quality Control starting (DISCOVERY MODE)...")
            print("[STN6] 💡 Send products through to find EXPECTED_VALUE")
        else:
            expected_name = VISION_ITEMS.get(self.EXPECTED_VALUE, "?")
            print(f"[STN6] 🔍 Quality Control starting (expecting: {self.EXPECTED_VALUE} = {expected_name})...")

        while self.running:
            sensors = self.read_sensors()

            # ── STATE 0: READY ──
            if self.state == 0:
                self.belt(True)
                self.blade(True)        # UP = blocking
                self.lights_off()

                # Wait for sensor clear (prevent false detection)
                if sensors["sensor_6"]:
                    time.sleep(0.05)
                    continue

                print("[STN6] ⏳ Waiting for product...")
                while self.running:
                    sensors = self.read_sensors()
                    if sensors["sensor_6"]:
                        break
                    time.sleep(0.05)

                if not self.running:
                    break

                self.cycle_start_time = time.time()
                print("[STN6] 📦 Product detected!")
                self.state = 1

            # ── STATE 1: ARRIVED ──
            elif self.state == 1:
                self.belt(False)
                time.sleep(self.SETTLE_TIME)
                self.lights_off()
                time.sleep(0.1)
                self.light_yellow(True)
                print("[STN6] 🔬 Inspecting product...")
                self.state = 2

            # ── STATE 2: INSPECTING ──
            elif self.state == 2:
                time.sleep(self.INSPECT_TIME)
                result = self.perform_inspection()
                print(f"[STN6] 📋 Product #{self.product_count}: {result}"
                      f"{f' ({self.last_fail_reason})' if self.last_fail_reason else ''}")
                self.state = 3

            # ── STATE 3: QC RESULT ──
            elif self.state == 3:
                # Turn ALL lights OFF first to prevent overlap
                self.lights_off()
                time.sleep(0.1)

                if self.last_qc_result == "PASS":
                    self.light_green(True)
                    print("[STN6] ✅ PASS — Green light ON")
                else:
                    self.light_red(True)
                    print("[STN6] ❌ FAIL — Red light ON")

                time.sleep(self.RESULT_DISPLAY)
                self.state = 4

            # ── STATE 4: RELEASING ──
            elif self.state == 4:
                self.blade(False)       # DOWN = release
                time.sleep(self.RELEASE_DELAY)
                self.belt(True)
                print("[STN6] 🔄 Releasing product...")
                self.state = 5

            # ── STATE 5: EXITING ──
            elif self.state == 5:
                while self.running:
                    sensors = self.read_sensors()
                    if not sensors["sensor_6"]:
                        break
                    time.sleep(0.05)

                time.sleep(0.5)
                self.lights_off()

                ct = time.time() - self.cycle_start_time if self.cycle_start_time else 0
                rate = self.pass_count / self.product_count * 100 if self.product_count > 0 else 0
                item_name = VISION_ITEMS.get(self.last_vision_value, "?")
                print(f"[STN6] ✅ Cycle done | {ct:.1f}s | "
                      f"Vision:{self.last_vision_value}({item_name}) | "
                      f"Pass:{self.pass_count} Fail:{self.fail_count} Rate:{rate:.0f}%")

                self.publish_status()
                self.state = 0

            time.sleep(0.05)

        # Shutdown
        self.belt(False)
        self.blade(False)
        self.lights_off()
        print("[STN6] 🛑 Quality Control stopped.")

    def stop(self):
        self.running = False


# ═══════════════════════════════════════════════════════
# Synced version (for multi-station line)
# ═══════════════════════════════════════════════════════

class SyncedStation6(Station6):
    """Station 6 with upstream/downstream synchronization"""

    def __init__(self, modbus_client, mqtt_client=None,
                 upstream_ready_event=None, downstream_ready_event=None):
        super().__init__(modbus_client, mqtt_client)
        # THIS station sets this when ready to receive from upstream (Stn3)
        self.upstream_ready = upstream_ready_event or threading.Event()
        # DOWNSTREAM (Stn7) sets this when ready to receive from us
        self.downstream_ready = downstream_ready_event

    def _signal_ready(self):
        """Tell upstream (Station 3) we're ready to receive"""
        self.upstream_ready.set()
        print("[STN6] 🟢 Ready — signaled upstream")

    def blade(self, up):
        """Override: wait for downstream before releasing"""
        if not up and self.downstream_ready:
            print("[STN6] ⏳ Waiting for downstream (Stn7) ready...")
            self.downstream_ready.wait()
            self.downstream_ready.clear()
            print("[STN6] ✅ Downstream ready — releasing")
        super().blade(up)

    def main(self):
        self.running = True
        self.transition_belt(True)

        if self.discovery_mode:
            print("[STN6] 🔍 QC starting (DISCOVERY + SYNCED)...")
        else:
            expected_name = VISION_ITEMS.get(self.EXPECTED_VALUE, "?")
            print(f"[STN6] 🔍 QC starting (SYNCED, expecting: {self.EXPECTED_VALUE} = {expected_name})...")

        while self.running:
            sensors = self.read_sensors()

            # ── STATE 0: READY ──
            if self.state == 0:
                self.belt(True)
                # Use parent blade directly — no sync needed for raising
                Station6.blade(self, True)
                self.lights_off()

                # Wait for sensor clear
                if sensors["sensor_6"]:
                    time.sleep(0.05)
                    continue

                # Signal upstream BEFORE waiting
                self._signal_ready()

                print("[STN6] ⏳ Waiting for product...")
                while self.running:
                    sensors = self.read_sensors()
                    if sensors["sensor_6"]:
                        break
                    time.sleep(0.05)

                if not self.running:
                    break

                self.cycle_start_time = time.time()
                print("[STN6] 📦 Product detected!")
                self.state = 1

            # ── STATE 1: ARRIVED ──
            elif self.state == 1:
                self.belt(False)
                time.sleep(self.SETTLE_TIME)
                self.lights_off()
                time.sleep(0.1)
                self.light_yellow(True)
                print("[STN6] 🔬 Inspecting...")
                self.state = 2

            # ── STATE 2: INSPECTING ──
            elif self.state == 2:
                time.sleep(self.INSPECT_TIME)
                result = self.perform_inspection()
                print(f"[STN6] 📋 Product #{self.product_count}: {result}"
                      f"{f' ({self.last_fail_reason})' if self.last_fail_reason else ''}")
                self.state = 3

            # ── STATE 3: QC RESULT ──
            elif self.state == 3:
                # Turn ALL lights OFF first
                self.lights_off()
                time.sleep(0.1)

                if self.last_qc_result == "PASS":
                    self.light_green(True)
                    print("[STN6] ✅ PASS")
                else:
                    self.light_red(True)
                    print("[STN6] ❌ FAIL")

                time.sleep(self.RESULT_DISPLAY)
                self.state = 4

            # ── STATE 4: RELEASING ──
            elif self.state == 4:
                self.blade(False)       # Synced: waits for downstream
                time.sleep(self.RELEASE_DELAY)
                self.belt(True)
                print("[STN6] 🔄 Releasing...")
                self.state = 5

            # ── STATE 5: EXITING ──
            elif self.state == 5:
                while self.running:
                    sensors = self.read_sensors()
                    if not sensors["sensor_6"]:
                        break
                    time.sleep(0.05)

                time.sleep(0.5)
                self.lights_off()

                ct = time.time() - self.cycle_start_time if self.cycle_start_time else 0
                rate = self.pass_count / self.product_count * 100 if self.product_count > 0 else 0
                item_name = VISION_ITEMS.get(self.last_vision_value, "?")
                print(f"[STN6] ✅ Cycle done | {ct:.1f}s | "
                      f"Vision:{self.last_vision_value}({item_name}) | "
                      f"Pass:{self.pass_count} Fail:{self.fail_count} Rate:{rate:.0f}%")

                self.publish_status()
                self.state = 0

            time.sleep(0.05)

        # Shutdown
        self.belt(False)
        Station6.blade(self, False)
        self.lights_off()
        print("[STN6] 🛑 Quality Control stopped.")