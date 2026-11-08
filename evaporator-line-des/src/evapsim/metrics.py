"""KPIs of one replication, confidence intervals and paired comparisons.

Definitions are for the measurement window (after warm-up):

==========================  ==================================================
Metric                      Definition
==========================  ==================================================
throughput (EVA/week)       EVA completed in window / measured weeks
attainment                  throughput / demand
weekly demand compliance    share of measured weeks with output >= demand
order lead time             completion of the order's last EVA - order arrival
                            (working days), for orders completed in the window;
                            mean, P50, P90, P95
on-time delivery            share of those orders completed by arrival + due weeks
WIP (EVA)                   time-average number of EVA in the system, per stage
Little's-law WIP            lambda x W = EVA completion rate x mean EVA lead time
FPY (pressure test)         1 - first-test failures / first tests
utilisation                 busy share of a resource (server-time)
active share                busy + changeover + down
bottleneck                  resource with the highest active share
queue bottleneck            resource with the highest mean queue time
VA ratio                    mean value-added minutes per EVA / mean EVA lead time
==========================  ==================================================
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from .config import LineConfig
from .model import STAGES, SimResult

KPI_LABELS: dict[str, tuple[str, str]] = {
    "throughput_eva_week": ("Throughput", "EVA/week"),
    "attainment": ("Demand attainment", "TH / demand"),
    "weekly_compliance": ("Weekly demand compliance", "share of weeks"),
    "lt_mean_days": ("Order lead time, mean", "working days"),
    "lt_p50_days": ("Order lead time, P50", "working days"),
    "lt_p90_days": ("Order lead time, P90", "working days"),
    "lt_p95_days": ("Order lead time, P95", "working days"),
    "on_time": ("On-time delivery", "share of orders"),
    "wip_total": ("WIP in system", "EVA"),
    "littles_wip": ("WIP from Little's law", "EVA"),
    "fpy_test": ("First-pass yield at pressure test", "fraction"),
    "va_ratio": ("Value-added ratio", "fraction"),
    "va_min_per_eva": ("Value-added time", "min/EVA"),
    "bottleneck_active": ("Bottleneck active share", "fraction"),
}


def replication_metrics(res: SimResult, cfg: LineConfig) -> dict[str, Any]:
    """Scalar KPIs of one replication."""
    win = res.win
    weeks = len(res.weekly_output)
    th = res.weekly_output.sum() / weeks
    o = res.orders[res.orders["completed_in_window"]]
    lt = o["lead_time_days"].to_numpy()
    ev = res.evas[res.evas["completion"].between(win.start, win.end, inclusive="left")] \
        if "completion" in res.evas else res.evas.iloc[0:0]
    ev_lt = (ev["completion"] - ev["arrival"]).to_numpy()
    lam = len(ev) / win.length
    r = res.resources.set_index("resource")
    bn = r["active"].idxmax()
    qbn = r["mean_wait_min"].idxmax()
    out: dict[str, Any] = {
        "rep": res.rep, "theta_steeking": res.theta_steeking,
        "throughput_eva_week": th, "attainment": th / cfg.demand,
        "weekly_compliance": float(np.mean(res.weekly_output >= cfg.demand)),
        "orders_completed": len(o),
        "lt_mean_days": float(lt.mean()) if len(lt) else np.nan,
        "lt_p50_days": float(np.percentile(lt, 50)) if len(lt) else np.nan,
        "lt_p90_days": float(np.percentile(lt, 90)) if len(lt) else np.nan,
        "lt_p95_days": float(np.percentile(lt, 95)) if len(lt) else np.nan,
        "on_time": float(o["on_time"].mean()) if len(o) else np.nan,
        "wip_total": res.wip_total,
        "littles_wip": lam * float(ev_lt.mean()) if len(ev) else np.nan,
        "fpy_test": 1 - res.first_test_failures / res.first_tests if res.first_tests else np.nan,
        "va_min_per_eva": float(ev["va_min"].mean()) if len(ev) else np.nan,
        "va_ratio": float(ev["va_min"].mean() / ev_lt.mean()) if len(ev) else np.nan,
        "eva_lt_mean_days": float(ev_lt.mean() / cfg.day_min) if len(ev) else np.nan,
        "bottleneck": bn, "bottleneck_active": float(r.loc[bn, "active"]),
        "queue_bottleneck": qbn, "in_system_end": res.in_system_end,
        "wip_peak": res.wip_peak, "reworks": res.reworks,
        "fin_job_mean_min": float(res.fin_jobs["job_min"].mean()) if len(res.fin_jobs)
        else np.nan,
    }
    for s in STAGES:
        out[f"wip_{s}"] = res.wip_by_stage[s]
    return out


def t_ci(x: np.ndarray | pd.Series, conf: float = 0.95) -> tuple[float, float, float]:
    """(mean, CI half-width, sd) of a Student-t interval (NaNs dropped)."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n == 0:
        return np.nan, np.nan, np.nan
    m = float(x.mean())
    if n < 2:
        return m, np.nan, np.nan
    sd = float(x.std(ddof=1))
    return m, float(stats.t.ppf(0.5 + conf / 2, n - 1) * sd / np.sqrt(n)), sd


