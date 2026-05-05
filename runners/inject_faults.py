"""
Fault Injection Tool for Twin Assembly Lines
=============================================
Sends fault commands via MQTT to a running run_twin.py instance.

Usage:
  python runners/inject_faults.py                  → Interactive menu
  python runners/inject_faults.py --scenario 1     → Run Scenario 1 (Thermal)
  python runners/inject_faults.py --scenario 2     → Run Scenario 2 (Pneumatic)
  python runners/inject_faults.py --scenario 3     → Run Scenario 3 (Power Grid)
  python runners/inject_faults.py --scenario 4     → Run Scenario 4 (Mechanical)
  python runners/inject_faults.py --cmd "1Af1 3"   → Single fault command
  python runners/inject_faults.py --clear           → Clear all faults

Requirements:
  - run_twin.py must be running in another terminal
  - Mosquitto MQTT broker must be running
"""

import json
import time
import sys
import argparse
import threading
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.mqtt_client import MQTTClient


# ═══════════════════════════════════════════════════════════════
# COMMAND PARSING — same logic as run_twin.py fault_console
# ═══════════════════════════════════════════════════════════════

STATION_FAULTS = {
    "A": {"1": "overheat", "3": "power", "4": "cnc_jam",
          "5": "sensor_drift", "6": "material_error"},
    "B": {"1": "overheat", "3": "power", "4": "cnc_jam",
          "5": "sensor_drift", "6": "material_error"},
    "1": {"1": "overheat", "2": "vibration", "3": "power",
          "4": "belt_slip", "5": "sensor_drift"},
    "2": {"1": "overheat", "3": "power", "4": "belt_slip",
          "5": "sensor_drift", "6": "gripper", "7": "pp_jam"},
    "3": {"1": "overheat", "3": "power", "4": "belt_slip",
          "5": "sensor_drift", "6": "positioner_jam"},
    "6": {"1": "overheat", "3": "power", "4": "belt_slip",
          "5": "sensor_drift", "6": "vision_error"},
    "7": {"1": "overheat", "3": "power", "4": "belt_slip",
          "5": "sensor_drift", "6": "sorter_jam", "7": "misroute"},
    "8": {"1": "overheat", "3": "power", "4": "belt_slip",
          "5": "sensor_drift", "6": "pp2_jam", "7": "grab_failure"},
    "9": {"1": "overheat", "3": "power", "4": "crane_drift",
          "5": "sensor_drift", "6": "fork_jam"},
}

STATION_KEY_MAP = {
    "A": "mc_a", "B": "mc_b",
    "1": "stn1", "2": "stn2", "3": "stn3",
    "6": "stn6", "7": "stn7",
    "8": "transfer", "9": "warehouse",
}

STATION_NAMES = {
    "A": "MC-A", "B": "MC-B",
    "1": "Station 1", "2": "Station 2", "3": "Station 3",
    "6": "Station 6 (QC)", "7": "Station 7 (Sorting)",
    "8": "Transfer", "9": "Warehouse",
}


def parse_command(cmd_str):
    """Parse shorthand like '1Af1 3' into (line_id, station_key, fault_type, severity)."""
    parts = cmd_str.strip().split()
    code = parts[0]
    sev = int(parts[1]) if len(parts) > 1 else 3

    line_num = code[0]
    if line_num not in ("1", "2"):
        raise ValueError(f"Line must be 1 or 2, got '{line_num}'")
    line_id = "line1" if line_num == "1" else "line2"

    f_idx = code.find("f", 1)
    if f_idx < 0:
        raise ValueError(f"No 'f' separator in '{code}'")

    stn_code = code[1:f_idx].upper()
    fault_code = code[f_idx + 1:]

    stn_key = STATION_KEY_MAP.get(stn_code)
    if not stn_key:
        raise ValueError(f"Unknown station '{stn_code}'")

    fault_type = STATION_FAULTS.get(stn_code, {}).get(fault_code)
    if not fault_type:
        raise ValueError(f"Unknown fault 'f{fault_code}' for station '{stn_code}'")

    sev = max(1, min(5, sev))
    return line_id, stn_key, fault_type, sev


def send_fault(mqtt, line_id, station_key, fault_type, severity):
    """Send a fault injection command via MQTT."""
    topic = f"factory/{line_id}/{station_key}/faults/inject"
    payload = {"fault": fault_type, "severity": severity}
    mqtt.publish(topic, payload)


