"""
Belt / Conveyor Dynamics Model.

Models conveyor belt behavior including:
  - Speed response (1st-order transfer function)
  - Slip probability as function of tension and fault severity
  - Product transit time
  - Brownout (power fault) downtime estimation

Derived from the fault effects in FAULT_CATALOG:
  belt_slip: stutter prob = severity * 0.08, on/off = 0.15/0.10s
  power:     brownout prob = severity * 0.06, duration = 0.3-0.8s

Transfer function for belt speed response:
  G(s) = K_belt / (τ_belt * s + 1)
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
from scipy.signal import lti, step

from simulation.models.base_model import (
    BaseModel,
    ComparisonResult,
    SimulationResult,
    TimeSeriesData,
)
from simulation.station_params import BELT_PARAMS, get_station_type


class BeltModel(BaseModel):
    """
    Conveyor belt dynamics model.

    Predicts:
      - Effective belt speed accounting for slip and brownouts
      - Product transit time through the station
      - Expected downtime per product cycle
      - Throughput impact
    """

    model_name = "belt_dynamics"

    def _get_params(self, station_id: str) -> dict:
        stype = get_station_type(station_id)
        return BELT_PARAMS.get(stype, BELT_PARAMS["station1"])

    def _effective_speed(
        self,
        nominal_speed: float,
        speed_cmd_pct: float,
        tension_pct: float,
        slip_severity: int,
        power_severity: int,
    ) -> dict:
        """
        Compute effective belt speed considering slip and brownouts.

        Returns dict with effective_speed, slip_prob, brownout_prob,
        expected_downtime_per_cycle.
        """
        # Command speed
        v_cmd = nominal_speed * (speed_cmd_pct / 100.0)

        # Slip reduces effective speed
        # Tension reduces slip: high tension → less slip
        tension_factor = max(0.1, tension_pct / 100.0)
        slip_prob = slip_severity * 0.08 / tension_factor if slip_severity > 0 else 0.0
        slip_prob = min(slip_prob, 0.95)  # cap at 95%

        # Brownout causes periodic belt OFF
        brownout_prob = power_severity * 0.06 if power_severity > 0 else 0.0
        brownout_prob = min(brownout_prob, 0.60)

        # Average brownout duration
        avg_brownout_duration = 0.55  # midpoint of (0.3, 0.8)

        # Effective speed = commanded speed × (1 - fraction of time lost)
        # Time lost to slip: each slip event = ~0.25s out of ~2s cycle → slip_prob * 0.125 duty
        slip_duty = slip_prob * 0.125
        # Time lost to brownout: brownout_prob per activation × avg duration / cycle_time
        brownout_duty = brownout_prob * avg_brownout_duration / 2.0

        effective_fraction = max(0.05, 1.0 - slip_duty - brownout_duty)
        v_effective = v_cmd * effective_fraction

        return {
            "v_commanded": round(v_cmd, 4),
            "v_effective": round(v_effective, 4),
            "effective_fraction": round(effective_fraction, 3),
            "slip_probability": round(slip_prob, 3),
            "brownout_probability": round(brownout_prob, 3),
            "expected_downtime_per_cycle_s": round(
                (slip_duty + brownout_duty) * 2.0, 3  # 2s nominal cycle
            ),
        }

    def _run_scenario(
        self,
        station_id: str,
        params: dict,
        speed_cmd_pct: float,
        tension_pct: float,
        slip_severity: int,
        power_severity: int,
        duration_s: float,
        scenario_label: str,
    ) -> SimulationResult:
        """Run one belt dynamics scenario."""
        nominal = params["nominal_speed_mps"]
        tau = params["time_constant_s"]
        belt_len = params["belt_length_m"]

        # Speed dynamics transfer function
        eff = self._effective_speed(
            nominal, speed_cmd_pct, tension_pct, slip_severity, power_severity
        )
        v_eff = eff["v_effective"]

        # Transfer function: G(s) = v_eff / (τs + 1)
        sys_tf = lti([v_eff], [tau, 1.0])
        t_eval = np.linspace(0, min(duration_s, 10.0), 200)
        t_out, y_out = step(sys_tf, T=t_eval)

        # Transit time
        transit_time = belt_len / v_eff if v_eff > 0.01 else float("inf")

        # Products per minute (simplified)
        cycle_time_with_faults = transit_time + eff["expected_downtime_per_cycle_s"]
        products_per_min = 60.0 / cycle_time_with_faults if cycle_time_with_faults > 0 else 0.0

        ts_speed = TimeSeriesData(
            name="belt_speed",
            unit="m/s",
            times=t_out,
            values=y_out,
            steady_state=float(v_eff),
        )

        kpis = {
            "v_commanded_mps": eff["v_commanded"],
            "v_effective_mps": eff["v_effective"],
            "effective_fraction": eff["effective_fraction"],
            "slip_probability": eff["slip_probability"],
            "brownout_probability": eff["brownout_probability"],
            "transit_time_s": round(transit_time, 2),
            "expected_downtime_per_cycle_s": eff["expected_downtime_per_cycle_s"],
            "products_per_min": round(products_per_min, 2),
            "transfer_function": {"K": round(v_eff, 4), "tau": round(tau, 2)},
            "speed_cmd_pct": speed_cmd_pct,
            "tension_pct": tension_pct,
            "slip_severity": slip_severity,
            "power_severity": power_severity,
        }

        warnings = []
        if eff["effective_fraction"] < 0.5:
            warnings.append(
                f"Belt efficiency critically low at {eff['effective_fraction']*100:.0f}%"
            )
        if eff["slip_probability"] > 0.3:
            warnings.append(
                f"High slip probability: {eff['slip_probability']*100:.0f}%"
            )
        if transit_time > 30:
            warnings.append(f"Transit time dangerously high: {transit_time:.1f}s")

        return SimulationResult(
            model_name=self.model_name,
            station_id=station_id,
            scenario=scenario_label,
            duration_s=duration_s,
            time_series=[ts_speed],
            kpis=kpis,
            warnings=warnings,
        )

    def simulate(
        self,
        station_id: str,
        current_state: Dict[str, Any],
        proposed_params: Dict[str, Any],
        duration_s: float = 300.0,
    ) -> ComparisonResult:
        """
        Run before/after belt simulation.

        current_state should contain:
            speed_cmd_pct: belt speed command (0-100%)
            tension_pct: belt tension (0-100%)
            slip_severity: belt_slip fault severity (0-5)
            power_severity: power fault severity (0-5)

        proposed_params may contain:
            belt_tension: new tension %
            line_speed_multiplier: speed multiplier (0.5-1.0)
            clear_fault: if True, severities drop to 0
        """
        params = self._get_params(station_id)

        speed_now = current_state.get("speed_cmd_pct", 100.0)
        tension_now = current_state.get("tension_pct", 70.0)
        slip_sev = current_state.get("slip_severity", 0)
        power_sev = current_state.get("power_severity", 0)

        before = self._run_scenario(
            station_id, params, speed_now, tension_now,
            slip_sev, power_sev, duration_s, "before"
        )

        # Apply proposed changes
        speed_after = speed_now
        if "speed_factor" in proposed_params:
            speed_after = speed_now * proposed_params["speed_factor"]
        elif "line_speed_multiplier" in proposed_params:
            speed_after = speed_now * proposed_params["line_speed_multiplier"]

        tension_after = proposed_params.get("target_belt_speed", proposed_params.get("belt_tension", tension_now))
        clear = proposed_params.get("clear_fault", False)
        slip_after = 0 if clear else slip_sev
        power_after = 0 if clear else power_sev

        after = self._run_scenario(
            station_id, params, speed_after, tension_after,
            slip_after, power_after, duration_s, "after"
        )

        # Deltas
        deltas = {
            "effective_speed_delta_mps": round(
                after.kpis["v_effective_mps"] - before.kpis["v_effective_mps"], 4
            ),
            "throughput_delta_ppm": round(
                after.kpis["products_per_min"] - before.kpis["products_per_min"], 2
            ),
            "efficiency_delta_pct": round(
                (after.kpis["effective_fraction"] - before.kpis["effective_fraction"]) * 100, 1
            ),
        }

        # GO/NO_GO
        eff_after = after.kpis["effective_fraction"]
        eff_before = before.kpis["effective_fraction"]
        ppm_after = after.kpis["products_per_min"]

        if eff_after > eff_before and eff_after > 0.6:
            go_no_go = "GO"
            confidence = min(90.0, 50.0 + (eff_after - eff_before) * 200)
            reasoning = (
                f"Belt efficiency improves from {eff_before*100:.0f}% to "
                f"{eff_after*100:.0f}%. Throughput: {ppm_after:.1f}/min."
            )
        elif eff_after >= eff_before:
            go_no_go = "GO"
            confidence = 55.0
            reasoning = f"Belt efficiency stable at {eff_after*100:.0f}%. No degradation."
        elif eff_after > 0.5:
            go_no_go = "GO"
            confidence = 45.0
            reasoning = (
                f"Belt efficiency drops slightly to {eff_after*100:.0f}% but remains acceptable."
            )
        else:
            go_no_go = "NO_GO"
            confidence = 80.0
            reasoning = (
                f"Belt efficiency too low at {eff_after*100:.0f}%. "
                f"Risk of production stall."
            )

        return ComparisonResult(
            before=before,
            after=after,
            deltas=deltas,
            go_no_go=go_no_go,
            confidence=confidence,
            reasoning=reasoning,
        )
