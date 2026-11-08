"""Phase 7a - scenario comparison with common random numbers.

All scenarios use the same base seed, so replication *r* of every scenario
sees the same units (same models, cycle-time draws and quality outcomes) and
the same failure and changeover streams on each machine. Each improvement
is therefore judged on the same sequence of events. Paired differences
against S0 are tested with the paired-t method, and their 95 % confidence
intervals are reported.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import plots
from .config import Scenario, load_scenarios
from .metrics import bottleneck_frequency, paired_difference, t_ci
from .runner import RunResult, run_replications, station_summary

COMPARE_METRICS = [
    "throughput_per_day",
    "takt_compliance",
    "lt_mean_min",
    "lt_p95_min",
    "batch_lt_mean_min",
    "wip_avg",
    "bottleneck_util",
]


def run_scenarios(n_reps: int, ids: list[str] | None = None, workers: int | None = None,
                  progress=None) -> tuple[dict[str, Scenario], dict[str, RunResult]]:
    """Simulate the selected scenarios (all of them by default)."""
    scenarios = load_scenarios()
    ids = ids or list(scenarios)
    if "S0" not in ids:
        ids = ["S0", *ids]
    runs = {}
    for sid in ids:
        cb = progress(sid) if progress else None
        runs[sid] = run_replications(scenarios[sid].config, n_reps, label=sid, workers=workers,
                                     progress=cb)
    return scenarios, runs


def summary_table(scenarios: dict[str, Scenario], runs: dict[str, RunResult]) -> pd.DataFrame:
    """One row per scenario: mean and 95 % CI of the key KPIs and the bottleneck mode."""
    rows = []
    for sid, run in runs.items():
        cfg = run.config
        r = {"scenario": sid, "name": scenarios[sid].name, "replications": run.n}
        for m in COMPARE_METRICS:
            mean, h, _ = t_ci(run.reps[m])
            r[f"{m}_mean"] = mean
            r[f"{m}_ci_low"] = mean - h
            r[f"{m}_ci_high"] = mean + h
        r["attainment_pct"] = 100 * r["throughput_per_day_mean"] / cfg.demand_per_day
        bf = bottleneck_frequency(run.reps, cfg)
        top = bf.loc[bf["share"].idxmax()]
        r["bottleneck_station"] = int(top["station_id"])
        r["bottleneck_share"] = float(top["share"])
        r["demand_per_day"] = cfg.demand_per_day
        rows.append(r)
    return pd.DataFrame(rows)


def paired_table(runs: dict[str, RunResult], baseline: str = "S0") -> pd.DataFrame:
    """Paired differences of each scenario against the baseline, per metric."""
    base = runs[baseline].reps.set_index("rep")
    rows = []
    for sid, run in runs.items():
        if sid == baseline:
            continue
        alt = run.reps.set_index("rep").loc[base.index]
        for m in COMPARE_METRICS:
            d = paired_difference(base[m].to_numpy(), alt[m].to_numpy())
            rows.append({"scenario": sid, "metric": m,
                         "baseline_mean": float(base[m].mean()),
                         "scenario_mean": float(alt[m].mean()), **d})
    return pd.DataFrame(rows)


def run_and_save(n_reps: int, out: Path, fig: Path, ids: list[str] | None = None,
                 workers: int | None = None, progress=None) -> pd.DataFrame:
    """Run scenarios and write all scenario tables and figures; return the summary."""
    scenarios, runs = run_scenarios(n_reps, ids, workers, progress)
    summary = summary_table(scenarios, runs)
    paired = paired_table(runs)
    stations = pd.concat([station_summary(r) for r in runs.values()], ignore_index=True)
    bfreq = pd.concat([bottleneck_frequency(r.reps, r.config).assign(scenario=sid)
                       for sid, r in runs.items()], ignore_index=True)
    reps = pd.concat([r.reps for r in runs.values()], ignore_index=True)

    out.mkdir(parents=True, exist_ok=True)
    summary.round(5).to_csv(out / "scenario_summary.csv", index=False)
    paired.round(5).to_csv(out / "scenario_paired_differences.csv", index=False)
    stations.round(5).to_csv(out / "scenario_stations.csv", index=False)
    bfreq.round(4).to_csv(out / "scenario_bottleneck_frequency.csv", index=False)
    reps.round(5).to_csv(out / "scenario_replications.csv", index=False)
    pd.DataFrame([{"scenario": s.sid, "name": s.name, "description": s.description}
                  for s in scenarios.values() if s.sid in runs]).to_csv(
        out / "scenario_definitions.csv", index=False)

    plots.scenario_comparison_figure(summary, paired, fig / "scenario_comparison.png")
    plots.scenario_bottleneck_figure(bfreq, fig / "scenario_bottleneck_frequency.png")
    plots.scenario_states_figure(stations, fig / "scenario_station_4_states.png", station_id=4)
    return summary
