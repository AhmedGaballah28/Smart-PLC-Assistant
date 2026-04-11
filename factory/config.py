"""
Factory Configuration
TV Assembly Production Line - All settings in one place

⚠️ MODBUS ADDRESSES MUST MATCH Factory I/O DRIVER CONFIGURATION!

ADDRESS MAP:
═══════════════════════════════════════════════════════════════
  OUTPUTS (Coils)                    INPUTS (Discrete)
  ─────────────────────────          ──────────────────────────
  0:  Stn1 Belt 1                    0:  Stn1 Sensor Entry
  1:  Stn1 Belt 1b (transition)      1:  Stn1 Sensor Station
  2:  Stn1 Emitter                   2:  Stn2 Sensor Entry
  3:  Stn1 Stop Blade                3:  Stn2 Sensor Station
  4:  Stn2 Belt                      4:  Stn2 P&P Moving X
  5:  Stn2 Stop Blade                5:  Stn2 P&P Moving Z
  6:  Stn2 Emitter (Lid)             6:  Stn2 P&P Item Detected
  7:  Stn2 P&P Move X
  8:  Stn2 P&P Move Z
  9:  Stn2 P&P Grab
═══════════════════════════════════════════════════════════════
"""

# =============================================================================
# MODBUS CONNECTION (Factory I/O)
# =============================================================================
MODBUS_HOST = "127.0.0.1"
MODBUS_PORT = 502
MODBUS_SLAVE_ID = 1
MODBUS_TIMEOUT = 5.0

# =============================================================================
# STATION 1: CHASSIS LOADING & INSPECTION
# =============================================================================
STATION1_CONFIG = {
    "name": "Chassis Loading & Inspection",
    "id": "station_1",
    "description": "Loads TV chassis (blue base) and performs initial inspection",

    "io": {
        # INPUTS
        "sensor_entry":   {"address": 0, "type": "input",  "description": "Entry diffuse sensor"},
        "sensor_station": {"address": 1, "type": "input",  "description": "Station position sensor"},

        # OUTPUTS
        "belt1":      {"address": 0, "type": "output", "description": "Belt 1 (main)"},
        "belt2":      {"address": 1, "type": "output", "description": "Belt 1b (transition)"},
        "emitter":    {"address": 2, "type": "output", "description": "Emitter trigger"},
        "stop_blade": {"address": 3, "type": "output", "description": "Stop blade UP/DOWN"},
    },

    "timing": {
        "emit_pulse_duration": 0.5,
        "inspection_time": 3.0,
        "cycle_delay": 2.0,
        "product_timeout": 15.0,
        "release_confirm_time": 2.0,
    },

    "simulation": {
        "normal_temperature": 28.0,
        "temperature_noise": 0.5,
        "normal_vibration": 10.0,
        "vibration_noise": 2.0,
        "inspection_pass_rate": 0.95,
    },
}

# =============================================================================
# STATION 2: PCB BOARD INSTALLATION (Pick & Place)
# =============================================================================
#
# PICK & PLACE POSITIONING:
# ─────────────────────────
# The P&P in Factory I/O has TWO positions per axis (boolean):
#
#   X axis: FALSE = position A,  TRUE = position B
#   Z axis: FALSE = position A,  TRUE = position B
#
# You need to figure out which position is "pick" and which is "place"
# by running: python test_pp_position.py
#
# Then set the values below:
#
#   x_pick_value  = the X value when P&P is over the EMITTER (where lids appear)
#   x_place_value = the X value when P&P is over the CHASSIS (on the belt)
#
# If the P&P is not aligned over the chassis:
#   1. Run test_pp_position.py → toggle X → see where it goes
#   2. If X=TRUE is over emitter, SWAP: x_pick_value=True, x_place_value=False
#   3. If STILL not aligned, physically move the P&P in Factory I/O scene editor
#      → drag it left/right until the PLACE position is over the stop blade
#
# =============================================================================

