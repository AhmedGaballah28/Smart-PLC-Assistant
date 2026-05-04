from typing import TypedDict, Dict, Any, List, Optional


class IncidentState(TypedDict):
    alert_id: str
    line_id: str                       # "line1" or "line2"
    station_id: str                    # e.g. "stn1", "mc_a"
    sensor_data: Dict[str, Any]
    current_agent: str                 # "DIAGNOSTIC", "VALIDATION", etc.

    # Diagnostic Agent
    rag_context: str
    diagnosis: Dict[str, Any]

    # Repair Agent
    repair_attempt: int
    rejection_feedback: str
    repair_proposals: List[Dict[str, Any]]

    # Validator Agent
    validation_verdict: str
    validation_reason: List[str]       # List of concerns/reasons

    # Simulation Agent
    simulation_impact: Dict[str, Any]

    # Human Node
    human_decision: str
    final_parameters: Dict[str, Any]

    # Execution Agent
    execution_status: str
