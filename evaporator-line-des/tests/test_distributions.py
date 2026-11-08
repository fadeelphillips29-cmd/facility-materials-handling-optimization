"""Random-variate generation and distribution fitting."""

from __future__ import annotations

import numpy as np
import pytest

from evapsim.distributions import (
    fit_candidates,
    lognormal_from_z,
    lognormal_params,
    sample_lognormal,
)


@pytest.mark.parametrize("mean,cv", [(42, 0.15), (78, 0.20), (120, 0.15)])
def test_lognormal_moments(mean, cv):
    rng = np.random.default_rng(1)
    x = sample_lognormal(rng, mean, cv, 400_000)
    assert x.mean() == pytest.approx(mean, rel=0.005)
    assert x.std() / x.mean() == pytest.approx(cv, rel=0.02)


def test_lognormal_from_z_matches_params():
    mu, sigma = lognormal_params(78, 0.2)
    assert lognormal_from_z(78, 0.2, 0.0) == pytest.approx(np.exp(mu))
    assert lognormal_from_z(78, 0.2, 1.0) == pytest.approx(np.exp(mu + sigma))
    assert lognormal_from_z(78, 0.0, 2.5) == 78  # deterministic mode


def test_fit_recovers_lognormal():
    rng = np.random.default_rng(3)
    x = sample_lognormal(rng, 60, 0.1, 2000)
    fits = {f.distribution: f for f in fit_candidates(x)}
    assert fits["lognormal"].fitted_mean == pytest.approx(60, rel=0.01)
    assert fits["lognormal"].aic <= fits["weibull"].aic
    assert fits["lognormal"].ks_pvalue > 0.05
