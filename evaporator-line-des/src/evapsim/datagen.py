"""Generation of the illustrative data sets (fixed seeds, byte-reproducible).

* ``data/time_study_samples.csv``: 40 synthetic stopwatch observations per
  operation, drawn from lognormal(standard time, CV) and rounded to 0.1 min.
  The fin press is observed per job (3 EVA). Weld stations are observed per
  coil.
* ``data/observed_weekly_output.csv``: 26 weeks of "measured" weekly output
  and order lead times from a *perturbed* copy of the model (see
  ASSUMPTIONS A31), so validation is meaningful without being exact.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import numpy as np
import pandas as pd

from . import equations as eq
from .config import DATA_DIR, LineConfig, apply_overrides, load_config
from .distributions import sample_lognormal

TIME_STUDY_SEED = 3131
OBSERVED_SEED = 4242
N_OBS = 40
FIN_PRESS_JOB_CV = 0.10
PERTURB = {"process_sd": 0.04, "procurement_sd": 0.06}
OBSERVED_WEEKS = 26
FIRST_WEEK = dt.date(2026, 1, 5)  # a Monday


def time_study(cfg: LineConfig, seed: int = TIME_STUDY_SEED) -> pd.DataFrame:
    """Synthetic time-study observations (minutes) for every timed operation."""
    rng = np.random.default_rng(seed)
    specs = [("fin_press", "Fin press job (3 EVA)", "evaporator",
              eq.fin_press(**cfg.fin_press).T_job, FIN_PRESS_JOB_CV, "per job (3 EVA)")]
    for op, o in cfg.operations.items():
        specs.append((op, o["label"], o["department"], cfg.op_mean_min(op), float(o["cv"]),
                      "per coil" if "t_op_min" in o else "per EVA"))
    rows = []
    for op, label, dept, mean, cv, basis in specs:
        x = np.asarray(sample_lognormal(rng, mean, cv, N_OBS))
        for i, v in enumerate(x):
            rows.append({"obs_id": f"TS-{op}-{i + 1:02d}", "operation": op, "label": label,
                         "department": dept, "basis": basis,
                         "observer": "A" if i % 2 == 0 else "B",
                         "observed_min": round(float(v), 1)})
    return pd.DataFrame(rows)


def perturbed_config(cfg: LineConfig, seed: int = OBSERVED_SEED) -> tuple[LineConfig,
                                                                           pd.DataFrame]:
    """The 'real system': process means and procurement lead times randomly perturbed."""
    rng = np.random.default_rng(seed)
    ov: dict = {"operations": {}, "lead_times": {}, "fin_press": {}}
    rows = []
    for op in cfg.operations:
        f = float(1 + rng.normal(0, PERTURB["process_sd"]))
        key = "t_op_min" if "t_op_min" in cfg.operations[op] else "mean_min"
        ov["operations"][op] = {key: {"scale": f}}
        rows.append({"item": op, "factor": f})
    f = float(1 + rng.normal(0, PERTURB["process_sd"]))
    ov["fin_press"]["setup_min"] = {"scale": f}
    rows.append({"item": "fin_press.setup_min", "factor": f})
    for k in ("procurement_sheet_metal", "procurement_tubing"):
        f = float(1 + rng.normal(0, PERTURB["procurement_sd"]))
        ov["lead_times"][k] = {"mean_days": {"scale": f}}
        rows.append({"item": k, "factor": f})
    return apply_overrides(cfg, ov), pd.DataFrame(rows)


def observed_weekly(cfg: LineConfig, seed: int = OBSERVED_SEED) -> pd.DataFrame:
    """Run the perturbed system once and export 26 weeks of weekly output and lead times."""
    from .model import simulate

    real, _ = perturbed_config(cfg, seed)
    real = apply_overrides(real, {"simulation": {"measure_weeks": OBSERVED_WEEKS}})
    res = simulate(real, rep=0, base_seed=seed)
    orders = res.orders[res.orders["completed_in_window"]]
    rows = []
    for w in range(OBSERVED_WEEKS):
        wk = orders[orders["completion_week"] == w]
        rows.append({
            "week": w + 1,
            "week_start": (FIRST_WEEK + dt.timedelta(weeks=w)).isoformat(),
            "eva_completed": int(res.weekly_output[w]),
            "orders_completed": len(wk),
            "order_ids": ";".join(f"WO{int(i):04d}" for i in wk["order"]),
            "order_lead_times_days": ";".join(f"{v:.1f}" for v in wk["lead_time_days"]),
            "mean_order_lead_time_days": round(float(wk["lead_time_days"].mean()), 2)
            if len(wk) else np.nan,
        })
    return pd.DataFrame(rows)


def write_time_study(cfg: LineConfig | None = None, out_dir: Path = DATA_DIR) -> Path:
    """Write ``time_study_samples.csv``."""
    path = Path(out_dir) / "time_study_samples.csv"
    time_study(cfg or load_config()).to_csv(path, index=False)
    return path


def write_observed(cfg: LineConfig | None = None, out_dir: Path = DATA_DIR) -> Path:
    """Write ``observed_weekly_output.csv``."""
    path = Path(out_dir) / "observed_weekly_output.csv"
    observed_weekly(cfg or load_config()).to_csv(path, index=False)
    return path
