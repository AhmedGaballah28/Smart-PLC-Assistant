"""
Run Line 1 and Line 2 concurrently.
Line 1: Normal Modbus addresses (0-55)
Line 2: Offset Modbus addresses (+100 for IO, +10 for Registers)

Both lines are fully independent — each has its own:
  - Sync events (station-to-station, transfer↔warehouse)
  - Station controllers (Line classes with fault injection)
  - Transition belts

They share:
  - ThreadSafeModbus connection
  - TwinLineSynchronizer (barrier of 4 for cross-line emitter sync)

CROSS-LINE EMITTER SYNC:
  Both lines' MCs (4 total) wait at a shared Barrier(4) before emitting.
  Trigger fires from each line's STN2 when base arrives at sensor_station
  (input 3 for Line 1, input 103 for Line 2).
  This guarantees gap-free simultaneous emission across both lines.
"""

import sys
import os
import threading
import time
import logging
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from factory.modbus_client import FactoryModbusClient
from factory.config import (
    STATION1_CONFIG, STATION2_CONFIG, MACHINING_A_CONFIG, MACHINING_B_CONFIG
)
# Line 1 configs that are natively hardcoded in the class attributes can just pass None
STATION3_CONFIG = None
STATION6_CONFIG = None
STATION7_CONFIG = None
from factory.config_line2 import (
    STATION1_CONFIG as S1_L2,
    STATION2_CONFIG as S2_L2,
    STATION3_CONFIG as S3_L2,
    STATION6_CONFIG as S6_L2,
    STATION7_CONFIG as S7_L2,
    MACHINING_A_CONFIG as MA_L2,
    MACHINING_B_CONFIG as MB_L2
)

# Import stations
from factory.stations.machining import MachiningBaseController, MachiningLidController

# Import the REAL Line classes from run_line (not the base classes!)
from tests.run_line import (
    ThreadSafeModbus,
    MachiningSynchronizer,
    SyncedStation1 as SyncedConfigStation1,
    SyncedStation2 as SyncedConfigStation2,
    SyncedStation3 as SyncedConfigStation3,
    LineStation6,
    LineStation7,
    LineTransferStation,
    LineWarehouse,
)

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger("TwinLines")


# =========================================================================
# TRANSITION BELT ADDRESSES
# =========================================================================

# Line 1 transition belts
L1_BELT_1B = 1      # Stn1 → Stn2
L1_BELT_2B = 10     # Stn2 → Stn3
L1_BELT_3B = 14     # Stn3 → Stn6
L1_BELT_4B = 20     # Stn6 → Stn7
L1_BELT_5B = 27     # Stn7 → Transfer

# Line 2 transition belts (+100 offset)
L2_BELT_1B = 101
L2_BELT_2B = 110
L2_BELT_3B = 114
L2_BELT_4B = 120
L2_BELT_5B = 127


# =========================================================================
# CROSS-LINE EMITTER SYNCHRONIZER
# =========================================================================

