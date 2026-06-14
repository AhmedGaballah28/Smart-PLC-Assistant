import os
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

from pydantic import BaseModel, Field
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent
from langgraph.store.base import BaseStore

from agents.state import IncidentState
from agents.tools.rag_tools import search_factory_manual

logger = logging.getLogger(__name__)

REPORTS_DIR = Path("data") / "reports"


class ReportOutput(BaseModel):
    title: str = Field(description="Short incident title (e.g. 'Motor Overheat on Station mc_a').")
    executive_summary: str = Field(description="2-3 sentence high-level summary of the entire incident for a factory manager.")
    diagnosis_narrative: str = Field(description="Plain-English explanation of what went wrong and why.")
    repair_narrative: str = Field(description="What repair was proposed, including key parameter changes.")
    simulation_narrative: str = Field(description="What the simulation predicted and whether it was safe.")
    human_decision_narrative: str = Field(description="What the human operator decided and why.")
    execution_narrative: str = Field(description="What was actually executed and the result. Say 'N/A' if execution did not occur.")
    outcome: str = Field(description="Final outcome: 'RESOLVED', 'ABORTED', or 'MAX_RETRIES_EXHAUSTED'.")
    recommendations: List[str] = Field(description="1-3 follow-up recommendations for the operations team.")


REPORT_SYSTEM_PROMPT = """You are an expert technical report writer for an industrial PLC factory automation system.

Your job is to take raw incident data from a fault-detection pipeline and produce a clear, professional narrative report that a factory manager or maintenance engineer can understand.

You have access to:
1. RAG search tool (search_factory_manual) to lookup factory procedures and specifications for more context.

WORKFLOW:
1. FIRST, use 'search_factory_manual' to look up any relevant procedures or specifications related to the fault described in the incident data. This will help you write more informed recommendations.
2. Generate your structured report output.

REPORT WRITING RULES:
1. Write in past tense — the incident has already been processed.
2. Use precise technical language but keep it accessible to non-experts.
3. Include specific numbers (temperatures, speeds, percentages) when available.
4. Be honest about uncertainties or low confidence scores.
5. If a section has no data (e.g. execution didn't happen because the proposal was rejected), write "N/A — [brief reason]".
6. Keep each narrative section to 2-4 sentences.
7. The executive_summary should capture: what happened, what was done, and the final outcome.
"""

llm = ChatGoogleGenerativeAI(
    model="gemini-2.5-flash-lite",
    temperature=0.2,
    google_api_key=os.getenv("GOOGLE_API_KEY"),
    vertexai=True,
    project="graduation-project-498314"
)

report_agent = create_react_agent(llm, [search_factory_manual], prompt=REPORT_SYSTEM_PROMPT, response_format=ReportOutput)


def _determine_outcome(state: IncidentState) -> str:
    """Determine the final outcome from state."""
    exec_status = state.get("execution_status", "")
    human_decision = state.get("human_decision", "")
    validation_verdict = state.get("validation_verdict", "")
    attempt = state.get("repair_attempt", 1)

    if exec_status and "SUCCESS" in exec_status:
        return "RESOLVED"
    elif exec_status and "FAIL" in exec_status:
        return "EXECUTION_FAILED"
    elif attempt >= 3:
        return "MAX_RETRIES_EXHAUSTED"
    elif human_decision == "REJECT":
        return "REJECTED_BY_OPERATOR"
    elif validation_verdict == "FAIL":
        return "VALIDATION_FAILED"
    else:
        return "ABORTED"


def _build_json_report(state: IncidentState, outcome: str, timestamp: str) -> Dict[str, Any]:
    """Build the structured JSON report from state."""
    return {
        "meta": {
            "alert_id": state.get("alert_id", "unknown"),
            "line_id": state.get("line_id", "unknown"),
            "station_id": state.get("station_id", "unknown"),
            "generated_at": timestamp,
            "outcome": outcome,
            "repair_attempts": state.get("repair_attempt", 1),
        },
        "sensor_data": state.get("sensor_data", {}),
        "diagnosis": state.get("diagnosis", {}),
        "repair_proposals": state.get("repair_proposals", []),
        "validation": {
            "verdict": state.get("validation_verdict", "N/A"),
            "reasons": state.get("validation_reason", []),
        },
        "simulation_impact": state.get("simulation_impact", {}),
        "human_decision": {
            "decision": state.get("human_decision", "N/A"),
            "rejection_feedback": state.get("rejection_feedback", ""),
        },
        "final_parameters": state.get("final_parameters", {}),
        "execution_status": state.get("execution_status", "N/A"),
    }


