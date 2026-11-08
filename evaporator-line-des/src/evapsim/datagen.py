"""Generation of the fictional input and validation data sets.

Two CSV files are produced, both with fixed seeds so they are byte-for-byte
reproducible:

* ``data/time_study_samples.csv`` - 40 stopwatch observations per station of
  the Medium model, drawn from the lognormal(mean, CV) stated in the config and
  rounded to 0.1 s as a stopwatch study would record them.
* ``data/observed_line_data.csv`` - 20 days of "measured" line performance in
  tidy long format (daily output, per-batch lead time, daily station
  utilisation). It is produced by a *perturbed* copy of the model (cycle times,
  MTBF and MTTR randomly shifted by a few percent, and a different seed), so
  validating the nominal model against it is meaningful but not trivially exact.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from .config import DATA_DIR, LineConfig, apply_overrides, load_config
from .distributions import sample_lognormal

TIME_STUDY_SEED = 1101
OBSERVED_SEED = 7707
OBSERVATIONS_PER_STATION = 40
PERTURBATION = {"ct_sd": 0.02, "mtbf_sd": 0.08, "mttr_sd": 0.08}
FIRST_OBSERVED_DAY = dt.date(2026, 3, 2)  # a Monday; weekends are skipped


def generate_time_study(cfg: LineConfig, seed: int = TIME_STUDY_SEED) -> pd.DataFrame:
    """Draw ``OBSERVATIONS_PER_STATION`` cycle-time observations per station."""
    rng = np.random.default_rng(seed)
    rows = []
    for st in cfg.stations:
        x = sample_lognormal(rng, st.ct_mean_s, st.ct_cv, OBSERVATIONS_PER_STATION)
        for i, val in enumerate(np.asarray(x)):
            ws = chr(ord("A") + i % st.servers)
            rows.append(
                {
                    "obs_id": f"TS-{st.id}-{i + 1:02d}",
                    "station_id": st.id,
                    "station_name": st.name,
                    "workstation": f"{st.id}{ws}",
                    "product": "Medium",
                    "study_date": (FIRST_OBSERVED_DAY - dt.timedelta(days=14 - i // 10)).isoformat(),
                    "observed_time_s": round(float(val), 1),
                }
            )
    return pd.DataFrame(rows)


def perturbed_config(cfg: LineConfig, seed: int = OBSERVED_SEED) -> tuple[LineConfig, pd.DataFrame]:
    """Return the "real line" config: nominal parameters with random perturbations.

    The perturbation factors are returned as a DataFrame so the gap between the
    model and the synthetic reality is documented.
    """
    rng = np.random.default_rng(seed)
    ov: dict[int, dict[str, float]] = {}
    rows = []
    for st in cfg.stations:
        f_ct = float(1 + rng.normal(0, PERTURBATION["ct_sd"]))
        f_mtbf = float(1 + rng.normal(0, PERTURBATION["mtbf_sd"]))
        f_mttr = float(1 + rng.normal(0, PERTURBATION["mttr_sd"]))
        ov[st.id] = {"ct_mean_s": {"scale": f_ct}}
        if st.has_breakdowns:
            ov[st.id]["mtbf_min"] = {"scale": f_mtbf}
            ov[st.id]["mttr_min"] = {"scale": f_mttr}
        rows.append(
            {
                "station_id": st.id,
                "ct_factor": f_ct,
                "mtbf_factor": f_mtbf if st.has_breakdowns else np.nan,
                "mttr_factor": f_mttr if st.has_breakdowns else np.nan,
            }
        )
    return apply_overrides(cfg, {"stations": ov}), pd.DataFrame(rows)


def generate_observed(cfg: LineConfig, seed: int = OBSERVED_SEED) -> pd.DataFrame:
    """Simulate the perturbed line once and export it as an MES-style long table."""
    from .model import simulate_replication  # local import: model depends on config only

    real_cfg, _ = perturbed_config(cfg, seed)
    res = simulate_replication(real_cfg, rep=0, base_seed=seed, keep_units=True)
    days = []
    d = FIRST_OBSERVED_DAY
    while len(days) < real_cfg.sim.days:
        if d.weekday() < 5:
            days.append(d)
        d += dt.timedelta(days=1)

    rows = []
    for i, out in enumerate(res.daily_output):
        rows.append(
            {
                "day": i + 1,
                "date": days[i].isoformat(),
                "record_type": "daily_output",
                "entity": "line",
                "value": int(out),
                "unit": "units",
            }
        )
    for i in range(real_cfg.sim.days):
        for st in real_cfg.stations:
            rows.append(
                {
                    "day": i + 1,
                    "date": days[i].isoformat(),
                    "record_type": "station_utilisation",
                    "entity": f"S{st.id}",
                    "value": round(float(res.daily_busy_share[i][st.id - 1]), 3),
                    "unit": "fraction",
                }
            )
    for b in res.batch_records:
        day = int(b["complete_day"])
        rows.append(
            {
                "day": day + 1,
                "date": days[day].isoformat(),
                "record_type": "batch_lead_time",
                "entity": f"B{int(b['batch_id']):04d}",
                "value": round(float(b["lead_time_min"]), 1),
                "unit": "min",
            }
        )
    df = pd.DataFrame(rows)
    order = {"daily_output": 0, "station_utilisation": 1, "batch_lead_time": 2}
    df["_o"] = df["record_type"].map(order)
    return df.sort_values(["day", "_o", "entity"]).drop(columns="_o").reset_index(drop=True)


def write_time_study(cfg: LineConfig | None = None, out_dir: Path = DATA_DIR) -> Path:
    """Generate and save ``time_study_samples.csv``; return its path."""
    cfg = cfg or load_config()
    path = Path(out_dir) / "time_study_samples.csv"
    generate_time_study(cfg).to_csv(path, index=False)
    return path


def write_observed(cfg: LineConfig | None = None, out_dir: Path = DATA_DIR) -> Path:
    """Generate and save ``observed_line_data.csv``; return its path."""
    cfg = cfg or load_config()
    path = Path(out_dir) / "observed_line_data.csv"
    generate_observed(cfg).to_csv(path, index=False)
    return path
