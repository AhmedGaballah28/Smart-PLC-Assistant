import json
import uuid
import time
import signal
import logging
import sys

# Ensure proper path loading if run standalone
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Enable LangChain verbose tracing — shows tool calls, LLM inputs/outputs
from langchain_core.globals import set_verbose, set_debug
set_verbose(True)

from core.mqtt_client import MQTTClient
from core.repository import DbRepository
from agents.supervisor_graph import supervisor_app

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

class MonitorAgent:
    def __init__(self):
        self.mqtt = MQTTClient(client_id="monitor_agent_daemon")
        self.running = False
        self.active_alerts = set() # Dampening to avoid spamming the graph

    def start(self):
        if not self.mqtt.connect():
            logger.error("MonitorAgent failed to connect to MQTT.")
            return
            
        # Instead of raw sensors, we listen to the Aggregator's anomaly topics
        # The realtime_aggregator.py handles all z-score, baseline, and threshold logic!
        self.mqtt.subscribe("agents/monitor/+/alert", self._on_aggregator_alert)
        self.running = True
        logger.info("MonitorAgent daemon listening for Aggregator alerts...")
        
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.stop()
            
    def stop(self):
        self.running = False
        self.mqtt.disconnect()
        logger.info("MonitorAgent shutdown gracefully.")
        
    def _on_aggregator_alert(self, topic: str, payload: dict | str):
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except json.JSONDecodeError:
                return
                
        # Aggregator publishes to: agents/monitor/{line_id}/alert
        # Payload format: { "station": "stn1", "type": "threshold", "severity": "critical",
        #                    "field": "temperature", "message": "temperature=72 exceeds CRITICAL (70)" }
        
        station_id = payload.get("station", "unknown_station")
        # line_id is NOT in the payload — extract from MQTT topic
        topic_parts = topic.split("/")
        line_id = topic_parts[2] if len(topic_parts) >= 4 else "unknown_line"
        metric_str = payload.get("field", payload.get("message", "unknown_metric"))
        alert_type = payload.get("type", "UNKNOWN_ALERT")
        
        # Simple dampening
        damp_key = f"{line_id}_{station_id}_{metric_str}_{alert_type}"
        if damp_key in self.active_alerts:
            # Maybe clear older alerts after some time, but simple set is fine for now
            return
        self.active_alerts.add(damp_key)
        
        alert_id = str(uuid.uuid4())
        logger.warning(f"AGGREGATOR ANOMALY RECEIVIED: {alert_type} on {line_id}/{station_id}")
        
        # Log to SQLite
        try:
            DbRepository.save_monitor_alert(
                event_id=f"ALT-{alert_id}",
                correlation_id=alert_id,
                alert_type=alert_type,
                message=f"Aggregator Alert: {metric_str} -> {alert_type}",
                severity="critical", # Up to graph to refine
                line_id=line_id,
                station_id=station_id,
                payload_json=payload
            )
        except Exception as e:
            logger.error(f"Failed to log alert to DB: {e}")
            
        # Trigger LangGraph (The orchestration begins!)
        initial_state = {
            "alert_id": alert_id,
            "line_id": line_id,
            "station_id": station_id,
            "sensor_data": payload,
            "current_agent": "MONITOR"
        }
        
        logger.info(f"Triggering LangGraph Supervisor for {damp_key}...")
        try:
            # Checkpointer thread memory
            supervisor_app.invoke(initial_state, config={"configurable": {"thread_id": alert_id}})
            logger.info(f"LangGraph execution finished/paused for alert {alert_id}")
        except Exception as e:
            logger.error(f"LangGraph execution crashed: {e}")

if __name__ == "__main__":
    agent = MonitorAgent()
    def handle_sigint(sig, frame):
        agent.stop()
        sys.exit(0)
        
    signal.signal(signal.SIGINT, handle_sigint)
    agent.start()
