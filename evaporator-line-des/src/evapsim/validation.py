"""Phase 6: validation against the observed data and a Kingman cross-check.

Validation question: could the 26 observed weeks have come from the model?

* **Weekly output.** In a stable open system throughput equals demand, so this
  is a consistency check (ASSUMPTIONS A32).
* **Order lead time.** This is the discriminating measure. The observed
  26-week mean is compared with the distribution of simulated 26-week means:
  % error (target |error| <= 5 %), empirical prediction-interval p-value, and
  a Welch t-test of the observed orders against simulated orders (one order
  sampled per replication, so the simulated sample is independent).

Kingman cross-check: at steeking and header welding, the simulated lot-level
queue time is compared with the VUT approximation, using the simulated
service SCV and utilisation, and two arrival SCVs. The *measured* SCV comes from
the lot interarrival times at the station. The *release* SCV comes from the
order arrivals. Arrivals at a station deep in the network are order releases
plus independent random delays. Successive gaps are then negatively
correlated (not renewal), so the measured SCV overstates the effective
variability and the release SCV understates it. The two Kingman values should
bracket the simulation at the bottleneck. A station fed by an upstream
bottleneck (header welding) gets regulated arrivals, and Kingman is not
expected to hold there.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from . import equations as eq
from . import plots
from .config import DATA_DIR, LineConfig, apply_overrides, load_config, with_demand
from .model import simulate
from .runner import run_replications

TARGET_PCT = 5.0


def load_observed(path: Path = DATA_DIR / "observed_weekly_output.csv") -> pd.DataFrame:
    """Observed weekly table (26 weeks)."""
    return pd.read_csv(path)


def observed_order_lead_times(obs: pd.DataFrame) -> np.ndarray:
    """All observed order lead times (days) from the semicolon-separated column."""
    vals = []
    for s in obs["order_lead_times_days"].dropna().astype(str):
        vals += [float(x) for x in s.split(";") if x]
    return np.asarray(vals)


def _p_emp(sim: np.ndarray, obs: float) -> float:
    lo = (np.sum(sim <= obs) + 1) / (len(sim) + 1)
    hi = (np.sum(sim >= obs) + 1) / (len(sim) + 1)
    return float(min(1.0, 2 * min(lo, hi)))


def run_validation(out: Path, fig: Path, n_reps: int, workers: int | None = None,
                   cfg: LineConfig | None = None) -> pd.DataFrame:
    """Simulate 26-week periods of the nominal model and compare with the observations."""
    cfg = cfg or load_config()
    obs = load_observed()
    weeks = len(obs)
    sim_cfg = apply_overrides(cfg, {"simulation": {"measure_weeks": weeks}})
    run = run_replications(sim_cfg, n_reps, "validation", workers)
    obs_out = obs["eva_completed"].to_numpy(float)
    obs_lt = observed_order_lead_times(obs)
    sim_th = run.reps["throughput_eva_week"].to_numpy()
    sim_lt = run.reps["lt_mean_days"].to_numpy()
    rng = np.random.default_rng(0)
    one_order = []
    for r in range(min(n_reps, 200)):
        res = simulate(sim_cfg, rep=r)
        o = res.orders[res.orders["completed_in_window"]]["lead_time_days"].to_numpy()
        one_order.append(float(rng.choice(o)))
    rows = []
    for name, unit, o_vals, sim_means, sim_t in (
            ("Mean weekly output", "EVA/week", obs_out, sim_th,
             run.weekly.groupby("rep").sample(1, random_state=1)["eva"].to_numpy(float)),
            ("Mean order lead time", "working days", obs_lt, sim_lt, np.asarray(one_order))):
        om, sm = float(np.mean(o_vals)), float(np.mean(sim_means))
        lo, hi = np.percentile(sim_means, [2.5, 97.5])
        err = 100 * (sm - om) / om
        p = _p_emp(sim_means, om)
        rows.append({"measure": name, "unit": unit, "observed_mean": om,
                     "n_observed": len(o_vals), "simulated_mean": sm,
                     "sim_pi95_low": lo, "sim_pi95_high": hi, "error_pct": err,
                     "within_target": abs(err) <= TARGET_PCT, "prediction_interval_p": p,
                     "welch_t_p": float(stats.ttest_ind(o_vals, sim_t, equal_var=False).pvalue),
                     "verdict": "valid" if abs(err) <= TARGET_PCT and p >= 0.05
                     else "investigate"})
    summary = pd.DataFrame(rows)
    summary.round(5).to_csv(out / "validation_summary.csv", index=False)
    plots.validation_figure(obs, obs_lt, sim_th, sim_lt, cfg.demand, fig / "validation.png")
    return summary


def calibration_grid(cfg: LineConfig, n_reps: int, workers: int | None = None,
                     key: str = "procurement_tubing", step: float = 0.25,
                     span: float = 2.5) -> pd.DataFrame:
    """Grid over the mean of the calibrated lead time, starting from the brief value.

    Rule (minimum-change calibration): adopt the smallest adjustment of the
    assumed input for which the model passes both criteria (|error| <= 5 % and
    prediction-interval p >= 0.05). The best-fit value is reported too. The
    minimum change is preferred because a single 26-week observation contains
    sampling noise, and fitting it exactly would overfit.
    """
    obs = float(np.mean(observed_order_lead_times(load_observed())))
    lt = cfg.raw["lead_times"][key]
    origin = float(lt.get("brief_mean_days", lt["mean_days"]))
    rows = []
    for v in np.arange(origin, origin + span + 1e-9, step):
        c = apply_overrides(cfg, {"simulation": {"measure_weeks": 26},
                                  "lead_times": {key: {"mean_days": float(v)}}})
        sim = run_replications(c, n_reps, f"cal {v:.2f}", workers).reps["lt_mean_days"].to_numpy()
        m = float(sim.mean())
        err = 100 * (m - obs) / obs
        p = _p_emp(sim, obs)
        rows.append({"parameter": f"lead_times.{key}.mean_days", "value": float(v),
                     "simulated_lt_mean_days": m, "observed_lt_mean_days": obs,
                     "error_pct": err, "prediction_interval_p": p,
                     "passes": abs(err) <= TARGET_PCT and p >= 0.05})
    df = pd.DataFrame(rows)
    passing = df[df["passes"]]
    df["selected_min_change"] = False
    df["best_fit"] = False
    if len(passing):
        df.loc[passing.index[0], "selected_min_change"] = True
    df.loc[df["error_pct"].abs().idxmin(), "best_fit"] = True
    return df


def kingman_check(cfg: LineConfig, demands: list[float], reps: int = 20) -> pd.DataFrame:
    """Lot-level queue time at steeking and header welding: simulation vs Kingman."""
    rows = []
    for d in demands:
        c = with_demand(cfg, d)
        for op, res_name in (("steeking", "steeking_crew"), ("header_welding", "header_welder")):
            wq, ia, sv, util = [], [], [], []
            for r in range(reps):
                res = simulate(c, rep=r)
                ev = res.evas.dropna(subset=[f"{op}_start", f"{op}_end"])
                g = ev.groupby("order").agg(arr=(f"{op}_ready", "min"),
                                            start=(f"{op}_start", "min"),
                                            end=(f"{op}_end", "max"))
                g["svc"] = ev.assign(dur=ev[f"{op}_end"] - ev[f"{op}_start"]).groupby(
                    "order")["dur"].sum()
                g = g.sort_values("arr")
                g = g[g["arr"].between(res.win.start, res.win.end)]
                wq += list(g["start"] - g["arr"])
                ia += list(np.diff(g["arr"].to_numpy()))
                sv += list(g["svc"])
                util.append(float(res.resources.set_index("resource").loc[res_name, "busy"]))
            ia_a, sv_a = np.asarray(ia), np.asarray(sv)
            ca2 = float(ia_a.var(ddof=1) / ia_a.mean() ** 2)
            cs2 = float(sv_a.var(ddof=1) / sv_a.mean() ** 2)
            rho = float(np.mean(util))
            k = eq.kingman_wq(ca2, cs2, rho, float(sv_a.mean()))
            ca2_rel = float(cfg.raw["demand"]["interarrival_cv"]) ** 2
            k_rel = eq.kingman_wq(ca2_rel, cs2, rho, float(sv_a.mean()))
            w = float(np.mean(wq))
            rows.append({"demand_eva_per_week": d, "station": op, "rho_sim": rho,
                         "ca2_measured": ca2, "ca2_release": ca2_rel, "cs2_sim": cs2,
                         "t_e_lot_min": float(sv_a.mean()), "wq_sim_min": w,
                         "wq_kingman_measured_ca2_min": k, "wq_kingman_release_ca2_min": k_rel,
                         "bracketed": bool(min(k, k_rel) <= w <= max(k, k_rel)),
                         "lots": len(wq)})
    return pd.DataFrame(rows)
