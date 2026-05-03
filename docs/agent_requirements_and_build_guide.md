# GenAI Agent Requirements and Build Guide (Factory I/O)

This document defines exactly what is required from each agent in your Smart PLC Assistant system, and how to build each one in this repository.

It is aligned with your existing code and topics:
- `core/mqtt_client.py`
- `core/llm_client.py`
- `config/mqtt_topics.py`
- `runners/realtime_aggregator.py`

## 1) Target Architecture

Pipeline:

1. Monitor Agent detects anomalies and publishes health/alerts.
2. Diagnostic Agent explains probable root cause.
3. Repair Agent proposes fixes.
4. Validation Agent checks safety/compliance.
5. Simulation Agent predicts impact before real execution.
6. Supervisor Agent orchestrates all steps and state.
7. Human-in-the-Loop Agent collects approve/reject/modify.
8. Execution Agent applies only approved actions.
9. Optimization Agent (recommended phase 2) improves throughput and quality over time.

Core rule: fail closed. If any stage is missing, invalid, timed out, or unsafe, no command is executed.

## 2) Shared Requirements for All Agents

Every agent must satisfy these baseline requirements.

### 2.1 Functional requirements

- Connect to MQTT using `MQTTClient` from `core/mqtt_client.py`.
- Subscribe only to required topics.
- Publish structured JSON outputs.
- Add status heartbeat on its own status topic.
- Include timestamp and correlation id in every output.
- Handle reconnect, retry, and malformed payloads without crashing.

### 2.2 Non-functional requirements

- Idempotent processing (same event id should not trigger duplicate actions).
- Timeout controls per stage.
- Structured logs for debugging and auditing.
- Configurable thresholds and model selection through environment/settings.

### 2.3 Message contract (minimum)

All agent messages should include:

- `event_id`: unique id of this message
- `correlation_id`: id that links the entire pipeline for one incident
- `source_agent`: producer agent name
- `line_id`: `line1` or `line2` where applicable
- `station_id`: station name where applicable
- `severity`: `info|warning|critical`
- `timestamp`: ISO format
- `payload`: agent-specific content

## 3) Agent-by-Agent Requirements and Build Plan

## 3.1 Monitor Agent

### Required from Monitor Agent

- Consume raw station status from `factory/line{1,2}/+/status`.
- Detect anomalies from:
  - sensor thresholds
  - z-score baseline drift
  - communication loss
  - stuck state duration
  - emergency signals
- Publish:
  - `agents/monitor/line{1,2}/health`
  - `agents/monitor/line{1,2}/alert`
  - `agents/monitor/factory/snapshot`
- Persist logs:
  - `data/aggregator/line1/health_reports.jsonl`
  - `data/aggregator/line2/health_reports.jsonl`
  - `data/aggregator/line1/alerts.jsonl`
  - `data/aggregator/line2/alerts.jsonl`
  - `data/aggregator/factory_snapshots.jsonl`
  - `data/aggregator/ai_context_log.txt`

### How to build Monitor Agent

1. Reuse `FactoryAggregator` from `runners/realtime_aggregator.py`.
2. Move or wrap it into `agents/monitor_agent.py`.
3. Keep thresholds configurable by settings file.
4. Add compatibility publish to `agents/monitor/alert` and `agents/monitor/status` if needed by legacy consumers.
5. Add a `run_monitor.py` entry script in `runners/`.
6. **(COMPLETED)** Hook into the data lake by importing `DbRepository` and saving anomalies automatically using `DbRepository.save_monitor_alert()` during the health loop.

### Done criteria

- Alerts are generated when injected faults occur.
- Snapshots are published at configured interval.
- No crash under malformed payload.

## 3.2 Diagnostic Agent

### Required from Diagnostic Agent

- Subscribe to monitor alerts:
  - `agents/monitor/line{1,2}/alert`
- Fetch context:
  - last health report for the station
  - recent snapshots
  - fault counters/effects
  - optional KB from `knowledge_base/`
- Call `LLMClient.diagnose_fault()`.
- Publish diagnosis report to:
  - `agents/diagnostic/report`
- Publish runtime status to:
  - `agents/diagnostic/status`

### Output content requirements

