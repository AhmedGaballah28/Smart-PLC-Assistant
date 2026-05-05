"""
Simulation Plotter — Before/After comparison charts.

Generates matplotlib figures showing:
  1. Temperature trajectory (before vs after)
  2. Step response (transfer function)
  3. Belt speed comparison
  4. Production cumulative chart
  5. Cycle time bar chart per station

Saves plots to data/simulation_plots/ and returns paths.
"""

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PLOT_DIR = PROJECT_ROOT / "data" / "simulation_plots"


def _ensure_plot_dir():
    PLOT_DIR.mkdir(parents=True, exist_ok=True)


def plot_simulation_results(
    sim_result: Dict[str, Any],
    correlation_id: str = "unknown",
) -> List[str]:
    """
    Generate all relevant plots from a simulation engine result.

    Args:
        sim_result: output from simulation.engine.run_simulation()
        correlation_id: used for filename uniqueness

    Returns:
        list of file paths to saved PNG images
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # non-interactive backend
        import matplotlib.pyplot as plt
    except ImportError:
        logger.warning("matplotlib not available — skipping plots")
        return []

    _ensure_plot_dir()
    saved_paths = []
    models = sim_result.get("models", {})

    for model_name, comparison in models.items():
        before = comparison.get("before", {})
        after = comparison.get("after", {})

        if model_name == "thermal_dynamics":
            paths = _plot_thermal(before, after, correlation_id, plt)
            saved_paths.extend(paths)
        elif model_name == "belt_dynamics":
            paths = _plot_belt(before, after, correlation_id, plt)
            saved_paths.extend(paths)
        elif model_name == "production_line":
            paths = _plot_production(before, after, correlation_id, plt)
            saved_paths.extend(paths)

    # Summary text plot
    paths = _plot_verdict_summary(sim_result, correlation_id, plt)
    saved_paths.extend(paths)

    logger.info(f"Generated {len(saved_paths)} simulation plots")
    return saved_paths


def _plot_thermal(before, after, cid, plt) -> List[str]:
    """Plot temperature trajectory before/after."""
    paths = []

    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    # Temperature trajectory
    ax = axes[0]
    b_ts = before.get("time_series", {}).get("temperature", {})
    a_ts = after.get("time_series", {}).get("temperature", {})

    b_kpis = before.get("kpis", {})
    a_kpis = after.get("kpis", {})
    T_crit = b_kpis.get("T_critical", 70)

    if b_ts:
        ax.plot([b_ts["initial"], b_ts["final"]], "r-", linewidth=1.5, alpha=0.3)
    if a_ts:
        ax.plot([a_ts["initial"], a_ts["final"]], "b-", linewidth=1.5, alpha=0.3)

    # Since we don't have full arrays in the dict, plot key points
    ax.axhline(y=T_crit, color="red", linestyle="--", alpha=0.7, label=f"Critical ({T_crit}°C)")
    ax.axhline(y=b_kpis.get("T_ambient", 25), color="gray", linestyle=":", alpha=0.5, label="Ambient")

    # Bar comparison
    labels = ["Initial", "Steady-state\n(Before)", "Steady-state\n(After)"]
    values = [
        b_kpis.get("T_initial", 25),
        b_kpis.get("T_steady_state", 45),
        a_kpis.get("T_steady_state", 45),
    ]
    colors = ["orange", "red" if values[1] >= T_crit else "orange",
              "green" if values[2] < T_crit else "red"]
    bars = ax.bar(labels, values, color=colors, alpha=0.7, edgecolor="black")
    ax.set_ylabel("Temperature (°C)")
    ax.set_title("Thermal Analysis: Before vs After")
    ax.axhline(y=T_crit, color="red", linestyle="--", alpha=0.7)
    ax.legend()

    # Transfer function info
    ax2 = axes[1]
    tf_before = b_kpis.get("transfer_function", {})
    tf_after = a_kpis.get("transfer_function", {})

    info_text = (
        "Transfer Function: G(s) = K / (τs + 1)\n\n"
        f"BEFORE:\n"
        f"  K = {tf_before.get('K', 0):.2f}°C,  τ = {tf_before.get('tau', 0):.2f}s\n"
        f"  T_steady = {b_kpis.get('T_steady_state', 0):.1f}°C\n"
        f"  Time to safe = {b_kpis.get('time_to_safe_s', 0):.1f}s\n\n"
        f"AFTER:\n"
        f"  K = {tf_after.get('K', 0):.2f}°C,  τ = {tf_after.get('tau', 0):.2f}s\n"
        f"  T_steady = {a_kpis.get('T_steady_state', 0):.1f}°C\n"
        f"  Time to safe = {a_kpis.get('time_to_safe_s', 0):.1f}s\n\n"
        f"Speed: {b_kpis.get('speed_factor', 1):.2f} → {a_kpis.get('speed_factor', 1):.2f}\n"
        f"Fan: {b_kpis.get('fan_speed_pct', 50):.0f}% → {a_kpis.get('fan_speed_pct', 50):.0f}%"
    )
    ax2.text(0.05, 0.95, info_text, transform=ax2.transAxes,
             fontsize=10, verticalalignment="top", fontfamily="monospace",
             bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.8))
    ax2.set_xlim(0, 1)
    ax2.set_ylim(0, 1)
    ax2.axis("off")
    ax2.set_title("Model Parameters")

    fig.suptitle(f"Thermal Dynamics Simulation — {before.get('station_id', '?')}", fontsize=13)
    fig.tight_layout()

    path = str(PLOT_DIR / f"thermal_{cid}.png")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)

    return paths


def _plot_belt(before, after, cid, plt) -> List[str]:
    """Plot belt dynamics comparison."""
    paths = []
    fig, ax = plt.subplots(figsize=(10, 5))

    b_kpis = before.get("kpis", {})
    a_kpis = after.get("kpis", {})

    metrics = ["v_effective_mps", "effective_fraction", "slip_probability",
               "brownout_probability", "products_per_min"]
    labels = ["Eff. Speed\n(m/s)", "Efficiency\n(fraction)", "Slip\nProb",
              "Brownout\nProb", "Throughput\n(ppm)"]

    x = np.arange(len(metrics))
    width = 0.35

    vals_before = [b_kpis.get(m, 0) for m in metrics]
    vals_after = [a_kpis.get(m, 0) for m in metrics]

    bars1 = ax.bar(x - width / 2, vals_before, width, label="Before",
                   color="salmon", edgecolor="black", alpha=0.8)
    bars2 = ax.bar(x + width / 2, vals_after, width, label="After",
                   color="lightgreen", edgecolor="black", alpha=0.8)

    ax.set_xticks(x)
    ax.set_xticklabels(labels)
    ax.legend()
    ax.set_title(f"Belt Dynamics — {before.get('station_id', '?')}")
    ax.set_ylabel("Value")

    fig.tight_layout()
    path = str(PLOT_DIR / f"belt_{cid}.png")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)

    return paths


def _plot_production(before, after, cid, plt) -> List[str]:
    """Plot production line comparison."""
    paths = []
    fig, axes = plt.subplots(1, 2, figsize=(14, 5))

    b_kpis = before.get("kpis", {})
    a_kpis = after.get("kpis", {})

    # Cycle times bar chart
    ax = axes[0]
    ct_before = b_kpis.get("cycle_times", {})
    ct_after = a_kpis.get("cycle_times", {})
    stations = list(ct_before.keys())

    if stations:
        x = np.arange(len(stations))
        width = 0.35
        vals_b = [ct_before.get(s, 0) for s in stations]
        vals_a = [ct_after.get(s, 0) for s in stations]

        ax.bar(x - width / 2, vals_b, width, label="Before", color="salmon",
               edgecolor="black", alpha=0.8)
        ax.bar(x + width / 2, vals_a, width, label="After", color="lightgreen",
               edgecolor="black", alpha=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(stations, rotation=45, ha="right")
        ax.set_ylabel("Cycle Time (s)")
        ax.set_title("Per-Station Cycle Times")
        ax.legend()

        # Mark bottleneck
        bn_b = b_kpis.get("bottleneck_station", "")
        bn_a = a_kpis.get("bottleneck_station", "")
        if bn_b in stations:
            idx = stations.index(bn_b)
            ax.annotate("bottleneck", (idx - width / 2, vals_b[idx]),
                        fontsize=8, ha="center", color="red")

    # KPI summary
    ax2 = axes[1]
    kpi_labels = ["Throughput\n(ppm)", "Pass Rate\n(%)", "Bottleneck\nCycle (s)"]
    kpi_before = [
        b_kpis.get("effective_throughput_ppm", 0),
        b_kpis.get("pass_rate", 0),
        b_kpis.get("bottleneck_cycle_time_s", 0),
    ]
    kpi_after = [
        a_kpis.get("effective_throughput_ppm", 0),
        a_kpis.get("pass_rate", 0),
        a_kpis.get("bottleneck_cycle_time_s", 0),
    ]

    x2 = np.arange(len(kpi_labels))
    ax2.bar(x2 - width / 2, kpi_before, width, label="Before", color="salmon",
            edgecolor="black", alpha=0.8)
    ax2.bar(x2 + width / 2, kpi_after, width, label="After", color="lightgreen",
            edgecolor="black", alpha=0.8)
    ax2.set_xticks(x2)
    ax2.set_xticklabels(kpi_labels)
    ax2.set_title("Line KPIs")
    ax2.legend()

    fig.suptitle("Production Line Simulation", fontsize=13)
    fig.tight_layout()
    path = str(PLOT_DIR / f"production_{cid}.png")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)

    return paths


def _plot_verdict_summary(sim_result, cid, plt) -> List[str]:
    """Plot a summary card with the final verdict."""
    paths = []
    fig, ax = plt.subplots(figsize=(8, 4))

    verdict = sim_result.get("go_no_go", "?")
    confidence = sim_result.get("confidence", 0)
    reasoning = sim_result.get("reasoning", "")
    station = sim_result.get("station_id", "?")
    fault = sim_result.get("fault_type_detected", "?")

    color = "green" if verdict == "GO" else "red" if verdict == "NO_GO" else "orange"

    ax.text(0.5, 0.85, f"VERDICT: {verdict}", transform=ax.transAxes,
            fontsize=28, fontweight="bold", ha="center", color=color)
    ax.text(0.5, 0.70, f"Confidence: {confidence:.0f}%", transform=ax.transAxes,
            fontsize=16, ha="center", color="gray")
    ax.text(0.5, 0.50, f"Station: {station}  |  Fault: {fault}", transform=ax.transAxes,
            fontsize=12, ha="center")

    # Wrap reasoning text
    import textwrap
    wrapped = "\n".join(textwrap.wrap(reasoning, width=70))
    ax.text(0.5, 0.20, wrapped, transform=ax.transAxes,
            fontsize=9, ha="center", va="center", fontfamily="monospace",
            bbox=dict(boxstyle="round", facecolor="lightyellow", alpha=0.8))

    # Deltas
    ct_delta = sim_result.get("predicted_cycle_time_delta", 0)
    tp_delta = sim_result.get("predicted_throughput_delta", 0)
    fr_delta = sim_result.get("predicted_fault_risk_delta", 0)
    delta_text = (
        f"Cycle Time: {ct_delta:+.2f}s  |  "
        f"Throughput: {tp_delta:+.2f}/min  |  "
        f"Fault Risk: {fr_delta:+.1f}"
    )
    ax.text(0.5, 0.02, delta_text, transform=ax.transAxes,
            fontsize=9, ha="center", color="dimgray")

    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    fig.tight_layout()
    path = str(PLOT_DIR / f"verdict_{cid}.png")
    fig.savefig(path, dpi=120, bbox_inches="tight")
    plt.close(fig)
    paths.append(path)

    return paths