def _render_markdown(report: ReportOutput, state: IncidentState, timestamp: str) -> str:
    """Render the LLM report output as a Markdown document."""
    alert_id = state.get("alert_id", "unknown")
    line_id = state.get("line_id", "unknown")
    station_id = state.get("station_id", "unknown")
    attempt = state.get("repair_attempt", 1)

    md = f"""# {report.title}

**Alert ID:** `{alert_id}`
**Line:** `{line_id}` | **Station:** `{station_id}`
**Generated:** {timestamp}
**Repair Attempts:** {attempt}
**Outcome:** {report.outcome}

---

## Executive Summary

{report.executive_summary}

---

## Diagnosis

{report.diagnosis_narrative}

## Proposed Repair

{report.repair_narrative}

## Simulation Results

{report.simulation_narrative}

## Human Decision

{report.human_decision_narrative}

## Execution

{report.execution_narrative}

---

## Recommendations

"""
    for i, rec in enumerate(report.recommendations, 1):
        md += f"{i}. {rec}\n"

    md += "\n---\n*Report generated automatically by the Smart PLC Assistant pipeline.*\n"
    return md


def run_report_node(state: IncidentState, config: RunnableConfig, *, store: BaseStore) -> IncidentState:
    """
    Final agent node in the pipeline. Uses an LLM agent with RAG + MCP tools
    to generate a professional incident report, log it to the database,
    and save both Markdown and JSON files to data/reports/.
    """
    state["current_agent"] = "REPORT"

    alert_id = state.get("alert_id", "unknown")
    station_id = state.get("station_id", "unknown")
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    file_stamp = now.strftime("%Y%m%d_%H%M%S")

    outcome = _determine_outcome(state)

    logger.info(f"Report agent starting for {station_id} (Alert: {alert_id}, Outcome: {outcome})")

    # ── Ensure output directory exists ──
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    base_name = f"{alert_id}_{file_stamp}"
    md_path = REPORTS_DIR / f"{base_name}.md"
    json_path = REPORTS_DIR / f"{base_name}.json"

    # ── 1. Save JSON report (always succeeds, no LLM needed) ──
    json_report = _build_json_report(state, outcome, timestamp)
    try:
        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(json_report, f, indent=2, default=str)
        logger.info(f"JSON report saved: {json_path}")
    except Exception as e:
        logger.error(f"Failed to save JSON report: {e}")

    # ── 2. Run the report agent (LLM + RAG + MCP) ──
    user_prompt = f"""Generate a professional incident report from this pipeline data.

Correlation ID for this incident: {alert_id}

Alert ID: {alert_id}
Line: {state.get('line_id', 'unknown')}
Station: {station_id}
Outcome: {outcome}
Repair Attempts: {state.get('repair_attempt', 1)}

Sensor Data:
{json.dumps(state.get('sensor_data', {}), default=str)}

Diagnosis:
{json.dumps(state.get('diagnosis', {}), default=str)}

Repair Proposals:
{json.dumps(state.get('repair_proposals', []), default=str)}

Validation Verdict: {state.get('validation_verdict', 'N/A')}
Validation Concerns: {json.dumps(state.get('validation_reason', []), default=str)}

Simulation Impact:
{json.dumps(state.get('simulation_impact', {}), default=str)}

Human Decision: {state.get('human_decision', 'N/A')}
Rejection Feedback: {state.get('rejection_feedback', '')}

Final Parameters Applied:
{json.dumps(state.get('final_parameters', {}), default=str)}

Execution Status: {state.get('execution_status', 'N/A')}"""

    try:
        result = report_agent.invoke({"messages": [("user", user_prompt)]})

        report = result["structured_response"]
        md_content = _render_markdown(report, state, timestamp)

        with open(md_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        logger.info(f"Markdown report saved: {md_path}")

        # Save to LangGraph memory store
        store.put(("reports", station_id), alert_id, {
            "title": report.title,
            "outcome": report.outcome,
            "summary": report.executive_summary,
            "report_path": str(md_path),
        })

    except Exception as e:
        logger.error(f"Report agent failed: {e}")
        # Fallback: write a basic template report without LLM
        fallback_md = f"""# Incident Report — {alert_id}

**Generated:** {timestamp}
**Outcome:** {outcome}

> Report agent failed: {str(e)}
> See the JSON report for full structured data.

**Diagnosis:** {json.dumps(state.get('diagnosis', {}), default=str, indent=2)}

**Execution Status:** {state.get('execution_status', 'N/A')}

---
*Report generated automatically by the Smart PLC Assistant pipeline.*
"""
        try:
            with open(md_path, "w", encoding="utf-8") as f:
                f.write(fallback_md)
            logger.info(f"Fallback Markdown report saved: {md_path}")
        except Exception as e2:
            logger.error(f"Failed to save fallback report: {e2}")

    state["report_path"] = str(md_path)
    return state
