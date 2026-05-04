"""
Smart PLC Assistant — Master Launcher (app.py)

Starts all required services for the full pipeline, each in its own terminal window.

STARTUP ORDER (enforced by this script):
  1. Mosquitto MQTT Broker         (prerequisite for everything)
  2. SQLite DB Init                (one-shot, ensures schema exists)
  3. MQTT Data Logger              (CSV logging for telemetry)
  4. Realtime Aggregator           (z-score anomaly detection → publishes alerts)
  5. Digital Twin (run_twin.py)    (Factory I/O Modbus + MQTT telemetry)
  6. Monitor Agent                 (listens for aggregator alerts → triggers LangGraph)

USAGE:
    python app.py                      # Start all services
    python app.py --no-twin            # Skip Factory I/O twin (no Modbus needed)
    python app.py --no-logger          # Skip CSV data logger
    python app.py --data-dir ./data/run_005   # Custom data output directory
    python app.py --init-db            # Force re-init the database schema
"""

import os
import sys
import time
import signal
import logging
import argparse
import subprocess
from pathlib import Path
from datetime import datetime

# ══════════════════════════════════════════════════════════════════════════
# PATHS
# ══════════════════════════════════════════════════════════════════════════

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PYTHON_EXE = sys.executable

# Runner scripts
INIT_DB_SCRIPT = PROJECT_ROOT / "runners" / "init_sqlite_db.py"
DATA_LOGGER_SCRIPT = PROJECT_ROOT / "runners" / "mqtt_data_logger.py"
AGGREGATOR_SCRIPT = PROJECT_ROOT / "runners" / "realtime_aggregator.py"
TWIN_SCRIPT = PROJECT_ROOT / "runners" / "run_twin.py"
MONITOR_AGENT_SCRIPT = PROJECT_ROOT / "agents" / "monitor_agent.py"

# ══════════════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("SmartPLC")

# ══════════════════════════════════════════════════════════════════════════
# PROCESS MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════

_child_processes: list[subprocess.Popen] = []


def _launch_in_terminal(title: str, command: list[str], cwd: str = None) -> subprocess.Popen:
    """
    Launch a command in a NEW Windows terminal window.
    Uses 'start' with /K to keep the window open for debugging.
    """
    cwd = cwd or str(PROJECT_ROOT)
    
    # Build the command string for cmd.exe
    cmd_str = " ".join(f'"{c}"' if " " in c else c for c in command)
    
    proc = subprocess.Popen(
        f'start "{title}" /D "{cwd}" cmd /K {cmd_str}',
        shell=True,
        cwd=cwd,
    )
    
    _child_processes.append(proc)
    logger.info(f"  ✅ {title} — launched (PID: {proc.pid})")
    return proc


