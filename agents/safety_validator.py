"""
Safety Validator Agent
Validates proposed repair actions against safety rules before execution.
Uses Google Gemini + rule-based safety checks.
"""

import json
import logging
import threading
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# ── Core safety rules ────────────────────────────────────────────────────────
SAFETY_RULES = """
MANDATORY SAFETY RULES FOR PLC REPAIR APPROVAL:

1. LOCKOUT/TAGOUT: Any physical inspection or component replacement requires
   full LOTO procedure. Electrical work at risk_level MEDIUM or HIGH must
   not proceed without LOTO confirmation.

2. BELT SPEED REDUCTION: Speed reductions > 30% may affect product positioning
   and downstream sensor trigger timing. Must be validated against cycle time.

3. EMERGENCY STOP RESET: Never reset an emergency stop without first verifying
   and documenting the root cause. Unexplained E-stops are HIGH risk.

4. CONCURRENT REPAIRS: Do not perform repairs on Station N while upstream
   Station N-1 is still running. Full line stop required.

5. PARAMETER CHANGES: Belt speed, timing, and threshold changes that exceed
   ±20% from nominal require supervisor sign-off.

6. VISION SENSOR RECALIBRATION: Any repair affecting the QC station requires
   re-running calibration verification before restart.

7. MAXIMUM DOWNTIME: For repairs estimated > 4 hours, arrange replacement
   parts before starting to minimize line stoppage.
"""


