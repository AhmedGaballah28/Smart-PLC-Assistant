"""
Repair Agent
Listens for Diagnostic Agent reports and proposes concrete repair solutions
using Google Gemini LLM + knowledge base context.
"""

import json
import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)


class RepairAgent:
    """
    Proposes repair solutions based on diagnoses from the Diagnostic Agent.

    Flow:
      1. Listens on agents/diagnostic/report
      2. Queries knowledge base for repair procedures matching the diagnosis
      3. Calls LLM to generate ranked repair proposals
      4. Publishes proposals to agents/repair/proposal

    MQTT IN:  agents/diagnostic/report
    MQTT OUT: agents/repair/proposal
              agents/repair/status
    """

    def __init__(self, mqtt_client, llm_client=None, kb_client=None,
                 on_proposal_callback=None):
        self.mqtt = mqtt_client
        self.llm = llm_client
        self.kb = kb_client
        self.on_proposal_callback = on_proposal_callback
        self._running = False
        self._lock = threading.Lock()
        self._proposal_count = 0
        self._recent_proposals: List[Dict] = []

    def start(self):
        self._running = True
        logger.info("🔧 Repair Agent starting...")
        self.mqtt.subscribe("agents/diagnostic/report", self._on_diagnosis)
        self._publish_status("online")
        logger.info("✅ Repair Agent running — awaiting diagnoses")

    def stop(self):
        self._running = False
        self._publish_status("offline")

    # ─────────────────────────────────────────────────────────────────────────
    # DIAGNOSIS HANDLER
    # ─────────────────────────────────────────────────────────────────────────

    def _on_diagnosis(self, topic: str, payload: Any):
        if not self._running:
            return
        try:
            if isinstance(payload, str):
                diagnosis = json.loads(payload)
            elif isinstance(payload, dict):
                diagnosis = payload
            else:
                return

            thread = threading.Thread(
                target=self._propose_repairs,
                args=(diagnosis,),
                daemon=True,
                name=f"Repair-{diagnosis.get('diagnosis_id', '?')}",
            )
            thread.start()
        except Exception as e:
            logger.error(f"Repair Agent: error handling diagnosis: {e}")

    def _propose_repairs(self, diagnosis: dict):
        try:
            logger.info(f"🔧 Proposing repairs for: {diagnosis.get('diagnosis_id')} "
                        f"[{diagnosis.get('station_name')}]")

            # ── RAG context ──
            rag_context = ""
            if self.kb:
                try:
                    query = (f"repair fix {diagnosis.get('root_cause', '')} "
                             f"{diagnosis.get('station_name', '')}")
                    results = self.kb.search(query, n_results=3)
                    rag_context = self._format_rag(results)
                except Exception as e:
                    logger.warning(f"   Repair RAG failed: {e}")

            # ── LLM proposals ──
            if self.llm:
                try:
                    repair_text = self.llm.suggest_repair(
                        json.dumps(diagnosis, indent=2), rag_context
                    )
                    proposals = self._parse_proposals(repair_text, diagnosis)
                except Exception as e:
                    logger.error(f"   Repair LLM error: {e}")
                    proposals = self._rule_based_repairs(diagnosis)
            else:
                proposals = self._rule_based_repairs(diagnosis)

            proposal_doc = {
                "proposal_id": f"RP-{self._proposal_count + 1:04d}",
                "diagnosis_id": diagnosis.get("diagnosis_id"),
                "alert_id": diagnosis.get("alert_id"),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "station_id": diagnosis.get("station_id"),
                "station_name": diagnosis.get("station_name"),
                "root_cause": diagnosis.get("root_cause"),
                "urgency": diagnosis.get("urgency", "MEDIUM"),
                "proposals": proposals,
                "requires_approval": True,
            }

            with self._lock:
                self._proposal_count += 1
                self._recent_proposals.append(proposal_doc)
                if len(self._recent_proposals) > 20:
                    self._recent_proposals.pop(0)

            logger.info(f"✅ Repair proposal #{self._proposal_count}: "
                        f"{len(proposals)} solutions for "
                        f"{diagnosis.get('station_name')}")

            self._publish_proposal(proposal_doc)

            if self.on_proposal_callback:
                self.on_proposal_callback(proposal_doc)

        except Exception as e:
            logger.error(f"Repair Agent: unhandled error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # PARSING + FALLBACK
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_proposals(self, text: str, diagnosis: dict) -> list:
        """Try to parse LLM JSON; fall back to structured text."""
        try:
            clean = text.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1])
            parsed = json.loads(clean)
            solutions = parsed.get("solutions", parsed if isinstance(parsed, list) else [])
            if solutions:
                return solutions
        except Exception:
            pass

        try:
            start = text.find("[")
            end = text.rfind("]") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception:
            pass

        # Fallback
        return self._rule_based_repairs(diagnosis)

    def _rule_based_repairs(self, diagnosis: dict) -> list:
        root_cause = diagnosis.get("root_cause", "").lower()
        urgency = diagnosis.get("urgency", "MEDIUM")

        if "temperature" in root_cause or "overheat" in root_cause:
            return [
                {
                    "id": 1,
                    "name": "Clean Cooling System",
                    "description": "Remove dust from motor vents and heatsink. Check fan operation.",
                    "parameters_to_change": {"inspection_frequency": "monthly"},
                    "expected_result": "Temperature reduction of 8-12°C",
                    "risk_level": "LOW",
                    "estimated_downtime_min": 30,
                    "trade_offs": "Short production halt required",
                },
                {
                    "id": 2,
                    "name": "Reduce Duty Cycle",
                    "description": "Reduce belt speed by 15% to lower thermal load.",
                    "parameters_to_change": {"belt_speed_pct": 85},
                    "expected_result": "5-8°C temperature reduction, 10% throughput loss",
                    "risk_level": "LOW",
                    "estimated_downtime_min": 0,
                    "trade_offs": "Reduced production rate",
                },
            ]
        elif "vibration" in root_cause or "bearing" in root_cause:
            return [
                {
                    "id": 1,
                    "name": "Inspect and Lubricate Bearings",
                    "description": "Check belt drive bearings for wear. Apply appropriate grease.",
                    "parameters_to_change": {"maintenance_interval": "6_months"},
                    "expected_result": "Vibration reduction of 40-60%",
                    "risk_level": "LOW",
                    "estimated_downtime_min": 60,
                    "trade_offs": "60-minute shutdown required",
                },
                {
                    "id": 2,
                    "name": "Replace Bearings",
                    "description": "Full bearing replacement if lubrication insufficient.",
                    "parameters_to_change": {},
                    "expected_result": "Full vibration resolution",
                    "risk_level": "MEDIUM",
                    "estimated_downtime_min": 180,
                    "trade_offs": "Extended downtime, parts cost",
                },
            ]
        elif "power" in root_cause or "electrical" in root_cause:
            return [
                {
                    "id": 1,
                    "name": "Inspect Electrical Connections",
                    "description": "Check terminal torque, inspect PSU output, verify cable integrity.",
                    "parameters_to_change": {},
                    "expected_result": "Stable power draw, reduced brownout frequency",
                    "risk_level": "MEDIUM",
                    "estimated_downtime_min": 45,
                    "trade_offs": "Requires electrical safety lockout",
                },
            ]
        else:
            return [
                {
                    "id": 1,
                    "name": "Manual Inspection",
                    "description": f"Manually inspect station for: {diagnosis.get('root_cause', 'fault')}",
                    "parameters_to_change": {},
                    "expected_result": "Root cause identified and addressed",
                    "risk_level": "LOW",
                    "estimated_downtime_min": 20,
                    "trade_offs": "Brief production halt",
                },
            ]

    def _format_rag(self, results: list) -> str:
        if not results:
            return ""
        parts = ["=== Repair Procedures from Knowledge Base ==="]
        for i, r in enumerate(results, 1):
            parts.append(f"\n[{i}] {r.get('metadata', {}).get('title', 'Procedure')}:")
            parts.append(r.get("document", "")[:400])
        return "\n".join(parts)

    # ─────────────────────────────────────────────────────────────────────────
    # MQTT
    # ─────────────────────────────────────────────────────────────────────────

    def _publish_proposal(self, proposal: dict):
        try:
            self.mqtt.publish("agents/repair/proposal", json.dumps(proposal))
        except Exception as e:
            logger.error(f"Repair: publish error: {e}")

    def _publish_status(self, status: str):
        try:
            self.mqtt.publish("agents/repair/status", json.dumps({
                "agent": "repair",
                "status": status,
                "proposal_count": self._proposal_count,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }))
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # QUERY API
    # ─────────────────────────────────────────────────────────────────────────

    def get_recent_proposals(self, limit: int = 10) -> List[Dict]:
        with self._lock:
            return list(reversed(self._recent_proposals[-limit:]))

    def get_proposal_count(self) -> int:
        return self._proposal_count
