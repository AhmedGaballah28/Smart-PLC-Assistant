"""
MCP Client — LangChain tool wrappers for the Smart PLC SQLite database.

Each tool calls DbRepository directly (in-process) rather than spawning
a subprocess.  The function names and parameter signatures match the
original MCP server tools so that agent system prompts work unchanged.

The standalone MCP server (runners/run_sqlite_mcp_server.py) is still
available for external consumers (dashboards, other processes).
"""

import json
import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from core.repository import DbRepository

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# HELPER
# ═══════════════════════════════════════════════════════════════════════════

def _ok(result: Any) -> str:
    """Serialise a DbRepository return value for the LLM."""
    try:
        return json.dumps(result, default=str)
    except Exception:
        return str(result)


# ═══════════════════════════════════════════════════════════════════════════
# TOOLS  (names MUST match the system-prompt instructions)
# ═══════════════════════════════════════════════════════════════════════════

@tool
def db_health_check() -> str:
    """Return DB connectivity and schema summary."""
    return _ok(DbRepository.get_health())


@tool
def create_incident(
    correlation_id: str,
    line_id: str = "",
    station_id: str = "",
    severity: str = "warning",
    status: str = "NEW_ALERT",
    summary: str = "",
) -> str:
    """Create (or return) an incident by correlation_id."""
    return _ok(DbRepository.create_incident(
        correlation_id,
        line_id or None, station_id or None,
        severity, status, summary or None,
    ))


@tool
def append_incident_event(
    event_id: str,
    correlation_id: str,
    stage: str,
    event_type: str,
    source_agent: str,
    severity: str = "info",
    line_id: str = "",
    station_id: str = "",
    payload_json: str = "",
) -> str:
    """Append an idempotent incident event; auto-creates incident if needed."""
    pj = json.loads(payload_json) if payload_json else None
    return _ok(DbRepository.append_incident_event(
        event_id, correlation_id, stage, event_type, source_agent,
        severity, line_id or None, station_id or None, pj,
    ))


@tool
def save_monitor_alert(
    event_id: str,
    correlation_id: str,
    alert_type: str,
    message: str,
    severity: str,
    line_id: str = "",
    station_id: str = "",
    status: str = "open",
    payload_json: str = "",
) -> str:
    """Persist monitor alert and write timeline event."""
    pj = json.loads(payload_json) if payload_json else None
    return _ok(DbRepository.save_monitor_alert(
        event_id, correlation_id, alert_type, message, severity,
        line_id or None, station_id or None, status, pj,
    ))


@tool
def save_diagnosis(
    event_id: str,
    correlation_id: str,
    root_cause: str,
    confidence: float,
    severity: str,
    model_name: str = "",
    urgency: str = "",
    recommended_action: str = "",
    reasoning: str = "",
    evidence_json: str = "",
    alternative_causes_json: str = "",
) -> str:
    """Persist diagnostic output and timeline event.

    Args:
        event_id: Unique event ID, e.g. "DX-{correlation_id}".
        correlation_id: The incident correlation ID.
        root_cause: Detailed explanation of the root cause.
        confidence: Confidence percentage (0-100).
        severity: info, warning, or critical.
        model_name: LLM model used for diagnosis.
        urgency: low, medium, or high.
        recommended_action: What should be done immediately.
        reasoning: Brief explanation of the diagnostic reasoning.
        evidence_json: JSON string of evidence list (optional).
        alternative_causes_json: JSON string of alternative causes (optional).
    """
    ev = json.loads(evidence_json) if evidence_json else None
    ac = json.loads(alternative_causes_json) if alternative_causes_json else None
    return _ok(DbRepository.save_diagnosis(
        event_id, correlation_id, root_cause, confidence, severity,
        model_name or None, urgency or None, ev, reasoning or None,
        ac, recommended_action or None, None,
    ))


@tool
def save_repair_proposal(
    event_id: str,
    correlation_id: str,
    proposal_version: int = 1,
    summary: str = "",
    model_name: str = "",
    options: str = "",
) -> str:
    """Persist repair proposal header and individual options.

    Args:
        event_id: Unique event ID, e.g. "RPR-{correlation_id}".
        correlation_id: The incident correlation ID.
        proposal_version: Version number of this proposal attempt.
        summary: Brief summary of the repair plan.
        model_name: LLM model used for repair generation.
        options: JSON string — a list of dicts, each with keys:
                 id, name, description, parameters_to_change (dict),
                 expected_result, risk_level, trade_offs.
    """
    opts = json.loads(options) if options else None
    return _ok(DbRepository.save_repair_proposal(
        event_id, correlation_id, proposal_version,
        summary or None, model_name or None, opts, None,
    ))


@tool
def save_validation_result(
    event_id: str,
    correlation_id: str,
    verdict: str,
    risk_score: float,
    checks_json: str = "",
    concerns_json: str = "",
    hard_rule_passed: bool = False,
    llm_review_passed: bool = False,
) -> str:
    """Persist validation result and timeline event.

    Args:
        event_id: Unique event ID, e.g. "VAL-{correlation_id}".
        correlation_id: The incident correlation ID.
        verdict: "PASS" or "FAIL".
        risk_score: 0-100 risk estimate.
        checks_json: JSON string of rules checked (list).
        concerns_json: JSON string of violations/concerns (list).
        hard_rule_passed: Whether hard safety rules all passed.
        llm_review_passed: Whether the LLM safety review passed.
    """
    ck = json.loads(checks_json) if checks_json else None
    cn = json.loads(concerns_json) if concerns_json else None
    return _ok(DbRepository.save_validation_result(
        event_id, correlation_id, verdict, risk_score,
        None, ck, cn, hard_rule_passed, llm_review_passed, None,
    ))


