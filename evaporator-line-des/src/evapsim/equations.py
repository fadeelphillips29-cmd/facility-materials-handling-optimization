"""Analytical (hand-calculation) model of the evaporator production system.

These are the equations of the brief. They are used to (i) build the
hand-calculated VSM table, (ii) cross-check the simulation, and (iii) explain
the results. All times are working minutes.

A. Fin press (nominal rate r_n fins/min)
    A1  t_ideal = 1 / r_n                       (r_n = s * k strokes x fins/stroke)
    A2  F_g     = F / Q                         gross fins for F good fins
    A3  T_run   = F_g / (r_n * P)               run time per EVA
    A4  T_eva   = T_run / A_u + (F_g / R) * t_r with A_u = MTBF / (MTBF + MTTR)
    A5  T_job   = S + B * T_eva                 job (lot) time
    A6  OEE     = B * F * t_ideal / T_job = A_tot * P * Q,  A_tot = B * T_run / T_job
    A7  r_eff   = r_n * OEE,  N(t) = r_eff * t,  X = B / T_job  (EVA/min)
    A8  F       = OEE * r_n * T_job / B         (calibration)

B. Manual stations
    ops/min = 1 / t_op;  min/coil = n_ops * t_op + t_handling
    labour content = min/coil * operators
    capacity (EVA/shift) = 480 * availability / (min/coil) * parallel stations
    rho = lambda * t / (c * availability)
    crew stations: elapsed = labour / (crew * eta(crew))

C. System
    bottleneck = argmax_i (min/EVA_i / parallel capacity_i)  (load per resource)
    Little's law WIP = TH * LT;  Kingman Wq = ((ca^2 + cs^2)/2) * (rho/(1-rho)) * t_e
    VA ratio = sum(value-added time) / total lead time
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import pandas as pd

from .config import LineConfig

# ============================================================== A. fin press


@dataclass(frozen=True)
class FinPressResult:
    """All intermediate quantities of equations A1-A7."""

    t_ideal_min: float
    F_g: float
    T_run: float
    A_u: float
    reloads_per_eva: float
    T_eva: float
    T_job: float
    per_eva: float
    A_tot: float
    OEE: float
    OEE_check: float
    r_eff: float
    X_eva_per_min: float


def fin_press(r_n: float, F: float, S: float, P: float, Q: float, MTBF: float, MTTR: float,
              R: float, t_r: float, B: float, **_: float) -> FinPressResult:
    """Evaluate equations A1-A7 for one parameter set (extra keys are ignored)."""
    t_ideal = 1.0 / r_n                               # A1
    F_g = F / Q                                       # A2
    T_run = F_g / (r_n * P)                           # A3
    A_u = MTBF / (MTBF + MTTR)
    reloads = F_g / R
    T_eva = T_run / A_u + reloads * t_r               # A4
    T_job = S + B * T_eva                             # A5
    OEE = B * F * t_ideal / T_job                     # A6
    A_tot = B * T_run / T_job
    return FinPressResult(t_ideal, F_g, T_run, A_u, reloads, T_eva, T_job, T_job / B, A_tot,
                          OEE, A_tot * P * Q, r_n * OEE, B / T_job)


def good_fins(r_eff: float, t: float) -> float:
    """A7: good fins produced in time ``t`` after setup, N(t) = r_eff * t."""
    return r_eff * t


def calibrate_good_fins(oee: float, r_n: float, T_job: float, B: float) -> float:
    """A8: F = OEE * r_n * T_job / B."""
    return oee * r_n * T_job / B


def strokes_rate(strokes_per_min: float, fins_per_stroke: float) -> float:
    """A1: nominal rate r_n = s * k."""
    return strokes_per_min * fins_per_stroke


# ===================================================== B. manual stations


@dataclass(frozen=True)
class StationMetrics:
    """Metrics 1-3 of a manual weld/assembly station plus capacity and load."""

    t_op_min: float
    ops_per_min: float
    n_ops: float
    min_per_coil: float
    operators: int
    labour_min: float
    capacity_eva_per_shift: float
    capacity_eva_per_week: float
    utilisation: float


def station_metrics(t_op: float, n_ops: float, handling: float, operators: int,
                    demand_per_week: float, week_min: float, shift_min: float = 480.0,
                    availability: float = 1.0, parallel: int = 1) -> StationMetrics:
    """Metric 1 (t_op), metric 2 (n_ops, ops/min) and metric 3 (min/coil), plus capacity.

    rho = lambda * t / (c * availability), with lambda in EVA/min.
    """
    mpc = n_ops * t_op + handling
    lam = demand_per_week / week_min
    return StationMetrics(
        t_op_min=t_op, ops_per_min=1.0 / t_op if t_op else float("nan"), n_ops=n_ops,
        min_per_coil=mpc, operators=operators, labour_min=mpc * operators,
        capacity_eva_per_shift=shift_min * availability / mpc * parallel,
        capacity_eva_per_week=week_min * availability / mpc * parallel,
        utilisation=lam * mpc / (parallel * availability),
    )


def crew_elapsed(labour_min: float, crew: int, eta: float) -> float:
    """Elapsed time of a crew station: labour / (crew * eta(crew))."""
    return labour_min / (crew * eta)


# ================================================================ C. system


def littles_law_wip(throughput: float, lead_time: float) -> float:
    """Little's law: WIP = TH * LT (consistent units)."""
    return throughput * lead_time


