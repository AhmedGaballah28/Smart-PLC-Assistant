import os
import json
import logging
import time
from typing import Dict, Any

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.runnables import RunnableConfig
from langchain_google_genai import ChatGoogleGenerativeAI
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

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite",
    temperature=0,
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    vertexai=True,
    project="graduation-project-498314",
    location="global"
)

mcp_tools = []
try:
    mcp_tools.extend(get_mcp_tools())
except Exception as e:
    logger.warning(f"Could not load MCP tools for execution: {e}")

execution_agent = create_react_agent(llm, mcp_tools, prompt=EXECUTION_SYSTEM_PROMPT)


def _publish_mqtt_commands(station_id: str, line_id: str, final_params: dict) -> bool:
    """Publish repair commands to the Digital Twin via MQTT.

    Topics:
      factory/{line_id}/{station_id}/commands/apply  — apply new parameters
      factory/{line_id}/{station_id}/commands/clear   — clear active faults
    """
    try:
        from core.mqtt_client import MQTTClient
    except ImportError:
        logger.warning("MQTTClient not available — skipping MQTT command publish")
        return False

    client = MQTTClient(client_id=f"exec_agent_{int(time.time())}")
    try:
        if not client.connect():
            logger.warning("MQTT connect failed — commands not published")
            return False

        base_topic = f"factory/{line_id}/{station_id}/commands"

        # Clear active faults if the repair calls for it
        clear_fault = final_params.get("clear_fault", False)
        fault_type = final_params.get("fault_type_to_clear", "all")
        if clear_fault:
            client.publish(f"{base_topic}/clear", {
                "action": "clear",
                "fault_type": fault_type,
                "station_id": station_id,
                "line_id": line_id,
                "timestamp": time.time(),
            })
            logger.info(f"MQTT: Published fault clear to {base_topic}/clear "
                        f"(fault_type={fault_type})")

        # Apply parameter changes
        apply_params = {k: v for k, v in final_params.items()
                        if k not in ("clear_fault", "fault_type_to_clear",
                                     "action", "description")}
        if apply_params:
            client.publish(f"{base_topic}/apply", {
                "parameters": apply_params,
                "station_id": station_id,
                "line_id": line_id,
                "timestamp": time.time(),
            })
            logger.info(f"MQTT: Published parameter apply to {base_topic}/apply: "
                        f"{apply_params}")

        return True
    except Exception as e:
        logger.error(f"MQTT command publish error: {e}")
        return False
    finally:
        client.disconnect()


def run_execution_node(state: IncidentState, config: RunnableConfig, *, store: BaseStore) -> IncidentState:
    state["current_agent"] = "EXECUTION"
    
    final_params = state.get("final_parameters", {})
    alert_id = state.get("alert_id", "NO_ID")
    station_id = state.get("station_id", "unknown")
    line_id = state.get("line_id", "unknown_line")
    
    logger.info(f"Execution node starting for {station_id} (Alert: {alert_id})")
    
    # ── 1. Publish MQTT commands to Digital Twin ──
    mqtt_ok = _publish_mqtt_commands(station_id, line_id, final_params)
    mqtt_status = "mqtt_published" if mqtt_ok else "mqtt_skipped"
    
    user_prompt = f"""We have written these parameters to the PLC: {json.dumps(final_params)}. Please log the execution to the database.

Incident Context:
alert_id: {alert_id}
line_id: {line_id}
station_id: {station_id}"""
    
    try:
        # ── 2. Log to DB using the agent ──
        execution_agent.invoke({"messages": [("user", user_prompt)]})
        
        # ── 3. Save LangGraph Memory ──
        memory_payload = {
            "alert": json.dumps(state.get("sensor_data", {})),
            "diagnosis": state.get("diagnosis", {}).get("root_cause", "No cause documented"),
            "fix": json.dumps(final_params),
            "impact": state.get("simulation_impact", {}).get("cycle_time_delta", "Unknown"),
            "mqtt_status": mqtt_status,
        }
        store.put(("incidents", station_id), alert_id, memory_payload)
        
        state["execution_status"] = f"SUCCESS ({mqtt_status})"
    except Exception as e:
        logger.error(f"Execution agent failed: {e}")
        state["execution_status"] = f"FAIL: {str(e)}"

    return state
