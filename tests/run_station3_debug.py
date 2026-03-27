"""
Station 3 Standalone Test — CORRECTED CYCLE

CORRECT CYCLE ORDER:
  1. Detect product (sensor)
  2. Belt OFF
  3. CLAMP product
  4. Wait 5 seconds (mounting)
  5. UNCLAMP product
  6. RAISE bar (out of the way)
  7. Belt ON, product exits
  8. LOWER bar (ready for next)
"""

import sys
import os
import time
import logging
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from factory.modbus_client import FactoryModbusClient
from factory.stations.station3 import Station3Controller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Station3Test")


# I/O Addresses
BELT_3 = 11
POS_RAISE = 12
POS_CLAMP = 13
SENSOR_5 = 9
POS_CLAMPED = 7
POS_LIMIT = 8


FAULT_MAP = {
    "f1": "overheat",
    "f3": "power",
    "f4": "belt_slip",
    "f5": "sensor_drift",
    "f6": "positioner_jam",
}


def read_sensor(modbus, addr):
    result = modbus.read_inputs(addr, 1)
    return result[0] if result else False


def show_io(modbus):
    """Display current I/O status."""
    sensor = read_sensor(modbus, SENSOR_5)
    clamped = read_sensor(modbus, POS_CLAMPED)
    limit = read_sensor(modbus, POS_LIMIT)
    
    print()
    print("  ┌─────────────────────────────────────────┐")
    print("  │  📊 STATION 3 I/O STATUS                │")
    print("  ├─────────────────────────────────────────┤")
    print(f"  │  Sensor 5:    {'🟢 PRODUCT' if sensor else '⚫ clear':16s}   │")
    print(f"  │  Clamped:     {'🟢 CLAMPED' if clamped else '⚫ open':16s}   │")
    print(f"  │  Limit:       {'🟢 BAR UP' if limit else '⚫ bar down':16s}   │")
    print("  └─────────────────────────────────────────┘")
    print()


def manual_cycle(modbus):
    """Run one manual cycle with timing display."""
    print()
    print("  ═══════════════════════════════════════════════")
    print("  📺 MANUAL CYCLE — CORRECT ORDER")
    print("  ═══════════════════════════════════════════════")
    print()
    
    cycle_start = time.time()
    
    # Initialize
    print("  [INIT] Bar DOWN, Clamp OPEN, Belt ON")
    modbus.write_output(POS_RAISE, False)   # Bar down
    modbus.write_output(POS_CLAMP, False)   # Clamp open
    modbus.write_output(BELT_3, True)       # Belt on
    time.sleep(0.5)
    
    # Wait for product
    print("  [STATE 0] Waiting for product...")
    if not read_sensor(modbus, SENSOR_5):
        print("           Place a product on Belt 3...")
        timeout = time.time() + 60
        while not read_sensor(modbus, SENSOR_5) and time.time() < timeout:
            time.sleep(0.1)
        if time.time() >= timeout:
            print("  ❌ Timeout!")
            return
    
    state_time = time.time() - cycle_start
    print(f"  [STATE 1] ✅ Product detected! ({state_time:.1f}s)")
    
    # Belt OFF
    print("  [STATE 1] Belt OFF")
    modbus.write_output(BELT_3, False)
    time.sleep(0.3)
    
    # CLAMP
    state_start = time.time()
    print("  [STATE 2] 🔧 CLAMPING product...")
    modbus.write_output(POS_CLAMP, True)
    
    timeout = time.time() + 5
    while not read_sensor(modbus, POS_CLAMPED) and time.time() < timeout:
        time.sleep(0.05)
    
    state_time = time.time() - state_start
    print(f"           ✓ Clamped: {read_sensor(modbus, POS_CLAMPED)} ({state_time:.2f}s)")
    
    # MOUNT (5 SECONDS!)
    state_start = time.time()
    print("  [STATE 3] 📺 MOUNTING DISPLAY PANEL...")
    print("           ⏱️ Counting 5 seconds:")
    for i in range(5, 0, -1):
        print(f"              {i}...")
        time.sleep(1.0)
    
    state_time = time.time() - state_start
    print(f"           ✅ Mounted! ({state_time:.2f}s)")
    
    # UNCLAMP
    state_start = time.time()
    print("  [STATE 4] 🔧 UNCLAMPING product...")
    modbus.write_output(POS_CLAMP, False)
    
    timeout = time.time() + 5
    while read_sensor(modbus, POS_CLAMPED) and time.time() < timeout:
        time.sleep(0.05)
    
    state_time = time.time() - state_start
    print(f"           ✓ Unclamped ({state_time:.2f}s)")
    
    # RAISE BAR
    state_start = time.time()
    print("  [STATE 5] ⬆️ RAISING bar (opening path)...")
    modbus.write_output(POS_RAISE, True)
    
    timeout = time.time() + 5
    while not read_sensor(modbus, POS_LIMIT) and time.time() < timeout:
        time.sleep(0.05)
    
    state_time = time.time() - state_start
    print(f"           ✓ Bar raised ({state_time:.2f}s)")
    
    # EXIT
    state_start = time.time()
    print("  [STATE 6] 🔄 Belt ON — product exiting...")
    modbus.write_output(BELT_3, True)
    
    timeout = time.time() + 10
    while read_sensor(modbus, SENSOR_5) and time.time() < timeout:
        time.sleep(0.05)
    
    time.sleep(1.5)  # Extra exit time
    
    state_time = time.time() - state_start
    print(f"           ✓ Product exited ({state_time:.2f}s)")
    
    # LOWER BAR
    state_start = time.time()
    print("  [STATE 7] ⬇️ LOWERING bar...")
    modbus.write_output(POS_RAISE, False)
    
    timeout = time.time() + 5
    while read_sensor(modbus, POS_LIMIT) and time.time() < timeout:
        time.sleep(0.05)
    
    state_time = time.time() - state_start
    print(f"           ✓ Bar lowered ({state_time:.2f}s)")
    
    # Done
    cycle_time = time.time() - cycle_start
    print()
    print("  ═══════════════════════════════════════════════")
    print(f"  ✅ CYCLE COMPLETE: {cycle_time:.1f}s")
    print(f"     (Expected: ~8-10s with 5s mount time)")
    print("  ═══════════════════════════════════════════════")
    print()


