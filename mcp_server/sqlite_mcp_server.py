"""
SQLite MCP server for Smart PLC Assistant.

Exposes a safe DB tool surface for agent orchestration.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from sqlalchemy.exc import IntegrityError

from core.database import get_table_names, health_check, session_scope
from core.db_models import (
    ApprovalRequest,
    CommandAudit,
    Diagnosis,
    ExecutionRun,
    HumanDecision,
    Incident,
    IncidentEvent,
    LineHealthSnapshot,
    MonitorAlert,
    OptimizerRecommendation,
    RepairOption,
    RepairProposal,
    SimulationResult,
    ValidationResult,
    utcnow,
)

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:
    raise RuntimeError(
        "mcp package is required. Install dependencies from requirements.txt"
    ) from exc


mcp = FastMCP("smart-plc-sqlite")


def _norm_dict(value: dict[str, Any] | None) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _norm_list(value: list[Any] | None) -> list[Any]:
    return value if isinstance(value, list) else []


def _incident_or_none(correlation_id: str) -> Incident | None:
    with session_scope() as db:
        return db.query(Incident).filter_by(correlation_id=correlation_id).one_or_none()


def _ensure_incident(
    db,
    correlation_id: str,
    line_id: str | None,
    station_id: str | None,
    severity: str,
    status: str = "NEW_ALERT",
    summary: str | None = None,
) -> Incident:
    incident = db.query(Incident).filter_by(correlation_id=correlation_id).one_or_none()
    now = utcnow()

    if incident is None:
        incident = Incident(
            correlation_id=correlation_id,
            line_id=line_id,
            station_id=station_id,
            status=status,
            severity=severity,
            summary=summary,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(incident)
        db.flush()
        return incident

    if line_id and not incident.line_id:
        incident.line_id = line_id
    if station_id and not incident.station_id:
        incident.station_id = station_id

    incident.last_seen_at = now
    incident.updated_at = now
    return incident


def _append_incident_event_if_new(
    db,
    event_id: str,
    incident_id: int,
    correlation_id: str,
    stage: str,
    event_type: str,
    source_agent: str,
    line_id: str | None,
    station_id: str | None,
    severity: str,
    payload_json: dict[str, Any] | None,
) -> tuple[bool, int | None]:
    existing = db.query(IncidentEvent).filter_by(event_id=event_id).one_or_none()
    if existing is not None:
        return True, existing.id

    event = IncidentEvent(
        event_id=event_id,
        incident_id=incident_id,
        correlation_id=correlation_id,
        stage=stage,
        event_type=event_type,
        source_agent=source_agent,
        line_id=line_id,
        station_id=station_id,
        severity=severity,
        payload_json=_norm_dict(payload_json),
    )
    db.add(event)
    db.flush()
    return False, event.id


def _incident_to_dict(incident: Incident) -> dict[str, Any]:
    return {
        "id": incident.id,
        "correlation_id": incident.correlation_id,
        "line_id": incident.line_id,
        "station_id": incident.station_id,
        "status": incident.status,
        "severity": incident.severity,
        "summary": incident.summary,
        "first_seen_at": incident.first_seen_at.isoformat() if incident.first_seen_at else None,
        "last_seen_at": incident.last_seen_at.isoformat() if incident.last_seen_at else None,
        "closed_at": incident.closed_at.isoformat() if incident.closed_at else None,
        "version": incident.version,
    }


@mcp.tool()
def db_health_check() -> dict[str, Any]:
    """Return DB connectivity and schema summary."""
    return {
        "ok": True,
        "healthy": health_check(),
        "table_count": len(get_table_names()),
        "tables": get_table_names(),
    }


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
    with session_scope() as db:
        existing = db.query(Incident).filter_by(correlation_id=correlation_id).one_or_none()
        if existing is not None:
            return {"ok": True, "duplicate": True, "incident": _incident_to_dict(existing)}

        incident = _ensure_incident(
            db,
            correlation_id=correlation_id,
            line_id=line_id,
            station_id=station_id,
            severity=severity,
            status=status,
            summary=summary,
        )
        return {"ok": True, "duplicate": False, "incident": _incident_to_dict(incident)}


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
    with session_scope() as db:
        incident = _ensure_incident(
            db,
            correlation_id=correlation_id,
            line_id=line_id,
            station_id=station_id,
            severity="warning" if severity == "critical" else severity,
            status="NEW_ALERT",
        )
        duplicate, event_pk = _append_incident_event_if_new(
            db,
            event_id=event_id,
            incident_id=incident.id,
            correlation_id=correlation_id,
            stage=stage,
            event_type=event_type,
            source_agent=source_agent,
            line_id=line_id,
            station_id=station_id,
            severity=severity,
            payload_json=payload_json,
        )

        return {
            "ok": True,
            "duplicate": duplicate,
            "incident_id": incident.id,
            "event_id": event_id,
            "event_pk_id": event_pk,
        }


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
    with session_scope() as db:
        existing = db.query(MonitorAlert).filter_by(event_id=event_id).one_or_none()
        if existing is not None:
            return {"ok": True, "duplicate": True, "alert_id": existing.id}

        incident = _ensure_incident(
            db,
            correlation_id=correlation_id,
            line_id=line_id,
            station_id=station_id,
            severity=severity,
            status="NEW_ALERT",
            summary=message,
        )

        alert = MonitorAlert(
            event_id=event_id,
            incident_id=incident.id,
            correlation_id=correlation_id,
            line_id=line_id,
            station_id=station_id,
            alert_type=alert_type,
            severity=severity,
            message=message,
            status=status,
            payload_json=_norm_dict(payload_json),
        )
        db.add(alert)
        db.flush()

        incident.source_alert_id = alert.id
        incident.last_seen_at = utcnow()

        _append_incident_event_if_new(
            db,
            event_id=event_id,
            incident_id=incident.id,
            correlation_id=correlation_id,
            stage="monitor",
            event_type="alert",
            source_agent="monitor_agent",
            line_id=line_id,
            station_id=station_id,
            severity=severity,
            payload_json=payload_json,
        )

        return {"ok": True, "duplicate": False, "incident_id": incident.id, "alert_id": alert.id}


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
    with session_scope() as db:
        existing = db.query(Diagnosis).filter_by(event_id=event_id).one_or_none()
        if existing is not None:
            return {"ok": True, "duplicate": True, "diagnosis_id": existing.id}

        incident = _ensure_incident(
            db,
            correlation_id=correlation_id,
            line_id=None,
            station_id=None,
            severity=severity,
            status="DIAGNOSED",
            summary=root_cause,
        )
        incident.status = "DIAGNOSED"

        diagnosis = Diagnosis(
            event_id=event_id,
            incident_id=incident.id,
            model_name=model_name,
            root_cause=root_cause,
            confidence=confidence,
            severity=severity,
            urgency=urgency,
            evidence_json=_norm_list(evidence_json),
            reasoning=reasoning,
            alternative_causes_json=_norm_list(alternative_causes_json),
            recommended_action=recommended_action,
            payload_json=_norm_dict(payload_json),
        )
        db.add(diagnosis)
        db.flush()

        _append_incident_event_if_new(
            db,
            event_id=event_id,
            incident_id=incident.id,
            correlation_id=correlation_id,
            stage="diagnostic",
            event_type="diagnosis",
            source_agent="diagnostic_agent",
            line_id=incident.line_id,
            station_id=incident.station_id,
            severity=severity,
            payload_json=payload_json,
        )

        return {"ok": True, "duplicate": False, "incident_id": incident.id, "diagnosis_id": diagnosis.id}


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
    with session_scope() as db:
        existing = db.query(RepairProposal).filter_by(event_id=event_id).one_or_none()
        if existing is not None:
            return {"ok": True, "duplicate": True, "proposal_id": existing.id}

        incident = _ensure_incident(
            db,
            correlation_id=correlation_id,
            line_id=None,
            station_id=None,
            severity="warning",
            status="REPAIR_READY",
            summary=summary,
        )
        incident.status = "REPAIR_READY"

        proposal = RepairProposal(
            event_id=event_id,
            incident_id=incident.id,
            proposal_version=proposal_version,
            model_name=model_name,
            summary=summary,
            payload_json=_norm_dict(payload_json),
        )
        db.add(proposal)
        db.flush()

        inserted_options = 0
        for idx, option in enumerate(_norm_list(options), start=1):
            opt = RepairOption(
                proposal_id=proposal.id,
                option_rank=option.get("option_rank", idx),
                option_id=option.get("id"),
                name=option.get("name", f"option_{idx}"),
                description=option.get("description"),
                parameters_to_change_json=_norm_dict(option.get("parameters_to_change")),
                expected_result=option.get("expected_result"),
                risk_level=option.get("risk_level"),
                trade_offs_json=_norm_list(option.get("trade_offs")),
                command_candidates_json=_norm_list(option.get("command_candidates")),
            )
            db.add(opt)
            inserted_options += 1

        _append_incident_event_if_new(
            db,
            event_id=event_id,
            incident_id=incident.id,
            correlation_id=correlation_id,
            stage="repair",
            event_type="proposal",
            source_agent="repair_agent",
            line_id=incident.line_id,
            station_id=incident.station_id,
            severity=incident.severity,
            payload_json=payload_json,
        )

        return {
            "ok": True,
            "duplicate": False,
            "incident_id": incident.id,
            "proposal_id": proposal.id,
            "options_inserted": inserted_options,
        }


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
    with session_scope() as db:
        existing = db.query(ValidationResult).filter_by(event_id=event_id).one_or_none()
        if existing is not None:
            return {"ok": True, "duplicate": True, "validation_id": existing.id}

        incident = _ensure_incident(
            db,
            correlation_id=correlation_id,
            line_id=None,
            station_id=None,
            severity="warning",
            status="VALIDATED",
        )
        incident.status = "VALIDATED" if verdict == "PASS" else "ABORTED"

        result = ValidationResult(
            event_id=event_id,
            incident_id=incident.id,
            proposal_id=proposal_id,
            verdict=verdict,
            risk_score=risk_score,
            checks_json=_norm_list(checks_json),
            concerns_json=_norm_list(concerns_json),
            hard_rule_passed=hard_rule_passed,
            llm_review_passed=llm_review_passed,
            payload_json=_norm_dict(payload_json),
        )
        db.add(result)
        db.flush()

        _append_incident_event_if_new(
            db,
            event_id=event_id,
            incident_id=incident.id,
            correlation_id=correlation_id,
            stage="validation",
            event_type="validation_result",
            source_agent="validation_agent",
            line_id=incident.line_id,
            station_id=incident.station_id,
            severity=incident.severity,
            payload_json=payload_json,
        )

        return {"ok": True, "duplicate": False, "incident_id": incident.id, "validation_id": result.id}


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
    with session_scope() as db:
        existing = db.query(SimulationResult).filter_by(event_id=event_id).one_or_none()
        if existing is not None:
            return {"ok": True, "duplicate": True, "simulation_id": existing.id}

        incident = _ensure_incident(
            db,
            correlation_id=correlation_id,
            line_id=None,
            station_id=None,
            severity="warning",
            status="SIMULATED",
        )
        incident.status = "SIMULATED"

        sim = SimulationResult(
            event_id=event_id,
            incident_id=incident.id,
            validation_id=validation_id,
            go_no_go=go_no_go,
            confidence=confidence,
            predicted_cycle_time_delta=predicted_cycle_time_delta,
            predicted_pass_rate_delta=predicted_pass_rate_delta,
            predicted_throughput_delta=predicted_throughput_delta,
            predicted_fault_risk_delta=predicted_fault_risk_delta,
            side_effects_json=_norm_list(side_effects_json),
            payload_json=_norm_dict(payload_json),
        )
        db.add(sim)
        db.flush()

        _append_incident_event_if_new(
            db,
            event_id=event_id,
            incident_id=incident.id,
            correlation_id=correlation_id,
            stage="simulation",
            event_type="simulation_result",
            source_agent="simulation_agent",
            line_id=incident.line_id,
            station_id=incident.station_id,
            severity=incident.severity,
            payload_json=payload_json,
        )

        return {"ok": True, "duplicate": False, "incident_id": incident.id, "simulation_id": sim.id}


@mcp.tool()
def create_approval_request(
    event_id: str,
    request_id: str,
    correlation_id: str,
    timeout_seconds: int = 300,
    payload_json: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Persist human approval request and timeline event."""
    with session_scope() as db:
        existing = db.query(ApprovalRequest).filter_by(event_id=event_id).one_or_none()
        if existing is not None:
            return {"ok": True, "duplicate": True, "approval_request_id": existing.id}

        incident = _ensure_incident(
            db,
            correlation_id=correlation_id,
            line_id=None,
            station_id=None,
            severity="warning",
            status="PENDING_HUMAN_APPROVAL",
        )
        incident.status = "PENDING_HUMAN_APPROVAL"

        now = utcnow()
        req = ApprovalRequest(
            event_id=event_id,
            request_id=request_id,
            incident_id=incident.id,
            status="pending",
            timeout_seconds=timeout_seconds,
            expires_at=now + timedelta(seconds=timeout_seconds),
            payload_json=_norm_dict(payload_json),
        )
        db.add(req)
        db.flush()

        _append_incident_event_if_new(
            db,
            event_id=event_id,
            incident_id=incident.id,
            correlation_id=correlation_id,
            stage="human",
            event_type="approval_request",
            source_agent="supervisor_agent",
            line_id=incident.line_id,
            station_id=incident.station_id,
            severity=incident.severity,
            payload_json=payload_json,
        )

        return {"ok": True, "duplicate": False, "incident_id": incident.id, "approval_request_id": req.id}


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
    with session_scope() as db:
        existing = db.query(HumanDecision).filter_by(event_id=event_id).one_or_none()
        if existing is not None:
            return {"ok": True, "duplicate": True, "decision_id": existing.id}

        incident = _ensure_incident(
            db,
            correlation_id=correlation_id,
            line_id=None,
            station_id=None,
            severity="warning",
            status="APPROVED" if decision == "APPROVE" else "REJECTED",
        )

        if decision == "APPROVE":
            incident.status = "APPROVED"
        elif decision == "MODIFY":
            incident.status = "MODIFIED"
        else:
            incident.status = "REJECTED"

        human = HumanDecision(
            event_id=event_id,
            incident_id=incident.id,
            approval_request_id=approval_request_id,
            decision=decision,
            operator_id=operator_id,
            reason=reason,
            modification_json=_norm_dict(modification_json),
            payload_json=_norm_dict(payload_json),
        )
        db.add(human)
        db.flush()

        _append_incident_event_if_new(
            db,
            event_id=event_id,
            incident_id=incident.id,
            correlation_id=correlation_id,
            stage="human",
            event_type="approval_decision",
            source_agent="human_agent",
            line_id=incident.line_id,
            station_id=incident.station_id,
            severity=incident.severity,
            payload_json=payload_json,
        )

        return {"ok": True, "duplicate": False, "incident_id": incident.id, "decision_id": human.id}


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
    with session_scope() as db:
        existing = db.query(ExecutionRun).filter_by(event_id=event_id).one_or_none()
        if existing is not None:
            return {"ok": True, "duplicate": True, "execution_run_id": existing.id}

        incident = _ensure_incident(
            db,
            correlation_id=correlation_id,
            line_id=None,
            station_id=None,
            severity="warning",
            status="EXECUTING",
        )

        run = ExecutionRun(
            event_id=event_id,
            incident_id=incident.id,
            decision_id=decision_id,
            status=status,
            dry_run=dry_run,
            guard_report_json=_norm_dict(guard_report_json),
            result_summary=result_summary,
            rollback_status=rollback_status,
            payload_json=_norm_dict(payload_json),
            started_at=utcnow() if status in ("RUNNING", "SUCCESS", "FAILED", "ABORTED") else None,
            finished_at=utcnow() if status in ("SUCCESS", "FAILED", "ABORTED") else None,
        )
        db.add(run)
        db.flush()

        if status == "SUCCESS":
            incident.status = "COMPLETED"
            incident.closed_at = utcnow()
        elif status in ("FAILED", "ABORTED"):
            incident.status = "ABORTED"
            incident.closed_at = utcnow()
        else:
            incident.status = "EXECUTING"

        _append_incident_event_if_new(
            db,
            event_id=event_id,
            incident_id=incident.id,
            correlation_id=correlation_id,
            stage="execution",
            event_type="execution_run",
            source_agent="execution_agent",
            line_id=incident.line_id,
            station_id=incident.station_id,
            severity=incident.severity,
            payload_json=payload_json,
        )

        return {"ok": True, "duplicate": False, "incident_id": incident.id, "execution_run_id": run.id}


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
    with session_scope() as db:
        existing = db.query(CommandAudit).filter_by(event_id=event_id).one_or_none()
        if existing is not None:
            return {"ok": True, "duplicate": True, "command_audit_id": existing.id}

        row = CommandAudit(
            event_id=event_id,
            execution_run_id=execution_run_id,
            topic=topic,
            line_id=line_id,
            station_id=station_id,
            command_payload_json=_norm_dict(command_payload_json),
            publish_status=publish_status,
            response_payload_json=_norm_dict(response_payload_json),
        )
        db.add(row)
        db.flush()

        return {"ok": True, "duplicate": False, "command_audit_id": row.id}


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
    with session_scope() as db:
        existing = db.query(OptimizerRecommendation).filter_by(event_id=event_id).one_or_none()
        if existing is not None:
            return {"ok": True, "duplicate": True, "recommendation_pk_id": existing.id}

        incident_id: int | None = None
        if correlation_id:
            incident = _ensure_incident(
                db,
                correlation_id=correlation_id,
                line_id=scope_line_id,
                station_id=scope_station_id,
                severity="info",
                status="COMPLETED",
            )
            incident_id = incident.id

        row = OptimizerRecommendation(
            event_id=event_id,
            recommendation_id=recommendation_id,
            incident_id=incident_id,
            scope_line_id=scope_line_id,
            scope_station_id=scope_station_id,
            risk_level=risk_level,
            status=status,
            recommendation_json=_norm_dict(recommendation_json),
            expected_impact_json=_norm_dict(expected_impact_json),
        )
        db.add(row)
        db.flush()
        return {"ok": True, "duplicate": False, "recommendation_pk_id": row.id}


