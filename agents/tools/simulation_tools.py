"""
Digital Twin MQTT Tools — @tool wrapper for simulation.

Allows the simulation agent to publish parameter proposals to the Digital Twin
(factory/sim/request) and wait for predictive results (agents/simulation/result).
Includes heuristic math fallback if the twin is offline.
"""

import json
import logging
import time
from typing import Dict, Any

from langchain_core.tools import tool

from core.mqtt_client import MQTTClient

# We use the generic topics for simulation as defined in docs/architecture,
# but can be adapted to factory/{line_id}/{station_id}/sim if needed.
TOPIC_SIM_REQUEST = "factory/sim/request"
TOPIC_SIM_RESULT = "agents/simulation/result"

logger = logging.getLogger(__name__)


def _math_fallback(station_id: str, proposed_parameters_json: str) -> str:
    """Heuristic fallback for simulation when MQTT is offline."""
    try:
        params = json.loads(proposed_parameters_json)
        # Basic heuristic logic
        if params.get("action") == "REDUCE_SPEED":
            predicted_cycle_time_delta = 2.5
            predicted_throughput_delta = -1.2
            predicted_fault_risk_delta = -40.0
            confidence = 85.0
        elif params.get("action") == "INCREASE_TENSION":
            predicted_cycle_time_delta = 0.0
            predicted_throughput_delta = 0.0
            predicted_fault_risk_delta = -20.0
            confidence = 75.0
        else:
            predicted_cycle_time_delta = 0.5
            predicted_throughput_delta = -0.1
            predicted_fault_risk_delta = -15.0
            confidence = 60.0

        return json.dumps({
            "go_no_go": "GO",
            "confidence": confidence,
            "predicted_cycle_time_delta": predicted_cycle_time_delta,
            "predicted_throughput_delta": predicted_throughput_delta,
            "predicted_fault_risk_delta": predicted_fault_risk_delta,
            "source": "heuristic_fallback"
        })
    except json.JSONDecodeError:
        return json.dumps({"go_no_go": "NO_GO", "confidence": 0.0, "source": "error", "error": "Invalid JSON parameters"})


@tool
def run_digital_twin(station_id: str, proposed_parameters: str) -> str:
    """Run a high-fidelity Digital Twin simulation via MQTT.

    Publishes the proposed parameters to the simulation topic and waits up to
    5 seconds for a response. If the twin is offline, falls back to a math-based
    heuristic estimation.

    Args:
        station_id: Target station (e.g., '11', '1A', '22', 'mc_a').
        proposed_parameters: JSON string of the exact parameters to change.
            Example: '{"action": "REDUCE_SPEED", "value": 1500}'

    Returns:
        JSON string containing the simulation predictions:
        go_no_go ("GO" or "NO_GO"), confidence (0-100), and delta predictions
        for cycle_time, throughput, and fault_risk.
    """
    client = MQTTClient(client_id=f"sim_tool_{int(time.time())}")
    result_data: Dict[str, Any] = {}
    received = False

    def on_message(topic, payload):
        nonlocal result_data, received
        if isinstance(payload, dict):
            result_data = payload
        else:
            try:
                result_data = json.loads(payload)
            except:
                result_data = {"raw": payload}
        received = True

    try:
        # Try to connect
        if not client.connect():
            logger.warning("Sim @tool: MQTT connect failed. Using math fallback.")
            return _math_fallback(station_id, proposed_parameters)

        # Build payload
        try:
            params = json.loads(proposed_parameters)
        except json.JSONDecodeError:
            return json.dumps({"go_no_go": "NO_GO", "error": "Invalid proposed_parameters JSON"})

        req_payload = {
            "station_id": station_id,
            "parameters": params,
            "timestamp": time.time()
        }

        # Subscribe and publish
        client.subscribe(TOPIC_SIM_RESULT, on_message)
        client.publish(TOPIC_SIM_REQUEST, req_payload)

        # Wait up to 5s for response
        logger.info(f"Sim @tool: Waiting up to 5s for digital twin response on {TOPIC_SIM_RESULT}...")
        start_wait = time.time()
        while time.time() - start_wait < 5.0:
            if received:
                break
            time.sleep(0.1)

        if not received:
            logger.warning("Sim @tool: Twin timeout. Using math fallback.")
            return _math_fallback(station_id, proposed_parameters)

        result_data["source"] = "digital_twin_mqtt"
        logger.info(f"Sim @tool: Received response from digital twin: {result_data.get('go_no_go')}")
        return json.dumps(result_data)

    except Exception as e:
        logger.error(f"Sim @tool: Unexpected error: {e}")
        return _math_fallback(station_id, proposed_parameters)
    finally:
        client.disconnect()
