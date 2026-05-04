import json
import logging
from typing import Dict, Any

from langchain_groq import ChatGroq
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore

from agents.state import IncidentState
from agents.tools.mcp_client import get_mcp_tools

try:
    from factory.modbus_client import FactoryIOClient
except ImportError:
    FactoryIOClient = None

logger = logging.getLogger(__name__)

EXECUTION_SYSTEM_PROMPT = """You are the final Execution Agent.

Your job is to permanently log the executed changes to the database.

IMPORTANT: The user message will provide the event's alert_id, line_id, and station_id.
MUST USE:
1. 'save_execution_run' tool:
   - event_id: "EXE-{alert_id}" (replacing {alert_id} with the actual id)
   - correlation_id: "{alert_id}" (replacing {alert_id} with the actual id)
   - status: "SUCCESS"
   - dry_run: true
   - result_summary: String representation of the applied parameters.

2. 'log_command_audit' tool:
   - event_id: "CMD-{alert_id}" (replacing {alert_id} with the actual id)
   - topic: "modbus/plc/write"
   - command_payload_json: The dictionary of final parameters applied.
   - publish_status: "executed"
   - line_id: "{line_id}" (replacing {line_id} with actual)
   - station_id: "{station_id}" (replacing {station_id} with actual)
"""

llm = ChatGroq(model_name="llama-3.3-70b-versatile", temperature=0)

mcp_tools = []
try:
    mcp_tools.extend(get_mcp_tools())
except Exception as e:
    logger.warning(f"Could not load MCP tools for execution: {e}")

execution_agent = create_react_agent(llm, mcp_tools, prompt=EXECUTION_SYSTEM_PROMPT)

def run_execution_node(state: IncidentState, config: RunnableConfig, *, store: BaseStore) -> IncidentState:
    state["current_agent"] = "EXECUTION"
    
    final_params = state.get("final_parameters", {})
    alert_id = state.get("alert_id", "NO_ID")
    station_id = state.get("station_id", "unknown")
    line_id = state.get("line_id", "unknown_line")
    
    logger.info(f"Execution node starting for {station_id} (Alert: {alert_id})")
    
    user_prompt = f"""We have written these parameters to the PLC: {json.dumps(final_params)}. Please log the execution to the database.

Incident Context:
alert_id: {alert_id}
line_id: {line_id}
station_id: {station_id}"""
    
    try:
        # Modbus Logic
        # if FactoryIOClient:
        #     client = FactoryIOClient()
        #     for param, val in final_params.items():
        #         client.write_float(param, float(val))
        
        # Log to DB using the agent
        execution_agent.invoke({"messages": [("user", user_prompt)]})
        
        # Save LangGraph Memory
        memory_payload = {
            "alert": json.dumps(state.get("sensor_data", {})),
            "diagnosis": state.get("diagnosis", {}).get("root_cause", "No cause documented"),
            "fix": json.dumps(final_params),
            "impact": state.get("simulation_impact", {}).get("cycle_time_delta", "Unknown")
        }
        store.put(("incidents", station_id), alert_id, memory_payload)
        
        state["execution_status"] = "SUCCESS"
    except Exception as e:
        logger.error(f"Execution agent failed: {e}")
        state["execution_status"] = f"FAIL: {str(e)}"

    return state