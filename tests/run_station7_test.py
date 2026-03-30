"""
Station 7: Sorting & Output — Standalone Test Runner
Simulates QC results to test sorting with real Pivot Arm Sorter.
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from factory.modbus_client import FactoryModbusClient
from factory.stations.station7 import Station7

TEST_EMITTER = 27


class FakeStation6:
    """Simulates Station 6 QC results for standalone testing"""
    def __init__(self):
        self.last_qc_result = "PASS"


def create_test_product(modbus):
    modbus.write_output(TEST_EMITTER, True)
    time.sleep(0.3)
    modbus.write_output(TEST_EMITTER, False)
    print("[TEST] 📦 Test product created")


def main():
    modbus = FactoryModbusClient()

    if not modbus.connect():
        print("❌ Cannot connect to Factory I/O")
        return

    print("✅ Connected to Factory I/O")
    print("=" * 55)
    print("  Station 7: Sorting & Output — Standalone Test")
    print("=" * 55)
    print()
    print("I/O Map:")
    print("  Belt 4b (transition)         → Digital Output 20")
    print("  Belt 5 (main)                → Digital Output 21")
    print("  Pivot Arm Sorter (Turn)      → Digital Output 22")
    print("  Pivot Arm Sorter Belt (+)    → Digital Output 23")
    print("  Pivot Arm Sorter Belt (-)    → Digital Output 24")
    print("  Light Indicator Green        → Digital Output 25")
    print("  Light Indicator Red          → Digital Output 26")
    print("  Test Emitter                 → Digital Output 27")
    print("  Diffuse Sensor 7             → Digital Input 11")
    print()
    print("Remover 1 at end of straight path (good)")
    print("Remover 2 at end of divert path (reject)")
    print()

    input("Press Enter when Factory I/O is running...")

    fake_stn6 = FakeStation6()
    station = Station7(modbus, station6_ref=fake_stn6)

    station_thread = threading.Thread(target=station.main, daemon=True)
    station_thread.start()

    print()
    print("Commands:")
    print("  p  = Create test product (uses current QC setting)")
    print("  g  = Set QC to PASS (next → GOOD bin, straight)")
    print("  f  = Set QC to FAIL (next → REJECT bin, divert)")
    print("  s  = Show statistics")
    print("  t  = Test sorter arm manually")
    print("  q  = Quit")
    print()
    print(f"  Current QC: {fake_stn6.last_qc_result}")
    print()

    try:
        while True:
            cmd = input("> ").strip().lower()

            if cmd == 'q':
                break

            elif cmd == 'p':
                create_test_product(modbus)

            elif cmd == 'g':
                fake_stn6.last_qc_result = "PASS"
                print("  ✅ Next product → PASS → GOOD bin (straight)")

            elif cmd == 'f':
                fake_stn6.last_qc_result = "FAIL"
                print("  ❌ Next product → FAIL → REJECT bin (divert)")

            elif cmd == 's':
                print(f"  State:    {station.state}")
                print(f"  Total:    {station.product_count}")
                print(f"  Good:     {station.good_count}")
                print(f"  Reject:   {station.reject_count}")
                print(f"  Last:     {station.last_sort_result}")
                print(f"  QC set:   {fake_stn6.last_qc_result}")

            elif cmd == 't':
                print("  Testing sorter arm...")
                print("  1. STRAIGHT (Turn OFF)...")
                modbus.write_output(22, False)
                modbus.write_output(23, True)       # Belt forward
                time.sleep(2)
                print("  2. DIVERT (Turn ON)...")
                modbus.write_output(22, True)
                time.sleep(2)
                print("  3. Belt forward ON...")
                modbus.write_output(23, True)
                time.sleep(2)
                print("  4. Reset: STRAIGHT, belt ON...")
                modbus.write_output(22, False)
                modbus.write_output(23, True)
                print("  Done!")

            else:
                print("  p=product g=pass f=fail s=stats t=test q=quit")

    except KeyboardInterrupt:
        pass

    print("\nShutting down...")
    station.stop()
    station_thread.join(timeout=3)
    modbus.write_output(TEST_EMITTER, False)
    modbus.disconnect()
    print("Done.")


if __name__ == "__main__":
    main()