"""
Page 3: AI Agent Console
"""

import sys
import time
from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.demo_simulator import get_simulator

st.set_page_config(page_title="AI Console | Smart PLC", page_icon="", layout="wide")

st.markdown("""
<style>
 @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400&display=swap');
 html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
 .stApp { background: linear-gradient(135deg,#0f172a 0%,#1a1f35 100%); }
 [data-testid="stSidebar"] { background: linear-gradient(160deg,#0f172a,#1e293b); }
 #MainMenu, footer { visibility: hidden; }

 .event-card {
 border-radius: 12px; padding: 1rem 1.2rem; margin-bottom: 0.8rem;
 border-left: 4px solid;
 }
 .alert-warn { background: rgba(245,158,11,0.08); border-color: #f59e0b; }
 .alert-crit { background: rgba(239,68,68,0.10); border-color: #ef4444; }
 .diag-card { background: rgba(99,102,241,0.08); border-color: #6366f1; }
 .repair-card { background: rgba(16,185,129,0.08); border-color: #10b981; }

 .event-title { font-size: 0.9rem; font-weight: 700; color: #e2e8f0; }
 .event-meta { font-size: 0.72rem; color: #64748b; font-family: 'JetBrains Mono'; margin-bottom:6px; }
 .event-body { font-size: 0.82rem; color: #cbd5e1; }
 .conf-badge { background: rgba(99,102,241,0.3); color: #a5b4fc; border-radius: 8px; padding: 1px 8px; font-size: 0.72rem; }
 .stn-badge { background: rgba(6,182,212,0.2); color: #67e8f9; border-radius: 8px; padding: 1px 8px; font-size: 0.72rem; }
 .level-warn { color: #f59e0b; font-weight: 700; }
 .level-crit { color: #ef4444; font-weight: 700; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="background:linear-gradient(90deg,#6366f1,#8b5cf6,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:1.8rem;font-weight:700"> AI Agent Console</h1>', unsafe_allow_html=True)
st.caption("Live feed: Monitor → Diagnose → Repair pipeline | Demo Mode (rule-based)")

sim = get_simulator()

# ── Status strip ─────────────────────────────────────────────────────────────
alerts = sim.get_alerts(limit=15)
diagnoses = sim.get_diagnoses(limit=8)
proposals = sim.get_proposals(limit=8)

c1, c2, c3, c4 = st.columns(4)
c1.metric("Alert: Total Alerts", len(alerts))
c2.metric(" Diagnoses Run", len(diagnoses))
c3.metric(" Repair Proposals", len(proposals))
c4.metric(" LLM Mode",  "Demo (Rule-based)")

st.markdown("---")

col_left, col_right = st.columns([1, 1])

# ── LEFT: Alerts + Diagnoses ──────────────────────────────────────────────────
with col_left:
 st.markdown("### Alert: Monitor Alerts")
 if not alerts:
  st.info("No alerts yet — the simulator generates alerts every ~30 seconds.")
 for a in alerts[:8]:
  level = a.get("level", "WARNING")
  css_cls = "alert-crit" if level == "CRITICAL" else "alert-warn"
  lvl_cls = "level-crit" if level == "CRITICAL" else "level-warn"
  ts = a.get("timestamp", "")[:19].replace("T", " ")
  st.markdown(f"""
<div class="event-card {css_cls}">
 <div class="event-title">
 <span class="{lvl_cls}">{level}</span> &nbsp;
 <span class="stn-badge">{a.get('station_name','?')}</span>
 </div>
 <div class="event-meta">{a.get('alert_id')} · {ts}</div>
 <div class="event-body">
 <b>{a.get('metric','?')}</b> = {a.get('value')} {a.get('unit','')}
 &nbsp;(threshold: {a.get('threshold','?')} {a.get('unit','')})
 </div>
</div>
""", unsafe_allow_html=True)

 st.markdown("### Diagnoses")
 if not diagnoses:
  st.info("Diagnoses appear after alerts are generated.")
 for d in diagnoses[:5]:
  conf = d.get("confidence", 0)
  ts = d.get("timestamp", "")[:19].replace("T", " ")
  llm_icon = "" if d.get("llm_used") else ""
  st.markdown(f"""
<div class="event-card diag-card">
 <div class="event-title">{llm_icon} {d.get('diagnosis_id')} — <span class="stn-badge">{d.get('station_name','?')}</span></div>
 <div class="event-meta">{ts} · urgency: {d.get('urgency','?')}</div>
 <div class="event-body">
 <b>Root cause:</b> {d.get('root_cause','?')}<br>
 <span class="conf-badge">Confidence {conf}%</span>
 &nbsp;<span style="color:#94a3b8;font-size:0.75rem">{d.get('recommended_action','')[:80]}</span>
 </div>
</div>
""", unsafe_allow_html=True)

# ── RIGHT: Repair Proposals ───────────────────────────────────────────────────
with col_right:
 st.markdown("### Repair Proposals")
 if not proposals:
  st.info("Repair proposals appear after diagnoses are generated.")
 for p in proposals[:6]:
  ts = p.get("timestamp", "")[:19].replace("T", " ")
  sub_props = p.get("proposals", [])
  st.markdown(f"""
<div class="event-card repair-card">
 <div class="event-title"> {p.get('proposal_id')} — <span class="stn-badge">{p.get('station_name','?')}</span></div>
 <div class="event-meta">{ts} · urgency: {p.get('urgency','?')}</div>
 <div class="event-body"><b>Cause:</b> {p.get('root_cause','?')[:80]}</div>
</div>
""", unsafe_allow_html=True)
  for sp in sub_props[:2]:
   risk = sp.get("risk_level", "LOW")
   risk_color = "#10b981" if risk == "LOW" else ("#f59e0b" if risk == "MEDIUM" else "#ef4444")
   st.markdown(f"""
<div style="background:rgba(15,23,42,0.6);border-radius:10px;padding:0.7rem 1rem;margin-bottom:0.5rem;border:1px solid rgba(99,102,241,0.15)">
 <div style="font-size:0.85rem;font-weight:600;color:#e2e8f0">{sp.get('name','?')}</div>
 <div style="font-size:0.78rem;color:#94a3b8;margin:4px 0">{sp.get('description','')[:120]}</div>
 <div style="font-size:0.72rem">
 <span style="color:{risk_color}">Risk: {risk}</span> &nbsp;·&nbsp;
 <span style="color:#67e8f9">⏱ {sp.get('estimated_downtime_min',0)} min downtime</span> &nbsp;·&nbsp;
 <span style="color:#a5b4fc">{sp.get('expected_result','')[:60]}</span>
 </div>
</div>
""", unsafe_allow_html=True)

 # ── Agent pipeline diagram ──
 st.markdown("### 🔗 Pipeline Status")
 st.markdown("""
<div style="background:rgba(15,23,42,0.8);border:1px solid rgba(99,102,241,0.2);border-radius:14px;padding:1.2rem;font-family:'JetBrains Mono',monospace;font-size:0.8rem;color:#94a3b8">
<span style="color:#10b981">●</span> Monitor Agent &nbsp;&nbsp;→ &nbsp;&nbsp;
<span style="color:#6366f1">●</span> Diagnostic Agent &nbsp;&nbsp;→ &nbsp;&nbsp;
<span style="color:#f59e0b">●</span> Repair Agent &nbsp;&nbsp;→ &nbsp;&nbsp;
<span style="color:#8b5cf6">●</span> Safety Validator<br><br>
<span style="color:#475569">IN: factory/+/status</span><br>
<span style="color:#475569">OUT: agents/diagnostic/report</span><br>
<span style="color:#475569">  agents/repair/proposal</span><br>
<span style="color:#475569">  agents/validation/result</span><br>
<span style="color:#475569">  human/requests/pending</span><br><br>
<span style="color:#34d399">LLM: Google Gemini (set GOOGLE_API_KEY)</span>
</div>
""", unsafe_allow_html=True)

if st.button(" Refresh", key="refresh_ai"):
 st.rerun()
