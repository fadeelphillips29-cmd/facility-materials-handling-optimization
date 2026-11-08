"""Matplotlib figures (static PNGs) with one shared style.

Department colour code, used in every diagram:
blue = engineering, pink = evaporator line, orange = in-house sheet metal,
green = outsourced, grey = assembly.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch, Patch  # noqa: E402

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"
CRITICAL = "#d03b3b"
NEUTRAL = "#b9b8b0"

DEPT_EDGE = {"engineering": "#2a78d6", "evaporator": "#d55181", "sheet_metal": "#eb6834",
             "outsourced": "#1f9d55", "assembly": "#6f6e69"}
DEPT_FILL = {"engineering": "#dbe8f8", "evaporator": "#fbe1ea", "sheet_metal": "#fde3d6",
             "outsourced": "#d8f0e2", "assembly": "#e8e7e3"}
DEPT_LABEL = {"engineering": "Engineering", "evaporator": "Evaporator line",
              "sheet_metal": "In-house sheet metal", "outsourced": "Outsourced / procurement",
              "assembly": "Assembly"}

STATE_ORDER = ["busy", "changeover", "down", "blocked", "starved"]
STATE_COLORS = {"busy": SERIES[0], "changeover": SERIES[3], "down": SERIES[7],
                "blocked": SERIES[1], "starved": NEUTRAL}
DIST_COLORS = {"lognormal": SERIES[0], "gamma": SERIES[1], "weibull": SERIES[2]}


def apply_style() -> None:
    """Set the shared rcParams."""
    plt.rcParams.update({
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "axes.edgecolor": AXIS, "axes.labelcolor": INK_2, "axes.titlecolor": INK,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.labelsize": 10,
        "axes.grid": True, "axes.axisbelow": True, "axes.spines.top": False,
        "axes.spines.right": False, "grid.color": GRID, "grid.linewidth": 0.6,
        "xtick.color": MUTED, "ytick.color": MUTED, "xtick.labelcolor": INK_2,
        "ytick.labelcolor": INK_2, "font.size": 10, "legend.frameon": False,
        "legend.fontsize": 9, "lines.linewidth": 2.0, "figure.dpi": 110, "savefig.dpi": 150,
        "savefig.bbox": "tight",
    })


def save(fig: plt.Figure, path: Path) -> Path:
    """Save and close a figure."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)
    return path


def dept_legend(ax: plt.Axes, loc: str = "lower center", **kw: object) -> None:
    """Add the department colour-code legend."""
    handles = [Patch(facecolor=DEPT_FILL[d], edgecolor=DEPT_EDGE[d], label=DEPT_LABEL[d])
               for d in DEPT_LABEL]
    ax.legend(handles=handles, loc=loc, ncol=5, **kw)


# ----------------------------------------------------------- process flow
def node(ax: plt.Axes, x: float, y: float, text: str, dept: str, w: float = 15.0,
         h: float = 6.0, fs: float = 8.0) -> None:
    """Draw one rounded process box centred on (x, y)."""
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                boxstyle="round,pad=0.25,rounding_size=0.8",
                                fc=DEPT_FILL[dept], ec=DEPT_EDGE[dept], lw=1.4))
    ax.text(x, y, text, ha="center", va="center", fontsize=fs, color=INK, linespacing=1.2)


def arrow(ax: plt.Axes, p0: tuple[float, float], p1: tuple[float, float], ls: str = "-",
          color: str = INK_2, rad: float = 0.0, lw: float = 1.2) -> None:
    """Connector arrow between two points."""
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle="-|>", mutation_scale=11, lw=lw, ls=ls,
                                 color=color, connectionstyle=f"arc3,rad={rad}",
                                 shrinkA=2, shrinkB=2))