def kingman_wq(ca2: float, cs2: float, rho: float, t_e: float) -> float:
    """Kingman (VUT) approximation of the mean queue time of a GI/G/1 station.

    Wq = ((ca^2 + cs^2) / 2) * (rho / (1 - rho)) * t_e. It returns ``inf`` for rho >= 1.
    """
    if rho >= 1:
        return float("inf")
    return (ca2 + cs2) / 2.0 * rho / (1.0 - rho) * t_e


def va_ratio(value_added_min: float, lead_time_min: float) -> float:
    """VSM value-added ratio."""
    return value_added_min / lead_time_min


# ---------------------------------------------------------- hand calculation
EVAPORATOR_ROUTE = ["steeking", "weld_return_bends", "expansion", "header_welding", "wash",
                    "pressure_test"]


def resource_loads(cfg: LineConfig) -> pd.DataFrame:
    """Load (min per EVA) and utilisation at demand of every resource.

    The shared fin-press/boxing operator is loaded with both activities. The
    pressure-test rework expectation (p x rework / (1 - p)) is added to the
    rework resource, and retests to the test bay, in the 'with rework' columns.
    """
    fp = fin_press(**cfg.fin_press)
    rw = cfg.raw["rework"]
    p = float(rw["fail_prob"])
    lam = cfg.demand / cfg.week_min
    rows = []
    for res, rdef in cfg.resources.items():
        servers = int(rdef.get("servers", 1))
        load = 0.0
        for op in cfg.resource_ops(res):
            load += fp.per_eva if op == "fin_press" else cfg.op_mean_min(op)
        extra = 0.0
        if res == rw["resource"]:
            extra += p / (1 - p) * float(rw["rework_min"]) * cfg.tsf
        if res == cfg.operations["pressure_test"]["resource"]:
            extra += p / (1 - p) * cfg.op_mean_min("pressure_test")
        rows.append({
            "resource": res, "label": cfg.resource_label(res), "servers": servers,
            "crew": int(rdef.get("crew", 1)), "operations": "+".join(cfg.resource_ops(res)),
            "min_per_eva": load, "min_per_eva_with_rework": load + extra,
            "capacity_eva_per_week": cfg.week_min * servers / load,
            "utilisation_at_demand": lam * load / servers,
            "utilisation_with_rework": lam * (load + extra) / servers,
        })
    df = pd.DataFrame(rows).sort_values("utilisation_at_demand", ascending=False)
    df["rank"] = range(1, len(df) + 1)
    return df.reset_index(drop=True)


def bottleneck(cfg: LineConfig) -> str:
    """Resource with the highest load per parallel server (C: argmax min/EVA / capacity)."""
    return str(resource_loads(cfg).iloc[0]["resource"])


