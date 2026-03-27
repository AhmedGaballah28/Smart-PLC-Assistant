"""
MQTT Topic Definitions
All MQTT topics used in the system.
"""

# =============================================================================
# FACTORY - Sensor Data (Published by Virtual Factory)
# =============================================================================
TOPIC_SENSOR_TEMPERATURE = "factory/sensors/motor/temperature"
TOPIC_SENSOR_SPEED = "factory/sensors/motor/speed"
TOPIC_SENSOR_VIBRATION = "factory/sensors/motor/vibration"
TOPIC_SENSOR_PROXIMITY = "factory/sensors/proximity/status"
TOPIC_SENSOR_COLOR = "factory/sensors/color/reading"
TOPIC_SENSOR_POWER = "factory/sensors/system/power"
TOPIC_SENSOR_CYCLE_TIME = "factory/sensors/system/cycle_time"

# =============================================================================
# FACTORY - Actuator States
# =============================================================================
TOPIC_ACTUATOR_MOTOR = "factory/actuators/motor/status"
TOPIC_ACTUATOR_PUSHER = "factory/actuators/pusher/status"

# =============================================================================
# FACTORY - Commands (ONLY sent after human approval)
# =============================================================================
TOPIC_CMD_MOTOR_SPEED = "factory/commands/motor/set_speed"
TOPIC_CMD_MOTOR_STOP = "factory/commands/motor/stop"
TOPIC_CMD_PUSHER = "factory/commands/pusher/activate"

# =============================================================================
# FACTORY - Fault Injection (Testing)
# =============================================================================
TOPIC_FAULT_INJECT = "factory/faults/inject"

# =============================================================================
# AGENTS - Monitor
# =============================================================================
TOPIC_MONITOR_ALERT = "agents/monitor/alert"
TOPIC_MONITOR_STATUS = "agents/monitor/status"

# =============================================================================
# AGENTS - Diagnostic
# =============================================================================
TOPIC_DIAGNOSTIC_REPORT = "agents/diagnostic/report"
TOPIC_DIAGNOSTIC_STATUS = "agents/diagnostic/status"

# =============================================================================
# AGENTS - Repair
# =============================================================================
TOPIC_REPAIR_PROPOSAL = "agents/repair/proposal"
TOPIC_REPAIR_STATUS = "agents/repair/status"

# =============================================================================
# AGENTS - Validation
# =============================================================================
TOPIC_VALIDATION_RESULT = "agents/validation/result"
TOPIC_VALIDATION_STATUS = "agents/validation/status"

# =============================================================================
# AGENTS - Simulation
# =============================================================================
TOPIC_SIMULATION_RESULT = "agents/simulation/result"
TOPIC_SIMULATION_PROGRESS = "agents/simulation/progress"
TOPIC_SIMULATION_STATUS = "agents/simulation/status"

# =============================================================================
# AGENTS - Optimization
# =============================================================================
TOPIC_OPTIMIZER_RECOMMENDATION = "agents/optimizer/recommendation"
TOPIC_OPTIMIZER_STATUS = "agents/optimizer/status"

# =============================================================================
# AGENTS - Supervisor
# =============================================================================
TOPIC_SUPERVISOR_DECISION = "agents/supervisor/decision"
TOPIC_SUPERVISOR_PIPELINE = "agents/supervisor/pipeline_status"
TOPIC_SUPERVISOR_STATUS = "agents/supervisor/status"

# =============================================================================
# HUMAN-IN-THE-LOOP
# =============================================================================
TOPIC_HUMAN_REQUEST = "human/requests/pending"
TOPIC_HUMAN_APPROVAL = "human/approval/decision"
TOPIC_HUMAN_MODIFICATION = "human/approval/modification"
TOPIC_HUMAN_NOTIFICATION = "human/notifications/urgent"

# =============================================================================
# SYSTEM
# =============================================================================
TOPIC_SYSTEM_HEALTH = "system/status/health"
TOPIC_SYSTEM_MQTT = "system/status/mqtt"
TOPIC_SYSTEM_LLM = "system/status/llm_api"
TOPIC_SYSTEM_AUDIT = "system/logs/audit"

# =============================================================================
# WILDCARD SUBSCRIPTIONS
# =============================================================================
ALL_SENSOR_TOPICS = "factory/sensors/#"
ALL_COMMAND_TOPICS = "factory/commands/#"
ALL_AGENT_TOPICS = "agents/#"
ALL_HUMAN_TOPICS = "human/#"
ALL_SYSTEM_TOPICS = "system/#"
ALL_TOPICS = "#"