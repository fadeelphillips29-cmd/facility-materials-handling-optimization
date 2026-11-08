"""Phase 7: demand sweep (the lead-time 'hockey stick') and one-at-a-time sensitivity.

Sensitivity factors: every operation's mean time, the fin-press setup, MTBF
and MTTR (each ±10 %), the steeking crew (2 ± 1 operators), and, beyond the
brief, the engineering, procurement and outsourcing lead times (±10 %). The response
is the mean order lead time, paired against the baseline at the same demand
(CRN, 95 % CI). A robustness run also swaps the steeking distribution family
from Weibull to lognormal.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import equations as eq
from . import plots
from .config import LineConfig, apply_overrides, load_config, load_scenarios, with_demand
from .metrics import paired_difference, summarize
from .runner import resource_summary, run_replications

STEP = 0.10
SWEEP_SCENARIOS = ("S0", "S1", "S3", "S6", "S7")


def demand_sweep(n: int, out: Path, fig: Path, workers: int | None = None, log=print
                 ) -> pd.DataFrame:
    """Lead time, throughput and utilisation versus demand for selected scenarios."""
    base = load_config()
    scen = load_scenarios(base)
    rows = []
    for sid in SWEEP_SCENARIOS:
        for d in base.raw["demand"]["sweep_eva_per_week"]:
            run = run_replications(with_demand(scen[sid].config, d), n, sid, workers)
            s = summarize(run.reps).set_index("metric")
            rs = resource_summary(run).set_index("resource")
            rows.append({
                "scenario": sid, "name": scen[sid].name, "demand_eva_per_week": d,
                **{f"{m}_{k}": s.loc[m, k] for m in ("throughput_eva_week", "lt_mean_days",
                                                     "lt_p90_days", "lt_p95_days", "on_time",
                                                     "wip_total")
                   for k in ("mean", "ci_low", "ci_high")},
                "steeking_util": float(rs.loc["steeking_crew", "busy"]),
                "header_util": float(rs.loc["header_welder", "busy"]),
                "bottleneck": run.reps["bottleneck"].mode().iloc[0],
                "eva_in_system_end": float(run.reps["in_system_end"].mean()),
            })
            log(f"[evapsim] sweep {sid} @ {d:g}: LT {rows[-1]['lt_mean_days_mean']:.1f} d")
    df = pd.DataFrame(rows)
    df.round(5).to_csv(out / "demand_sweep.csv", index=False)
    plots.demand_curve(df, base, fig / "demand_curve.png")
    return df


def factors(cfg: LineConfig) -> list[tuple[str, str, dict, dict]]:
    """(key, label, low overrides, high overrides) for every OAT factor."""
    out = []
    for op, o in cfg.operations.items():
        field = "t_op_min" if "t_op_min" in o else "mean_min"
        out.append((op, f"{o['label']} time",
                    {"operations": {op: {field: {"scale": 1 - STEP}}}},
                    {"operations": {op: {field: {"scale": 1 + STEP}}}}))
    for k, lab in (("setup_min", "Fin press setup"), ("mtbf_min", "Fin press MTBF"),
                   ("mttr_min", "Fin press MTTR")):
        out.append((f"fin_press.{k}", lab, {"fin_press": {k: {"scale": 1 - STEP}}},
                    {"fin_press": {k: {"scale": 1 + STEP}}}))
    for k, lt in cfg.raw["lead_times"].items():
        out.append((f"lead_times.{k}", f"{lt['label']} lead time",
                    {"lead_times": {k: {"mean_days": {"scale": 1 - STEP}}}},
                    {"lead_times": {k: {"mean_days": {"scale": 1 + STEP}}}}))
    crew = int(cfg.resources["steeking_crew"]["crew"])
    out.append(("steeking_crew", f"Steeking crew ({crew} ± 1)",
                {"resources": {"steeking_crew": {"crew": crew - 1}}},
                {"resources": {"steeking_crew": {"crew": crew + 1}}}))
    return out


def run_sensitivity(n: int, out: Path, fig: Path, workers: int | None = None, log=print
                    ) -> pd.DataFrame:
    """One-at-a-time design at each scenario demand level, plus the family robustness run."""
    base = load_config()
    rows = []
    for d in base.raw["demand"]["scenario_eva_per_week"]:
        b = with_demand(base, d)
        ref = run_replications(b, n, "base", workers).reps
        for key, label, lo, hi in factors(base):
            for level, ov in (("low", lo), ("high", hi)):
                pc = apply_overrides(b, ov)
                reps = run_replications(pc, n, key, workers).reps
                peak = float(eq.resource_loads(pc)["utilisation_with_rework"].max())
                dlt = paired_difference(ref["lt_mean_days"].to_numpy(),
                                        reps["lt_mean_days"].to_numpy())
                dth = paired_difference(ref["throughput_eva_week"].to_numpy(),
                                        reps["throughput_eva_week"].to_numpy())
                rows.append({"demand_eva_per_week": d, "factor": key, "label": label,
                             "level": level, "lt_base_days": float(ref["lt_mean_days"].mean()),
                             "lt_days": float(reps["lt_mean_days"].mean()),
                             "lt_diff": dlt["diff_mean"], "lt_ci_low": dlt["diff_ci_low"],
                             "lt_ci_high": dlt["diff_ci_high"], "lt_rel_pct": dlt["rel_change_pct"],
                             "lt_significant": dlt["significant"], "th_diff": dth["diff_mean"],
                             "max_resource_load": peak, "unstable": peak >= 1.0})
        log(f"[evapsim] sensitivity @ {d:g} EVA/week done")
    df = pd.DataFrame(rows)
    sw = df.pivot_table(index=["demand_eva_per_week", "factor"], columns="level",
                        values="lt_diff")
    sw["swing"] = (sw["high"] - sw["low"]).abs()
    df["swing"] = [sw.loc[(r.demand_eva_per_week, r.factor), "swing"] for r in df.itertuples()]
    df = df.sort_values(["demand_eva_per_week", "swing", "factor", "level"],
                        ascending=[True, False, True, True])
    df.round(5).to_csv(out / "sensitivity_oat.csv", index=False)
    plots.tornado(df, fig / "sensitivity_tornado.png", n)

    fam = []
    for d in base.raw["demand"]["scenario_eva_per_week"]:
        b = with_demand(base, d)
        ref = run_replications(b, n, "weibull", workers).reps
        alt = run_replications(apply_overrides(b, {"operations": {"steeking": {
            "distribution": "lognormal"}}}), n, "lognormal", workers).reps
        for m in ("lt_mean_days", "lt_p95_days", "throughput_eva_week"):
            fam.append({"demand_eva_per_week": d, "metric": m,
                        "weibull_mean": float(ref[m].mean()),
                        "lognormal_mean": float(alt[m].mean()),
                        **paired_difference(ref[m].to_numpy(), alt[m].to_numpy())})
    pd.DataFrame(fam).round(5).to_csv(out / "distribution_robustness.csv", index=False)
    return df