- `root_cause`
- `confidence` (0-100)
- `severity`
- `evidence` (list)
- `reasoning`
- `alternative_causes`
- `urgency`
- `recommended_action`

### How to build Diagnostic Agent

1. Create `agents/diagnostic_agent.py`.
2. On alert event, build `sensor_data` object from latest reports.
3. Retrieve knowledge snippets (simple file retrieval first using **`knowledge_base/factory_troubleshooting_manual.md`**; vector retrieval later).
4. Invoke `LLMClient.diagnose_fault(sensor_data, rag_context)`.
5. Validate JSON output and enforce schema.
6. Publish normalized report with correlation id.

### Done criteria

- For known injected faults, root cause is relevant and confidence is nonzero.
- Invalid LLM output is handled safely and republished as parser error status.

## 3.3 Repair Agent

### Required from Repair Agent

- Subscribe to `agents/diagnostic/report`.
- Generate at least 2 repair options when possible.
- Include exact parameter/command-level recommendations.
- Publish to:
  - `agents/repair/proposal`
  - `agents/repair/status`

### Output content requirements

For each proposed solution:

- `id`
- `name`
- `description`
- `parameters_to_change`
- `expected_result`
- `risk_level`
- `trade_offs`

### How to build Repair Agent

1. Create `agents/repair_agent.py`.
2. Consume diagnosis + latest context.
3. Call `LLMClient.suggest_repair(diagnosis, rag_context)`.
4. Add rule-based post-filter:
   - reject dangerous command values
   - enforce line/station scope
5. Publish proposals with explicit command candidates.

### Done criteria

- Proposal includes executable parameter-level details.
- Proposal is rejected if no safe bounded values exist.

## 3.4 Validation Agent

### Required from Validation Agent

- Subscribe to `agents/repair/proposal`.
- Apply hard safety rules first (deterministic).
- Then run `LLMClient.validate_safety()` for semantic review.
- Publish:
  - `agents/validation/result`
  - `agents/validation/status`

### Required safety checks

- Never bypass emergency stop condition.
- Never write outside approved command topic set.
- Never exceed configured min/max parameter bounds.
- Never execute without valid correlation id and source chain.
- Fail result if rules or schema are incomplete.

### Output content requirements

- `verdict`: `PASS` or `FAIL`
- `risk_score` (0-100)
- `checks` (list)
- `concerns` (list)

### How to build Validation Agent

1. Create `agents/validation_agent.py`.
2. Implement `SafetyRuleEngine` class (hard checks).
3. Run hard checks before any LLM call.
4. If hard checks pass, run `validate_safety` as secondary review.
5. Merge results into final verdict.

### Done criteria

- Unsafe proposal always returns `FAIL`.
- Validation latency remains bounded under load.

## 3.5 Simulation Agent

### Required from Simulation Agent

- Subscribe to `agents/validation/result` where `verdict=PASS`.
- Simulate expected effects before execution.
- Publish:
  - `agents/simulation/result`
  - `agents/simulation/progress`
  - `agents/simulation/status`

### Simulation requirements

- Estimate impact on:
  - cycle time
  - pass rate / reject rate
  - fault recurrence risk
  - throughput
- Identify possible side effects and confidence.

### How to build Simulation Agent

1. Create `agents/simulation_agent.py`.
2. Phase 1 simulation method:
   - heuristic replay from recent station history + thresholds.
3. Phase 2 method:
   - run digital twin what-if episode using station models.
4. Return machine-readable summary + human-readable explanation.

### Done criteria

- Simulation output includes clear go/no-go recommendation.
- Missing data produces safe fallback (`inconclusive`, do not execute).

## 3.6 Supervisor Agent

### Required from Supervisor Agent

- Orchestrate full incident workflow.
- Maintain incident state machine.
- Enforce ordering and timeouts.
- Trigger human approval after successful simulation.
- Publish:
  - `agents/supervisor/decision`
  - `agents/supervisor/pipeline_status`
  - `agents/supervisor/status`

### Required incident states

- `NEW_ALERT`
- `DIAGNOSING`
- `DIAGNOSED`
- `PROPOSING_REPAIR`
- `REPAIR_READY`
- `VALIDATING`
- `VALIDATED`
- `SIMULATING`
- `SIMULATED`
- `PENDING_HUMAN_APPROVAL`
- `APPROVED` or `REJECTED` or `MODIFIED`
- `EXECUTING`
- `COMPLETED` or `ABORTED`

