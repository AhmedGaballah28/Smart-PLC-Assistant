"""
runners/run_warehouse_test.py

Warehouse Test
  PICKUP:  LEFT → LIFT → MIDDLE → LIFT OFF
  DEPOSIT: LIFT → RIGHT → LIFT OFF → MIDDLE
"""

import logging
import sys
import time
import threading
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from factory.modbus_client import FactoryModbusClient
from factory.stations.warehouse import WarehouseController

logger = logging.getLogger(__name__)


def show_sensors(wh):
    sensors = wh.read_all_sensors()
    print()
    print("  ┌─────────────────────────────────────────────────┐")
    print("  │              SENSOR STATUS                       │")
    print("  ├─────────────────────────────────────────────────┤")
    for name, value in sensors.items():
        icon = "🟢" if value else "⚫"
        addr = wh.IN.get(name, "?")
        print(f"  │  {icon}  {name:15s} = {str(value):5s} "
              f"  (Input {addr})  │")
    print("  └─────────────────────────────────────────────────┘")
    reg = wh.modbus.read_register(wh.REG['target_position'])
    print(f"  Target Position register: {reg}")
    print()


def io_test_mode(wh):
    states = {name: False for name in wh.OUT}
    ea_state = False
    xa_state = False

    actuator_map = {
        'em':  ('emitter',        wh.emitter),
        'er':  ('entry_roller',   wh.entry_roller),
        'el':  ('entry_loading',  wh.entry_loading),
        'cl':  ('crane_left',     wh.crane_left),
        'cr':  ('crane_right',    wh.crane_right),
        'li':  ('crane_lift',     wh.crane_lift),
        'xl':  ('exit_loading',   wh.exit_loading),
        'xr':  ('exit_roller',    wh.exit_roller),
        'rm':  ('remover',        wh.remover),
    }

    print()
    print("  ╔════════════════════════════════════════════════════════╗")
    print("  ║              IO TEST MODE                              ║")
    print("  ╠════════════════════════════════════════════════════════╣")
    print("  ║  em = Emitter    (0)   cl = Left   (3)  cr = Right (4) ║")
    print("  ║  er = Entry Roll (1)   li = Lift   (5)                 ║")
    print("  ║  el = Entry Load (2)   xl = Exit Load (6)              ║")
    print("  ║  ea = Entry ALL        xr = Exit Roll (7)              ║")
    print("  ║  xa = Exit ALL         rm = Remover   (8)              ║")
    print("  ║                                                         ║")
    print("  ║  tp <n> = Target (0=stop, 1-54=cell, 55=rest)          ║")
    print("  ║  fp = PICKUP   (LEFT→LIFT→MIDDLE→LIFT OFF)            ║")
    print("  ║  fd = STORE    (LIFT→RIGHT→LIFT OFF→MIDDLE)           ║")
    print("  ║  fr = RETRIEVE (LEFT→LIFT→MIDDLE→LIFT OFF)            ║")
    print("  ║  fw = PUTDOWN  (LIFT→RIGHT→LIFT OFF→MIDDLE)           ║")
    print("  ║  rr = Read register   s = Sensors   off = All OFF      ║")
    print("  ║  b = Back                                               ║")
    print("  ╚════════════════════════════════════════════════════════╝")
    print()

    while True:
        try:
            cmd = input("  io> ").strip().lower()
            if not cmd:
                continue
            if cmd == "b":
                wh.all_off(); return
            elif cmd == "s":
                show_sensors(wh)
            elif cmd == "off":
                wh.all_off()
                for k in states: states[k] = False
                ea_state = xa_state = False
                print("  🛑 All OFF")
            elif cmd == "rr":
                v = wh.modbus.read_register(wh.REG['target_position'])
                print(f"  📖 Register = {v}")
            elif cmd.startswith("tp"):
                parts = cmd.split()
                if len(parts) >= 2:
                    try:
                        pos = int(parts[1])
                        wh.set_target(pos)
                        labels = {0: "STOP", 55: "REST"}
                        print(f"  📍 Target → {pos} "
                              f"({labels.get(pos, f'cell {pos}')})")
                    except ValueError:
                        print("  Usage: tp <number>")
            elif cmd == "fp":
                print("  🔄 PICKUP: LEFT → LIFT → MIDDLE → LIFT OFF")
                wh.running = True
                wh._pickup_from_conveyor()
                wh.running = False
            elif cmd == "fd":
                print("  🔄 STORE: LIFT → RIGHT → LIFT OFF → MIDDLE")
                wh.running = True
                wh._store_into_rack()
                wh.running = False
            elif cmd == "fr":
                print("  🔄 RETRIEVE: LEFT → LIFT → MIDDLE → LIFT OFF")
                wh.running = True
                wh._retrieve_from_rack()
                wh.running = False
            elif cmd == "fw":
                print("  🔄 PUTDOWN: LIFT → RIGHT → LIFT OFF → MIDDLE")
                wh.running = True
                wh._putdown_onto_conveyor()
                wh.running = False
            elif cmd == "ea":
                ea_state = not ea_state
                wh.entry_all(ea_state)
                print(f"  {'🟢 ON' if ea_state else '⚫ OFF'}  Entry ALL")
            elif cmd == "xa":
                xa_state = not xa_state
                wh.exit_all(xa_state)
                print(f"  {'🟢 ON' if xa_state else '⚫ OFF'}  Exit ALL")
            elif cmd in actuator_map:
                name, fn = actuator_map[cmd]
                states[name] = not states[name]
                fn(states[name])
                icon = "🟢 ON" if states[name] else "⚫ OFF"
                addr = wh.OUT.get(name, "?")
                print(f"  {icon}  {name} (Coil {addr})")
            else:
                print(f"  Unknown: '{cmd}'")
        except (EOFError, KeyboardInterrupt):
            wh.all_off(); return


