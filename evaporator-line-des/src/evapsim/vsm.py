"""Phase 8 - value stream map (VSM) diagrams drawn with matplotlib.

The current-state map shows the simulated baseline (S0), and the future-state
map shows scenario S5. Every number on a map comes from the scenario result
tables (``scenario_stations.csv``, ``scenario_replications.csv``) or from the
configuration. Each map uses the standard VSM icons: supplier and customer
factories, a production-control box, process boxes with data boxes, inventory
triangles, push arrows, the CONWIP loop, kaizen bursts (future state) and the
lead-time ladder.

Ladder logic: the wait in front of each process comes from Little's law,
W = average buffer content / throughput rate. The processing time is the
mix-weighted mean cycle time. Whatever line lead time is left over (blocking,
breakdowns and changeovers while a unit is on a machine, and rework) is shown
as an explicit "other delays" figure, so the ladder adds up to the simulated
lead time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyArrowPatch, Polygon, Rectangle  # noqa: E402

from .config import DOCS_DIR, LineConfig, Scenario, load_scenarios  # noqa: E402
from .plots import INK, INK_2, MUTED, SERIES, SURFACE, apply_style  # noqa: E402

BOX_FILL = "#eef4fc"
DATA_FILL = "#ffffff"
TRI_FILL = "#fdf3d7"
KAIZEN = "#eda100"


@dataclass
class ProcessData:
    """Numbers shown for one process box."""

    sid: int
    name: str
    ct_s: float
    co_min: float
    uptime_pct: float
    fpy_pct: float
    operators: int
    servers: int
    util_pct: float
    inv_units: float      # average units in front (buffer); NaN for station 1
    wait_min: float       # Little's-law wait in the buffer in front


def collect(scenario: Scenario, stations: pd.DataFrame, reps: pd.DataFrame) -> dict:
    """Assemble everything one VSM needs from the result tables."""
    cfg = scenario.config
    st = stations[stations["scenario"] == scenario.sid].set_index("station_id")
    rp = reps[reps["scenario"] == scenario.sid]
    th_day = float(rp["throughput_per_day"].mean())
    rate_per_min = th_day / (cfg.day_seconds / 60.0)
    procs = []
    for s in cfg.stations:
        row = st.loc[s.id]
        inv = float(row["buffer_in_front_avg"]) if s.id > 1 else float("nan")
        procs.append(ProcessData(
            sid=s.id, name=s.name, ct_s=s.ct_mean_s * cfg.mix_ct_multiplier,
            co_min=s.changeover_min if s.changeover else 0.0,
            uptime_pct=100 * float(row["uptime"]), fpy_pct=100 * float(row["fpy"]),
            operators=s.vsm.operators * (s.servers if s.servers > 1 and s.vsm.operators == 1
                                         else 1),
            servers=s.servers, util_pct=100 * float(row["busy"]), inv_units=inv,
            wait_min=(inv / rate_per_min) if s.id > 1 else 0.0,
        ))
    lt = float(rp["lt_mean_min"].mean())
    va_s = float(rp["va_time_s"].mean())
    day_min = cfg.day_seconds / 60.0
    store_min = (cfg.vsm.raw_material_stock_days + cfg.vsm.finished_goods_stock_days) * day_min
    return {
        "cfg": cfg, "scenario": scenario, "procs": procs, "th_day": th_day,
        "lt_min": lt, "va_s": va_s, "va_ratio_line": va_s / 60.0 / lt,
        "door_lt_days": (lt + store_min) / day_min,
        "va_ratio_door": va_s / 60.0 / (lt + store_min),
        "takt_s": cfg.takt_s, "wip": float(rp["wip_avg"].mean()),
        "other_min": lt - sum(p.wait_min for p in procs) - sum(p.ct_s for p in procs) / 60.0,
    }


# ------------------------------------------------------------------ primitives
def _factory(ax, x: float, y: float, w: float, h: float, label: str) -> None:
    pts = [(x, y), (x + w, y), (x + w, y + h * 0.62), (x + w * 0.75, y + h * 0.42),
           (x + w * 0.75, y + h * 0.62), (x + w * 0.5, y + h * 0.42), (x + w * 0.5, y + h * 0.62),
           (x + w * 0.25, y + h * 0.42), (x + w * 0.25, y + h), (x, y + h)]
    ax.add_patch(Polygon(pts, closed=True, fc=BOX_FILL, ec=INK, lw=1.2))
    ax.text(x + w / 2, y + h * 0.2, label, ha="center", va="center", fontsize=8, color=INK,
            wrap=True)


def _triangle(ax, x: float, y: float, top: str, bottom: str, size: float = 2.6) -> None:
    pts = [(x - size / 2, y), (x + size / 2, y), (x, y + size * 0.95)]
    ax.add_patch(Polygon(pts, closed=True, fc=TRI_FILL, ec=INK, lw=1.0))
    ax.text(x, y + size * 0.3, "I", ha="center", va="center", fontsize=9, fontweight="bold",
            color=INK)
    ax.text(x, y - 0.6, top, ha="center", va="top", fontsize=7.6, color=INK)
    ax.text(x, y - 2.0, bottom, ha="center", va="top", fontsize=7.2, color=INK_2)


def _push_arrow(ax, x0: float, x1: float, y: float) -> None:
    ax.add_patch(Rectangle((x0, y - 0.35), x1 - x0 - 1.0, 0.7, fc="white", ec=INK, lw=0.9,
                           hatch="////"))
    ax.add_patch(Polygon([(x1 - 1.0, y - 0.9), (x1 - 1.0, y + 0.9), (x1, y)], closed=True,
                         fc=INK, ec=INK))


def _arrow(ax, p0, p1, style: str = "-|>", ls: str = "-", color: str = INK,
           rad: float = 0.0) -> None:
    ax.add_patch(FancyArrowPatch(p0, p1, arrowstyle=style, mutation_scale=11, lw=1.1, ls=ls,
                                 color=color, connectionstyle=f"arc3,rad={rad}"))


def _kaizen(ax, x: float, y: float, text: str) -> None:
    n = 9
    ang = np.linspace(0, 2 * np.pi, 2 * n, endpoint=False)
    r = np.where(np.arange(2 * n) % 2 == 0, 2.6, 1.7)
    pts = np.c_[x + r * 1.25 * np.cos(ang), y + r * np.sin(ang)]
    ax.add_patch(Polygon(pts, closed=True, fc=KAIZEN, ec=INK, lw=0.8, zorder=5))
    ax.text(x, y, text, ha="center", va="center", fontsize=6.8, fontweight="bold", color=INK,
            zorder=6)


def _truck(ax, x: float, y: float) -> None:
    ax.add_patch(Rectangle((x, y), 3.4, 1.6, fc="white", ec=INK, lw=1))
    ax.add_patch(Rectangle((x + 3.4, y), 1.4, 1.1, fc="white", ec=INK, lw=1))
    for cx in (x + 0.8, x + 2.6, x + 4.1):
        ax.add_patch(plt.Circle((cx, y - 0.1), 0.35, fc=INK, ec=INK))


# ------------------------------------------------------------------------ draw
def draw_vsm(data: dict, title: str, path: Path, kaizens: list[tuple[float, float, str]] | None
             = None, baseline: dict | None = None) -> Path:
    """Draw one VSM and save it as PNG."""
    apply_style()
    cfg: LineConfig = data["cfg"]
    procs: list[ProcessData] = data["procs"]
    fig, ax = plt.subplots(figsize=(19, 10.6))
    ax.set_xlim(0, 118)
    ax.set_ylim(-3, 66)
    ax.axis("off")
    fig.patch.set_facecolor(SURFACE)
    ax.text(0.5, 65, title, fontsize=15, fontweight="bold", color=INK, va="top")
    ax.text(0.5, 62.6, "All data fictional · numbers from the simulation results "
            f"({len(procs)} stations, {data['scenario'].sid})", fontsize=9, color=MUTED,
            va="top")

    # top row: supplier, production control, customer
    _factory(ax, 1.5, 49, 11, 9, cfg.vsm.supplier)
    _factory(ax, 104, 50, 12, 8.5, cfg.vsm.customer)
    ax.add_patch(Rectangle((103.5, 42.3), 13, 7, fc=DATA_FILL, ec=INK, lw=0.9))
    ax.text(104.2, 48.6, f"Demand {cfg.demand_per_day:.0f} units/day\n"
            f"Takt {cfg.takt_s:.1f} s\n"
            f"Mix S/M/L {'/'.join(f'{p.mix * 100:.0f}' for p in cfg.products)} %\n"
            f"Batches of {cfg.batch_size}", fontsize=7.6, va="top", color=INK, linespacing=1.35)
    ax.add_patch(Rectangle((46, 50), 24, 7.5, fc=BOX_FILL, ec=INK, lw=1.2))
    rel = (f"CONWIP release, {cfg.release.conwip_limit} cards" if cfg.release.rule == "conwip"
           else "Push release (unlimited)")
    ax.text(58, 55.6, "Production Control", ha="center", fontsize=10, fontweight="bold",
            color=INK)
    ax.text(58, 52.2, f"MRP / weekly schedule\n{rel}", ha="center", fontsize=8, color=INK_2,
            va="center")
    _arrow(ax, (103.5, 53), (70.5, 54), ls="--")
    ax.text(87, 54.6, "daily orders", fontsize=7.5, color=INK_2, ha="center")
    _arrow(ax, (46, 54), (13, 55), ls="--")
    ax.text(29, 55.9, "weekly forecast", fontsize=7.5, color=INK_2, ha="center")

    # process boxes
    xs = [16 + i * 13.2 for i in range(len(procs))]
    w, y_box, h_box = 9.6, 31, 6.0
    for x, p in zip(xs, procs, strict=True):
        ax.add_patch(Rectangle((x - w / 2, y_box), w, h_box, fc=BOX_FILL, ec=INK, lw=1.3))
        ax.text(x, y_box + h_box - 0.9, f"S{p.sid}", ha="center", fontsize=9, fontweight="bold",
                color=INK)
        ax.text(x, y_box + 2.4, p.name.replace(" & ", " &\n"), ha="center", va="center",
                fontsize=7.8, color=INK, linespacing=1.15)
        ax.text(x, y_box + 0.55, f"{'●' * p.operators}  {p.operators} op"
                + (f" · {p.servers} stations" if p.servers > 1 else ""),
                ha="center", fontsize=7, color=INK_2)
        ax.add_patch(Rectangle((x - w / 2, 21.4), w, 8.9, fc=DATA_FILL, ec=INK, lw=0.9))
        lines = [f"C/T  {p.ct_s:.1f} s", f"C/O  {p.co_min:.1f} min" if p.co_min else "C/O  —",
                 f"Uptime {p.uptime_pct:.1f}%", f"FPY  {p.fpy_pct:.1f}%",
                 f"Util. {p.util_pct:.0f}%"]
        ax.text(x - w / 2 + 0.5, 29.6, "\n".join(lines), fontsize=7.6, va="top", color=INK,
                linespacing=1.55, family="monospace")
    # push arrows + inventory triangles
    for i in range(len(procs) - 1):
        _push_arrow(ax, xs[i] + w / 2 + 0.2, xs[i + 1] - w / 2 - 0.2, y_box + 4.6)
        p = procs[i + 1]
        _triangle(ax, (xs[i] + xs[i + 1]) / 2, y_box - 0.5, f"{p.inv_units:.1f} u",
                  f"{p.inv_units / cfg.demand_per_day:.3f} d")
    rm_d, fg_d = cfg.vsm.raw_material_stock_days, cfg.vsm.finished_goods_stock_days
    _triangle(ax, 6.5, y_box - 0.5, "RM", f"{rm_d:.1f} d")
    _triangle(ax, 110.5, y_box - 0.5, "FG", f"{fg_d:.1f} d")
    _truck(ax, 4.5, 42)
    _arrow(ax, (7, 48.5), (7, 34.5))
    _truck(ax, 108.5, 37.2)
    _arrow(ax, (110.5, 33.4), (110.5, 36.6))
    ax.text(110.5, 39.4, f"{cfg.vsm.shipments_per_week}×/week", fontsize=7.4, color=INK_2,
            ha="center")
    _arrow(ax, (58, 50), (xs[0], y_box + h_box + 0.2), ls="--", rad=0.15)
    if cfg.release.rule == "conwip":
        _arrow(ax, (xs[-1], y_box + h_box + 0.3), (xs[0] + 1.5, y_box + h_box + 0.3),
               ls=":", color=SERIES[0], rad=0.25)
        ax.text(58, 44.4, f"CONWIP loop: max {cfg.release.conwip_limit} units in line "
                f"(avg WIP {data['wip']:.1f})", ha="center", fontsize=8, color=SERIES[0])

    # timeline ladder
    y_hi, y_lo = 11.0, 7.0
    pts_x = [3.0]
    pts_y = [y_hi]
    for i, (x, p) in enumerate(zip(xs, procs, strict=True)):
        left = (xs[i - 1] + x) / 2 if i else 9.0
        mid_wait = left
        ax.text(mid_wait, y_hi + 0.6, f"{p.wait_min:.1f} min" if i else "release",
                ha="center", fontsize=7.6, color=INK)
        pts_x += [x - w / 2, x - w / 2, x + w / 2, x + w / 2]
        pts_y += [y_hi, y_lo, y_lo, y_hi]
        ax.text(x, y_lo - 1.5, f"{p.ct_s:.1f} s", ha="center", fontsize=7.6, color=INK)
    pts_x.append(xs[-1] + w / 2 + 0.6)
    pts_y.append(y_hi)
    ax.plot(pts_x, pts_y, color=INK, lw=1.3)
    ax.text(1.0, 13.8, "Wait in buffer (Little's law)", fontsize=7.6, color=MUTED)
    ax.text(1.0, 4.2, "Processing (value-added) time", fontsize=7.6, color=MUTED)

    ax.add_patch(Rectangle((101.2, -2.5), 16.6, 16.5, fc=DATA_FILL, ec=INK, lw=1.1))
    rows = [
        ("Throughput", f"{data['th_day']:.1f} /day"),
        ("Line lead time", f"{data['lt_min']:.1f} min"),
        ("  of which other*", f"{data['other_min']:.1f} min"),
        ("VA time", f"{data['va_s']:.0f} s"),
        ("VA ratio (line)", f"{data['va_ratio_line'] * 100:.1f} %"),
        ("Door-to-door LT", f"{data['door_lt_days']:.2f} d"),
        ("VA ratio (door)", f"{data['va_ratio_door'] * 100:.2f} %"),
    ]
    if baseline is not None:
        rows.insert(1, ("  vs current", f"{data['th_day'] - baseline['th_day']:+.1f} /day"))
    for k, (a, b) in enumerate(rows):
        yy = 12.6 - k * 1.85
        ax.text(101.8, yy, a, fontsize=8, color=INK, va="top",
                fontweight="bold" if k == 0 else "normal")
        ax.text(117.2, yy, b, fontsize=8, color=INK, va="top", ha="right",
                fontweight="bold" if k == 0 else "normal")
    ax.text(1.0, -2.2, "* other = time on machines beyond the mean cycle time: blocking, "
            "breakdowns, changeovers and rework. Days of stock = units / daily demand. "
            "RM/FG store levels are VSM inputs, not simulated.", fontsize=7.3, color=MUTED)
    for kx, ky, text in kaizens or []:
        _kaizen(ax, kx, ky, text)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)
    return path


def build_vsms(results_dir: Path, out_dir: Path = DOCS_DIR, future: str = "S5") -> pd.DataFrame:
    """Draw ``vsm_current.png`` (S0) and ``vsm_future.png`` (``future``); return the data."""
    scen = load_scenarios()
    stations = pd.read_csv(Path(results_dir) / "scenario_stations.csv")
    reps = pd.read_csv(Path(results_dir) / "scenario_replications.csv")
    cur = collect(scen["S0"], stations, reps)
    fut = collect(scen[future], stations, reps)
    draw_vsm(cur, "Current-state value stream map: evaporator coil line (S0 baseline)",
             Path(out_dir) / "vsm_current.png")
    xs = [16 + i * 13.2 for i in range(len(fut["procs"]))]
    kaizens = [(xs[1] + 3.5, 39.6, "SMED\nC/O -40%"), (xs[3] + 3.5, 39.6, "SMED\nC/O -40%"),
               (xs[2], 39.6, "TPM\nS1-S5"), (xs[4] + 6.6, 17.2, "Buffers\n5→8")]
    draw_vsm(fut, f"Future-state value stream map: {scen[future].name} ({future})",
             Path(out_dir) / "vsm_future.png", kaizens=kaizens, baseline=cur)
    rows = []
    for label, d in (("current", cur), ("future", fut)):
        for p in d["procs"]:
            rows.append({"state": label, "scenario": d["scenario"].sid, **p.__dict__})
        rows.append({"state": label, "scenario": d["scenario"].sid, "sid": 0, "name": "LINE",
                     "ct_s": sum(p.ct_s for p in d["procs"]), "wait_min": d["lt_min"],
                     "util_pct": np.nan, "inv_units": d["wip"]})
    df = pd.DataFrame(rows)
    df.round(4).to_csv(Path(results_dir) / "vsm_data.csv", index=False)
    summ = pd.DataFrame([{"state": k, "scenario": d["scenario"].sid,
                          "throughput_per_day": d["th_day"], "line_lead_time_min": d["lt_min"],
                          "other_delays_min": d["other_min"], "va_time_s": d["va_s"],
                          "va_ratio_line_pct": 100 * d["va_ratio_line"],
                          "door_to_door_lead_time_days": d["door_lt_days"],
                          "va_ratio_door_pct": 100 * d["va_ratio_door"], "wip": d["wip"]}
                         for k, d in (("current", cur), ("future", fut))])
    summ.round(4).to_csv(Path(results_dir) / "vsm_summary.csv", index=False)
    return summ
