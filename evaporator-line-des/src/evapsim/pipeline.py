"""Analysis steps used by the CLI. Every step is seeded and writes to results/."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import equations as eq
from . import plots
from .config import DOCS_DIR, RESULTS_DIR, load_config


def out_dirs(quick: bool = False) -> tuple[Path, Path]:
    """Results and figure directories (results/quick/ in quick mode)."""
    out = RESULTS_DIR / "quick" if quick else RESULTS_DIR
    fig = out / "figures"
    fig.mkdir(parents=True, exist_ok=True)
    return out, fig


def log(msg: str) -> None:
    """Progress message."""
    print(f"[evapsim] {msg}", flush=True)


def step_handcalc() -> None:
    """Phase 1/2 analytical outputs: hand-calc VSM, loads, critical path, fin press."""
    cfg = load_config()
    out, fig = out_dirs()
    eq.hand_calc_vsm(cfg).round(4).to_csv(out / "vsm_hand_calc.csv", index=False)
    eq.resource_loads(cfg).round(4).to_csv(out / "resource_loads.csv", index=False)
    cp = eq.deterministic_lead_time(cfg)
    pd.DataFrame([cp]).round(3).to_csv(out / "deterministic_lead_time.csv", index=False)
    plots.process_flow_figure(DOCS_DIR / "process_flow.png",
                              cfg.raw["flags"]["wash_before_test"],
                              cfg.raw["flags"]["include_outsourced_coating"])
    log(f"hand calc: bottleneck {eq.bottleneck(cfg)}, single-order lead time "
        f"{cp['lead_time_min']:.0f} min = {cp['lead_time_days']:.2f} working days")


S4_PACKAGE = {"setup_min": 18.0, "mtbf_min": 540.0, "mttr_min": 10.0, "performance": 0.985,
              "quality": 0.99, "reload_min": 2.0}


def fin_press_options(cfg) -> pd.DataFrame:
    """OEE of the baseline, SMED-only, the theoretical cap and the S4 package (A23)."""
    base = dict(cfg.fin_press)

    def row(name: str, **kw: float) -> dict:
        p = {**base, **kw}
        r = eq.fin_press(**p)
        return {"case": name, "S": p["S"], "P": p["P"], "Q": p["Q"], "MTBF": p["MTBF"],
                "MTTR": p["MTTR"], "t_r": p["t_r"], "T_job_min": r.T_job,
                "min_per_eva": r.per_eva, "A_u": r.A_u, "A_tot": r.A_tot, "OEE": r.OEE}

    pk = S4_PACKAGE
    return pd.DataFrame([
        row("baseline (calibrated)"),
        row("SMED only: setup -40%", S=base["S"] * 0.6),
        row("cap: setup -40%, A_u = P = 1", S=base["S"] * 0.6, P=1.0, MTTR=1e-9),
        row("S4 package (SMED + TPM + quick reel change)", S=pk["setup_min"] * cfg.tsf,
            MTBF=pk["mtbf_min"] * cfg.tsf, MTTR=pk["mttr_min"] * cfg.tsf, P=pk["performance"],
            Q=pk["quality"], t_r=pk["reload_min"] * cfg.tsf),
    ])


def step_analytic() -> None:
    """Phase 2 outputs: fin-press calibration, OEE options, station metrics, Kingman table."""
    cfg = load_config()
    out, _ = out_dirs()
    fp = eq.fin_press(**cfg.fin_press)
    rec = eq.as_records(fp)
    rec["whiteboard_T_job_min"] = 229.0
    rec["whiteboard_OEE"] = 0.70
    rec["calibrated_F_from_A8"] = eq.calibrate_good_fins(0.70, cfg.fin_press["r_n"], 229.0,
                                                         cfg.lot)
    rec["F_used"] = cfg.fin_press["F"]
    rec["T_job_error_vs_whiteboard_pct"] = 100 * (fp.T_job / 229.0 - 1)
    pd.DataFrame([rec]).round(6).to_csv(out / "fin_press_calibration.csv", index=False)
    fin_press_options(cfg).round(5).to_csv(out / "fin_press_oee_options.csv", index=False)
    rows = []
    for op in ("weld_hairpins", "weld_return_bends", "expansion", "header_welding"):
        o = cfg.operations[op]
        m = eq.station_metrics(float(o["t_op_min"]) * cfg.tsf, float(o["n_ops"]),
                               float(o.get("handling_min", 0)) * cfg.tsf, cfg.op_crew(op),
                               cfg.demand, cfg.week_min, cfg.day_min,
                               parallel=int(cfg.resources[o["resource"]].get("servers", 1)))
        rows.append({"operation": op, "label": o["label"], **eq.as_records(m),
                     "ops_per_hour": 60 * m.ops_per_min, "min_per_lot": m.min_per_coil * cfg.lot,
                     "hours_per_lot": m.min_per_coil * cfg.lot / 60})
    pd.DataFrame(rows).round(4).to_csv(out / "station_metrics.csv", index=False)
    loads = eq.resource_loads(cfg).set_index("resource")
    krows = []
    ca2 = float(cfg.raw["demand"]["interarrival_cv"]) ** 2
    for d in cfg.raw["demand"]["sweep_eva_per_week"]:
        for res, op in (("steeking_crew", "steeking"), ("header_welder", "header_welding")):
            t_lot = cfg.op_mean_min(op) * cfg.lot
            cs2 = cfg.op_cv(op) ** 2 / cfg.lot  # lot of B independent EVA
            rho = d * loads.loc[res, "min_per_eva"] / cfg.week_min
            krows.append({"demand_eva_per_week": d, "resource": res, "t_e_lot_min": t_lot,
                          "ca2": ca2, "cs2": cs2, "rho": rho,
                          "kingman_wq_min": eq.kingman_wq(ca2, cs2, rho, t_lot)})
    pd.DataFrame(krows).round(4).to_csv(out / "kingman_analytic.csv", index=False)
    log(f"analytic: T_job {fp.T_job:.2f} min (whiteboard 229), OEE {fp.OEE:.4f}")
