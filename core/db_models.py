"""
SQLite database models for Smart PLC Assistant.

This module defines the operational system-of-record schema used by
the multi-agent pipeline.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


INCIDENT_STATES = [
    "NEW_ALERT",
    "DIAGNOSING",
    "DIAGNOSED",
    "PROPOSING_REPAIR",
    "REPAIR_READY",
    "VALIDATING",
    "VALIDATED",
    "SIMULATING",
    "SIMULATED",
    "PENDING_HUMAN_APPROVAL",
    "APPROVED",
    "REJECTED",
    "MODIFIED",
    "EXECUTING",
    "COMPLETED",
    "ABORTED",
]

SEVERITY_LEVELS = ["info", "warning", "critical"]


def in_check(values: list[str]) -> str:
    joined = ", ".join(f"'{value}'" for value in values)
    return f"IN ({joined})"


class Base(DeclarativeBase):
    pass


class Incident(Base):
    __tablename__ = "incidents"
    __table_args__ = (
        UniqueConstraint("correlation_id", name="uq_incidents_correlation_id"),
        CheckConstraint(f"status {in_check(INCIDENT_STATES)}", name="ck_incidents_status"),
        CheckConstraint(f"severity {in_check(SEVERITY_LEVELS)}", name="ck_incidents_severity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    line_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    station_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(64), nullable=False, default="NEW_ALERT")
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="warning")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_alert_id: Mapped[int | None] = mapped_column(
        ForeignKey("monitor_alerts.id", ondelete="SET NULL"), nullable=True
    )
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )


class IncidentEvent(Base):
    __tablename__ = "incident_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_incident_events_event_id"),
        Index("ix_incident_events_correlation_created_at", "correlation_id", "created_at"),
        Index("ix_incident_events_incident_created_at", "incident_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    stage: Mapped[str] = mapped_column(String(64), nullable=False)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_agent: Mapped[str] = mapped_column(String(64), nullable=False)
    line_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    station_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    severity: Mapped[str] = mapped_column(String(16), nullable=False, default="info")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class MonitorAlert(Base):
    __tablename__ = "monitor_alerts"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_monitor_alerts_event_id"),
        Index("ix_monitor_alerts_line_station_created_at", "line_id", "station_id", "created_at"),
        Index("ix_monitor_alerts_status_created_at", "status", "created_at"),
        CheckConstraint(f"severity {in_check(SEVERITY_LEVELS)}", name="ck_monitor_alerts_severity"),
        CheckConstraint("status IN ('open', 'acknowledged', 'cleared')", name="ck_monitor_alerts_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[int | None] = mapped_column(
        ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True
    )
    correlation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    line_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    station_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    alert_type: Mapped[str] = mapped_column(String(64), nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class LineHealthSnapshot(Base):
    __tablename__ = "line_health_snapshots"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_line_health_snapshots_event_id"),
        Index("ix_line_health_snapshots_line_created_at", "line_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    line_id: Mapped[str] = mapped_column(String(32), nullable=False)
    overall_health: Mapped[str] = mapped_column(String(16), nullable=False)
    total_produced: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_rate_per_min: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    active_fault_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class Diagnosis(Base):
    __tablename__ = "diagnoses"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_diagnoses_event_id"),
        Index("ix_diagnoses_incident_created_at", "incident_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    root_cause: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    severity: Mapped[str] = mapped_column(String(16), nullable=False)
    urgency: Mapped[str | None] = mapped_column(String(32), nullable=True)
    evidence_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    alternative_causes_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    recommended_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RepairProposal(Base):
    __tablename__ = "repair_proposals"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_repair_proposals_event_id"),
        Index("ix_repair_proposals_incident_created_at", "incident_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    proposal_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    model_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RepairOption(Base):
    __tablename__ = "repair_options"
    __table_args__ = (Index("ix_repair_options_proposal_id", "proposal_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proposal_id: Mapped[int] = mapped_column(ForeignKey("repair_proposals.id", ondelete="CASCADE"), nullable=False)
    option_rank: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    option_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    parameters_to_change_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    expected_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    trade_offs_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    command_candidates_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ValidationResult(Base):
    __tablename__ = "validation_results"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_validation_results_event_id"),
        CheckConstraint("verdict IN ('PASS', 'FAIL')", name="ck_validation_results_verdict"),
        Index("ix_validation_results_incident_created_at", "incident_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    proposal_id: Mapped[int | None] = mapped_column(
        ForeignKey("repair_proposals.id", ondelete="SET NULL"), nullable=True
    )
    verdict: Mapped[str] = mapped_column(String(8), nullable=False)
    risk_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    checks_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    concerns_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    hard_rule_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    llm_review_passed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class SimulationResult(Base):
    __tablename__ = "simulation_results"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_simulation_results_event_id"),
        CheckConstraint("go_no_go IN ('GO', 'NO_GO', 'INCONCLUSIVE')", name="ck_simulation_results_go_no_go"),
        Index("ix_simulation_results_incident_created_at", "incident_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    validation_id: Mapped[int | None] = mapped_column(
        ForeignKey("validation_results.id", ondelete="SET NULL"), nullable=True
    )
    go_no_go: Mapped[str] = mapped_column(String(16), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    predicted_cycle_time_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_pass_rate_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_throughput_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    predicted_fault_risk_delta: Mapped[float | None] = mapped_column(Float, nullable=True)
    side_effects_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False, default=list)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ApprovalRequest(Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_approval_requests_event_id"),
        UniqueConstraint("request_id", name="uq_approval_requests_request_id"),
        CheckConstraint("status IN ('pending', 'answered', 'expired', 'cancelled')", name="ck_approval_requests_status"),
        Index("ix_approval_requests_status_created_at", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class HumanDecision(Base):
    __tablename__ = "human_decisions"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_human_decisions_event_id"),
        CheckConstraint("decision IN ('APPROVE', 'REJECT', 'MODIFY')", name="ck_human_decisions_decision"),
        Index("ix_human_decisions_incident_created_at", "incident_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    approval_request_id: Mapped[int | None] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="SET NULL"), nullable=True
    )
    decision: Mapped[str] = mapped_column(String(16), nullable=False)
    operator_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    modification_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class ExecutionRun(Base):
    __tablename__ = "execution_runs"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_execution_runs_event_id"),
        CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'SUCCESS', 'FAILED', 'ABORTED')",
            name="ck_execution_runs_status",
        ),
        Index("ix_execution_runs_incident_created_at", "incident_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[int] = mapped_column(ForeignKey("incidents.id", ondelete="CASCADE"), nullable=False)
    decision_id: Mapped[int | None] = mapped_column(ForeignKey("human_decisions.id", ondelete="SET NULL"), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    guard_report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    rollback_status: Mapped[str | None] = mapped_column(String(32), nullable=True)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class CommandAudit(Base):
    __tablename__ = "command_audit"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_command_audit_event_id"),
        Index("ix_command_audit_topic_created_at", "topic", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("execution_runs.id", ondelete="SET NULL"), nullable=True
    )
    topic: Mapped[str] = mapped_column(String(256), nullable=False)
    line_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    station_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    command_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    publish_status: Mapped[str] = mapped_column(String(32), nullable=False, default="queued")
    response_payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class AgentHeartbeat(Base):
    __tablename__ = "agent_heartbeats"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_agent_heartbeats_event_id"),
        Index("ix_agent_heartbeats_agent_created_at", "agent_name", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    agent_name: Mapped[str] = mapped_column(String(64), nullable=False)
    instance_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="running")
    details_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class OptimizerRecommendation(Base):
    __tablename__ = "optimizer_recommendations"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_optimizer_recommendations_event_id"),
        UniqueConstraint("recommendation_id", name="uq_optimizer_recommendations_recommendation_id"),
        Index("ix_optimizer_recommendations_created_at", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    event_id: Mapped[str] = mapped_column(String(128), nullable=False)
    recommendation_id: Mapped[str] = mapped_column(String(128), nullable=False)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)
    scope_line_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    scope_station_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    risk_level: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="proposed")
    recommendation_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    expected_impact_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RAGDocument(Base):
    __tablename__ = "rag_documents"
    __table_args__ = (
        UniqueConstraint("document_id", name="uq_rag_documents_document_id"),
        Index("ix_rag_documents_source_path", "source_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    document_id: Mapped[str] = mapped_column(String(128), nullable=False)
    source_path: Mapped[str] = mapped_column(String(512), nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    title: Mapped[str | None] = mapped_column(String(512), nullable=True)
    version: Mapped[str | None] = mapped_column(String(64), nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class RAGFeedback(Base):
    __tablename__ = "rag_feedback"
    __table_args__ = (Index("ix_rag_feedback_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    incident_id: Mapped[int | None] = mapped_column(ForeignKey("incidents.id", ondelete="SET NULL"), nullable=True)
    diagnosis_id: Mapped[int | None] = mapped_column(ForeignKey("diagnoses.id", ondelete="SET NULL"), nullable=True)
    repair_option_id: Mapped[int | None] = mapped_column(ForeignKey("repair_options.id", ondelete="SET NULL"), nullable=True)
    rag_document_id: Mapped[int | None] = mapped_column(ForeignKey("rag_documents.id", ondelete="SET NULL"), nullable=True)
    usefulness_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


def all_model_names() -> list[str]:
    return sorted(Base.metadata.tables.keys())
