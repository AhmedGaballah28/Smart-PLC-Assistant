# SQLite MCP Server Quickstart

This server exposes safe SQLite tools for your multi-agent pipeline.

## 1) Install dependencies

```powershell
pip install -r requirements.txt
```

## 2) Initialize database schema

```powershell
"f:/AI/Graduation Project/smart_plc_assistant/Ahmed/Scripts/python.exe" runners/init_sqlite_db.py
```

## 3) Run MCP server (stdio)

```powershell
"f:/AI/Graduation Project/smart_plc_assistant/Ahmed/Scripts/python.exe" runners/run_sqlite_mcp_server.py
```

## 4) Available MCP tools

- `db_health_check`
- `create_incident`
- `append_incident_event`
- `save_monitor_alert`
- `save_diagnosis`
- `save_repair_proposal`
- `save_validation_result`
- `save_simulation_result`
- `create_approval_request`
- `save_human_decision`
- `save_execution_run`
- `log_command_audit`
- `save_optimizer_recommendation`
- `get_incident_timeline`

## 5) Example stdio MCP client config

```json
{
  "servers": [
    {
      "type": "stdio",
      "command": "f:/AI/Graduation Project/smart_plc_assistant/Ahmed/Scripts/python.exe",
      "args": [
        "runners/run_sqlite_mcp_server.py"
      ],
      "cwd": "f:/AI/Graduation Project/smart_plc_assistant"
    }
  ]
}
```

## 6) Expected usage pattern from agents

1. `save_monitor_alert`
2. `save_diagnosis`
3. `save_repair_proposal`
4. `save_validation_result`
5. `save_simulation_result`
6. `create_approval_request`
7. `save_human_decision`
8. `save_execution_run`
9. `log_command_audit`

Use `append_incident_event` for extra timeline entries when needed.
