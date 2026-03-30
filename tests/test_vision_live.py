"""Quick vision sensor monitor — reads continuously"""
import sys, os, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from factory.modbus_client import FactoryModbusClient

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

modbus = FactoryModbusClient()
if not modbus.connect():
    print("❌ Cannot connect")
    exit()

print("✅ Connected — Reading Vision Sensor continuously")
print("   Press Ctrl+C to stop")
print()
print("   Move different products under the sensor and watch:")
print()

last_val = None
try:
    while True:
        val = modbus.read_register(0)
        if val != last_val:
            name = VISION_ITEMS.get(val, f"Unknown({val})")
            print(f"   📷 Vision Sensor: {val} = {name}")
            last_val = val
        time.sleep(0.1)
except KeyboardInterrupt:
    print("\nDone.")
    modbus.disconnect()