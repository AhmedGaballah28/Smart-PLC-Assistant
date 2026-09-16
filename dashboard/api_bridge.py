from __future__ import annotations

import json
import sqlite3
import sys
import uuid
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DB_PATH = PROJECT_ROOT / "data" / "plc_data.db"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _launch_in_terminal(title: str, command: list[str], cwd: str) -> int:
    cmd_line = subprocess.list2cmdline(command)
    clean_title = "".join(c for c in title if ord(c) < 128).strip() or "Service"
    proc = subprocess.Popen(
        f'cmd /S /K "title {clean_title} && {cmd_line}"',
        cwd=cwd,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
    )
    return proc.pid


def start_project() -> dict[str, Any]:
    pids_file = PROJECT_ROOT / "data" / "active_processes.json"
    if pids_file.exists():
        return {"ok": False, "error": "Project is already running (PIDs file exists). Stop it first."}
    
    # 1. DB initialization
    init_db_cmd = [sys.executable, "runners/init_sqlite_db.py", "--drop-existing"]
    init_res = subprocess.run(init_db_cmd, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
    if init_res.returncode != 0:
        return {"ok": False, "error": f"DB Init failed: {init_res.stderr or init_res.stdout}"}
    
    # 2. Launch processes in sequence
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    data_dir_path = PROJECT_ROOT / "data" / f"run_{timestamp}"
    data_dir_path.mkdir(parents=True, exist_ok=True)
    data_dir = str(data_dir_path)
    
    pids = []
    try:
        services = [
            ("Data Logger", [sys.executable, "runners/mqtt_data_logger.py", "--output", data_dir]),
            ("Realtime Aggregator", [sys.executable, "runners/realtime_aggregator.py", "--output", data_dir]),
            ("Digital Twin", [sys.executable, "runners/run_twin.py"]),
            ("Monitor Agent", [sys.executable, "agents/monitor_agent.py"]),
        ]

        for name, command in services:
            pids.append({
                "name": name,
                "pid": _launch_in_terminal(name, command, str(PROJECT_ROOT)),
            })
            time.sleep(1)

        with open(pids_file, "w") as f:
            json.dump(pids, f)

        return {"ok": True, "pids": pids, "data_dir": data_dir}
    except Exception as e:
        return {"ok": False, "error": f"Failed to spawn services: {e}"}

    try:
        # MQTT Data Logger
        logger_cmd = [sys.executable, "runners/mqtt_data_logger.py", "--output", data_dir]
        pids.append({
            "name": "Data Logger",
            "pid": _launch_in_terminal("📊 Data Logger", logger_cmd, str(PROJECT_ROOT))
        })
        time.sleep(1)
        
        # Realtime Aggregator
        aggregator_cmd = [sys.executable, "runners/realtime_aggregator.py", "--output", data_dir]
        pids.append({
            "name": "Realtime Aggregator",
            "pid": _launch_in_terminal("🔍 Realtime Aggregator", aggregator_cmd, str(PROJECT_ROOT))
        })
        time.sleep(1)
        
        # Monitor Agent
        monitor_cmd = [sys.executable, "agents/monitor_agent.py"]
        pids.append({
            "name": "Monitor Agent",
            "pid": _launch_in_terminal("🤖 Monitor Agent", monitor_cmd, str(PROJECT_ROOT))
        })
        time.sleep(1)
        
        # Digital Twin
        twin_cmd = [sys.executable, "runners/run_twin.py"]
        pids.append({
            "name": "Digital Twin",
            "pid": _launch_in_terminal("🏭 Digital Twin", twin_cmd, str(PROJECT_ROOT))
        })
    except Exception as e:
        return {"ok": False, "error": f"Failed to spawn services: {e}"}
        
    with open(pids_file, "w") as f:
        json.dump(pids, f)
        
    return {"ok": True, "pids": pids, "data_dir": data_dir}


def stop_project() -> dict[str, Any]:
    pids_file = PROJECT_ROOT / "data" / "active_processes.json"
    if not pids_file.exists():
        return {"ok": True, "message": "No active processes recorded."}
        
    try:
        with open(pids_file, "r") as f:
            pids = json.load(f)
    except Exception as e:
        return {"ok": False, "error": f"Failed to read PIDs: {e}"}
        
    terminated = []
    for entry in pids:
        pid = entry.get("pid")
        name = entry.get("name")
        if pid:
            try:
                subprocess.run(
                    f"taskkill /T /F /PID {pid}",
                    shell=True, capture_output=True,
                )
                terminated.append(name)
            except Exception:
                pass
                
    if pids_file.exists():
        try:
            pids_file.unlink()
        except Exception:
            pass
            
    return {"ok": True, "terminated": terminated}


def inject_fault(payload: dict[str, Any]) -> dict[str, Any]:
    action = payload.get("action")
    scenario = payload.get("scenario")
    cmd = payload.get("cmd")
    
    args = [sys.executable, "runners/inject_faults.py"]
    
    if action == "scenario":
        args.extend(["--scenario", str(scenario)])
        _launch_in_terminal(f"Scenario {scenario}", args, str(PROJECT_ROOT))
        return {"ok": True, "message": f"Scenario {scenario} launched in new console window."}
        
    elif action == "command":
        args.extend(["--cmd", cmd])
        res = subprocess.run(args, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        return {
            "ok": res.returncode == 0,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "message": f"Injected fault command: {cmd}"
        }
        
    elif action == "clear":
        args.append("--clear")
        res = subprocess.run(args, cwd=str(PROJECT_ROOT), capture_output=True, text=True)
        return {
            "ok": res.returncode == 0,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "message": "Cleared all faults."
        }
        
    elif action == "interactive":
        _launch_in_terminal("Fault Injection Menu", args, str(PROJECT_ROOT))
        return {"ok": True, "message": "Interactive fault menu launched in new console window."}
        
    return {"ok": False, "error": f"Unknown fault injection action: {action}"}


def _json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _rows(query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    if not DB_PATH.exists():
        return []
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def _one(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
    rows = _rows(query, params)
    return rows[0] if rows else None


def _health() -> dict[str, Any]:
    if not DB_PATH.exists():
        return {"healthy": False, "table_count": 0, "database": str(DB_PATH)}
    tables = _rows("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    return {"healthy": True, "table_count": len(tables), "database": str(DB_PATH)}


def _active_node(latest_event: dict[str, Any] | None, latest_incident: dict[str, Any] | None) -> str:
    status_map = {
        "NEW_ALERT": "diagnose",
        "DIAGNOSING": "diagnose",
        "DIAGNOSED": "repair",
        "PROPOSING_REPAIR": "repair",
        "REPAIR_READY": "validate",
        "VALIDATING": "validate",
        "VALIDATED": "simulate",
        "SIMULATING": "simulate",
        "SIMULATED": "human",
        "PENDING_HUMAN_APPROVAL": "human",
        "APPROVED": "execute",
        "REJECTED": "inject_feedback",
        "MODIFIED": "repair",
        "EXECUTING": "execute",
        "COMPLETED": "report",
        "ABORTED": "report",
    }
    stage_map = {
        "monitor": "diagnose",
        "diagnostic": "diagnose",
        "diagnose": "diagnose",
        "repair": "repair",
        "validation": "validate",
        "validate": "validate",
        "simulation": "simulate",
        "simulate": "simulate",
        "human": "human",
        "execution": "execute",
        "execute": "execute",
        "report": "report",
    }
    if latest_incident and latest_incident.get("status") in status_map:
        return status_map[latest_incident["status"]]
    if latest_event:
        return stage_map.get(str(latest_event.get("stage", "")).lower(), "diagnose")
    return "diagnose"


def snapshot() -> dict[str, Any]:
    latest_incident = _one(
        """
        SELECT id, correlation_id, line_id, station_id, status, severity, summary, updated_at, created_at
        FROM incidents
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """
    )
    latest_event = _one(
        """
        SELECT id, event_id, correlation_id, stage, event_type, source_agent, severity, payload_json, created_at
        FROM incident_events
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """
    )
    alerts = _rows(
        """
        SELECT id, event_id, correlation_id, line_id, station_id, alert_type, severity, message, status, payload_json, created_at
        FROM monitor_alerts
        ORDER BY created_at DESC, id DESC
        LIMIT 8
        """
    )
    diagnoses = _rows(
        """
        SELECT d.id, d.event_id, i.correlation_id, d.root_cause, d.confidence, d.severity,
               d.reasoning, d.recommended_action, d.evidence_json, d.created_at
        FROM diagnoses d
        JOIN incidents i ON i.id = d.incident_id
        ORDER BY d.created_at DESC, d.id DESC
        LIMIT 5
        """
    )
    events = _rows(
        """
        SELECT event_id, correlation_id, stage, event_type, source_agent, severity, payload_json, created_at
        FROM incident_events
        ORDER BY created_at DESC, id DESC
        LIMIT 20
        """
    )
    approvals = _rows(
        """
        SELECT a.id, a.request_id, i.correlation_id, a.status, a.timeout_seconds, a.expires_at, a.payload_json, a.created_at
        FROM approval_requests a
        JOIN incidents i ON i.id = a.incident_id
        WHERE a.status = 'pending'
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT 3
        """
    )
    simulations = _rows(
        """
        SELECT s.id, i.correlation_id, s.go_no_go, s.confidence, s.predicted_cycle_time_delta,
               s.predicted_pass_rate_delta, s.predicted_throughput_delta, s.predicted_fault_risk_delta,
               s.side_effects_json, s.created_at
        FROM simulation_results s
        JOIN incidents i ON i.id = s.incident_id
        ORDER BY s.created_at DESC, s.id DESC
        LIMIT 5
        """
    )
    repair_proposals = _rows(
        """
        SELECT rp.id, rp.event_id, i.correlation_id, rp.proposal_version, rp.model_name,
               rp.summary, rp.payload_json, rp.created_at
        FROM repair_proposals rp
        JOIN incidents i ON i.id = rp.incident_id
        ORDER BY rp.created_at DESC, rp.id DESC
        LIMIT 6
        """
    )
    repair_options = _rows(
        """
        SELECT ro.id, ro.proposal_id, ro.option_rank, ro.option_id, ro.name, ro.description,
               ro.parameters_to_change_json, ro.expected_result, ro.risk_level,
               ro.trade_offs_json, ro.command_candidates_json, ro.created_at
        FROM repair_options ro
        ORDER BY ro.created_at DESC, ro.id DESC
        LIMIT 12
        """
    )
    validation_results = _rows(
        """
        SELECT v.id, v.event_id, i.correlation_id, v.proposal_id, v.verdict, v.risk_score,
               v.checks_json, v.concerns_json, v.hard_rule_passed, v.llm_review_passed,
               v.payload_json, v.created_at
        FROM validation_results v
        JOIN incidents i ON i.id = v.incident_id
        ORDER BY v.created_at DESC, v.id DESC
        LIMIT 8
        """
    )
    heartbeats = _rows(
        """
        SELECT agent_name, instance_id, version, status, details_json, created_at
        FROM agent_heartbeats
        ORDER BY created_at DESC, id DESC
        LIMIT 16
        """
    )
    health_rows = _rows(
        """
        SELECT event_id, line_id, overall_health, total_produced, total_rate_per_min,
               active_fault_count, alert_count, payload_json, created_at
        FROM line_health_snapshots
        ORDER BY created_at DESC, id DESC
        LIMIT 8
        """
    )

    for row in alerts:
        row["payload_json"] = _json(row.get("payload_json"), {})
    for row in diagnoses:
        row["evidence_json"] = _json(row.get("evidence_json"), [])
    for row in events:
        row["payload_json"] = _json(row.get("payload_json"), {})
    for row in approvals:
        row["payload_json"] = _json(row.get("payload_json"), {})
    for row in simulations:
        row["side_effects_json"] = _json(row.get("side_effects_json"), [])
    for row in repair_proposals:
        row["payload_json"] = _json(row.get("payload_json"), {})
        row["options"] = []
    for row in repair_options:
        row["parameters_to_change_json"] = _json(row.get("parameters_to_change_json"), {})
        row["trade_offs_json"] = _json(row.get("trade_offs_json"), [])
        row["command_candidates_json"] = _json(row.get("command_candidates_json"), [])
    for row in validation_results:
        row["checks_json"] = _json(row.get("checks_json"), [])
        row["concerns_json"] = _json(row.get("concerns_json"), [])
        row["payload_json"] = _json(row.get("payload_json"), {})
    for row in heartbeats:
        row["details_json"] = _json(row.get("details_json"), {})
    for row in health_rows:
        row["payload_json"] = _json(row.get("payload_json"), {})

    proposal_by_id = {row["id"]: row for row in repair_proposals}
    for option in repair_options:
        proposal = proposal_by_id.get(option.get("proposal_id"))
        if proposal:
            proposal["options"].append(option)

    is_running = (PROJECT_ROOT / "data" / "active_processes.json").exists()

    return {
        "ok": True,
        "source": "sqlite",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "health": _health(),
        "active_node": _active_node(latest_event, latest_incident),
        "latest_incident": latest_incident,
        "alerts": alerts,
        "diagnoses": diagnoses,
        "events": events,
        "approvals": approvals,
        "simulations": simulations,
        "repair_proposals": repair_proposals,
        "validation_results": validation_results,
        "heartbeats": heartbeats,
        "line_health": health_rows,
        "is_running": is_running,
    }


def save_decision(payload: dict[str, Any]) -> dict[str, Any]:
    from core.repository import DbRepository

    decision = str(payload.get("decision", "APPROVE")).upper()
    if decision not in {"APPROVE", "REJECT", "MODIFY"}:
        raise ValueError("decision must be APPROVE, REJECT, or MODIFY")

    pending = _one(
        """
        SELECT a.id, i.correlation_id
        FROM approval_requests a
        JOIN incidents i ON i.id = a.incident_id
        WHERE a.status = 'pending'
        ORDER BY a.created_at DESC, a.id DESC
        LIMIT 1
        """
    )
    latest = _one("SELECT correlation_id FROM incidents ORDER BY updated_at DESC, id DESC LIMIT 1")
    correlation_id = payload.get("correlation_id") or (pending or latest or {}).get("correlation_id")
    if not correlation_id:
        correlation_id = f"dashboard-{uuid.uuid4()}"
        DbRepository.create_incident(
            correlation_id=correlation_id,
            line_id="line1",
            station_id="dashboard",
            severity="warning",
            status="PENDING_HUMAN_APPROVAL",
            summary="Dashboard-created human decision placeholder.",
        )

    result = DbRepository.save_human_decision(
        event_id=f"DASH-HUMAN-{uuid.uuid4()}",
        correlation_id=correlation_id,
        decision=decision,
        operator_id=payload.get("operator_id", "dashboard_operator"),
        reason=payload.get("reason", "Decision submitted from Node dashboard."),
        modification_json=payload.get("modification_json") or {},
        approval_request_id=(pending or {}).get("id"),
        payload_json={
            "source": "node_dashboard",
            "ui_decision": decision,
            "submitted_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    return {"ok": True, "decision": decision, "result": result, "snapshot": snapshot()}


def main() -> None:
    action = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    if action == "snapshot":
        print(json.dumps(snapshot()))
        return
    if action == "decision":
        payload = json.loads(sys.stdin.read() or "{}")
        print(json.dumps(save_decision(payload)))
        return
    if action == "start_project":
        print(json.dumps(start_project()))
        return
    if action == "stop_project":
        print(json.dumps(stop_project()))
        return
    if action == "inject_fault":
        payload = json.loads(sys.stdin.read() or "{}")
        print(json.dumps(inject_fault(payload)))
        return
    raise ValueError(f"Unknown action: {action}")


if __name__ == "__main__":
    main()