@mcp.tool()
def get_incident_timeline(correlation_id: str, limit: int = 200) -> dict[str, Any]:
    """Return incident metadata and chronological event timeline."""
    with session_scope() as db:
        incident = db.query(Incident).filter_by(correlation_id=correlation_id).one_or_none()
        if incident is None:
            return {"ok": False, "error": "incident_not_found", "correlation_id": correlation_id}

        events = (
            db.query(IncidentEvent)
            .filter_by(incident_id=incident.id)
            .order_by(IncidentEvent.created_at.asc())
            .limit(max(1, min(limit, 5000)))
            .all()
        )

        timeline = []
        for ev in events:
            timeline.append(
                {
                    "event_id": ev.event_id,
                    "stage": ev.stage,
                    "event_type": ev.event_type,
                    "source_agent": ev.source_agent,
                    "line_id": ev.line_id,
                    "station_id": ev.station_id,
                    "severity": ev.severity,
                    "payload_json": ev.payload_json,
                    "created_at": ev.created_at.isoformat() if ev.created_at else None,
                }
            )

        return {
            "ok": True,
            "incident": _incident_to_dict(incident),
            "event_count": len(timeline),
            "timeline": timeline,
        }


def run_stdio() -> None:
    """Run MCP server over stdio transport."""
    mcp.run()


if __name__ == "__main__":
    run_stdio()
