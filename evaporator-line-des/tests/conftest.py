"""Shared fixtures."""

from __future__ import annotations

import pytest

from evapsim.config import LineConfig, apply_overrides, load_config


@pytest.fixture(scope="session")
def base_cfg() -> LineConfig:
    """Baseline configuration exactly as in config/line_parameters.yaml."""
    return load_config()


@pytest.fixture(scope="session")
def det_cfg(base_cfg: LineConfig) -> LineConfig:
    """Deterministic verification mode with a short horizon."""
    return apply_overrides(base_cfg, {"simulation": {"deterministic": True, "measure_weeks": 26}})


@pytest.fixture(scope="session")
def short_cfg(base_cfg: LineConfig) -> LineConfig:
    """Stochastic baseline with a 20-week measured horizon (fast tests)."""
    return apply_overrides(base_cfg, {"simulation": {"measure_weeks": 20}})
