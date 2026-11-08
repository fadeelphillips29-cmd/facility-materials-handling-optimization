"""End-to-end analysis steps used by the CLI (``python -m evapsim <step>``).

Each step reads the configuration, runs what it needs and writes CSV tables to
``results/`` (or ``results/quick/`` in quick mode) and figures to
``<results>/figures/``. Steps are idempotent and fully seeded.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np
import pandas as pd

from . import plots
from .config import RESULTS_DIR, LineConfig, load_config
from .metrics import bottleneck_frequency, summarize
from .runner import (
    LT_BIN_EDGES,
    RunResult,
    convergence_table,
    required_replications,
    run_replications,
    save_run,
    station_summary,
)

CONVERGENCE_TARGET_PCT = 1.0


def out_dirs(quick: bool) -> tuple[Path, Path]:
    """Results and figure directories for the chosen mode."""
    out = RESULTS_DIR / "quick" if quick else RESULTS_DIR
    fig = out / "figures"
    fig.mkdir(parents=True, exist_ok=True)
    return out, fig


def n_reps(cfg: LineConfig, quick: bool, override: int | None = None) -> int:
    """Replication count: explicit override, else quick or full setting."""
    if override:
        return int(override)
    return cfg.sim.quick_replications if quick else cfg.sim.replications


def _log(msg: str) -> None:
    print(f"[evapsim] {msg}", flush=True)


def _progress(label: str):
    state = {"t0": time.time(), "last": 0.0}

    def cb(done: int, total: int) -> None:
        now = time.time()
        if done == total or now - state["last"] > 10:
            state["last"] = now
            _log(f"{label}: {done}/{total} replications ({now - state['t0']:.0f} s)")

    return cb


def write_meta(out: Path, step: str, info: dict) -> None:
    """Record run metadata (replications, seed, runtime) for traceability."""
    path = out / "run_metadata.json"
    meta = json.loads(path.read_text()) if path.exists() else {}
    meta[step] = info
    path.write_text(json.dumps(meta, indent=2, sort_keys=True))


def baseline_outputs(run: RunResult, out: Path, fig: Path, prefix: str = "baseline") -> None:
    """Write KPI summary, bottleneck frequency and baseline figures for one run."""
    cfg = run.config
    save_run(run, out, prefix)
    summarize(run.reps).round(5).to_csv(out / f"{prefix}_kpis.csv", index=False)
    bf = bottleneck_frequency(run.reps, cfg)
    bf_alt = bottleneck_frequency(run.reps, cfg, column="bottleneck_busy_blocked_rule")
    bf["share_busy_plus_blocked_rule"] = bf_alt["share"].to_numpy()
    bf.round(4).to_csv(out / f"{prefix}_bottleneck_frequency.csv", index=False)
    first = run.batches[run.batches["rep"] < 50]
    first.round(3).to_csv(out / f"{prefix}_batch_lead_times.csv", index=False)

    st = station_summary(run)
    pct = {k: float(run.reps[f"lt_{k.lower()}_min"].mean()) for k in ("P50", "P90", "P95")}
    plots.daily_output_figure(run.daily, cfg.demand_per_day,
                              f"Baseline daily output vs demand ({run.n} replications x "
                              f"{cfg.sim.days} days)", fig / f"{prefix}_daily_output.png")
    plots.lead_time_figure(run.lt_hist, LT_BIN_EDGES, pct,
                           "Baseline line lead-time distribution (pooled good units)",
                           fig / f"{prefix}_lead_time.png")
    plots.station_state_figure(st, "Baseline station state breakdown (mean of replications)",
                               fig / f"{prefix}_station_states.png")
    plots.bottleneck_figure(bf, "Baseline bottleneck frequency (active-period method)",
                            fig / f"{prefix}_bottleneck_frequency.png")


def step_baseline(quick: bool = False, reps: int | None = None,
                  workers: int | None = None) -> RunResult:
    """Run the baseline (S0), write tables/figures and the convergence analysis."""
    cfg = load_config()
    out, fig = out_dirs(quick)
    n = n_reps(cfg, quick, reps)
    _log(f"baseline: {n} replications x ({cfg.sim.warmup_days}+{cfg.sim.days}) days")
    t0 = time.time()
    run = run_replications(cfg, n, label="S0", workers=workers, progress=_progress("baseline"))
    baseline_outputs(run, out, fig)

    conv = pd.concat([
        convergence_table(run.reps["throughput_per_day"].to_numpy(), "throughput_per_day"),
        convergence_table(run.reps["lt_mean_min"].to_numpy(), "lt_mean_min"),
    ])
    conv.round(5).to_csv(out / "convergence.csv", index=False)
    req = pd.DataFrame([
        {"metric": m, "target_rel_half_width_pct": p,
         "required_replications": required_replications(run.reps[m].to_numpy(), p / 100),
         "replications_run": run.n,
         "achieved_rel_half_width_pct": float(
             conv[(conv.metric == m) & (conv.n == run.n)]["rel_half_width_pct"].iloc[0])}
        for m in ("throughput_per_day", "lt_mean_min") for p in (0.5, 1.0, 2.0)
    ])
    req.round(4).to_csv(out / "convergence_required_replications.csv", index=False)
    plots.convergence_figure(conv, CONVERGENCE_TARGET_PCT,
                             "Convergence of baseline estimates with replication count",
                             fig / "convergence.png")
    write_meta(out, "baseline", {"replications": n, "base_seed": cfg.sim.base_seed,
                                 "runtime_s": round(time.time() - t0, 1)})
    th = run.reps["throughput_per_day"]
    _log(f"baseline: throughput {th.mean():.1f} units/day (sd {th.std():.1f}); "
         f"lead time {run.reps['lt_mean_min'].mean():.1f} min; done in {time.time() - t0:.0f} s")
    return run


def static_capacity(cfg: LineConfig) -> pd.DataFrame:
    """Hand-calculation of each station's effective time per unit and daily capacity.

    t_eff = CT x mix multiplier x (1 + MTTR/MTBF)  [operation-dependent failures]
            + P(model switch) x changeover / batch size
            + rework load (test failures x rework share x rework time) at the rework station
    divided by the number of parallel servers. This ignores blocking/starving
    and is therefore an *upper bound* on throughput.
    """
    mix = np.array([p.mix for p in cfg.products])
    p_switch = 1.0 - float(np.sum(mix ** 2))
    test = cfg.station(cfg.rework.test_station)
    rows = []
    for st in cfg.stations:
        ct = st.ct_mean_s * cfg.mix_ct_multiplier
        fail = 1.0 + (st.mttr_min / st.mtbf_min if st.has_breakdowns and cfg.sim.breakdowns
                      else 0.0)
        rework = 0.0
        if st.id == cfg.rework.rework_station and cfg.rework.rework_share > 0:
            rework = test.scrap_rate * cfg.rework.rework_share * cfg.rework.rework_time_s
        co = p_switch * st.changeover_min * 60.0 / cfg.batch_size if st.changeover else 0.0
        t_eff = (ct * fail + rework * fail + co) / st.servers
        rows.append({"station_id": st.id, "station": st.name, "servers": st.servers,
                     "ct_mix_s": ct, "failure_factor": fail, "changeover_s_per_unit": co,
                     "rework_s_per_unit": rework, "t_eff_s": t_eff,
                     "capacity_per_day": cfg.day_seconds / t_eff,
                     "load_vs_takt": t_eff / cfg.takt_s})
    return pd.DataFrame(rows)