class TwinLineSynchronizer:
    """
    Synchronizes ALL 4 machining centers across BOTH lines to emit
    at the EXACT same time.

    Uses a shared Barrier(4) so no MC emits until ALL 4 are ready.

    Trigger flow:
      1. Line 1 STN2 detects base at sensor_station (input 3)
         → calls trigger_line1() → sets L1 MC-A and MC-B ready flags
      2. Line 2 STN2 detects base at sensor_station (input 103)
         → calls trigger_line2() → sets L2 MC-A and MC-B ready flags
      3. Each MC checks its flag, then waits at Barrier(4)
      4. When all 4 arrive → barrier opens → all emit simultaneously

    First cycle: all 4 skip the trigger wait (first=True) and go
    straight to the barrier, so the very first emission is also synced.
    """

    def __init__(self):
        self.lock = threading.Lock()
        self._emit_barrier = threading.Barrier(4)

        # Per-MC ready flags (set by trigger, consumed by wait)
        self._ready = {
            'l1_a': False, 'l1_b': False,
            'l2_a': False, 'l2_b': False,
        }
        # First-cycle skip flags
        self._first = {
            'l1_a': True, 'l1_b': True,
            'l2_a': True, 'l2_b': True,
        }

    def _wait(self, mc_id, controller):
        """Generic wait: skip trigger on first cycle, then barrier."""
        if not self._first[mc_id]:
            logger.info(f"{controller.STATION_ID} ┃ ⏳ Waiting for STN2 trigger...")
            while controller.is_running:
                with self.lock:
                    if self._ready[mc_id]:
                        self._ready[mc_id] = False
                        break
                time.sleep(0.1)
            if not controller.is_running:
                return
        else:
            self._first[mc_id] = False

        # Wait at shared barrier for ALL 4 MCs
        logger.info(f"{controller.STATION_ID} ┃ ⏳ At emit gate — waiting for all MCs...")
        try:
            self._emit_barrier.wait(timeout=180)
        except threading.BrokenBarrierError:
            return
        logger.info(f"{controller.STATION_ID} ┃ ✅ Gate open — emitting NOW!")

    # ── Per-MC wait functions (passed as wait_to_emit_fn) ──

    def wait_l1_a(self, controller):
        self._wait('l1_a', controller)

    def wait_l1_b(self, controller):
        self._wait('l1_b', controller)

    def wait_l2_a(self, controller):
        self._wait('l2_a', controller)

    def wait_l2_b(self, controller):
        self._wait('l2_b', controller)

    # ── Per-line triggers (called by each line's STN2) ──

    def trigger_line1(self):
        """Called by Line 1 STN2 when base detected at sensor_station (input 3)."""
        with self.lock:
            self._ready['l1_a'] = True
            self._ready['l1_b'] = True

    def trigger_line2(self):
        """Called by Line 2 STN2 when base detected at sensor_station (input 103)."""
        with self.lock:
            self._ready['l2_a'] = True
            self._ready['l2_b'] = True

    def abort(self):
        """Call during shutdown to unblock any thread stuck at the barrier."""
        try:
            self._emit_barrier.abort()
        except Exception:
            pass


def init_transition_belts(modbus, io_offset=0):
    """Turn on all 5 transition belts for a line."""
    belts = [
        (1 + io_offset,  "Stn1 → Stn2"),
        (10 + io_offset, "Stn2 → Stn3"),
        (14 + io_offset, "Stn3 → Stn6"),
        (20 + io_offset, "Stn6 → Stn7"),
        (27 + io_offset, "Stn7 → Transfer"),
    ]
    for addr, desc in belts:
        modbus.write_output(addr, True)
    belt_list = ", ".join(f"{addr}({desc})" for addr, desc in belts)
    logger.info(f"  🔄 Transition belts ON: {belt_list}")