@tool
def save_simulation_result(
    event_id: str,
    correlation_id: str,
    go_no_go: str,
    confidence: float,
    predicted_cycle_time_delta: float = 0.0,
    predicted_throughput_delta: float = 0.0,
    predicted_pass_rate_delta: float = 0.0,
    predicted_fault_risk_delta: float = 0.0,
    side_effects_json: str = "",
) -> str:
    """Persist simulation result and timeline event.

    Args:
        event_id: Unique event ID, e.g. "SIM-{correlation_id}".
        correlation_id: The incident correlation ID.
        go_no_go: "GO" or "NO_GO".
        confidence: 0-100 confidence in the prediction.
        predicted_cycle_time_delta: Predicted cycle-time change (seconds).
        predicted_throughput_delta: Predicted throughput change (%).
        predicted_pass_rate_delta: Predicted pass-rate change (%).
        predicted_fault_risk_delta: Predicted fault-risk change (%).
        side_effects_json: JSON string of side-effect list (optional).
    """
    se = json.loads(side_effects_json) if side_effects_json else None
    return _ok(DbRepository.save_simulation_result(
        event_id, correlation_id, go_no_go, confidence,
        None, predicted_cycle_time_delta, predicted_pass_rate_delta,
        predicted_throughput_delta, predicted_fault_risk_delta, se, None,
    ))


@tool
def create_approval_request(
    event_id: str,
    request_id: str,
    correlation_id: str,
    timeout_seconds: int = 300,
) -> str:
    """Persist human approval request and timeline event."""
    return _ok(DbRepository.create_approval_request(
        event_id, request_id, correlation_id, timeout_seconds, None,
    ))


@tool
def save_human_decision(
    event_id: str,
    correlation_id: str,
    decision: str,
    operator_id: str = "",
    reason: str = "",
    modification_json: str = "",
) -> str:
    """Persist human decision and timeline event."""
    mj = json.loads(modification_json) if modification_json else None
    return _ok(DbRepository.save_human_decision(
        event_id, correlation_id, decision,
        operator_id or None, reason or None, mj, None, None,
    ))


@tool
def save_execution_run(
    event_id: str,
    correlation_id: str,
    status: str,
    dry_run: bool = True,
    result_summary: str = "",
    rollback_status: str = "",
) -> str:
    """Persist execution run and timeline event.

    Args:
        event_id: Unique event ID, e.g. "EXE-{alert_id}".
        correlation_id: The incident correlation ID.
        status: "SUCCESS", "FAIL", etc.
        dry_run: Whether this was a dry run.
        result_summary: Human-readable summary of what was applied.
        rollback_status: Rollback info if applicable.
    """
    return _ok(DbRepository.save_execution_run(
        event_id, correlation_id, status, dry_run,
        None, None, result_summary or None, rollback_status or None, None,
    ))


@tool
def log_command_audit(
    event_id: str,
    topic: str,
    command_payload_json: str = "",
    publish_status: str = "queued",
    line_id: str = "",
    station_id: str = "",
) -> str:
    """Persist command audit row (idempotent by event_id).

    Args:
        event_id: Unique event ID, e.g. "CMD-{alert_id}".
        topic: MQTT topic the command was published to.
        command_payload_json: JSON string of the command payload dict.
        publish_status: "queued", "executed", etc.
        line_id: Factory line identifier.
        station_id: Station identifier.
    """
    cp = json.loads(command_payload_json) if command_payload_json else None
    return _ok(DbRepository.log_command_audit(
        event_id, topic, cp, publish_status,
        None, None, line_id or None, station_id or None,
    ))


@tool
def save_optimizer_recommendation(
    event_id: str,
    recommendation_id: str,
    recommendation_json: str,
    expected_impact_json: str = "",
    risk_level: str = "",
    status: str = "proposed",
    scope_line_id: str = "",
    scope_station_id: str = "",
    correlation_id: str = "",
) -> str:
    """Persist optimizer recommendation (optional incident link)."""
    rj = json.loads(recommendation_json) if recommendation_json else {}
    ei = json.loads(expected_impact_json) if expected_impact_json else None
    return _ok(DbRepository.save_optimizer_recommendation(
        event_id, recommendation_id, rj, ei,
        risk_level or None, status,
        scope_line_id or None, scope_station_id or None,
        correlation_id or None,
    ))


@tool
def get_incident_timeline(correlation_id: str, limit: int = 200) -> str:
    """Return incident metadata and chronological event timeline."""
    return _ok(DbRepository.get_incident_timeline(correlation_id, limit))


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC API  (called by every agent node)
# ═══════════════════════════════════════════════════════════════════════════

def get_mcp_tools() -> list:
    """
    Return all 14 database tools as LangChain Tool objects.

    These call DbRepository directly (in-process) — no subprocess needed.
    Tool names match the MCP server exactly so agent prompts work unchanged.
    """
    tools = [
        db_health_check,
        create_incident,
        append_incident_event,
        save_monitor_alert,
        save_diagnosis,
        save_repair_proposal,
        save_validation_result,
        save_simulation_result,
        create_approval_request,
        save_human_decision,
        save_execution_run,
        log_command_audit,
        save_optimizer_recommendation,
        get_incident_timeline,
    ]
    logger.info(f"Loaded {len(tools)} DB tools (direct DbRepository)")
    return tools
