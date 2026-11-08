"""Phase 7: scenario comparison at several demand levels with common random numbers.

All scenarios share the base seed, so replication ``r`` sees the same orders,
operation-time draws, delays and test outcomes in every scenario. Each
scenario is compared with S0 *at the same demand level* through paired
differences per replication (paired-t 95 % CI).
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import plots
from .config import Scenario, load_config, load_scenarios, with_demand
from .metrics import bottleneck_frequency, paired_difference, t_ci
from .runner import RunResult, resource_summary, run_replications

METRICS = ["throughput_eva_week", "lt_mean_days", "lt_p90_days", "lt_p95_days", "on_time",
           "wip_total", "weekly_compliance", "fpy_test", "va_ratio", "bottleneck_active"]


def run_scenarios(n: int, workers: int | None = None, log=print
                  ) -> tuple[dict[str, Scenario], dict[tuple[str, float], RunResult]]:
    """Run every scenario at every scenario demand level."""
    scen = load_scenarios()
    demands = load_config().raw["demand"]["scenario_eva_per_week"]
    runs = {}
    for d in demands:
        for sid, s in scen.items():
            runs[(sid, float(d))] = run_replications(with_demand(s.config, d), n, sid, workers)
            log(f"[evapsim] scenario {sid} @ {d:g} EVA/week done")
    return scen, runs


def summary_table(scen: dict[str, Scenario], runs: dict[tuple[str, float], RunResult]
                  ) -> pd.DataFrame:
    """Mean and 95 % CI of the key KPIs per scenario and demand."""
    rows = []
    for (sid, d), run in runs.items():
        r = {"scenario": sid, "name": scen[sid].name, "demand_eva_per_week": d,
             "replications": run.n}
        for m in METRICS:
            mean, h, _ = t_ci(run.reps[m])
            r[f"{m}_mean"], r[f"{m}_ci_low"], r[f"{m}_ci_high"] = mean, mean - h, mean + h
        bf = bottleneck_frequency(run.reps)
        r["bottleneck"] = bf.iloc[0]["resource"]
        r["bottleneck_share"] = float(bf.iloc[0]["share"])
        qb = bottleneck_frequency(run.reps, "queue_bottleneck")
        r["queue_bottleneck"] = qb.iloc[0]["resource"]
        rs = resource_summary(run).set_index("resource")
        r["steeking_util"] = float(rs.loc["steeking_crew", "busy"])
        r["header_util"] = float(rs.loc["header_welder", "busy"])
        r["unstable_backlog_end"] = float(run.reps["in_system_end"].mean())
        rows.append(r)
    return pd.DataFrame(rows)


def paired_table(runs: dict[tuple[str, float], RunResult]) -> pd.DataFrame:
    """Paired differences of each scenario against S0 at the same demand."""
    rows = []
    for (sid, d), run in runs.items():
        if sid == "S0":
            continue
        base = runs[("S0", d)].reps.set_index("rep")
        alt = run.reps.set_index("rep").loc[base.index]
        for m in METRICS:
            rows.append({"scenario": sid, "demand_eva_per_week": d, "metric": m,
                         "baseline_mean": float(base[m].mean()),
                         "scenario_mean": float(alt[m].mean()),
                         **paired_difference(base[m].to_numpy(), alt[m].to_numpy())})
    return pd.DataFrame(rows)


def run_and_save(n: int, out: Path, fig: Path, workers: int | None = None, log=print
                 ) -> pd.DataFrame:
    """Run, then write the scenario tables and figures."""
    scen, runs = run_scenarios(n, workers, log)
    summary = summary_table(scen, runs)
    paired = paired_table(runs)
    res = pd.concat([resource_summary(r).assign(demand_eva_per_week=d)
                     for (_s, d), r in runs.items()], ignore_index=True)
    bf = pd.concat([bottleneck_frequency(r.reps).assign(scenario=s, demand_eva_per_week=d)
                    for (s, d), r in runs.items()], ignore_index=True)
    reps = pd.concat([r.reps.assign(demand_eva_per_week=d) for (_s, d), r in runs.items()],
                     ignore_index=True)
    summary.round(5).to_csv(out / "scenario_summary.csv", index=False)
    paired.round(5).to_csv(out / "scenario_paired_differences.csv", index=False)
    res.round(5).to_csv(out / "scenario_resources.csv", index=False)
    bf.round(4).to_csv(out / "scenario_bottleneck_frequency.csv", index=False)
    reps.round(5).to_csv(out / "scenario_replications.csv", index=False)
    pd.DataFrame([{"scenario": s.sid, "name": s.name, "description": s.description}
                  for s in scen.values()]).to_csv(out / "scenario_definitions.csv", index=False)
    plots.scenario_figure(summary, paired, fig / "scenario_comparison.png")
    plots.scenario_bottleneck_figure(bf, load_config(), fig / "scenario_bottlenecks.png")
    return summary
