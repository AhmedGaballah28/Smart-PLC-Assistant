"""
Production Line Model — Line-level KPI prediction.

Models the full assembly line as a series of stations with:
  - Individual cycle times (affected by faults)
  - Bottleneck identification
  - Throughput calculation
  - Pass rate / reject rate estimation
  - Queue buildup prediction

The line throughput is limited by the slowest station (bottleneck):
    TH = 1 / max(T_i)

Where T_i = base_cycle × fault_multiplier for each station.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from simulation.models.base_model import (
    BaseModel,
    ComparisonResult,
    SimulationResult,
    TimeSeriesData,
)
from simulation.station_params import (
    CYCLE_TIME_PARAMS,
    FAULT_PROBABILITIES,
    get_station_type,
)

# Default line composition: ordered list of stations in the pipeline
DEFAULT_LINE_STATIONS = ["mc_a", "mc_b", "stn1", "stn2", "stn3", "stn6", "stn7"]


class ProductionLineModel(BaseModel):
    """
    Production line throughput and quality model.

    Predicts:
      - Per-station cycle times with fault multipliers
      - Bottleneck station identification
      - Line throughput (products/min)
      - Pass rate based on QC and sorting fault probabilities
      - Cumulative production over time
    """

    model_name = "production_line"

    def _station_cycle_time(self, station_id: str, faults: Dict[str, int]) -> float:
        """Compute cycle time for a station given active faults."""
        stype = get_station_type(station_id)
        ct_params = CYCLE_TIME_PARAMS.get(stype)
        if ct_params is None:
            return 5.0  # default

        base = ct_params["base_cycle_s"]
        multiplier = 1.0

        for fault_type, severity in faults.items():
            if severity <= 0:
                continue
            fault_mults = ct_params.get("fault_multipliers", {}).get(fault_type, {})
            if severity in fault_mults:
                multiplier = max(multiplier, fault_mults[severity])
            elif fault_mults:
                # Interpolate for unlisted severities
                max_sev = max(fault_mults.keys())
                if severity > max_sev:
                    multiplier = max(multiplier, fault_mults[max_sev])

        return base * multiplier

    def _pass_rate(self, faults_by_station: Dict[str, Dict[str, int]]) -> float:
        """
        Estimate line pass rate based on QC-related faults.

        vision_error on stn6 → wrong pass/fail decisions
        misroute on stn7 → good products sent to reject bin
        gripper on stn2 → products not assembled → fail QC
        """
        # Start at 100% pass rate, multiply failure probabilities
        pass_rate = 1.0

        stn6_faults = faults_by_station.get("stn6", {})
        vision_sev = stn6_faults.get("vision_error", 0)
        if vision_sev > 0:
            # Vision error causes wrong QC reads
            error_prob = vision_sev * FAULT_PROBABILITIES["vision_error"]["prob_per_severity"]
            pass_rate *= (1.0 - error_prob)

        stn7_faults = faults_by_station.get("stn7", {})
        misroute_sev = stn7_faults.get("misroute", 0)
        if misroute_sev > 0:
            error_prob = misroute_sev * FAULT_PROBABILITIES["misroute"]["prob_per_severity"]
            pass_rate *= (1.0 - error_prob)

        stn2_faults = faults_by_station.get("stn2", {})
        gripper_sev = stn2_faults.get("gripper_failure", 0)
        if gripper_sev > 0:
            error_prob = gripper_sev * FAULT_PROBABILITIES["gripper_failure"]["prob_per_severity"]
            pass_rate *= (1.0 - error_prob)

        return max(0.0, min(1.0, pass_rate))

    def _run_scenario(
        self,
        target_station: str,
        faults_by_station: Dict[str, Dict[str, int]],
        line_speed_mult: float,
        duration_s: float,
        scenario_label: str,
        stations: Optional[List[str]] = None,
    ) -> SimulationResult:
        """Run one production scenario."""
        if stations is None:
            stations = DEFAULT_LINE_STATIONS

        # Compute per-station cycle times
        cycle_times = {}
        for sid in stations:
            faults = faults_by_station.get(sid, {})
            ct = self._station_cycle_time(sid, faults)
            cycle_times[sid] = ct / line_speed_mult  # speed multiplier

        # Bottleneck = station with longest cycle time
        bottleneck_id = max(cycle_times, key=cycle_times.get)
        bottleneck_ct = cycle_times[bottleneck_id]

        # Throughput limited by bottleneck (products/min)
        throughput_ppm = 60.0 / bottleneck_ct if bottleneck_ct > 0 else 0.0

        # Pass rate
        pass_rate = self._pass_rate(faults_by_station)
        effective_throughput = throughput_ppm * pass_rate

        # Cumulative production time series
        t_eval = np.linspace(0, duration_s, int(duration_s))
        cumulative = np.floor(t_eval * effective_throughput / 60.0)

        ts_production = TimeSeriesData(
            name="cumulative_production",
            unit="units",
            times=t_eval,
            values=cumulative,
            steady_state=float(cumulative[-1]),
        )

        # Cycle time per station as time series (constant, but useful for charts)
        ts_cycle = TimeSeriesData(
            name="cycle_times",
            unit="s",
            times=np.array(list(range(len(stations))), dtype=float),
            values=np.array([cycle_times[s] for s in stations]),
            steady_state=float(bottleneck_ct),
        )

        kpis = {
            "cycle_times": {sid: round(ct, 2) for sid, ct in cycle_times.items()},
            "bottleneck_station": bottleneck_id,
            "bottleneck_cycle_time_s": round(bottleneck_ct, 2),
            "throughput_ppm": round(throughput_ppm, 2),
            "pass_rate": round(pass_rate * 100, 1),
            "effective_throughput_ppm": round(effective_throughput, 2),
            "total_produced_in_duration": int(cumulative[-1]),
            "line_speed_multiplier": round(line_speed_mult, 2),
        }

        warnings = []
        if throughput_ppm < 1.0:
            warnings.append(f"Throughput critically low: {throughput_ppm:.1f}/min")
        if pass_rate < 0.7:
            warnings.append(f"Pass rate dangerously low: {pass_rate*100:.0f}%")
        if bottleneck_ct > 30:
            warnings.append(
                f"Bottleneck {bottleneck_id} has {bottleneck_ct:.1f}s cycle time"
            )

        return SimulationResult(
            model_name=self.model_name,
            station_id=f"line({','.join(stations)})",
            scenario=scenario_label,
            duration_s=duration_s,
            time_series=[ts_production, ts_cycle],
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
        Run before/after production line simulation.

        current_state should contain:
            faults: dict of {station_id: {fault_type: severity}}
            line_speed_multiplier: current speed (default 1.0)
            stations: optional list of station_ids in the line

        proposed_params may contain:
            line_speed_multiplier: new speed factor
            clear_fault: if True, clear faults on target station
            clear_all_faults: if True, clear all faults
            target_station: which station's faults to clear
        """
        faults_before = current_state.get("faults", {})
        speed_before = current_state.get("line_speed_multiplier", 1.0)
        stations = current_state.get("stations", DEFAULT_LINE_STATIONS)

        before = self._run_scenario(
            station_id, faults_before, speed_before, duration_s, "before", stations
        )

        # Apply proposed changes
        faults_after = {}
        for sid, fault_dict in faults_before.items():
            faults_after[sid] = dict(fault_dict)

        target = proposed_params.get("target_station", station_id)
        if proposed_params.get("clear_fault", False):
            faults_after[target] = {}
        if proposed_params.get("clear_all_faults", False):
            faults_after = {sid: {} for sid in faults_after}

        speed_after = proposed_params.get("line_speed_multiplier", speed_before)

        after = self._run_scenario(
            station_id, faults_after, speed_after, duration_s, "after", stations
        )

        # Deltas
        tp_before = before.kpis["effective_throughput_ppm"]
        tp_after = after.kpis["effective_throughput_ppm"]
        pr_before = before.kpis["pass_rate"]
        pr_after = after.kpis["pass_rate"]

        deltas = {
            "throughput_delta_ppm": round(tp_after - tp_before, 2),
            "throughput_delta_pct": round(
                ((tp_after - tp_before) / tp_before * 100) if tp_before > 0 else 0, 1
            ),
            "pass_rate_delta_pct": round(pr_after - pr_before, 1),
            "bottleneck_cycle_delta_s": round(
                after.kpis["bottleneck_cycle_time_s"]
                - before.kpis["bottleneck_cycle_time_s"],
                2,
            ),
            "production_delta_units": (
                after.kpis["total_produced_in_duration"]
                - before.kpis["total_produced_in_duration"]
            ),
        }

        # GO/NO_GO
        if tp_after > tp_before and pr_after >= pr_before - 5:
            go_no_go = "GO"
            confidence = min(92.0, 60.0 + (tp_after - tp_before) * 10)
            reasoning = (
                f"Throughput improves from {tp_before:.1f} to {tp_after:.1f}/min "
                f"(+{deltas['throughput_delta_pct']:.1f}%). Pass rate: {pr_after:.0f}%."
            )
        elif tp_after >= tp_before * 0.85 and pr_after > pr_before:
            go_no_go = "GO"
            confidence = 60.0
            reasoning = (
                f"Throughput slightly reduced to {tp_after:.1f}/min but "
                f"pass rate improves to {pr_after:.0f}%. Net positive."
            )
        elif tp_after < tp_before * 0.5:
            go_no_go = "NO_GO"
            confidence = 85.0
            reasoning = (
                f"Throughput drops to {tp_after:.1f}/min "
                f"({deltas['throughput_delta_pct']:.1f}%). Unacceptable loss."
            )
        else:
            go_no_go = "GO"
            confidence = 50.0
            reasoning = (
                f"Marginal change: throughput {tp_after:.1f}/min, "
                f"pass rate {pr_after:.0f}%."
            )

        return ComparisonResult(
            before=before,
            after=after,
            deltas=deltas,
            go_no_go=go_no_go,
            confidence=confidence,
            reasoning=reasoning,
        )