def process_flow_figure(path: Path, wash_before_test: bool = True,
                        include_coating: bool = True) -> Path:
    """The 14-step process flow, colour-coded by department."""
    apply_style()
    fig, ax = plt.subplots(figsize=(18, 10))
    ax.set_xlim(0, 180)
    ax.set_ylim(0, 106)
    ax.axis("off")
    W, H = 15.5, 7.0
    n = {
        "eng": (10, 70, "1 Engineering releases\ndrawings to shop floor", "engineering"),
        "pt": (32, 82, "2 Procure tubing\n~8 d", "outsourced"),
        "ps": (10, 18, "2 Procure sheet metal\n(cut to size) ~4 d", "outsourced"),
        "trim": (52, 82, "6 Trim tubes", "evaporator"),
        "hp": (72, 82, "6 Weld hairpins\n(2 tubes + 1 bend)", "evaporator"),
        "fps": (32, 62, "3 Fin press set-up\n(tooling change)", "evaporator"),
        "fin": (52, 62, "4 Punch fins\n75 fins/min nominal", "evaporator"),
        "box": (72, 62, "5 Boxing: modules +\nend panels (same op.)", "evaporator"),
        "stk": (92, 62, "7 Steeking\n(2 operators)", "evaporator"),
        "rb": (112, 62, "8 Weld return\nbends", "evaporator"),
        "exp": (132, 62, "9 Hydraulic\nexpanding", "evaporator"),
        "ph": (132, 82, "10 Prepare headers\n(parallel)", "evaporator"),
        "hw": (152, 62, "10 Header welding", "evaporator"),
        "wash": (152, 44, "11 Cleaning\n(wash bay)", "evaporator"),
        "test": (132, 44, "12 Pressure test", "evaporator"),
        "rwk": (132, 28, "Rework (weld repair)\n-> retest", "evaporator"),
        "coat": (112, 44, "Powder coat /\ngalvanise (out)", "outsourced"),
        "ca": (92, 18, "Complete assembly\ncoil + plenum + tray", "assembly"),
        "pb": (32, 27, "13 Press brake\n(plenum)", "sheet_metal"),
        "fw": (52, 27, "13 Flat welding", "sheet_metal"),
        "pa": (72, 27, "13 Plenum assembly", "sheet_metal"),
        "dte": (32, 9, "14 Drip tray: external\nbend & punch", "outsourced"),
        "dtw": (52, 9, "14 Drip tray weld", "sheet_metal"),
        "dta": (72, 9, "14 Drip tray assembly", "sheet_metal"),
        "cust": (112, 12, "Customer", "assembly"),
    }
    for _k, (x, y, t, d) in n.items():
        node(ax, x, y, t, d, W, H)

    def e(a: str, b: str, side_a: str = "r", side_b: str = "l", **kw: object) -> None:
        xa, ya = n[a][0], n[a][1]
        xb, yb = n[b][0], n[b][1]
        off = {"r": (W / 2, 0), "l": (-W / 2, 0), "t": (0, H / 2), "b": (0, -H / 2)}
        arrow(ax, (xa + off[side_a][0], ya + off[side_a][1]),
              (xb + off[side_b][0], yb + off[side_b][1]), **kw)

    e("eng", "pt", "r", "l")
    e("eng", "fps", "r", "l")
    e("eng", "ps", "b", "t")
    e("pt", "trim", ls="--")
    e("pt", "box", "b", "t", rad=0.15, ls="--")
    e("pt", "ph", "t", "t", rad=-0.1, ls="--")
    e("trim", "hp")
    e("fps", "fin")
    e("fin", "box")
    e("box", "stk")
    e("hp", "stk", "r", "t", rad=-0.25)
    e("fin", "stk", "b", "b", rad=0.3, ls=":")
    e("stk", "rb")
    e("rb", "exp")
    e("exp", "hw")
    e("ph", "hw", "r", "t", rad=-0.3)
    if wash_before_test:
        e("hw", "wash", "b", "t")
        e("wash", "test", "l", "r")
        last = "test"
    else:
        e("hw", "test", "b", "t", rad=0.2)
        e("test", "wash", "r", "l")
        last = "wash"
    e("test", "rwk", "b", "t", color=CRITICAL)
    e("rwk", "test", "r", "r", rad=-0.6, color=CRITICAL)
    if include_coating:
        if last == "test":
            e(last, "coat", "l", "r")
        else:
            e(last, "coat", "b", "r", rad=0.3)
        e("coat", "ca", "b", "t", rad=0.25)
    else:
        e(last, "ca", "l", "t", rad=0.2)
    e("ps", "pb", "r", "l")
    e("ps", "dte", "r", "l")
    e("pb", "fw")
    e("fw", "pa")
    e("dte", "dtw")
    e("dtw", "dta")
    e("pa", "ca", "r", "l", rad=-0.1)
    e("dta", "ca", "r", "l", rad=0.1)
    e("ca", "cust")
    ax.text(1, 105, "Process flow of the evaporator production system (the Company, illustrative)",
            fontsize=14, fontweight="bold", color=INK, va="top")
    ax.text(1, 101.5, "Solid = material flow · dashed = purchased material arrives · dotted = fin "
            "pack to steeking · red = test failure loop", fontsize=9, color=MUTED, va="top")
    dept_legend(ax, loc="lower right", bbox_to_anchor=(1.0, -0.02), fontsize=9)
    return save(fig, path)


