"""Model verification: hand calculations, Little's law, conservation, logic checks."""

from __future__ import annotations

import numpy as np
import pytest

from evapsim.config import apply_overrides
from evapsim.metrics import replication_metrics
from evapsim.model import simulate_replication
from evapsim.pipeline import static_capacity


def test_deterministic_throughput_equals_bottleneck_rate(deterministic_cfg):
    """Zero variance, no failures: TH = 1 / bottleneck CT = 28 800 s / 78 s per day."""
    res = simulate_replication(deterministic_cfg)
    expected = deterministic_cfg.day_seconds / 78.0  # 369.23 units/day
    assert res.daily_output.mean() == pytest.approx(expected, abs=1.0)
    assert set(res.daily_output) <= {369, 370}
    assert res.scrapped == 0
    shares = res.state_time_s / (res.servers[:, None] * res.measure_s)
    assert shares[3, 0] == pytest.approx(1.0, abs=1e-6)  # brazing never idle
    assert shares[:, 3].sum() == 0 and shares[:, 4].sum() == 0  # no down, no changeover


def test_deterministic_bottleneck_moves_with_second_fixture(deterministic_cfg):
    """With 2 brazing fixtures (78/2 = 39 s) the binding station is S6: 120 s / 2 = 60 s."""
    cfg = apply_overrides(deterministic_cfg, {"stations": {4: {"servers": 2}}})
    res = simulate_replication(cfg)
    assert res.daily_output.mean() == pytest.approx(cfg.day_seconds / 60.0, abs=1.0)


def test_deterministic_changeover_hand_calculation(deterministic_cfg):
    """Two models, 12-min changeover at St 4 only, no warm-up.

    Brazing is never blocked (downstream is faster) and only starved while the
    line first fills (42 + 55 + 48 = 145 s), so over the horizon T:
        busy + changeover + 145 s = T,  changeover = 720 s x number of switches,
        units brazed = busy / 78 s,  output = units brazed - units still downstream.
    """
    cfg = apply_overrides(deterministic_cfg, {
        "products": [{"name": "A", "mix": 0.5, "ct_multiplier": 1.0},
                     {"name": "B", "mix": 0.5, "ct_multiplier": 1.0}],
        "stations": {4: {"changeover_min": 12.0}},
        "simulation": {"warmup_days": 0},
    })
    res = simulate_replication(cfg)
    total = res.measure_s
    busy, starved, blocked, _, co = res.state_time_s[3]
    n_co = res.changeovers_by_station[3]
    assert n_co > 0
    assert blocked == pytest.approx(0.0, abs=1e-6)
    assert starved == pytest.approx(145.0, abs=1e-6)
    assert co == pytest.approx(720.0 * n_co, abs=720.0)  # last one may be cut off
    assert busy + co + starved == pytest.approx(total)
    brazed = busy / 78.0
    assert brazed - 8 <= res.good <= brazed
    hand_th = (total - 145.0 - 720.0 * n_co) / 78.0 / cfg.sim.days
    assert res.daily_output.mean() == pytest.approx(hand_th, abs=2.0)


def test_littles_law(short_cfg):
    res = simulate_replication(short_cfg, rep=3)
    m = replication_metrics(res, short_cfg)
    assert m["littles_wip"] == pytest.approx(m["wip_avg"], rel=0.03)


def test_conservation_of_units(short_cfg):
    res = simulate_replication(short_cfg, rep=1, keep_units=True)
    assert res.total_released == res.total_departed + res.wip_end
    assert len(res.units) == res.total_departed
    good = sum(1 for u in res.units if u["status"] == "good")
    scrap = sum(1 for u in res.units if u["status"].startswith("scrap"))
    assert good + scrap == res.total_departed
    # window counters are a subset of the whole-run counters
    assert res.good + res.scrapped <= res.total_departed
    assert res.daily_output.sum() == res.good


def test_conwip_limit_respected(short_cfg):
    res = simulate_replication(short_cfg)
    assert res.max_wip <= short_cfg.release.conwip_limit
    tight = apply_overrides(short_cfg, {"release": {"conwip_limit": 8}})
    r2 = simulate_replication(tight)
    assert r2.max_wip <= 8
    assert r2.wip_avg < res.wip_avg


def test_unlimited_release_bounded_by_buffers(short_cfg):
    cfg = apply_overrides(short_cfg, {"release": {"rule": "unlimited"}})
    res = simulate_replication(cfg)
    physical = sum(cfg.buffer_capacities) + sum(s.servers for s in cfg.stations)
    assert res.max_wip <= physical + 3  # +rework units that bypass slots


def test_timestamps_are_ordered(short_cfg):
    res = simulate_replication(short_cfg, keep_units=True)
    for u in res.units:
        if u["status"] != "good" or u["reworks"]:
            continue
        starts = [u[f"start_S{i}"] for i in range(1, 8)]
        ends = [u[f"end_S{i}"] for i in range(1, 8)]
        assert u["release_s"] <= starts[0]
        assert all(s <= e for s, e in zip(starts, ends, strict=True))
        assert all(ends[i] <= starts[i + 1] for i in range(6))
        assert ends[-1] == pytest.approx(u["depart_s"])


def test_state_shares_sum_to_one(short_cfg):
    res = simulate_replication(short_cfg)
    shares = res.state_time_s / (res.servers[:, None] * res.measure_s)
    assert np.allclose(shares.sum(axis=1), 1.0, atol=1e-9)


def test_rework_loop_no_deadlock_under_stress(short_cfg):
    """Heavy test failures, all reworked, tiny buffers: the line must keep flowing."""
    cfg = apply_overrides(short_cfg, {
        "stations": {5: {"scrap_rate": 0.4}},
        "rework": {"rework_share": 1.0},
        "buffers": {"all": 1},
    })
    res = simulate_replication(cfg, keep_units=True)
    assert res.reworked > 0
    assert res.daily_output.min() > 0
    assert max(u["reworks"] for u in res.units) <= cfg.rework.max_reworks_per_unit


def test_blocking_increases_with_smaller_buffers(short_cfg):
    def blocked(cap):
        r = simulate_replication(apply_overrides(short_cfg, {"buffers": {"all": cap}}))
        return (r.state_time_s[:3, 2] / r.measure_s).sum(), r.daily_output.mean()

    b1, th1 = blocked(1)
    b10, th10 = blocked(10)
    assert b1 > b10
    assert th1 < th10


def test_static_capacity_upper_bound(base_cfg, short_cfg):
    cap = static_capacity(base_cfg)
    assert int(cap.loc[cap.capacity_per_day.idxmin(), "station_id"]) == 4
    res = simulate_replication(short_cfg)
    assert res.daily_output.mean() < cap.capacity_per_day.min()
