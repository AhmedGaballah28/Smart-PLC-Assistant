"""
Test Station 2 ALONE.
Products are created by Station 1 (must be running)
OR manually place a Product Base in Factory I/O.
"""

import logging
import sys
import os
import threading

# Add workspace root to Python path so we can import 'factory' module
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from factory.modbus_client import FactoryModbusClient
from factory.stations.station2 import Station2Controller


def fault_menu(station: Station2Controller):
    """Fault injection for Station 2."""
    print()
    print("  ┌───────────────────────────────────────────────────┐")
    print("  │  STN2 FAULT INJECTION — Pick & Place Effects! ⚡   │")
    print("  │                                                    │")
    print("  │  f1 [sev] = Overheat     (belt stutter/ESTOP)    │")
    print("  │  f3 [sev] = Power        (brownout/ESTOP)        │")
    print("  │  f4 [sev] = Belt Slip    (belt stops randomly)   │")
    print("  │  f5 [sev] = Sensor Drift (wrong decisions)       │")
    print("  │  f6 [sev] = Gripper Fail (DROPS lid mid-air!) ⚡  │")
    print("  │  f7 [sev] = P&P Jam      (EMERGENCY STOP)       │")
    print("  │                                                    │")
    print("  │  fc = Clear ALL    fe = Effects    rp = Report    │")
    print("  └───────────────────────────────────────────────────┘")
    print()

    while station.is_running:
        try:
            cmd = input().strip().lower()

            if cmd.startswith("f1"):
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                station.inject_fault("overheat", sev)
            elif cmd.startswith("f3"):
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                station.inject_fault("power", sev)
            elif cmd.startswith("f4"):
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                station.inject_fault("belt_slip", sev)
            elif cmd.startswith("f5"):
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                station.inject_fault("sensor_drift", sev)
            elif cmd.startswith("f6"):
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                station.inject_fault("gripper", sev)
            elif cmd.startswith("f7"):
                parts = cmd.split()
                sev = int(parts[1]) if len(parts) > 1 else 3
                station.inject_fault("pp_jam", sev)
            elif cmd == "fc":
                station.clear_fault("all")
            elif cmd == "fe":
                fc = station._fault_counters
                print(f"\n  ⚡ Stutters={fc['stutters']}, "
                      f"Brownouts={fc['brownouts']}, "
                      f"Grips={fc['gripper_failures']}, "
                      f"E-Stops={fc['emergency_stops']}, "
                      f"Misreads={fc['sensor_misreads']}\n")
            elif cmd == "rp":
                print(station.get_full_report())

        except (EOFError, ValueError):
            pass
        except Exception as e:
            print(f"  Error: {e}")


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    print()
    print("═" * 65)
    print("  📺 TV ASSEMBLY LINE — STATION 2 TEST")
    print("  🔧 Pick & Place PCB Installation")
    print("═" * 65)
    print()

    modbus = FactoryModbusClient()
    if not modbus.connect():
        print("  ❌ Cannot connect to Factory I/O!")
        sys.exit(1)

    mqtt = None
    try:
        from core.mqtt_client import MQTTClient
        mqtt = MQTTClient("station2")
        if mqtt.connect():
            print("  ✅ MQTT Connected")
        else:
            mqtt = None
    except Exception:
        mqtt = None
        print("  ⚠️  MQTT not available")

    station = Station2Controller(modbus, mqtt_client=mqtt)

    print("─" * 65)
    print("  Press Ctrl+C to stop")
    print("─" * 65)

    fault_thread = threading.Thread(
        target=fault_menu,
        args=(station,),
        daemon=True,
    )
    fault_thread.start()

    try:
        station.run()
    except KeyboardInterrupt:
        pass
    finally:
        station.stop()
        print(station.get_full_report())
        if mqtt:
            mqtt.disconnect()
        modbus.disconnect()


if __name__ == "__main__":
    main()