# ------------------------------------------------------------ input analysis
def input_fit_figure(x: np.ndarray, fits: list, title: str, selected: str, unit: str,
                     path: Path) -> Path:
    """Histogram with fitted densities (left) and a Q-Q plot per candidate (right)."""
    from .distributions import pdf, ppf

    apply_style()
    x = np.sort(np.asarray(x, dtype=float))
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(10.5, 3.8))
    ax1.hist(x, bins="auto", density=True, color=GRID, edgecolor=SURFACE, linewidth=1.5,
             label=f"Observed (n={len(x)})")
    grid = np.linspace(x.min() * 0.8, x.max() * 1.15, 300)
    for f in fits:
        ax1.plot(grid, pdf(f, grid), color=DIST_COLORS[f.distribution],
                 lw=2.4 if f.distribution == selected else 1.4,
                 label=f"{f.distribution} (AIC {f.aic:.1f})")
    ax1.set_xlabel(f"Observed time ({unit})")
    ax1.set_ylabel(f"Density (1/{unit.split()[0]})")
    ax1.set_title("Histogram and fitted densities", loc="left")
    ax1.set_ylim(0, ax1.get_ylim()[1] * 1.35)
    ax1.legend(loc="upper right", fontsize=8)
    q = (np.arange(1, len(x) + 1) - 0.5) / len(x)
    ax2.plot([x.min(), x.max()], [x.min(), x.max()], color=AXIS, lw=1.0)
    for f in fits:
        ax2.plot(ppf(f, q), x, "o", ms=4.5, mfc=DIST_COLORS[f.distribution], mec=SURFACE,
                 mew=0.8, label=f.distribution)
    ax2.set_xlabel(f"Theoretical quantile ({unit})")
    ax2.set_ylabel(f"Observed quantile ({unit})")
    ax2.set_title("Q-Q plot (45° line = perfect fit)", loc="left")
    ax2.legend(loc="upper left", fontsize=8)
    fig.suptitle(title, x=0.01, ha="left", fontsize=12.5, fontweight="bold", color=INK)
    fig.tight_layout()
    return save(fig, path)


def bar_by_department(df: pd.DataFrame, value: str, label_col: str, dept_col: str,
                      xlabel: str, title: str, path: Path, ref: float | None = None,
                      ref_label: str = "", pct: bool = False) -> Path:
    """Horizontal bars coloured by department (one bar per row, ranked)."""
    apply_style()
    d = df.sort_values(value)
    fig, ax = plt.subplots(figsize=(9, 0.38 * len(d) + 1.6))
    vals = d[value].to_numpy() * (100 if pct else 1)
    ax.barh(d[label_col], vals, color=[DEPT_FILL[x] for x in d[dept_col]],
            edgecolor=[DEPT_EDGE[x] for x in d[dept_col]], linewidth=1.2, height=0.65)
    for i, v in enumerate(vals):
        ax.text(v, i, f" {v:.1f}{'%' if pct else ''}", va="center", fontsize=8, color=INK_2)
    if ref is not None:
        ax.axvline(ref * (100 if pct else 1), color=CRITICAL, lw=1.4)
        ax.text(ref * (100 if pct else 1), len(d) - 0.4, f" {ref_label}", color=CRITICAL,
                fontsize=8.5, va="bottom")
    ax.set_xlabel(xlabel)
    ax.grid(axis="y", visible=False)
    ax.set_title(title, loc="left")
    ax.set_xlim(0, max(vals.max(), (ref or 0) * (100 if pct else 1)) * 1.15)
    dept_legend(ax, loc="lower center", bbox_to_anchor=(0.5, -0.32 - 2.2 / (len(d) + 4)),
                fontsize=8)
    return save(fig, path)


