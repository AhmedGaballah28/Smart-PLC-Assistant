"""
Agent Pipeline — Entry Point
Wires together Monitor → Diagnostic → Repair → Safety Validator agents.
Connects to MQTT broker and starts all agents.

Usage:
    python agents/run_agents.py
    python agents/run_agents.py --no-llm      # skip LLM, rule-based only
    python agents/run_agents.py --test-llm    # test Gemini connection then exit
"""

import sys
import os
import logging
import argparse
import time
import signal
from pathlib import Path

# ── Path setup ──────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from core.mqtt_client import MQTTClient
from agents.monitor_agent import MonitorAgent
from agents.diagnostic_agent import DiagnosticAgent
from agents.repair_agent import RepairAgent
from agents.safety_validator import SafetyValidatorAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)-20s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("AgentPipeline")


def build_llm_client(api_key: str):
    """Try to build Gemini client; return None on failure (fallback mode)."""
    if not api_key:
        logger.warning("⚠️  GOOGLE_API_KEY not set — running rule-based fallback mode")
        return None
    try:
        from agents.gemini_llm_client import GeminiLLMClient
        client = GeminiLLMClient(api_key=api_key)
        return client
    except Exception as e:
        logger.warning(f"⚠️  Gemini init failed ({e}) — running rule-based fallback")
        return None


def build_kb_client():
    """Try to build ChromaDB KB client; return None if not available."""
    try:
        from knowledge_base.kb_client import KnowledgeBaseClient
        kb = KnowledgeBaseClient()
        if kb.is_available():
            logger.info("✅ Knowledge base loaded")
            return kb
        else:
            logger.warning("⚠️  Knowledge base empty — run: python knowledge_base/build_kb.py")
            return None
    except Exception as e:
        logger.warning(f"⚠️  KB not available ({e})")
        return None


def main():
    parser = argparse.ArgumentParser(description="Smart PLC Agent Pipeline")
    parser.add_argument("--no-llm", action="store_true", help="Skip LLM, use rule-based fallback")
    parser.add_argument("--test-llm", action="store_true", help="Test Gemini connection and exit")
    parser.add_argument("--no-human-approval", action="store_true", help="Disable human approval requests")
    args = parser.parse_args()

    logger.info("═" * 60)
    logger.info("  Smart PLC Assistant — Agent Pipeline")
    logger.info("═" * 60)

    # ── API Key ──────────────────────────────────────────────────────────────
    api_key = os.getenv("GOOGLE_API_KEY", "")
    if not api_key:
        # Try to read from .env
        env_file = PROJECT_ROOT / ".env"
        if env_file.exists():
            for line in env_file.read_text().splitlines():
                if line.startswith("GOOGLE_API_KEY="):
                    api_key = line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    # ── LLM Test mode ────────────────────────────────────────────────────────
    if args.test_llm:
        logger.info("Testing Gemini connection...")
        from agents.gemini_llm_client import GeminiLLMClient
        try:
            client = GeminiLLMClient(api_key=api_key)
            results = client.test_connection()
            print(f"\nResults: {results}")
        except Exception as e:
            print(f"❌ Failed: {e}")
        return

    # ── Build LLM ────────────────────────────────────────────────────────────
    llm = None if args.no_llm else build_llm_client(api_key)
    kb  = build_kb_client()

    # ── MQTT ─────────────────────────────────────────────────────────────────
    logger.info("Connecting to MQTT broker...")
    mqtt = MQTTClient(client_id="smart_plc_agents")
    try:
        mqtt.connect()
        logger.info("✅ MQTT connected")
    except Exception as e:
        logger.error(f"❌ MQTT connection failed: {e}")
        logger.error("   Make sure Mosquitto is running: net start mosquitto")
        sys.exit(1)

    # ── Build agents ─────────────────────────────────────────────────────────
    monitor   = MonitorAgent(mqtt)
    diagnostic = DiagnosticAgent(mqtt, llm_client=llm, kb_client=kb)
    repair    = RepairAgent(mqtt, llm_client=llm, kb_client=kb)
    validator = SafetyValidatorAgent(
        mqtt,
        llm_client=llm,
        require_human_approval=not args.no_human_approval,
    )

    # ── Start agents ──────────────────────────────────────────────────────────
    monitor.start()
    diagnostic.start()
    repair.start()
    validator.start()

    logger.info("")
    logger.info("✅ All agents running!")
    logger.info(f"   Monitor    → factory/+/status")
    logger.info(f"   Diagnostic → agents/monitor/alert")
    logger.info(f"   Repair     → agents/diagnostic/report")
    logger.info(f"   Validator  → agents/repair/proposal")
    logger.info(f"   LLM        : {'Gemini (Google)' if llm else 'Rule-based fallback'}")
    logger.info(f"   KB         : {'Available' if kb else 'Not loaded'}")
    logger.info("")
    logger.info("Press Ctrl+C to stop.\n")

    # ── Graceful shutdown ──────────────────────────────────────────────────
    running = [True]

    def _stop(sig, frame):
        logger.info("\n⏹  Stopping agents...")
        running[0] = False

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    try:
        while running[0]:
            time.sleep(1.0)
    finally:
        monitor.stop()
        diagnostic.stop()
        repair.stop()
        validator.stop()
        mqtt.disconnect()
        logger.info("Agents stopped. Goodbye.")


if __name__ == "__main__":
    main()
