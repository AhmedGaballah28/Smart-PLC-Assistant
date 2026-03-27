"""
Run Station 1 with REAL Fault Effects
"""

import logging
import sys
import threading
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from factory.modbus_client import FactoryModbusClient
from factory.stations.station1 import Station1Controller


def fault_injection_menu(station: Station1Controller):
    """Background thread for fault injection commands."""
    print()
    print("  ┌──────────────────────────────────────────────────┐")
    print("  │  FAULT INJECTION — REAL Factory I/O Effects! ⚡   │")
    print("  │                                                   │")
    print("  │  f1 [sev] = Overheat   (1-3:stutter, 4-5:ESTOP) │")
    print("  │  f2 [sev] = Vibration  (3-4:chatter, 5:ESTOP)   │")
    print("  │  f3 [sev] = Power      (1-4:brownout, 5:ESTOP)  │")
    print("  │  f4 [sev] = Belt Slip  (belt stops randomly)     │")
    print("  │  f5 [sev] = Sensor     (wrong control decisions) │")
    print("  │                                                   │")
    print("  │  fc = Clear ALL faults (+ clear emergency)       │")
    print("  │  fe = Show fault effects summary                 │")
    print("  │  st = Print full status JSON                     │")
    print("  │  rp = Print full report                          │")
    print("  │                                                   │")
    print("  │  Example: f1 3  (overheat severity 3 → stutters) │")
    print("  │  Example: f3 5  (power severity 5 → ESTOP!)     │")
    print("  └──────────────────────────────────────────────────┘")
    print()

    while station.is_running:
        try:
            cmd = input()
            cmd = cmd.strip().lower()

            if cmd.startswith("f1"):
                parts = cmd.split()
                severity = int(parts[1]) if len(parts) > 1 else 3
                station.inject_fault("overheat", severity)

            elif cmd.startswith("f2"):
                parts = cmd.split()
                severity = int(parts[1]) if len(parts) > 1 else 3
                station.inject_fault("vibration", severity)

            elif cmd.startswith("f3"):
                parts = cmd.split()
                severity = int(parts[1]) if len(parts) > 1 else 3
                station.inject_fault("power", severity)

            elif cmd.startswith("f4"):
                parts = cmd.split()
                severity = int(parts[1]) if len(parts) > 1 else 3
                station.inject_fault("belt_slip", severity)

            elif cmd.startswith("f5"):
                parts = cmd.split()
                severity = int(parts[1]) if len(parts) > 1 else 3
                station.inject_fault("sensor_drift", severity)

            elif cmd == "fc":
                station.clear_fault("all")

            elif cmd == "fe":
                fc = station._fault_counters
                print()
                print("  ⚡ REAL FAULT EFFECTS SUMMARY:")
                print(f"     Belt Stutters:    {fc['stutters']}")
                print(f"     Power Brownouts:  {fc['brownouts']}")
                print(f"     Blade Chatters:   {fc['blade_chatters']}")
                print(f"     Emergency Stops:  {fc['emergency_stops']}")
                print(f"     Sensor Misreads:  {fc['sensor_misreads']}")
                print(f"     Fault Downtime:   {fc['total_fault_downtime']:.1f}s")
                if station._emergency_active:
                    print(f"     🚨 EMERGENCY: {station._emergency_reason}")
                print()

            elif cmd == "st":
                import json
                print(json.dumps(station.get_status(), indent=2))

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
    print("  📺 TV ASSEMBLY LINE — STATION 1")
    print("  ⚡ REAL Fault Effects Enabled!")
    print("═" * 65)
    print()

    # Connect to Factory I/O
    modbus = FactoryModbusClient()
    if not modbus.connect():
        print("  ❌ Cannot connect to Factory I/O!")
        sys.exit(1)

    # Optional MQTT
    mqtt = None
    try:
        from core.mqtt_client import MQTTClient
        mqtt = MQTTClient("station1")
        if mqtt.connect():
            print("  ✅ MQTT Connected")
        else:
            mqtt = None
            print("  ⚠️  MQTT not available (running without)")
    except Exception:
        mqtt = None
        print("  ⚠️  MQTT not available (running without)")

    # Create controller
    station = Station1Controller(modbus, mqtt_client=mqtt)

    print()
    print("─" * 65)
    print("  Press Ctrl+C to stop")
    print("─" * 65)

    # Start fault menu in background
    fault_thread = threading.Thread(
        target=fault_injection_menu,
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