"""
Smart PLC Assistant — Configuration Settings

Central configuration for MQTT, Modbus, LLM, database, and sensor thresholds.
All values can be overridden via environment variables or .env file.
"""

import os
from dotenv import load_dotenv

load_dotenv()


# =============================================================================
# MQTT CONFIGURATION
# =============================================================================
MQTT_BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "localhost")
MQTT_BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", 1883))
MQTT_USERNAME = os.getenv("MQTT_USERNAME", None)
MQTT_PASSWORD = os.getenv("MQTT_PASSWORD", None)
MQTT_CLIENT_ID_PREFIX = "smart_plc"


# =============================================================================
# FACTORY I/O (MODBUS) CONFIGURATION
# =============================================================================
FACTORY_MODBUS_HOST = os.getenv("FACTORY_MODBUS_HOST", "127.0.0.1")
FACTORY_MODBUS_PORT = int(os.getenv("FACTORY_MODBUS_PORT", 502))
FACTORY_MODBUS_SLAVE_ID = int(os.getenv("FACTORY_MODBUS_SLAVE_ID", 1))
FACTORY_SCALE_FACTOR = float(os.getenv("FACTORY_SCALE_FACTOR", 100.0))


# =============================================================================
# LLM CONFIGURATION
# =============================================================================

# API Keys — set whichever you have in .env
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
AGENT_ROUTER_API_KEY = os.getenv("AGENT_ROUTER_API_KEY")

LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", 0.3))

# Per-agent model overrides (optional — set in .env to customize)
# Format: PROVIDER:MODEL  e.g. "google:gemini-2.5-pro", "agentrouter:claude-opus-4-6", "groq:llama-3.3-70b-versatile"
DIAGNOSTIC_MODEL = os.getenv("DIAGNOSTIC_MODEL", "auto")
REPAIR_MODEL = os.getenv("REPAIR_MODEL", "auto")
VALIDATOR_MODEL = os.getenv("VALIDATOR_MODEL", "auto")
SIMULATION_MODEL = os.getenv("SIMULATION_MODEL", "auto")
EXECUTION_MODEL = os.getenv("EXECUTION_MODEL", "auto")


# =============================================================================
# DATABASE CONFIGURATION
# =============================================================================
DATABASE_PATH = os.path.join("data", "plc_data.db")
CHROMA_DB_PATH = os.path.join("data", "chroma_db")


# =============================================================================
# VIRTUAL FACTORY CONFIGURATION
# =============================================================================
FACTORY_UPDATE_INTERVAL = 1.0
SENSOR_NOISE_LEVEL = 0.02


# =============================================================================
# HUMAN-IN-THE-LOOP CONFIGURATION
# =============================================================================
REQUIRE_HUMAN_APPROVAL = True
APPROVAL_TIMEOUT = 300


# =============================================================================
# SENSOR THRESHOLDS
# =============================================================================
THRESHOLDS = {
    "motor_temperature": {
        "normal_min": 25.0,
        "normal_max": 55.0,
        "warning": 55.0,
        "critical": 70.0,
        "max_allowed": 75.0,
        "unit": "°C",
    },
    "motor_speed": {
        "normal_min": 1400,
        "normal_max": 1500,
        "warning_low": 1300,
        "critical_low": 1200,
        "max_allowed": 1500,
        "unit": "RPM",
    },
    "vibration": {
        "normal_max": 30.0,
        "warning": 45.0,
        "critical": 60.0,
        "unit": "mm/s",
    },
    "cycle_time": {
        "normal_min": 4.0,
        "normal_max": 6.0,
        "warning": 8.0,
        "critical": 10.0,
        "unit": "seconds",
    },
    "power_consumption": {
        "normal_max": 3.0,
        "warning": 4.0,
        "critical": 5.0,
        "unit": "kW",
    },
}


# =============================================================================
# MQTT TOPIC DEFINITIONS
# =============================================================================

