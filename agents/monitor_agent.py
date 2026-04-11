"""
Monitor Agent
Subscribes to MQTT station status topics, checks sensor values against
thresholds, and publishes anomaly alerts for the Diagnostic Agent.
"""

import json
import logging
import threading
import time
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# ── Thresholds for each metric ──────────────────────────────────────────────
THRESHOLDS = {
    "temperature": {"warning": 50.0, "critical": 65.0, "unit": "°C"},
    "vibration":   {"warning": 30.0, "critical": 50.0, "unit": "mm/s"},
    "power_kw":    {"warning": 4.0,  "critical": 5.5,  "unit": "kW"},
}

STATION_NAMES = {
    "station_1": "Chassis Loading",
    "station_2": "PCB Installation",
    "station_3": "Display Panel",
    "station_4": "Wiring Connection",
    "station_5": "Back Cover Assembly",
    "station_6": "Quality Control",
    "station_7": "Sorting & Output",
}


class MonitorAgent:
    """
    Monitors all factory station telemetry via MQTT.

    Flow:
      1. Subscribes to factory/+/status and factory/+/+/status
      2. On each message, checks sensor values against thresholds
      3. If value exceeds warning/critical → publishes to agents/monitor/alert
      4. Alert includes: station, metric, value, threshold level, timestamp

    MQTT IN:  factory/+/status
    MQTT OUT: agents/monitor/alert
              agents/monitor/status
    """

    ALERT_COOLDOWN = 30.0  # Minimum seconds between same-type alerts per station

    def __init__(self, mqtt_client, alert_callback=None):
        self.mqtt = mqtt_client
        self.alert_callback = alert_callback  # Optional: fn(alert_dict) called on each alert
        self._running = False
        self._lock = threading.Lock()
        self._last_alert: Dict[str, float] = {}  # "{station}_{metric}" → timestamp
        self._alert_count = 0
        self._station_states: Dict[str, Dict] = {}

    def start(self):
        """Subscribe to all station status topics and begin monitoring."""
        self._running = True
        logger.info("🔍 Monitor Agent starting...")

        # Subscribe to both topic patterns used in the project
        for topic in ["factory/+/status", "factory/+/+/status"]:
            self.mqtt.subscribe(topic, self._on_status_message)

        # Publish agent-online status
        self._publish_status("online")
        logger.info("✅ Monitor Agent running — watching all stations")

    def stop(self):
        self._running = False
        self._publish_status("offline")
        logger.info("Monitor Agent stopped")

    # ─────────────────────────────────────────────────────────────────────────
    # MESSAGE HANDLER
    # ─────────────────────────────────────────────────────────────────────────

    def _on_status_message(self, topic: str, payload: Any):
        """Called for each station status publish."""
        if not self._running:
            return

        try:
            if isinstance(payload, str):
                data = json.loads(payload)
            elif isinstance(payload, dict):
                data = payload
            else:
                return

            station_id = data.get("station", self._extract_station(topic))
            if not station_id:
                return

            with self._lock:
                self._station_states[station_id] = data

            self._check_thresholds(station_id, data)
            self._check_emergency(station_id, data)

        except Exception as e:
            logger.debug(f"Monitor: error parsing message: {e}")

    def _extract_station(self, topic: str) -> str:
        """Pull station ID from topic like factory/station_1/status."""
        parts = topic.split("/")
        for p in parts:
            if p.startswith("station_") or p in STATION_NAMES:
                return p
        return ""

    # ─────────────────────────────────────────────────────────────────────────
    # THRESHOLD CHECKING
    # ─────────────────────────────────────────────────────────────────────────

    def _check_thresholds(self, station_id: str, data: dict):
        sensors = data.get("sensors", {})
        for metric, limits in THRESHOLDS.items():
            value = sensors.get(metric)
            if value is None:
                continue

            level = None
            if value >= limits["critical"]:
                level = "CRITICAL"
            elif value >= limits["warning"]:
                level = "WARNING"

            if level:
                self._maybe_emit_alert(
                    station_id=station_id,
                    alert_type="sensor_threshold",
                    level=level,
                    metric=metric,
                    value=value,
                    threshold=limits[level.lower()],
                    unit=limits["unit"],
                    data=data,
                )

    def _check_emergency(self, station_id: str, data: dict):
        if data.get("emergency_active"):
            reason = data.get("emergency_reason", "unknown")
            self._maybe_emit_alert(
                station_id=station_id,
                alert_type="emergency_stop",
                level="CRITICAL",
                metric="emergency",
                value=reason,
                threshold=None,
                unit="",
                data=data,
            )

        # Check active faults
        faults = data.get("faults", {})
        if faults.get("has_fault"):
            for fault in faults.get("active", []):
                self._maybe_emit_alert(
                    station_id=station_id,
                    alert_type="fault_active",
                    level="WARNING",
                    metric="fault",
                    value=fault,
                    threshold=None,
                    unit="",
                    data=data,
                )

    def _maybe_emit_alert(self, station_id: str, alert_type: str, level: str,
                          metric: str, value: Any, threshold: Any, unit: str,
                          data: dict):
        """Rate-limited alert emission."""
        key = f"{station_id}_{metric}"
        now = time.time()

        with self._lock:
            last = self._last_alert.get(key, 0)
            if now - last < self.ALERT_COOLDOWN:
                return
            self._last_alert[key] = now
            self._alert_count += 1

        alert = self._build_alert(
            station_id=station_id,
            alert_type=alert_type,
            level=level,
            metric=metric,
            value=value,
            threshold=threshold,
            unit=unit,
            station_state=data.get("state", "unknown"),
            faults_active=data.get("faults", {}).get("active", []),
            sensors=data.get("sensors", {}),
        )

        logger.warning(f"🚨 ALERT [{level}] {station_id}: {metric}={value}{unit}")
        self._publish_alert(alert)

        if self.alert_callback:
            try:
                self.alert_callback(alert)
            except Exception as e:
                logger.error(f"Monitor: alert_callback error: {e}")

    def _build_alert(self, station_id: str, alert_type: str, level: str,
                     metric: str, value: Any, threshold: Any, unit: str,
                     station_state: str, faults_active: list, sensors: dict) -> dict:
        return {
            "alert_id": f"ALT-{self._alert_count:04d}",
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "station_id": station_id,
            "station_name": STATION_NAMES.get(station_id, station_id),
            "alert_type": alert_type,
            "level": level,           # "WARNING" or "CRITICAL"
            "metric": metric,
            "value": value,
            "threshold": threshold,
            "unit": unit,
            "station_state": station_state,
            "faults_active": faults_active,
            "sensor_snapshot": sensors,
        }

    # ─────────────────────────────────────────────────────────────────────────
    # MQTT PUBLISHING
    # ─────────────────────────────────────────────────────────────────────────

    def _publish_alert(self, alert: dict):
        try:
            self.mqtt.publish("agents/monitor/alert", json.dumps(alert))
        except Exception as e:
            logger.error(f"Monitor: failed to publish alert: {e}")

    def _publish_status(self, status: str):
        try:
            self.mqtt.publish("agents/monitor/status", json.dumps({
                "agent": "monitor",
                "status": status,
                "alert_count": self._alert_count,
                "watched_stations": list(self._station_states.keys()),
                "timestamp": datetime.utcnow().isoformat() + "Z",
            }))
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # QUERY API (used by dashboard)
    # ─────────────────────────────────────────────────────────────────────────

    def get_station_state(self, station_id: str) -> Optional[Dict]:
        with self._lock:
            return self._station_states.get(station_id)

    def get_all_states(self) -> Dict[str, Dict]:
        with self._lock:
            return dict(self._station_states)

    def get_alert_count(self) -> int:
        return self._alert_count
