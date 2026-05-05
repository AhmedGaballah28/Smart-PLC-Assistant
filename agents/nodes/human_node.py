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
    # === TEMPORARY CLI OVERRIDE FOR TESTING ===
    # human_input = interrupt(summary)
    
    print("\n" + "="*60)
    print(f"🚨 HUMAN APPROVAL REQUIRED FOR ALERT: {alert_id}")
    print(f"   Diagnosis: {summary.get('diagnosis')}")
    print(f"   Proposed Repair: {summary.get('proposed_repair')}")
    print(f"   Simulation Impact: {summary.get('simulation_impact')}")
    print("="*60)
    
    raw_input = input("\nType 'APPROVE' or 'REJECT' [optional reason]: ").strip()
    
    if raw_input == "":
        decision = "APPROVE"
        reason = "CLI override for testing"
    else:
        parts = raw_input.split(maxsplit=1)
        decision = parts[0].upper()
        if decision not in ["APPROVE", "REJECT", "MODIFY"]:
            decision = "REJECT" # Prevents database crashes
        reason = parts[1] if len(parts) > 1 else ""
        
    if not reason:
        reason = "No reason provided"

    human_input = {
        "decision": decision,
        "reason": reason,
        "modified_params": summary["proposed_repair"].get("parameters_to_change", {})
    }
    # ==========================================
    
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