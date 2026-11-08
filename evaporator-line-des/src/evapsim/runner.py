"""Monte Carlo replication runner (process pool, CRN streams, two-level input uncertainty).

Replication ``r`` uses streams ``SeedSequence(base_seed, spawn_key=(r, k))``, the
same children that ``SeedSequence(base_seed).spawn(n)[r]`` produces. Results do
not depend on the number of replications or worker processes, and the first
30 replications of a quick run are identical to the first 30 of a full run.

Two-level Monte Carlo: when ``thetas`` is given (or input uncertainty is
enabled in the config), replication ``r`` runs with steeking mean
``thetas[r]``. This is the outer loop over the uncertain input. The inner
variability comes from the replication's own random streams.
"""

from __future__ import annotations

import atexit
import multiprocessing
import os
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from .config import LineConfig
from .metrics import replication_metrics, t_ci
from .model import simulate

LT_BINS_DAYS = np.arange(0.0, 151.0, 1.0)


@dataclass
class RunResult:
    """Aggregated output of ``n`` replications of one configuration."""

    label: str
    config: LineConfig
    reps: pd.DataFrame         # one row per replication
    resources: pd.DataFrame    # replication x resource state shares
    activities: pd.DataFrame   # replication x activity (busy share, mean queue time)
    weekly: pd.DataFrame       # replication x week output
    lt_hist: np.ndarray        # pooled order lead-time histogram (days), last = overflow

    @property
    def n(self) -> int:
        """Number of replications."""
        return len(self.reps)


def _one(cfg: LineConfig, rep: int, theta: float | None) -> dict[str, Any]:
    res = simulate(cfg, rep=rep, theta_steeking=theta)
    m = replication_metrics(res, cfg)
    lt = res.orders.loc[res.orders["completed_in_window"], "lead_time_days"].to_numpy()
    h, _ = np.histogram(lt, bins=LT_BINS_DAYS)
    return {"rep": m,
            "resources": res.resources.assign(rep=rep).to_dict("records"),
            "activities": res.activities.assign(rep=rep).to_dict("records"),
            "weekly": res.weekly_output.tolist(),
            "hist": np.append(h, int(np.sum(lt >= LT_BINS_DAYS[-1])))}


def _worker(task: tuple[dict[str, Any], list[tuple[int, float | None]]]) -> list[dict[str, Any]]:
    from .config import LineConfig as _LC

    cfg_dict, items = task
    cfg = _LC(cfg_dict)
    return [_one(cfg, r, th) for r, th in items]


_POOLS: dict[int, ProcessPoolExecutor] = {}


def _pool(workers: int) -> ProcessPoolExecutor:
    """Persistent ``spawn`` process pool per worker count (safe in threaded hosts)."""
    ex = _POOLS.get(workers)
    if ex is None:
        ex = ProcessPoolExecutor(max_workers=workers,
                                 mp_context=multiprocessing.get_context("spawn"))
        _POOLS[workers] = ex
        atexit.register(ex.shutdown)
    return ex


def default_workers() -> int:
    """Worker processes: ``$EVAPSIM_WORKERS`` or the CPU count."""
    env = os.environ.get("EVAPSIM_WORKERS")
    return max(1, int(env)) if env else max(1, os.cpu_count() or 1)


