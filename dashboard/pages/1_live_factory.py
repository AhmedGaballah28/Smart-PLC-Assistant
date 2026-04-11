"""
Page 1: Live Factory — Real-time station status cards
"""

import sys
import time
from pathlib import Path
import streamlit as st

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from dashboard.demo_simulator import get_simulator

st.set_page_config(page_title="Live Factory | Smart PLC", page_icon="", layout="wide")

st.markdown("""
<style>
 @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&family=JetBrains+Mono:wght@400&display=swap');
 html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
 .stApp { background: linear-gradient(135deg, #0f172a 0%, #1a1f35 100%); }
 [data-testid="stSidebar"] { background: linear-gradient(160deg, #0f172a 0%, #1e293b 100%); }
 #MainMenu, footer { visibility: hidden; }

 .station-card {
 background: rgba(30,41,59,0.85);
 border: 1px solid rgba(99,102,241,0.25);
 border-radius: 16px;
 padding: 1.2rem;
 margin-bottom: 1rem;
 transition: border-color 0.3s, box-shadow 0.3s;
 }
 .station-card.fault {
 border-color: rgba(239,68,68,0.6);
 box-shadow: 0 0 20px rgba(239,68,68,0.15);
 }
 .station-card.ok {
 border-color: rgba(16,185,129,0.4);
 }
 .station-card.warn {
 border-color: rgba(245,158,11,0.5);
 box-shadow: 0 0 16px rgba(245,158,11,0.1);
 }
 .station-title { font-size: 1rem; font-weight: 700; color: #e2e8f0; margin:0 0 4px 0; }
 .station-id { font-size: 0.7rem; color: #64748b; font-family: 'JetBrains Mono', monospace; }
 .station-state { font-size: 0.85rem; color: #94a3b8; margin-top: 8px; }
 .sensor-row { display: flex; gap: 18px; margin-top: 10px; flex-wrap: wrap; }
 .sensor-item { text-align: center; min-width: 60px; }
 .sensor-val { font-size: 1.1rem; font-weight: 600; color: #818cf8; font-family: 'JetBrains Mono'; }
 .sensor-lbl { font-size: 0.65rem; color: #64748b; margin-top: 2px; }
 .fault-badge { background: rgba(239,68,68,0.2); border: 1px solid #ef4444; color: #fca5a5;
     border-radius: 8px; padding: 2px 8px; font-size: 0.7rem; display: inline-block; margin: 2px; }
 .ok-badge  { background: rgba(16,185,129,0.15); border: 1px solid #10b981; color: #6ee7b7;
     border-radius: 8px; padding: 2px 10px; font-size: 0.75rem; display: inline-block; }
 .prod-count { font-size: 1.8rem; font-weight: 700; color: #34d399; font-family: 'JetBrains Mono'; }
</style>
""", unsafe_allow_html=True)

# ── Header ──────────────────────────────────────────────────────────────────
st.markdown('<h1 style="background:linear-gradient(90deg,#6366f1,#06b6d4);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:1.8rem;font-weight:700"> Live Factory</h1>', unsafe_allow_html=True)
st.caption("Real-time station telemetry — auto-refreshes every 2 seconds | Demo Mode")

sim = get_simulator()

# ── Summary strip ────────────────────────────────────────────────────────────
summary = sim.get_production_summary()
c1, c2, c3, c4, c5 = st.columns(5)
c1.metric(" Total Produced", summary["total_products"])
c2.metric("Passed QC", summary["passed"])
c3.metric("Failed QC", summary["failed"])
c4.metric(" Pass Rate", f"{summary['pass_rate']}%")
c5.metric(" Active Faults", summary["active_faults"])

st.markdown("---")

# ── Station cards ────────────────────────────────────────────────────────────
states = sim.get_all_states()

STATION_ORDER = [
 "station_1", "station_2", "station_3",
 "station_4", "station_5",
 "station_6", "station_7",
]

NEW_STATIONS = {"station_4", "station_5"}

cols_row1 = st.columns(4)
cols_row2 = st.columns(3)

all_cols = cols_row1 + cols_row2

for i, sid in enumerate(STATION_ORDER):
 data = states.get(sid, {})
 if not data:
  continue

 sensors = data.get("sensors", {})
 counters = data.get("counters", {})
 faults = data.get("faults", {})
 temp = sensors.get("temperature", 0)
 vib = sensors.get("vibration", 0)
 pwr = sensors.get("power_kw", 0)
 name = data.get("name", sid)
 state_str = data.get("state", "unknown")
 emerging = data.get("emergency_active", False)
 has_fault = faults.get("has_fault", False)

 # Determine card class
 if emerging or (has_fault and "CRITICAL" in str(faults.get("active", []))):
  card_class = "fault"
 elif has_fault or temp> 48 or vib> 28:
  card_class = "warn"
 else:
  card_class = "ok"

 # Temperature colour
 t_color = "#10b981" if temp < 45 else ("#f59e0b" if temp < 55 else "#ef4444")
 v_color = "#10b981" if vib < 25 else ("#f59e0b" if vib < 35 else "#ef4444")
 p_color = "#10b981" if pwr < 3 else ("#f59e0b" if pwr < 4.5 else "#ef4444")

 new_badge = ' <span style="background:#6366f1;color:#fff;border-radius:6px;padding:1px 6px;font-size:0.65rem;vertical-align:middle">NEW</span>' if sid in NEW_STATIONS else ""

 fault_html = ""
 for f in faults.get("active", []):
  fault_html += f'<span class="fault-badge">{f}</span>'
 if not has_fault:
  fault_html = '<span class="ok-badge">Healthy</span>'

 oee = counters.get("oee", 0)
 oee_color = "#10b981" if oee> 80 else ("#f59e0b" if oee> 65 else "#ef4444")

 html = f"""
<div class="station-card {card_class}">
 <div class="station-title">Stn {i+1} — {name}{new_badge}</div>
 <div class="station-id">{sid}</div>
 <div class="station-state"> State: <b style="color:#c7d2fe">{state_str.replace('_',' ')}</b></div>
 <div class="sensor-row">
 <div class="sensor-item">
  <div class="sensor-val" style="color:{t_color}">{temp}°</div>
  <div class="sensor-lbl">TEMP °C</div>
 </div>
 <div class="sensor-item">
  <div class="sensor-val" style="color:{v_color}">{vib}</div>
  <div class="sensor-lbl">VIB mm/s</div>
 </div>
 <div class="sensor-item">
  <div class="sensor-val" style="color:{p_color}">{pwr}</div>
  <div class="sensor-lbl">PWR kW</div>
 </div>
 <div class="sensor-item">
  <div class="prod-count">{counters.get('products_completed', 0)}</div>
  <div class="sensor-lbl">PRODUCTS</div>
 </div>
 <div class="sensor-item">
  <div class="sensor-val" style="color:{oee_color}">{oee}%</div>
  <div class="sensor-lbl">OEE</div>
 </div>
 </div>
 <div style="margin-top:10px">{fault_html}</div>
</div>
"""
 with all_cols[i]:
  st.markdown(html, unsafe_allow_html=True)

# ── Auto-refresh ─────────────────────────────────────────────────────────────
time.sleep(0.3)
st.markdown(f'<div style="color:#475569;font-size:0.7rem;text-align:right">Last update: {time.strftime("%H:%M:%S")}</div>', unsafe_allow_html=True)

if st.button(" Refresh Now", key="refresh_live"):
 st.rerun()

# Auto-refresh every 2s
st.markdown("""
<script>
 setTimeout(function(){ window.location.reload(); }, 2000);
</script>
""", unsafe_allow_html=True)