# ── Factory - Sensor Data (Published by Virtual Factory) ──
TOPIC_SENSOR_TEMPERATURE = "factory/sensors/motor/temperature"
TOPIC_SENSOR_SPEED = "factory/sensors/motor/speed"
TOPIC_SENSOR_VIBRATION = "factory/sensors/motor/vibration"
TOPIC_SENSOR_PROXIMITY = "factory/sensors/proximity/status"
TOPIC_SENSOR_COLOR = "factory/sensors/color/reading"
TOPIC_SENSOR_POWER = "factory/sensors/system/power"
TOPIC_SENSOR_CYCLE_TIME = "factory/sensors/system/cycle_time"

# ── Factory - Actuator States ──
TOPIC_ACTUATOR_MOTOR = "factory/actuators/motor/status"
TOPIC_ACTUATOR_PUSHER = "factory/actuators/pusher/status"

# ── Factory - Commands (ONLY sent after human approval) ──
TOPIC_CMD_MOTOR_SPEED = "factory/commands/motor/set_speed"
TOPIC_CMD_MOTOR_STOP = "factory/commands/motor/stop"
TOPIC_CMD_PUSHER = "factory/commands/pusher/activate"

# ── Factory - Fault Injection (Testing) ──
TOPIC_FAULT_INJECT = "factory/faults/inject"

# ── Agents - Monitor ──
TOPIC_MONITOR_ALERT = "agents/monitor/alert"
TOPIC_MONITOR_STATUS = "agents/monitor/status"

# ── Agents - Diagnostic ──
TOPIC_DIAGNOSTIC_REPORT = "agents/diagnostic/report"
TOPIC_DIAGNOSTIC_STATUS = "agents/diagnostic/status"

# ── Agents - Repair ──
TOPIC_REPAIR_PROPOSAL = "agents/repair/proposal"
TOPIC_REPAIR_STATUS = "agents/repair/status"

# ── Agents - Validation ──
TOPIC_VALIDATION_RESULT = "agents/validation/result"
TOPIC_VALIDATION_STATUS = "agents/validation/status"

# ── Agents - Simulation ──
TOPIC_SIMULATION_RESULT = "agents/simulation/result"
TOPIC_SIMULATION_PROGRESS = "agents/simulation/progress"
TOPIC_SIMULATION_STATUS = "agents/simulation/status"

# ── Agents - Optimization ──
TOPIC_OPTIMIZER_RECOMMENDATION = "agents/optimizer/recommendation"
TOPIC_OPTIMIZER_STATUS = "agents/optimizer/status"

# ── Agents - Supervisor ──
TOPIC_SUPERVISOR_DECISION = "agents/supervisor/decision"
TOPIC_SUPERVISOR_PIPELINE = "agents/supervisor/pipeline_status"
TOPIC_SUPERVISOR_STATUS = "agents/supervisor/status"

# ── Human-in-the-Loop ──
TOPIC_HUMAN_REQUEST = "human/requests/pending"
TOPIC_HUMAN_APPROVAL = "human/approval/decision"
TOPIC_HUMAN_MODIFICATION = "human/approval/modification"
TOPIC_HUMAN_NOTIFICATION = "human/notifications/urgent"

# ── System ──
TOPIC_SYSTEM_HEALTH = "system/status/health"
TOPIC_SYSTEM_MQTT = "system/status/mqtt"
TOPIC_SYSTEM_LLM = "system/status/llm_api"
TOPIC_SYSTEM_AUDIT = "system/logs/audit"

# ── Wildcard Subscriptions ──
ALL_SENSOR_TOPICS = "factory/sensors/#"
ALL_COMMAND_TOPICS = "factory/commands/#"
ALL_AGENT_TOPICS = "agents/#"
ALL_HUMAN_TOPICS = "human/#"
ALL_SYSTEM_TOPICS = "system/#"
ALL_TOPICS = "#"