### How to build Supervisor Agent

1. Create `agents/supervisor_agent.py`.
2. Use an in-memory incident store first, then persistent store.
3. Subscribe to outputs of all upstream agents.
4. Enforce state transitions strictly.
5. Publish pending request to `human/requests/pending`.
6. Wait for `human/approval/decision` or timeout.
7. Publish final decision event for execution stage.

### Done criteria

- No stage is skipped.
- Timeout leads to safe abort.
- Full trace for one correlation id is reconstructible.

## 3.7 Human-in-the-Loop Agent

### Required from Human Agent

- Subscribe to `human/requests/pending`.
- Present operator with:
  - diagnosis
  - repair proposal
  - validation verdict
  - simulation impact
  - risk summary
- Publish operator decision to:
  - `human/approval/decision`
- Optional modification channel:
  - `human/approval/modification`
- Publish urgent notifications:
  - `human/notifications/urgent`

### Decision requirements

- Allowed decisions: `APPROVE`, `REJECT`, `MODIFY`.
- Decision must include operator id and reason.
- Decision timeout must be enforced by Supervisor.

### How to build Human Agent

1. Build Streamlit page under `dashboard/pages/`.
2. Add pending queue UI with one-click decision buttons.
3. Write MQTT publisher for decision topics.
4. Add audit row for each decision.

### Done criteria

- Operator can approve/reject/modify an incident end-to-end.
- Decision appears in supervisor pipeline within timeout window.

## 3.8 Execution Agent

### Required from Execution Agent

- Subscribe to `agents/supervisor/decision`.
- Execute only when decision is approved and valid.
- Publish command events to approved factory command topics.
- Publish execution status and audit records.

### Execution safety requirements

- Verify approval token/correlation chain before command.
- Verify target station is not in emergency mode.
- Apply bounded writes only.
- Support dry-run mode.
- Support rollback command set where possible.

### How to build Execution Agent

1. Create `agents/execution_agent.py`.
2. Build `CommandGuard` for command whitelist and value bounds.
3. Map high-level action to MQTT command topics under `factory/commands/#`.
4. Publish execution receipt to `system/logs/audit`.
5. Report success/failure back to supervisor topic.

### Done criteria

- No command is emitted without approved decision.
- Every command has an audit trail entry.

## 3.9 Optimization Agent (Recommended Phase 2)

### Required from Optimization Agent

- Consume long-horizon metrics from snapshots/history.
- Recommend throughput-quality-energy tradeoff changes.
- Publish:
  - `agents/optimizer/recommendation`
  - `agents/optimizer/status`

### How to build Optimization Agent

1. Create `agents/optimizer_agent.py`.
2. Run periodic batch analysis (for example every 10-30 minutes).
3. Use Pareto-style recommendations with explicit trade-offs.
4. Send recommendations to Supervisor as advisory only.

### Done criteria

- Recommendations are explainable and bounded.
- No direct execution path (advisory only).

## 4) Suggested Repository Layout

Create these files:

```text
agents/
  __init__.py
  base_agent.py
  schemas.py
  monitor_agent.py
  diagnostic_agent.py
  repair_agent.py
  validation_agent.py
  simulation_agent.py
  supervisor_agent.py
  human_agent.py
  execution_agent.py
  optimizer_agent.py

runners/
  run_monitor_agent.py
  run_diagnostic_agent.py
  run_repair_agent.py
  run_validation_agent.py
  run_simulation_agent.py
  run_supervisor_agent.py
  run_execution_agent.py
  run_optimizer_agent.py
```

## 5) Build Order (Recommended)

1. Monitor (you already have most logic).
2. Supervisor minimal skeleton + Human approval UI.
3. Diagnostic + Repair.
4. Validation hard-rule engine.
5. Simulation.
6. Execution with strict guards.
7. Optimization.

Reason for this order: you get safe observability first, then controlled orchestration, then intelligence, then actuation.

## 6) Minimum Acceptance Tests

Run these end-to-end tests:

