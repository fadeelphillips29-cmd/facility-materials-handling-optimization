"""Analytical model (equations A, B, C) and the hand-calculated VSM."""

from __future__ import annotations

import math

import pytest

from evapsim import equations as eq
from evapsim.config import ConfigError, apply_overrides


def test_fin_press_reproduces_whiteboard(base_cfg):
    r = eq.fin_press(**base_cfg.fin_press)
    assert r.t_ideal_min * 60 == pytest.approx(0.8)                      # A1: 0.8 s per fin
    assert r.F_g == pytest.approx(4000 / 0.98)                          # A2
    assert r.T_run == pytest.approx(4000 / 0.98 / (75 * 0.95))          # A3
    assert r.A_u == pytest.approx(0.90)                                 # A4
    assert r.T_job == pytest.approx(229.0, abs=0.5)                     # A5: whiteboard 229
    assert r.per_eva == pytest.approx(76.3, abs=0.2)
    assert r.OEE == pytest.approx(0.70, abs=0.001)                      # A6
    assert r.OEE == pytest.approx(r.A_tot * 0.95 * 0.98)                # A6 identity
    assert r.r_eff == pytest.approx(52.5, abs=0.1)                      # A7
    assert eq.good_fins(r.r_eff, 60) == pytest.approx(60 * r.r_eff)
    assert r.X_eva_per_min == pytest.approx(3 / r.T_job)


def test_fin_press_calibration_and_rate():
    assert eq.calibrate_good_fins(0.70, 75, 229, 3) == pytest.approx(4007.5)   # A8
    assert eq.strokes_rate(25, 3) == 75                                      # r_n = s * k


def test_oee_package_reaches_85_but_smed_alone_does_not(base_cfg):
    from evapsim.pipeline import fin_press_options

    o = fin_press_options(base_cfg).set_index("case")
    assert o.loc["SMED only: setup -40%", "OEE"] == pytest.approx(0.7387, abs=1e-3)
    assert o.iloc[2]["OEE"] < 0.85                                          # cap below target
    assert o.iloc[3]["OEE"] == pytest.approx(0.85, abs=0.002)


@pytest.mark.parametrize("op,t_op,n,mpc,lot", [
    ("weld_hairpins", 4, 54, 216, 648), ("weld_return_bends", 4, 36, 144, 432),
    ("expansion", 3, 24, 87, 261), ("header_welding", 8, 48, 384, 1152)])
def test_weld_station_metrics(base_cfg, op, t_op, n, mpc, lot):
    o = base_cfg.operations[op]
    m = eq.station_metrics(o["t_op_min"], o["n_ops"], o.get("handling_min", 0), 1, 3, 2400)
    assert (m.t_op_min, m.n_ops, m.min_per_coil) == (t_op, n, mpc)
    assert 3 * m.min_per_coil == lot
    assert base_cfg.op_mean_min(op) == mpc


def test_header_welding_reported_metrics():
    m = eq.station_metrics(8, 48, 0, 1, 3, 2400)
    assert m.ops_per_min == 0.125 and m.ops_per_min * 60 == 7.5
    assert m.min_per_coil == 384 and m.min_per_coil / 60 == 6.4
    assert 3 * m.min_per_coil / 60 == pytest.approx(19.2)
    assert m.capacity_eva_per_shift == pytest.approx(1.25)
    assert m.utilisation == pytest.approx(0.48)


def test_crew_elapsed_and_steeking_capacity(base_cfg):
    assert base_cfg.op_labour_min("steeking") == 840
    assert base_cfg.op_mean_min("steeking") == 420
    assert eq.crew_elapsed(840, 3, 0.85) == pytest.approx(329.41, abs=0.01)
    s1 = apply_overrides(base_cfg, {"resources": {"steeking_crew": {"crew": 3}}})
    assert s1.op_mean_min("steeking") == pytest.approx(840 / 2.55)
    cap_shift = base_cfg.day_min / base_cfg.op_mean_min("steeking")
    assert cap_shift == pytest.approx(1.143, abs=1e-3)
    assert base_cfg.week_min / base_cfg.op_mean_min("steeking") == pytest.approx(5.714, abs=1e-3)


