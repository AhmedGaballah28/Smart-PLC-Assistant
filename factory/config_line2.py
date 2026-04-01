"""
Configuration for Assembly Line 2 (The Twin Line)
All Modbus addresses are offset by +100 from Line 1.
All Registers are offset by +10 from Line 1.
"""

STATION1_CONFIG = {
    "name": "Chassis Loading & Inspection (Line 2)",
    "id": "station_1_b",
    "description": "Loads TV chassis (blue base) and performs initial inspection",
    "io": {
        "sensor_entry": {
            "address": 100,
            "type": "input",
            "description": "Entry diffuse sensor"
        },
        "sensor_station": {
            "address": 101,
            "type": "input",
            "description": "Station position sensor"
        },
        "belt1": {
            "address": 100,
            "type": "output",
            "description": "Belt 1 (main)"
        },
        "belt2": {
            "address": 101,
            "type": "output",
            "description": "Belt 1b (transition)"
        },
        "emitter": {
            "address": 102,
            "type": "output",
            "description": "Emitter trigger"
        },
        "stop_blade": {
            "address": 103,
            "type": "output",
            "description": "Stop blade UP/DOWN"
        }
    },
    "timing": {
        "emit_pulse_duration": 0.5,
        "inspection_time": 3.0,
        "cycle_delay": 2.0,
        "product_timeout": 15.0,
        "release_confirm_time": 2.0
    },
    "simulation": {
        "normal_temperature": 28.0,
        "temperature_noise": 0.5,
        "normal_vibration": 10.0,
        "vibration_noise": 2.0,
        "inspection_pass_rate": 0.95
    }
}

STATION2_CONFIG = {
    "name": "PCB Board Installation (Line 2)",
    "id": "station_2_b",
    "description": "Places PCB board (product lid) onto chassis using Pick & Place",
    "io": {
        "sensor_entry": {
            "address": 102,
            "type": "input",
            "description": "Entry diffuse sensor"
        },
        "sensor_station": {
            "address": 103,
            "type": "input",
            "description": "Station position sensor (at blade)"
        },
        "pp_moving_x": {
            "address": 104,
            "type": "input",
            "description": "P&P X axis in motion"
        },
        "pp_moving_z": {
            "address": 105,
            "type": "input",
            "description": "P&P Z axis in motion"
        },
        "pp_item_detected": {
            "address": 106,
            "type": "input",
            "description": "P&P gripper has item"
        },
        "belt": {
            "address": 104,
            "type": "output",
            "description": "Station 2 belt"
        },
        "stop_blade": {
            "address": 105,
            "type": "output",
            "description": "Stop blade 2"
        },
        "emitter": {
            "address": 106,
            "type": "output",
            "description": "Emitter 2 (Product Lid)"
        },
        "pp_move_x": {
            "address": 107,
            "type": "output",
            "description": "P&P X axis move"
        },
        "pp_move_z": {
            "address": 108,
            "type": "output",
            "description": "P&P Z axis move"
        },
        "pp_grab": {
            "address": 109,
            "type": "output",
            "description": "P&P gripper"
        }
    },
    "pick_and_place": {
        "x_pick_value": False,
        "x_place_value": True,
        "z_up_value": False,
        "z_down_value": True,
        "grab_close_value": True,
        "grab_open_value": False
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
        "product_timeout": 120.0
    },
    "simulation": {
        "normal_temperature": 30.0,
        "temperature_noise": 0.5,
        "normal_vibration": 8.0,
        "vibration_noise": 1.5,
        "pp_motor_power": 1.8,
        "belt_motor_power": 2.2
    }
}

STATION3_CONFIG = {
    "name": "Display Panel Mounting (Line 2)",
    "id": "station_3_b",
    "description": "Simulates LCD panel mounting using Aligners + timed stop",
    "io": {
        "pos_clamped": {
            "address": 107,
            "type": "input"
        },
        "pos_limit": {
            "address": 108,
            "type": "input"
        },
        "sensor": {
            "address": 109,
            "type": "input"
        },
        "belt": {
            "address": 111,
            "type": "output"
        },
        "pos_raise": {
            "address": 112,
            "type": "output"
        },
        "pos_clamp": {
            "address": 113,
            "type": "output"
        }
    },
    "timing": {
        "mount_time": 5.0,
        "exit_time": 1.5,
        "mechanical_timeout": 10.0,
        "product_timeout": 120.0,
        "debounce_time": 0.3,
        "settle_time": 0.3
    },
    "simulation": {
        "normal_temperature": 22.0,
        "temperature_noise": 0.3,
        "normal_vibration": 1.0,
        "vibration_noise": 0.2,
        "belt_motor_power": 0.8
    }
}

