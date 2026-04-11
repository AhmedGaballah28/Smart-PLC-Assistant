"""
Diagnostic Agent
Listens for Monitor Agent alerts and uses Google Gemini (via LangChain)
+ ChromaDB RAG to diagnose the root cause of each fault.
"""

import json
import logging
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class DiagnosticAgent:
    """
    Diagnoses factory faults from Monitor Agent alerts.

    Flow:
      1. Listens on agents/monitor/alert
      2. For each alert: queries ChromaDB knowledge base for similar faults
      3. Calls Google Gemini LLM with alert + RAG context
      4. Publishes structured diagnosis to agents/diagnostic/report

    MQTT IN:  agents/monitor/alert
    MQTT OUT: agents/diagnostic/report
              agents/diagnostic/status
    """

    def __init__(self, mqtt_client, llm_client=None, kb_client=None,
                 on_diagnosis_callback=None):
        self.mqtt = mqtt_client
        self.llm = llm_client          # GeminiLLMClient instance
        self.kb = kb_client            # KnowledgeBaseClient instance
        self.on_diagnosis_callback = on_diagnosis_callback
        self._running = False
        self._lock = threading.Lock()
        self._diagnosis_count = 0
        self._recent_diagnoses: List[Dict] = []  # Last 20 diagnoses
        self._processing = False

    def start(self):
        self._running = True
        logger.info("🔬 Diagnostic Agent starting...")
        self.mqtt.subscribe("agents/monitor/alert", self._on_alert)
        self._publish_status("online")
        logger.info("✅ Diagnostic Agent running — awaiting alerts")

    def stop(self):
        self._running = False
        self._publish_status("offline")

    # ─────────────────────────────────────────────────────────────────────────
    # ALERT HANDLER
    # ─────────────────────────────────────────────────────────────────────────

    def _on_alert(self, topic: str, payload: Any):
        if not self._running:
            return
        try:
            if isinstance(payload, str):
                alert = json.loads(payload)
            elif isinstance(payload, dict):
                alert = payload
            else:
                return

            # Don't stack up concurrent diagnoses
            if self._processing:
                logger.debug("Diagnostic: busy, skipping alert")
                return

            thread = threading.Thread(
                target=self._diagnose_alert,
                args=(alert,),
                daemon=True,
                name=f"Diagnose-{alert.get('alert_id', '?')}",
            )
            thread.start()

        except Exception as e:
            logger.error(f"Diagnostic: error handling alert: {e}")

    def _diagnose_alert(self, alert: dict):
        self._processing = True
        try:
            logger.info(f"🔬 Diagnosing alert: {alert.get('alert_id')} "
                        f"[{alert.get('station_id')}] {alert.get('metric')}")

            # ── Step 1: Build sensor context ──
            sensor_data = {
                "station_id": alert.get("station_id"),
                "station_name": alert.get("station_name"),
                "alert_type": alert.get("alert_type"),
                "level": alert.get("level"),
                "metric": alert.get("metric"),
                "value": alert.get("value"),
                "unit": alert.get("unit"),
                "threshold": alert.get("threshold"),
                "station_state": alert.get("station_state"),
                "faults_active": alert.get("faults_active", []),
                "sensor_snapshot": alert.get("sensor_snapshot", {}),
            }

            # ── Step 2: RAG — fetch relevant fault knowledge ──
            rag_context = ""
            if self.kb:
                try:
                    query = (f"{alert.get('station_name', '')} "
                             f"{alert.get('metric', '')} "
                             f"{alert.get('alert_type', '')}")
                    results = self.kb.search(query, n_results=3)
                    rag_context = self._format_rag_results(results)
                    logger.info(f"   📚 RAG: {len(results)} relevant docs found")
                except Exception as e:
                    logger.warning(f"   RAG query failed: {e}")

            # ── Step 3: LLM Diagnosis ──
            if self.llm:
                try:
                    diagnosis_text = self.llm.diagnose_fault(sensor_data, rag_context)
                    diagnosis = self._parse_diagnosis(diagnosis_text)
                except Exception as e:
                    logger.error(f"   LLM error: {e}")
                    diagnosis = self._rule_based_diagnosis(sensor_data)
            else:
                # Fallback — rule-based diagnosis without LLM
                diagnosis = self._rule_based_diagnosis(sensor_data)

            # ── Step 4: Build final report ──
            report = {
                "diagnosis_id": f"DX-{self._diagnosis_count + 1:04d}",
                "alert_id": alert.get("alert_id"),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "station_id": alert.get("station_id"),
                "station_name": alert.get("station_name"),
                "alert_type": alert.get("alert_type"),
                "level": alert.get("level"),
                "sensor_data": sensor_data,
                "rag_context_used": bool(rag_context),
                "llm_used": bool(self.llm),
                **diagnosis,
            }

            with self._lock:
                self._diagnosis_count += 1
                self._recent_diagnoses.append(report)
                if len(self._recent_diagnoses) > 20:
                    self._recent_diagnoses.pop(0)

            logger.info(f"✅ Diagnosis #{self._diagnosis_count}: "
                        f"{report.get('root_cause', '?')} "
                        f"(confidence={report.get('confidence', 0)}%)")

            self._publish_diagnosis(report)

            if self.on_diagnosis_callback:
                try:
                    self.on_diagnosis_callback(report)
                except Exception as e:
                    logger.error(f"Diagnosis callback error: {e}")

        except Exception as e:
            logger.error(f"Diagnostic: unhandled error: {e}")
        finally:
            self._processing = False

    # ─────────────────────────────────────────────────────────────────────────
    # PARSING + FALLBACK
    # ─────────────────────────────────────────────────────────────────────────

    def _parse_diagnosis(self, text: str) -> dict:
        """Try to parse LLM JSON response; fall back to text extraction."""
        try:
            # Strip markdown code fences if present
            clean = text.strip()
            if clean.startswith("```"):
                lines = clean.split("\n")
                clean = "\n".join(lines[1:-1])
            return json.loads(clean)
        except Exception:
            pass

        # Try to find JSON blob inside text
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception:
            pass

        # Fallback structured response
        return {
            "root_cause": "Analysis from LLM (unstructured)",
            "confidence": 60,
            "severity": "MEDIUM",
            "evidence": [text[:500]],
            "reasoning": text[:1000],
            "alternative_causes": [],
            "urgency": "MEDIUM",
            "recommended_action": "Review LLM response and inspect station manually.",
        }

    def _rule_based_diagnosis(self, sensor_data: dict) -> dict:
        """Rule-based fallback when LLM is unavailable."""
        metric = sensor_data.get("metric", "")
        value = sensor_data.get("value", 0)
        level = sensor_data.get("level", "WARNING")
        station = sensor_data.get("station_name", "Unknown")

        rules = {
            "temperature": {
                "root_cause": "Motor overheating — possible bearing wear or blocked ventilation",
                "recommended_action": "Check motor cooling fan, inspect bearings, reduce duty cycle",
                "evidence": [f"Temperature {value}°C exceeds limit"],
            },
            "vibration": {
                "root_cause": "Mechanical vibration anomaly — bearing defect or belt misalignment",
                "recommended_action": "Inspect belt tension, check bearing condition, realign pulleys",
                "evidence": [f"Vibration {value} mm/s exceeds threshold"],
            },
            "power_kw": {
                "root_cause": "Power consumption elevated — possible motor overload or electrical fault",
                "recommended_action": "Check load conditions, inspect drive electronics, verify voltage",
                "evidence": [f"Power draw {value} kW exceeds normal range"],
            },
            "emergency": {
                "root_cause": f"Emergency stop triggered: {value}",
                "recommended_action": "Investigate root cause, clear fault, verify safe restart",
                "evidence": [f"Emergency stop active on {station}"],
            },
            "fault": {
                "root_cause": f"Active fault detected: {value}",
                "recommended_action": "Address reported fault, clear fault state, monitor after restart",
                "evidence": [f"Fault: {value}"],
            },
        }

        rule = rules.get(metric, {
            "root_cause": f"Anomaly detected: {metric}={value}",
            "recommended_action": "Inspect station and review sensor data",
            "evidence": [f"{metric} out of normal range"],
        })

        return {
            "root_cause": rule["root_cause"],
            "confidence": 70 if level == "CRITICAL" else 55,
            "severity": level,
            "evidence": rule["evidence"],
            "reasoning": f"Rule-based diagnosis for {station}: {metric} reading of {value}",
            "alternative_causes": ["Sensor calibration drift", "Intermittent electrical connection"],
            "urgency": "HIGH" if level == "CRITICAL" else "MEDIUM",
            "recommended_action": rule["recommended_action"],
        }

    def _format_rag_results(self, results: list) -> str:
        if not results:
            return "No relevant knowledge base entries found."
        parts = ["=== Knowledge Base Context ==="]
        for i, r in enumerate(results, 1):
            doc = r.get("document", "")
            meta = r.get("metadata", {})
            parts.append(f"\n[{i}] {meta.get('title', 'Reference')}:")
            parts.append(doc[:500])
        return "\n".join(parts)

    # ─────────────────────────────────────────────────────────────────────────
    # MQTT
    # ─────────────────────────────────────────────────────────────────────────

    def _publish_diagnosis(self, report: dict):
        try:
            self.mqtt.publish("agents/diagnostic/report", json.dumps(report))
        except Exception as e:
            logger.error(f"Diagnostic: publish error: {e}")

    def _publish_status(self, status: str):
        try:
            self.mqtt.publish("agents/diagnostic/status", json.dumps({
                "agent": "diagnostic",
                "status": status,
                "diagnosis_count": self._diagnosis_count,
                "llm_available": bool(self.llm),
                "kb_available": bool(self.kb),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }))
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # QUERY API
    # ─────────────────────────────────────────────────────────────────────────

    def get_recent_diagnoses(self, limit: int = 10) -> List[Dict]:
        with self._lock:
            return list(reversed(self._recent_diagnoses[-limit:]))

    def get_diagnosis_count(self) -> int:
        return self._diagnosis_count

    def is_processing(self) -> bool:
        return self._processing