def guided_store(wh):
    cell = wh.next_cell
    if cell > wh.MAX_CELLS:
        print("  ❌ FULL!"); return

    print()
    print(f"  📦 GUIDED STORE — Cell {cell}")
    print(f"  PICKUP:  LEFT → LIFT → MIDDLE → LIFT OFF")
    print(f"  STORE:   LIFT → RIGHT → LIFT OFF → MIDDLE")
    print()

    def prompt():
        try:
            r = input("  [Enter=next, q=abort, s=sensors] ").strip().lower()
            if r == 'q': return False
            if r == 's': show_sensors(wh)
            return True
        except (EOFError, KeyboardInterrupt):
            return False

    def wait_sensor(fn, name, timeout, desc):
        print(f"  ⏳ {desc}...")
        start = time.time()
        while time.time() - start < timeout:
            if fn():
                print(f"  ✅ {name} ({time.time()-start:.1f}s)")
                return True
            time.sleep(0.2)
        print(f"  ⚠️ {name} timeout"); return False

    # ══════ PREPARE ══════
    print("  ═══ STEP 1: Emit ═══")
    wh.emitter(True); time.sleep(0.5); wh.emitter(False)
    print("  ✅ Created")
    if not prompt(): wh.all_off(); return

    print("  ═══ STEP 2: Crane → REST ═══")
    wh.set_target(55); time.sleep(1)
    wait_sensor(lambda: not wh.crane_busy(), "crane", 30, "rest")
    if not prompt(): wh.all_off(); return

    print("  ═══ STEP 3: Forks? ═══")
    wh.crane_lift(False)
    if not wh.middle_limit():
        wh.crane_left(False); wh.crane_right(False)
        wait_sensor(wh.middle_limit, "middle", 10, "retract")
    else:
        print("  ✅ At middle")
    if not prompt(): wh.all_off(); return

    # ══════ PRODUCT TO PLATFORM ══════
    print("  ═══ STEP 4: Entry ON ═══")
    wh.entry_all(True)
    if not prompt(): wh.all_off(); return

    print("  ═══ STEP 5: Wait entry ═══")
    wait_sensor(wh.entry_sensor, "entry", 20, "entry sensor")
    if not prompt(): wh.all_off(); return

    print("  ═══ STEP 6: Push + stop ═══")
    time.sleep(2.0); wh.entry_all(False)
    print("  ✅ On platform")
    if not prompt(): wh.all_off(); return

    # ══════ PICKUP ══════
    print()
    print("  ★ PICKUP: LEFT → LIFT → MIDDLE → LIFT OFF")

    print("  ═══ STEP 7: LEFT (under product) ═══")
    wh.crane_left(True)
    wait_sensor(wh.left_limit, "left", 10, "left")
    if not prompt(): wh.all_off(); return

    print("  ═══ STEP 8: LIFT ON (lift off conveyor) ═══")
    wh.crane_lift(True); time.sleep(1.0)
    if not prompt(): wh.all_off(); return

    print("  ═══ STEP 9: MIDDLE (retract with product) ═══")
    wh.crane_left(False)
    wait_sensor(wh.middle_limit, "middle", 10, "middle")
    if not prompt(): wh.all_off(); return

    print("  ═══ STEP 10: LIFT OFF ═══")
    wh.crane_lift(False); time.sleep(0.5)
    print("  ✅ Product on forks!")
    if not prompt(): wh.all_off(); return

    # ══════ MOVE ══════
    print()
    print(f"  ★ CRANE → CELL {cell}")

    print(f"  ═══ STEP 11: Target = {cell} ═══")
    if not wh.set_target(cell):
        print("  ❌ Failed!"); wh.all_off(); return
    if not prompt(): wh.all_off(); return

    print("  ═══ STEP 12: Wait crane ═══")
    time.sleep(1)
    print(f"  X={wh.moving_x()} Z={wh.moving_z()}")
    wait_sensor(lambda: not wh.crane_busy(), "crane", 30, "arrive")
    if not prompt(): wh.all_off(); return

    # ══════ STORE INTO RACK ══════
    print()
    print("  ★ STORE: LIFT → RIGHT → LIFT OFF → MIDDLE")

    print("  ═══ STEP 13: LIFT ON (raise above beams) ═══")
    wh.crane_lift(True); time.sleep(1.0)
    print("  ✅ Product above shelf level")
    if not prompt(): wh.all_off(); return

    print("  ═══ STEP 14: RIGHT (extend into cell) ═══")
    wh.crane_right(True)
    wait_sensor(wh.right_limit, "right", 10, "right")
    print("  ✅ Product in cell (above beams)")
    if not prompt(): wh.all_off(); return

    print("  ═══ STEP 15: LIFT OFF (lower — product on beams) ═══")
    wh.crane_lift(False); time.sleep(0.5)
    print("  ✅ Product resting on shelf beams, forks below")
    if not prompt(): wh.all_off(); return

    print("  ═══ STEP 16: MIDDLE (retract — slide out) ═══")
    wh.crane_right(False)
    wait_sensor(wh.middle_limit, "middle", 10, "middle")
    print("  ✅ Forks out — product stays on shelf!")
    if not prompt(): wh.all_off(); return

    # ══════ HOME ══════
    print("  ═══ STEP 17: Crane → rest ═══")
    wh.set_target(55); time.sleep(1)
    wait_sensor(lambda: not wh.crane_busy(), "crane", 30, "rest")

    wh.occupied.add(cell)
    wh.last_cell_used = cell
    wh.next_cell = cell + 1
    wh.products_stored += 1

    print()
    print(f"  ✅✅✅ Cell {cell} STORED!")
    print(f"  📦 {len(wh.occupied)}/{wh.MAX_CELLS}")
    print()