def hand_calc_vsm(cfg: LineConfig) -> pd.DataFrame:
    """Deterministic hand-calculated VSM table (one row per process step).

    Columns: per-EVA minutes, per-lot minutes, operators, labour content,
    weld metrics where relevant, capacity per shift and week, and utilisation
    at demand of the performing resource (shared operators are loaded with all
    their activities). Calendar delays are listed with their lead time.
    """
    fp = fin_press(**cfg.fin_press)
    loads = resource_loads(cfg).set_index("resource")
    B = cfg.lot
    rows = [{
        "step": 3, "station": "fin_press", "label": "Fin Press (setup + punching)",
        "department": "evaporator", "source": cfg.raw["fin_press"]["source"],
        "resource": cfg.raw["fin_press"]["resource"], "operators": 1,
        "per_eva_min": fp.per_eva, "per_lot_min": fp.T_job, "labour_min_per_eva": fp.per_eva,
        "t_op_min": fp.t_ideal_min, "n_ops": cfg.fin_press["F"],
        "ops_per_min": cfg.fin_press["r_n"],
        "oee": fp.OEE, "seq": 0.0,
    }]
    for k, (op, o) in enumerate(cfg.operations.items()):
        res = o["resource"]
        rdef = cfg.resources[res]
        rows.append({
            "step": o["step"], "station": op, "label": o["label"], "department": o["department"],
            "source": o["source"], "resource": res,
            "operators": int(rdef.get("crew", 1)) * int(rdef.get("servers", 1)),
            "per_eva_min": cfg.op_mean_min(op), "per_lot_min": B * cfg.op_mean_min(op),
            "labour_min_per_eva": cfg.op_labour_min(op),
            "t_op_min": float(o["t_op_min"]) * cfg.tsf if "t_op_min" in o else float("nan"),
            "n_ops": float(o["n_ops"]) if "n_ops" in o else float("nan"),
            "ops_per_min": 1 / (float(o["t_op_min"]) * cfg.tsf) if "t_op_min" in o
            else float("nan"),
            "oee": float("nan"), "seq": float(k + 1),
        })
    df = pd.DataFrame(rows)
    servers = df["resource"].map(lambda r: int(cfg.resources[r].get("servers", 1)))
    df["capacity_eva_per_shift"] = cfg.day_min / df["per_eva_min"] * servers
    df["capacity_eva_per_week"] = cfg.week_min / df["per_eva_min"] * servers
    df["station_utilisation_at_demand"] = cfg.demand / df["capacity_eva_per_week"]
    df["resource_utilisation_at_demand"] = df["resource"].map(loads["utilisation_at_demand"])
    top = loads.index[0]
    df["is_bottleneck_resource"] = df["resource"] == top
    delays = []
    for key, lt in cfg.raw["lead_times"].items():
        if key == "coating" and not cfg.raw["flags"]["include_outsourced_coating"]:
            continue
        delays.append({
            "step": {"engineering_release": 1, "procurement_sheet_metal": 2,
                     "procurement_tubing": 2, "drip_tray_external": 14, "coating": 15}[key],
            "station": key, "label": lt["label"], "department": lt["department"],
            "source": lt["source"], "resource": "(calendar delay)", "operators": 0,
            "per_eva_min": float("nan"), "per_lot_min": cfg.lead_time_mean_min(key),
            "lead_time_days": float(lt["mean_days"]),
            "seq": {"engineering_release": 0, "procurement_sheet_metal": 0,
                    "procurement_tubing": 0.5, "drip_tray_external": -1, "coating": -1}[key],
        })
    out = pd.concat([df, pd.DataFrame(delays)], ignore_index=True)
    out = out.sort_values(["step", "seq"], kind="stable").reset_index(drop=True)
    return out.drop(columns="seq")