STATION2_CONFIG = {
    "name": "PCB Board Installation",
    "id": "station_2",
    "description": "Places PCB board (product lid) onto chassis using Pick & Place",

    "io": {
        # INPUTS
        "sensor_entry":      {"address": 2, "type": "input",  "description": "Entry diffuse sensor"},
        "sensor_station":    {"address": 3, "type": "input",  "description": "Station position sensor (at blade)"},
        "pp_moving_x":       {"address": 4, "type": "input",  "description": "P&P X axis in motion"},
        "pp_moving_z":       {"address": 5, "type": "input",  "description": "P&P Z axis in motion"},
        "pp_item_detected":  {"address": 6, "type": "input",  "description": "P&P gripper has item"},

        # OUTPUTS
        "belt":       {"address": 4,  "type": "output", "description": "Station 2 belt"},
        "stop_blade": {"address": 5,  "type": "output", "description": "Stop blade 2"},
        "emitter":    {"address": 6,  "type": "output", "description": "Emitter 2 (Product Lid)"},
        "pp_move_x":  {"address": 7,  "type": "output", "description": "P&P X axis move"},
        "pp_move_z":  {"address": 8,  "type": "output", "description": "P&P Z axis move"},
        "pp_grab":    {"address": 9,  "type": "output", "description": "P&P gripper"},
    },

    # ┌──────────────────────────────────────────────────────┐
    # │  ⚡ ADJUST THESE VALUES TO FIX P&P ALIGNMENT! ⚡      │
    # │                                                       │
    # │  Run: python test_pp_position.py                      │
    # │  Toggle X to see which direction = pick / place       │
    # │  Then update the values below                         │
    # └──────────────────────────────────────────────────────┘
    "pick_and_place": {
        "x_pick_value":   False,    # X value at PICK position (over emitter)
        "x_place_value":  True,     # X value at PLACE position (over chassis)
        "z_up_value":     False,    # Z value when UP
        "z_down_value":   True,     # Z value when DOWN
        "grab_close_value": True,   # Grab value to CLOSE gripper
        "grab_open_value":  False,  # Grab value to OPEN gripper
    },

    "timing": {
        "lid_creation_time": 0.5,
        "lid_settle_time": 0.5,
        "grab_settle_time": 0.5,
        "release_settle_time": 0.5,
        "blade_lower_time": 0.5,
        "product_exit_time": 1.0,
        "pp_move_start_delay": 0.2,
        "pp_move_timeout": 10.0,
        "product_timeout": 120.0,
    },

    "simulation": {
        "normal_temperature": 30.0,
        "temperature_noise": 0.5,
        "normal_vibration": 8.0,
        "vibration_noise": 1.5,
        "pp_motor_power": 1.8,
        "belt_motor_power": 2.2,
    },
}

# =============================================================================
# STATION 4 — Wiring Connection (Coils 14-15, Inputs 10-11, Stack light 22-23)
# =============================================================================
STATION4_CONFIG = {
    "name": "Station 4 — Wiring Connection",
    "id": "station_4",
    "io": {
        "belt":           {"address": 14, "type": "output"},
        "stop_blade":     {"address": 15, "type": "output"},
        "light_green":    {"address": 22, "type": "output"},
        "light_red":      {"address": 23, "type": "output"},
        "sensor_entry":   {"address": 10, "type": "input"},
        "sensor_station": {"address": 11, "type": "input"},
    },
    "timing": {
        "wiring_time":        3.0,
        "settle_time":        0.3,
        "exit_time":          1.0,
        "product_timeout":    120.0,
        "sensor_clear_timeout": 30.0,
        "debounce_time":      0.3,
    },
    "simulation": {
        "normal_temperature": 24.0,
        "temperature_noise":  0.3,
        "normal_vibration":   3.0,
        "vibration_noise":    0.5,
        "belt_motor_power":   0.7,
    },
}

# =============================================================================
# STATION 5 — Back Cover Assembly (Coils 16-18, Inputs 12-15, Stack light 24-25)
# =============================================================================
STATION5_CONFIG = {
    "name": "Station 5 — Back Cover Assembly",
    "id": "station_5",
    "io": {
        "belt":             {"address": 16, "type": "output"},
        "stop_blade":       {"address": 17, "type": "output"},
        "pusher":           {"address": 18, "type": "output"},
        "light_green":      {"address": 24, "type": "output"},
        "light_red":        {"address": 25, "type": "output"},
        "sensor_entry":     {"address": 12, "type": "input"},
        "sensor_station":   {"address": 13, "type": "input"},
        "pusher_extended":  {"address": 14, "type": "input"},
        "pusher_retracted": {"address": 15, "type": "input"},
    },
    "timing": {
        "pre_push_wait":        1.5,
        "push_hold_time":       2.5,
        "retract_settle_time":  0.5,
        "exit_time":            1.0,
        "product_timeout":      120.0,
        "mechanical_timeout":   5.0,
        "sensor_clear_timeout": 30.0,
        "debounce_time":        0.3,
        "settle_time":          0.3,
    },
    "simulation": {
        "normal_temperature": 26.0,
        "temperature_noise":  0.3,
        "normal_vibration":   4.0,
        "vibration_noise":    0.8,
        "belt_motor_power":   0.9,
    },
}


