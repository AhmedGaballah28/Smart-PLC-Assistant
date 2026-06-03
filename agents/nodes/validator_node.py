import json
import logging
from typing import Dict, Any, List
from pydantic import BaseModel, Field
import os
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore

from agents.state import IncidentState
from agents.tools.mcp_client import get_mcp_tools
from agents.tools.rag_tools import search_factory_manual

logger = logging.getLogger(__name__)


class ValidationOutput(BaseModel):
    verdict: str = Field(description="'PASS' if the repair is safe and valid, 'FAIL' if not.")
    concerns: List[str] = Field(description="List of specific concerns or reasons for failure.")
    safety_check: bool = Field(description="True if all parameters are within safe operating ranges.")
    compliance_check: bool = Field(description="True if the repair follows factory policy and procedures.")


VALIDATOR_SYSTEM_PROMPT = """You are an expert industrial safety validator for PLC systems.

Your job is to validate a proposed repair BEFORE it goes to simulation and human approval.

You MUST check:
1. Are the proposed parameter changes within safe operating ranges? Use 'search_factory_manual' to look up limits.
2. Does the repair follow factory policy and established procedures?
3. Are there any dangerous side effects or interactions between changed parameters?
4. Is the root cause diagnosis sound and does the repair actually address it?
5. CRITICAL: Provide AT LEAST ONE physical parameter adjustment (like spindle_speed, aux_fan_speed, transfer_arm_speed) alongside ANY 'clear_fault' command. Never approve a repair that ONLY contains 'clear_fault' and 'fault_type_to_clear' with no other parameters.

If ANY concern is found, set verdict to "FAIL" and list ALL concerns.
If everything checks out, set verdict to "PASS" with an empty concerns list.

Be strict — safety is paramount in industrial environments.

IMPORTANT: The user message will provide the event's correlation_id.
After validation, use the 'save_validation_result' MCP tool (if available) to log:
- event_id: "VAL-{correlation_id}" (replacing {correlation_id} with the actual id)
- correlation_id: "{correlation_id}" (replacing {correlation_id} with the actual id)
- verdict: Your verdict ("PASS" or "FAIL")
- risk_score: A float from 0.0 to 100.0 representing the safety risk level.
- concerns_json: Your list of concerns
"""

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash",
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
    logger.warning(f"Could not load MCP tools for validator: {e}")

validator_agent = create_react_agent(llm, tools, prompt=VALIDATOR_SYSTEM_PROMPT, response_format=ValidationOutput)


def run_validator_node(state: IncidentState, config: RunnableConfig, *, store: BaseStore) -> IncidentState:
    """
    Validates the proposed repair against factory safety rules and parameter bounds.
    Sets validation_verdict and validation_reason in state.
    """
    state["current_agent"] = "VALIDATION"

    diagnosis = state.get("diagnosis", {})
    proposals = state.get("repair_proposals", [])
    station_id = state.get("station_id", "unknown")
    correlation_id = state.get("alert_id", "unknown")
    rejection_feedback = state.get("rejection_feedback", "")

    logger.info(f"Validator starting for {station_id} (Alert: {correlation_id})")

    # Build the user prompt with all context
    proposal_text = json.dumps(proposals[0], default=str) if proposals else "No proposals available"

    user_prompt = f"""Validate this repair proposal for station {station_id}:

Diagnosis:
{json.dumps(diagnosis, default=str)}

Proposed Repair:
{proposal_text}

Correlation ID for this incident: {correlation_id}"""

    if rejection_feedback:
        user_prompt += f"\n\nPrevious rejection feedback:\n{rejection_feedback}"

    try:
        result = validator_agent.invoke({"messages": [("user", user_prompt)]})

        structured = result["structured_response"]
        state["validation_verdict"] = structured.verdict
        state["validation_reason"] = structured.concerns

        logger.info(f"Validation verdict: {structured.verdict} | Concerns: {structured.concerns}")

    except Exception as e:
        logger.error(f"Validator agent failed: {e}")
        state["validation_verdict"] = "FAIL"
        state["validation_reason"] = [f"Validator agent crashed: {str(e)}"]

    return state
    
