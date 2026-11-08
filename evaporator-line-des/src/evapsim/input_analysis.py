"""Phase 3: fit lognormal, gamma and Weibull distributions to the time-study samples.

Selection rule:
    1. Drop candidates that the Kolmogorov-Smirnov test rejects at alpha = 0.05.
    2. Prefer the lognormal if its AIC is within 2 units of the best, because the
       difference is then statistically insignificant (Burnham & Anderson). The
       lognormal is positive and right-skewed, and its multiplicative variation
       matches manual work. It is also set directly from the mean and CV of a
       standard time.
    3. Otherwise take the candidate with the lowest AIC.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

from .config import DATA_DIR, FIGURES_DIR, RESULTS_DIR
from .distributions import fit_candidates
from .plots import input_fit_figure

ALPHA = 0.05
DELTA_AIC = 2.0
PREFERRED = "lognormal"
FIGURE_OPS = ("fin_press", "steeking", "header_welding", "weld_hairpins")


def select(tab: pd.DataFrame) -> str:
    """Apply the selection rule to one operation's fit table."""
    ok = tab[tab["ks_pvalue"] >= ALPHA]
    ok = tab if ok.empty else ok
    best = ok["aic"].min()
    pref = ok[ok["distribution"] == PREFERRED]
    if not pref.empty and pref["aic"].iloc[0] - best <= DELTA_AIC:
        return PREFERRED
    return str(ok.loc[ok["aic"].idxmin(), "distribution"])


def run_input_analysis(samples: Path = DATA_DIR / "time_study_samples.csv",
                       out_dir: Path = RESULTS_DIR, fig_dir: Path = FIGURES_DIR) -> pd.DataFrame:
    """Fit every operation, write ``input_analysis.csv`` and Q-Q/histogram figures."""
    data = pd.read_csv(samples)
    rows = []
    for op, g in data.groupby("operation", sort=False):
        x = g["observed_min"].to_numpy(float)
        n = len(x)
        mean, sd = float(x.mean()), float(x.std(ddof=1))
        half = float(stats.t.ppf(0.975, n - 1) * sd / np.sqrt(n))
        fits = fit_candidates(x)
        tab = pd.DataFrame([f.__dict__ for f in fits])
        chosen = select(tab)
        best = tab["aic"].min()
        for f in fits:
            rows.append({
                "operation": op, "label": g["label"].iloc[0], "basis": g["basis"].iloc[0],
                "n": n, "sample_mean_min": mean, "sample_cv": sd / mean,
                "mean_ci95_low": mean - half, "mean_ci95_high": mean + half,
                "distribution": f.distribution, "aic": f.aic, "delta_aic": f.aic - best,
                "ks_stat": f.ks_stat, "ks_pvalue": f.ks_pvalue, "ks_pass": f.ks_pvalue >= ALPHA,
                "fitted_mean_min": f.fitted_mean, "fitted_cv": f.fitted_cv,
                "selected": f.distribution == chosen,
            })
        if op in FIGURE_OPS:
            input_fit_figure(x, fits, f"{g['label'].iloc[0]}: time-study fit (n={n}, "
                             f"{g['basis'].iloc[0]})", chosen, "min",
                             Path(fig_dir) / f"input_fit_{op}.png")
    out = pd.DataFrame(rows)
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    out.round(4).to_csv(Path(out_dir) / "input_analysis.csv", index=False)
    return out
