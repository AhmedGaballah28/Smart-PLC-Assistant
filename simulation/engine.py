"""
Factory Simulation Engine — Orchestrator.

Maps station_id + fault context → appropriate physics models,
runs before/after scenarios, and produces a unified verdict.

This is the single entry point used by the LangGraph simulation tool.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from simulation.models.base_model import ComparisonResult
from simulation.models.thermal_model import ThermalModel
from simulation.models.belt_model import BeltModel
from simulation.models.production_model import ProductionLineModel
from simulation.station_params import get_station_type, THERMAL_PARAMS, BELT_PARAMS

logger = logging.getLogger(__name__)

# Singleton model instances (stateless, safe to reuse)
_thermal = ThermalModel()
_belt = BeltModel()
_production = ProductionLineModel()

# Map fault types to the models that should analyze them
FAULT_TO_MODELS = {
    "overheat": [_thermal, _production],
    "power": [_belt, _production],
    "belt_slip": [_belt, _production],
    "vibration": [_belt, _production],
    "sensor_drift": [_production],
    "gripper_failure": [_production],
    "vision_error": [_production],
    "sorter_jam": [_production],
    "misroute": [_production],
    "positioner_jam": [_production],
    "cnc_jam": [_production],
    "material_error": [_production],
}


def _detect_fault_type(sensor_data: dict) -> str:
    """Infer the primary fault type from sensor/telemetry data."""
    alert_type = sensor_data.get("type", "")
    fault_type = sensor_data.get("fault_type", "")

    # Direct match
    if fault_type in FAULT_TO_MODELS:
        return fault_type

    # Infer from alert type keywords
    lower = (alert_type + " " + fault_type).lower()
    if "overheat" in lower or "thermal" in lower or "temperature" in lower:
        return "overheat"
    if "power" in lower or "brownout" in lower or "voltage" in lower:
        return "power"
    if "slip" in lower or "belt" in lower or "stutter" in lower:
        return "belt_slip"
    if "vibration" in lower:
        return "vibration"
    if "sensor" in lower or "drift" in lower:
        return "sensor_drift"
    if "gripper" in lower or "vacuum" in lower:
        return "gripper_failure"
    if "vision" in lower or "camera" in lower:
        return "vision_error"
    if "sort" in lower or "jam" in lower:
        return "sorter_jam"

    return "overheat"  # default to thermal analysis


def _extract_current_state(
    sensor_data: dict, fault_type: str, station_id: str
) -> Dict[str, Any]:
    """Build model input state from raw telemetry/alert payload."""
    state = {}

    # Temperature
    temp = sensor_data.get("temperature", sensor_data.get("value"))
    if isinstance(temp, (int, float)):
        state["temperature"] = float(temp)

    # Fault severity
    severity = sensor_data.get("severity_level", sensor_data.get("severity", 0))
    if isinstance(severity, str):
        severity = {"info": 1, "warning": 2, "critical": 3}.get(severity, 2)
    state["fault_severity"] = int(severity) if isinstance(severity, (int, float)) else 2

    # Speed and fan
    state["speed_factor"] = sensor_data.get("speed_factor", 1.0)
    state["fan_speed"] = sensor_data.get("fan_speed", 50.0)

    # Belt params
    state["speed_cmd_pct"] = sensor_data.get("speed_cmd_pct", 100.0)
    state["tension_pct"] = sensor_data.get("tension_pct", 70.0)
    state["slip_severity"] = sensor_data.get("slip_severity", 0)
    state["power_severity"] = sensor_data.get("power_severity", 0)

    # For production model: build faults dict
    if fault_type in ("overheat", "power", "belt_slip", "vibration"):
        sev = state["fault_severity"]
        state["faults"] = {station_id: {fault_type: sev}}
        if fault_type == "power":
            state["power_severity"] = sev
        if fault_type == "belt_slip":
            state["slip_severity"] = sev
    else:
        state["faults"] = {station_id: {fault_type: state["fault_severity"]}}

    state["line_speed_multiplier"] = sensor_data.get("line_speed_multiplier", 1.0)

    return state


def run_simulation(
    station_id: str,
    sensor_data: Dict[str, Any],
    proposed_params: Dict[str, Any],
    duration_s: float = 300.0,
) -> Dict[str, Any]:
    """
    Main entry point: run all relevant models for a proposed repair.

    Args:
        station_id: e.g. "stn1", "mc_a"
        sensor_data: current telemetry/alert payload
        proposed_params: the repair agent's proposed parameter changes
        duration_s: simulation horizon in seconds

    Returns:
        dict with:
            go_no_go: "GO" / "NO_GO" / "INCONCLUSIVE"
            confidence: 0-100
            reasoning: explanation string
            models: {model_name: ComparisonResult.to_dict()}
            predicted_cycle_time_delta: float
            predicted_throughput_delta: float
            predicted_fault_risk_delta: float
    """
    fault_type = _detect_fault_type(sensor_data)
    current_state = _extract_current_state(sensor_data, fault_type, station_id)

    # Ensure clear_fault is set if the proposal implies it
    REPAIR_KEYS = {
        "spindle_speed", "spindle_speed_rpm", "Spindle_Speed_RPM",
        "fan_speed", "aux_fan_speed", "aux_enclosure_fan_speed_percent", "aux_fan_speed_percent",
        "target_belt_speed", "belt_tension", "speed_factor", "line_speed_multiplier",
    }
    if any(k in proposed_params for k in REPAIR_KEYS):
        proposed_params.setdefault("clear_fault", True)

    models = FAULT_TO_MODELS.get(fault_type, [_production])
    results: List[ComparisonResult] = []

    for model in models:
        try:
            result = model.simulate(station_id, current_state, proposed_params, duration_s)
            results.append(result)
            logger.info(
                f"  {model.model_name}: {result.go_no_go} "
                f"(confidence {result.confidence:.0f}%) — {result.reasoning}"
            )
        except Exception as e:
            logger.error(f"  {model.model_name} failed: {e}")

    if not results:
        return {
            "go_no_go": "INCONCLUSIVE",
            "confidence": 0.0,
            "reasoning": "All simulation models failed.",
            "models": {},
            "predicted_cycle_time_delta": 0.0,
            "predicted_throughput_delta": 0.0,
            "predicted_fault_risk_delta": 0.0,
            "source": "simulation_engine",
        }

    # Aggregate: if ANY model says NO_GO, overall is NO_GO
    no_go_results = [r for r in results if r.go_no_go == "NO_GO"]
    go_results = [r for r in results if r.go_no_go == "GO"]

    if no_go_results:
        worst = max(no_go_results, key=lambda r: r.confidence)
        go_no_go = "NO_GO"
        confidence = worst.confidence
        reasoning = f"BLOCKED by {worst.before.model_name}: {worst.reasoning}"
    elif go_results:
        best = max(go_results, key=lambda r: r.confidence)
        go_no_go = "GO"
        confidence = sum(r.confidence for r in go_results) / len(go_results)
        reasoning = " | ".join(f"{r.before.model_name}: {r.reasoning}" for r in go_results)
    else:
        go_no_go = "INCONCLUSIVE"
        confidence = 30.0
        reasoning = "Models returned inconclusive results."

    # Extract key deltas from model results
    cycle_time_delta = 0.0
    throughput_delta = 0.0
    fault_risk_delta = 0.0

    for r in results:
        if "temperature_delta" in r.deltas:
            # Temperature drop → less fault risk
            fault_risk_delta += r.deltas["temperature_delta"] * -1.5  # heuristic
        if "throughput_delta_ppm" in r.deltas:
            throughput_delta += r.deltas["throughput_delta_ppm"]
        if "throughput_delta_pct" in r.deltas:
            cycle_time_delta += r.deltas.get("bottleneck_cycle_delta_s", 0.0)

    return {
        "go_no_go": go_no_go,
        "confidence": round(confidence, 1),
        "reasoning": reasoning,
        "models": {r.before.model_name: r.to_dict() for r in results},
        "predicted_cycle_time_delta": round(cycle_time_delta, 2),
        "predicted_throughput_delta": round(throughput_delta, 2),
        "predicted_fault_risk_delta": round(fault_risk_delta, 2),
        "source": "simulation_engine",
        "fault_type_detected": fault_type,
        "station_id": station_id,
    }
