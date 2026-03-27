"""
MQTT Client Module
Handles all MQTT communication for Smart PLC Assistant.
"""

import json
import time
import logging
import threading
from datetime import datetime
from typing import Callable, Optional, Any, Dict

import paho.mqtt.client as mqtt

from config.settings import (
    MQTT_BROKER_HOST,
    MQTT_BROKER_PORT,
    MQTT_USERNAME,
    MQTT_PASSWORD,
    MQTT_CLIENT_ID_PREFIX
)

logger = logging.getLogger(__name__)


class MQTTClient:
    """
    MQTT Client for Smart PLC Assistant.
    """

    def __init__(self, client_id: str):
        self.client_id = f"{MQTT_CLIENT_ID_PREFIX}_{client_id}_{int(time.time())}"
        self.client = mqtt.Client(client_id=self.client_id)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message

        self._topic_callbacks: Dict[str, Callable] = {}
        self._general_callback: Optional[Callable] = None

        self.is_connected = False
        self._connection_event = threading.Event()

        if MQTT_USERNAME and MQTT_PASSWORD:
            self.client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

        logger.info(f"MQTT Client created: {self.client_id}")

    def connect(self) -> bool:
        try:
            logger.info(f"Connecting to MQTT broker at {MQTT_BROKER_HOST}:{MQTT_BROKER_PORT}...")
            self.client.connect(MQTT_BROKER_HOST, MQTT_BROKER_PORT, keepalive=60)
            self.client.loop_start()
            connected = self._connection_event.wait(timeout=10)
            if connected:
                logger.info("✅ Connected to MQTT broker!")
            else:
                logger.error("❌ Connection timeout!")
            return connected
        except ConnectionRefusedError:
            logger.error("❌ Connection refused! Is Mosquitto running?")
            return False
        except Exception as e:
            logger.error(f"❌ Connection failed: {e}")
            return False

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()
        self.is_connected = False
        self._connection_event.clear()
        logger.info("Disconnected from MQTT broker")

    def publish(self, topic: str, data: Any, retain: bool = False) -> bool:
        try:
            if isinstance(data, dict):
                data["timestamp"] = datetime.now().isoformat()
                payload = json.dumps(data)
            elif isinstance(data, (list, tuple)):
                payload = json.dumps(data)
            else:
                payload = str(data)

            result = self.client.publish(topic, payload, retain=retain)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                logger.debug(f"📤 Published to {topic}")
                return True
            else:
                logger.error(f"❌ Publish failed on {topic}")
                return False
        except Exception as e:
            logger.error(f"❌ Error publishing to {topic}: {e}")
            return False

    def subscribe(self, topic: str, callback: Optional[Callable] = None):
        self.client.subscribe(topic)
        if callback:
            self._topic_callbacks[topic] = callback
        logger.info(f"📥 Subscribed to: {topic}")

    def set_general_callback(self, callback: Callable):
        self._general_callback = callback

    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.is_connected = True
            self._connection_event.set()
            logger.info(f"✅ MQTT Connected: {self.client_id}")
            for topic in self._topic_callbacks:
                self.client.subscribe(topic)
        else:
            error_messages = {
                1: "Incorrect protocol version",
                2: "Invalid client identifier",
                3: "Server unavailable",
                4: "Bad username or password",
                5: "Not authorized"
            }
            msg = error_messages.get(rc, f"Unknown error: {rc}")
            logger.error(f"❌ MQTT Connection failed: {msg}")

    def _on_disconnect(self, client, userdata, rc):
        self.is_connected = False
        self._connection_event.clear()
        if rc != 0:
            logger.warning(f"⚠️ Unexpected disconnect (code: {rc})")

    def _on_message(self, client, userdata, msg):
        try:
            raw_payload = msg.payload.decode("utf-8")
            try:
                data = json.loads(raw_payload)
            except json.JSONDecodeError:
                data = raw_payload

            for subscribed_topic, callback in self._topic_callbacks.items():
                if mqtt.topic_matches_sub(subscribed_topic, msg.topic):
                    callback(msg.topic, data)

            if self._general_callback:
                self._general_callback(msg.topic, data)

        except Exception as e:
            logger.error(f"❌ Error processing message on {msg.topic}: {e}")


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def create_sensor_message(sensor_name: str, value: float, unit: str) -> dict:
    return {
        "sensor": sensor_name,
        "value": round(value, 2),
        "unit": unit,
        "quality": "good"
    }


def create_alert_message(alert_id: str, severity: str, parameter: str,
                         value: float, threshold: float, message: str) -> dict:
    return {
        "alert_id": alert_id,
        "severity": severity,
        "parameter": parameter,
        "current_value": value,
        "threshold": threshold,
        "message": message
    }


def create_approval_request(request_id: str, diagnosis: dict,
                            repair_proposal: dict, validation: dict,
                            simulation: dict) -> dict:
    return {
        "request_id": request_id,
        "type": "approval_request",
        "requires": "HUMAN_DECISION",
        "diagnosis": diagnosis,
        "repair_proposal": repair_proposal,
        "validation_result": validation,
        "simulation_result": simulation,
        "options": ["APPROVE", "REJECT", "MODIFY"],
        "message": "Human approval required before executing this change."
    }