def spawn_line(modbus_wrapper, mqtt_client, line_id="LINE1",
               wait_to_emit_a=None, wait_to_emit_b=None,
               emit_trigger_fn=None):
    """
    Spawn a complete assembly line with all stations.
    
    Each line gets its own:
      - Sync events (station-to-station coordination)
      - pallet_ready / product_placed events (Transfer ↔ Warehouse)
      - Line classes with proper behavior

    Emitter sync is controlled externally via:
      - wait_to_emit_a / wait_to_emit_b: wait functions for MC-A / MC-B
      - emit_trigger_fn: trigger function for STN2
    If not provided, a per-line MachiningSynchronizer is created (fallback).
    """
    is_l2 = (line_id == "LINE2")
    io_offset = 100 if is_l2 else 0
    reg_offset = 10 if is_l2 else 0
    
    # ─── Config selection ───
    cfg_s1 = S1_L2 if is_l2 else STATION1_CONFIG
    cfg_s2 = S2_L2 if is_l2 else STATION2_CONFIG
    cfg_s3 = S3_L2 if is_l2 else STATION3_CONFIG
    cfg_s6 = S6_L2 if is_l2 else STATION6_CONFIG
    cfg_s7 = S7_L2 if is_l2 else STATION7_CONFIG
    cfg_ma = MA_L2 if is_l2 else MACHINING_A_CONFIG
    cfg_mb = MB_L2 if is_l2 else MACHINING_B_CONFIG
    
    # ─── Synchronization events (station-to-station) ───
    sync_a_ready = threading.Event()       # MC-A → Stn1
    sync_lid_ready = threading.Event()     # MC-B → Stn2
    sync_1_ready = threading.Event()       # Stn1 → Stn2
    sync_2_ready = threading.Event()       # Stn2 → Stn3
    sync_3_ready = threading.Event()       # Stn3 → Stn6
    sync_6_ready = threading.Event()       # Stn6 → Stn7
    sync_7_ready = threading.Event()       # Stn7 → Transfer
    
    # ─── Transfer ↔ Warehouse coordination events ───
    pallet_ready = threading.Event()       # Warehouse → Transfer (stacker at home)
    product_placed = threading.Event()     # Transfer → Warehouse (product on pallet)
    
    # ─── Machining sync: use external if provided, else per-line fallback ───
    mc_sync_local = None
    if wait_to_emit_a is None:
        mc_sync_local = MachiningSynchronizer()
        wait_to_emit_a = mc_sync_local.wait_a
        wait_to_emit_b = mc_sync_local.wait_b
        emit_trigger_fn = mc_sync_local.trigger
    
    # ─── Transfer sensor address (for Stn7 to monitor) ───
    transfer_sensor_addr = 12 + io_offset   # Line1: 12, Line2: 112
    stacker_register = 0 + reg_offset       # Line1: 0,  Line2: 10
    
    line_label = f"Line {'2' if is_l2 else '1'}"
    transfer_name = f"Transfer-{line_label}"
    
    logger.info(f"")
    logger.info(f"{'═' * 60}")
    logger.info(f"  📺 Spawning {line_label}")
    logger.info(f"     IO offset: +{io_offset}  Reg offset: +{reg_offset}")
    logger.info(f"     Transfer sensor: input {transfer_sensor_addr}")
    logger.info(f"     Stacker register: holding reg {stacker_register}")
    logger.info(f"{'═' * 60}")
    
    # ─── Create station controllers ───
    
    # Machining Centers
    stn_mach_a = MachiningBaseController(
        modbus_wrapper, mqtt_client,
        downstream_ready=sync_a_ready,
        wait_to_emit_fn=wait_to_emit_a,
        config=cfg_ma
    )
    stn_mach_b = MachiningLidController(
        modbus_wrapper, mqtt_client,
        lid_ready_event=sync_lid_ready,
        wait_to_emit_fn=wait_to_emit_b,
        config=cfg_mb
    )
    
    # Station 1 — Chassis Loading & Inspection
    stn1 = SyncedConfigStation1(
        modbus_wrapper, mqtt_client,
        config=cfg_s1,
        downstream_ready=sync_1_ready,
        upstream_ready=sync_a_ready
    )
    
    # Station 2 — PCB Board Installation
    stn2 = SyncedConfigStation2(
        modbus_wrapper, mqtt_client,
        config=cfg_s2,
        upstream_ready=sync_1_ready,
        downstream_ready=sync_2_ready,
        lid_ready=sync_lid_ready,
        emit_trigger_fn=emit_trigger_fn
    )
    
    # Station 3 — Display Panel Mounting
    stn3 = SyncedConfigStation3(
        modbus_wrapper, mqtt_client,
        config=cfg_s3,
        upstream_ready=sync_2_ready,
        downstream_ready=sync_3_ready
    )
    
    # Station 6 — Quality Control (LINE version with fault injection)
    stn6 = LineStation6(
        modbus_wrapper, mqtt_client,
        upstream_ready_event=sync_3_ready,
        downstream_ready_event=sync_6_ready,
        config=cfg_s6
    )
    
    # Station 7 — Sorting & Output (LINE version with 6s arm wait + fault injection)
    stn7 = LineStation7(
        modbus_wrapper,
        station6_ref=stn6,
        mqtt_client=mqtt_client,
        upstream_ready_event=sync_6_ready,
        config=cfg_s7,
        transfer_sensor_addr=transfer_sensor_addr
    )
    
    # Transfer — LINE version with warehouse coordination
    stn_transfer = LineTransferStation(
        modbus_wrapper, mqtt_client,
        pallet_ready_event=pallet_ready,
        product_placed_event=product_placed,
        station_name=transfer_name,
        stacker_register=stacker_register
    )
    
    # Warehouse — LINE version with Transfer coordination + offset addresses
    stn_warehouse = LineWarehouse(
        modbus_wrapper, mqtt_client,
        pallet_ready_event=pallet_ready,
        product_placed_event=product_placed,
        io_offset=io_offset,
        reg_offset=reg_offset
    )
    
    # ─── Station list (DOWNSTREAM FIRST for proper event wiring) ───
    stations_in_start_order = [
        ("Warehouse",  stn_warehouse),
        ("Transfer",   stn_transfer),
        ("Station 7",  stn7),
        ("Station 6",  stn6),
        ("Station 3",  stn3),
        ("Station 2",  stn2),
        ("Station 1",  stn1),
        ("MC-A",       stn_mach_a),
        ("MC-B",       stn_mach_b),
    ]
    
    logger.info(f"  ✅ {line_label} — ALL stations created!")
    logger.info(f"")
    
    return stations_in_start_order, mc_sync_local


