"""
Fault Injection Tool — REAL Factory I/O Effects!
Run this in a SEPARATE terminal while Station 1 is running.
Sends fault commands via MQTT → Station controller triggers REAL Modbus writes.
"""

import json
import time
import sys
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.WARNING)

from core.mqtt_client import MQTTClient


# ═══════════════════════════════════════════════════════
# Severity → Real Effect mapping
# ═══════════════════════════════════════════════════════
FAULT_INFO = {
    "overheat": {
        "name": "🔥 Motor Overheating",
        "effects": {
            1: "Belt stutters ~1 every 17s (0.4s pause)",
            2: "Belt stutters ~1 every 8s  (0.6s pause)",
            3: "Belt stutters ~1 every 6s  (0.8s pause)",
            4: "🚨 EMERGENCY STOP — line goes DEAD!",
            5: "🚨 EMERGENCY STOP — line goes DEAD!",
        },
        "real": True,
    },
    "vibration": {
        "name": "📳 Vibration Anomaly",
        "effects": {
            1: "Simulated vibration (MQTT dashboard only)",
            2: "Simulated vibration (MQTT dashboard only)",
            3: "Blade CHATTERS randomly in Factory I/O",
            4: "Blade CHATTERS frequently in Factory I/O",
            5: "🚨 EMERGENCY STOP — line goes DEAD!",
        },
        "real": True,
    },
    "power": {
        "name": "⚡ Power Fluctuation",
        "effects": {
            1: "Random BROWNOUTS (~0.7s, everything OFF)",
            2: "Random BROWNOUTS (~1.1s, everything OFF)",
            3: "Random BROWNOUTS (~1.5s, everything OFF)",
            4: "Frequent BROWNOUTS (~1.9s, everything OFF)",
            5: "🚨 TOTAL POWER FAILURE — line goes DEAD!",
        },
        "real": True,
    },
    "belt_slip": {
        "name": "🔄 Belt Slippage",
        "effects": {
            1: "Belt stops randomly (~0.3s pauses)",
            2: "Belt stops randomly (~0.5s pauses)",
            3: "Belt stops frequently (~0.6s pauses)",
            4: "Belt stops very often (~0.8s pauses)",
            5: "Belt stops constantly (~1.0s pauses)",
        },
        "real": True,
    },
    "sensor_drift": {
        "name": "📡 Sensor Drift",
        "effects": {
            1: "5% sensor misread rate → occasional wrong decisions",
            2: "10% misread rate → belt/blade act unpredictably",
            3: "15% misread rate → frequent wrong decisions",
            4: "20% misread rate → very unreliable control",
            5: "25% misread rate → nearly random behavior!",
        },
        "real": True,
    },
}

SEVERITY_LABELS = {
    1: "Minor",
    2: "Low",
    3: "Medium",
    4: "High ⚠️",
    5: "CRITICAL 🚨",
}


def print_menu():
    print()
    print("═" * 64)
    print("  🧪 FAULT INJECTION TOOL — REAL Factory I/O Effects! ⚡")
    print("═" * 64)
    print()
    print("  INJECT FAULTS (all cause REAL visible effects!):")
    print("  ─────────────────────────────────────────────────")
    print("  1 [sev] → Overheat     (1-3: stutter, 4-5: ESTOP)")
    print("  2 [sev] → Vibration    (3-4: chatter, 5: ESTOP)")
    print("  3 [sev] → Power        (1-4: brownout, 5: ESTOP)")
    print("  4 [sev] → Belt Slip    (belt stops randomly)")
    print("  5 [sev] → Sensor Drift (wrong control decisions)")
    print()
    print("  CONTROLS:")
    print("  ─────────────────────────────────────────────────")
    print("  c  → Clear ALL faults (+ clear emergency stop)")
    print("  s  → Show current station status")
    print("  e  → Show fault effects summary")
    print("  h  → Show this menu again")
    print("  q  → Quit")
    print()
    print("  SEVERITY GUIDE:")
    print("  ─────────────────────────────────────────────────")
    print("  1 = Minor     (rare, small effect)")
    print("  2 = Low       (occasional effect)")
    print("  3 = Medium    (frequent effect)")
    print("  4 = High ⚠️    (very frequent / EMERGENCY)")
    print("  5 = CRITICAL 🚨 (constant / EMERGENCY STOP)")
    print()
    print("  EXAMPLES:")
    print("  ─────────────────────────────────────────────────")
    print("  Type: 1 3   → overheat sev 3 (belt stutters)")
    print("  Type: 3 5   → power sev 5 (EMERGENCY STOP!)")
    print("  Type: c     → clear all faults, resume line")
    print()


