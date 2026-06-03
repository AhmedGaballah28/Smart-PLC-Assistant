import os
import json
import logging
from typing import Dict, Any
from pydantic import BaseModel, Field

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore

from agents.state import IncidentState
from agents.tools.mcp_client import get_mcp_tools
from agents.tools.simulation_tools import run_digital_twin, generate_simulation_plots

logger = logging.getLogger(__name__)

class SimulationOutput(BaseModel):
    go_no_go: str = Field(description="'GO' if safe to proceed, 'NO_GO' if unsafe risk.")
    confidence: float = Field(description="Confidence of the prediction 0.0 to 100.0")
    cycle_time_delta: float = Field(description="Predicted cycle time change in seconds.")
    throughput_delta_pct: float = Field(description="Predicted throughput change as percentage.")
    reasoning: str = Field(default="", description="Brief explanation of the prediction.")

SIMULATION_SYSTEM_PROMPT = """You are an elite simulation analysis agent for industrial automation.

You have access to a PHYSICS-BASED simulation engine that uses first-principles models:
- Thermal dynamics (1st-order ODE with transfer function)
- Belt dynamics (speed, slip probability, brownout risk)
- Production line model (throughput, bottleneck analysis, pass rate)

WORKFLOW:
1. Use the 'run_digital_twin' tool with the station_id and a JSON string containing:
   - The proposed repair parameters (action, speed_factor, clear_fault, etc.)
   - Current sensor context (temperature, fault_type, severity_level, etc.)
   
2. Analyze the physics model output — it includes before/after comparisons,
   transfer function parameters, and per-model GO/NO_GO verdicts.

3. Optionally use 'generate_simulation_plots' to create visual before/after charts.

4. MUST log the simulation result to the database using the 'save_simulation_result' tool.
   IMPORTANT: The user message will provide the event's correlation_id.
   Set:
   - event_id: "SIM-{correlation_id}"
   - correlation_id: the actual correlation_id
   - go_no_go: Output from simulation
   - confidence: Output from simulation
   - predicted_cycle_time_delta: Output from simulation
   - predicted_throughput_delta: Output from simulation

Think carefully about the model outputs before declaring GO or NO_GO.
A NO_GO from any physics model should be taken seriously.
"""

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite",
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    vertexai=True,
    project="graduation-project-498314",
    location="global"
)

tools = [run_digital_twin, generate_simulation_plots]
try:
    tools.extend(get_mcp_tools())
except Exception as e:
    logger.warning(f"Could not load MCP tools for simulation: {e}")

simulation_agent = create_react_agent(llm, tools, prompt=SIMULATION_SYSTEM_PROMPT, response_format=SimulationOutput)

def run_simulation_node(state: IncidentState, config: RunnableConfig, *, store: BaseStore) -> IncidentState:
    state["current_agent"] = "SIMULATION"
    
    proposals = state.get("repair_proposals", [])
    params = proposals[0].get("parameters_to_change", {}) if proposals else {}
    station_id = state.get("station_id", "unknown")
    correlation_id = state.get("alert_id", "unknown")
    sensor_data = state.get("sensor_data", {})
    
    logger.info(f"Simulation node starting for {station_id} (Alert: {correlation_id})")
    
    # ── Extract real sensor values from the enriched alert payload ──
    # The aggregator now includes a sensor_snapshot with live readings
    # (e.g. {"temperature": 57.4, "vibration": 12.3, "power_consumption": 2.8})
    # plus fault context (active_faults, fault_active).
    sim_input = dict(params)
    if isinstance(sensor_data, dict):
        # 1. Inject real-time sensor readings from the snapshot
        snapshot = sensor_data.get("sensor_snapshot", {})
        for k, v in snapshot.items():
            if k not in sim_input and isinstance(v, (int, float)):
                # Map aggregator field names to simulation engine names
                mapped = k
                if k == "power_consumption":
                    mapped = "power"
                sim_input[mapped] = v

        # 2. Use the alert's current value for the specific triggered field
        field = sensor_data.get("field", "")
        current_val = sensor_data.get("current")
        if field and current_val is not None:
            mapped_field = field
            if field == "power_consumption":
                mapped_field = "power"
            sim_input[mapped_field] = current_val

        # 3. Infer fault type from active_faults or alert field
        active_faults = sensor_data.get("active_faults", [])
        if active_faults and "fault_type" not in sim_input:
            sim_input["fault_type"] = active_faults[0]
        elif field in ("temperature",) and "fault_type" not in sim_input:
            sim_input["fault_type"] = "overheat"
        elif field in ("vibration",) and "fault_type" not in sim_input:
            sim_input["fault_type"] = "vibration"
        elif field in ("power_consumption", "power") and "fault_type" not in sim_input:
            sim_input["fault_type"] = "power"

        # 4. Map severity string to integer for the physics engine
        sev = sensor_data.get("severity", "")
        if isinstance(sev, str) and "severity_level" not in sim_input:
            sev_map = {"info": 1, "warning": 3, "critical": 4}
            sim_input["severity_level"] = sev_map.get(sev, 3)

        # 5. Pass through any direct keys the engine understands
        for k in ("type", "speed_factor", "fan_speed"):
            if k in sensor_data and k not in sim_input:
                sim_input[k] = sensor_data[k]

    logger.info(f"Simulation input for {station_id}: {json.dumps(sim_input, default=str)}")
    
    user_prompt = f"""Run simulation for station {station_id} with these proposed parameters:

{json.dumps(sim_input)}

Correlation ID for this incident: {correlation_id}"""
    
    try:
        result = simulation_agent.invoke({"messages": [("user", user_prompt)]})
        
        structured_result = result["structured_response"]
        
        impact = {
            "source": "physics_simulation_agent",
            "cycle_time_delta": structured_result.cycle_time_delta,
            "throughput_delta_pct": structured_result.throughput_delta_pct,
            "safe": True if structured_result.go_no_go == "GO" else False,
            "confidence": structured_result.confidence,
            "reasoning": structured_result.reasoning,
        }
        state["simulation_impact"] = impact
        
        # Also write semantic memory to LangGraph store
        store.put(("simulations", station_id), correlation_id, impact)
        
    except Exception as e:
        logger.error(f"Simulation agent failed: {e}")
        state["simulation_impact"] = {
            "source": "error",
            "cycle_time_delta": 0.0,
            "throughput_delta_pct": 0.0,
            "safe": False,
            "confidence": 0.0,
            "error_msg": str(e)
        }

    return state
