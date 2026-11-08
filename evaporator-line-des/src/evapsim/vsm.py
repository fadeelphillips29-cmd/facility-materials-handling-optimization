"""Phase 8: current- and future-state value stream maps (matplotlib).

Each map shows the network: a feeder row (fin press, boxing, prepare headers),
the coil line (tubes → steeking → … → complete assembly), the sheet-metal row
(plenum and drip tray), and the outsourced legs (procurement, external
bending, coating). Boxes are colour-coded by department. Every number comes
from a simulation run with the scenario replication count and the base seed,
so the maps agree with ``scenario_summary.csv``. Inventory triangles show the
average number of EVA queuing in front of each process (Little's law: arrival
rate × mean queue time). The timeline ladder follows the critical coil path,
with waits on the upper steps (working days) and processing on the lower steps
(minutes).
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Polygon, Rectangle  # noqa: E402

from . import equations as eq  # noqa: E402
from .config import DOCS_DIR, LineConfig, load_config, load_scenarios, with_demand  # noqa: E402
from .metrics import summarize  # noqa: E402
from .plots import (  # noqa: E402
    DEPT_EDGE,
    DEPT_FILL,
    INK,
    INK_2,
    MUTED,
    apply_style,
    arrow,
    dept_legend,
)
from .runner import activity_summary, resource_summary, run_replications  # noqa: E402

COIL_PATH = ["trim_tubes", "weld_hairpins", "steeking", "weld_return_bends", "expansion",
             "header_welding", "wash", "pressure_test", "coating", "complete_assembly"]
FEEDERS = {"fin_press": 2, "boxing": 3, "prepare_headers": 7}      # column index in row A
SHEET = ["press_brake", "flat_welding", "plenum_assembly", "drip_tray_external",
         "drip_tray_weld", "drip_tray_assembly"]


def collect(cfg: LineConfig, n: int, label: str, workers: int | None = None) -> dict:
    """Run ``cfg`` and return everything a map needs."""
    run = run_replications(cfg, n, label, workers)
    k = summarize(run.reps).set_index("metric")["mean"]
    act = activity_summary(run).set_index("activity")
    res = resource_summary(run).set_index("resource")
    lam = float(k["throughput_eva_week"]) / cfg.week_min      # EVA per minute
    fp = eq.fin_press(**cfg.fin_press)
    procs: dict[str, dict] = {}
    for op, o in cfg.operations.items():
        r = o["resource"]
        rdef = cfg.resources[r]
        wq = float(act.loc[op, "mean_wait_min"]) if op in act.index else 0.0
        procs[op] = {"label": o["label"], "dept": o["department"], "ct": cfg.op_mean_min(op),
                     "ops": int(rdef.get("crew", 1)) * int(rdef.get("servers", 1)),
                     "servers": int(rdef.get("servers", 1)),
                     "util": float(res.loc[r, "busy"]), "wq_min": wq, "inv": lam * wq,
                     "uptime": 1.0, "fpy": float(k["fpy_test"]) if op == "pressure_test"
                     else 1.0}
    wq = float(act.loc["fin_press", "mean_wait_min"]) if "fin_press" in act.index else 0.0
    procs["fin_press"] = {"label": "Fin press (setup + punch)", "dept": "evaporator",
                          "ct": fp.per_eva, "ops": 1, "servers": 1,
                          "util": float(res.loc[cfg.raw["fin_press"]["resource"], "active"]),
                          "wq_min": wq, "inv": lam * wq, "uptime": fp.A_u, "oee": fp.OEE,
                          "fpy": cfg.fin_press["Q"]}
    for key in ("drip_tray_external", "coating"):
        lt = cfg.raw["lead_times"][key]
        procs[key] = {"label": lt["label"], "dept": "outsourced", "delay_days":
                      cfg.lead_time_mean_min(key) / cfg.day_min}
    ev_lt_days = float(k["lt_mean_days"])
    va = float(k["va_min_per_eva"])
    return {"cfg": cfg, "label": label, "kpi": k, "procs": procs, "lt_days": ev_lt_days,
            "eva_lt_days": float(run.reps["eva_lt_mean_days"].mean()), "va_min": va,
            "va_ratio": float(k["va_ratio"]), "th": float(k["throughput_eva_week"]),
            "wip": float(k["wip_total"]), "on_time": float(k["on_time"]),
            "p95": float(k["lt_p95_days"])}


# --------------------------------------------------------------- primitives
def _box(ax, x: float, y: float, w: float, h: float, title: str, dept: str,
         bold: bool = False) -> None:
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                boxstyle="round,pad=0.12,rounding_size=0.5",
                                fc=DEPT_FILL[dept], ec=DEPT_EDGE[dept], lw=2.2 if bold else 1.3))
    title = "\n".join(textwrap.fill(part, 17) for part in title.split("\n"))
    ax.text(x, y, title, ha="center", va="center", fontsize=7.4, color=INK,
            fontweight="bold" if bold else "normal", linespacing=1.1)


def _data(ax, x: float, y_top: float, w: float, lines: list[str]) -> None:
    h = 1.75 * len(lines) + 0.6
    ax.add_patch(Rectangle((x - w / 2, y_top - h), w, h, fc="white", ec=INK_2, lw=0.7))
    ax.text(x - w / 2 + 0.4, y_top - 0.45, "\n".join(lines), fontsize=6.4, va="top",
            family="monospace", color=INK, linespacing=1.45)


def _tri(ax, x: float, y: float, txt: str, s: float = 2.2) -> None:
    ax.add_patch(Polygon([(x - s / 2, y), (x + s / 2, y), (x, y + s * 0.95)], closed=True,
                         fc="#fdf3d7", ec=INK, lw=0.8))
    ax.text(x, y + 0.65, "I", ha="center", va="center", fontsize=6.5, fontweight="bold")
    ax.text(x, y - 0.5, txt, ha="center", va="top", fontsize=6.2, color=INK_2)


def _push(ax, x0: float, x1: float, y: float, onepiece: bool = False) -> None:
    if x1 - x0 < 1.2:
        return
    ax.add_patch(Rectangle((x0, y - 0.3), x1 - x0 - 0.8, 0.6, fc="white", ec=INK, lw=0.7,
                           hatch="////" if not onepiece else None))
    ax.add_patch(Polygon([(x1 - 0.8, y - 0.75), (x1 - 0.8, y + 0.75), (x1, y)], closed=True,
                         fc=INK, ec=INK))


def _kaizen(ax, x: float, y: float, text: str) -> None:
    ang = np.linspace(0, 2 * np.pi, 18, endpoint=False)
    r = np.where(np.arange(18) % 2 == 0, 2.5, 1.65)
    ax.add_patch(Polygon(np.c_[x + 1.35 * r * np.cos(ang), y + r * np.sin(ang)], closed=True,
                         fc="#eda100", ec=INK, lw=0.7, zorder=6))
    ax.text(x, y, text, ha="center", va="center", fontsize=6.2, fontweight="bold", zorder=7)


def _factory(ax, x: float, y: float, label: str, dept: str) -> None:
    w, h = 11, 6
    pts = [(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + 0.6),
           (x + w / 4, y - 0.6), (x + w / 4, y + 0.6), (x, y - 0.6), (x, y + 0.6),
           (x - w / 4, y - 0.6), (x - w / 4, y + h / 2), (x - w / 2, y + h / 2)]
    ax.add_patch(Polygon(pts, closed=True, fc=DEPT_FILL[dept], ec=DEPT_EDGE[dept], lw=1.2))
    ax.text(x, y - 1.8, label, ha="center", va="center", fontsize=7, color=INK)


# --------------------------------------------------------------------- draw
def draw(data: dict, title: str, path: Path, kaizens: list[tuple[float, float, str]] = (),
         compare: dict | None = None) -> Path:
    """Draw one value stream map."""
    apply_style()
    cfg: LineConfig = data["cfg"]
    P = data["procs"]
    tb1 = cfg.transfer_batch == 1
    fig, ax = plt.subplots(figsize=(22, 12.5))
    ax.set_xlim(-2, 152)
    ax.set_ylim(-17, 92)
    ax.axis("off")
    ax.text(-1.5, 91.5, title, fontsize=15, fontweight="bold", va="top", color=INK)
    ax.text(-1.5, 88.3, f"the Company · illustrative, anonymised data · {data['label']} · "
            f"demand {cfg.demand:g} EVA/week · takt {cfg.takt_min:.0f} min/EVA · lot {cfg.lot}, "
            f"transfer batch {cfg.transfer_batch} · release {cfg.raw['release']['rule']}",
            fontsize=9, color=MUTED, va="top")
    # top row: supplier, production control, customer
    _factory(ax, 6, 79, cfg.raw["vsm"]["supplier"], "outsourced")
    _factory(ax, 144, 79, cfg.raw["vsm"]["customer"], "assembly")
    ax.add_patch(Rectangle((62, 75.5), 26, 7.5, fc=DEPT_FILL["engineering"],
                           ec=DEPT_EDGE["engineering"], lw=1.3))
    ax.text(75, 81.2, "Production control / engineering", ha="center", fontsize=9,
            fontweight="bold")
    rel = cfg.raw["release"]
    eng_days = cfg.raw["lead_times"]["engineering_release"]["mean_days"]
    release = (f"CONWIP limit {rel['conwip_limit_orders']} orders" if rel["rule"] == "conwip"
               else "push release")
    ax.text(75, 77.8, f"drawing release ~{eng_days:g} d · {release}", ha="center",
            fontsize=7.5, color=INK_2)
    arrow(ax, (138.5, 80), (88.5, 80), ls="--")
    ax.text(113, 80.8, f"orders {cfg.demand:g} EVA/wk", fontsize=7.5, color=INK_2, ha="center")
    arrow(ax, (62, 80), (11.5, 80), ls="--")
    ax.text(36, 80.8, "purchase orders at drawing release", fontsize=7.5, color=INK_2,
            ha="center")
    # left column: procurement legs
    lt = cfg.raw["lead_times"]
    for y, key in ((44, "procurement_tubing"), (21, "procurement_sheet_metal")):
        _box(ax, 6, y, 10.5, 6, f"{lt[key]['label']}\n{lt[key]['mean_days']:g} working days",
             "outsourced")
    arrow(ax, (6, 76), (6, 47.2))
    arrow(ax, (3, 76), (3, 24.2), rad=0.0)
    # coil line row B
    xB = {op: 18.5 + 13.0 * k for k, op in enumerate(COIL_PATH)}
    yB, w, h = 44, 10.8, 6.0
    for k, op in enumerate(COIL_PATH):
        p = P[op]
        bold = op in ("steeking", "header_welding")
        if "delay_days" in p:
            _box(ax, xB[op], yB, w, h, f"{p['label']}\n{p['delay_days']:g} d (outsourced)",
                 "outsourced")
        else:
            _box(ax, xB[op], yB, w, h, p["label"], p["dept"], bold)
            lines = [f"CT {p['ct']:6.0f} min", f"Ops {p['ops']:>2}"
                     + (f" x{p['servers']}st" if p["servers"] > 1 else ""),
                     f"Util {100 * p['util']:4.0f} %", f"Wq {p['wq_min'] / 60:5.1f} h"]
            if op == "pressure_test":
                lines.append(f"FPY {100 * p['fpy']:4.1f} %")
            _data(ax, xB[op], yB - h / 2 - 0.6, w, lines)
        if k:
            prev = COIL_PATH[k - 1]
            _push(ax, xB[prev] + w / 2 + 0.2, xB[op] - w / 2 - 0.2, yB + 1.2, tb1)
            if "inv" in p:
                _tri(ax, (xB[prev] + xB[op]) / 2, yB - 2.6, f"{p['inv']:.1f}")
    arrow(ax, (11.3, 44), (xB["trim_tubes"] - w / 2, 44))
    # feeder row A
    yA = 66
    xA = {op: 18.5 + 13.0 * c for op, c in FEEDERS.items()}
    for op, x in xA.items():
        p = P[op]
        _box(ax, x, yA, w, h, p["label"], p["dept"])
        lines = [f"CT {p['ct']:6.1f} min", f"Ops {p['ops']:>2}", f"Util {100 * p['util']:4.0f} %"]
        if op == "fin_press":
            lines = [f"CT {p['ct']:6.1f} min", f"OEE {100 * p['oee']:4.1f} %",
                     f"Up  {100 * p['uptime']:4.1f} %", f"Util {100 * p['util']:4.0f} %"]
        _data(ax, x, yA - h / 2 - 0.6, w, lines)
    ax.text((xA["fin_press"] + xA["boxing"]) / 2, yA + h / 2 + 1.1,
            "one shared operator", ha="center", fontsize=7, color=INK_2)
    _push(ax, xA["fin_press"] + w / 2 + 0.2, xA["boxing"] - w / 2 - 0.2, yA + 1.2, tb1)
    arrow(ax, (xA["boxing"] + 2, 56.4), (xB["steeking"] - 2, yB + h / 2), rad=0.2)
    arrow(ax, (xA["prepare_headers"] + 3, 56.4), (xB["header_welding"] - 1, yB + h / 2),
          rad=-0.15)
    arrow(ax, (75, 75.5), (xA["fin_press"] + 1, yA + h / 2 + 0.2), ls="--", rad=0.15)
    ax.text(6, 39.6, "kitted tubing also feeds\nBoxing and Prepare Headers", ha="center",
            va="top", fontsize=6.6, color=INK_2)
    # sheet metal row C
    yC = 21
    xC = {op: 18.5 + 13.0 * k for k, op in enumerate(SHEET)}
    for k, op in enumerate(SHEET):
        p = P[op]
        if "delay_days" in p:
            _box(ax, xC[op], yC, w, h, f"{p['label']}\n{p['delay_days']:g} d", "outsourced")
        else:
            _box(ax, xC[op], yC, w, h, p["label"], p["dept"])
            _data(ax, xC[op], yC - h / 2 - 0.6, w, [f"CT {p['ct']:6.0f} min",
                                                     f"Util {100 * p['util']:4.0f} %"])
        if k and op != "drip_tray_external":
            _push(ax, xC[SHEET[k - 1]] + w / 2 + 0.2, xC[op] - w / 2 - 0.2, yC + 1.2, tb1)
    arrow(ax, (11.3, 21), (xC["press_brake"] - w / 2, 21))
    arrow(ax, (6, 18), (xC["drip_tray_external"] - 2, yC - h / 2), rad=0.3, ls=":")
    arrow(ax, (xC["plenum_assembly"] + w / 2, yC + 2),
          (xB["complete_assembly"] - 2, yB - 12), rad=-0.12)
    arrow(ax, (xC["drip_tray_assembly"] + w / 2, yC),
          (xB["complete_assembly"], yB - 12), rad=-0.2)
    arrow(ax, (xB["complete_assembly"], yB + h / 2), (144, 76), ls="-")
    # ladder along the coil critical path
    y_hi, y_lo = -7.0, -11.0
    segs = [("Eng.", lt["engineering_release"]["mean_days"], None),
            ("Tubing", lt["procurement_tubing"]["mean_days"], None)]
    for op in COIL_PATH:
        p = P[op]
        if "delay_days" in p:
            segs.append((op, p["delay_days"], None))
        else:
            segs.append((op, p["wq_min"] / cfg.day_min, p["ct"]))
    x0, x1 = 0.0, 128.0
    total_w = sum(s[1] for s in segs)
    total_p = sum(s[2] or 0 for s in segs)
    sum_days = total_w + total_p / cfg.day_min
    scale = (x1 - x0) / max(sum_days, 1e-9)
    x = x0
    px, py = [x], [y_hi]
    for _name, wait, proc in segs:
        xw = x + wait * scale
        px += [xw]
        py += [y_hi]
        if wait > 0.05:
            ax.text((x + xw) / 2, y_hi + 0.6, f"{wait:.1f} d", ha="center", fontsize=6.5,
                    color=INK)
        x = xw
        if proc:
            xp = x + proc / cfg.day_min * scale
            px += [x, xp, xp]
            py += [y_lo, y_lo, y_hi]
            ax.text((x + xp) / 2, y_lo - 1.6, f"{proc:.0f}", ha="center", fontsize=6.2,
                    color=INK)
            x = xp
    ax.plot(px, py, color=INK, lw=1.2)
    ax.text(0, y_hi + 2.6, "Critical coil path: waits / delays (working days, upper) and "
            "processing (min, lower)", fontsize=7.5, color=MUTED)
    ax.add_patch(Rectangle((130, -16.5), 21.5, 13.5, fc="white", ec=INK, lw=1))
    rows = [("Throughput", f"{data['th']:.2f} EVA/wk"),
            ("Order lead time", f"{data['lt_days']:.1f} d (P95 {data['p95']:.1f})"),
            ("Path sum (ladder)", f"{sum_days:.1f} d"),
            ("VA time / EVA", f"{data['va_min']:.0f} min"),
            ("VA ratio", f"{100 * data['va_ratio']:.1f} %"),
            ("WIP", f"{data['wip']:.1f} EVA"), ("On-time", f"{100 * data['on_time']:.1f} %")]
    if compare is not None:
        rows.insert(2, ("  vs S0 same demand", f"{data['lt_days'] - compare['lt_days']:+.1f} d"))
    for k, (a, b) in enumerate(rows):
        yy = -4.0 - k * 1.55
        ax.text(130.6, yy, a, fontsize=7.4, va="top", fontweight="bold" if k == 1 else "normal")
        ax.text(151.2, yy, b, fontsize=7.4, va="top", ha="right",
                fontweight="bold" if k == 1 else "normal")
    for kx, ky, t in kaizens:
        _kaizen(ax, kx, ky, t)
    dept_legend(ax, loc="lower left", bbox_to_anchor=(0.0, 0.135), fontsize=8)
    ax.text(-1.5, -16.6, "Inventory triangles: average EVA queuing in front of the process "
            "(throughput x mean queue time). Path sum excludes join waits and transfer-batch "
            "waits outside the coil path. Ops = operators (x stations).", fontsize=7, color=MUTED)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130)
    plt.close(fig)
    return path


def build(results_dir: Path, n: int, future: str = "S7", future_demand: float = 5.0,
          workers: int | None = None, out_dir: Path = DOCS_DIR) -> pd.DataFrame:
    """Draw vsm_current.png (S0 at baseline demand) and vsm_future.png (``future``)."""
    base = load_config()
    scen = load_scenarios(base)
    cur = collect(base, n, "S0 baseline", workers)
    ref = collect(with_demand(base, future_demand), n, f"S0 @ {future_demand:g}", workers)
    fut = collect(with_demand(scen[future].config, future_demand), n,
                  f"{future} {scen[future].name}", workers)
    draw(cur, "Current-state value stream map: evaporator production system",
         Path(out_dir) / "vsm_current.png")
    xB = {op: 18.5 + 13.0 * k for k, op in enumerate(COIL_PATH)}
    kz = []
    fcfg = scen[future].config
    if fcfg.resources["steeking_crew"]["crew"] > base.resources["steeking_crew"]["crew"]:
        kz.append((xB["steeking"] + 4.5, 51.5, "3rd\nsteeker"))
    if fcfg.resources["header_welder"]["servers"] > 1:
        kz.append((xB["header_welding"] + 4.5, 51.5, "2nd\nwelder"))
    if fcfg.transfer_batch == 1:
        kz.append((xB["weld_return_bends"] + 6.5, 51.5, "one-piece\nflow"))
    if fcfg.raw["release"]["rule"] == "conwip":
        kz.append((93, 79, "CONWIP"))
    draw(fut, f"Future-state value stream map: {future} {scen[future].name} at "
         f"{future_demand:g} EVA/week", Path(out_dir) / "vsm_future.png", kz, compare=ref)
    rows = []
    for lab, d in (("current", cur), ("S0 at future demand", ref), ("future", fut)):
        rows.append({"state": lab, "label": d["label"], "demand_eva_per_week": d["cfg"].demand,
                     "throughput_eva_week": d["th"], "order_lead_time_days": d["lt_days"],
                     "order_lead_time_p95_days": d["p95"], "eva_lead_time_days": d["eva_lt_days"],
                     "va_min_per_eva": d["va_min"], "va_ratio": d["va_ratio"], "wip_eva": d["wip"],
                     "on_time": d["on_time"],
                     "steeking_queue_h": d["procs"]["steeking"]["wq_min"] / 60,
                     "header_queue_h": d["procs"]["header_welding"]["wq_min"] / 60})
    df = pd.DataFrame(rows)
    df.round(4).to_csv(Path(results_dir) / "vsm_summary.csv", index=False)
    pd.DataFrame([{"state": lab, "process": k, **{kk: v for kk, v in p.items()
                                                   if not isinstance(v, str)}}
                  for lab, d in (("current", cur), ("future", fut))
                  for k, p in d["procs"].items()]).round(4).to_csv(
        Path(results_dir) / "vsm_data.csv", index=False)
    return df