def send_clear_all(mqtt):
    """Send clear-all command via MQTT."""
    mqtt.publish("factory/faults/inject", {"clear": "all"})


# ═══════════════════════════════════════════════════════════════
# SCENARIOS — from fault scenarios.txt
# ═══════════════════════════════════════════════════════════════

SCENARIOS = {
    1: {
        "name": "Cooling System Failure - Thermal Cascade (Line 1)",
        "story": (
            "Line 1 chiller loses refrigerant. Spindles heat up first,\n"
            "  then heat spreads through enclosed cabinets to downstream stations.\n"
            "  Line 2 stays healthy - agent should notice the asymmetry."
        ),
        "steps": [
            ("1Af1 1", "MC-A spindle bearing preload shift - slight warmth, 15% slower"),
            ("1Bf1 1", "MC-B follows - both machining centers warming"),
            ("1Af1 3", "MC-A escalates to 55C - thermal compensation active, 60% slower"),
            ("1Bf1 3", "MC-B same - both machining centers now visibly degraded"),
            ("11f1 2", "Station 1 belt motor cabinet at 45C - fan 100%, 25% slower"),
            ("12f1 3", "Station 2 stepper missing steps - assembly significantly slower"),
            ("12f6 2", "Gripper vacuum cup softening from heat - vacuum level dropping"),
            ("16f1 3", "QC vision CPU throttling at 85C - frame rate drops to 15fps"),
            ("16f6 2", "Vision focus drifting from thermal expansion - wrong classifications"),
            ("1Af1 5", "MC-A CRITICAL: approaching bearing seizure - 2.5x cycle time"),
            ("17f1 3", "Sorting actuator seal expanding - arm sluggish"),
        ],
    },
    2: {
        "name": "Contaminated Compressed Air - Pneumatic Collapse (Line 2)",
        "story": (
            "Air dryer desiccant on Line 2 saturates. Moisture enters pneumatic\n"
            "  lines, affecting every station with cylinders, grippers, or valves.\n"
            "  Line 1 has its own air supply and stays clean."
        ),
        "steps": [
            ("22f3 2", "Assembly pneumatic pressure oscillating +/-0.3 bar"),
            ("22f6 1", "Gripper vacuum cup seal time increasing - still grips"),
            ("23f6 2", "Panel positioner cylinder rod scoring from moisture - jerky motion"),
            ("22f6 3", "Gripper venturi build time doubled - moisture in vacuum line"),
            ("27f7 2", "Sorting 5/2 valve spring weakened - doesn't fully return"),
            ("22f7 2", "Assembly PP guide lubrication contaminated - friction rising"),
            ("23f6 4", "Positioner cylinder seal extruded - bar won't clamp"),
            ("27f6 3", "Sorting pivot bearing grease contaminated - arm sticks randomly"),
            ("28f7 3", "Transfer grab vacuum line restricted - grip limited to 5 seconds"),
            ("22f6 5", "Assembly gripper CRITICAL: cup torn - cannot maintain grip"),
            ("27f7 4", "Sorting valve pilot pressure too low - arm goes unpredictably"),
        ],
    },
    3: {
        "name": "Power Grid Instability - Both Lines Simultaneously",
        "story": (
            "Neighboring factory starts 500kW motor. Voltage sags hit the shared\n"
            "  transformer feeding both lines. Some stations ride through,\n"
            "  others cascade into sensor drift from electrical noise."
        ),
        "steps": [
            ("1Af3 2", "Line 1 MC-A VFD bus capacitor ESR rising - 5% ripple"),
            ("2Af3 2", "Line 2 MC-A same - confirms grid-wide"),
            ("11f3 2", "Line 1 Station 1 PSU terminal resistance rising"),
            ("21f3 2", "Line 2 Station 1 same"),
            ("16f3 3", "Line 1 QC LED driver PWM fault - lighting inconsistent"),
            ("26f3 3", "Line 2 QC same - inspection lighting flickering"),
            ("11f5 2", "Line 1 Station 1 sensor LED aging from voltage stress"),
            ("21f5 2", "Line 2 Station 1 same - sensors drifting from noise"),
            ("16f6 3", "Line 1 QC vision errors - lighting instability causes wrong reads"),
            ("26f6 3", "Line 2 QC same - both lines failing quality checks"),
            ("1Af3 4", "Line 1 MC-A VFD frequent bus dips - drive faults"),
            ("2Af3 4", "Line 2 MC-A same - machining centers struggling"),
            ("19f3 3", "Line 1 warehouse regen resistor - bus ripple during lowering"),
            ("29f3 3", "Line 2 warehouse same"),
            ("17f3 3", "Line 1 sorting valve coil partial short from voltage spikes"),
        ],
    },
    4: {
        "name": "End-of-Shift Mechanical Wear - Chain Reaction (Line 1)",
        "story": (
            "After 8 hours of continuous production, worn mechanical components\n"
            "  on Line 1 start failing in sequence. Belt slip causes misalignment,\n"
            "  debris contaminates downstream sensors, jams cascade backward."
        ),
        "steps": [
            ("11f2 2", "Station 1 roller bearing BPFO defect - vibration 18mm/s"),
            ("11f4 2", "Station 1 belt tension low from spring fatigue - products hesitate"),
            ("12f4 3", "Station 2 belt joint opening - regular stuttering, products jerk"),
            ("11f2 4", "Station 1 bearing cage wear - blade chatters, products misaligned"),
            ("12f7 2", "Assembly PP guide lubrication thickening - friction increasing"),
            ("13f6 2", "Panel positioner cylinder rod scoring - jerky bar motion"),
            ("16f4 3", "QC belt contaminated with oil from upstream - products sliding"),
            ("16f5 3", "QC sensor reflector degraded by debris - occasional misses"),
            ("16f6 4", "Vision lens coated with particles - glare causes misreads"),
            ("17f6 3", "Sorting pivot bearing grease broken down - arm sticks randomly"),
            ("17f7 3", "Sorting valve spool contaminated - random routing errors"),
            ("19f6 2", "Warehouse fork chain stretching - fork hesitates during extension"),
        ],
    },
}


