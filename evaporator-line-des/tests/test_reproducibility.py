"""Seeds, common random numbers and parallel/serial equivalence."""

from __future__ import annotations

import numpy as np

from evapsim.config import apply_overrides
from evapsim.metrics import paired_difference
from evapsim.model import simulate_replication
from evapsim.runner import run_replications


def test_same_seed_same_result(short_cfg):
    a = simulate_replication(short_cfg, rep=4)
    b = simulate_replication(short_cfg, rep=4)
    assert np.array_equal(a.daily_output, b.daily_output)
    assert np.array_equal(a.lead_times_min, b.lead_times_min)
    assert np.array_equal(a.state_time_s, b.state_time_s)


def test_different_replications_differ(short_cfg):
    a = simulate_replication(short_cfg, rep=0)
    b = simulate_replication(short_cfg, rep=1)
    assert not np.array_equal(a.daily_output, b.daily_output)


def test_base_seed_changes_results(short_cfg):
    a = simulate_replication(short_cfg, rep=0)
    b = simulate_replication(short_cfg, rep=0, base_seed=short_cfg.sim.base_seed + 1)
    assert not np.array_equal(a.lead_times_min, b.lead_times_min)


def test_parallel_equals_serial(short_cfg):
    s = run_replications(short_cfg, 6, workers=1)
    p = run_replications(short_cfg, 6, workers=3)
    assert s.reps.equals(p.reps)


def test_quick_reps_are_prefix_of_full_run(short_cfg):
    a = run_replications(short_cfg, 3, workers=1).reps
    b = run_replications(short_cfg, 5, workers=1).reps.iloc[:3].reset_index(drop=True)
    assert a.equals(b)


def test_common_random_numbers_induce_positive_correlation(short_cfg):
    smed = apply_overrides(short_cfg, {"stations": {4: {"changeover_min": {"scale": 0.6}}}})
    base = run_replications(short_cfg, 12, workers=1).reps["throughput_per_day"]
    alt = run_replications(smed, 12, workers=1).reps["throughput_per_day"]
    d = paired_difference(base.to_numpy(), alt.to_numpy())
    assert d["crn_corr"] > 0.5
    assert d["diff_mean"] > 0
