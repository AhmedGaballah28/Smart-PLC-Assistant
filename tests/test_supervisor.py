import sys
import os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from agents.supervisor_graph import workflow
from langgraph.types import Command
from langgraph.checkpoint.memory import MemorySaver
from langgraph.store.memory import InMemoryStore

def test_supervisor():
    print("Testing Supervisor Graph...")
    
    # Needs a memory saver to use threads and interrupts
    memory = MemorySaver()
    store = InMemoryStore()
    app_with_memory = workflow.compile(
        checkpointer=memory,
        store=store,
        interrupt_before=["human"]
    )
    
    # 1. Initial State
    initial_state = {
        "alert_id": "TEST-123",
        "sensor_data": {"metric": "temperature_high", "station_id": "station_1"}
    }
    
    print("\n--- Running Graph ---")
    thread_config = {"configurable": {"thread_id": "1"}}
    
    for event in app_with_memory.stream(initial_state, config=thread_config):
        print(event)
    
    print("\n--- Resuming Graph with Approval ---")
    # Simulate the user clicking "Approve" in Streamlit
    human_input = {"decision": "APPROVE"}
    for event in app_with_memory.stream(Command(resume=human_input), config=thread_config):
         print(event)

if __name__ == "__main__":
    test_supervisor()