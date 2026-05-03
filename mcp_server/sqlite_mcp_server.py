from __future__ import annotations

from typing import Any

from core.repository import DbRepository

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:
    raise RuntimeError(
        "mcp package is required. Install dependencies from requirements.txt"
    ) from exc


mcp = FastMCP("smart-plc-sqlite")


@mcp.tool()
def db_health_check() -> dict[str, Any]:
    """Return DB connectivity and schema summary."""
    return DbRepository.get_health()


@mcp.tool()
def create_incident(
    correlation_id: str,
    line_id: str | None = None,
    station_id: str | None = None,
    severity: str = "warning",
    status: str = "NEW_ALERT",
    summary: str | None = None,
) -> dict[str, Any]:
    """Create (or return) an incident by correlation_id."""
    return DbRepository.create_incident(
        correlation_id, line_id, station_id, severity, status, summary
    )


@mcp.tool()
def append_incident_event(
    event_id: str,
    correlation_id: str,
    stage: str,
    event_type: str,
    source_agent: str,
    severity: str = "info",
    line_id: str | None = None,
    station_id: str | None = None,
    payload_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Append idempotent incident event; auto-creates incident if needed."""
    return DbRepository.append_incident_event(
        event_id,
        correlation_id,
        stage,
        event_type,
        source_agent,
        severity,
        line_id,
        station_id,
        payload_json,
    )


@mcp.tool()
def save_monitor_alert(
    event_id: str,
    correlation_id: str,
    alert_type: str,
    message: str,
    severity: str,
    line_id: str | None = None,
    station_id: str | None = None,
    status: str = "open",
    payload_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist monitor alert and write timeline event."""
    return DbRepository.save_monitor_alert(
        event_id,
        correlation_id,
        alert_type,
        message,
        severity,
        line_id,
        station_id,
        status,
        payload_json,
    )


@mcp.tool()
def save_diagnosis(
    event_id: str,
    correlation_id: str,
    root_cause: str,
    confidence: float,
    severity: str,
    model_name: str | None = None,
    urgency: str | None = None,
    evidence_json: list[Any] | None = None,
    reasoning: str | None = None,
    alternative_causes_json: list[Any] | None = None,
    recommended_action: str | None = None,
    payload_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist diagnostic output and timeline event."""
    return DbRepository.save_diagnosis(
        event_id,
        correlation_id,
        root_cause,
        confidence,
        severity,
        model_name,
        urgency,
        evidence_json,
        reasoning,
        alternative_causes_json,
        recommended_action,
        payload_json,
    )


@mcp.tool()
def save_repair_proposal(
    event_id: str,
    correlation_id: str,
    proposal_version: int = 1,
    summary: str | None = None,
    model_name: str | None = None,
    options: list[dict[str, Any]] | None = None,
    payload_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist repair proposal header and options."""
    return DbRepository.save_repair_proposal(
        event_id,
        correlation_id,
        proposal_version,
        summary,
        model_name,
        options,
        payload_json,
    )


@mcp.tool()
def save_validation_result(
    event_id: str,
    correlation_id: str,
    verdict: str,
    risk_score: float,
    proposal_id: int | None = None,
    checks_json: list[Any] | None = None,
    concerns_json: list[Any] | None = None,
    hard_rule_passed: bool = False,
    llm_review_passed: bool = False,
    payload_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist validation result and timeline event."""
    return DbRepository.save_validation_result(
        event_id,
        correlation_id,
        verdict,
        risk_score,
        proposal_id,
        checks_json,
        concerns_json,
        hard_rule_passed,
        llm_review_passed,
        payload_json,
    )


@mcp.tool()
def save_simulation_result(
    event_id: str,
    correlation_id: str,
    go_no_go: str,
    confidence: float,
    validation_id: int | None = None,
    predicted_cycle_time_delta: float | None = None,
    predicted_pass_rate_delta: float | None = None,
    predicted_throughput_delta: float | None = None,
    predicted_fault_risk_delta: float | None = None,
    side_effects_json: list[Any] | None = None,
    payload_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist simulation result and timeline event."""
    return DbRepository.save_simulation_result(
        event_id,
        correlation_id,
        go_no_go,
        confidence,
        validation_id,
        predicted_cycle_time_delta,
        predicted_pass_rate_delta,
        predicted_throughput_delta,
        predicted_fault_risk_delta,
        side_effects_json,
        payload_json,
    )


@mcp.tool()
def create_approval_request(
    event_id: str,
    request_id: str,
    correlation_id: str,
    timeout_seconds: int = 300,
    payload_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist human approval request and timeline event."""
    return DbRepository.create_approval_request(
        event_id, request_id, correlation_id, timeout_seconds, payload_json
    )


@mcp.tool()
def save_human_decision(
    event_id: str,
    correlation_id: str,
    decision: str,
    operator_id: str | None = None,
    reason: str | None = None,
    modification_json: dict[str, Any] | None = None,
    approval_request_id: int | None = None,
    payload_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist human decision and timeline event."""
    return DbRepository.save_human_decision(
        event_id,
        correlation_id,
        decision,
        operator_id,
        reason,
        modification_json,
        approval_request_id,
        payload_json,
    )


@mcp.tool()
def save_execution_run(
    event_id: str,
    correlation_id: str,
    status: str,
    dry_run: bool = True,
    decision_id: int | None = None,
    guard_report_json: dict[str, Any] | None = None,
    result_summary: str | None = None,
    rollback_status: str | None = None,
    payload_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist execution run and timeline event."""
    return DbRepository.save_execution_run(
        event_id,
        correlation_id,
        status,
        dry_run,
        decision_id,
        guard_report_json,
        result_summary,
        rollback_status,
        payload_json,
    )


@mcp.tool()
def log_command_audit(
    event_id: str,
    topic: str,
    command_payload_json: dict[str, Any] | None = None,
    publish_status: str = "queued",
    response_payload_json: dict[str, Any] | None = None,
    execution_run_id: int | None = None,
    line_id: str | None = None,
    station_id: str | None = None,
) -> dict[str, Any]:
    """Persist command audit row (idempotent by event_id)."""
    return DbRepository.log_command_audit(
        event_id,
        topic,
        command_payload_json,
        publish_status,
        response_payload_json,
        execution_run_id,
        line_id,
        station_id,
    )


@mcp.tool()
def save_optimizer_recommendation(
    event_id: str,
    recommendation_id: str,
    recommendation_json: dict[str, Any],
    expected_impact_json: dict[str, Any] | None = None,
    risk_level: str | None = None,
    status: str = "proposed",
    scope_line_id: str | None = None,
    scope_station_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Persist optimizer recommendation (optional incident link)."""
    return DbRepository.save_optimizer_recommendation(
        event_id,
        recommendation_id,
        recommendation_json,
        expected_impact_json,
        risk_level,
        status,
        scope_line_id,
        scope_station_id,
        correlation_id,
    )


@mcp.tool()
def get_incident_timeline(correlation_id: str, limit: int = 200) -> dict[str, Any]:
    """Return incident metadata and chronological event timeline."""
    return DbRepository.get_incident_timeline(correlation_id, limit)


def run_stdio() -> None:
    """Run MCP server over stdio transport."""
    mcp.run()


if __name__ == "__main__":
    run_stdio()