# =============================================================================
# THRESHOLDS FOR AI MONITORING
# =============================================================================
THRESHOLDS = {
    "motor_temperature": {
        "normal_min": 20.0, "normal_max": 45.0,
        "warning": 50.0, "critical": 60.0, "unit": "°C",
    },
    "vibration": {
        "normal_max": 25.0, "warning": 35.0,
        "critical": 50.0, "unit": "mm/s",
    },
    "power_consumption": {
        "normal_max": 3.0, "warning": 4.0,
        "critical": 5.0, "unit": "kW",
    },
    "cycle_time": {
        "normal_min": 5.0, "normal_max": 15.0,
        "warning": 20.0, "critical": 30.0, "unit": "seconds",
    },
}

# =============================================================================
# MACHINING CENTER A — Blue Base Producer (Coils 40-45, Inputs 24-27)
# =============================================================================
MACHINING_A_CONFIG = {
    "name": "Machining Center A — Blue Base Producer",
    "station_id": "machining_a",
    "produce_lids": False,
    "machining_time": 3.0,
    "io": {
        "is_busy":      {"address": 24, "type": "input"},
        "has_error":    {"address": 25, "type": "input"},
        "opened":       {"address": 26, "type": "input"},
        "exit_sensor":  {"address": 27, "type": "input"},
        "emitter":      {"address": 40, "type": "output"},
        "produce_lids": {"address": 41, "type": "output"},
        "start":        {"address": 42, "type": "output"},
        "stop":         {"address": 43, "type": "output"},
        "reset":        {"address": 44, "type": "output"},
        "exit_belt":    {"address": 45, "type": "output"},
    },
    "registers": {"progress": 1},
    "timing": {
        "emitter_pulse": 0.5, "load_timeout": 30.0,
        "machining_timeout": 30.0, "exit_timeout": 5.0,
        "settle_time": 0.5, "reset_pulse": 1.0,
    },
    "simulation": {
        "normal_temperature": 25.0, "temperature_noise": 0.4,
        "normal_vibration": 1.5, "vibration_noise": 0.3,
        "cnc_motor_power": 1.2,
    },
}

# =============================================================================
# MACHINING CENTER B — Green Lid Producer (Coils 46-50, Inputs 28-31)
# =============================================================================
MACHINING_B_CONFIG = {
    "name": "Machining Center B — Green Lid Producer",
    "station_id": "machining_b",
    "produce_lids": True,
    "machining_time": 6.0,
    "io": {
        "is_busy":      {"address": 28, "type": "input"},
        "has_error":    {"address": 29, "type": "input"},
        "opened":       {"address": 30, "type": "input"},
        "exit_sensor":  {"address": 31, "type": "input"},
        "emitter":      {"address": 46, "type": "output"},
        "produce_lids": {"address": 47, "type": "output"},
        "start":        {"address": 48, "type": "output"},
        "stop":         {"address": 49, "type": "output"},
        "reset":        {"address": 50, "type": "output"},
    },
    "registers": {"progress": 2},
    "timing": {
        "emitter_pulse": 0.5, "load_timeout": 30.0,
        "machining_timeout": 45.0, "exit_timeout": 10.0,
        "settle_time": 0.5, "reset_pulse": 1.0,
    },
    "simulation": {
        "normal_temperature": 25.0, "temperature_noise": 0.4,
        "normal_vibration": 1.5, "vibration_noise": 0.3,
        "cnc_motor_power": 1.5,
    },
}

# =============================================================================
# FAULT INJECTION
# =============================================================================
FAULT_CONFIG = {
    "probabilities": {
        "belt_stutter": 0.003,
        "power_brownout": 0.002,
        "vibration_chatter": 0.002,
        "gripper_drop": 0.008,
    },
    "durations": {
        "belt_stutter": (0.2, 0.2),
        "power_brownout": (0.3, 0.4),
        "vibration_chatter": (0.15, 0.0),
        "gripper_drop": (0.0, 0.0),
    },
    "emergency_threshold": 4,
    "severity_labels": {
        1: "Minor", 2: "Low", 3: "Medium",
        4: "High ⚠️", 5: "CRITICAL 🚨",
    },
}

# =============================================================================
# LOGGING
# =============================================================================
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s │ %(levelname)-8s │ %(message)s"
LOG_DATE_FORMAT = "%H:%M:%S"