# -------------------------------------------------------- critical path (CP)
def _flow(starts_ready: list[float], t: float, free_at: float, tb: int) -> tuple[list[float],
                                                                                 float]:
    """Process EVAs one by one on a single server; return transfer-batch release times.

    ``starts_ready[i]`` is when EVA i becomes available at the station. Units
    are processed in index order; the downstream availability of each unit
    is the completion time of the last unit of its transfer batch.
    """
    done = []
    t_free = free_at
    for r in starts_ready:
        start = max(r, t_free)
        t_free = start + t
        done.append(t_free)
    out = []
    for i in range(len(done)):
        g_end = min(len(done), (i // tb + 1) * tb) - 1
        out.append(done[g_end])
    return out, t_free


def deterministic_lead_time(cfg: LineConfig) -> dict[str, float]:
    """Critical-path lead time of ONE work order through the empty system (zero variance).

    This is an independent hand calculation (no SimPy), used to verify the
    deterministic simulation. It uses mean delays, the fin-press job time T_job,
    the operation means and the transfer batch. It assumes no test failures and
    that a shared resource is never needed by two activities at the same time.
    That holds for a single order, and the function checks it.
    """
    B, tb = cfg.lot, cfg.transfer_batch
    fp = fin_press(**cfg.fin_press)
    lt = cfg.lead_time_mean_min
    m = cfg.op_mean_min
    t_rel = lt("engineering_release")
    t_tube = t_rel + lt("procurement_tubing")
    t_sheet = t_rel + lt("procurement_sheet_metal")
    # fin press job: setup then punch B EVA (deterministic T_eva each)
    fins_done = [t_rel + cfg.fin_press["S"] + (i + 1) * fp.T_eva for i in range(B)]
    fins_avail = [fins_done[min(B, (i // tb + 1) * tb) - 1] for i in range(B)]
    fp_free = fins_done[-1]
    # boxing (same operator): after its fin pack and tubing
    boxed, _ = _flow([max(fins_done[i], t_tube) for i in range(B)], m("boxing"),
                            fp_free, tb)
    trimmed, _ = _flow([t_tube] * B, m("trim_tubes"), 0.0, tb)
    circuits, _ = _flow(trimmed, m("weld_hairpins"), 0.0, tb)
    headers, _ = _flow([t_tube] * B, m("prepare_headers"), 0.0, tb)
    ready = [max(fins_avail[i], boxed[i], circuits[i]) for i in range(B)]
    steeked, _ = _flow(ready, m("steeking"), 0.0, tb)
    rb, _ = _flow(steeked, m("weld_return_bends"), 0.0, tb)
    ex, _ = _flow(rb, m("expansion"), 0.0, tb)
    hw, _ = _flow([max(ex[i], headers[i]) for i in range(B)], m("header_welding"), 0.0, tb)
    order = ["wash", "pressure_test"] if cfg.raw["flags"]["wash_before_test"] else [
        "pressure_test", "wash"]
    x = hw
    for op in order:
        x, _ = _flow(x, m(op), 0.0, tb)
    coil_ready = x
    if cfg.raw["flags"]["include_outsourced_coating"]:
        # coating is sent out per transfer batch and returns after the lead time
        coil_ready = [v + lt("coating") for v in x]
    pb, _ = _flow([t_sheet] * B, m("press_brake"), 0.0, tb)
    fw, _ = _flow(pb, m("flat_welding"), 0.0, tb)
    pa, sma_free = _flow(fw, m("plenum_assembly"), 0.0, tb)
    ext = [t_sheet + lt("drip_tray_external")] * B
    dw, _ = _flow(ext, m("drip_tray_weld"), 0.0, tb)
    da, _ = _flow(dw, m("drip_tray_assembly"), sma_free, tb)
    if min(dw) < sma_free:
        raise ValueError("shared sheet-metal assembler overlap: CP formula not valid")
    ca, end = _flow([max(coil_ready[i], pa[i], da[i]) for i in range(B)],
                    m("complete_assembly"), 0.0, tb)
    va = sum(cfg.op_mean_min(op) for op in cfg.operations) + fp.per_eva
    return {"lead_time_min": end, "lead_time_days": end / cfg.day_min,
            "lead_time_weeks": end / cfg.week_min, "drawing_release": t_rel,
            "tubing_arrival": t_tube, "sheet_arrival": t_sheet, "fins_done": fins_done[-1],
            "steeking_ready": min(ready),
            "steeking_done": max(steeked), "header_welding_done": max(hw),
            "coil_ready": max(coil_ready), "plenum_ready": max(pa), "drip_tray_ready": max(da),
            "va_min_per_eva": va, "va_ratio": va / end}


def as_records(obj: FinPressResult | StationMetrics) -> dict[str, float]:
    """Dataclass result as a plain dict (for CSV export)."""
    return asdict(obj)
