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
from functools import lru_cache

import numpy as np
from scipy import optimize, stats


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


def lognormal_mean_cv(rng: np.random.Generator, mean: float, cv: float) -> float:
    """One lognormal(mean, cv) variate (``mean`` itself when cv == 0)."""
    if cv == 0 or mean == 0:
        return float(mean)
    mu, sigma = lognormal_params(mean, cv)
    return float(rng.lognormal(mu, sigma))


FAMILIES = ("lognormal", "gamma", "weibull")


@lru_cache(maxsize=256)
def weibull_shape(cv: float) -> float:
    """Weibull shape k whose coefficient of variation equals ``cv``."""
    def f(k: float) -> float:
        g1, g2 = math.gamma(1 + 1 / k), math.gamma(1 + 2 / k)
        return math.sqrt(g2 / g1 ** 2 - 1) - cv
    return float(optimize.brentq(f, 0.2, 200.0))


def variate_from_z(family: str, mean: float, cv: float, z: float) -> float:
    """Variate of ``family`` with the given mean and CV, driven by a standard normal ``z``.

    The lognormal is evaluated in closed form. Gamma and Weibull use the inverse
    CDF at u = Phi(z), so the same pre-drawn normal gives a monotone mapping
    in every family. Common random numbers are therefore kept when the family
    changes.
    """
    if cv == 0 or mean == 0:
        return float(mean)
    if family == "lognormal":
        return lognormal_from_z(mean, cv, z)
    u = float(stats.norm.cdf(z))
    if family == "gamma":
        a = 1.0 / (cv * cv)
        return float(stats.gamma.ppf(u, a, scale=mean / a))
    if family == "weibull":
        k = weibull_shape(round(cv, 10))
        lam = mean / math.gamma(1 + 1 / k)
        return float(lam * (-math.log1p(-u)) ** (1 / k))
    raise ValueError(f"unknown distribution family '{family}'")
