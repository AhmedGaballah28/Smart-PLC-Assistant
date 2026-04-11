"""
Page 2: Production Analytics
"""

import sys
import time
import random
from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.demo_simulator import get_simulator

try:
 import plotly.graph_objects as go
 import plotly.express as px
 from plotly.subplots import make_subplots
 PLOTLY = True
except ImportError:
 PLOTLY = False

st.set_page_config(page_title="Analytics | Smart PLC", page_icon="", layout="wide")

st.markdown("""
<style>
 @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
 html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
 .stApp { background: linear-gradient(135deg,#0f172a 0%,#1a1f35 100%); }
 [data-testid="stSidebar"] { background: linear-gradient(160deg,#0f172a,#1e293b); }
 #MainMenu, footer { visibility: hidden; }
 [data-testid="stMetric"] {
 background: rgba(30,41,59,0.7);
 border: 1px solid rgba(99,102,241,0.2);
 border-radius: 12px; padding: 0.8rem 1rem;
 }
 [data-testid="stMetricValue"] { color: #818cf8 !important; }
 [data-testid="stMetricLabel"] { color: #94a3b8 !important; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="background:linear-gradient(90deg,#6366f1,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:1.8rem;font-weight:700"> Production Analytics</h1>', unsafe_allow_html=True)
st.caption("OEE metrics, cycle time trends, and quality analysis — Demo Mode")

sim = get_simulator()
states = sim.get_all_states()
summary = sim.get_production_summary()

# ── KPI Row ──────────────────────────────────────────────────────────────────
k1, k2, k3, k4, k5, k6 = st.columns(6)
k1.metric("Total Products", summary["total_products"], f"+{random.randint(1,3)}")
k2.metric("QC Pass Rate", f"{summary['pass_rate']}%")
k3.metric("Throughput/hr", f"{summary['throughput_per_hour']}")
k4.metric("Active Faults", summary["active_faults"])
k5.metric("Runtime",  f"{summary['runtime_seconds']//60}m {summary['runtime_seconds']%60}s")
avg_oee = round(sum(s.get("counters", {}).get("oee", 0) for s in states.values()) / max(len(states), 1), 1)
k6.metric("Avg OEE",  f"{avg_oee}%")

st.markdown("---")

if not PLOTLY:
 st.warning("Plotly not installed — install with: pip install plotly")
 st.stop()

# ── OEE Gauges ───────────────────────────────────────────────────────────────
st.markdown("### OEE by Station")
station_ids = list(states.keys())
oee_values = [states[s].get("counters", {}).get("oee", 75) for s in station_ids]
station_labels = [states[s].get("name", s) for s in station_ids]

fig_oee = go.Figure()
for label, val in zip(station_labels, oee_values):
 color = "#10b981" if val> 80 else ("#f59e0b" if val> 65 else "#ef4444")
 fig_oee.add_trace(go.Bar(
  name=label, x=[label], y=[val],
  marker_color=color,
  text=f"{val}%", textposition="outside",
  width=0.6,
 ))
fig_oee.add_hline(y=80, line_dash="dot", line_color="#6366f1", annotation_text="World-class 80%")
fig_oee.add_hline(y=65, line_dash="dot", line_color="#f59e0b", annotation_text="Warning 65%")
fig_oee.update_layout(
 paper_bgcolor="rgba(0,0,0,0)",
 plot_bgcolor="rgba(15,23,42,0.5)",
 font_color="#e2e8f0",
 showlegend=False,
 yaxis=dict(range=[0, 105], title="OEE %", gridcolor="rgba(99,102,241,0.1)"),
 xaxis=dict(gridcolor="rgba(99,102,241,0.1)"),
 margin=dict(l=20, r=20, t=20, b=20),
 height=350,
)
st.plotly_chart(fig_oee, use_container_width=True)

# ── Sensor Heatmap ────────────────────────────────────────────────────────────
col_a, col_b = st.columns(2)

with col_a:
 st.markdown("### Temperature vs Vibration")
 temps = [states[s]["sensors"]["temperature"] for s in station_ids]
 vibs = [states[s]["sensors"]["vibration"] for s in station_ids]
 fig_scatter = go.Figure(go.Scatter(
  x=temps, y=vibs,
  mode="markers+text",
  text=[f"Stn{i+1}" for i in range(len(station_ids))],
  textposition="top center",
  marker=dict(
   size=14,
   color=[states[s].get("counters", {}).get("oee", 75) for s in station_ids],
   colorscale="RdYlGn",
   cmin=50, cmax=95,
   showscale=True,
   colorbar=dict(title="OEE %", thickness=12),
   line=dict(color="rgba(99,102,241,0.6)", width=2),
  ),
 ))
 fig_scatter.add_vline(x=50, line_dash="dot", line_color="#f59e0b")
 fig_scatter.add_hline(y=30, line_dash="dot", line_color="#f59e0b")
 fig_scatter.update_layout(
  paper_bgcolor="rgba(0,0,0,0)",
  plot_bgcolor="rgba(15,23,42,0.5)",
  font_color="#e2e8f0",
  xaxis=dict(title="Temperature (°C)", gridcolor="rgba(99,102,241,0.1)"),
  yaxis=dict(title="Vibration (mm/s)", gridcolor="rgba(99,102,241,0.1)"),
  margin=dict(l=20, r=20, t=30, b=20),
  height=320,
 )
 st.plotly_chart(fig_scatter, use_container_width=True)

with col_b:
 st.markdown("### Production Count per Station")
 prods = [states[s].get("counters", {}).get("products_completed", 0) for s in station_ids]
 fig_bar = go.Figure(go.Bar(
  x=[f"Stn {i+1}" for i in range(len(station_ids))],
  y=prods,
  marker=dict(
   color=prods,
   colorscale=[[0, "#6366f1"], [0.5, "#8b5cf6"], [1, "#06b6d4"]],
  ),
  text=prods, textposition="outside",
 ))
 fig_bar.update_layout(
  paper_bgcolor="rgba(0,0,0,0)",
  plot_bgcolor="rgba(15,23,42,0.5)",
  font_color="#e2e8f0",
  yaxis=dict(title="Products", gridcolor="rgba(99,102,241,0.1)"),
  xaxis=dict(gridcolor="rgba(99,102,241,0.1)"),
  margin=dict(l=20, r=20, t=30, b=20),
  height=320,
  showlegend=False,
 )
 st.plotly_chart(fig_bar, use_container_width=True)

# ── QC Pie ───────────────────────────────────────────────────────────────────
st.markdown("### Quality Control Breakdown")
col_p1, col_p2 = st.columns([1, 2])
with col_p1:
 passed = summary["passed"]
 failed = summary["failed"]
 fig_pie = go.Figure(go.Pie(
  labels=["Passed OK", "Failed Error"],
  values=[max(passed, 1), max(failed, 1)],
  hole=0.55,
  marker=dict(colors=["#10b981", "#ef4444"]),
  textfont=dict(color="#e2e8f0"),
 ))
 fig_pie.update_layout(
  paper_bgcolor="rgba(0,0,0,0)",
  font_color="#e2e8f0",
  margin=dict(l=0, r=0, t=20, b=0),
  height=260,
  showlegend=True,
  legend=dict(font=dict(color="#e2e8f0")),
 )
 st.plotly_chart(fig_pie, use_container_width=True)

with col_p2:
 st.markdown("#### Sensor Summary")
 for sid in station_ids:
  s = states[sid]
  sensors = s.get("sensors", {})
  t = sensors.get("temperature", 0)
  v = sensors.get("vibration", 0)
  p = sensors.get("power_kw", 0)
  name = s.get("name", sid)
  t_bar = min(int(t / 70 * 100), 100)
  v_bar = min(int(v / 60 * 100), 100)
  st.markdown(f"**{name}**")
  col_x, col_y, col_z = st.columns(3)
  col_x.progress(t_bar, text=f"🌡 {t}°C")
  col_y.progress(v_bar, text=f" {v}mm/s")
  col_z.progress(min(int(p/5*100), 100), text=f" {p}kW")

if st.button(" Refresh", key="refresh_analytics"):
 st.rerun()
