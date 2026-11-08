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


# ================================================================= Monte Carlo
import json  # noqa: E402
import time  # noqa: E402

import numpy as np  # noqa: E402

from .config import LineConfig, apply_overrides, with_demand  # noqa: E402
from .metrics import (  # noqa: E402
    bottleneck_frequency,
    summarize,
    variance_decomposition,
)
from .runner import (  # noqa: E402
    LT_BINS_DAYS,
    RunResult,
    activity_summary,
    convergence_table,
    required_replications,
    resource_summary,
    run_replications,
)


def n_reps(cfg: LineConfig, quick: bool, override: int | None = None,
           kind: str = "replications") -> int:
    """Replication count for a step (explicit override > quick > config)."""
    if override:
        return int(override)
    sim = cfg.raw["simulation"]
    if quick:
        return int(sim["quick_replications"]) if kind == "replications" else max(
            10, int(sim["quick_replications"]) // 2)
    return int(sim[kind])


def progress(label: str):
    """Throttled progress callback."""
    st = {"t0": time.time(), "last": 0.0}

    def cb(done: int, total: int) -> None:
        now = time.time()
        if done == total or now - st["last"] > 15:
            st["last"] = now
            log(f"{label}: {done}/{total} replications ({now - st['t0']:.0f} s)")
    return cb


def write_meta(out: Path, step: str, info: dict) -> None:
    """Record replications and seed of each step in run_metadata.json."""
    p = out / "run_metadata.json"
    meta = json.loads(p.read_text()) if p.exists() else {}
    meta[step] = info
    p.write_text(json.dumps(meta, indent=2, sort_keys=True))


def save_run_tables(run: RunResult, out: Path, prefix: str) -> None:
    """Standard tables of one run."""
    run.reps.round(5).to_csv(out / f"{prefix}_replications.csv", index=False)
    summarize(run.reps).round(5).to_csv(out / f"{prefix}_kpis.csv", index=False)
    resource_summary(run).round(5).to_csv(out / f"{prefix}_resources.csv", index=False)
    activity_summary(run).round(5).to_csv(out / f"{prefix}_stations.csv", index=False)
    bf = bottleneck_frequency(run.reps).assign(method="highest active share")
    bq = bottleneck_frequency(run.reps, "queue_bottleneck").assign(method="longest mean queue")
    pd.concat([bf, bq]).round(4).to_csv(out / f"{prefix}_bottleneck_frequency.csv", index=False)
    wip = run.reps[[c for c in run.reps.columns if c.startswith("wip_")]].mean()
    wip.rename("mean_eva").to_frame().round(4).to_csv(out / f"{prefix}_wip_by_stage.csv")
    pd.DataFrame({"bin_low_days": LT_BINS_DAYS[:-1], "bin_high_days": LT_BINS_DAYS[1:],
                  "orders": run.lt_hist[:-1]}).to_csv(out / f"{prefix}_lead_time_hist.csv",
                                                       index=False)
    run.weekly.to_csv(out / f"{prefix}_weekly_output.csv", index=False)


def step_baseline(quick: bool = False, reps: int | None = None,
                  workers: int | None = None) -> RunResult:
    """Baseline Monte Carlo run (S0 at baseline demand) + convergence analysis."""
    cfg = load_config()
    out, fig = out_dirs(quick)
    n = n_reps(cfg, quick, reps)
    t0 = time.time()
    run = run_replications(cfg, n, "S0", workers, progress=progress("baseline"))
    save_run_tables(run, out, "baseline")
    conv = pd.concat([convergence_table(run.reps[m].to_numpy(), m)
                      for m in ("lt_mean_days", "lt_p90_days", "throughput_eva_week")])
    conv.round(5).to_csv(out / "convergence.csv", index=False)
    pd.DataFrame([{"metric": m, "target_rel_half_width_pct": p,
                   "required_replications": required_replications(run.reps[m].to_numpy(),
                                                                  p / 100),
                   "replications_run": run.n,
                   "achieved_rel_half_width_pct": float(
                       conv[(conv.metric == m) & (conv.n == run.n)]["rel_half_width_pct"].iloc[0])}
                  for m in ("lt_mean_days", "lt_p90_days", "throughput_eva_week")
                  for p in (0.5, 1.0, 2.0)]).round(4).to_csv(
        out / "convergence_required_replications.csv", index=False)
    plots.convergence_figure(conv, 1.0, "Convergence of baseline estimates with replications",
                             fig / "convergence.png")
    rs = resource_summary(run)
    plots.state_bars(rs, "Baseline resource states (3 EVA/week, mean of replications)",
                     fig / "baseline_resource_states.png")
    plots.utilisation_vs_handcalc(rs, eq.resource_loads(cfg), plots.resource_dept(cfg),
                                  "Simulated utilisation vs hand calculation (baseline)",
                                  fig / "baseline_utilisation_vs_handcalc.png")
    plots.lead_time_hist({"S0 baseline (3 EVA/week)": run.lt_hist}, LT_BINS_DAYS,
                         "Baseline order lead-time distribution (pooled orders)",
                         fig / "baseline_lead_time.png",
                         due_days=cfg.raw["demand"]["due_date_weeks"]
                         * cfg.raw["calendar"]["days_per_week"])
    write_meta(out, "baseline", {"replications": n, "base_seed":
                                 cfg.raw["simulation"]["base_seed"],
                                 "runtime_s": round(time.time() - t0, 1)})
    k = summarize(run.reps).set_index("metric")
    log(f"baseline: TH {k.loc['throughput_eva_week', 'mean']:.3f} EVA/week, LT "
        f"{k.loc['lt_mean_days', 'mean']:.2f} d (P95 {k.loc['lt_p95_days', 'mean']:.2f}), "
        f"on-time {k.loc['on_time', 'mean']:.3f}; {time.time() - t0:.0f} s")
    return run


def step_uncertainty(quick: bool = False, workers: int | None = None) -> None:
    """Two-level Monte Carlo: nested variance decomposition, full two-level run, cases."""
    cfg = load_config()
    out, fig = out_dirs(quick)
    iu = cfg.raw["input_uncertainty"]
    n_out = max(8, int(iu["outer_samples"]) // (4 if quick else 1))
    n_in = int(iu["inner_replications"])
    lo, mode, hi = iu["steeking_triangular_min"]
    rng = np.random.Generator(np.random.PCG64(np.random.SeedSequence(
        cfg.raw["simulation"]["base_seed"], spawn_key=(99999,))))
    outer = rng.triangular(lo, mode, hi, n_out)
    thetas = np.repeat(outer, n_in)
    rows, dec = [], []
    for d in cfg.raw["demand"]["scenario_eva_per_week"]:
        run = run_replications(with_demand(cfg, d), n_out * n_in, f"nested@{d}", workers,
                               thetas=thetas, progress=progress(f"nested design @ {d} EVA/wk"))
        r = run.reps.assign(outer=np.repeat(np.arange(n_out), n_in), demand=d)
        rows.append(r)
        for m in ("lt_mean_days", "lt_p90_days", "throughput_eva_week"):
            dec.append({"demand_eva_per_week": d, "metric": m,
                        **variance_decomposition(r[m].to_numpy(), r["outer"].to_numpy())})
    pd.concat(rows).round(5).to_csv(out / "uncertainty_nested_replications.csv", index=False)
    pd.DataFrame(dec).round(6).to_csv(out / "variance_decomposition.csv", index=False)
    bottleneck_under_uncertainty(out, fig)

    n = n_reps(cfg, quick)
    two = apply_overrides(cfg, {"input_uncertainty": {"enabled": True}})
    summ = []
    hists = {}
    for d in cfg.raw["demand"]["scenario_eva_per_week"]:
        r1 = run_replications(with_demand(cfg, d), n, f"single@{d}", workers)
        r2 = run_replications(with_demand(two, d), n, f"two-level@{d}", workers,
                              progress=progress(f"two-level @ {d} EVA/wk"))
        for lab, rr in (("process variability only (steeking 420)", r1),
                        ("two-level (steeking ~ tri(360,420,600))", r2)):
            s = summarize(rr.reps).set_index("metric")
            summ.append({"demand_eva_per_week": d, "model": lab,
                         **{f"{m}_{k}": s.loc[m, k] for m in ("lt_mean_days", "lt_p95_days",
                                                              "throughput_eva_week", "on_time")
                            for k in ("mean", "sd")},
                         "steeking_util_mean": float(rr.resources[
                             rr.resources.resource == "steeking_crew"]["busy"].mean())})
            hists[f"{lab.split(' (')[0]} @ {d:g} EVA/wk"] = rr.lt_hist
        if d == cfg.raw["demand"]["scenario_eva_per_week"][-1]:
            r2.reps[["rep", "theta_steeking", "lt_mean_days", "throughput_eva_week"]].round(4) \
                .to_csv(out / "uncertainty_theta_vs_lt.csv", index=False)
    pd.DataFrame(summ).round(5).to_csv(out / "uncertainty_two_level_summary.csv", index=False)
    plots.lead_time_hist(hists, LT_BINS_DAYS,
                         "Order lead time: process variability only vs two-level Monte Carlo",
                         fig / "uncertainty_lead_time.png",
                         due_days=cfg.raw["demand"]["due_date_weeks"] * 5)
    cases = []
    ns = n_reps(cfg, quick, kind="sensitivity_replications")
    for h in iu["steeking_cases_hours"]:
        theta = float(h) * 60.0
        rr = run_replications(cfg, ns, f"steek {h} h", workers, thetas=[theta] * ns)
        s = summarize(rr.reps).set_index("metric")
        util = float(rr.resources[rr.resources.resource == "steeking_crew"]["busy"].mean())
        cases.append({"steeking_hours_per_eva": h, "steeking_min_per_eva": theta,
                      "steeking_capacity_eva_week": cfg.week_min / (theta * cfg.tsf),
                      "demand_eva_per_week": cfg.demand,
                      "throughput_eva_week": s.loc["throughput_eva_week", "mean"],
                      "lt_mean_days": s.loc["lt_mean_days", "mean"],
                      "lt_p95_days": s.loc["lt_p95_days", "mean"],
                      "on_time": s.loc["on_time", "mean"], "steeking_utilisation": util,
                      "eva_in_system_at_end": float(rr.reps["in_system_end"].mean()),
                      "stable": bool(cfg.week_min / (theta * cfg.tsf) > cfg.demand)})
        log(f"steeking case {h} h: TH {cases[-1]['throughput_eva_week']:.2f}, LT "
            f"{cases[-1]['lt_mean_days']:.1f} d")
    pd.DataFrame(cases).round(4).to_csv(out / "steeking_cases.csv", index=False)
    write_meta(out, "uncertainty", {"outer": n_out, "inner": n_in, "two_level_reps": n,
                                    "case_reps": ns})


def step_validate(quick: bool = False, workers: int | None = None) -> None:
    """Phase 6: validation vs observed data + Kingman cross-check."""
    from .validation import calibration_grid, kingman_check, run_validation

    cfg = load_config()
    out, fig = out_dirs(quick)
    n = n_reps(cfg, quick)
    s = run_validation(out, fig, n, workers, cfg)
    log("validation:\n" + s[["measure", "observed_mean", "simulated_mean", "error_pct",
                             "prediction_interval_p", "verdict"]].round(3).to_string(index=False))
    k = kingman_check(cfg, [3.0, 4.0, 5.0, 5.5], reps=10 if quick else 30)
    k.round(4).to_csv(out / "kingman_check.csv", index=False)
    grid = calibration_grid(cfg, n, workers)
    grid.round(5).to_csv(out / "calibration_grid.csv", index=False)
    sel = grid[grid["selected_min_change"]]
    log(f"calibration: min-change value {float(sel['value'].iloc[0]) if len(sel) else 'none'}, "
        f"best fit {float(grid[grid['best_fit']]['value'].iloc[0])}")
    write_meta(out, "validate", {"replications": n})


def step_scenarios(quick: bool = False, reps: int | None = None,
                   workers: int | None = None) -> None:
    """Phase 7: scenarios S0-S6 at each scenario demand level."""
    from .scenarios import run_and_save

    cfg = load_config()
    out, fig = out_dirs(quick)
    n = n_reps(cfg, quick, reps)
    t0 = time.time()
    run_and_save(n, out, fig, workers, log=print)
    write_meta(out, "scenarios", {"replications": n, "runtime_s": round(time.time() - t0, 1)})


def step_sweep(quick: bool = False, reps: int | None = None,
               workers: int | None = None) -> None:
    """Phase 7: demand sweep (hockey stick)."""
    from .sensitivity import demand_sweep

    cfg = load_config()
    out, fig = out_dirs(quick)
    n = n_reps(cfg, quick, reps, kind="sensitivity_replications")
    demand_sweep(n, out, fig, workers, log=print)
    write_meta(out, "sweep", {"replications": n})


def step_sensitivity(quick: bool = False, reps: int | None = None,
                     workers: int | None = None) -> None:
    """Phase 7: one-at-a-time sensitivity + distribution-family robustness."""
    from .sensitivity import run_sensitivity

    cfg = load_config()
    out, fig = out_dirs(quick)
    n = n_reps(cfg, quick, reps, kind="sensitivity_replications")
    run_sensitivity(n, out, fig, workers, log=print)
    write_meta(out, "sensitivity", {"replications": n})


def step_vsm(quick: bool = False, reps: int | None = None, workers: int | None = None) -> None:
    """Phase 8: current/future-state VSM diagrams (docs/vsm_*.png)."""
    from .vsm import build

    cfg = load_config()
    out, fig = out_dirs(quick)
    n = n_reps(cfg, quick, reps)
    target = DOCS_DIR if not quick else fig
    df = build(out, n, workers=workers, out_dir=target)
    log("vsm:\n" + df[["state", "order_lead_time_days", "va_ratio"]].round(3)
        .to_string(index=False))


def bottleneck_under_uncertainty(out: Path, fig: Path) -> pd.DataFrame:
    """Bottleneck frequency vs the sampled steeking mean (from the nested design)."""
    cfg = load_config()
    d = pd.read_csv(out / "uncertainty_nested_replications.csv")
    t = d.groupby(["demand", "outer"]).agg(
        theta_steeking=("theta_steeking", "first"),
        share_header_bottleneck=("bottleneck", lambda x: float((x == "header_welder").mean()))
    ).reset_index().rename(columns={"demand": "demand_eva_per_week"})
    loads = eq.resource_loads(cfg).set_index("resource")
    switch = float(loads.loc["header_welder", "min_per_eva_with_rework"]) / cfg.tsf
    t["analytic_switch_min"] = switch
    t.round(5).to_csv(out / "uncertainty_bottleneck.csv", index=False)
    plots.bottleneck_vs_theta(t, switch, fig / "uncertainty_bottleneck.png")
    return t
