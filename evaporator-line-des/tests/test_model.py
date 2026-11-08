"""Verification of the SimPy model against the hand calculation and system laws."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from evapsim import equations as eq
from evapsim.config import apply_overrides, with_demand
from evapsim.model import simulate
from evapsim.runner import run_replications


def _window_orders(res):
    return res.orders[res.orders["completed_in_window"]]


# ------------------------------------------------------- deterministic = hand calc
def test_deterministic_lead_time_matches_critical_path_exactly(det_cfg):
    res = simulate(det_cfg)
    lt = _window_orders(res)["lead_time_min"].to_numpy()
    cp = eq.deterministic_lead_time(det_cfg)["lead_time_min"]
    assert len(lt) == 26
    assert np.allclose(lt, cp, rtol=0, atol=1e-6)


@pytest.mark.parametrize("ov", [
    {"orders": {"transfer_batch": 1}},
    {"flags": {"wash_before_test": False}},
    {"flags": {"include_outsourced_coating": False}},
    {"time_scale_factor": 1.5},
])
def test_deterministic_variants_match_critical_path(det_cfg, ov):
    cfg = apply_overrides(det_cfg, ov)
    lt = _window_orders(simulate(cfg))["lead_time_min"].to_numpy()
    assert np.allclose(lt, eq.deterministic_lead_time(cfg)["lead_time_min"], atol=1e-6)


def test_deterministic_utilisation_and_output_match_hand_calc(det_cfg):
    res = simulate(det_cfg)
    assert set(res.weekly_output) == {3}
    sim = res.resources.set_index("resource")["active"]
    hc = eq.resource_loads(det_cfg).set_index("resource")["utilisation_at_demand"]
    for r in hc.index:
        assert sim[r] == pytest.approx(hc[r], rel=1e-9, abs=1e-12), r
    fp = eq.fin_press(**det_cfg.fin_press)
    assert res.fin_jobs["job_min"].to_numpy() == pytest.approx(fp.T_job)


def test_hand_calc_table_reproduced_per_station(det_cfg):
    res = simulate(det_cfg)
    act = res.activities.set_index("activity")["busy"]
    hc = eq.hand_calc_vsm(det_cfg).set_index("station")
    for op in det_cfg.operations:
        servers = det_cfg.resources[det_cfg.operations[op]["resource"]].get("servers", 1)
        expected = det_cfg.demand * hc.loc[op, "per_eva_min"] / (det_cfg.week_min * servers)
        assert act[op] == pytest.approx(expected, rel=1e-9), op


# ------------------------------------------------------------------- fin press
def test_fin_press_stochastic_mean_within_one_percent(base_cfg):
    cfg = apply_overrides(base_cfg, {"simulation": {"measure_weeks": 52}})
    jobs = pd.concat([simulate(cfg, rep=r).fin_jobs for r in range(25)])
    target = eq.fin_press(**cfg.fin_press).T_job
    assert len(jobs) > 1000
    assert jobs["job_min"].mean() == pytest.approx(target, rel=0.01)


# ------------------------------------------------------------------- laws
def test_littles_law(base_cfg):
    """WIP = TH x LT. Per replication, window-edge effects (orders in flight at the
    window boundaries, lead time ~4.6 weeks) allow a few % deviation. The mean over
    replications must agree within 1.5 %."""
    r = run_replications(base_cfg, 8, workers=1).reps
    assert np.allclose(r["littles_wip"], r["wip_total"], rtol=0.06)
    assert r["littles_wip"].mean() == pytest.approx(r["wip_total"].mean(), rel=0.015)


def test_unit_conservation(short_cfg):
    res = simulate(short_cfg, rep=2)
    assert res.arrived == res.completed_evas_total + res.in_system_end
    done = res.evas["completion"].notna().sum()
    assert done == res.completed_evas_total
    assert res.weekly_output.sum() <= done


def test_join_logic_never_starts_early(short_cfg):
    res = simulate(apply_overrides(short_cfg, {"orders": {"transfer_batch": 1}}), rep=1)
    ev = res.evas.dropna(subset=["completion"])
    assert len(ev) > 30
    assert (ev["steeking_start"] >= ev[["fin_press_end", "boxing_end",
                                        "weld_hairpins_end"]].max(axis=1) - 1e-9).all()
    assert (ev["header_welding_start"] >= ev[["expansion_end",
                                              "prepare_headers_end"]].max(axis=1) - 1e-9).all()
    assert (ev["complete_assembly_start"] >= ev[["coating_end", "plenum_assembly_end",
                                                 "drip_tray_assembly_end"]].max(axis=1)
            - 1e-9).all()
    # tube-dependent steps never start before the order's tubing could have arrived
    assert (ev["trim_tubes_start"] > ev["arrival"]).all()


def test_transfer_batch_moves_lot_together(short_cfg):
    ev = simulate(short_cfg, rep=0).evas.dropna(subset=["completion"])
    last_box = ev.groupby("order")["boxing_end"].transform("max")
    assert (ev["steeking_ready"] >= last_box - 1e-9).all()


def test_conwip_limits_orders_on_floor(short_cfg):
    cfg = apply_overrides(with_demand(short_cfg, 5.0),
                          {"release": {"rule": "conwip", "conwip_limit_orders": 2}})
    res = simulate(cfg, rep=3)
    ev = res.evas.dropna(subset=["test_pass_t"])
    o = res.orders.set_index("order")
    out = ev.groupby("order")["test_pass_t"].max()
    events = sorted([(o.loc[k, "card"], 1) for k in out.index] + [(t, -1) for t in out])
    level = peak = 0
    for _t, d in events:
        level += d
        peak = max(peak, level)
    assert peak <= 2


def test_rework_loop(short_cfg):
    cfg = apply_overrides(short_cfg, {"rework": {"fail_prob": 0.5}})
    res = simulate(cfg, rep=0)
    assert res.reworks > 0
    fpy = 1 - res.first_test_failures / res.first_tests
    assert 0.35 < fpy < 0.65
    assert (res.evas.dropna(subset=["completion"])["tests"] >= 1).all()


def test_reproducibility_and_parallel_equals_serial(short_cfg):
    a = simulate(short_cfg, rep=5)
    b = simulate(short_cfg, rep=5)
    assert a.orders.equals(b.orders)
    s = run_replications(short_cfg, 6, workers=1).reps
    p = run_replications(short_cfg, 6, workers=3).reps
    assert s.equals(p)
    q = run_replications(short_cfg, 3, workers=1).reps
    assert q.equals(s.iloc[:3].reset_index(drop=True))
    c = simulate(short_cfg, rep=5, base_seed=1)
    assert not c.orders["lead_time_min"].equals(a.orders["lead_time_min"])


def test_crn_pairs_scenarios(short_cfg):
    s1 = apply_overrides(short_cfg, {"resources": {"steeking_crew": {"crew": 3}}})
    a = run_replications(with_demand(short_cfg, 5), 12, workers=1).reps["lt_mean_days"]
    b = run_replications(with_demand(s1, 5), 12, workers=1).reps["lt_mean_days"]
    assert np.corrcoef(a, b)[0, 1] > 0.3
    assert (b < a).mean() > 0.8


def test_bottleneck_shifts_to_header_welding_with_third_steeker(short_cfg):
    base = run_replications(with_demand(short_cfg, 5), 8, workers=1).reps
    s1 = apply_overrides(short_cfg, {"resources": {"steeking_crew": {"crew": 3}}})
    shifted = run_replications(with_demand(s1, 5), 8, workers=1).reps
    assert (base["bottleneck"] == "steeking_crew").all()
    assert (shifted["bottleneck"] == "header_welder").mean() >= 0.75


def test_input_uncertainty_sampling(short_cfg):
    cfg = apply_overrides(short_cfg, {"input_uncertainty": {"enabled": True}})
    th = [simulate(cfg, rep=r).theta_steeking for r in range(12)]
    assert all(360 <= t <= 600 for t in th)
    assert len(set(th)) == 12
    assert simulate(cfg, rep=3).theta_steeking == th[3]


def test_observed_data_independent_of_calibration(base_cfg):
    """The synthetic 'real system' is built from the brief values, so calibrating the
    model's tubing lead time must not change the observations (no circularity)."""
    from evapsim.datagen import perturbed_config

    other = apply_overrides(base_cfg, {"lead_times": {"procurement_tubing": {"mean_days": 12.0}}})
    a, _ = perturbed_config(base_cfg)
    b, _ = perturbed_config(other)
    assert a.raw["lead_times"]["procurement_tubing"]["mean_days"] == pytest.approx(
        b.raw["lead_times"]["procurement_tubing"]["mean_days"])
