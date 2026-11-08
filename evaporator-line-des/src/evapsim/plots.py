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

