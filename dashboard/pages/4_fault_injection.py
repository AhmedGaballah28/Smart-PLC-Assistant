"""
Page 4: Fault Injection
"""

import sys
from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.demo_simulator import get_simulator

st.set_page_config(page_title="Fault Injection | Smart PLC", page_icon="", layout="wide")

st.markdown("""
<style>
 @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
 html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
 .stApp { background: linear-gradient(135deg,#0f172a 0%,#1a1f35 100%); }
 [data-testid="stSidebar"] { background: linear-gradient(160deg,#0f172a,#1e293b); }
 #MainMenu, footer { visibility: hidden; }
 .stButton>button {
 border-radius: 10px; font-weight: 600; transition: all 0.2s;
 border: 1px solid rgba(99,102,241,0.4);
 }
 .stButton>button:hover { box-shadow: 0 0 12px rgba(99,102,241,0.3); }
 [data-testid="stSelectbox"] label { color: #94a3b8 !important; }
 [data-testid="stSlider"] label { color: #94a3b8 !important; }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 style="background:linear-gradient(90deg,#ef4444,#f59e0b,#6366f1);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:1.8rem;font-weight:700"> Fault Injection Console</h1>', unsafe_allow_html=True)
st.caption("Inject and clear faults on any station to test AI diagnostic pipeline | Demo Mode")

sim = get_simulator()
states = sim.get_all_states()

st.markdown("---")

# ── Inject fault ──────────────────────────────────────────────────────────────
st.markdown("## Inject a Fault")

STATION_NAMES = {
 "station_1": "Stn 1 — Chassis Loading",
 "station_2": "Stn 2 — PCB Installation",
 "station_3": "Stn 3 — Display Panel",
 "station_4": "Stn 4 — Wiring Connection 🆕",
 "station_5": "Stn 5 — Back Cover Assembly 🆕",
 "station_6": "Stn 6 — Quality Control",
 "station_7": "Stn 7 — Sorting & Output",
}

FAULT_TYPES = {
 "overheat":  " Overheat — motor/sensor thermal fault",
 "power":   " Power Brownout — electrical fluctuation",
 "belt_slip":  " Belt Slip — mechanical slippage",
 "sensor_drift": " Sensor Drift — false readings",
 "gripper":  " Gripper Failure — (Station 2 only)",
 "pp_jam":   " P&P Jam — pick-and-place stuck (Stn 2)",
 "positioner_jam": " Positioner Jam — (Station 3 only)",
 "pusher_jam":  " Pusher Jam — (Station 5 only)",
 "vision_error": " Vision Error — QC wrong readings (Stn 6)",
 "sorter_jam":  " Sorter Jam — pivot arm stuck (Stn 7)",
 "misroute":  " Misroute — good/reject inverted (Stn 7)",
}

col1, col2, col3 = st.columns([2, 2, 1])

with col1:
 selected_station = st.selectbox(
  "Target Station",
  options=list(STATION_NAMES.keys()),
  format_func=lambda x: STATION_NAMES[x],
  key="inj_station",
 )

with col2:
 selected_fault = st.selectbox(
  "Fault Type",
  options=list(FAULT_TYPES.keys()),
  format_func=lambda x: FAULT_TYPES[x],
  key="inj_fault",
 )

with col3:
 severity = st.slider("Severity", 1, 5, 3, key="inj_sev",
       help="1=Minor … 5=CRITICAL")

# Severity description
SEV_LABELS = {1: "Minor", 2: "Low", 3: "Medium", 4: "⚠️ High", 5: "Alert: CRITICAL"}
st.caption(f"Severity {severity}/5 — **{SEV_LABELS[severity]}**")

col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 3])

with col_btn1:
 if st.button("Alert: Inject Fault", key="btn_inject", type="primary"):
  sim.inject_fault(selected_station, selected_fault)
  stn_name = STATION_NAMES[selected_station]
  st.error(f"Alert: Fault injected: **{selected_fault}** on **{stn_name}** (severity {severity})")
  st.info("→ Watch the AI Console to see Monitor → Diagnose → Repair pipeline activate")

with col_btn2:
 if st.button("OK Clear Station Faults", key="btn_clear_stn"):
  sim.clear_faults(selected_station)
  st.success(f"Faults cleared for {STATION_NAMES[selected_station]}")

with col_btn3:
 if st.button(" Clear ALL Faults", key="btn_clear_all"):
  sim.clear_faults("all")
  st.success("All station faults cleared")

st.markdown("---")

# ── Current fault status ──────────────────────────────────────────────────────
st.markdown("## Current Fault Status")

cols = st.columns(4)
fault_stations = []
for i, (sid, data) in enumerate(states.items()):
 has_fault = data.get("faults", {}).get("has_fault", False)
 faults = data.get("faults", {}).get("active", [])
 name = data.get("name", sid)
 temp = data.get("sensors", {}).get("temperature", 0)
 with cols[i % 4]:
  if has_fault:
   fault_stations.append(sid)
   st.markdown(f"""
<div style="background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.4);border-radius:12px;padding:0.9rem;margin-bottom:0.6rem">
 <div style="font-weight:700;color:#fca5a5;font-size:0.85rem"> {name}</div>
 <div style="font-size:0.75rem;color:#94a3b8;margin-top:4px">Faults:</div>
 {"".join(f'<div style="background:rgba(239,68,68,0.2);border-radius:6px;padding:2px 8px;font-size:0.72rem;color:#fca5a5;display:inline-block;margin:2px">{f}</div>' for f in faults)}
 <div style="font-size:0.72rem;color:#64748b;margin-top:6px">Temp: {temp}°C</div>
</div>
""", unsafe_allow_html=True)
  else:
   st.markdown(f"""
<div style="background:rgba(16,185,129,0.07);border:1px solid rgba(16,185,129,0.25);border-radius:12px;padding:0.9rem;margin-bottom:0.6rem">
 <div style="font-weight:600;color:#6ee7b7;font-size:0.85rem">OK {name}</div>
 <div style="font-size:0.72rem;color:#64748b;margin-top:4px">No active faults · {temp}°C</div>
</div>
""", unsafe_allow_html=True)

if not fault_stations:
 st.success("All stations healthy — no active faults")

# ── Quick fault scenarios ─────────────────────────────────────────────────────
st.markdown("---")
st.markdown("## Quick Scenarios")
st.caption("Pre-configured fault scenarios to demonstrate the AI pipeline")

s1, s2, s3, s4 = st.columns(4)

with s1:
 if st.button(" Motor Overheat\n(Station 1, Sev 4)", key="scene1", use_container_width=True):
  sim.inject_fault("station_1", "overheat")
  st.warning("Injected: Overheat on Station 1 (severity 4)")

with s2:
 if st.button(" Sensor Cascade\n(All stations)", key="scene2", use_container_width=True):
  for sid in ["station_1", "station_3", "station_6"]:
   sim.inject_fault(sid, "sensor_drift")
  st.warning("Injected: Sensor drift on Stations 1, 3, 6")

with s3:
 if st.button(" Power Brownout\n(Station 2 + 4)", key="scene3", use_container_width=True):
  sim.inject_fault("station_2", "power")
  sim.inject_fault("station_4", "power")
  st.warning("Injected: Power faults on Stations 2 and 4")

with s4:
 if st.button(" New Stn5 Pusher\nJam (Sev 3)", key="scene4", use_container_width=True):
  sim.inject_fault("station_5", "pusher_jam")
  st.warning("Injected: Pusher jam on Station 5 (NEW station)")

if st.button(" Refresh Status", key="refresh_faults"):
 st.rerun()
