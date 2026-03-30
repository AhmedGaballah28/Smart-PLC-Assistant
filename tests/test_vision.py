"""Find where the Vision Sensor value actually lives"""

import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from factory.modbus_client import FactoryModbusClient

modbus = FactoryModbusClient()
if not modbus.connect():
    print("❌ Cannot connect")
    exit()

print("✅ Connected")
print()
print("Place a product UNDER the Vision Sensor")
print("Make sure the Vision Sensor LED is GREEN right now")
print()
input("Press Enter when product is under sensor and LED is green...")
print()

# Try Input Registers (FC 4)
print("=== Input Registers (read_input_registers) ===")
for addr in range(16):
    result = modbus.client.read_input_registers(addr, 1)
    if result is not None and len(result) > 0 and result[0] != 0:
        print(f"  Register Input {addr} = {result[0]}  ← ⭐ FOUND SOMETHING!")
    else:
        val = result[0] if result and len(result) > 0 else None
        print(f"  Register Input {addr} = {val}")

print()

# Try Holding Registers (FC 3)
print("=== Holding Registers (read_holding_registers) ===")
for addr in range(16):
    result = modbus.client.read_holding_registers(addr, 1)
    if result is not None and len(result) > 0 and result[0] != 0:
        print(f"  Holding Register {addr} = {result[0]}  ← ⭐ FOUND SOMETHING!")
    else:
        val = result[0] if result and len(result) > 0 else None
        print(f"  Holding Register {addr} = {val}")

print()

# Also check discrete inputs (maybe it's in digital mode)
print("=== Digital Inputs (discrete inputs) ===")
result = modbus.client.read_discrete_inputs(0, 20)
if result:
    for i, v in enumerate(result):
        if v:
            print(f"  Digital Input {i} = {v}  ← ⭐ ON!")
        else:
            print(f"  Digital Input {i} = {v}")

print()
print("Now REMOVE the product from under the sensor")
input("Press Enter when sensor LED is OFF...")
print()

print("=== Input Registers (no product) ===")
for addr in range(16):
    result = modbus.client.read_input_registers(addr, 1)
    val = result[0] if result and len(result) > 0 else None
    print(f"  Register Input {addr} = {val}")

print()
print("=== Holding Registers (no product) ===")
for addr in range(16):
    result = modbus.client.read_holding_registers(addr, 1)
    val = result[0] if result and len(result) > 0 else None
    print(f"  Holding Register {addr} = {val}")

modbus.disconnect()
print()
print("Done! Tell me which address had a non-zero value!")