def auto_store_mode(wh):
    print()
    print("  🔄 AUTO STORE")
    print("  PICKUP:  LEFT → LIFT → MIDDLE → LIFT OFF")
    print("  DEPOSIT: LIFT → RIGHT → LIFT OFF → MIDDLE")
    print("  Press Enter to stop.")
    print()

    wh.running = True
    thread = threading.Thread(
        target=lambda: wh.main(use_emitter=True),
        daemon=True,
    )
    thread.start()

    try:
        input("  >>> Press Enter to STOP... ")
    except (EOFError, KeyboardInterrupt):
        pass

    wh.running = False
    thread.join(timeout=10)
    wh.all_off()
    print(wh.get_full_report())


def scan_addresses(modbus):
    print()
    print("  🔍 INPUTS (0-9):")
    for addr in range(10):
        try:
            result = modbus.read_inputs(addr, 1)
            if result and len(result) > 0:
                val = bool(result[0])
                icon = "🟢 TRUE " if val else "⚫ false"
                print(f"    Input {addr}: {icon}")
        except Exception:
            pass
    print()
    print("  🔍 REGISTERS (0-4):")
    for addr in range(5):
        try:
            result = modbus.read_register(addr)
            print(f"    Reg {addr}: {result}")
        except Exception as e:
            print(f"    Reg {addr}: ERROR ({e})")
    print()


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    print()
    print("═" * 60)
    print("  🏭 WAREHOUSE TEST — 3 Racks (54 Cells)")
    print("  PICKUP:  LEFT → LIFT → MIDDLE → LIFT OFF")
    print("  DEPOSIT: LIFT → RIGHT → LIFT OFF → MIDDLE")
    print("═" * 60)
    print()

    modbus = FactoryModbusClient()
    if not modbus.connect():
        print("  ❌ Cannot connect!"); sys.exit(1)

    print("  ✅ Connected!")
    if not hasattr(modbus, 'write_register'):
        print("  ❌ write_register() missing!"); modbus.disconnect(); sys.exit(1)
    print("  ✅ write_register() found")

    wh = WarehouseController(modbus)
    sensors = wh.read_all_sensors()
    active = [k for k, v in sensors.items() if v]
    if active:
        print(f"  Active sensors: {', '.join(active)}")
    else:
        print("  ⚠️ No sensors — scene PLAYING?")
    reg = modbus.read_register(0)
    print(f"  Register 0: {reg}")
    print()

    while True:
        print("  ╔══════════════════════════════════════════════╗")
        print("  ║         WAREHOUSE TEST MENU                  ║")
        print("  ╠══════════════════════════════════════════════╣")
        print("  ║  0 = Register Test                           ║")
        print("  ║  1 = IO Test                                 ║")
        print("  ║  2 = Guided Store                            ║")
        print("  ║  3 = Auto Store                              ║")
        print("  ║  4 = Retrieve                                ║")
        print("  ║  5 = Scan                                    ║")
        print("  ║  6 = Report                                  ║")
        print("  ║  s = Sensors       q = Quit                  ║")
        print("  ╚══════════════════════════════════════════════╝")

        try:
            c = input("  > ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            break

        if c == "q": break
        elif c == "0":
            wh.running = True; wh.test_register(); wh.running = False
        elif c == "1": io_test_mode(wh)
        elif c == "2": guided_store(wh)
        elif c == "3": auto_store_mode(wh)
        elif c == "4":
            if not wh.occupied:
                print("  ❌ Nothing stored!"); continue
            print(f"  Occupied: {sorted(wh.occupied)}")
            try:
                cell = int(input("  Cell: ").strip())
                wh.running = True
                wh.retrieve_product(cell)
                wh.running = False
            except (ValueError, EOFError, KeyboardInterrupt):
                pass
        elif c == "5": scan_addresses(modbus)
        elif c == "6": print(wh.get_full_report())
        elif c == "s": show_sensors(wh)

    wh.all_off()
    if wh.products_stored > 0:
        print(wh.get_full_report())
    modbus.disconnect()
    print("  ✅ Done!")


if __name__ == "__main__":
    main()