def summarize(df: pd.DataFrame, cols: list[str] | None = None) -> pd.DataFrame:
    """Mean, SD and 95 % CI of each KPI across replications."""
    cols = cols or [c for c in KPI_LABELS if c in df.columns]
    rows = []
    for c in cols:
        m, h, sd = t_ci(df[c])
        lab, unit = KPI_LABELS.get(c, (c, ""))
        rows.append({"metric": c, "label": lab, "unit": unit, "mean": m, "sd": sd,
                     "ci_half_width": h, "ci_low": m - h, "ci_high": m + h,
                     "n": int(df[c].notna().sum())})
    return pd.DataFrame(rows)


def paired_difference(a: np.ndarray, b: np.ndarray) -> dict[str, float]:
    """Paired-t comparison of b - a over the same replications (CRN)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    ok = ~(np.isnan(a) | np.isnan(b))
    a, b = a[ok], b[ok]
    d = b - a
    m, h, sd = t_ci(d)
    p = float(stats.ttest_rel(b, a).pvalue) if len(d) > 1 and sd > 0 else (
        0.0 if m != 0 else 1.0)
    base = float(np.mean(a)) if len(a) else np.nan
    corr = float(np.corrcoef(a, b)[0, 1]) if len(a) > 2 and a.std() > 0 and b.std() > 0 \
        else np.nan
    return {"diff_mean": m, "diff_ci_low": m - h, "diff_ci_high": m + h,
            "rel_change_pct": 100 * m / base if base else np.nan, "p_value": p,
            "significant": bool((m - h) > 0 or (m + h) < 0), "crn_corr": corr, "n": len(d)}


def bottleneck_frequency(reps: pd.DataFrame, column: str = "bottleneck") -> pd.DataFrame:
    """Share of replications in which each resource is the bottleneck."""
    vc = reps[column].value_counts()
    return pd.DataFrame({"resource": vc.index, "count": vc.to_numpy(),
                         "share": vc.to_numpy() / len(reps)})


def variance_decomposition(y: np.ndarray, groups: np.ndarray) -> dict[str, float]:
    """One-way random-effects ANOVA: input-uncertainty vs process-variability variance.

    ``y`` holds replication outputs and ``groups`` the outer-sample index of each
    output (balanced design). Var(Y) = Var(E[Y|theta]) + E[Var(Y|theta)].
    """
    df = pd.DataFrame({"y": y, "g": groups}).dropna()
    k = df.groupby("g")["y"]
    n = int(k.size().iloc[0])
    ms_w = float(k.var(ddof=1).mean())
    ms_b = float(n * k.mean().var(ddof=1))
    var_input = max(0.0, (ms_b - ms_w) / n)
    total = var_input + ms_w
    return {"var_input": var_input, "var_process": ms_w, "var_total": total,
            "share_input": var_input / total if total else np.nan,
            "share_process": ms_w / total if total else np.nan,
            "outer": int(k.ngroups), "inner": n, "grand_mean": float(df["y"].mean())}
