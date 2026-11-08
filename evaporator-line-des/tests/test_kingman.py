"""Kingman / Pollaczek-Khinchine agreement on a single-station test bench.

The bench uses the same TimedResource class as the full model: Poisson
arrivals, lognormal service with CV 0.5 and rho = 0.7. For ca^2 = 1, Kingman's
formula equals the exact M/G/1 Pollaczek-Khinchine result.
"""

from __future__ import annotations

import numpy as np
import pytest
import simpy

from evapsim.distributions import lognormal_from_z
from evapsim.equations import kingman_wq
from evapsim.resources import TimedResource, Window


def _mg1(seed: int, n: int, rho: float, t_e: float, cs: float) -> float:
    env = simpy.Environment()
    rng = np.random.default_rng(seed)
    res = TimedResource(env, "bench", 1, Window(0.0, 1e12, 1.0))
    waits: list[float] = []

    def customer(z: float):
        t0 = env.now
        with res.request() as req:
            yield req
            waits.append(env.now - t0)
            yield from res.hold(lognormal_from_z(t_e, cs, z), "busy", "bench")

    def source():
        for _ in range(n):
            env.process(customer(float(rng.standard_normal())))
            yield env.timeout(float(rng.exponential(t_e / rho)))

    env.process(source())
    env.run()
    return float(np.mean(waits[n // 10:]))


def test_kingman_single_station_agreement():
    rho, t_e, cs = 0.7, 10.0, 0.5
    sim = np.mean([_mg1(s, 60_000, rho, t_e, cs) for s in range(3)])
    assert sim == pytest.approx(kingman_wq(1.0, cs * cs, rho, t_e), rel=0.06)