# ═══════════════════════════════════════════════════════════════
# SCENARIO RUNNER
# ═══════════════════════════════════════════════════════════════

def run_scenario(mqtt, scenario_num, delay=60, stop_event=None):
    """Run a full scenario with timed delays between steps."""
    scenario = SCENARIOS[scenario_num]

    print()
    print("=" * 70)
    print(f"  SCENARIO {scenario_num}: {scenario['name']}")
    print("=" * 70)
    print(f"  {scenario['story']}")
    print(f"  Steps: {len(scenario['steps'])}   Delay: {delay}s between each")
    print("=" * 70)
    print()

    for i, (cmd, description) in enumerate(scenario["steps"]):
        if stop_event and stop_event.is_set():
            print("\n  [ABORTED]")
            return

        line_id, stn_key, fault_type, sev = parse_command(cmd)

        print(f"  Step {i+1}/{len(scenario['steps'])}: {cmd}")
        print(f"    -> {line_id}/{stn_key}: {fault_type} severity {sev}")
        print(f"    -> {description}")

        send_fault(mqtt, line_id, stn_key, fault_type, sev)

        if i < len(scenario["steps"]) - 1:
            print(f"    ... waiting {delay}s ", end="", flush=True)
            for sec in range(delay):
                if stop_event and stop_event.is_set():
                    print(" [ABORTED]")
                    return
                time.sleep(1)
                if (sec + 1) % 10 == 0:
                    print(f"{sec+1}s ", end="", flush=True)
            print()

        print()

    print("=" * 70)
    print(f"  SCENARIO {scenario_num} COMPLETE")
    print(f"  Type 'fc' to clear all faults when done testing")
    print("=" * 70)
    print()


# ═══════════════════════════════════════════════════════════════
# INTERACTIVE MENU
# ═══════════════════════════════════════════════════════════════

