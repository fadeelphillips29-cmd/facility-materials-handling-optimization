"""Statistical helpers."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from scipy import stats

from evapsim.metrics import paired_difference, summarize, t_ci


def test_t_ci_matches_scipy():
    x = np.array([10.0, 12.0, 11.0, 13.0, 9.0])
    m, h, sd = t_ci(x)
    lo, hi = stats.t.interval(0.95, len(x) - 1, loc=x.mean(), scale=stats.sem(x))
    assert m == pytest.approx(11.0)
    assert m - h == pytest.approx(lo) and m + h == pytest.approx(hi)
    assert sd == pytest.approx(x.std(ddof=1))


def test_paired_difference_detects_shift():
    rng = np.random.default_rng(0)
    a = rng.normal(100, 10, 200)
    b = a + 2 + rng.normal(0, 0.5, 200)
    d = paired_difference(a, b)
    assert d["diff_ci_low"] < 2 < d["diff_ci_high"]
    assert d["significant"] and d["p_value"] < 1e-6
    assert d["crn_corr"] > 0.9


def test_summarize_columns():
    df = pd.DataFrame({"throughput_per_day": [1.0, 2.0, 3.0]})
    s = summarize(df)
    assert s.loc[0, "mean"] == pytest.approx(2.0)
    assert {"ci_low", "ci_high", "label", "unit"} <= set(s.columns)
