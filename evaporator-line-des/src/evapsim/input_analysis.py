"""Phase 2 - input analysis of the time-study samples.

For every station the 40 observations are fitted with lognormal, gamma and
Weibull distributions (MLE, location fixed at zero), compared by AIC and the
Kolmogorov-Smirnov test, and plotted (histogram + Q-Q). The sample mean and CV
are also checked against the engineering standard in ``line_parameters.yaml``.

Selection rule (documented in BUILD_PHASES.md):
    1. Discard candidates rejected by KS at alpha = 0.05.
    2. Among the rest, prefer lognormal whenever its AIC is within 2 units of
       the best (Burnham & Anderson: delta-AIC < 2 means "substantial support",
       i.e. statistically indistinguishable); lognormal is preferred on
       physical grounds (strictly positive, right-skewed, multiplicative
       sources of variation) and keeps one family across the model.
    3. Otherwise take the lowest-AIC candidate.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .config import DATA_DIR, FIGURES_DIR, RESULTS_DIR, LineConfig, load_config
from .distributions import fit_candidates
from .plots import input_fit_figure

ALPHA = 0.05
DELTA_AIC_TOLERANCE = 2.0
PREFERRED = "lognormal"


def select_distribution(fits: pd.DataFrame) -> str:
    """Apply the selection rule to one station's fit table."""
    ok = fits[fits["ks_pvalue"] >= ALPHA]
    if ok.empty:
        ok = fits
    best_aic = ok["aic"].min()
    pref = ok[ok["distribution"] == PREFERRED]
    if not pref.empty and pref["aic"].iloc[0] - best_aic <= DELTA_AIC_TOLERANCE:
        return PREFERRED
    return str(ok.loc[ok["aic"].idxmin(), "distribution"])


def run_input_analysis(
    cfg: LineConfig | None = None,
    samples_path: Path = DATA_DIR / "time_study_samples.csv",
    out_dir: Path = RESULTS_DIR,
    fig_dir: Path = FIGURES_DIR,
) -> pd.DataFrame:
    """Fit candidates for every station; write the CSV and figures; return the table."""
    cfg = cfg or load_config()
    data = pd.read_csv(samples_path)
    rows = []
    for st in cfg.stations:
        x = data.loc[data["station_id"] == st.id, "observed_time_s"].to_numpy(float)
        n = len(x)
        mean, sd = float(np.mean(x)), float(np.std(x, ddof=1))
        half = float(stats.t.ppf(0.975, n - 1) * sd / np.sqrt(n))
        fits = fit_candidates(x)
        tab = pd.DataFrame([f.__dict__ for f in fits])
        chosen = select_distribution(tab)
        best_aic = tab["aic"].min()
        for f in fits:
            rows.append(
                {
                    "station_id": st.id,
                    "station_name": st.name,
                    "n": n,
                    "sample_mean_s": round(mean, 2),
                    "sample_cv": round(sd / mean, 3),
                    "mean_ci95_low_s": round(mean - half, 2),
                    "mean_ci95_high_s": round(mean + half, 2),
                    "spec_mean_s": st.ct_mean_s,
                    "spec_cv": st.ct_cv,
                    "spec_mean_in_ci": bool(mean - half <= st.ct_mean_s <= mean + half),
                    "distribution": f.distribution,
                    "param_shape": round(f.params[0], 4),
                    "param_scale": round(f.params[2], 4),
                    "loglik": round(f.loglik, 3),
                    "aic": round(f.aic, 3),
                    "delta_aic": round(f.aic - best_aic, 3),
                    "ks_stat": round(f.ks_stat, 4),
                    "ks_pvalue": round(f.ks_pvalue, 4),
                    "ks_pass": bool(f.ks_pvalue >= ALPHA),
                    "fitted_mean_s": round(f.fitted_mean, 2),
                    "fitted_cv": round(f.fitted_cv, 3),
                    "selected": f.distribution == chosen,
                }
            )
        input_fit_figure(
            x,
            fits,
            title=f"Station {st.id} - {st.name}: time-study fit (Medium model, n={n})",
            selected=chosen,
            path=Path(fig_dir) / f"input_fit_S{st.id}.png",
        )
    out = pd.DataFrame(rows)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out.to_csv(Path(out_dir) / "input_analysis.csv", index=False)
    return out