def run_replications(cfg: LineConfig, n_reps: int, label: str = "",
                     workers: int | None = None, thetas: Sequence[float] | None = None,
                     rep_offset: int = 0,
                     progress: Callable[[int, int], None] | None = None) -> RunResult:
    """Run replications ``rep_offset .. rep_offset + n_reps - 1`` of ``cfg``.

    Args:
        cfg: Configuration.
        n_reps: Number of replications.
        label: Label stored with the result (scenario id, ...).
        workers: Worker processes (default :func:`default_workers`).
        thetas: Optional steeking mean per replication (outer loop of two-level MC).
        rep_offset: First replication index (seeds are keyed by the index).
        progress: Optional callback ``progress(done, total)``.
    """
    workers = default_workers() if workers is None else max(1, workers)
    items = [(rep_offset + i, None if thetas is None else float(thetas[i]))
             for i in range(n_reps)]
    chunk = max(1, min(20, n_reps // (workers * 4) or 1))
    d = cfg.to_dict()
    tasks = [(d, items[i:i + chunk]) for i in range(0, n_reps, chunk)]
    outputs: list[dict[str, Any]] = []
    if workers == 1 or len(tasks) == 1:
        for t in tasks:
            outputs += _worker(t)
            if progress:
                progress(len(outputs), n_reps)
    else:
        try:
            for part in _pool(workers).map(_worker, tasks):
                outputs += part
                if progress:
                    progress(len(outputs), n_reps)
        except BrokenProcessPool:
            _POOLS.pop(workers, None)
            outputs = [o for t in tasks for o in _worker(t)]
    return assemble(label, cfg, outputs)


def assemble(label: str, cfg: LineConfig, outputs: list[dict[str, Any]]) -> RunResult:
    """Combine per-replication outputs into tables."""
    reps = pd.DataFrame([o["rep"] for o in outputs]).sort_values("rep").reset_index(drop=True)
    res = pd.DataFrame([r for o in outputs for r in o["resources"]])
    act = pd.DataFrame([r for o in outputs for r in o["activities"]])
    weekly = pd.DataFrame([{"rep": o["rep"]["rep"], "week": w + 1, "eva": v}
                           for o in outputs for w, v in enumerate(o["weekly"])])
    hist = np.sum([o["hist"] for o in outputs], axis=0)
    for df in (reps, res, act, weekly):
        df.insert(0, "scenario", label)
    return RunResult(label, cfg, reps, res, act, weekly, hist)


def resource_summary(run: RunResult) -> pd.DataFrame:
    """Mean state shares and queue time per resource across replications."""
    num = run.resources.drop(columns=["scenario", "label", "rep"])
    out = num.groupby("resource", sort=False).mean().reset_index()
    out.insert(1, "label", out["resource"].map(run.config.resource_label))
    out.insert(0, "scenario", run.label)
    return out.sort_values("active", ascending=False).reset_index(drop=True)


def activity_summary(run: RunResult) -> pd.DataFrame:
    """Mean busy share and queue time per activity (station) across replications."""
    a = run.activities.groupby(["resource", "activity"], sort=False).agg(
        busy=("busy", "mean"), mean_wait_min=("mean_wait_min", "mean"),
        n_waits=("n_waits", "mean")).reset_index()
    a.insert(0, "scenario", run.label)
    return a


def pooled_percentiles(hist: np.ndarray, qs: tuple[int, ...] = (50, 90, 95)) -> dict[str, float]:
    """Approximate percentiles of the pooled lead-time distribution (bin upper edges)."""
    c = np.cumsum(hist[:-1]) / max(1, hist.sum())
    return {f"P{q}": float(LT_BINS_DAYS[min(int(np.searchsorted(c, q / 100)) + 1,
                                            len(LT_BINS_DAYS) - 1)]) for q in qs}


def convergence_table(values: np.ndarray, metric: str) -> pd.DataFrame:
    """Running mean and 95 % CI half-width after each additional replication."""
    values = np.asarray(values, float)
    rows = []
    for n in range(2, len(values) + 1):
        m, h, _ = t_ci(values[:n])
        rows.append({"metric": metric, "n": n, "running_mean": m, "ci_half_width": h,
                     "rel_half_width_pct": 100 * h / m if m else np.nan})
    return pd.DataFrame(rows)


def required_replications(values: np.ndarray, rel: float) -> int:
    """Replications for a CI half-width of ``rel`` x mean: n = (t s / (rel x mean))^2."""
    from scipy import stats

    values = np.asarray(values, float)
    values = values[~np.isnan(values)]
    m, s = float(values.mean()), float(values.std(ddof=1))
    n = 2
    while n < 100000 and n < (stats.t.ppf(0.975, n - 1) * s / (rel * abs(m))) ** 2:
        n += 1
    return n
