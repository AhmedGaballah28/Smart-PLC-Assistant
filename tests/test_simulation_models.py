"""
Tests for the simulation engine — thermal, belt, production models.

Run with: pytest tests/test_simulation_models.py -v
"""

import pytest
import json
import sys
import os

# Ensure project root is on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from simulation.models.thermal_model import ThermalModel
from simulation.models.belt_model import BeltModel
from simulation.models.production_model import ProductionLineModel
from simulation.engine import run_simulation


# ═══════════════════════════════════════════════════════════
# THERMAL MODEL TESTS
# ═══════════════════════════════════════════════════════════

class TestThermalModel:
    """Tests for ThermalModel (1st-order ODE + transfer function)."""

    def setup_method(self):
        self.model = ThermalModel()

    def test_no_fault_steady_state(self):
        """No fault → temperature should stay near target (45°C)."""
        state = {"temperature": 45.0, "fault_severity": 0, "speed_factor": 1.0, "fan_speed": 50.0}
        params = {}
        result = self.model.simulate("stn1", state, params, duration_s=300)
        assert result.go_no_go == "GO"
        assert result.after.kpis["T_steady_state"] < 70  # below critical

    def test_overheat_fault_before_is_hot(self):
        """Severity 3 overheat → before scenario should show high temp."""
        state = {"temperature": 68.0, "fault_severity": 3, "speed_factor": 1.0, "fan_speed": 50.0}
        params = {}
        result = self.model.simulate("stn1", state, params, duration_s=300)
        assert result.before.kpis["T_steady_state"] > 45  # above normal target

    def test_speed_reduction_cools_down(self):
        """Reducing speed + clearing fault should lower temperature."""
        state = {"temperature": 68.0, "fault_severity": 3, "speed_factor": 1.0, "fan_speed": 50.0}
        params = {"speed_factor": 0.6, "clear_fault": True, "fan_speed": 80.0}
        result = self.model.simulate("stn1", state, params, duration_s=300)

        before_T = result.before.kpis["T_steady_state"]
        after_T = result.after.kpis["T_steady_state"]
        assert after_T < before_T, f"After ({after_T}) should be cooler than Before ({before_T})"
        assert result.go_no_go == "GO"

    def test_high_speed_overheats(self):
        """Speed factor 2.0 with existing fault → should stay hot."""
        state = {"temperature": 70.0, "fault_severity": 4, "speed_factor": 2.0, "fan_speed": 30.0}
        params = {"speed_factor": 2.0}
        result = self.model.simulate("stn1", state, params, duration_s=300)
        assert result.after.kpis["T_steady_state"] > 60

    def test_transfer_function_present(self):
        """Transfer function G(s) = K/(tau*s + 1) should be computed."""
        state = {"temperature": 50.0, "fault_severity": 2, "speed_factor": 1.0, "fan_speed": 50.0}
        params = {"clear_fault": True}
        result = self.model.simulate("stn1", state, params, duration_s=300)
        tf = result.after.kpis["transfer_function"]
        assert "K" in tf
        assert "tau" in tf
        assert tf["tau"] > 0

    def test_machining_station(self):
        """Thermal model should work for machining centers too."""
        state = {"temperature": 55.0, "fault_severity": 2, "speed_factor": 1.0, "fan_speed": 50.0}
        params = {"clear_fault": True}
        result = self.model.simulate("mc_a", state, params, duration_s=300)
        assert result.go_no_go in ("GO", "NO_GO", "INCONCLUSIVE")
        assert result.confidence > 0


# ═══════════════════════════════════════════════════════════
# BELT MODEL TESTS
# ═══════════════════════════════════════════════════════════

