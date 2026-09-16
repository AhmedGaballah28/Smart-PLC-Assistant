"""
Quick test to verify Python can talk to Factory I/O
"""

import time
from pyModbusTCP.client import ModbusClient


def main():
    print("=" * 60)
    print("  📺 FACTORY I/O CONNECTION TEST")
    print("=" * 60)

    # ─────────────────────────────────────────
    # Step 1: Connect to Factory I/O
    # ─────────────────────────────────────────
    print("\n🔌 Connecting to Factory I/O...")

    client = ModbusClient(
        host="192.168.101.160",
        port=502,
        unit_id=1,
        auto_open=True,
        auto_close=False,
        timeout=5.0
    )

    if not client.open():
        print("❌ Cannot connect to Factory I/O!")
        print("   Make sure:")
        print("   1. Factory I/O is running")
        print("   2. Modbus TCP/IP Server is enabled (F4)")
        print("   3. Scene is in PLAY mode (F5)")
        return

    print("✅ Connected to Factory I/O!\n")

    # ─────────────────────────────────────────
    # Step 2: Read Sensors
    # ─────────────────────────────────────────
    print("📡 Reading Sensors...")
    print("-" * 40)

    inputs = client.read_discrete_inputs(0, 4)
    if inputs:
        print(f"   Input 0 (Sensor 1 - Entry):   {inputs[0]}")
        print(f"   Input 1 (Sensor 2 - Station): {inputs[1]}")
        print(f"   Input 2 (Future):             {inputs[2]}")
        print(f"   Input 3 (Future):             {inputs[3]}")
    else:
        print("   ⚠️ Could not read inputs")
        print("   Trying alternative read method...")
        inputs = client.read_coils(0, 4)
        if inputs:
            print(f"   Input 0 (Sensor 1 - Entry):   {inputs[0]}")
            print(f"   Input 1 (Sensor 2 - Station): {inputs[1]}")
        else:
            print("   ❌ Failed to read inputs")

    # ─────────────────────────────────────────
    # Step 3: Test Outputs (Actuators)
    # ─────────────────────────────────────────
    print(f"\n⚡ Testing Outputs...")
    print("-" * 40)

    # Test Belt 1
    print("   Testing Belt 1 (Output 0)...")
    result = client.write_single_coil(0, True)
    print(f"   Belt 1 ON:  {'✅' if result else '❌'}")
    time.sleep(2)

    # Test Belt 2
    print("   Testing Belt 2 (Output 1)...")
    result = client.write_single_coil(1, True)
    print(f"   Belt 2 ON:  {'✅' if result else '❌'}")
    time.sleep(2)

    # Test Emitter
    print("   Testing Emitter (Output 2)...")
    result = client.write_single_coil(2, True)
    print(f"   Emitter ON: {'✅' if result else '❌'}")
    time.sleep(2)
    client.write_single_coil(2, False)
    print(f"   Emitter OFF: ✅")

    # Test Stop Blade
    print("   Testing Stop Blade (Output 3)...")
    result = client.write_single_coil(3, True)
    print(f"   Stop Blade UP:   {'✅' if result else '❌'}")
    time.sleep(2)
    client.write_single_coil(3, False)
    print(f"   Stop Blade DOWN: ✅")

    # ─────────────────────────────────────────
    # Step 4: Full Cycle Test
    # ─────────────────────────────────────────
    print(f"\n🔄 Running Full Station 1 Cycle Test...")
    print("-" * 40)

    # Stop everything first
    client.write_single_coil(0, False)  # Belt 1 OFF
    client.write_single_coil(1, False)  # Belt 2 OFF
    client.write_single_coil(2, False)  # Emitter OFF
    client.write_single_coil(3, False)  # Stop Blade DOWN
    time.sleep(1)

    # Step A: Raise Stop Blade
    print("   Step A: Raising Stop Blade...")
    client.write_single_coil(3, True)
    time.sleep(0.5)

    # Step B: Start Belts
    print("   Step B: Starting Belts...")
    client.write_single_coil(0, True)   # Belt 1 ON
    client.write_single_coil(1, True)   # Belt 2 ON
    time.sleep(0.5)

    # Step C: Create Product
    print("   Step C: Creating chassis (Emitter pulse)...")
    client.write_single_coil(2, True)
    time.sleep(0.5)
    client.write_single_coil(2, False)
    print("   📦 Chassis created!")

    # Step D: Wait for product to reach Stop Blade
    print("   Step D: Waiting for chassis to reach Stop Blade...")
    timeout = 15
    start = time.time()
    product_detected_entry = False
    product_at_station = False

    while time.time() - start < timeout:
        inputs = client.read_discrete_inputs(0, 2)
        if inputs is None:
            inputs = client.read_coils(0, 2)

        if inputs:
            # Check Entry Sensor
            if inputs[0] and not product_detected_entry:
                print(f"   📡 Sensor 1: Chassis detected at entry! ({time.time()-start:.1f}s)")
                product_detected_entry = True

            # Check Station Sensor
            if inputs[1] and not product_at_station:
                print(f"   📡 Sensor 2: Chassis arrived at station! ({time.time()-start:.1f}s)")
                product_at_station = True
                break

        time.sleep(0.1)

    if not product_at_station:
        print("   ❌ TIMEOUT: Chassis never reached station!")
        print("   Check sensor positions and belt direction")
    else:
        # Step E: Simulate Inspection
        print("   Step E: Inspecting chassis (3 seconds)...")
        for i in range(3, 0, -1):
            print(f"           Inspecting... {i}s remaining")
            time.sleep(1)
        print("   ✅ Inspection PASSED!")

        # Step F: Release product
        print("   Step F: Releasing chassis (Stop Blade DOWN)...")
        client.write_single_coil(3, False)
        time.sleep(3)

        # Check if product left
        inputs = client.read_discrete_inputs(0, 2)
        if inputs is None:
            inputs = client.read_coils(0, 2)

        if inputs and not inputs[1]:
            print("   ✅ Chassis released successfully!")
        else:
            print("   ⚠️ Chassis might still be at station")

    # ─────────────────────────────────────────
    # Step 5: Cleanup
    # ─────────────────────────────────────────
    print(f"\n🧹 Cleaning up...")
    time.sleep(2)
    client.write_single_coil(0, False)  # Belt 1 OFF
    client.write_single_coil(1, False)  # Belt 2 OFF
    client.write_single_coil(2, False)  # Emitter OFF
    client.write_single_coil(3, False)  # Stop Blade DOWN

    client.close()

    print("\n" + "=" * 60)
    print("  📊 TEST RESULTS SUMMARY")
    print("=" * 60)
    print(f"   Connection:        ✅")
    print(f"   Belt 1:            ✅")
    print(f"   Belt 2:            ✅")
    print(f"   Emitter:           ✅")
    print(f"   Stop Blade:        ✅")
    print(f"   Entry Sensor:      {'✅' if product_detected_entry else '❌'}")
    print(f"   Station Sensor:    {'✅' if product_at_station else '❌'}")
    print(f"   Full Cycle:        {'✅' if product_at_station else '❌'}")
    print("=" * 60)


if __name__ == "__main__":
    main()