"""
Thermal Dynamics Model — 1st-order ODE with transfer function.

Models temperature evolution for any station with an overheat fault.
Replicates the exact math from TemperatureSimulator in station1.py:

    dT/dt = heating_rate * (T_target - T)     when running
    dT/dt = -cooling_rate * (T - T_ambient)    when idle

Transfer function (linearized around operating point):
    G(s) = K / (τs + 1)

Where:
    K = T_target - T_ambient  (steady-state gain)
    τ = 1 / heating_rate      (time constant)

The model runs two scenarios:
    1. "before" — current fault severity, current speed
    2. "after"  — proposed parameters applied (speed change, fan, fault clear)

Then compares steady-state temperatures and time-to-safe.
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np
from scipy.integrate import solve_ivp
from scipy.signal import lti, step

from simulation.models.base_model import (
    BaseModel,
    ComparisonResult,
    SimulationResult,
    TimeSeriesData,
)
from simulation.station_params import (
    THERMAL_PARAMS,
    CYCLE_TIME_PARAMS,
    SAFE_BOUNDS,
    get_station_type,
)


class ThermalModel(BaseModel):
    """
    First-principles thermal model for factory stations.

    ODE:  C * dT/dt = Q_gen(speed, severity) - Q_loss(T, fan_speed)

    Simplified to match the twin's TemperatureSimulator:
        dT/dt = α * (T_target(speed, severity) - T)   [heating]
              - β * (T - T_amb)                         [cooling + fan]
    """

    model_name = "thermal_dynamics"

    def _get_params(self, station_id: str) -> dict:
        stype = get_station_type(station_id)
        return THERMAL_PARAMS.get(stype, THERMAL_PARAMS["station1"])

    def _compute_target(self, params: dict, speed_factor: float,
                        fault_severity: int, fan_speed_pct: float) -> float:
        """Compute thermal equilibrium target temperature."""
        base_target = params["T_steady_normal"]
        fault_offset = params["fault_offset_per_severity"] * fault_severity
        # Speed affects heat generation: lower speed → less heat
        speed_heat = base_target * speed_factor
        # Fan affects cooling: fan_speed 100% doubles cooling
        fan_offset = fan_speed_pct / 100.0 * 5.0  # up to 5°C reduction
        return speed_heat + fault_offset - fan_offset

    def _thermal_ode(self, t, T, params, target, fan_speed_pct):
        """ODE: dT/dt for the thermal system."""
        T_amb = params["T_ambient"]
        alpha = params["heating_rate"]
        beta = params["cooling_rate"]
        # Fan boosts cooling rate
        fan_boost = 1.0 + (fan_speed_pct / 100.0) * 2.0  # up to 3x cooling
        heating = alpha * (target - T) if target > T else 0.0
        cooling = beta * fan_boost * (T - T_amb) if T > T_amb else 0.0
        return heating - cooling

    def _run_scenario(
        self,
        station_id: str,
        params: dict,
        T_initial: float,
        speed_factor: float,
        fault_severity: int,
        fan_speed_pct: float,
        duration_s: float,
        scenario_label: str,
    ) -> SimulationResult:
        """Run one thermal scenario (before or after)."""
        target = self._compute_target(params, speed_factor,
                                      fault_severity, fan_speed_pct)
        T_amb = params["T_ambient"]

        # Solve ODE
        t_span = (0.0, duration_s)
        t_eval = np.linspace(0, duration_s, int(duration_s * 2))  # 0.5s resolution

        sol = solve_ivp(
            fun=lambda t, T: self._thermal_ode(t, T, params, target, fan_speed_pct),
            t_span=t_span,
            y0=[T_initial],
            t_eval=t_eval,
            method="RK45",
        )

        T_values = sol.y[0]
        T_steady = T_values[-1]

        # Transfer function representation (linearized)
        # G(s) = K / (τs + 1)
        alpha = params["heating_rate"]
        K_gain = target - T_amb
        tau = 1.0 / alpha if alpha > 0 else 100.0

        # Step response for documentation/plotting
        sys_tf = lti([K_gain], [tau, 1.0])
        t_step, y_step = step(sys_tf, T=t_eval)
        step_response = y_step + T_amb  # shift by ambient

        # Time to safe (below critical)
        critical = params["critical_temp"]
        if T_initial > critical and T_steady < critical:
            # Find crossing point
            crossings = np.where(T_values < critical)[0]
            time_to_safe = sol.t[crossings[0]] if len(crossings) > 0 else duration_s
        else:
            time_to_safe = 0.0 if T_steady < critical else float("inf")

        # Build result
        ts_temp = TimeSeriesData(
            name="temperature",
            unit="°C",
            times=sol.t,
            values=T_values,
            steady_state=float(T_steady),
        )
        ts_step = TimeSeriesData(
            name="step_response",
            unit="°C",
            times=t_step,
            values=step_response,
            steady_state=float(step_response[-1]) if len(step_response) > 0 else T_amb,
        )

        kpis = {
            "T_initial": round(float(T_initial), 2),
            "T_steady_state": round(float(T_steady), 2),
            "T_target": round(float(target), 2),
            "T_critical": critical,
            "T_ambient": T_amb,
            "time_to_safe_s": round(float(time_to_safe), 1),
            "is_safe": bool(T_steady < critical),
            "transfer_function": {"K": round(K_gain, 2), "tau": round(tau, 2)},
            "fault_severity": fault_severity,
            "speed_factor": round(speed_factor, 2),
            "fan_speed_pct": round(fan_speed_pct, 1),
        }

        warnings = []
        if T_steady >= critical:
            warnings.append(
                f"Steady-state {T_steady:.1f}°C exceeds critical {critical}°C"
            )
        if T_steady >= params["max_temp"]:
            warnings.append(
                f"DANGER: Temperature reaches physical max {params['max_temp']}°C"
            )

        return SimulationResult(
            model_name=self.model_name,
            station_id=station_id,
            scenario=scenario_label,
            duration_s=duration_s,
            time_series=[ts_temp, ts_step],
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
        Run before/after thermal simulation.

        current_state should contain:
            temperature: current temperature reading (°C)
            fault_severity: current overheat severity (0-5, 0=no fault)
            speed_factor: current speed as fraction of nominal (0.0-1.0)
            fan_speed: current fan speed % (0-100)

        proposed_params may contain:
            spindle_speed: new speed in RPM (converted to factor via /3000)
            aux_fan_speed: new fan speed %
            clear_fault: if True, severity drops to 0
            speed_factor: direct speed factor override
        """
        params = self._get_params(station_id)

        # Current state
        T_current = current_state.get("temperature", params["T_steady_normal"])
        fault_sev = current_state.get("fault_severity", 0)
        speed_now = current_state.get("speed_factor", 1.0)
        fan_now = current_state.get("fan_speed", 50.0)

        # "Before" scenario: current conditions projected forward
        before = self._run_scenario(
            station_id, params, T_current,
            speed_now, fault_sev, fan_now,
            duration_s, "before"
        )

        # "After" scenario: proposed changes applied
        speed_after = speed_now
        if "spindle_speed" in proposed_params:
            speed_after = proposed_params["spindle_speed"] / 3000.0
        if "speed_factor" in proposed_params:
            speed_after = proposed_params["speed_factor"]
        if "line_speed_multiplier" in proposed_params:
            speed_after = proposed_params["line_speed_multiplier"]

        fan_after = proposed_params.get("aux_fan_speed", fan_now)
        sev_after = 0 if proposed_params.get("clear_fault", False) else fault_sev

        after = self._run_scenario(
            station_id, params, T_current,
            speed_after, sev_after, fan_after,
            duration_s, "after"
        )

        # Compute deltas
        deltas = {
            "temperature_delta": round(
                after.kpis["T_steady_state"] - before.kpis["T_steady_state"], 2
            ),
            "time_to_safe_delta": round(
                after.kpis["time_to_safe_s"] - before.kpis["time_to_safe_s"], 1
            ),
            "speed_factor_delta": round(speed_after - speed_now, 3),
        }

        # Determine GO/NO_GO
        after_safe = after.kpis["is_safe"]
        before_safe = before.kpis["is_safe"]
        T_after = after.kpis["T_steady_state"]
        T_before = before.kpis["T_steady_state"]

        if after_safe and T_after < T_before:
            go_no_go = "GO"
            confidence = min(95.0, 60.0 + (T_before - T_after) * 2)
            reasoning = (
                f"Temperature drops from {T_before:.1f}°C to {T_after:.1f}°C "
                f"(below critical {params['critical_temp']}°C). Safe to proceed."
            )
        elif after_safe and T_after >= T_before:
            go_no_go = "GO"
            confidence = 55.0
            reasoning = (
                f"Temperature stable at {T_after:.1f}°C "
                f"(below critical). Marginal improvement."
            )
        elif not after_safe and T_after < T_before:
            go_no_go = "NO_GO"
            confidence = 70.0
            reasoning = (
                f"Temperature improves ({T_before:.1f}→{T_after:.1f}°C) but "
                f"still exceeds critical {params['critical_temp']}°C. "
                f"Stronger intervention needed."
            )
        else:
            go_no_go = "NO_GO"
            confidence = 85.0
            reasoning = (
                f"Temperature remains dangerous at {T_after:.1f}°C "
                f"(critical: {params['critical_temp']}°C). Reject proposal."
            )

        return ComparisonResult(
            before=before,
            after=after,
            deltas=deltas,
            go_no_go=go_no_go,
            confidence=confidence,
            reasoning=reasoning,
        )
