"""
Abstract base class for all simulation models.

Every model follows the same contract:
  1. Initialize with current state + station parameters
  2. simulate(proposed_params, duration_s) → SimulationResult
  3. Results include time-series data + summary KPIs
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class TimeSeriesData:
    """A single time-series variable from the simulation."""
    name: str
    unit: str
    times: np.ndarray          # shape (N,) — time points in seconds
    values: np.ndarray         # shape (N,) — values at each time point
    steady_state: float = 0.0  # final steady-state value

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "unit": self.unit,
            "initial": float(self.values[0]) if len(self.values) > 0 else 0.0,
            "final": float(self.values[-1]) if len(self.values) > 0 else 0.0,
            "steady_state": float(self.steady_state),
            "min": float(np.min(self.values)),
            "max": float(np.max(self.values)),
        }


@dataclass
class SimulationResult:
    """Output of a single simulation run (before OR after)."""
    model_name: str
    station_id: str
    scenario: str                        # "before" or "after"
    duration_s: float
    time_series: List[TimeSeriesData] = field(default_factory=list)
    kpis: Dict[str, Any] = field(default_factory=dict)  # model-specific KPIs
    warnings: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "model": self.model_name,
            "station_id": self.station_id,
            "scenario": self.scenario,
            "duration_s": self.duration_s,
            "kpis": self.kpis,
            "time_series": {ts.name: ts.to_dict() for ts in self.time_series},
            "warnings": self.warnings,
        }


@dataclass
class ComparisonResult:
    """Before/after comparison with delta KPIs and GO/NO_GO verdict."""
    before: SimulationResult
    after: SimulationResult
    deltas: Dict[str, float] = field(default_factory=dict)
    go_no_go: str = "INCONCLUSIVE"  # "GO", "NO_GO", "INCONCLUSIVE"
    confidence: float = 0.0
    reasoning: str = ""

    def to_dict(self) -> dict:
        return {
            "go_no_go": self.go_no_go,
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "deltas": self.deltas,
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
        }


class BaseModel(ABC):
    """Abstract base for all physics simulation models."""

    model_name: str = "base"

    @abstractmethod
    def simulate(
        self,
        station_id: str,
        current_state: Dict[str, Any],
        proposed_params: Dict[str, Any],
        duration_s: float = 300.0,
    ) -> ComparisonResult:
        """
        Run before/after simulation and return comparison.

        Args:
            station_id: e.g. "stn1", "mc_a"
            current_state: current telemetry/sensor readings
            proposed_params: the repair proposal parameters
            duration_s: how far to simulate into the future

        Returns:
            ComparisonResult with before/after time series and verdict
        """
        ...
