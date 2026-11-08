"""Random-variate generation and input-distribution fitting.

Cycle times are lognormal, parameterised by their *mean* and *coefficient of
variation* (CV) because those are the quantities a time-study engineer reports.
For a lognormal with mean ``m`` and CV ``c``::

    sigma^2 = ln(1 + c^2)
    mu      = ln(m) - sigma^2 / 2

A variate is then ``exp(mu + sigma * z)`` with ``z ~ N(0, 1)``. Passing the
standard normal ``z`` explicitly lets the model attach pre-drawn normals to each
unit, which keeps common random numbers synchronised across scenarios.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats


def lognormal_params(mean: float, cv: float) -> tuple[float, float]:
    """Return ``(mu, sigma)`` of the underlying normal for a lognormal with ``mean`` and ``cv``."""
    if mean <= 0:
        raise ValueError("mean must be > 0")
    if cv < 0:
        raise ValueError("cv must be >= 0")
    sigma2 = math.log1p(cv * cv)
    return math.log(mean) - 0.5 * sigma2, math.sqrt(sigma2)


def lognormal_from_z(mean: float, cv: float, z: float) -> float:
    """Transform a standard-normal draw ``z`` into a lognormal(mean, cv) variate.

    With ``cv == 0`` the mean is returned exactly (deterministic mode).
    """
    if cv == 0:
        return mean
    mu, sigma = lognormal_params(mean, cv)
    return math.exp(mu + sigma * z)


def sample_lognormal(
    rng: np.random.Generator, mean: float, cv: float, size: int | None = None
) -> np.ndarray | float:
    """Draw lognormal variates with the given mean and CV."""
    if cv == 0:
        return np.full(size, mean) if size is not None else mean
    mu, sigma = lognormal_params(mean, cv)
    return rng.lognormal(mu, sigma, size)


def sample_exponential(rng: np.random.Generator, mean: float) -> float:
    """Draw one exponential variate with the given mean."""
    return float(rng.exponential(mean))


# ---------------------------------------------------------------- input analysis
CANDIDATES: dict[str, stats.rv_continuous] = {
    "lognormal": stats.lognorm,
    "gamma": stats.gamma,
    "weibull": stats.weibull_min,
}


@dataclass(frozen=True)
class FitResult:
    """Result of fitting one candidate distribution to one sample."""

    distribution: str
    params: tuple[float, ...]
    loglik: float
    aic: float
    ks_stat: float
    ks_pvalue: float
    fitted_mean: float
    fitted_cv: float


def fit_candidates(x: np.ndarray) -> list[FitResult]:
    """Fit lognormal, gamma and Weibull (location fixed at 0) by maximum likelihood.

    Returns one :class:`FitResult` per candidate with log-likelihood, AIC
    (2k - 2 lnL, k = 2 free parameters each) and the one-sample
    Kolmogorov-Smirnov statistic and p-value. Note that KS p-values are
    optimistic when parameters are estimated from the same data; they are used
    here as a goodness-of-fit screen, and AIC is the ranking criterion.
    """
    x = np.asarray(x, dtype=float)
    out: list[FitResult] = []
    for name, dist in CANDIDATES.items():
        params = dist.fit(x, floc=0)
        ll = float(np.sum(dist.logpdf(x, *params)))
        k = 2
        ks = stats.kstest(x, dist.cdf, args=params)
        mean, var = dist.stats(*params, moments="mv")
        out.append(
            FitResult(
                distribution=name,
                params=tuple(float(p) for p in params),
                loglik=ll,
                aic=2 * k - 2 * ll,
                ks_stat=float(ks.statistic),
                ks_pvalue=float(ks.pvalue),
                fitted_mean=float(mean),
                fitted_cv=float(math.sqrt(var) / mean),
            )
        )
    return out


def ppf(result: FitResult, q: np.ndarray) -> np.ndarray:
    """Quantile function of a fitted candidate (used for QQ plots)."""
    return CANDIDATES[result.distribution].ppf(q, *result.params)


def pdf(result: FitResult, x: np.ndarray) -> np.ndarray:
    """Density of a fitted candidate (used for histogram overlays)."""
    return CANDIDATES[result.distribution].pdf(x, *result.params)
