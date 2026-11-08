"""Random-variate generation and distribution fitting."""

from __future__ import annotations

import numpy as np
import pytest

from evapsim.distributions import fit_candidates, sample_lognormal, variate_from_z, weibull_shape


@pytest.mark.parametrize("family", ["lognormal", "gamma", "weibull"])
def test_family_moments(family):
    z = np.random.default_rng(7).standard_normal(60_000)
    x = np.array([variate_from_z(family, 420.0, 0.2, v) for v in z])
    assert x.mean() == pytest.approx(420, rel=0.01)
    assert x.std() / x.mean() == pytest.approx(0.2, rel=0.03)


def test_variates_monotone_in_z_and_deterministic_at_cv0():
    for fam in ("lognormal", "gamma", "weibull"):
        assert variate_from_z(fam, 100, 0.15, -1.0) < variate_from_z(fam, 100, 0.15, 1.0)
        assert variate_from_z(fam, 100, 0.0, 1.7) == 100


def test_weibull_shape_cv():
    assert weibull_shape(1.0) == pytest.approx(1.0, abs=1e-6)   # exponential
    assert 5 < weibull_shape(0.2) < 6


def test_fit_recovers_lognormal():
    x = sample_lognormal(np.random.default_rng(3), 90, 0.15, 3000)
    fits = {f.distribution: f for f in fit_candidates(x)}
    assert fits["lognormal"].fitted_mean == pytest.approx(90, rel=0.01)
    assert fits["lognormal"].ks_pvalue > 0.05
