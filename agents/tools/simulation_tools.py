"""
Simulation Tools — Physics-based + MQTT Digital Twin.

Primary path: run first-principles physics models (thermal, belt, production).
Secondary path: publish to MQTT twin for visual verification.
Fallback: heuristic if both fail.
"""

import json
import logging
import time
from typing import Dict, Any

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _try_physics_engine(station_id: str, sensor_data: dict, proposed_params: dict) -> dict | None:
    """Run local physics simulation engine."""
    try:
        from simulation.engine import run_simulation
        result = run_simulation(station_id, sensor_data, proposed_params, duration_s=300.0)
        if result and result.get("go_no_go"):
            return result
    except ImportError:
        logger.warning("simulation.engine not available")
    except Exception as e:
        logger.error(f"Physics engine error: {e}")
    return None


def _try_mqtt_twin(station_id: str, proposed_params: dict) -> dict | None:
    """Publish to MQTT digital twin and wait for response."""
    try:
        from core.mqtt_client import MQTTClient
    except ImportError:
        return None

    result_data: Dict[str, Any] = {}
    received = False

    def on_message(topic, payload):
        nonlocal result_data, received
        if isinstance(payload, dict):
            result_data = payload
        else:
            try:
                result_data = json.loads(payload)
            except Exception:
                result_data = {"raw": payload}
        received = True

    client = MQTTClient(client_id=f"sim_tool_{int(time.time())}")
    try:
        if not client.connect():
            return None

        req_payload = {
            "station_id": station_id,
            "parameters": proposed_params,
            "timestamp": time.time(),
        }

        client.subscribe("agents/simulation/result", on_message)
        client.publish("factory/sim/request", req_payload)

        start_wait = time.time()
        while time.time() - start_wait < 3.0:
            if received:
                break
            time.sleep(0.1)

        if received:
            result_data["source"] = "digital_twin_mqtt"
            return result_data
        return None
    except Exception:
        return None
    finally:
        client.disconnect()


def _heuristic_fallback(station_id: str, params: dict) -> dict:
    """Last-resort heuristic when no engine is available."""
    action = params.get("action", "")
    if action == "REDUCE_SPEED":
        return {
            "go_no_go": "GO", "confidence": 60.0,
            "predicted_cycle_time_delta": 2.5,
            "predicted_throughput_delta": -1.2,
            "predicted_fault_risk_delta": -40.0,
            "source": "heuristic_fallback",
        }
    if "clear_fault" in params or action == "CLEAR":
        return {
            "go_no_go": "GO", "confidence": 70.0,
            "predicted_cycle_time_delta": -1.0,
            "predicted_throughput_delta": 0.5,
            "predicted_fault_risk_delta": -50.0,
            "source": "heuristic_fallback",
        }
    return {
        "go_no_go": "GO", "confidence": 50.0,
        "predicted_cycle_time_delta": 0.5,
        "predicted_throughput_delta": -0.1,
        "predicted_fault_risk_delta": -15.0,
        "source": "heuristic_fallback",
    }


@tool
def run_digital_twin(station_id: str, proposed_parameters: str) -> str:
    """Run physics-based simulation and/or Digital Twin for a proposed repair.

    Uses first-principles models (thermal ODE, belt dynamics, production line)
    to predict the impact of parameter changes. Falls back to MQTT twin or
    heuristic estimation if the physics engine is unavailable.

    Args:
        station_id: Target station (e.g., 'stn1', 'mc_a', 'stn2', 'stn3').
        proposed_parameters: JSON string with proposed changes AND sensor context.
            Example: '{"action": "REDUCE_SPEED", "speed_factor": 0.7,
                       "temperature": 68.5, "severity_level": 3,
                       "fault_type": "overheat"}'

    Returns:
        JSON string with simulation predictions:
        go_no_go, confidence, reasoning, model details, and delta predictions.
    """
    try:
        params = json.loads(proposed_parameters)
    except json.JSONDecodeError:
        return json.dumps({
            "go_no_go": "NO_GO", "confidence": 0.0,
            "error": "Invalid proposed_parameters JSON",
            "source": "error",
        })

    # Extract sensor context from the params (repair agent embeds it)
    SENSOR_KEYS = {
        "temperature", "vibration", "power", "power_consumption",
        "severity_level", "severity", "fault_type", "type",
        "speed_factor", "fan_speed", "speed_cmd_pct", "tension_pct",
        "slip_severity", "power_severity", "line_speed_multiplier",
        "value", "motor_runtime", "belt_distance",
    }
    sensor_data = {
        k: params.pop(k) for k in list(params.keys())
        if k in SENSOR_KEYS
    }

    # 1. Try physics engine (primary)
    result = _try_physics_engine(station_id, sensor_data, params)
    if result:
        logger.info(f"Simulation result [{result['source']}]: "
                     f"{result['go_no_go']} ({result['confidence']:.0f}%)")
        return json.dumps(result)

    # 2. Try MQTT twin (secondary)
    result = _try_mqtt_twin(station_id, params)
    if result:
        logger.info(f"Twin result: {result.get('go_no_go')}")
        return json.dumps(result)

    # 3. Heuristic fallback
    logger.warning("Using heuristic fallback for simulation")
    return json.dumps(_heuristic_fallback(station_id, params))


@tool
def generate_simulation_plots(station_id: str, simulation_result_json: str) -> str:
    """Generate before/after comparison plots from simulation results.

    Creates matplotlib PNG charts showing thermal trajectories, belt dynamics,
    production KPIs, and a verdict summary card.

    Args:
        station_id: Station that was simulated.
        simulation_result_json: JSON string from run_digital_twin output.

    Returns:
        JSON string with list of saved plot file paths, or error message.
    """
    try:
        sim_result = json.loads(simulation_result_json)
    except json.JSONDecodeError:
        return json.dumps({"error": "Invalid simulation result JSON"})

    try:
        from simulation.plotter import plot_simulation_results
        paths = plot_simulation_results(sim_result, correlation_id=station_id)
        return json.dumps({"plots": paths, "count": len(paths)})
    except ImportError:
        return json.dumps({"error": "matplotlib or simulation.plotter not available"})
    except Exception as e:
        return json.dumps({"error": str(e)})
