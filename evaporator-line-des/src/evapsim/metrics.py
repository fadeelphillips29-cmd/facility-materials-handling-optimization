"""Phase 4 - performance metrics computed from replication results.

Definitions (all over the measurement window, i.e. after warm-up):

=====================  ======================================================
Metric                 Formula
=====================  ======================================================
throughput/day (TH)    good units leaving Station 7 / measured days
takt compliance        share of measured days with output >= demand
lead time (LT)         exit time - release time of each good unit (minutes);
                       mean, P50, P90, P95 per replication
WIP                    time-average number of units released and not departed
Little's-law WIP       departure rate (good + scrap, units/min) x mean sojourn
line FPY               good units never failing a test / units departed
RTY                    product of the station first-pass yields
station state share    time in state / (servers x window length)
active share           busy + down + changeover = 1 - starved - blocked
bottleneck             station with the highest active share (active-period
                       method, ASSUMPTIONS A21)
VA ratio (line)        mean processing time per good unit / mean LT
VA ratio (door)        processing time / (LT + raw-material and FG store days)
days of stock          average buffer content / daily demand
=====================  ======================================================
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
from scipy import stats

from .config import LineConfig
from .model import BLOCKED, BUSY, CHANGEOVER, DOWN, STARVED, ReplicationResult

KPI_LABELS: dict[str, tuple[str, str]] = {
    "throughput_per_day": ("Throughput", "units/day"),
    "takt_compliance": ("Takt compliance (days >= demand)", "share of days"),
    "attainment": ("Demand attainment", "TH / demand"),
    "lt_mean_min": ("Lead time, mean", "min"),
    "lt_p50_min": ("Lead time, P50", "min"),
    "lt_p90_min": ("Lead time, P90", "min"),
    "lt_p95_min": ("Lead time, P95", "min"),
    "batch_lt_mean_min": ("Batch lead time, mean", "min"),
    "wip_avg": ("WIP, time average", "units"),
    "littles_wip": ("WIP from Little's law (TH x LT)", "units"),
    "fpy_line": ("First-pass yield (line)", "fraction"),
    "rty": ("Rolled throughput yield", "fraction"),
    "scrap_share": ("Scrap share of departures", "fraction"),
    "va_time_s": ("Value-added time per unit", "s"),
    "va_ratio_line": ("VA ratio (line lead time)", "fraction"),
    "va_ratio_door": ("VA ratio (door-to-door)", "fraction"),
    "bottleneck_util": ("Bottleneck active share", "fraction"),
}


def replication_metrics(res: ReplicationResult, cfg: LineConfig) -> dict[str, Any]:
    """Scalar KPIs of one replication."""
    days = len(res.daily_output)
    th = float(res.daily_output.mean())
    lt = res.lead_times_min
    shares = station_state_shares(res)
    active = shares[:, BUSY] + shares[:, DOWN] + shares[:, CHANGEOVER]
    busy_blocked = shares[:, BUSY] + shares[:, BLOCKED]
    departed = res.good + res.scrapped
    window_min = res.measure_s / 60.0
    lam = len(res.sojourn_all_min) / window_min
    station_fpy = station_yields(res, cfg)
    lt_mean = float(lt.mean()) if len(lt) else float("nan")
    va = float(res.va_time_s.mean()) if len(lt) else float("nan")
    store_min = (cfg.vsm.raw_material_stock_days + cfg.vsm.finished_goods_stock_days) * (
        cfg.day_seconds / 60.0)
    blt = [b["lead_time_min"] for b in res.batch_records]
    return {
        "rep": res.rep,
        "throughput_per_day": th,
        "throughput_sd_daily": float(res.daily_output.std(ddof=1)) if days > 1 else 0.0,
        "takt_compliance": float(np.mean(res.daily_output >= cfg.demand_per_day)),
        "attainment": th / cfg.demand_per_day,
        "lt_mean_min": lt_mean,
        "lt_p50_min": float(np.percentile(lt, 50)) if len(lt) else float("nan"),
        "lt_p90_min": float(np.percentile(lt, 90)) if len(lt) else float("nan"),
        "lt_p95_min": float(np.percentile(lt, 95)) if len(lt) else float("nan"),
        "batch_lt_mean_min": float(np.mean(blt)) if blt else float("nan"),
        "wip_avg": res.wip_avg,
        "littles_wip": lam * float(res.sojourn_all_min.mean()) if departed else 0.0,
        "fpy_line": res.first_pass_good / departed if departed else float("nan"),
        "rty": float(np.prod(station_fpy)),
        "scrap_share": res.scrapped / departed if departed else float("nan"),
        "va_time_s": va,
        "va_ratio_line": va / 60.0 / lt_mean if len(lt) else float("nan"),
        "va_ratio_door": va / 60.0 / (lt_mean + store_min) if len(lt) else float("nan"),
        "bottleneck_station": int(res.station_ids[int(np.argmax(active))]),
        "bottleneck_util": float(active.max()),
        "bottleneck_busy_blocked_rule": int(res.station_ids[int(np.argmax(busy_blocked))]),
        "released": res.released,
        "good": res.good,
        "scrapped": res.scrapped,
        "test_failures": res.test_failures,
        "reworked": res.reworked,
    }


def station_state_shares(res: ReplicationResult) -> np.ndarray:
    """(n_stations, 5) share of window time in each state, averaged over servers."""
    return res.state_time_s / (res.servers[:, None] * res.measure_s)


def station_yields(res: ReplicationResult, cfg: LineConfig) -> np.ndarray:
    """Measured first-pass yield of each station.

    FPY = 1 - (scrapped there / first-pass completions there); at the test
    station every first-test failure counts, whether reworked or scrapped.
    """
    test_i = cfg.rework.test_station - 1
    out = np.ones(len(res.station_ids))
    for i in range(len(out)):
        n = res.processed_by_station[i]
        if n:
            fails = (res.test_failures if (i == test_i and cfg.rework.rework_share > 0)
                     else res.scrap_by_station[i])
            out[i] = 1.0 - fails / n
    return out


def station_metrics(res: ReplicationResult, cfg: LineConfig) -> list[dict[str, Any]]:
    """Per-station metrics of one replication (one dict per station)."""
    shares = station_state_shares(res)
    fpy = station_yields(res, cfg)
    days = res.measure_s / res.day_s
    rows = []
    for i, st in enumerate(cfg.stations):
        buf_in = float(res.buffer_avg[i - 1]) if i > 0 else float("nan")
        rows.append({
            "rep": res.rep,
            "station_id": st.id,
            "station": st.name,
            "servers": st.servers,
            "busy": shares[i, BUSY],
            "starved": shares[i, STARVED],
            "blocked": shares[i, BLOCKED],
            "down": shares[i, DOWN],
            "changeover": shares[i, CHANGEOVER],
            "active": shares[i, BUSY] + shares[i, DOWN] + shares[i, CHANGEOVER],
            "busy_plus_blocked": shares[i, BUSY] + shares[i, BLOCKED],
            # uptime = operating / (operating + down); comparable with MTBF/(MTBF+MTTR)
            "uptime": shares[i, BUSY] / max(1e-12, shares[i, BUSY] + shares[i, DOWN]),
            "fpy": fpy[i],
            "buffer_in_front_avg": buf_in,
            "days_of_stock_in_front": buf_in / cfg.demand_per_day if i > 0 else float("nan"),
            "failures_per_day": res.failures_by_station[i] / (days + cfg.sim.warmup_days),
            "changeovers_per_day": res.changeovers_by_station[i] / (days + cfg.sim.warmup_days),
        })
    return rows


# ------------------------------------------------------------------ statistics
def t_ci(x: np.ndarray | pd.Series, conf: float = 0.95) -> tuple[float, float, float]:
    """Return (mean, half-width, sd) of a Student-t confidence interval."""
    x = np.asarray(x, dtype=float)
    x = x[~np.isnan(x)]
    n = len(x)
    if n == 0:
        return float("nan"), float("nan"), float("nan")
    m = float(x.mean())
    if n < 2:
        return m, float("nan"), float("nan")
    sd = float(x.std(ddof=1))
    return m, float(stats.t.ppf(0.5 + conf / 2, n - 1) * sd / np.sqrt(n)), sd


def summarize(df: pd.DataFrame, cols: list[str] | None = None,
              conf: float = 0.95) -> pd.DataFrame:
    """Mean, SD, CI half-width and bounds of each column across replications."""
    cols = cols or [c for c in KPI_LABELS if c in df.columns]
    rows = []
    for c in cols:
        m, h, sd = t_ci(df[c], conf)
        label, unit = KPI_LABELS.get(c, (c, ""))
        rows.append({"metric": c, "label": label, "unit": unit, "mean": m, "sd": sd,
                     "ci_half_width": h, "ci_low": m - h, "ci_high": m + h,
                     "n": int(df[c].notna().sum())})
    return pd.DataFrame(rows)


def paired_difference(a: np.ndarray, b: np.ndarray, conf: float = 0.95) -> dict[str, float]:
    """Paired-t comparison of scenario ``b`` minus baseline ``a`` (same replications).

    Returns the mean difference, its CI, the relative change versus the
    baseline mean, the paired-t p-value and the correlation between the two
    series (a positive correlation is the variance reduction from CRN).
    """
    a = np.asarray(a, float)
    b = np.asarray(b, float)
    d = b - a
    m, h, sd = t_ci(d, conf)
    if len(d) > 1 and sd > 0:
        p = float(stats.ttest_rel(b, a).pvalue)
    else:
        p = 0.0 if m != 0 else 1.0
    base = float(np.mean(a))
    corr = float(np.corrcoef(a, b)[0, 1]) if np.std(a) > 0 and np.std(b) > 0 else float("nan")
    return {"diff_mean": m, "diff_ci_low": m - h, "diff_ci_high": m + h, "diff_sd": sd,
            "rel_change_pct": 100.0 * m / base if base else float("nan"),
            "rel_ci_low_pct": 100.0 * (m - h) / base if base else float("nan"),
            "rel_ci_high_pct": 100.0 * (m + h) / base if base else float("nan"),
            "p_value": p, "significant": bool((m - h) > 0 or (m + h) < 0), "crn_corr": corr}


def bottleneck_frequency(rep_df: pd.DataFrame, cfg: LineConfig,
                         column: str = "bottleneck_station") -> pd.DataFrame:
    """Share of replications in which each station was the bottleneck."""
    counts = rep_df[column].value_counts()
    n = len(rep_df)
    return pd.DataFrame([
        {"station_id": st.id, "station": st.name, "count": int(counts.get(st.id, 0)),
         "share": counts.get(st.id, 0) / n}
        for st in cfg.stations
    ])