# --------------------------------------------------------------- run figures
def resource_dept(cfg) -> dict[str, str]:
    """Department of each resource (from the first operation it performs)."""
    out = {}
    for res in cfg.resources:
        ops = [o for o in cfg.resource_ops(res) if o != "fin_press"]
        out[res] = cfg.operations[ops[0]]["department"] if ops else "evaporator"
    return out


def state_bars(rs: pd.DataFrame, title: str, path: Path) -> Path:
    """Stacked horizontal bars of resource state shares (sorted by active share)."""
    apply_style()
    d = rs.sort_values("active")
    fig, ax = plt.subplots(figsize=(10, 0.4 * len(d) + 1.8))
    left = np.zeros(len(d))
    for s in STATE_ORDER:
        v = d[s].to_numpy() * 100
        ax.barh(d["label"], v, left=left, color=STATE_COLORS[s], edgecolor=SURFACE,
                linewidth=1.2, height=0.65, label=s)
        for y, (lft, w) in enumerate(zip(left, v, strict=True)):
            if w >= 6:
                ax.text(lft + w / 2, y, f"{w:.0f}", ha="center", va="center", fontsize=7.5,
                        color=INK if s in ("changeover", "starved") else "white")
        left += v
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of available server time (%)")
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=5, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    ax.set_title(title, loc="left", pad=26)
    return save(fig, path)


def lead_time_hist(hists: dict[str, np.ndarray], edges: np.ndarray, title: str, path: Path,
                   due_days: float | None = None) -> Path:
    """Order lead-time distribution(s) as step histograms (share of orders per day bin)."""
    apply_style()
    fig, ax = plt.subplots(figsize=(9, 4))
    hi = 0
    for k, (lab, h) in enumerate(hists.items()):
        c = h[:-1] / max(1, h.sum()) * 100
        ax.step(edges[:-1], c, where="post", color=SERIES[k], lw=1.8, label=lab)
        nz = np.nonzero(c > 0.05)[0]
        hi = max(hi, int(nz.max()) + 3 if len(nz) else 0)
    if due_days:
        ax.axvline(due_days, color=CRITICAL, lw=1.3)
        ax.text(due_days, ax.get_ylim()[1] * 0.95, f" due date {due_days:.0f} d",
                color=CRITICAL, fontsize=8.5, va="top")
    ax.set_xlim(edges[0], max(hi, (due_days or 0) + 3))
    ax.set_xlabel("Order lead time (working days)")
    ax.set_ylabel("Share of orders (%)")
    ax.set_title(title, loc="left")
    ax.legend(loc="upper right")
    return save(fig, path)


def convergence_figure(conv: pd.DataFrame, target: float, title: str, path: Path) -> Path:
    """Running mean ± CI (top) and relative half-width (bottom) per metric."""
    apply_style()
    metrics = list(dict.fromkeys(conv["metric"]))
    names = {"lt_mean_days": ("Mean order lead time", "working days"),
             "throughput_eva_week": ("Throughput", "EVA/week"),
             "lt_p90_days": ("P90 order lead time", "working days")}
    fig, axes = plt.subplots(2, len(metrics), figsize=(5.2 * len(metrics), 6.2), squeeze=False)
    for j, m in enumerate(metrics):
        d = conv[conv["metric"] == m]
        name, unit = names.get(m, (m, ""))
        ax = axes[0, j]
        ax.fill_between(d["n"], d["running_mean"] - d["ci_half_width"],
                        d["running_mean"] + d["ci_half_width"], color=SERIES[0], alpha=0.18,
                        lw=0, label="95% CI")
        ax.plot(d["n"], d["running_mean"], color=SERIES[0], lw=1.6, label="running mean")
        s = d[d["n"] >= 10]
        lo = (s["running_mean"] - s["ci_half_width"]).min()
        hi = (s["running_mean"] + s["ci_half_width"]).max()
        ax.set_ylim(lo - 0.15 * (hi - lo), hi + 0.15 * (hi - lo))
        ax.set_title(name, loc="left")
        ax.set_ylabel(f"Running mean ({unit})")
        ax.legend(loc="upper right", fontsize=8)
        ax2 = axes[1, j]
        ax2.plot(d["n"], d["rel_half_width_pct"], color=SERIES[1], lw=1.6)
        ax2.axhline(target, color=INK_2, lw=1)
        ax2.text(d["n"].max(), target, f"target ±{target:g}%", ha="right", va="bottom",
                 fontsize=8.5, color=INK_2)
        ax2.set_ylim(0, min(10, d["rel_half_width_pct"].max() * 1.05))
        ax2.set_xlabel("Number of replications")
        ax2.set_ylabel("CI half-width (% of mean)")
    fig.suptitle(title, x=0.01, ha="left", fontsize=13, fontweight="bold", color=INK)
    fig.tight_layout()
    return save(fig, path)