1. Inject known fault -> monitor alert is published.
2. Alert -> diagnosis report generated with correlation id.
3. Diagnosis -> repair proposals generated.
4. Proposal -> validation fails for unsafe values.
5. Safe proposal -> simulation result generated.
6. Supervisor sends human request.
7. Human approves -> execution emits bounded command.
8. Full trace appears in `system/logs/audit`.

## 7) Operational Guardrails

- Keep `REQUIRE_HUMAN_APPROVAL=True` for all non-test environments.
- Run Execution Agent in dry-run mode first.
- Use topic-level ACL on broker so only Execution Agent can publish command topics.
- Use separate MQTT client ids per agent instance.
- Keep strict schema validation at every hop.

## 8) What You Already Have vs What You Need

Already implemented strongly:
- Monitor/Aggregator logic (`runners/realtime_aggregator.py`).
- MQTT transport and topic matching (`core/mqtt_client.py`).
- LLM methods for diagnose/repair/validation (`core/llm_client.py`).
- Topic map for all planned agents (`config/mqtt_topics.py`).

Still required to build:
- Concrete agent runtime files under `agents/`.
- Supervisor state machine and incident store.
- Human approval page and decision bridge.
- Execution guardrails and audit-first command runner.

## 9) Database Blueprint (Deep Design)

This section defines how to build the operational database for all agents.

Important principle:

- LangGraph memory is context memory.
- SQL database is system-of-record memory.
- Keep both. Do not replace SQL with memory.

### 9.1 Storage layers

Use three storage layers together:

1. Operational SQL database (mandatory)
  - Incident state
  - Agent outputs
  - Approvals
  - Command audit
2. Telemetry history (already available as JSONL)
  - High-frequency reports and snapshots
3. Vector store for RAG (recommended)
  - SOPs, manuals, prior incident narratives

### 9.2 Engine choice

Phase 1 (single machine, MVP):

- SQLite at `data/plc_data.db`
- Enable WAL mode
- Use short transactions and idempotent writes

Phase 2 (team or production):

- PostgreSQL
- Optional partitioning for high-volume snapshot tables
- Optional pgvector if you want one DB for relational + vectors

### 9.3 SQL schema (what to create)

Create these core tables.

1. `incidents`
  - One row per incident (correlation id)
  - Current state and severity
  - First seen / last updated / closed times

2. `incident_events`
  - Append-only event log for the full pipeline
  - One row per message-stage event
  - Raw payload JSON + normalized metadata

3. `monitor_alerts`
  - Alerts extracted from monitor reports
  - Alert lifecycle: open, acknowledged, cleared

4. `line_health_snapshots`
  - Every health report summary per line
  - Keep compact fields + raw JSON

5. `diagnoses`
  - Diagnostic outputs from Diagnostic Agent
  - Root cause, confidence, evidence, urgency

6. `repair_proposals`
  - Header for proposal bundle
  - Proposal version and model metadata

7. `repair_options`
  - One row per fix option
  - Parameter changes and risk/trade-offs

8. `validation_results`
  - Hard-rule outcome + LLM safety review
  - Final PASS/FAIL with concerns

9. `simulation_results`
  - Predicted impact before execution
  - Includes confidence and go/no-go flag

10. `approval_requests`
   - Requests sent to operators
   - Timeout and presentation payload

11. `human_decisions`
   - Human approvals/rejections/modifications
   - Operator id, reason, modification payload

12. `execution_runs`
   - One row per approved execution attempt
   - Guard checks, result, rollback status

13. `command_audit`
   - One row per command emitted to factory command topics
   - Topic, payload, status, response

14. `agent_heartbeats`
   - Liveness and version info per agent process

15. `optimizer_recommendations`
   - Optional phase 2 storage for optimization outputs

16. `rag_documents` and `rag_feedback`
   - Metadata for indexed docs and retrieval usefulness
   - Store vectors in Chroma path, metadata in SQL

### 9.4 Required columns and constraints

At minimum, include these columns on most tables:

- `id` (primary key)
- `event_id` (unique idempotency key where event-based)
- `correlation_id` (pipeline trace key)
- `line_id`, `station_id` (nullable when not station-scoped)
- `source_agent`
- `payload_json`
- `created_at`, `updated_at`

Critical constraints:

- Unique index on `incident_events.event_id`
- Unique index on `incidents.correlation_id`
- Foreign keys from all stage outputs to `incidents.id`
- Check constraint for valid incident states

