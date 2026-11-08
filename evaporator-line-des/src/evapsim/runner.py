"""Phase 5 - Monte Carlo replication runner.

Replication ``r`` always uses the random streams derived from
``SeedSequence(base_seed, spawn_key=(r, ...))``, which is exactly what
``SeedSequence(base_seed).spawn(n)[r]`` would produce. The streams therefore do
not depend on the number of replications or on how work is split across
processes: results are bit-for-bit reproducible for a given base seed, and the
quick-mode replications are the first 50 replications of the full run.
"""

from __future__ import annotations

import multiprocessing
import os
from collections.abc import Callable
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from .config import LineConfig, config_from_dict
from .metrics import replication_metrics, station_metrics, t_ci
from .model import simulate_replication

LT_BIN_EDGES = np.arange(0.0, 402.0, 2.0)  # lead-time histogram bins (minutes)


@dataclass
class RunResult:
    """Aggregated output of ``n`` replications of one configuration."""

    label: str
    config: LineConfig
    reps: pd.DataFrame        # one row per replication (KPIs)
    stations: pd.DataFrame    # one row per replication x station
    daily: pd.DataFrame       # one row per replication x measured day
    batches: pd.DataFrame     # one row per completed batch
    lt_hist: np.ndarray       # pooled lead-time histogram counts (LT_BIN_EDGES)

    @property
    def n(self) -> int:
        """Number of replications."""
        return len(self.reps)

    def lt_hist_frame(self) -> pd.DataFrame:
        """Pooled lead-time histogram as a DataFrame (bin edges in minutes)."""
        return pd.DataFrame({"bin_low_min": LT_BIN_EDGES[:-1], "bin_high_min": LT_BIN_EDGES[1:],
                             "count": self.lt_hist[:-1]}).assign(
            overflow_above_max=int(self.lt_hist[-1]))


def _one(cfg: LineConfig, rep: int) -> dict[str, Any]:
    res = simulate_replication(cfg, rep=rep)
    hist, _ = np.histogram(res.lead_times_min, bins=LT_BIN_EDGES)
    over = int(np.sum(res.lead_times_min >= LT_BIN_EDGES[-1]))
    return {
        "rep": replication_metrics(res, cfg),
        "stations": station_metrics(res, cfg),
        "daily": res.daily_output.tolist(),
        "batches": [{"rep": rep, **b} for b in res.batch_records],
        "hist": np.append(hist, over),
    }


def _worker(task: tuple[dict[str, Any], list[int]]) -> list[dict[str, Any]]:
    cfg_dict, reps = task
    cfg = config_from_dict(cfg_dict)
    return [_one(cfg, r) for r in reps]


def default_workers() -> int:
    """Number of worker processes (``EVAPSIM_WORKERS`` env var or CPU count)."""
    env = os.environ.get("EVAPSIM_WORKERS")
    if env:
        return max(1, int(env))
    return max(1, os.cpu_count() or 1)