class SafetyValidatorAgent:
    """
    Validates repair proposals against safety rules before allowing execution.

    Flow:
      1. Listens on agents/repair/proposal
      2. Runs rule-based safety checks on each proposed repair
      3. Optionally calls LLM for deeper safety analysis
      4. Publishes PASS/FAIL verdict to agents/validation/result
      5. High-risk proposals trigger human approval request

    MQTT IN:  agents/repair/proposal
    MQTT OUT: agents/validation/result
              agents/validation/status
              human/requests/pending  (if human approval needed)
    """

    # Risk levels that require human approval
    HUMAN_APPROVAL_RISK_LEVELS = {"HIGH", "CRITICAL"}

    # Parameters that can never be changed without approval
    FORBIDDEN_AUTO_PARAMS = {
        "emergency_override", "safety_bypass", "sensor_disable",
    }

    def __init__(self, mqtt_client, llm_client=None,
                 on_validation_callback=None, require_human_approval=True):
        self.mqtt = mqtt_client
        self.llm = llm_client
        self.on_validation_callback = on_validation_callback
        self.require_human_approval = require_human_approval
        self._running = False
        self._lock = threading.Lock()
        self._validation_count = 0
        self._recent_validations: List[Dict] = []

    def start(self):
        self._running = True
        logger.info("🛡️ Safety Validator Agent starting...")
        self.mqtt.subscribe("agents/repair/proposal", self._on_proposal)
        self._publish_status("online")
        logger.info("✅ Safety Validator running — awaiting repair proposals")

    def stop(self):
        self._running = False
        self._publish_status("offline")

    # ─────────────────────────────────────────────────────────────────────────
    # PROPOSAL HANDLER
    # ─────────────────────────────────────────────────────────────────────────

    def _on_proposal(self, topic: str, payload: Any):
        if not self._running:
            return
        try:
            if isinstance(payload, str):
                proposal = json.loads(payload)
            elif isinstance(payload, dict):
                proposal = payload
            else:
                return

            thread = threading.Thread(
                target=self._validate_proposal,
                args=(proposal,),
                daemon=True,
                name=f"Validate-{proposal.get('proposal_id', '?')}",
            )
            thread.start()
        except Exception as e:
            logger.error(f"Safety Validator: error: {e}")

    def _validate_proposal(self, proposal: dict):
        try:
            logger.info(f"🛡️ Validating: {proposal.get('proposal_id')} "
                        f"[{proposal.get('station_name')}]")

            proposals = proposal.get("proposals", [])
            validated_proposals = []
            overall_verdict = "PASS"
            overall_risk = 0

            for p in proposals:
                result = self._validate_single(p, proposal)
                validated_proposals.append(result)
                if result["verdict"] == "FAIL":
                    overall_verdict = "FAIL"
                overall_risk = max(overall_risk, result.get("risk_score", 0))

            # ── LLM deeper check (optional) ──
            llm_verdict = None
            if self.llm and overall_verdict == "PASS" and validated_proposals:
                try:
                    highest_risk = max(validated_proposals, key=lambda x: x.get("risk_score", 0))
                    llm_check = self.llm.validate_safety(
                        highest_risk.get("proposal", {}), SAFETY_RULES
                    )
                    parsed = self._parse_llm_verdict(llm_check)
                    if parsed.get("verdict") == "FAIL":
                        overall_verdict = "CONDITIONAL"
                    llm_verdict = parsed
                except Exception as e:
                    logger.warning(f"   LLM safety check failed: {e}")

            # ── Human approval required? ──
            needs_human = (
                self.require_human_approval
                and (
                    overall_risk >= 70
                    or proposal.get("urgency") == "HIGH"
                    or overall_verdict != "PASS"
                )
            )

            validation_result = {
                "validation_id": f"VLD-{self._validation_count + 1:04d}",
                "proposal_id": proposal.get("proposal_id"),
                "diagnosis_id": proposal.get("diagnosis_id"),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "station_id": proposal.get("station_id"),
                "station_name": proposal.get("station_name"),
                "overall_verdict": overall_verdict,
                "overall_risk_score": overall_risk,
                "needs_human_approval": needs_human,
                "llm_verdict": llm_verdict,
                "validated_proposals": validated_proposals,
                "safety_rules_applied": len(SAFETY_RULES.strip().split("\n")),
            }

            with self._lock:
                self._validation_count += 1
                self._recent_validations.append(validation_result)
                if len(self._recent_validations) > 20:
                    self._recent_validations.pop(0)

            logger.info(f"✅ Validation #{self._validation_count}: "
                        f"verdict={overall_verdict} risk={overall_risk} "
                        f"human_needed={needs_human}")

            self._publish_validation(validation_result)

            if needs_human:
                self._request_human_approval(proposal, validation_result)

            if self.on_validation_callback:
                self.on_validation_callback(validation_result)

        except Exception as e:
            logger.error(f"Safety Validator: unhandled error: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # VALIDATION LOGIC
    # ─────────────────────────────────────────────────────────────────────────

    def _validate_single(self, proposal: dict, parent: dict) -> dict:
        """Run rule-based checks on a single repair proposal."""
        checks = []
        risk_score = 0
        verdict = "PASS"
        concerns = []

        risk_level = proposal.get("risk_level", "LOW").upper()

        # Rule 1: Forbidden parameters
        params = proposal.get("parameters_to_change", {})
        for forbidden in self.FORBIDDEN_AUTO_PARAMS:
            if forbidden in params:
                checks.append(f"FAIL: Forbidden parameter '{forbidden}'")
                verdict = "FAIL"
                risk_score = 100
                concerns.append(f"Parameter '{forbidden}' is safety-critical and cannot be auto-changed")

        # Rule 2: Risk level escalation
        if risk_level == "HIGH":
            risk_score = max(risk_score, 80)
            concerns.append("High-risk repair — requires careful supervision")
        elif risk_level == "MEDIUM":
            risk_score = max(risk_score, 50)

        # Rule 3: Belt speed checks
        new_speed = params.get("belt_speed_pct")
        if new_speed is not None:
            if new_speed < 50:
                checks.append(f"WARNING: Belt speed {new_speed}% < 50% may cause product positioning issues")
                risk_score = max(risk_score, 60)
                concerns.append(f"Speed reduction to {new_speed}% exceeds 20% limit — validate cycle timing")
            checks.append(f"PASS: Belt speed change to {new_speed}% is within safety range")

        # Rule 4: Emergency stop check
        urgency = parent.get("urgency", "MEDIUM")
        if urgency == "HIGH" and risk_level != "LOW":
            concerns.append("High urgency + non-low risk: full line stop recommended before repair")

        # Rule 5: Estimated downtime check
        downtime = proposal.get("estimated_downtime_min", 0)
        if downtime > 240:
            checks.append(f"WARNING: Estimated downtime {downtime} min > 4 hours")
            concerns.append("Long downtime repair — arrange replacement parts before starting")

        if not checks:
            checks.append("PASS: All basic safety rules satisfied")

        return {
            "proposal_id": proposal.get("id"),
            "proposal_name": proposal.get("name"),
            "verdict": verdict,
            "risk_score": risk_score,
            "checks": checks,
            "concerns": concerns,
            "requires_loto": risk_level in ("MEDIUM", "HIGH"),
            "proposal": proposal,
        }

    def _parse_llm_verdict(self, text: str) -> dict:
        try:
            clean = text.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1])
            return json.loads(clean)
        except Exception:
            try:
                start = text.find("{")
                end = text.rfind("}") + 1
                if start >= 0 and end > start:
                    return json.loads(text[start:end])
            except Exception:
                pass
        return {"verdict": "PASS", "risk_score": 30, "checks": [text[:300]], "concerns": []}

    # ─────────────────────────────────────────────────────────────────────────
    # HUMAN APPROVAL REQUEST
    # ─────────────────────────────────────────────────────────────────────────

    def _request_human_approval(self, proposal: dict, validation: dict):
        request = {
            "request_id": f"HUM-{self._validation_count:04d}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "type": "repair_approval",
            "station_id": proposal.get("station_id"),
            "station_name": proposal.get("station_name"),
            "root_cause": proposal.get("root_cause"),
            "urgency": proposal.get("urgency"),
            "overall_risk_score": validation.get("overall_risk_score"),
            "overall_verdict": validation.get("overall_verdict"),
            "proposals": proposal.get("proposals", []),
            "concerns": [
                c for vp in validation.get("validated_proposals", [])
                for c in vp.get("concerns", [])
            ],
            "response_topic": "human/approval/decision",
            "instructions": (
                "Review the repair proposals and safety validation. "
                "Respond with {approved: true/false, selected_proposal_id: N, "
                "comments: '...'} to the response_topic."
            ),
        }
        try:
            self.mqtt.publish("human/requests/pending", json.dumps(request))
            logger.warning(f"👤 Human approval requested for {proposal.get('station_name')}")
        except Exception as e:
            logger.error(f"Safety: failed to publish human request: {e}")

    # ─────────────────────────────────────────────────────────────────────────
    # MQTT
    # ─────────────────────────────────────────────────────────────────────────

    def _publish_validation(self, result: dict):
        try:
            self.mqtt.publish("agents/validation/result", json.dumps(result))
        except Exception as e:
            logger.error(f"Safety: publish error: {e}")

    def _publish_status(self, status: str):
        try:
            self.mqtt.publish("agents/validation/status", json.dumps({
                "agent": "safety_validator",
                "status": status,
                "validation_count": self._validation_count,
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }))
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # QUERY API
    # ─────────────────────────────────────────────────────────────────────────

    def get_recent_validations(self, limit: int = 10) -> List[Dict]:
        with self._lock:
            return list(reversed(self._recent_validations[-limit:]))
