"""
Physical constants for each station type.

All values are calibrated against the actual TemperatureSimulator,
VibrationSimulator, PowerSimulator in factory/stations/station1.py
and the FAULT_CATALOG in runners/run_twin.py.

Units:
  temperature  — Celsius (°C)
  time         — seconds (s)
  speed        — RPM or % of nominal
  pressure     — bar
  vibration    — mm/s RMS
  power        — kW
"""

# ═══════════════════════════════════════════════════════════════════
# THERMAL MODEL PARAMETERS
# Derived from TemperatureSimulator dataclass in station1.py:
#   ambient=25, heating_rate=0.15, cooling_rate=0.05,
#   target_running=45, fault_offset = severity * 8.0
# ═══════════════════════════════════════════════════════════════════

THERMAL_PARAMS = {
    "station1": {
        "T_ambient": 25.0,        # °C
        "T_steady_normal": 45.0,  # °C at full speed, no fault
        "heating_rate": 0.15,     # per-step gain toward target
        "cooling_rate": 0.05,     # per-step decay toward ambient
        "fault_offset_per_severity": 8.0,  # °C added to target per severity level
        "max_temp": 80.0,         # physical clamp
        "critical_temp": 70.0,    # triggers emergency above this
        "noise_std": 0.3,         # sensor noise σ
        "description": "Belt motor winding cabinet",
    },
    "machining": {
        "T_ambient": 25.0,
        "T_steady_normal": 45.0,
        "heating_rate": 0.15,
        "cooling_rate": 0.05,
        "fault_offset_per_severity": 8.0,
        "max_temp": 90.0,
        "critical_temp": 85.0,
        "noise_std": 0.3,
        "description": "CNC spindle bearings + coolant",
    },
    "station2": {
        "T_ambient": 25.0,
        "T_steady_normal": 40.0,
        "heating_rate": 0.12,
        "cooling_rate": 0.06,
        "fault_offset_per_severity": 7.0,
        "max_temp": 75.0,
        "critical_temp": 65.0,
        "noise_std": 0.2,
        "description": "Stepper motor + P&P actuator",
    },
    "station3": {
        "T_ambient": 25.0,
        "T_steady_normal": 38.0,
        "heating_rate": 0.10,
        "cooling_rate": 0.06,
        "fault_offset_per_severity": 6.0,
        "max_temp": 70.0,
        "critical_temp": 60.0,
        "noise_std": 0.2,
        "description": "Solenoid coil (positioner)",
    },
    "station6": {
        "T_ambient": 25.0,
        "T_steady_normal": 42.0,
        "heating_rate": 0.12,
        "cooling_rate": 0.05,
        "fault_offset_per_severity": 7.0,
        "max_temp": 85.0,
        "critical_temp": 75.0,
        "noise_std": 0.3,
        "description": "Vision CPU + LED driver",
    },
    "station7": {
        "T_ambient": 25.0,
        "T_steady_normal": 36.0,
        "heating_rate": 0.10,
        "cooling_rate": 0.07,
        "fault_offset_per_severity": 6.0,
        "max_temp": 70.0,
        "critical_temp": 60.0,
        "noise_std": 0.2,
        "description": "Pivot actuator seal",
    },
}

# ═══════════════════════════════════════════════════════════════════
# BELT DYNAMICS PARAMETERS
# Derived from fault effects in FAULT_CATALOG:
#   belt_slip → stutter probability = severity * 0.08
#   power brownout → belt OFF prob = severity * 0.06, duration 0.3-0.8s
# ═══════════════════════════════════════════════════════════════════

BELT_PARAMS = {
    "station1": {
        "belt_length_m": 1.5,         # meters (conveyor length)
        "nominal_speed_mps": 0.25,    # meters/sec at 100%
        "time_constant_s": 0.8,       # belt spin-up τ
        "slip_prob_per_severity": 0.08,  # belt_slip fault
        "brownout_prob_per_severity": 0.06,  # power fault
        "brownout_duration_range": (0.3, 0.8),  # seconds
        "stutter_on_off_s": (0.15, 0.10),  # belt_slip on/off times (sev 1)
        "description": "Main belt conveyor 1",
    },
    "station2": {
        "belt_length_m": 1.2,
        "nominal_speed_mps": 0.20,
        "time_constant_s": 0.6,
        "slip_prob_per_severity": 0.08,
        "brownout_prob_per_severity": 0.06,
        "brownout_duration_range": (0.3, 0.8),
        "stutter_on_off_s": (0.15, 0.10),
        "description": "Assembly belt 2",
    },
    "station3": {
        "belt_length_m": 1.0,
        "nominal_speed_mps": 0.20,
        "time_constant_s": 0.6,
        "slip_prob_per_severity": 0.08,
        "brownout_prob_per_severity": 0.06,
        "brownout_duration_range": (0.3, 0.8),
        "stutter_on_off_s": (0.15, 0.10),
        "description": "Panel mounting belt 3",
    },
    "station6": {
        "belt_length_m": 1.0,
        "nominal_speed_mps": 0.20,
        "time_constant_s": 0.6,
        "slip_prob_per_severity": 0.08,
        "brownout_prob_per_severity": 0.06,
        "brownout_duration_range": (0.3, 0.8),
        "stutter_on_off_s": (0.15, 0.10),
        "description": "QC inspection belt 4",
    },
    "station7": {
        "belt_length_m": 1.2,
        "nominal_speed_mps": 0.22,
        "time_constant_s": 0.7,
        "slip_prob_per_severity": 0.08,
        "brownout_prob_per_severity": 0.06,
        "brownout_duration_range": (0.3, 0.8),
        "stutter_on_off_s": (0.15, 0.10),
        "description": "Sorting belt 5",
    },
}

