"""Shared fixtures: short-horizon configurations so the suite runs in seconds."""

from __future__ import annotations

import pytest

from evapsim.config import LineConfig, apply_overrides, load_config


@pytest.fixture(scope="session")
def base_cfg() -> LineConfig:
    """The baseline configuration exactly as in config/line_parameters.yaml."""
    return load_config()


@pytest.fixture(scope="session")
def short_cfg(base_cfg: LineConfig) -> LineConfig:
    """Baseline with a 6-day horizon (1 warm-up + 5 measured) for fast tests."""
    return apply_overrides(base_cfg, {"simulation": {"days": 5}})


@pytest.fixture(scope="session")
def deterministic_cfg(base_cfg: LineConfig) -> LineConfig:
    """Zero variance, no breakdowns, no scrap, no changeovers, one product.

    The hand-calculated throughput is 1 / max_i(CT_i / servers_i) = 1 / 78 s.
    """
    return apply_overrides(base_cfg, {
        "simulation": {"deterministic": True, "breakdowns": False, "days": 5},
        "products": [{"name": "Medium", "mix": 1.0, "ct_multiplier": 1.0}],
        "stations": {"all": {"scrap_rate": 0.0, "changeover_min": 0.0}},
    })