### 9.5 Index strategy

Create indexes for common query paths:

1. `incidents(correlation_id)` unique
2. `incidents(status, updated_at)`
3. `incident_events(correlation_id, created_at)`
4. `monitor_alerts(line_id, station_id, created_at)`
5. `diagnoses(incident_id, created_at desc)`
6. `repair_options(proposal_id)`
7. `validation_results(incident_id, created_at desc)`
8. `execution_runs(incident_id, created_at desc)`
9. `command_audit(topic, created_at)`

### 9.6 Agent-to-database attachment map

Attach agents as follows.

1. Monitor Agent
  - Write: `monitor_alerts`, `line_health_snapshots`, `incident_events`
  - Read: optional threshold profile tables

2. Diagnostic Agent
  - Read: `monitor_alerts`, `line_health_snapshots`, recent `incident_events`, RAG metadata
  - Write: `diagnoses`, `incident_events`

3. Repair Agent
  - Read: `diagnoses`, prior `repair_options`, prior `execution_runs`
  - Write: `repair_proposals`, `repair_options`, `incident_events`

4. Validation Agent
  - Read: `repair_options`, safety policy tables, command bounds
  - Write: `validation_results`, `incident_events`

5. Simulation Agent
  - Read: `line_health_snapshots`, `validation_results`, baseline tables
  - Write: `simulation_results`, `incident_events`

6. Supervisor Agent
  - Read/Write: `incidents`, `incident_events`, stage output tables
  - Owns incident state transitions

7. Human-in-the-Loop Agent
  - Read: `approval_requests`
  - Write: `human_decisions`, `incident_events`

8. Execution Agent
  - Read: approved `human_decisions`, `validation_results`, command limits
  - Write: `execution_runs`, `command_audit`, `incident_events`

9. Optimization Agent
  - Read: long-horizon snapshots and execution outcomes
  - Write: `optimizer_recommendations`, `incident_events`

### 9.7 Transaction and idempotency rules

Apply these rules in every agent:

1. Every incoming message must carry `event_id` and `correlation_id`.
2. Before write, upsert/check `event_id` in `incident_events`.
3. If duplicate `event_id`, do not re-run side effects.
4. State transition updates use optimistic version check on `incidents`.
5. Execution Agent writes command audit in same transaction as execution status update.

### 9.8 Retention policy

Use practical retention from day one:

1. `incident_events`: keep 12 months online, archive older.
2. `line_health_snapshots`: keep 90 days online, aggregate older data.
3. `command_audit`: keep indefinitely (safety/legal trace).
4. `human_decisions`: keep indefinitely.
5. `diagnoses` and `repair_*`: keep at least 12 months for learning.

### 9.9 Build sequence for the database layer

Build in this order:

1. Add SQLAlchemy models for core incident and event tables.
2. Add Alembic migrations.
3. Add repository/service layer (`create_incident`, `append_event`, `save_stage_output`).
4. Integrate Monitor writes.
5. Integrate Supervisor state machine on top of SQL.
6. Attach Diagnostic and Repair reads/writes.
7. Attach Validation and Simulation writes.
8. Attach Human and Execution with strict audit writes.
9. Add background retention job.

### 9.10 Minimum database acceptance criteria

Database implementation is complete when:

1. One correlation id can reconstruct full incident timeline.
2. Duplicate event delivery does not duplicate side effects.
3. No command executes without corresponding approved human decision.
4. Incident state transitions are valid and auditable.
5. Dashboard can query open incidents, recent alerts, and last execution outcomes in under 2 seconds.

## 10) SQLite Implementation Added

The SQLite implementation has been created in the repository.

Files:

- `core/db_models.py` (all operational tables, constraints, indexes)
- `core/database.py` (engine, WAL pragmas, sessions, init helpers)
- `runners/init_sqlite_db.py` (one-command initializer)

Run command:

```powershell
"f:/AI/Graduation Project/smart_plc_assistant/Ahmed/Scripts/python.exe" runners/init_sqlite_db.py
```

Optional reset command:

```powershell
"f:/AI/Graduation Project/smart_plc_assistant/Ahmed/Scripts/python.exe" runners/init_sqlite_db.py --drop-existing
```

Database file:

- `data/plc_data.db`

## 11) Upgrade Summary: Which Agents Are Required

This section is the quick answer for implementation priority.

### 11.1 Required agent set for your current target

For the workflow you requested (monitor -> diagnose -> repair -> validate -> simulate -> human approval -> execute), the required agents are:

1. Monitor Agent
2. Diagnostic Agent
3. Repair Agent
4. Validation Agent
5. Simulation Agent
6. Supervisor Agent
7. Human-in-the-Loop Agent
8. Execution Agent

Optional (phase 2):

1. Optimization Agent

### 11.2 Requirement matrix (core vs full)

| Agent | Required for Safe Core | Required for Full AI Closed-Loop |
|---|---|---|
| Monitor | Yes | Yes |
| Supervisor | Yes | Yes |
| Validation | Yes | Yes |
| Human-in-the-Loop | Yes | Yes |
| Execution | Yes | Yes |
| Diagnostic | No | Yes |
| Repair | No | Yes |
| Simulation | No | Yes |
| Optimization | No | No (recommended phase 2) |

Interpretation:

- Safe Core = monitor and govern execution with strict approval and audit.
- Full AI Closed-Loop = add diagnosis, repair generation, and simulation before approval/execution.

### 11.3 MCP tool attachment per agent (implemented)

Use the SQLite MCP server as the write/read contract for all agents.

1. Monitor Agent
  - Must use: `save_monitor_alert`, `append_incident_event`
  - Purpose: create incident signal and timeline start.

2. Diagnostic Agent
  - Must use: `save_diagnosis`, `append_incident_event`
  - Purpose: persist root-cause output and trace.

3. Repair Agent
  - Must use: `save_repair_proposal`, `append_incident_event`
  - Purpose: persist candidate fixes and options.

4. Validation Agent
  - Must use: `save_validation_result`, `append_incident_event`
  - Purpose: enforce PASS/FAIL gate before simulation/execution.

5. Simulation Agent
  - Must use: `save_simulation_result`, `append_incident_event`
  - Purpose: store GO/NO_GO impact prediction.

6. Supervisor Agent
  - Must use: `create_incident`, `create_approval_request`, `append_incident_event`, `get_incident_timeline`
  - Purpose: own state transitions and orchestration.

7. Human-in-the-Loop Agent
  - Must use: `save_human_decision`, `append_incident_event`
  - Purpose: record operator approval/reject/modify with reason.

8. Execution Agent
  - Must use: `save_execution_run`, `log_command_audit`, `append_incident_event`
  - Purpose: enforce approved execution with full audit trace.

9. Optimization Agent (phase 2)
  - Must use: `save_optimizer_recommendation`
  - Purpose: advisory optimization history.

### 11.4 Recommended build order after this upgrade

1. Monitor + Supervisor **(Monitor is hooked up to SQLite data lake)**
2. Validation + Human
3. Execution (dry-run first)
4. Diagnostic + Repair **(RAG text manual created at `knowledge_base/factory_troubleshooting_manual.md`)**
5. Simulation
6. Optimization

### 12) Current Implementation Progress

As of today, the following components have been fully realized from this document:

1. **Database Layer (SQLite + Alembic)**:
   - Full 18-table relational schema implemented (`data/plc_data.db`).
   - `core/repository.py` pattern created to cleanly separate ORM tasks (`DbRepository`) away from AI layers.
   - MCP Server (`mcp_server/sqlite_mcp_server.py`) refactored.
2. **Monitor Agent Data Ingestion**:
   - `runners/realtime_aggregator.py` modified to detect threshold anomalies and push `alerts` natively to SQLite DB (`save_monitor_alert`).
   - Generating status `NEW_ALERT` ready for the Supervisor to orchestrate.
3. **Diagnostic / Repair RAG Base**:
   - Parsed real telemetry cascades and constraints into `knowledge_base/factory_troubleshooting_manual.md` to be read via direct-file retrieval by the reasoning LLM.

**Next Immediate Goal:** Build the `Supervisor Agent` (`agents/supervisor_agent.py`) to poll/subscribe to SQLite incidents mapped as `NEW_ALERT`.

### 11.5 Single-rule safety contract

If any required stage result is missing, invalid, timed out, or not approved, execution must not publish factory commands.