def run_replications(
    cfg: LineConfig,
    n_reps: int,
    label: str = "",
    workers: int | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> RunResult:
    """Run replications 0..n_reps-1 of ``cfg`` (in parallel when workers > 1).

    Args:
        cfg: Configuration to simulate.
        n_reps: Number of replications.
        label: Name stored with the result (e.g. scenario id).
        workers: Process count; defaults to :func:`default_workers`.
        progress: Optional callback ``progress(done, total)``.
    """
    workers = default_workers() if workers is None else max(1, workers)
    reps = list(range(n_reps))
    chunk = max(1, min(25, n_reps // (workers * 4) or 1))
    tasks = [(cfg.to_dict(), reps[i:i + chunk]) for i in range(0, n_reps, chunk)]
    outputs: list[dict[str, Any]] = []
    if workers == 1 or len(tasks) == 1:
        for t in tasks:
            outputs += _worker(t)
            if progress:
                progress(len(outputs), n_reps)
    else:
        ctx = multiprocessing.get_context("spawn")  # safe with threads (Streamlit, pytest)
        with ProcessPoolExecutor(max_workers=workers, mp_context=ctx) as ex:
            for part in ex.map(_worker, tasks):
                outputs += part
                if progress:
                    progress(len(outputs), n_reps)
    return _assemble(label, cfg, outputs)


def _assemble(label: str, cfg: LineConfig, outputs: list[dict[str, Any]]) -> RunResult:
    reps = pd.DataFrame([o["rep"] for o in outputs]).sort_values("rep").reset_index(drop=True)
    stations = pd.DataFrame([r for o in outputs for r in o["stations"]])
    daily = pd.DataFrame(
        [{"rep": o["rep"]["rep"], "day": d + 1, "output": v}
         for o in outputs for d, v in enumerate(o["daily"])]
    )
    batches = pd.DataFrame([b for o in outputs for b in o["batches"]])
    hist = np.sum([o["hist"] for o in outputs], axis=0)
    for df in (reps, stations, daily, batches):
        df.insert(0, "scenario", label)
    return RunResult(label, cfg, reps, stations, daily, batches, hist)


def station_summary(run: RunResult) -> pd.DataFrame:
    """Mean of every station metric across replications (one row per station)."""
    num = run.stations.drop(columns=["scenario", "station", "rep"])
    out = num.groupby("station_id").mean().reset_index()
    names = {s.id: s.name for s in run.config.stations}
    out.insert(1, "station", out["station_id"].map(names))
    out.insert(0, "scenario", run.label)
    return out


def pooled_lt_percentiles(
    hist: np.ndarray, qs: tuple[float, ...] = (50, 90, 95)
) -> dict[str, float]:
    """Percentiles of the pooled lead-time distribution from histogram counts."""
    counts = hist[:-1].astype(float)
    cdf = np.cumsum(counts) / max(1.0, hist.sum())
    out = {}
    for q in qs:
        idx = int(np.searchsorted(cdf, q / 100.0))
        out[f"P{int(q)}"] = float(LT_BIN_EDGES[min(idx + 1, len(LT_BIN_EDGES) - 1)])
    return out


# ------------------------------------------------------------------ convergence
def convergence_table(values: np.ndarray, metric: str, conf: float = 0.95) -> pd.DataFrame:
    """Running mean and CI half-width after each additional replication."""
    values = np.asarray(values, float)
    rows = []
    for n in range(2, len(values) + 1):
        m, h, _ = t_ci(values[:n], conf)
        rows.append({"metric": metric, "n": n, "running_mean": m, "ci_half_width": h,
                     "rel_half_width_pct": 100.0 * h / m if m else float("nan")})
    return pd.DataFrame(rows)


def required_replications(values: np.ndarray, rel_precision: float = 0.01,
                          conf: float = 0.95) -> int:
    """Replications needed for a CI half-width of ``rel_precision`` x mean.

    Uses the iterative formula n = (t_{n-1} * s / (e * mean))^2 with the sample
    standard deviation of the pilot replications.
    """
    from scipy import stats

    values = np.asarray(values, float)
    m, s = float(values.mean()), float(values.std(ddof=1))
    e = rel_precision * abs(m)
    n = 2
    while n < 100000:
        need = (stats.t.ppf(0.5 + conf / 2, n - 1) * s / e) ** 2
        if n >= need:
            return n
        n += 1
    return n


def save_run(run: RunResult, out_dir: Path, prefix: str) -> dict[str, Path]:
    """Write the standard CSV tables of a run; return their paths."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = {
        "replications": out_dir / f"{prefix}_replications.csv",
        "stations": out_dir / f"{prefix}_stations.csv",
        "daily": out_dir / f"{prefix}_daily_output.csv",
        "lt_hist": out_dir / f"{prefix}_lead_time_histogram.csv",
    }
    run.reps.round(5).to_csv(paths["replications"], index=False)
    station_summary(run).round(5).to_csv(paths["stations"], index=False)
    run.daily.to_csv(paths["daily"], index=False)
    run.lt_hist_frame().to_csv(paths["lt_hist"], index=False)
    return paths