def print_menu():
    print()
    print("=" * 70)
    print("  FAULT INJECTION TOOL - Twin Assembly Lines")
    print("=" * 70)
    print()
    print("  SCENARIOS (auto-inject with delays):")
    print("    s1  Scenario 1: Thermal Cascade (Line 1)")
    print("    s2  Scenario 2: Pneumatic Collapse (Line 2)")
    print("    s3  Scenario 3: Power Grid Instability (Both Lines)")
    print("    s4  Scenario 4: Mechanical Wear Chain Reaction (Line 1)")
    print()
    print("  SINGLE FAULT (same format as run_twin.py console):")
    print("    <line><station>f<fault> [severity]")
    print("    Examples: 1Af1 3   22f6 5   17f7 2   11f2 4")
    print()
    print("  STATIONS:  A=MC-A  B=MC-B  1-3=Stn1-3  6=QC  7=Sort  8=Transfer  9=Warehouse")
    print("  FAULTS:    f1=overheat  f2=vibration  f3=power  f4=belt/jam  f5=sensor  f6=mech  f7=valve")
    print("  SEVERITY:  1-5 (default 3)")
    print()
    print("  CONTROLS:")
    print("    fc        Clear ALL faults")
    print("    delay N   Set scenario delay to N seconds (default 60)")
    print("    h         Show this menu")
    print("    q         Quit")
    print()


def interactive(mqtt):
    """Interactive fault injection loop."""
    print_menu()

    scenario_delay = 60
    scenario_thread = None
    stop_event = threading.Event()

    while True:
        try:
            cmd = input("  > ").strip()
        except (EOFError, KeyboardInterrupt):
            break

        if not cmd:
            continue

        lower = cmd.lower()

        # Quit
        if lower == "q":
            stop_event.set()
            break

        # Help
        if lower == "h":
            print_menu()
            continue

        # Clear all
        if lower == "fc":
            stop_event.set()
            time.sleep(0.2)
            stop_event.clear()
            send_clear_all(mqtt)
            print("  All faults cleared")
            continue

        # Set delay
        if lower.startswith("delay "):
            try:
                scenario_delay = int(lower.split()[1])
                print(f"  Scenario delay set to {scenario_delay}s")
            except (IndexError, ValueError):
                print("  Usage: delay 60")
            continue

        # Scenarios
        if lower in ("s1", "s2", "s3", "s4"):
            num = int(lower[1])
            stop_event.clear()
            scenario_thread = threading.Thread(
                target=run_scenario,
                args=(mqtt, num, scenario_delay, stop_event),
                daemon=True,
            )
            scenario_thread.start()
            print(f"  Scenario {num} running in background. Type 'fc' to abort and clear.")
            continue

        # Single fault command
        try:
            line_id, stn_key, fault_type, sev = parse_command(cmd)
            send_fault(mqtt, line_id, stn_key, fault_type, sev)
            print(f"  Injected: {line_id}/{stn_key} -> {fault_type} severity {sev}")
        except ValueError as e:
            print(f"  Error: {e}")
            print("  Type 'h' for help")


# ═══════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Fault injection for twin assembly lines")
    parser.add_argument("--scenario", "-s", type=int, choices=[1, 2, 3, 4],
                        help="Run a scenario (1-4)")
    parser.add_argument("--cmd", "-c", type=str,
                        help="Single fault command (e.g. '1Af1 3')")
    parser.add_argument("--clear", action="store_true",
                        help="Clear all faults")
    parser.add_argument("--delay", "-d", type=int, default=60,
                        help="Seconds between scenario steps (default 60)")
    args = parser.parse_args()

    # Connect MQTT
    mqtt = MQTTClient("fault_injector")
    if not mqtt.connect():
        print("  Cannot connect to MQTT broker!")
        print("  Make sure Mosquitto is running: net start mosquitto")
        sys.exit(1)
    print("  Connected to MQTT broker")
    time.sleep(0.3)

    try:
        # --clear
        if args.clear:
            send_clear_all(mqtt)
            print("  All faults cleared")
            return

        # --cmd "1Af1 3"
        if args.cmd:
            line_id, stn_key, fault_type, sev = parse_command(args.cmd)
            send_fault(mqtt, line_id, stn_key, fault_type, sev)
            print(f"  Injected: {line_id}/{stn_key} -> {fault_type} severity {sev}")
            return

        # --scenario N
        if args.scenario:
            run_scenario(mqtt, args.scenario, args.delay)
            return

        # No args → interactive mode
        interactive(mqtt)

    except KeyboardInterrupt:
        print("\n  Interrupted")
    finally:
        send_clear_all(mqtt)
        time.sleep(0.3)
        mqtt.disconnect()
        print("  Done")


if __name__ == "__main__":
    main()