def utilisation_vs_handcalc(rs: pd.DataFrame, hc: pd.DataFrame, dept: dict[str, str],
                            title: str, path: Path) -> Path:
    """Simulated busy share vs hand-calculated utilisation per resource."""
    apply_style()
    d = rs.merge(hc[["resource", "utilisation_with_rework"]], on="resource").sort_values(
        "active")
    fig, ax = plt.subplots(figsize=(9.5, 0.42 * len(d) + 1.8))
    y = np.arange(len(d))
    ax.barh(y, d["active"] * 100, color=[DEPT_FILL[dept[r]] for r in d["resource"]],
            edgecolor=[DEPT_EDGE[dept[r]] for r in d["resource"]], lw=1.2, height=0.62,
            label="simulated active share (busy + changeover + down)")
    ax.plot(d["utilisation_with_rework"] * 100, y, "|", ms=16, mew=2.2, color=INK,
            label="hand calculation (incl. expected rework)")
    ax.set_yticks(y, d["label"])
    ax.set_xlabel("Utilisation at demand (%)")
    ax.grid(axis="y", visible=False)
    ax.set_title(title, loc="left")
    ax.legend(loc="lower right", fontsize=8.5)
    return save(fig, path)


def validation_figure(obs: pd.DataFrame, obs_lt: np.ndarray, sim_th: np.ndarray,
                      sim_lt: np.ndarray, demand: float, path: Path) -> Path:
    """Observed vs simulated: weekly output and the 26-week mean order lead time."""
    apply_style()
    fig, axes = plt.subplots(1, 3, figsize=(15.5, 4.2))
    ax = axes[0]
    ax.bar(obs["week"], obs["eva_completed"], color=SERIES[1], width=0.7, label="observed")
    ax.axhline(demand, color=CRITICAL, lw=1.3, label=f"demand {demand:g}/week")
    ax.axhline(obs["eva_completed"].mean(), color=INK_2, lw=1.1,
               label=f"observed mean {obs['eva_completed'].mean():.2f}")
    ax.set_xlabel("Week")
    ax.set_ylabel("EVA completed per week")
    ax.set_title("Observed weekly output", loc="left")
    ax.legend(loc="upper right", fontsize=8)
    for ax, sim, o, lab, unit in ((axes[1], sim_th, float(obs["eva_completed"].mean()),
                                   "Mean weekly output", "EVA/week"),
                                  (axes[2], sim_lt, float(np.mean(obs_lt)),
                                   "Mean order lead time", "working days")):
        ax.hist(sim, bins=30, color=SERIES[0], edgecolor=SURFACE, lw=1,
                label="simulated 26-week means")
        lo, hi = np.percentile(sim, [2.5, 97.5])
        ax.axvspan(lo, hi, color=GRID, alpha=0.5, lw=0, zorder=0, label="95% prediction interval")
        ax.axvline(o, color=SERIES[1], lw=2.2, label=f"observed {o:.2f}")
        ax.set_xlabel(f"{lab} over 26 weeks ({unit})")
        ax.set_ylabel("Replications")
        ax.set_title(lab, loc="left")
        ax.legend(loc="upper left", fontsize=8)
    fig.suptitle("Validation: nominal model vs observed (illustrative) data", x=0.01, ha="left",
                 fontsize=13, fontweight="bold", color=INK)
    fig.tight_layout()
    return save(fig, path)