def start_all_threads(stations_l1, stations_l2, twin_sync):
    """
    Start ALL station threads for both lines simultaneously.
    Uses a shared start_event so no line gets a head start.
    """
    start_event = threading.Event()
    
    def gated_run(station, start_evt):
        """Wait for the start signal, then run the station."""
        start_evt.wait()
        station.run()
    
    all_threads = []
    
    # Create threads for Line 1
    for name, station in stations_l1:
        t = threading.Thread(
            target=gated_run, args=(station, start_event),
            daemon=True, name=f"Line 1-{name}"
        )
        t.start()
        all_threads.append((station, t))
        logger.info(f"  ▶ Line 1 — {name} thread ready")
    
    # Create threads for Line 2
    for name, station in stations_l2:
        t = threading.Thread(
            target=gated_run, args=(station, start_event),
            daemon=True, name=f"Line 2-{name}"
        )
        t.start()
        all_threads.append((station, t))
        logger.info(f"  ▶ Line 2 — {name} thread ready")
    
    # All threads are created and waiting — release them all at once!
    logger.info("")
    logger.info("🚀 ALL threads ready — starting BOTH lines NOW!")
    start_event.set()
    
    return all_threads


def main():
    print()
    print("═" * 70)
    print("  📺 TWIN TV ASSEMBLY LINES")
    print("  🔗 Two independent lines, shared Modbus, concurrent operation")
    print("  📦 Line 1: addresses 0-55  |  Line 2: addresses +100/+10")
    print("  🔄 Cross-line emitter sync: Barrier(4) for gap-free emission")
    print("═" * 70)
    print()
    
    # ─── Connect to Factory I/O ───
    client = FactoryModbusClient("127.0.0.1", 502)
    if not client.connect():
        logger.error("Could not connect to Modbus server.")
        return
    
    modbus_wrapper = ThreadSafeModbus(client)
    logger.info("🔒 Thread-safe Modbus wrapper active")
    
    # ─── Create shared cross-line synchronizer ───
    twin_sync = TwinLineSynchronizer()
    logger.info("🔄 TwinLineSynchronizer created — Barrier(4) for all MCs")
    logger.info("   Trigger: STN2 sensor_station (input 3 / input 103)")
    
    # ─── Create both lines (stations only, no threads yet) ───
    logger.info("Creating Line 1 stations...")
    stations_l1, _ = spawn_line(
        modbus_wrapper, None, "LINE1",
        wait_to_emit_a=twin_sync.wait_l1_a,
        wait_to_emit_b=twin_sync.wait_l1_b,
        emit_trigger_fn=twin_sync.trigger_line1
    )
    
    logger.info("Creating Line 2 stations...")
    stations_l2, _ = spawn_line(
        modbus_wrapper, None, "LINE2",
        wait_to_emit_a=twin_sync.wait_l2_a,
        wait_to_emit_b=twin_sync.wait_l2_b,
        emit_trigger_fn=twin_sync.trigger_line2
    )
    
    # ─── Initialize transition belts for both lines ───
    init_transition_belts(modbus_wrapper, 0)    # Line 1
    init_transition_belts(modbus_wrapper, 100)  # Line 2
    
    # ─── Start ALL threads simultaneously ───
    all_threads = start_all_threads(stations_l1, stations_l2, twin_sync)
    
    print()
    print("═" * 70)
    print("  ✅ BOTH LINES RUNNING SIMULTANEOUSLY!")
    print("  🔄 Emitters synced: all 4 MCs rendezvous at Barrier(4)")
    print("  📡 Re-emit trigger: STN2 sensor_station (input 3 / 103)")
    print("  Press Ctrl+C to stop all stations")
    print("═" * 70)
    print()
    
    # ─── Main loop ───
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        logger.info("🛑 Stopping all stations...")
        
        # Abort the shared synchronizer first (release barrier-stuck threads)
        twin_sync.abort()
        
        # Stop all stations
        for station, thread in all_threads:
            station.is_running = False
        
        # Wait for threads to finish
        for station, thread in all_threads:
            thread.join(timeout=3.0)
        
        logger.info("✅ Shutdown complete.")
        client.disconnect()


if __name__ == "__main__":
    main()
