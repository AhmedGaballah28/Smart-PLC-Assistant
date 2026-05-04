import json
import logging
from typing import Dict, Any, List
from pydantic import BaseModel, Field

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore

from agents.state import IncidentState
from agents.llm_factory import get_llm, get_model_name
from agents.tools.mcp_client import get_mcp_tools
from agents.tools.rag_tools import search_factory_manual

logger = logging.getLogger(__name__)

class DiagnosisOutput(BaseModel):
    root_cause: str = Field(description="Detailed explanation of the root cause based on telemetry.")
    confidence: int = Field(description="Confidence percentage of diagnosis (0-100).", ge=0, le=100)
    severity: str = Field(description="Severity (info, warning, critical).")
    urgency: str = Field(description="Recommended urgency (e.g. low, medium, high).")
    recommended_action: str = Field(description="What should be done immediately.")

DIAGNOSTIC_SYSTEM_PROMPT = """You are an expert industrial PLC diagnostician.

Your goal is to diagnose the fault from the incoming telemetry.
You have access to:
1. RAG search tool (search_factory_manual) to lookup factory rules and mechanical bounds.
2. Database tools to query past events or related faults (via MCP).

USE 'search_factory_manual' IMMEDIATELY to look up the specific sensor or actuator mentioned in the telemetry.

After you have enough context, MUST use the 'save_diagnosis' tool to log your final diagnosis to the database.

IMPORTANT: The user message will provide the event's correlation_id, model_name, and past incident history.
When calling 'save_diagnosis', set:
- event_id to "DX-{correlation_id}" (replacing {correlation_id} with the actual id)
- correlation_id to "{correlation_id}" (replacing {correlation_id} with the actual id)
- model_name to the model_name provided in the user message
- Fill out root_cause, confidence, severity, urgency, and recommended_action.
"""

llm = get_llm("diagnostic", temperature=0)

tools = [search_factory_manual]
try:
    tools.extend(get_mcp_tools())
except Exception as e:
    logger.warning(f"Could not load MCP tools for diagnostics: {e}")

diagnostic_agent = create_react_agent(llm, tools, prompt=DIAGNOSTIC_SYSTEM_PROMPT, response_format=DiagnosisOutput)

def run_diagnostic_node(state: IncidentState, config: RunnableConfig, *, store: BaseStore) -> IncidentState:
    state["current_agent"] = "DIAGNOSTIC"
    sensor_data = state.get("sensor_data", {})
    station_id = state.get("station_id", "unknown_station")
    correlation_id = state.get("alert_id", "unknown_alert")
    
    logger.info(f"Diagnostics starting for {station_id} (Alert: {correlation_id})")

    # 1. Fetch Long-Term Memory (Past Incidents resolved)
    try:
        past_memories = store.search(("incidents", station_id), limit=2)
        if past_memories:
            past_context = "\n".join([f"- Past Alert: {m.value.get('alert', '')} -> Fix: {m.value.get('fix', '')}" for m in past_memories])
        else:
            past_context = "No historical matching incidents found in long-term memory."
    except Exception as e:
        past_context = f"Failed to access long term memory: {e}"

    
    model_name = get_model_name("diagnostic")
    
    user_prompt = f"""Diagnose this telemetry payload: {json.dumps(sensor_data)}

Correlation ID for this incident: {correlation_id}
Model name for DB logging: {model_name}

Past Incident History for this station:
{past_context}"""
    
    try:
        # Run agent
        result = diagnostic_agent.invoke({"messages": [("user", user_prompt)]})
        
        # Output directly from structured response
        state["diagnosis"] = result["structured_response"].model_dump()
        state["rag_context"] = "Context derived during agent execution (see DB)."
    except Exception as e:
        logger.error(f"Diagnostics agent failed: {e}")
        state["diagnosis"] = {
            "root_cause": f"Agent crash: {str(e)}", 
            "confidence": 0,
            "severity": "unknown"
        }

    return state
