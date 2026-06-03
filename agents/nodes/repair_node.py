import json
import logging
from typing import Dict, Any, List
from pydantic import BaseModel, Field

from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore
import os
from agents.state import IncidentState
from agents.tools.mcp_client import get_mcp_tools
from agents.tools.rag_tools import search_factory_manual

logger = logging.getLogger(__name__)

class RepairProposal(BaseModel):
    id: str = Field(description="Unique proposal id.")
    name: str = Field(description="Short name for the repair option.")
    description: str = Field(description="Detailed description of the repair action.")
    parameters_to_change: Dict[str, Any] = Field(description="PLC parameters to change.")
    expected_result: str = Field(description="Expected outcome if applied.")
    risk_level: str = Field(description="Risk level (low, medium, high).")
    trade_offs: str = Field(description="Trade-offs or side effects.")

class RepairProposals(BaseModel):
    proposals: List[RepairProposal] = Field(description="List of proposed repair options.")

REPAIR_SYSTEM_PROMPT = """You are an expert industrial PLC repair agent.

Your job is to propose at least two safe repair options for the diagnosed fault.

For each proposal, provide:
- id
- name
- description
- parameters_to_change (dict)
- expected_result
- risk_level
- trade_offs

Use the RAG search tool (search_factory_manual) to look up safe parameter ranges and repair procedures.

Reject any proposal that is unsafe, out of bounds, or not allowed by factory policy.

IMPORTANT: The user message will provide the event's correlation_id.
After generating proposals, use the 'save_repair_proposal' MCP tool (if available) to log:
- event_id: "REP-{correlation_id}" (replacing {correlation_id} with the actual id)
- correlation_id: "{correlation_id}" (replacing {correlation_id} with the actual id)
- options: The array sequence of your generated repair options

CRITICAL — VALID PARAMETER NAMES AND RANGES:
You MUST ONLY use these exact parameter keys in parameters_to_change (numeric values only, no strings):

  spindle_speed        — RPM, min=1000, max=4000, default=3000
  aux_fan_speed        — %, min=0, max=100, default=50
  system_pressure_setpoint — bar, min=4.0, max=7.0, default=6.0
  actuator_speed       — %, min=20, max=100, default=80
  line_speed_multiplier — x, min=0.5, max=1.0, default=1.0
  vfd_smoothing        — level, min=0, max=5, default=0
  camera_exposure_time — ms, min=1, max=20, default=5
  belt_tension         — %, min=40, max=90, default=70
  transfer_arm_speed   — %, min=10, max=80, default=60
  clear_fault          — boolean true/false, clears the active fault on the station
  fault_type_to_clear  — string: specific fault name or "all"

Do NOT invent parameter names. Do NOT use strings for numeric values.

CRITICAL FAULT CLEARING RULE:
If the diagnosis mentions a component failure or the station going into a fault state (like overheat, limit_switch_error, communication_loss), you MUST include:
"clear_fault": true 
"fault_type_to_clear": "all" (or the specific fault name if provided)
in your parameters_to_change. If you do not, the PLC will refuse to resume production even if you fix the main parameter!
"""

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-pro",
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    vertexai=True,
    project="graduation-project-498314",
    location="global"
)

tools = [search_factory_manual]
try:
    tools.extend(get_mcp_tools())
except Exception as e:
    logger.warning(f"Could not load MCP tools for repair: {e}")

repair_agent = create_react_agent(llm, tools, prompt=REPAIR_SYSTEM_PROMPT, response_format=RepairProposals)

def run_repair_node(state: IncidentState, config: RunnableConfig, *, store: BaseStore) -> IncidentState:
    """
    Receives diagnosis and context, generates repair proposals, and attaches them to state.
    """
    state["current_agent"] = "REPAIR"

    diagnosis = state.get("diagnosis", {})
    sensor_data = state.get("sensor_data", {})
    station_id = state.get("station_id", "unknown")
    correlation_id = state.get("alert_id", "unknown")
    rejection_feedback = state.get("rejection_feedback", "")
    attempt = state.get("repair_attempt", 1)

    logger.info(f"Repair node starting for {station_id} (Alert: {correlation_id}, Attempt: {attempt})")

    user_prompt = f"""Diagnose and propose repair options for station {station_id}.

Diagnosis:
{json.dumps(diagnosis, default=str)}

Sensor Data:
{json.dumps(sensor_data, default=str)}

Correlation ID for this incident: {correlation_id}"""

    if rejection_feedback:
        user_prompt += f"\n\nPrevious attempt was rejected. Feedback:\n{rejection_feedback}\n\nPlease address these concerns in your new proposals."

    try:
        result = repair_agent.invoke({"messages": [("user", user_prompt)]})

        structured = result["structured_response"]
        # Extract the list of dicts from the RepairProposals wrapper
        proposals = [p.model_dump() for p in structured.proposals]
        state["repair_proposals"] = proposals

        logger.info(f"Repair agent produced {len(proposals)} proposals")

    except Exception as e:
        logger.error(f"Repair agent failed: {e}")
        state["repair_proposals"] = []

    return state