def main():
    print()
    print("═" * 60)
    print("  📺 STATION 3 — STANDALONE TEST (CORRECTED CYCLE)")
    print("═" * 60)
    print()
    print("  CORRECT CYCLE ORDER:")
    print("    1. Detect → 2. Clamp → 3. Mount 5s → 4. Unclamp")
    print("    5. Raise bar → 6. Exit → 7. Lower bar")
    print()

    modbus = FactoryModbusClient()
    if not modbus.connect():
        print("  ❌ Cannot connect to Factory I/O!")
        return

    print("  ✅ Connected to Factory I/O")
    show_io(modbus)

    print("  Commands:")
    print("    m     - Run one manual cycle (with timing)")
    print("    auto  - Start automatic station")
    print("    io    - Show I/O status")
    print("    q     - Quit")
    print()

    station = None
    station_thread = None

    try:
        while True:
            cmd = input("  [Station 3] > ").strip().lower()

            if not cmd:
                continue

            if cmd == "q":
                break

            elif cmd == "io":
                show_io(modbus)

            elif cmd == "m":
                manual_cycle(modbus)

            elif cmd == "auto":
                if station and station.is_running:
                    print("  Station already running!")
                    continue
                
                print("  Starting automatic mode...")
                station = Station3Controller(modbus)
                station_thread = threading.Thread(target=station.run, daemon=True)
                station_thread.start()
                print("  🏭 Station 3 running! Place products to test.")
                print()
                print("  Auto mode commands:")
                print("    f1-f6  Inject fault")
                print("    fc     Clear faults")
                print("    st     Show status")
                print("    stop   Stop automatic mode")
                print()

            elif cmd == "stop":
                if station and station.is_running:
                    station.is_running = False
                    station_thread.join(timeout=5)
                    print("  Automatic mode stopped")
                    station = None
                else:
                    print("  Not running in automatic mode")

            elif cmd == "fc":
                if station:
                    station.clear_fault("all")
                else:
                    print("  Start 'auto' mode first")

            elif cmd == "st":
                if station:
                    s = station.get_status()
                    print(f"    State: {s['state']}")
                    print(f"    Products: {s['counters']['products_completed']}")
                    print(f"    Avg cycle: {s['timing']['average_cycle_time']:.1f}s")
                else:
                    show_io(modbus)

            elif cmd.startswith("f") and len(cmd) >= 2:
                if not station:
                    print("  Start 'auto' mode first")
                    continue
                parts = cmd.split()
                if parts[0] in FAULT_MAP:
                    sev = int(parts[1]) if len(parts) > 1 else 3
                    station.inject_fault(FAULT_MAP[parts[0]], sev)
                else:
                    print("  Unknown fault")

            else:
                print("  Commands: m, auto, io, stop, f1-f6, fc, st, q")

    except KeyboardInterrupt:
        pass

    finally:
        if station and station.is_running:
            station.is_running = False
        
        # Safe shutdown
        modbus.write_output(BELT_3, False)
        modbus.write_output(POS_RAISE, False)
        modbus.write_output(POS_CLAMP, False)
        modbus.disconnect()
        print("  Done!")


if __name__ == "__main__":
    main()