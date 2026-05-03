import sys
from pathlib import Path

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import uuid
from core.repository import DbRepository

def run_test():
    print("1. Checking DB health...")
    health = DbRepository.get_health()
    print(f"Health: {health}")
    assert health["ok"], "Health check failed!"

    corr_id = "TEST-CORR-" + uuid.uuid4().hex[:8]

    print(f"\n2. Creating incident {corr_id}...")
    inc_res = DbRepository.create_incident(
        correlation_id=corr_id,
        line_id="line_2",
        station_id="station_3",
        severity="critical",
        status="NEW_ALERT",
        summary="Testing MCP Repository Layer"
    )
    print(f"Incident Result: {inc_res}")
    assert inc_res["ok"], "Creating incident failed!"

    print("\n3. Saving monitor alert...")
    alert_res = DbRepository.save_monitor_alert(
        event_id="EV-ALERT-" + uuid.uuid4().hex[:8],
        correlation_id=corr_id,
        alert_type="SENSOR_FAULT",
        message="Test sensor faulted",
        severity="critical",
        line_id="line_2",
        station_id="station_3"
    )
    print(f"Alert Result: {alert_res}")

    print("\n4. Appending another event...")
    ev_res = DbRepository.append_incident_event(
        event_id="EV-EVENT-" + uuid.uuid4().hex[:8],
        correlation_id=corr_id,
        stage="diagnostic",
        event_type="test_event",
        source_agent="test_script",
        severity="info"
    )
    print(f"Event Result: {ev_res}")

    print("\n5. Fetching incident timeline...")
    timeline = DbRepository.get_incident_timeline(corr_id)
    print(f"Timeline Result: {timeline}")
    assert timeline["ok"], "Fetching timeline failed!"
    assert timeline["event_count"] >= 2, "Timeline should have at least 2 events"

    print("\nSUCCESS: All Repository integration tests passed!")

if __name__ == "__main__":
    run_test()
