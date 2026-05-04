import json
import logging
from langgraph.types import interrupt
from langchain_core.runnables import RunnableConfig
from langgraph.store.base import BaseStore
from core.repository import DbRepository
from agents.state import IncidentState

logger = logging.getLogger(__name__)

def run_human_node(state: IncidentState, config: RunnableConfig, *, store: BaseStore) -> IncidentState:
    state["current_agent"] = "HUMAN_WAITING"
    
    # 1. Gather all Incident Context
    summary = {
        "alert": state.get("sensor_data"),
        "diagnosis": state.get("diagnosis"),
        "proposed_repair": state.get("repair_proposals", [{}])[0] if state.get("repair_proposals") else {},
        "safety_verdict": state.get("validation_verdict"),
        "simulation_impact": state.get("simulation_impact")
    }
    
    logger.info(f"Pausing execution to ask Human Operator for incident {state.get('alert_id')}")
    
    alert_id = state.get("alert_id", "unknown")
    try:
        DbRepository.create_approval_request(
            event_id=f"APR-{alert_id}",
            request_id=f"REQ-{alert_id}",
            correlation_id=alert_id
        )
    except Exception as e:
        logger.error(f"Failed to save approval request: {e}")
        
    # 2. LangGraph Interrupt!
    # Engine completely freezes until `.stream(Command(resume=...))`
    human_input = interrupt(summary)
    
    # 3. Resume with output
    logger.info(f"Operator clicked '{human_input.get('decision')}' on the dashboard.")
    
    state["human_decision"] = human_input.get("decision", "REJECT")
    state["rejection_feedback"] = human_input.get("reason", "No reason provided by human operator.")
    
    # Allow human to alter parameters (or fallback to AI default options)
    proposal_params = summary["proposed_repair"].get("parameters_to_change", {})
    state["final_parameters"] = human_input.get("modified_params", proposal_params)
    
    try:
        DbRepository.save_human_decision(
            event_id=f"DEC-{alert_id}",
            correlation_id=alert_id,
            decision=state["human_decision"],
            modification_json=state["final_parameters"]
        )
    except Exception as e:
        logger.error(f"Failed to log human decision: {e}")
        
    return state