from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore
# from langchain_huggingface import HuggingFaceEmbeddings  # required if you want semantic search in store

from agents.state import IncidentState
from agents.nodes.diagnostic_node import run_diagnostic_node
from agents.nodes.repair_node import run_repair_node
from agents.nodes.validator_node import run_validator_node
from agents.nodes.simulation_node import run_simulation_node
from agents.nodes.human_node import run_human_node
from agents.nodes.execution_node import run_execution_node

MAX_REPAIR_ATTEMPTS = 3

def validation_router(state: IncidentState) -> str:
    if state.get("validation_verdict") == "PASS":
        return "simulate"
    elif state.get("repair_attempt", 1) >= MAX_REPAIR_ATTEMPTS:
        return "end"
    else:
        return "retry_repair"

def human_router(state: IncidentState) -> str:
    if state.get("human_decision") == "APPROVE":
        return "execute"
    elif state.get("repair_attempt", 1) >= MAX_REPAIR_ATTEMPTS:
        return "end"
    else:
        return "retry_repair"

def run_inject_feedback_node(state: IncidentState) -> IncidentState:
    state["repair_attempt"] = state.get("repair_attempt", 1) + 1
    
    if state.get("validation_verdict") == "FAIL":
        concerns = state.get("validation_reason", [])
        state["rejection_feedback"] = f"Validator FAILED: {'; '.join(concerns)}"
        
    return state

workflow = StateGraph(IncidentState)

# Add nodes
workflow.add_node("diagnose", run_diagnostic_node)
workflow.add_node("repair", run_repair_node)
workflow.add_node("validate", run_validator_node)
workflow.add_node("simulate", run_simulation_node)
workflow.add_node("human", run_human_node)
workflow.add_node("execute", run_execution_node)
workflow.add_node("inject_feedback", run_inject_feedback_node)

# Add edges
workflow.set_entry_point("diagnose")
workflow.add_edge("diagnose", "repair")
workflow.add_edge("repair", "validate")

# Conditional routing from validate
workflow.add_conditional_edges(
    "validate",
    validation_router,
    {
        "simulate": "simulate",
        "retry_repair": "inject_feedback",
        "end": END
    }
)

workflow.add_edge("simulate", "human")

# Conditional routing from human
workflow.add_conditional_edges(
    "human",
    human_router,
    {
        "execute": "execute",
        "retry_repair": "inject_feedback",
        "end": END
    }
)

# inject_feedback always goes back to repair
workflow.add_edge("inject_feedback", "repair")

workflow.add_edge("execute", END)

# Note: Compiling the app with Checkpointer and Store for memory layers
memory = MemorySaver()
store = InMemoryStore()
supervisor_app = workflow.compile(checkpointer=memory, store=store)