def _run_sync(title: str, command: list[str], cwd: str = None, timeout: int = 30) -> bool:
    """Run a command synchronously and wait for completion."""
    cwd = cwd or str(PROJECT_ROOT)
    logger.info(f"  ⏳ {title} — running...")
    
    try:
        result = subprocess.run(
            command,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            logger.info(f"  ✅ {title} — completed successfully")
            if result.stdout.strip():
                for line in result.stdout.strip().split("\n")[-5:]:
                    logger.info(f"     {line.strip()}")
            return True
        else:
            logger.error(f"  ❌ {title} — failed (exit code {result.returncode})")
            if result.stderr.strip():
                for line in result.stderr.strip().split("\n")[-3:]:
                    logger.error(f"     {line.strip()}")
            return False
    except subprocess.TimeoutExpired:
        logger.error(f"  ❌ {title} — timed out after {timeout}s")
        return False


def shutdown_all(signum=None, frame=None):
    """Gracefully terminate all child processes."""
    logger.info("")
    logger.info("🛑 Shutting down all services...")
    
    for proc in reversed(_child_processes):
        try:
            proc.terminate()
        except Exception:
            pass
    
    # Give processes time to exit
    time.sleep(2)
    
    for proc in reversed(_child_processes):
        try:
            if proc.poll() is None:
                proc.kill()
        except Exception:
            pass
    
    logger.info("✅ All services stopped.")
    sys.exit(0)


# ══════════════════════════════════════════════════════════════════════════
# MAIN LAUNCHER
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description="Smart PLC Assistant — Master Launcher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
STARTUP ORDER:
  1. mosquitto (MQTT broker)
  2. init_sqlite_db.py (one-shot schema creation)
  3. mqtt_data_logger.py (CSV logging)
  4. realtime_aggregator.py (anomaly detection)
  5. run_twin.py (Factory I/O digital twin)
  6. monitor_agent.py (LangGraph supervisor trigger)
        """,
    )
    parser.add_argument("--no-twin", action="store_true",
                        help="Skip the Factory I/O digital twin (no Modbus)")
    parser.add_argument("--no-logger", action="store_true",
                        help="Skip the CSV data logger")
    parser.add_argument("--no-monitor", action="store_true",
                        help="Skip the Monitor Agent (LangGraph)")
    parser.add_argument("--init-db", action="store_true",
                        help="Force re-initialize the database schema")
    parser.add_argument("--data-dir", type=str, default=None,
                        help="Custom data output directory for logger/aggregator")
    args = parser.parse_args()

    # Auto-generate data directory if not specified
    if args.data_dir is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        data_dir = str(PROJECT_ROOT / "data" / f"run_{timestamp}")
    else:
        data_dir = args.data_dir

    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, shutdown_all)
    signal.signal(signal.SIGTERM, shutdown_all)

    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║           SMART PLC ASSISTANT — MASTER LAUNCHER                ║")
    print("║                                                                ║")
    print("║   AI-Powered Fault Detection, Diagnosis & Repair Pipeline      ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    # ── Step 0: Verify Environment ────────────────────────────────────────
    logger.info("═══ Step 0: Environment Check ═══")
    
    env_path = PROJECT_ROOT / ".env"
    if env_path.exists():
        logger.info("  ✅ .env file found")
    else:
        logger.warning("  ⚠️  No .env file found — LLM API keys may be missing!")

    db_path = PROJECT_ROOT / "data" / "plc_data.db"
    if db_path.exists():
        logger.info(f"  ✅ Database exists ({db_path.stat().st_size / 1024:.0f} KB)")
    else:
        logger.info("  ⚠️  No database found — will initialize")
        args.init_db = True

    print()

    # ── Step 1: MQTT Broker ───────────────────────────────────────────────
    logger.info("═══ Step 1: MQTT Broker (Mosquitto) ═══")
    logger.info("  ℹ️  Make sure Mosquitto is running before we continue!")
    logger.info("  ℹ️  If not, open a terminal and run: mosquitto -v")
    
    # Quick health check: try to connect
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from core.mqtt_client import MQTTClient
        test_mqtt = MQTTClient(client_id="launcher_health_check")
        if test_mqtt.connect():
            logger.info("  ✅ MQTT Broker is reachable!")
            test_mqtt.disconnect()
        else:
            logger.warning("  ⚠️  Cannot connect to MQTT broker!")
            logger.warning("      Please start mosquitto and re-run this script.")
            logger.warning("      Continuing anyway — services will retry...")
    except Exception as e:
        logger.warning(f"  ⚠️  MQTT check failed: {e}")
        logger.warning("      Continuing — services will retry on their own.")
    print()

    # ── Step 2: Database Init ─────────────────────────────────────────────
    if args.init_db:
        logger.info("═══ Step 2: Database Initialization ═══")
        _run_sync(
            "SQLite Schema Init",
            [PYTHON_EXE, str(INIT_DB_SCRIPT)],
        )
        print()
    else:
        logger.info("═══ Step 2: Database ═══")
        logger.info("  ⏩ Skipping init (database exists). Use --init-db to force.")
        print()

    # ── Step 3: MQTT Data Logger ──────────────────────────────────────────
    if not args.no_logger:
        logger.info("═══ Step 3: MQTT Data Logger (CSV) ═══")
        logger_cmd = [PYTHON_EXE, str(DATA_LOGGER_SCRIPT), "--output", data_dir]
        _launch_in_terminal("📊 Data Logger", logger_cmd)
        time.sleep(2)  # Give it time to create CSV files
        print()
    else:
        logger.info("═══ Step 3: Data Logger ═══")
        logger.info("  ⏩ Skipped (--no-logger)")
        print()

    # ── Step 4: Realtime Aggregator ───────────────────────────────────────
    logger.info("═══ Step 4: Realtime Aggregator (Anomaly Detection) ═══")
    aggregator_cmd = [PYTHON_EXE, str(AGGREGATOR_SCRIPT), "--output", data_dir]
    _launch_in_terminal("🔍 Realtime Aggregator", aggregator_cmd)
    time.sleep(2)
    print()

    # ── Step 5: Digital Twin ──────────────────────────────────────────────
    if not args.no_twin:
        logger.info("═══ Step 5: Digital Twin (Factory I/O + MQTT Telemetry) ═══")
        logger.info("  ℹ️  Ensure Factory I/O scene is loaded and running!")
        twin_cmd = [PYTHON_EXE, str(TWIN_SCRIPT)]
        _launch_in_terminal("🏭 Digital Twin", twin_cmd)
        time.sleep(3)
        print()
    else:
        logger.info("═══ Step 5: Digital Twin ═══")
        logger.info("  ⏩ Skipped (--no-twin)")
        print()

    # ── Step 6: Monitor Agent (LangGraph) ─────────────────────────────────
    if not args.no_monitor:
        logger.info("═══ Step 6: Monitor Agent (LangGraph Supervisor) ═══")
        monitor_cmd = [PYTHON_EXE, str(MONITOR_AGENT_SCRIPT)]
        _launch_in_terminal("🤖 Monitor Agent", monitor_cmd)
        time.sleep(2)
        print()
    else:
        logger.info("═══ Step 6: Monitor Agent ═══")
        logger.info("  ⏩ Skipped (--no-monitor)")
        print()

    # ── Summary ───────────────────────────────────────────────────────────
    print()
    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║                    ALL SERVICES LAUNCHED                       ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    
    services = []
    services.append(("  MQTT Broker", "External", "mosquitto -v"))
    if not args.no_logger:
        services.append(("  📊 Data Logger", "Terminal", "CSV → " + data_dir))
    services.append(("  🔍 Aggregator", "Terminal", "z-score + threshold alerts"))
    if not args.no_twin:
        services.append(("  🏭 Digital Twin", "Terminal", "Factory I/O Modbus + MQTT"))
    if not args.no_monitor:
        services.append(("  🤖 Monitor Agent", "Terminal", "LangGraph Supervisor"))
    
    for name, mode, desc in services:
        print(f"║ {name:<22} │ {mode:<10} │ {desc:<27} ║")
    
    print("╠══════════════════════════════════════════════════════════════════╣")
    print(f"║  Data Directory: {data_dir:<45} ║")
    print(f"║  Database: {'data/plc_data.db':<51} ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    print("║  Press Ctrl+C in this window to shutdown all services.         ║")
    print("╚══════════════════════════════════════════════════════════════════╝")
    print()

    # ── Keep alive ────────────────────────────────────────────────────────
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        shutdown_all()


if __name__ == "__main__":
    main()