# ═══════════════════════════════════════════════════════════════════
# PRODUCTION / CYCLE TIME PARAMETERS
# Derived from FAULT_CATALOG severity_map multipliers:
#   machining overheat sev3 → multiplier 1.60
#   station1 overheat sev3 → timing_multiplier 1.50
# ═══════════════════════════════════════════════════════════════════

CYCLE_TIME_PARAMS = {
    "machining": {
        "base_cycle_s": 15.0,
        "fault_multipliers": {
            "overheat": {1: 1.15, 2: 1.35, 3: 1.60, 4: 2.00, 5: 2.50},
            "cnc_jam": {1: 1.04, 2: 1.08, 3: 1.12, 4: 1.18, 5: 1.25},
        },
        "description": "CNC machining cycle",
    },
    "station1": {
        "base_cycle_s": 6.0,   # 3s inspection + ~3s transit/release
        "fault_multipliers": {
            "overheat": {1: 1.10, 2: 1.25, 3: 1.50, 4: 1.80, 5: 2.50},
        },
        "description": "Chassis loading + inspection",
    },
    "station2": {
        "base_cycle_s": 18.0,   # P&P sequence ~15s + setup
        "fault_multipliers": {
            "overheat": {1: 1.10, 2: 1.20, 3: 1.40, 4: 1.70, 5: 2.00},
        },
        "description": "PCB pick & place assembly",
    },
    "station3": {
        "base_cycle_s": 10.0,  # 5s mount + transit
        "fault_multipliers": {
            "overheat": {1: 1.10, 2: 1.20, 3: 1.35, 4: 1.50, 5: 1.80},
        },
        "description": "Display panel mounting",
    },
    "station6": {
        "base_cycle_s": 6.0,   # 3s inspect + transit
        "fault_multipliers": {
            "overheat": {1: 1.50, 2: 2.00, 3: 2.50, 4: 3.00, 5: 3.50},
        },
        "description": "Quality control inspection",
    },
    "station7": {
        "base_cycle_s": 5.0,   # sorting + transit
        "fault_multipliers": {
            "overheat": {1: 1.40, 2: 1.80, 3: 2.20, 4: 2.60, 5: 3.00},
        },
        "description": "Sorting & output",
    },
}

# ═══════════════════════════════════════════════════════════════════
# FAULT EFFECT PROBABILITIES
# Probabilities per cycle for discrete-event faults
# ═══════════════════════════════════════════════════════════════════

FAULT_PROBABILITIES = {
    "sensor_drift": {
        "prob_per_severity": 0.05,  # per-read probability = severity * 0.05
        "description": "Sensor returns wrong value",
    },
    "belt_slip": {
        "prob_per_severity": 0.08,
        "description": "Belt stutters ON/OFF",
    },
    "power_brownout": {
        "prob_per_severity": 0.06,
        "description": "Belt turns OFF briefly",
    },
    "gripper_failure": {
        "prob_per_severity": 0.08,  # station2 specific
        "description": "Vacuum cup fails to grab",
    },
    "vision_error": {
        "prob_per_severity": 0.10,  # station6 specific
        "description": "Camera returns wrong QC result",
    },
    "sorter_jam": {
        "prob_per_severity": 0.08,  # station7 specific
        "description": "Pivot arm ignores command",
    },
    "misroute": {
        "prob_per_severity": 0.10,  # station7 specific
        "description": "Good→reject or reject→good",
    },
    "positioner_jam": {
        "prob_per_severity": 0.08,  # station3 specific
        "description": "Clamp bar stuck",
    },
}

# ═══════════════════════════════════════════════════════════════════
# SAFE REPAIR BOUNDS (from knowledge_base/factory_troubleshooting_manual.md)
# Validation agent uses these — simulation engine also needs them
# to know the valid parameter ranges.
# ═══════════════════════════════════════════════════════════════════

SAFE_BOUNDS = {
    "spindle_speed": {"min": 1000, "max": 4000, "default": 3000, "unit": "RPM"},
    "aux_fan_speed": {"min": 0, "max": 100, "default": 50, "unit": "%"},
    "system_pressure_setpoint": {"min": 4.0, "max": 7.0, "default": 6.0, "unit": "bar"},
    "actuator_speed": {"min": 20, "max": 100, "default": 80, "unit": "%"},
    "line_speed_multiplier": {"min": 0.5, "max": 1.0, "default": 1.0, "unit": "x"},
    "vfd_smoothing": {"min": 0, "max": 5, "default": 0, "unit": "level"},
    "camera_exposure_time": {"min": 1, "max": 20, "default": 5, "unit": "ms"},
    "belt_tension": {"min": 40, "max": 90, "default": 70, "unit": "%"},
    "transfer_arm_speed": {"min": 10, "max": 80, "default": 60, "unit": "%"},
}

# ═══════════════════════════════════════════════════════════════════
# STATION ID → TYPE MAPPING
# Maps the station IDs used in MQTT topics to station types
# used in the parameter tables above.
# ═══════════════════════════════════════════════════════════════════

STATION_TYPE_MAP = {
    # Line 1
    "mc_a": "machining", "mc_b": "machining",
    "stn1": "station1", "stn2": "station2", "stn3": "station3",
    "stn6": "station6", "stn7": "station7",
    "transfer": "station7",  # transfer uses similar timing model
    "warehouse": "station7",  # simplified
    # Line 2 (same types, different instances)
    "l2_mc_a": "machining", "l2_mc_b": "machining",
    "l2_stn1": "station1", "l2_stn2": "station2", "l2_stn3": "station3",
    "l2_stn6": "station6", "l2_stn7": "station7",
}


def get_station_type(station_id: str) -> str:
    """Resolve a station_id to its type for parameter lookup."""
    return STATION_TYPE_MAP.get(station_id, "station1")
