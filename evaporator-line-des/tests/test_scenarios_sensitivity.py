"""Scenario tables, sensitivity factor design and report generation."""

from __future__ import annotations

import re

import pytest

from evapsim.config import RESULTS_DIR, apply_overrides, load_scenarios
from evapsim.runner import run_replications
from evapsim.scenarios import paired_table, summary_table
from evapsim.sensitivity import factors, perturbed


@pytest.fixture(scope="module")
def small_runs():
    scen = {k: v for k, v in load_scenarios().items() if k in ("S0", "S2", "S3")}
    runs = {}
    for sid, s in scen.items():
        cfg = apply_overrides(s.config, {"simulation": {"days": 3}})
        runs[sid] = run_replications(cfg, 6, label=sid, workers=1)
    return scen, runs


def test_summary_and_paired_tables(small_runs):
    scen, runs = small_runs
    summary = summary_table(scen, runs)
    assert list(summary["scenario"]) == ["S0", "S2", "S3"]
    assert int(summary.set_index("scenario").loc["S0", "bottleneck_station"]) == 4
    paired = paired_table(runs)
    th = paired[paired.metric == "throughput_per_day"].set_index("scenario")
    assert th.loc["S3", "diff_mean"] > th.loc["S2", "diff_mean"] > 0
    assert th.loc["S3", "significant"]


def test_sensitivity_factor_design(base_cfg):
    fs = factors(base_cfg)
    assert len(fs) == 7 + 5 + 5 + 1
    f = next(x for x in fs if x.key == "S4.mtbf")
    cfg, new, pct = perturbed(base_cfg, f, +1)
    assert new == pytest.approx(198) and pct == pytest.approx(10)
    assert cfg.station(4).mtbf_min == pytest.approx(198)
    b = next(x for x in fs if x.key == "buffers")
    cfg, new, _ = perturbed(base_cfg, b, -1)
    assert cfg.buffer_capacities == (4,) * 6


@pytest.mark.skipif(not (RESULTS_DIR / "scenario_summary.csv").exists(),
                    reason="full results not generated")
def test_report_blocks_render():
    from evapsim.report import BLOCKS

    for name, fn in BLOCKS.items():
        text = fn()
        assert text.startswith("|"), name
        assert not re.search(r"\bnan\b", text, re.I), name  # no missing values rendered
