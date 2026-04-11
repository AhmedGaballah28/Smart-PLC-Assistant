"""
Smart PLC Assistant — Streamlit Dashboard
Multi-page app with live factory view, analytics, AI console, fault injection.

Run: streamlit run dashboard/app.py
"""

import sys
import os
from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

st.set_page_config(
 page_title="Smart PLC Assistant",
 page_icon="",
 layout="wide",
 initial_sidebar_state="expanded",
)

# ── Custom CSS ───────────────────────────────────────────────────────────────
st.markdown("""
<style>
 @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');

 html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

 /* Dark glass sidebar */
 [data-testid="stSidebar"] {
 background: linear-gradient(160deg, #0f172a 0%, #1e293b 100%);
 border-right: 1px solid rgba(99,102,241,0.2);
 }
 [data-testid="stSidebar"] * { color: #e2e8f0 !important; }

 /* Main background */
 .stApp { background: linear-gradient(135deg, #0f172a 0%, #1a1f35 50%, #0f172a 100%); }

 /* Cards */
 .glass-card {
 background: rgba(30,41,59,0.8);
 border: 1px solid rgba(99,102,241,0.25);
 border-radius: 16px;
 padding: 1.2rem;
 backdrop-filter: blur(12px);
 margin-bottom: 1rem;
 box-shadow: 0 4px 24px rgba(0,0,0,0.3);
 transition: box-shadow 0.2s;
 }
 .glass-card:hover { box-shadow: 0 8px 32px rgba(99,102,241,0.2); }

 /* Status badges */
 .badge-ok { background:#10b981; color:#fff; padding:2px 10px; border-radius:12px; font-size:0.75rem; font-weight:600; }
 .badge-warn { background:#f59e0b; color:#fff; padding:2px 10px; border-radius:12px; font-size:0.75rem; font-weight:600; }
 .badge-crit { background:#ef4444; color:#fff; padding:2px 10px; border-radius:12px; font-size:0.75rem; font-weight:600; }
 .badge-stop { background:#6366f1; color:#fff; padding:2px 10px; border-radius:12px; font-size:0.75rem; font-weight:600; }

 /* Metric overrides */
 [data-testid="stMetric"] {
 background: rgba(30,41,59,0.6);
 border: 1px solid rgba(99,102,241,0.2);
 border-radius: 12px;
 padding: 0.8rem 1rem;
 }
 [data-testid="stMetricValue"] { font-size: 1.6rem !important; color: #818cf8 !important; }
 [data-testid="stMetricLabel"] { color: #94a3b8 !important; font-size: 0.75rem !important; }

 /* Alert boxes */
 .alert-warning { background:rgba(245,158,11,0.1); border-left:4px solid #f59e0b; padding:0.8rem 1rem; border-radius:8px; margin:0.5rem 0; }
 .alert-critical { background:rgba(239,68,68,0.1); border-left:4px solid #ef4444; padding:0.8rem 1rem; border-radius:8px; margin:0.5rem 0; }
 .alert-ok { background:rgba(16,185,129,0.1); border-left:4px solid #10b981; padding:0.8rem 1rem; border-radius:8px; margin:0.5rem 0; }

 /* Header gradient */
 .main-header {
 background: linear-gradient(90deg, #6366f1, #8b5cf6, #06b6d4);
 -webkit-background-clip: text; -webkit-text-fill-color: transparent;
 font-size: 2rem; font-weight: 700; margin-bottom: 0;
 }

 /* Hide Streamlit branding */
 #MainMenu, footer { visibility: hidden; }
 .stDeployButton { display: none; }

 /* Station state colour coding */
 .state-idle { color: #94a3b8; }
 .state-running { color: #10b981; }
 .state-fault { color: #ef4444; }
 .state-waiting { color: #f59e0b; }
</style>
""", unsafe_allow_html=True)

# ── Sidebar ───────────────────────────────────────────────────────────────────
with st.sidebar:
 st.markdown("## Smart PLC")
 st.markdown("**TV Assembly Line**")
 st.markdown("---")

 pages = {
  " Live Factory":  "pages/1_live_factory.py",
  " Analytics":   "pages/2_analytics.py",
  " AI Agent Console": "pages/3_ai_console.py",
  " Fault Injection": "pages/4_fault_injection.py",
 }

 st.markdown("### Navigation")
 for name in pages:
  st.markdown(f"- **{name}**")

 st.markdown("---")
 st.markdown("**Connection**")

 # Try MQTT status
 try:
  import paho.mqtt.client as mqtt_check
  st.success("MQTT Support: Connected")
 except Exception:
  st.error("MQTT Support: Missing")

 st.markdown("---")
 st.caption("Smart PLC Assistant v2.0\nTV Assembly Production Line")

# ── Main landing page ─────────────────────────────────────────────────────────
st.markdown('<p class="main-header"> Smart PLC Assistant</p>', unsafe_allow_html=True)
st.markdown("**AI-Powered TV Assembly Production Line Monitor**")
st.markdown("---")

col1, col2, col3, col4 = st.columns(4)
with col1:
 st.markdown('<div class="glass-card"><h3>7 Stations</h3><p style="color:#94a3b8">Full assembly line<br>5 complete OK + 2 new</p></div>', unsafe_allow_html=True)
with col2:
 st.markdown('<div class="glass-card"><h3>4 AI Agents</h3><p style="color:#94a3b8">Monitor → Diagnose<br>Repair → Validate</p></div>', unsafe_allow_html=True)
with col3:
 st.markdown('<div class="glass-card"><h3>Gemini LLM</h3><p style="color:#94a3b8">Google AI Studio<br>RAG + ChromaDB</p></div>', unsafe_allow_html=True)
with col4:
 st.markdown('<div class="glass-card"><h3>MQTT Telemetry</h3><p style="color:#94a3b8">Real-time sensor data<br>Fault injection</p></div>', unsafe_allow_html=True)

st.markdown("## System Architecture")
st.markdown("""
```
Factory I/O (Modbus TCP)
  │
  ▼
┌─────────────────────────────────────────────────────────┐
│    Production Line (7 Stations)     │
│ Stn1→Stn2→Stn3→[Stn4 NEW]→[Stn5 NEW]→Stn6→Stn7→WH │
└─────────────────────────────┬───────────────────────────┘
        │ MQTT Telemetry
        ▼
┌─────────────────────────────────────────────────────────┐
│     AI Agent Pipeline      │
│ Monitor Agent → Diagnostic Agent → Repair Agent   │
│         → Safety Validator  │
└─────────────────────────────┬───────────────────────────┘
        │ Results + Proposals
        ▼
┌─────────────────────────────────────────────────────────┐
│    Streamlit Dashboard (this app)    │
│ Live View │ Analytics │ AI Console │ Fault Injection │
└─────────────────────────────────────────────────────────┘
```
""")

st.markdown("## Quick Start")
st.code("""
# 1. Start Mosquitto MQTT broker (already installed)
net start mosquitto

# 2. Set your Google API Key
$env:GOOGLE_API_KEY = "your_key_here"

# 3. Build knowledge base (once)
python knowledge_base/build_kb.py

# 4. Start AI agents (separate terminal)
python agents/run_agents.py

# 5. Run the production line (separate terminal, needs Factory I/O)
python tests/run_line.py

# 6. This dashboard auto-updates every 2s
""", language="bash")

st.info(" Use the sidebar pages to navigate. The dashboard works with live Factory I/O data or in **demo mode** (simulated data) when Factory I/O is not running.")
