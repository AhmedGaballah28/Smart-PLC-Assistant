"""
Station 6: Quality Control — Standalone Test Runner
Uses Vision Sensor (All Numerical) to detect product type.
EXPECTED_VALUE = 5 (Green Product Lid on top = assembled)
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from factory.modbus_client import FactoryModbusClient
from factory.stations.station6 import Station6, VISION_ITEMS

# Test emitter address (remove for full line)
TEST_EMITTER = 20


def create_test_product(modbus):
    """Pulse test emitter to create one product"""
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
    print("  Station 6: Quality Control — Standalone Test")
    print("=" * 55)
    print()
    print("I/O Map:")
    print("  Belt 3b (transition)    → Digital Output 14")
    print("  Belt 4 (main)           → Digital Output 15")
    print("  Stop Blade 3            → Digital Output 16")
    print("  Stack Light Green       → Digital Output 17")
    print("  Stack Light Yellow      → Digital Output 18")
    print("  Stack Light Red         → Digital Output 19")
    print("  Test Emitter            → Digital Output 20")
    print("  Diffuse Sensor 6        → Digital Input 10")
    print("  Vision Sensor (Value)   → Register Input 0")
    print()

    # Quick vision sensor test
    print("Testing Vision Sensor register read...")
    val = modbus.read_register(0)
    name = VISION_ITEMS.get(val, f"Unknown({val})")
    print(f"  Vision Sensor register 0 = {val} ({name})")
    if val is None:
        print("  ⚠️  Could not read register!")
    else:
        print("  ✅ Register read working!")
    print()

    input("Press Enter when Factory I/O is running...")

    station = Station6(modbus)

    station_thread = threading.Thread(target=station.main, daemon=True)
    station_thread.start()

    print()
    print("Commands:")
    print("  p  = Create test product")
    print("  v  = Read vision sensor NOW")
    print("  s  = Show QC statistics")
    print("  q  = Quit")
    print()

    try:
        while True:
            cmd = input("> ").strip().lower()

            if cmd == 'q':
                break

            elif cmd == 'p':
                create_test_product(modbus)

            elif cmd == 'v':
                val = modbus.read_register(0)
                name = VISION_ITEMS.get(val, f"Unknown({val})")
                print(f"  📷 Vision Sensor: {val} = {name}")

            elif cmd == 's':
                rate = (station.pass_count / station.product_count * 100) if station.product_count > 0 else 0
                print(f"  State:        {station.state}")
                print(f"  Products:     {station.product_count}")
                print(f"  Pass:         {station.pass_count}")
                print(f"  Fail:         {station.fail_count}")
                print(f"  Rate:         {rate:.0f}%")
                print(f"  Last result:  {station.last_qc_result}")
                print(f"  Last vision:  {station.last_vision_value} = {VISION_ITEMS.get(station.last_vision_value, '?')}")
                print(f"  Last reason:  {station.last_fail_reason}")
                print(f"  Discovery:    {station.discovery_mode}")

            else:
                print("  p=product  v=vision  s=stats  q=quit")

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