class TestBeltModel:
    """Tests for BeltModel (speed dynamics + slip probability)."""

    def setup_method(self):
        self.model = BeltModel()

    def test_no_fault_full_speed(self):
        """No fault → belt should be at full effective speed."""
        state = {"speed_cmd_pct": 100, "tension_pct": 70, "slip_severity": 0, "power_severity": 0}
        params = {}
        result = self.model.simulate("stn1", state, params, duration_s=60)
        assert result.go_no_go == "GO"
        kpis = result.after.kpis
        assert kpis["effective_fraction"] > 0.9

    def test_slip_reduces_speed(self):
        """Belt slip severity 3 → effective speed should drop."""
        state = {"speed_cmd_pct": 100, "tension_pct": 50, "slip_severity": 3, "power_severity": 0}
        params = {}
        result = self.model.simulate("stn1", state, params, duration_s=60)
        kpis = result.before.kpis
        assert kpis["effective_fraction"] < 1.0
        assert kpis["slip_probability"] > 0

    def test_clear_fault_restores_speed(self):
        """Clearing slip fault should restore belt speed."""
        state = {"speed_cmd_pct": 100, "tension_pct": 50, "slip_severity": 3, "power_severity": 0}
        params = {"clear_fault": True, "tension_pct": 80}
        result = self.model.simulate("stn1", state, params, duration_s=60)

        before_eff = result.before.kpis["effective_fraction"]
        after_eff = result.after.kpis["effective_fraction"]
        assert after_eff > before_eff

    def test_power_brownout_probability(self):
        """Power severity increases brownout probability."""
        state = {"speed_cmd_pct": 100, "tension_pct": 70, "slip_severity": 0, "power_severity": 4}
        params = {}
        result = self.model.simulate("stn1", state, params, duration_s=60)
        assert result.before.kpis["brownout_probability"] > 0

    def test_throughput_calculation(self):
        """Products per minute should be positive for running belt."""
        state = {"speed_cmd_pct": 100, "tension_pct": 70, "slip_severity": 0, "power_severity": 0}
        params = {}
        result = self.model.simulate("stn1", state, params, duration_s=60)
        assert result.after.kpis["products_per_min"] > 0


# ═══════════════════════════════════════════════════════════
# PRODUCTION MODEL TESTS
# ═══════════════════════════════════════════════════════════

class TestProductionModel:
    """Tests for ProductionLineModel (throughput + bottleneck analysis)."""

    def setup_method(self):
        self.model = ProductionLineModel()

    def test_no_faults_high_throughput(self):
        """No faults → throughput should be near nominal."""
        state = {"faults": {}, "line_speed_multiplier": 1.0}
        params = {}
        result = self.model.simulate("stn1", state, params, duration_s=300)
        assert result.go_no_go == "GO"
        kpis = result.after.kpis
        assert kpis["effective_throughput_ppm"] > 3.0  # decent throughput

    def test_overheat_reduces_throughput(self):
        """Overheat on stn1 → throughput should drop."""
        state = {"faults": {"stn1": {"overheat": 3}}, "line_speed_multiplier": 1.0}
        params = {}
        result = self.model.simulate("stn1", state, params, duration_s=300)

        before_tpm = result.before.kpis["effective_throughput_ppm"]
        # Before has the fault, so throughput is reduced
        state_clear = {"faults": {}, "line_speed_multiplier": 1.0}
        result_clear = self.model.simulate("stn1", state_clear, {}, duration_s=300)
        clean_tpm = result_clear.after.kpis["effective_throughput_ppm"]
        assert clean_tpm >= before_tpm

    def test_bottleneck_identified(self):
        """Model should identify the bottleneck station."""
        state = {"faults": {"stn1": {"overheat": 4}}, "line_speed_multiplier": 1.0}
        params = {}
        result = self.model.simulate("stn1", state, params, duration_s=300)
        kpis = result.before.kpis
        assert "bottleneck_station" in kpis

    def test_clearing_fault_improves_pass_rate(self):
        """Clearing a fault should improve pass rate."""
        state = {"faults": {"stn2": {"gripper_failure": 3}}, "line_speed_multiplier": 1.0}
        params = {"clear_fault": True}
        result = self.model.simulate("stn2", state, params, duration_s=300)

        before_pr = result.before.kpis["pass_rate"]
        after_pr = result.after.kpis["pass_rate"]
        assert after_pr >= before_pr


