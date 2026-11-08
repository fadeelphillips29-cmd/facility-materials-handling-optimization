"""Phase 6 - operational validation against the (fictional) observed line data.

The observed record covers 20 production days. The simulation produces 500
independent 20-day periods (replications) of the nominal model. Validation asks:
*could the observed 20-day period plausibly have come from the model?*

For each headline measure (mean daily output, mean batch lead time):

1. **% error** of the simulated mean against the observed mean, with a target
   of |error| <= 5 %.
2. **Prediction-interval test**: the observed 20-day mean is compared with the
   distribution of simulated 20-day means. The empirical two-sided p-value is
   2 x min(P(sim <= obs), P(sim >= obs)). If p >= 0.05, the model is not
   rejected.
3. **Welch two-sample t-test** of the observed values against simulated
   values. Daily output uses one day per replication, so the simulated sample
   is independent. Batch lead time uses the replication means.

Station utilisation is compared station by station (mean absolute error,
in percentage points). The VSM gemba-walk snapshot in the YAML is compared
with the simulated uptime, first-pass yield (FPY) and inventory in front of
each station.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from . import plots
from .config import DATA_DIR, LineConfig, load_config

TARGET_ERROR_PCT = 5.0
ALPHA = 0.05


def load_observed(path: Path = DATA_DIR / "observed_line_data.csv") -> dict[str, pd.DataFrame]:
    """Split the long-format observed data into its three record types."""
    df = pd.read_csv(path)
    return {k: g.reset_index(drop=True) for k, g in df.groupby("record_type")}


def _empirical_p(sim: np.ndarray, obs: float) -> float:
    sim = np.asarray(sim, float)
    lo = (np.sum(sim <= obs) + 1) / (len(sim) + 1)
    hi = (np.sum(sim >= obs) + 1) / (len(sim) + 1)
    return float(min(1.0, 2 * min(lo, hi)))


def compare_measure(name: str, unit: str, obs_values: np.ndarray, sim_period_means: np.ndarray,
                    sim_values_for_t: np.ndarray) -> dict[str, object]:
    """Compare one measure (see module docstring) and return a summary row."""
    obs_mean = float(np.mean(obs_values))
    sim_mean = float(np.mean(sim_period_means))
    err = 100.0 * (sim_mean - obs_mean) / obs_mean
    pi_lo, pi_hi = np.percentile(sim_period_means, [2.5, 97.5])
    p_emp = _empirical_p(sim_period_means, obs_mean)
    welch = stats.ttest_ind(obs_values, sim_values_for_t, equal_var=False)
    return {
        "measure": name, "unit": unit, "observed_mean": obs_mean, "n_observed": len(obs_values),
        "simulated_mean": sim_mean, "n_sim_periods": len(sim_period_means),
        "sim_pi95_low": float(pi_lo), "sim_pi95_high": float(pi_hi),
        "error_pct": err, "within_target": bool(abs(err) <= TARGET_ERROR_PCT),
        "prediction_interval_p": p_emp, "welch_t_p": float(welch.pvalue),
        "verdict": "valid" if abs(err) <= TARGET_ERROR_PCT and p_emp >= ALPHA else "investigate",
    }


def run_validation(results_dir: Path, fig_dir: Path, cfg: LineConfig | None = None,
                   observed_path: Path = DATA_DIR / "observed_line_data.csv") -> pd.DataFrame:
    """Validate the baseline results in ``results_dir`` against the observed data.

    Requires the baseline step to have been run (it reads ``baseline_*.csv``).
    Writes ``validation_summary.csv``, ``validation_station_utilisation.csv``,
    ``vsm_observed_vs_simulated.csv`` and ``figures/validation.png``.
    """
    cfg = cfg or load_config()
    results_dir, fig_dir = Path(results_dir), Path(fig_dir)
    obs = load_observed(observed_path)
    reps = pd.read_csv(results_dir / "baseline_replications.csv")
    daily = pd.read_csv(results_dir / "baseline_daily_output.csv")
    stations = pd.read_csv(results_dir / "baseline_stations.csv")
    batches = pd.read_csv(results_dir / "baseline_batch_lead_times.csv")

    obs_out = obs["daily_output"]["value"].to_numpy(float)
    one_day = daily[daily["day"] == (daily["rep"] % cfg.sim.days) + 1]["output"].to_numpy(float)
    obs_blt = obs["batch_lead_time"]["value"].to_numpy(float)
    rows = [
        compare_measure("Mean daily output", "units/day", obs_out,
                        reps["throughput_per_day"].to_numpy(), one_day),
        compare_measure("Mean batch lead time", "min", obs_blt,
                        reps["batch_lt_mean_min"].to_numpy(),
                        reps["batch_lt_mean_min"].to_numpy()),
    ]
    summary = pd.DataFrame(rows)

    util_obs = obs["station_utilisation"].groupby("entity")["value"].mean()
    util = pd.DataFrame({
        "station_id": stations["station_id"],
        "station": stations["station"],
        "observed_utilisation": [util_obs.get(f"S{i}", np.nan) for i in stations["station_id"]],
        "simulated_utilisation": stations["busy"],
    })
    util["abs_error_pp"] = 100 * (util["simulated_utilisation"] - util["observed_utilisation"])
    util["rel_error_pct"] = 100 * (util["simulated_utilisation"] / util["observed_utilisation"]
                                   - 1)
    summary = pd.concat([summary, pd.DataFrame([{
        "measure": "Station utilisation (mean abs. error)", "unit": "percentage points",
        "observed_mean": float(util["observed_utilisation"].mean()),
        "simulated_mean": float(util["simulated_utilisation"].mean()),
        "error_pct": float(util["abs_error_pp"].abs().mean()),
        "within_target": bool(util["rel_error_pct"].abs().max() <= TARGET_ERROR_PCT * 2),
        "verdict": "valid" if util["rel_error_pct"].abs().max() <= TARGET_ERROR_PCT * 2
        else "investigate",
    }])], ignore_index=True)

    vsm = pd.DataFrame([{
        "station_id": st.id, "station": st.name,
        "observed_uptime_pct": st.vsm.uptime_pct,
        "simulated_uptime_pct": 100 * float(stations.loc[stations.station_id == st.id,
                                                         "uptime"].iloc[0]),
        "observed_fpy_pct": st.vsm.first_pass_yield_pct,
        "simulated_fpy_pct": 100 * float(stations.loc[stations.station_id == st.id,
                                                      "fpy"].iloc[0]),
        "observed_inventory_units": st.vsm.inventory_in_front_units,
        "simulated_inventory_units": float(stations.loc[stations.station_id == st.id,
                                                        "buffer_in_front_avg"].iloc[0]),
    } for st in cfg.stations])

    results_dir.mkdir(parents=True, exist_ok=True)
    summary.round(4).to_csv(results_dir / "validation_summary.csv", index=False)
    util.round(4).to_csv(results_dir / "validation_station_utilisation.csv", index=False)
    vsm.round(3).to_csv(results_dir / "vsm_observed_vs_simulated.csv", index=False)
    plots.validation_figure(obs_out, reps["throughput_per_day"].to_numpy(), obs_blt,
                            batches["lead_time_min"].to_numpy(), util, fig_dir / "validation.png")
    return summary