STATION6_CONFIG = {
    "name": "Quality Control & Testing (Line 2)",
    "id": "station_6_b",
    "description": "Vision sensor inspects assembled product",
    "io": {
        "sensor_entry": {
            "address": 110,
            "type": "input"
        },
        "vision_sensor": {
            "address": 10,
            "type": "input_register"
        },
        "belt_3b": {
            "address": 114,
            "type": "output"
        },
        "belt": {
            "address": 115,
            "type": "output"
        },
        "stop_blade": {
            "address": 116,
            "type": "output"
        },
        "light_green": {
            "address": 117,
            "type": "output"
        },
        "light_yellow": {
            "address": 118,
            "type": "output"
        },
        "light_red": {
            "address": 119,
            "type": "output"
        }
    },
    "timing": {
        "inspection_time": 3.0,
        "product_timeout": 60.0
    }
}

STATION7_CONFIG = {
    "name": "Sorting & Output (Line 2)",
    "id": "station_7_b",
    "description": "Routes products based on QC result",
    "io": {
        "sensor_entry": {
            "address": 111,
            "type": "input"
        },
        "belt": {
            "address": 121,
            "type": "output"
        },
        "sorter_turn": {
            "address": 122,
            "type": "output"
        },
        "sorter_belt_fwd": {
            "address": 123,
            "type": "output"
        },
        "sorter_belt_rev": {
            "address": 124,
            "type": "output"
        },
        "light_green": {
            "address": 125,
            "type": "output"
        },
        "light_red": {
            "address": 126,
            "type": "output"
        }
    },
    "timing": {
        "sort_delay": 2.0,
        "product_timeout": 30.0
    }
}

MACHINING_A_CONFIG = {
    "name": "Machining Center A \u2014 Blue Base Producer (Line 2)",
    "station_id": "machining_a_line2",
    "produce_lids": False,
    "machining_time": 3.0,
    "io": {
        "is_busy": {
            "address": 124,
            "type": "input"
        },
        "has_error": {
            "address": 125,
            "type": "input"
        },
        "opened": {
            "address": 126,
            "type": "input"
        },
        "exit_sensor": {
            "address": 127,
            "type": "input"
        },
        "emitter": {
            "address": 140,
            "type": "output"
        },
        "produce_lids": {
            "address": 141,
            "type": "output"
        },
        "start": {
            "address": 142,
            "type": "output"
        },
        "stop": {
            "address": 143,
            "type": "output"
        },
        "reset": {
            "address": 144,
            "type": "output"
        },
        "exit_belt": {
            "address": 145,
            "type": "output"
        }
    },
    "registers": {
        "progress": 11
    },
    "timing": {
        "emitter_pulse": 0.5,
        "load_timeout": 30.0,
        "machining_timeout": 30.0,
        "exit_timeout": 5.0,
        "settle_time": 0.5,
        "reset_pulse": 1.0
    },
    "simulation": {
        "normal_temperature": 25.0,
        "temperature_noise": 0.4,
        "normal_vibration": 1.5,
        "vibration_noise": 0.3,
        "cnc_motor_power": 1.2
    }
}

MACHINING_B_CONFIG = {
    "name": "Machining Center B \u2014 Green Lid Producer (Line 2)",
    "station_id": "machining_b_line2",
    "produce_lids": True,
    "machining_time": 6.0,
    "io": {
        "is_busy": {
            "address": 128,
            "type": "input"
        },
        "has_error": {
            "address": 129,
            "type": "input"
        },
        "opened": {
            "address": 130,
            "type": "input"
        },
        "exit_sensor": {
            "address": 131,
            "type": "input"
        },
        "emitter": {
            "address": 146,
            "type": "output"
        },
        "produce_lids": {
            "address": 147,
            "type": "output"
        },
        "start": {
            "address": 148,
            "type": "output"
        },
        "stop": {
            "address": 149,
            "type": "output"
        },
        "reset": {
            "address": 150,
            "type": "output"
        }
    },
    "registers": {
        "progress": 12
    },
    "timing": {
        "emitter_pulse": 0.5,
        "load_timeout": 30.0,
        "machining_timeout": 45.0,
        "exit_timeout": 10.0,
        "settle_time": 0.5,
        "reset_pulse": 1.0
    },
    "simulation": {
        "normal_temperature": 25.0,
        "temperature_noise": 0.4,
        "normal_vibration": 1.5,
        "vibration_noise": 0.3,
        "cnc_motor_power": 1.5
    }
}