def main():
    print_menu()

    # Connect to MQTT
    mqtt = MQTTClient("fault_injector")
    if not mqtt.connect():
        print("  ❌ Cannot connect to MQTT!")
        print("  Make sure Mosquitto is running")
        sys.exit(1)
    print("  ✅ Connected to MQTT")
    print()

    # ─── Subscribe to station updates ───
    station_status = {"last_status": None}
    fault_effects = {"last_effects": None}

    def on_status(topic, data):
        station_status["last_status"] = data

    def on_fault_effect(topic, data):
        """Show real-time fault effects as they happen."""
        if isinstance(data, str):
            data = json.loads(data)
        effect = data.get("effect", "?")
        reason = data.get("reason", "")
        duration = data.get("duration", 0)
        writes = data.get("real_modbus_writes", [])

        print()
        print(f"  ⚡ REAL EFFECT TRIGGERED in Factory I/O!")
        print(f"     Type: {effect} {f'({reason})' if reason else ''}")
        print(f"     Duration: {duration:.2f}s")
        print(f"     Modbus writes: {', '.join(writes)}")
        print()

    def on_emergency(topic, data):
        if isinstance(data, str):
            data = json.loads(data)
        if data.get("active"):
            print()
            print("  🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨")
            print("  🚨  EMERGENCY STOP ACTIVATED!")
            print(f"  🚨  Reason: {data.get('reason', '?')}")
            print(f"  🚨  {data.get('details', '')}")
            print("  🚨  Factory I/O: LINE IS DEAD!")
            print("  🚨  Type 'c' to clear and resume")
            print("  🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨🚨")
            print()

    def on_fault_injected(topic, data):
        if isinstance(data, str):
            data = json.loads(data)
        real = data.get("real_effects", False)
        if real:
            print(f"  ✅ Station confirmed: REAL effects active")

    def on_fault_cleared(topic, data):
        if isinstance(data, str):
            data = json.loads(data)
        print(f"  ✅ Station confirmed: fault cleared ({data.get('fault_type', '?')})")

    mqtt.subscribe("factory/station1/status", on_status)
    mqtt.subscribe("factory/station1/fault_effect", on_fault_effect)
    mqtt.subscribe("factory/station1/emergency", on_emergency)
    mqtt.subscribe("factory/station1/fault_injected", on_fault_injected)
    mqtt.subscribe("factory/station1/fault_cleared", on_fault_cleared)

    # ─── Fault key mapping ───
    fault_keys = {
        "1": "overheat",
        "2": "vibration",
        "3": "power",
        "4": "belt_slip",
        "5": "sensor_drift",
    }

    try:
        while True:
            cmd = input("  🧪 Command > ").strip().lower()

            if not cmd:
                continue

            # ─── QUIT ───
            if cmd == "q":
                print("  Bye!")
                break

            # ─── HELP ───
            elif cmd == "h":
                print_menu()

            # ─── CLEAR FAULTS ───
            elif cmd == "c":
                mqtt.publish("factory/faults/inject", {
                    "action": "clear",
                    "fault_type": "all",
                })
                print()
                print("  ✅ Clear ALL faults command sent!")
                print("  ✅ Emergency stop will be cleared if active")
                print("  ✅ Line will resume from where it stopped")
                print()

            # ─── SHOW STATUS ───
            elif cmd == "s":
                if station_status["last_status"]:
                    s = station_status["last_status"]
                    if isinstance(s, str):
                        s = json.loads(s)

                    print()
                    print("  ┌───────────────────────────────────────────────┐")
                    print(f"  │  State: {s.get('state', '?'):38s}│")

                    if s.get("emergency_active"):
                        reason = s.get("emergency_reason", "?")[:36]
                        print(f"  │  🚨 EMERGENCY: {reason:30s}│")

                    sensors = s.get("sensors", {})
                    print(f"  │  Temp:     {sensors.get('motor_temperature', '?'):>6}°C"
                          f"                          │")
                    print(f"  │  Vibr:     {sensors.get('vibration', '?'):>6} mm/s"
                          f"                       │")
                    print(f"  │  Power:    {sensors.get('power_consumption', '?'):>6} kW"
                          f"                         │")
                    print(f"  │  Belt Spd: {sensors.get('belt_speed', '?'):>6}%"
                          f"                           │")

                    faults = s.get("faults", {})
                    if faults.get("has_fault"):
                        active = faults.get("active_faults", [])
                        print(f"  │  ⚠️  FAULTS: {len(active)} active"
                              f"                          │")
                        for f in active:
                            print(f"  │    • {f:39s}│")
                    else:
                        print(f"  │  ✅ No active faults"
                              f"                          │")

                    # Show real effects counters
                    fx = s.get("fault_effects", {})
                    counters = fx.get("counters", {})
                    if any(v > 0 for v in counters.values()
                           if isinstance(v, (int, float))):
                        print(f"  │                                               │")
                        print(f"  │  ⚡ REAL EFFECTS:                              │")
                        print(f"  │    Stutters:  {counters.get('stutters', 0):>4}"
                              f"   Brownouts: {counters.get('brownouts', 0):>4}"
                              f"          │")
                        print(f"  │    Chatters:  {counters.get('blade_chatters', 0):>4}"
                              f"   E-Stops:   {counters.get('emergency_stops', 0):>4}"
                              f"          │")
                        print(f"  │    Misreads:  {counters.get('sensor_misreads', 0):>4}"
                              f"   Downtime:  "
                              f"{counters.get('total_fault_downtime', 0):>5.1f}s"
                              f"       │")

                    cnts = s.get("counters", {})
                    print(f"  │                                               │")
                    print(f"  │  Products: {cnts.get('products_completed', '?')}"
                          f"   OEE: {s.get('oee', {}).get('oee', '?')}%"
                          f"                     │")
                    print(f"  └───────────────────────────────────────────────┘")
                    print()
                else:
                    print("  ⚠️  No status received yet (wait a moment)")
                    print()

            # ─── SHOW FAULT EFFECTS ───
            elif cmd == "e":
                if station_status["last_status"]:
                    s = station_status["last_status"]
                    if isinstance(s, str):
                        s = json.loads(s)
                    fx = s.get("fault_effects", {})
                    counters = fx.get("counters", {})
                    events = fx.get("recent_events", [])

                    print()
                    print("  ⚡ REAL FAULT EFFECTS SUMMARY:")
                    print("  ─────────────────────────────────────")
                    print(f"     Belt Stutters:    {counters.get('stutters', 0)}"
                          f"  (belt stopped in Factory I/O)")
                    print(f"     Power Brownouts:  {counters.get('brownouts', 0)}"
                          f"  (all outputs OFF)")
                    print(f"     Blade Chatters:   {counters.get('blade_chatters', 0)}"
                          f"  (blade flipped)")
                    print(f"     Emergency Stops:  {counters.get('emergency_stops', 0)}"
                          f"  (line went DEAD)")
                    print(f"     Sensor Misreads:  {counters.get('sensor_misreads', 0)}"
                          f"  (wrong decisions)")
                    print(f"     Fault Downtime:   "
                          f"{counters.get('total_fault_downtime', 0):.1f}s")

                    if fx.get("emergency_active"):
                        print()
                        print("     🚨 EMERGENCY STOP IS ACTIVE!")
                        print("     Type 'c' to clear")

                    if events:
                        print()
                        print("  📋 RECENT EVENTS:")
                        for ev in events[-5:]:
                            t = ev.get("time", "?")
                            if "T" in str(t):
                                t = t.split("T")[1][:8]
                            print(f"     {t} │ {ev.get('type', '?')}: "
                                  f"{ev.get('details', '')}")

                    print()
                else:
                    print("  ⚠️  No status received yet")
                    print()

            # ─── INJECT FAULT ───
            else:
                parts = cmd.split()
                fault_key = parts[0]
                severity = int(parts[1]) if len(parts) > 1 else 3

                if fault_key not in fault_keys:
                    print(f"  ❌ Unknown: {cmd}")
                    print("  Use 1-5 for faults, c/s/e/h/q for controls")
                    continue

                fault_type = fault_keys[fault_key]
                severity = max(1, min(5, severity))
                info = FAULT_INFO[fault_type]
                effect_desc = info["effects"][severity]
                level = SEVERITY_LABELS[severity]

                # Send via MQTT
                mqtt.publish("factory/faults/inject", {
                    "action": "inject",
                    "fault_type": fault_type,
                    "severity": severity,
                    "station": "station_1",
                })

                print()
                print(f"  🚨 ═══════════════════════════════════════════")
                print(f"  🚨 FAULT INJECTED!")
                print(f"  🚨")
                print(f"  🚨 Type:     {info['name']}")
                print(f"  🚨 Severity: {severity}/5 ({level})")
                print(f"  🚨")
                print(f"  🚨 ⚡ REAL EFFECT in Factory I/O:")
                print(f"  🚨 {effect_desc}")

                if severity >= 4 and fault_type in ("overheat", "power"):
                    print(f"  🚨")
                    print(f"  🚨 ⚠️  This will STOP the entire line!")
                    print(f"  🚨 ⚠️  Type 'c' to clear and resume")
                elif severity >= 5 and fault_type == "vibration":
                    print(f"  🚨")
                    print(f"  🚨 ⚠️  This will STOP the entire line!")
                    print(f"  🚨 ⚠️  Type 'c' to clear and resume")

                print(f"  🚨 ═══════════════════════════════════════════")
                print()

    except KeyboardInterrupt:
        print("\n  Bye!")

    finally:
        mqtt.disconnect()


if __name__ == "__main__":
    main()