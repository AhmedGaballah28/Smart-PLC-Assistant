import json
import logging
from typing import Dict, Any
from pydantic import BaseModel, Field

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore

from agents.state import IncidentState
from agents.tools.mcp_client import get_mcp_tools
from agents.tools.simulation_tools import run_digital_twin

logger = logging.getLogger(__name__)

class SimulationOutput(BaseModel):
    go_no_go: str = Field(description="'GO' if safe to proceed, 'NO_GO' if unsafe risk.")
    confidence: float = Field(description="Confidence of the prediction 0.0 to 100.0")
    cycle_time_delta: float = Field(description="Predicted cycle time change in seconds.")
    throughput_delta_pct: float = Field(description="Predicted throughput change as percentage.")

SIMULATION_SYSTEM_PROMPT = """You are an elite simulation analysis agent for industrial automation.

Your MUST use the 'run_digital_twin' tool to predict what will happen if we apply the proposed PLC parameters to the factory.

After getting the digital twin results, you MUST log the simulation result to the database using the 'save_simulation_result' tool.
IMPORTANT: The user message will provide the event's correlation_id.
Set:
- event_id: "SIM-{correlation_id}" (replacing {correlation_id} with the actual id)
- correlation_id: "{correlation_id}" (replacing {correlation_id} with the actual id)
- go_no_go: Output from twin (e.g. "GO")
- confidence: Output from twin
- predicted_cycle_time_delta: Output from twin
- predicted_throughput_delta: Output from twin

Think carefully about the twin's output before declaring GO or NO_GO.
"""

llm = ChatGroq(model_name="llama-3.3-70b-versatile", temperature=0)

tools = [run_digital_twin]
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
    
    logger.info(f"Simulation node starting for {station_id} (Alert: {correlation_id})")
    
    user_prompt = f"""Run simulation for station {station_id} with these proposed parameters:

{json.dumps(params)}

Correlation ID for this incident: {correlation_id}"""
    
    try:
        result = simulation_agent.invoke({"messages": [("user", user_prompt)]})
        
        structured_result = result["structured_response"]
        
        impact = {
            "source": "react_simulation_agent",
            "cycle_time_delta": structured_result.cycle_time_delta,
            "throughput_delta_pct": structured_result.throughput_delta_pct,
            "safe": True if structured_result.go_no_go == "GO" else False,
            "confidence": structured_result.confidence
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