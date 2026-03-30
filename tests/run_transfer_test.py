"""
Test runner for Transfer Station (standalone).
PICK = X=TRUE (far end)  |  PLACE = X=FALSE (X=0)
Sensor 9 = product on Belt 6  |  Pallet = timed wait
"""

import sys
import os
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from factory.modbus_client import FactoryModbusClient
from factory.stations.transfer import TransferStation


def main():
    print("=" * 60)
    print("  🔄 TRANSFER STATION - Standalone Test")
    print("=" * 60)
    print()
    print("  PICK  = X=TRUE  (far end, over Belt 6)")
    print("  PLACE = X=FALSE (X=0, over Roller 1)")
    print("  Sensor 9 = product on Belt 6")
    print("  Pallet = timed wait (no sensor)")
    print()
    print("  In Factory I/O:")
    print("    1. Place components and wire I/O tags")
    print("    2. Emitter 3 → set to emit Pallets")
    print("    3. Two-Axis P&P → set to Digital mode")
    print("    4. Start simulation (Play)")
    print("    5. Place a product on Belt 6 manually")
    print()

    client = FactoryModbusClient()
    if not client.connect():
        print("❌ Failed to connect to Factory I/O!")
        return

    print("✅ Connected to Factory I/O\n")

    station = TransferStation(client, station_name="Transfer")

    try:
        station.run()
    except KeyboardInterrupt:
        print("\n\n  ⛔ Interrupted by user")
    finally:
        station.stop()
        client.disconnect()
        print("  🔌 Disconnected")


if __name__ == "__main__":
    main()