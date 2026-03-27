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
# LLM CONFIGURATION (GROQ - FREE)
# =============================================================================
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", 0.3))

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
        "unit": "°C"
    },
    "motor_speed": {
        "normal_min": 1400,
        "normal_max": 1500,
        "warning_low": 1300,
        "critical_low": 1200,
        "max_allowed": 1500,
        "unit": "RPM"
    },
    "vibration": {
        "normal_max": 30.0,
        "warning": 45.0,
        "critical": 60.0,
        "unit": "mm/s"
    },
    "cycle_time": {
        "normal_min": 4.0,
        "normal_max": 6.0,
        "warning": 8.0,
        "critical": 10.0,
        "unit": "seconds"
    },
    "power_consumption": {
        "normal_max": 3.0,
        "warning": 4.0,
        "critical": 5.0,
        "unit": "kW"
    }
}