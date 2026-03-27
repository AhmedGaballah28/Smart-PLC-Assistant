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
# FUTURE STATIONS
# =============================================================================
STATION3_CONFIG = {
    "name": "Display Panel Mounting",
    "description": "Simulates LCD panel mounting using Aligners + timed stop",
    "io": {
        "sensor_entry":   {"address": 7,  "type": "input"},
        "sensor_station": {"address": 8,  "type": "input"},
        "belt":         {"address": 10, "type": "output"},
        "stop_blade":   {"address": 11, "type": "output"},
        "aligners":     {"address": 12, "type": "output"},
        "light_green":  {"address": 13, "type": "output"},
        "light_yellow": {"address": 14, "type": "output"},
    },
    "timing": {"mounting_time": 5.0, "product_timeout": 60.0},
}

STATION4_CONFIG = {
    "name": "Wiring Connection",
    "description": "Simulates internal wiring with timed stop",
    "io": {
        "sensor_entry":   {"address": 9,  "type": "input"},
        "sensor_station": {"address": 10, "type": "input"},
        "belt":         {"address": 15, "type": "output"},
        "stop_blade":   {"address": 16, "type": "output"},
        "light_green":  {"address": 17, "type": "output"},
        "light_yellow": {"address": 18, "type": "output"},
    },
    "timing": {"wiring_time": 3.0, "product_timeout": 60.0},
}

STATION5_CONFIG = {
    "name": "Back Cover Assembly",
    "description": "Simulates back cover pressing using Pusher",
    "io": {
        "sensor_entry":   {"address": 11, "type": "input"},
        "sensor_station": {"address": 12, "type": "input"},
        "belt":         {"address": 19, "type": "output"},
        "stop_blade":   {"address": 20, "type": "output"},
        "pusher":       {"address": 21, "type": "output"},
        "light_green":  {"address": 22, "type": "output"},
        "light_yellow": {"address": 23, "type": "output"},
    },
    "timing": {"cover_press_time": 4.0, "product_timeout": 60.0},
}

STATION6_CONFIG = {
    "name": "Quality Control & Testing",
    "description": "Vision sensor inspects assembled product",
    "io": {
        "sensor_entry":   {"address": 13, "type": "input"},
        "sensor_station": {"address": 14, "type": "input"},
        "vision_sensor":  {"address": 15, "type": "input"},
        "belt":         {"address": 24, "type": "output"},
        "stop_blade":   {"address": 25, "type": "output"},
        "light_green":  {"address": 26, "type": "output"},
        "light_yellow": {"address": 27, "type": "output"},
        "light_red":    {"address": 28, "type": "output"},
        "alarm":        {"address": 29, "type": "output"},
    },
    "timing": {"inspection_time": 3.0, "product_timeout": 60.0},
}

STATION7_CONFIG = {
    "name": "Sorting & Output",
    "description": "Routes products based on QC result",
    "io": {
        "sensor_entry": {"address": 16, "type": "input"},
        "belt":        {"address": 30, "type": "output"},
        "sorter":      {"address": 31, "type": "output"},
        "light_green": {"address": 32, "type": "output"},
        "light_red":   {"address": 33, "type": "output"},
    },
    "timing": {"sort_delay": 2.0, "product_timeout": 30.0},
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