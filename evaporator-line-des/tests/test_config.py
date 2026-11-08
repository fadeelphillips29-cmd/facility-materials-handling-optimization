"""Configuration loading, validation and scenario overrides."""

from __future__ import annotations

import pytest

from evapsim.config import ConfigError, apply_overrides, load_scenarios


def test_baseline_values(base_cfg):
    assert base_cfg.n_stations == 7
    assert base_cfg.takt_s == pytest.approx(480 * 60 / 380)
    assert base_cfg.mix_ct_multiplier == pytest.approx(1.005)
    assert base_cfg.station(4).servers == 1
    assert base_cfg.station(6).servers == 2
    assert not base_cfg.station(6).has_breakdowns
    assert base_cfg.buffer_capacities == (5, 5, 5, 5, 5, 5)
    assert base_cfg.release.rule == "conwip" and base_cfg.release.conwip_limit == 40


def test_scale_and_range_overrides(base_cfg):
    cfg = apply_overrides(base_cfg, {"stations": {"1-5": {"mtbf_min": {"scale": 1.25}}}})
    assert cfg.station(4).mtbf_min == pytest.approx(225)
    assert cfg.station(6).mtbf_min is None  # disabled feature stays disabled
    assert base_cfg.station(4).mtbf_min == 180  # base config untouched


def test_buffer_all_override(base_cfg):
    cfg = apply_overrides(base_cfg, {"buffers": {"all": 8}})
    assert cfg.buffer_capacities == (8,) * 6


def test_scenarios_resolve_extends(base_cfg):
    sc = load_scenarios(base_cfg)
    assert list(sc)[:6] == ["S0", "S1", "S2", "S3", "S4", "S5"]
    s5 = sc["S5"].config
    assert s5.station(4).changeover_min == pytest.approx(7.2)
    assert s5.station(2).changeover_min == pytest.approx(6.0)
    assert s5.station(4).mttr_min == pytest.approx(25 * 0.85)
    assert s5.buffer_capacities == (8,) * 6
    assert s5.station(4).servers == 1
    assert sc["S6"].config.station(4).servers == 2


@pytest.mark.parametrize("bad", [
    {"products": [{"name": "A", "mix": 0.5, "ct_multiplier": 1.0}]},
    {"buffers": {"capacities": [5, 5]}},
    {"release": {"rule": "kanban"}},
    {"stations": {3: {"ct_mean_s": -1}}},
    {"stations": {2: {"mttr_min": None}}},
])
def test_invalid_configs_rejected(base_cfg, bad):
    with pytest.raises(ConfigError):
        apply_overrides(base_cfg, bad)