# ═══════════════════════════════════════════════════════════
# ENGINE INTEGRATION TESTS
# ═══════════════════════════════════════════════════════════

class TestSimulationEngine:
    """Tests for the orchestrator engine."""

    def test_overheat_scenario(self):
        """Engine should select thermal + production models for overheat."""
        result = run_simulation(
            station_id="stn1",
            sensor_data={
                "fault_type": "overheat",
                "temperature": 68.0,
                "severity_level": 3,
            },
            proposed_params={
                "speed_factor": 0.7,
                "fan_speed": 80,
                "clear_fault": True,
            },
            duration_s=300,
        )
        assert result["go_no_go"] in ("GO", "NO_GO", "INCONCLUSIVE")
        assert result["confidence"] > 0
        assert "thermal_dynamics" in result["models"]
        assert "production_line" in result["models"]
        assert result["source"] == "simulation_engine"

    def test_belt_slip_scenario(self):
        """Engine should select belt + production models for belt_slip."""
        result = run_simulation(
            station_id="stn1",
            sensor_data={
                "fault_type": "belt_slip",
                "severity_level": 2,
            },
            proposed_params={"clear_fault": True, "belt_tension": 80},
            duration_s=60,
        )
        assert result["go_no_go"] in ("GO", "NO_GO", "INCONCLUSIVE")
        assert "belt_dynamics" in result["models"]

    def test_power_fault_scenario(self):
        """Power fault → belt + production models."""
        result = run_simulation(
            station_id="mc_a",
            sensor_data={
                "fault_type": "power",
                "severity_level": 3,
            },
            proposed_params={"clear_fault": True},
            duration_s=120,
        )
        assert result["go_no_go"] in ("GO", "NO_GO", "INCONCLUSIVE")
        assert "belt_dynamics" in result["models"]

    def test_unknown_fault_defaults(self):
        """Unknown fault type should still produce a result."""
        result = run_simulation(
            station_id="stn1",
            sensor_data={"type": "unknown_issue"},
            proposed_params={},
            duration_s=60,
        )
        assert result["go_no_go"] in ("GO", "NO_GO", "INCONCLUSIVE")

    def test_result_has_deltas(self):
        """Result should include all delta fields."""
        result = run_simulation(
            station_id="stn1",
            sensor_data={"fault_type": "overheat", "severity_level": 3, "temperature": 65},
            proposed_params={"clear_fault": True, "speed_factor": 0.8},
            duration_s=300,
        )
        assert "predicted_cycle_time_delta" in result
        assert "predicted_throughput_delta" in result
        assert "predicted_fault_risk_delta" in result

    def test_json_serializable(self):
        """Engine output must be JSON-serializable (for LangChain tools)."""
        result = run_simulation(
            station_id="stn2",
            sensor_data={"fault_type": "gripper_failure", "severity_level": 2},
            proposed_params={"clear_fault": True},
            duration_s=120,
        )
        json_str = json.dumps(result)
        assert len(json_str) > 10
        parsed = json.loads(json_str)
        assert parsed["go_no_go"] == result["go_no_go"]


# ═══════════════════════════════════════════════════════════
# STATION PARAMS TESTS
# ═══════════════════════════════════════════════════════════

class TestStationParams:
    """Test the station_params module."""

    def test_get_station_type(self):
        from simulation.station_params import get_station_type
        assert get_station_type("stn1") == "station1"
        assert get_station_type("mc_a") == "machining"
        assert get_station_type("mc_b") == "machining"
        assert get_station_type("stn2") == "station2"
        assert get_station_type("stn3") == "station3"

    def test_thermal_params_exist(self):
        from simulation.station_params import THERMAL_PARAMS
        assert "station1" in THERMAL_PARAMS
        assert THERMAL_PARAMS["station1"]["T_ambient"] == 25.0

    def test_belt_params_exist(self):
        from simulation.station_params import BELT_PARAMS
        assert "station1" in BELT_PARAMS
        assert BELT_PARAMS["station1"]["belt_length_m"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