def test_bottleneck_ranking(base_cfg):
    loads = eq.resource_loads(base_cfg)
    assert list(loads["resource"][:3]) == ["steeking_crew", "header_welder", "hairpin_welder"]
    assert eq.bottleneck(base_cfg) == "steeking_crew"
    assert loads.iloc[0]["utilisation_at_demand"] == pytest.approx(3 * 420 / 2400)
    fpo = loads.set_index("resource").loc["fin_press_operator", "min_per_eva"]
    assert fpo == pytest.approx(228.6066 / 3 + 100, abs=1e-3)       # shared operator load
    s1 = apply_overrides(base_cfg, {"resources": {"steeking_crew": {"crew": 3}}})
    assert eq.bottleneck(s1) == "header_welder"                      # bottleneck shifts


def test_kingman_and_littles_law():
    assert eq.kingman_wq(1, 1, 0.8, 10) == pytest.approx(40)         # M/M/1: rho/(1-rho) t_e
    assert eq.kingman_wq(1, 0.25, 0.8, 10) == pytest.approx(25)      # M/G/1 = Pollaczek-Khinchine
    assert math.isinf(eq.kingman_wq(1, 1, 1.0, 10))
    assert eq.littles_law_wip(2.0, 3.5) == 7.0
    assert eq.va_ratio(30, 120) == 0.25


def test_critical_path_hand_calc(base_cfg):
    cp = eq.deterministic_lead_time(base_cfg)
    tubing = base_cfg.lead_time_mean_min("procurement_tubing")
    # release + tubing + 120 trim + 648 hairpins + 1260 steek + 432 + 261 + 1152
    # + 135 wash + 270 test + 1440 coating + 450 assembly (critical path through tubing)
    assert cp["lead_time_min"] == pytest.approx(
        480 + tubing + 120 + 648 + 1260 + 432 + 261 + 1152 + 135 + 270 + 1440 + 450)
    brief = apply_overrides(base_cfg, {"lead_times": {"procurement_tubing": {"mean_days": 8.0}}})
    assert eq.deterministic_lead_time(brief)["lead_time_min"] == 10488   # whiteboard lead time
    tb1 = eq.deterministic_lead_time(apply_overrides(base_cfg, {"orders": {"transfer_batch": 1}}))
    assert tb1["lead_time_min"] < cp["lead_time_min"]


def test_time_scale_factor(base_cfg):
    k = apply_overrides(base_cfg, {"time_scale_factor": 2.0})
    assert k.op_mean_min("header_welding") == 768
    a, b = eq.fin_press(**base_cfg.fin_press), eq.fin_press(**k.fin_press)
    assert b.T_job == pytest.approx(2 * a.T_job)
    assert b.OEE == pytest.approx(a.OEE)
    assert k.lead_time_mean_min("procurement_tubing") == base_cfg.lead_time_mean_min(
        "procurement_tubing")


def test_hand_calc_table(base_cfg):
    t = eq.hand_calc_vsm(base_cfg).set_index("station")
    assert t.loc["steeking", "per_lot_min"] == 1260
    assert bool(t.loc["steeking", "is_bottleneck_resource"])
    assert t.loc["header_welding", "capacity_eva_per_shift"] == pytest.approx(1.25)
    assert t.loc["procurement_tubing", "lead_time_days"] == 8.75   # calibrated (Phase 6)


@pytest.mark.parametrize("bad", [
    {"orders": {"transfer_batch": 4}}, {"release": {"rule": "kanban"}},
    {"operations": {"steeking": {"resource": "nobody"}}}, {"fin_press": {"quality": 1.2}},
    {"operations": {"wash": {"source": "guess"}}}, {"time_scale_factor": 0},
])
def test_invalid_config_rejected(base_cfg, bad):
    with pytest.raises(ConfigError):
        apply_overrides(base_cfg, bad)
