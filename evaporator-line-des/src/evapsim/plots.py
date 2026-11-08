"""Matplotlib figures for the analysis (static PNGs saved under ``results/figures``).

All figures share one restrained style: light chart surface, hairline grid,
thin marks, categorical colours assigned in a fixed order so a given entity
(scenario, station state, candidate distribution) always keeps its colour.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from .distributions import FitResult, pdf, ppf  # noqa: E402

# Validated categorical order (fixed, never cycled) and chart chrome.
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
GOOD = "#0ca30c"
CRITICAL = "#d03b3b"
NEUTRAL = "#b9b8b0"

STATE_ORDER = ["busy", "changeover", "down", "blocked", "starved"]
STATE_COLORS = {
    "busy": SERIES[0],
    "changeover": SERIES[3],
    "down": SERIES[7],
    "blocked": SERIES[1],
    "starved": NEUTRAL,
}
DIST_COLORS = {"lognormal": SERIES[0], "gamma": SERIES[1], "weibull": SERIES[2]}


def apply_style() -> None:
    """Set the shared rcParams (call once before plotting)."""
    plt.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": AXIS,
            "axes.labelcolor": INK_2,
            "axes.titlecolor": INK,
            "axes.titlesize": 12,
            "axes.titleweight": "bold",
            "axes.labelsize": 10,
            "axes.grid": True,
            "axes.axisbelow": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "grid.color": GRID,
            "grid.linewidth": 0.6,
            "xtick.color": MUTED,
            "ytick.color": MUTED,
            "xtick.labelcolor": INK_2,
            "ytick.labelcolor": INK_2,
            "font.family": "sans-serif",
            "font.size": 10,
            "legend.frameon": False,
            "legend.fontsize": 9,
            "lines.linewidth": 2.0,
            "figure.dpi": 110,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
        }
    )


def _save(fig: plt.Figure, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


# ----------------------------------------------------------------- input analysis
def input_fit_figure(
    x: np.ndarray, fits: Sequence[FitResult], title: str, selected: str, path: Path
) -> Path:
    """Histogram with fitted densities (left) and QQ plot per candidate (right)."""
    apply_style()
    x = np.sort(np.asarray(x, dtype=float))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 4.0))
    ax1.hist(x, bins="auto", density=True, color=GRID, edgecolor=SURFACE, linewidth=1.5,
             label=f"Observed (n={len(x)})")
    grid = np.linspace(x.min() * 0.8, x.max() * 1.15, 300)
    for f in fits:
        lw = 2.4 if f.distribution == selected else 1.4
        ax1.plot(grid, pdf(f, grid), color=DIST_COLORS[f.distribution], lw=lw,
                 label=f"{f.distribution} (AIC {f.aic:.1f})")
    ax1.set_xlabel("Observed cycle time (s)")
    ax1.set_ylabel("Density (1/s)")
    ax1.set_title("Histogram and fitted densities", loc="left")
    ax1.set_ylim(0, ax1.get_ylim()[1] * 1.35)
    ax1.legend(loc="upper right")

    n = len(x)
    q = (np.arange(1, n + 1) - 0.5) / n
    lo, hi = x.min(), x.max()
    ax2.plot([lo, hi], [lo, hi], color=AXIS, lw=1.0, zorder=1)
    for f in fits:
        ax2.plot(ppf(f, q), x, "o", ms=4.5, mfc=DIST_COLORS[f.distribution], mec=SURFACE,
                 mew=0.8, alpha=0.9, label=f.distribution)
    ax2.set_xlabel("Theoretical quantile (s)")
    ax2.set_ylabel("Observed quantile (s)")
    ax2.set_title("Q-Q plot (45° line = perfect fit)", loc="left")
    ax2.legend(loc="upper left")
    fig.suptitle(title, x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK)
    fig.tight_layout()
    return _save(fig, path)



# ---------------------------------------------------------------- baseline run
def daily_output_figure(daily: pd.DataFrame, demand: float, title: str, path: Path) -> Path:
    """Distribution of daily good output across all replication-days vs demand."""
    apply_style()
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    x = daily["output"].to_numpy()
    bins = np.arange(np.floor(x.min() / 10) * 10, max(x.max(), demand) + 20, 10)
    ax.hist(x, bins=bins, color=SERIES[0], edgecolor=SURFACE, linewidth=1.2)
    ax.axvline(demand, color=CRITICAL, lw=1.6)
    ax.text(demand, ax.get_ylim()[1] * 0.95, f"  demand {demand:.0f}/day", color=INK,
            va="top", ha="left" if demand < bins[-1] - 40 else "right")
    ax.axvline(x.mean(), color=INK_2, lw=1.2)
    ax.text(x.mean(), ax.get_ylim()[1] * 0.85, f"  mean {x.mean():.1f}", color=INK_2, va="top")
    ax.set_xlabel("Good units completed per day (units/day)")
    ax.set_ylabel("Replication-days (count)")
    ax.set_title(title, loc="left")
    return _save(fig, path)


def lead_time_figure(hist: np.ndarray, edges: np.ndarray, pct: dict[str, float], title: str,
                     path: Path) -> Path:
    """Pooled lead-time histogram with mean percentiles marked."""
    apply_style()
    fig, ax = plt.subplots(figsize=(8.5, 4.2))
    counts = hist[: len(edges) - 1].astype(float)
    share = counts / counts.sum()
    upto = int(np.searchsorted(np.cumsum(share), 0.995)) + 2
    ax.bar(edges[:upto], share[:upto] * 100, width=np.diff(edges)[:upto] * 0.9, align="edge",
           color=SERIES[0])
    for i, (k, v) in enumerate(pct.items()):
        ax.axvline(v, color=INK_2, lw=1.0)
        ax.text(v, ax.get_ylim()[1] * (0.95 - 0.09 * i), f" {k} {v:.1f} min", color=INK_2,
                va="top", fontsize=9)
    ax.set_xlabel("Line lead time, release to exit (productive minutes)")
    ax.set_ylabel("Share of good units (%)")
    ax.set_title(title, loc="left")
    return _save(fig, path)


def station_state_figure(st: pd.DataFrame, title: str, path: Path) -> Path:
    """Stacked horizontal bars of station state shares (one bar per station)."""
    apply_style()
    st = st.sort_values("station_id", ascending=False)
    labels = [f"S{i} {n}" for i, n in zip(st["station_id"], st["station"], strict=True)]
    fig, ax = plt.subplots(figsize=(9.5, 4.4))
    left = np.zeros(len(st))
    for s in STATE_ORDER:
        v = st[s].to_numpy() * 100
        ax.barh(labels, v, left=left, color=STATE_COLORS[s], edgecolor=SURFACE, linewidth=1.5,
                height=0.62, label=s)
        for y, (lft, w) in enumerate(zip(left, v, strict=True)):
            if w >= 7:
                ax.text(lft + w / 2, y, f"{w:.0f}", ha="center", va="center", fontsize=8,
                        color="#0b0b0b" if s in ("changeover", "starved") else "white")
        left += v
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of scheduled time (%)")
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=5, loc="lower center", bbox_to_anchor=(0.5, 1.0), frameon=False)
    ax.set_title(title, loc="left", pad=28)
    return _save(fig, path)


def bottleneck_figure(freq: pd.DataFrame, title: str, path: Path) -> Path:
    """Share of replications in which each station was the bottleneck."""
    apply_style()
    fig, ax = plt.subplots(figsize=(8.5, 3.8))
    labels = [f"S{i}" for i in freq["station_id"]]
    v = freq["share"].to_numpy() * 100
    ax.bar(labels, v, color=SERIES[0], width=0.6)
    for i, val in enumerate(v):
        if val > 0:
            ax.text(i, val + 1.5, f"{val:.0f}%", ha="center", color=INK_2, fontsize=9)
    ax.set_ylim(0, 110)
    ax.set_xlabel("Station")
    ax.set_ylabel("Replications where station is bottleneck (%)")
    ax.set_title(title, loc="left")
    return _save(fig, path)


def convergence_figure(conv: pd.DataFrame, target_pct: float, title: str, path: Path) -> Path:
    """Running mean with CI band (top) and relative CI half-width (bottom) per metric."""
    apply_style()
    metrics = list(dict.fromkeys(conv["metric"]))
    fig, axes = plt.subplots(2, len(metrics), figsize=(5.2 * len(metrics), 6.4), squeeze=False)
    names = {"throughput_per_day": ("Throughput", "units/day"),
             "lt_mean_min": ("Mean line lead time", "min")}
    for j, m in enumerate(metrics):
        d = conv[conv["metric"] == m]
        name, unit = names.get(m, (m, ""))
        ax = axes[0, j]
        ax.fill_between(d["n"], d["running_mean"] - d["ci_half_width"],
                        d["running_mean"] + d["ci_half_width"], color=SERIES[0], alpha=0.18,
                        linewidth=0, label="95% CI")
        ax.plot(d["n"], d["running_mean"], color=SERIES[0], lw=1.6, label="running mean")
        settled = d[d["n"] >= 10]
        lo = (settled["running_mean"] - settled["ci_half_width"]).min()
        hi = (settled["running_mean"] + settled["ci_half_width"]).max()
        pad = (hi - lo) * 0.15
        ax.set_ylim(lo - pad, hi + pad)
        ax.set_title(name, loc="left")
        ax.set_ylabel(f"Running mean ({unit})")
        ax.legend(loc="upper right")
        ax2 = axes[1, j]
        ax2.plot(d["n"], d["rel_half_width_pct"], color=SERIES[1], lw=1.6)
        ax2.axhline(target_pct, color=INK_2, lw=1.0)
        ax2.text(d["n"].max(), target_pct, f"target ±{target_pct:g}%", ha="right", va="bottom",
                 color=INK_2, fontsize=9)
        ax2.set_ylim(0, min(10, d["rel_half_width_pct"].max() * 1.05))
        ax2.set_xlabel("Number of replications")
        ax2.set_ylabel("CI half-width (% of mean)")
    fig.suptitle(title, x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK)
    fig.tight_layout()
    return _save(fig, path)


# ------------------------------------------------------------------ validation
def validation_figure(obs_daily: np.ndarray, sim_period_means: np.ndarray, obs_blt: np.ndarray,
                      sim_blt: np.ndarray, util: pd.DataFrame, path: Path) -> Path:
    """Observed vs simulated: 20-day mean output, batch lead-time ECDF, utilisation."""
    apply_style()
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.4))
    ax = axes[0]
    ax.hist(sim_period_means, bins=30, color=SERIES[0], edgecolor=SURFACE, linewidth=1.0,
            label="Simulated 20-day means")
    om = float(np.mean(obs_daily))
    ax.axvline(om, color=SERIES[1], lw=2.2, label=f"Observed mean {om:.1f}")
    lo, hi = np.percentile(sim_period_means, [2.5, 97.5])
    ax.axvspan(lo, hi, color=GRID, alpha=0.5, lw=0, label="95% prediction interval", zorder=0)
    ax.set_xlabel("Mean daily output over 20 days (units/day)")
    ax.set_ylabel("Replications (count)")
    ax.set_title("Daily output", loc="left")
    ax.legend(loc="upper left", fontsize=8)

    ax = axes[1]
    for x, c, lab in ((np.sort(sim_blt), SERIES[0], "Simulated (50 reps)"),
                      (np.sort(obs_blt), SERIES[1], f"Observed ({len(obs_blt)} batches)")):
        ax.step(x, np.arange(1, len(x) + 1) / len(x), where="post", color=c, lw=1.8, label=lab)
    ax.set_xlim(0, np.percentile(np.concatenate([sim_blt, obs_blt]), 99.5))
    ax.set_xlabel("Batch lead time (min)")
    ax.set_ylabel("Cumulative share of batches")
    ax.set_title("Batch lead time (ECDF)", loc="left")
    ax.legend(loc="lower right", fontsize=8)

    ax = axes[2]
    x = np.arange(len(util))
    ax.bar(x - 0.19, util["observed_utilisation"] * 100, width=0.36, color=SERIES[1],
           label="Observed")
    ax.bar(x + 0.19, util["simulated_utilisation"] * 100, width=0.36, color=SERIES[0],
           label="Simulated")
    ax.set_xticks(x, [f"S{i}" for i in util["station_id"]])
    ax.set_xlabel("Station")
    ax.set_ylabel("Utilisation, busy share (%)")
    ax.set_title("Station utilisation", loc="left")
    ax.legend(loc="upper right", fontsize=8)
    fig.suptitle("Validation: nominal model vs observed line data (fictional)", x=0.01,
                 ha="left", fontsize=13, fontweight="bold", color=INK)
    fig.tight_layout()
    return _save(fig, path)
