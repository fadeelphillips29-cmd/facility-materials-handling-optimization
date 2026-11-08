"""Write generated tables into README.md and docs/*.md from config and results.

Each table sits between ``<!-- BEGIN:name -->`` and ``<!-- END:name -->``
markers. ``python -m evapsim report`` regenerates every block, so the
documentation cannot drift away from the configuration or the committed
results.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from .config import DOCS_DIR, PROJECT_ROOT, RESULTS_DIR, load_config


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(RESULTS_DIR / name)


def md_table(df: pd.DataFrame) -> str:
    """Render a DataFrame as a GitHub Markdown table."""
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |",
           "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(v) for v in r.to_numpy()) + " |")
    return "\n".join(out)


def fmt(v: float, nd: int = 1) -> str:
    """Format a number, or return '-' when it is missing."""
    return "-" if pd.isna(v) else f"{v:,.{nd}f}"


def input_register() -> str:
    """Data dictionary of every process input with value, unit and source tag."""
    cfg = load_config()
    rows = []
    fp = cfg.raw["fin_press"]
    for k, unit in (("nominal_rate_fpm", "fins/min"), ("good_fins_per_eva", "fins/EVA"),
                    ("setup_min", "min/job"), ("setup_cv", "-"), ("performance", "-"),
                    ("quality", "-"), ("mtbf_min", "min run time"), ("mttr_min", "min"),
                    ("mttr_cv", "-"), ("reel_fins", "fins/reel"), ("reload_min", "min/reel")):
        src = "assumed" if k in ("setup_cv", "mttr_cv") else fp["source"]
        rows.append({"Input": f"fin_press.{k}", "Value": fp[k], "Unit": unit, "Source": src})
    for op, o in cfg.operations.items():
        if "t_op_min" in o:
            val = (f"{o['n_ops']} x {o['t_op_min']} min"
                   + (f" + {o['handling_min']} min" if o.get("handling_min") else ""))
        else:
            val = f"{o['mean_min']} min"
        crew = cfg.resources[o["resource"]].get("crew", 1)
        rows.append({"Input": f"operations.{op}", "Value": f"{val}, CV {o['cv']}, crew {crew}",
                     "Unit": "per EVA", "Source": o["source"]})
    for k, lt in cfg.raw["lead_times"].items():
        val = f"{lt['mean_days']} d, CV {lt['cv']}"
        src = lt["source"]
        if lt.get("calibrated"):
            val += f" (brief {lt['brief_mean_days']} d)"
            src += ", calibrated (A35)"
        rows.append({"Input": f"lead_times.{k}", "Value": val, "Unit": "working days",
                     "Source": src})
    rw = cfg.raw["rework"]
    rows.append({"Input": "rework", "Value": f"p = {rw['fail_prob']}, {rw['rework_min']} min",
                 "Unit": "-", "Source": rw["source"]})
    rows.append({"Input": "demand.eva_per_week", "Value": cfg.demand, "Unit": "EVA/week",
                 "Source": "time study (whiteboard, to confirm)"})
    rows.append({"Input": "demand.interarrival_cv", "Value": cfg.raw["demand"]["interarrival_cv"],
                 "Unit": "-", "Source": "assumed"})
    rows.append({"Input": "demand.due_date_weeks", "Value": cfg.raw["demand"]["due_date_weeks"],
                 "Unit": "weeks", "Source": "assumed"})
    rows.append({"Input": "crew_efficiency", "Value": str(cfg.raw["crew_efficiency"]),
                 "Unit": "eta(crew)", "Source": "assumed"})
    tri = cfg.raw["input_uncertainty"]["steeking_triangular_min"]
    rows.append({"Input": "input_uncertainty.steeking_triangular_min", "Value": str(tri),
                 "Unit": "min/EVA", "Source": "estimate"})
    return md_table(pd.DataFrame(rows))


def hand_calc() -> str:
    """Hand-calculated deterministic VSM table."""
    d = _read("vsm_hand_calc.csv")
    rows = []
    for _, r in d.iterrows():
        delay = r["resource"] == "(calendar delay)"
        rows.append({
            "Step": int(r["step"]), "Process": r["label"], "Dept": r["department"],
            "Source": r["source"],
            "Min/EVA": "-" if delay else fmt(r["per_eva_min"]),
            "Min/3 EVA": fmt(r["per_lot_min"]) if not delay else f"{r['lead_time_days']:g} d",
            "Ops": "-" if delay else int(r["operators"]),
            "Labour min/EVA": "-" if delay else fmt(r["labour_min_per_eva"]),
            "EVA/shift": "-" if delay else fmt(r["capacity_eva_per_shift"], 2),
            "EVA/week": "-" if delay else fmt(r["capacity_eva_per_week"], 2),
            "Resource util. @ demand": "-" if delay
            else f"{100 * r['resource_utilisation_at_demand']:.1f} %"
            + (" **(BN)**" if r["is_bottleneck_resource"] is True
               or str(r["is_bottleneck_resource"]) == "True" else ""),
        })
    return md_table(pd.DataFrame(rows))


def _ci(lo: float, hi: float, nd: int = 2) -> str:
    return f"[{lo:.{nd}f}, {hi:.{nd}f}]"


def _diff(r: pd.Series, pct: bool = True) -> str:
    """'+x.xx d [lo, hi] = +y.y %' from a paired-difference row."""
    out = f"{r['diff_mean']:+.2f} d {_ci(r['diff_ci_low'], r['diff_ci_high'])}"
    return out + (f" = {r['rel_change_pct']:+.1f} %" if pct else "")


def _p(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


RES_SHORT = {"steeking_crew": "Steeking", "header_welder": "Header welding",
             "hairpin_welder": "Hairpins", "fin_press_operator": "Fin press/boxing"}


def headline() -> str:
    """Baseline vs recommended scenario at current and target demand."""
    s = _read("scenario_summary.csv").set_index(["scenario", "demand_eva_per_week"])
    p = _read("scenario_paired_differences.csv")
    cols = [("S0", 3.0), ("S7", 3.0), ("S0", 5.0), ("S7", 5.0)]
    hdr = {c: f"{c[0]} @ {c[1]:g}/wk" for c in cols}
    rows = []
    for m, lab, nd, sc in (("throughput_eva_week", "Throughput (EVA/week)", 2, 1),
                           ("lt_mean_days", "Order lead time, mean (working days)", 1, 1),
                           ("lt_p95_days", "Order lead time, P95 (working days)", 1, 1),
                           ("on_time", "On-time delivery (6-week promise)", 1, 100),
                           ("wip_total", "WIP in system (EVA)", 1, 1),
                           ("va_ratio", "Value-added ratio", 1, 100)):
        r = {"KPI": lab}
        for c in cols:
            v = s.loc[c, f"{m}_mean"] * sc
            h = (s.loc[c, f"{m}_ci_high"] - s.loc[c, f"{m}_mean"]) * sc
            r[hdr[c]] = f"{v:.{nd}f}{' %' if sc == 100 else ''} (±{h:.{nd + 1}f})"
        rows.append(r)
    rows.append({"KPI": "Bottleneck (share of replications)",
                 **{hdr[c]: f"{RES_SHORT.get(s.loc[c, 'bottleneck'], s.loc[c, 'bottleneck'])} "
                            f"({100 * s.loc[c, 'bottleneck_share']:.0f} %)" for c in cols}})
    lt = p[p.metric == "lt_mean_days"].set_index(["scenario", "demand_eva_per_week"])
    rows.append({"KPI": "Paired lead-time change vs S0 (95 % CI)",
                 **{hdr[c]: "-" if c[0] == "S0" else _diff(lt.loc[c]) for c in cols}})
    n = int(s["replications"].iloc[0])
    return md_table(pd.DataFrame(rows)) + (
        f"\n\n_Mean (± 95 % CI half-width) over {n} replications of 52 measured weeks; "
        "common random numbers; S7 = S6 (3rd steeker + 2nd header welder + CONWIP) + "
        "one-piece flow. Source: `results/scenario_summary.csv`, "
        "`results/scenario_paired_differences.csv`._")


def scenarios() -> str:
    """Scenario table per demand level."""
    s = _read("scenario_summary.csv")
    p = _read("scenario_paired_differences.csv")
    lt = p[p.metric == "lt_mean_days"].set_index(["scenario", "demand_eva_per_week"])
    rows = []
    for _, r in s.iterrows():
        k = (r["scenario"], r["demand_eva_per_week"])
        d = "-" if r["scenario"] == "S0" else _diff(lt.loc[k], pct=False)
        rows.append({
            "Demand": f"{r['demand_eva_per_week']:g}",
            "Scenario": f"**{r['scenario']}** {r['name']}",
            "TH (EVA/wk)": f"{r['throughput_eva_week_mean']:.2f}",
            "LT mean (d)": f"{r['lt_mean_days_mean']:.2f}",
            "ΔLT vs S0 [95 % CI]": d,
            "ΔLT %": "-" if r["scenario"] == "S0" else f"{lt.loc[k, 'rel_change_pct']:+.1f} %",
            "p": "-" if r["scenario"] == "S0" else _p(lt.loc[k, "p_value"]),
            "LT P95 (d)": f"{r['lt_p95_days_mean']:.1f}",
            "On-time": f"{100 * r['on_time_mean']:.1f} %",
            "Steeking util.": f"{100 * r['steeking_util']:.0f} %",
            "Header util.": f"{100 * r['header_util']:.0f} %",
            "Bottleneck": f"{RES_SHORT.get(r['bottleneck'], r['bottleneck'])} "
                          f"({100 * r['bottleneck_share']:.0f} %)",
        })
    return md_table(pd.DataFrame(rows))


def scenario_defs() -> str:
    """Scenario definitions."""
    d = _read("scenario_definitions.csv")
    return md_table(d.rename(columns={"scenario": "ID", "name": "Scenario",
                                      "description": "Change"}))


def bottleneck_ranking() -> str:
    """Hand-calculated loads vs simulated active shares, ranked."""
    h = _read("resource_loads.csv")
    b = _read("baseline_resources.csv").set_index("resource")
    s5 = _read("scenario_resources.csv")
    s5 = s5[(s5.scenario == "S0") & (s5.demand_eva_per_week == 5.0)].set_index("resource")
    rows = []
    for _, r in h.head(8).iterrows():
        rows.append({"Rank": int(r["rank"]), "Resource": r["label"],
                     "Load (min/EVA)": f"{r['min_per_eva']:.1f}",
                     "Capacity (EVA/wk)": f"{r['capacity_eva_per_week']:.2f}",
                     "Hand-calc util. @ 3/wk": f"{100 * r['utilisation_with_rework']:.1f} %",
                     "Simulated @ 3/wk": f"{100 * b.loc[r['resource'], 'active']:.1f} %",
                     "Simulated @ 5/wk": f"{100 * s5.loc[r['resource'], 'active']:.1f} %",
                     "Mean queue @ 5/wk (h)": f"{s5.loc[r['resource'], 'mean_wait_min'] / 60:.1f}"})
    return md_table(pd.DataFrame(rows))


def sweep() -> str:
    """Mean order lead time (days) vs demand, by scenario (pivot)."""
    d = _read("demand_sweep.csv")
    piv = d.pivot_table(index="demand_eva_per_week", columns="scenario",
                        values="lt_mean_days_mean", sort=False)
    th = d[d.scenario == "S0"].set_index("demand_eva_per_week")
    out = pd.DataFrame({"Demand (EVA/wk)": [f"{x:g}" for x in piv.index]})
    for c in piv.columns:
        out[f"{c} LT (d)"] = [f"{v:.1f}" for v in piv[c]]
    out["S0 TH (EVA/wk)"] = [f"{th.loc[x, 'throughput_eva_week_mean']:.2f}" for x in piv.index]
    out["S0 on-time"] = [f"{100 * th.loc[x, 'on_time_mean']:.0f} %" for x in piv.index]
    out["S0 steeking util."] = [f"{100 * th.loc[x, 'steeking_util']:.0f} %" for x in piv.index]
    return md_table(out) + ("\n\n_100 replications per point. Source: "
                            "`results/demand_sweep.csv`._")


def sensitivity(top: int = 6) -> str:
    """Largest one-at-a-time effects per demand level."""
    d = _read("sensitivity_oat.csv")
    rows = []
    for dm, g in d.groupby("demand_eva_per_week"):
        for f in list(dict.fromkeys(g["factor"]))[:top]:
            sub = g[g.factor == f].set_index("level")
            rows.append({
                "Demand": f"{dm:g}", "Factor": sub["label"].iloc[0],
                "Low (−10 % / crew −1)": f"{sub.loc['low', 'lt_diff']:+.2f} d"
                + (" (unstable)" if bool(sub.loc["low", "unstable"]) else ""),
                "High (+10 % / crew +1)": f"{sub.loc['high', 'lt_diff']:+.2f} d"
                + (" (unstable)" if bool(sub.loc["high", "unstable"]) else ""),
            })
    return md_table(pd.DataFrame(rows)) + ("\n\n_Paired change in mean order lead time "
                                           "against the baseline at the same demand (CRN, 100 "
                                           "replications). Source: `results/sensitivity_oat.csv`._")


def validation() -> str:
    """Validation summary (post-calibration) and calibration grid excerpt."""
    v = _read("validation_summary.csv")
    rows = [{"Measure": f"{r['measure']} ({r['unit']})", "Observed (26 wk)":
             f"{r['observed_mean']:.2f}", "Simulated": f"{r['simulated_mean']:.2f}",
             "Error": f"{r['error_pct']:+.2f} %", "Sim. 95 % PI": _ci(r["sim_pi95_low"],
                                                                  r["sim_pi95_high"]),
             "PI p": f"{r['prediction_interval_p']:.3f}", "Welch p": f"{r['welch_t_p']:.3f}",
             "Verdict": r["verdict"]} for _, r in v.iterrows()]
    return md_table(pd.DataFrame(rows))


def calibration() -> str:
    """Calibration grid of the tubing lead time."""
    g = _read("calibration_grid.csv")
    rows = [{"Tubing mean (d)": f"{r['value']:.2f}",
             "Sim. LT (d)": f"{r['simulated_lt_mean_days']:.2f}",
             "Error vs observed": f"{r['error_pct']:+.2f} %",
             "PI p": f"{r['prediction_interval_p']:.3f}",
             "Passes": "yes" if r["passes"] else "no",
             "Note": "**selected (minimum change)**" if r["selected_min_change"] else
             ("best fit" if r["best_fit"] else ("brief value" if i == 0 else ""))}
            for i, (_, r) in enumerate(g.iterrows()) if i < 6 or r["best_fit"]]
    return md_table(pd.DataFrame(rows))


def deterministic() -> str:
    """Deterministic simulation vs hand calculation."""
    d = _read("deterministic_check.csv")
    rows = [{"Case": r["case"],
             "Quantity": r["quantity"].replace("utilisation ", "utilisation: "),
             "Hand calc": f"{r['hand_calc']:.4f}" if r["hand_calc"] < 10
             else f"{r['hand_calc']:.2f}",
             "Simulated (min-max)": (f"{r['simulated_min']:.4f}" if r["hand_calc"] < 10 else
                                     f"{r['simulated_min']:.2f}") +
             ("" if r["simulated_min"] == r["simulated_max"] else f" - {r['simulated_max']:.2f}"),
             "Exact": "yes" if r["exact_match"] else "no"}
            for _, r in d.iterrows() if r["quantity"] in (
                "order lead time (min)", "EVA per week", "fin press job (min)")
            or any(k in r["quantity"] for k in ("steeking", "header_welder", "fin_press_operator"))]
    n_ok = int(d["exact_match"].sum())
    return md_table(pd.DataFrame(rows)) + (f"\n\n_{n_ok} of {len(d)} checked quantities match "
                                           "exactly (all 15 resource utilisations included). "
                                           "Source: `results/deterministic_check.csv`._")


def kingman() -> str:
    """Kingman bracket check at steeking and header welding."""
    k = _read("kingman_check.csv")
    rows = [{"Demand": f"{r['demand_eva_per_week']:g}", "Station": r["station"],
             "rho (sim)": f"{r['rho_sim']:.3f}", "ca² measured / release":
             f"{r['ca2_measured']:.2f} / {r['ca2_release']:.4f}",
             "cs² (lot)": f"{r['cs2_sim']:.4f}",
             "Wq sim (h)": f"{r['wq_sim_min'] / 60:.1f}",
             "Kingman (h): release ca² / measured ca²":
             f"{r['wq_kingman_release_ca2_min'] / 60:.1f} / "
             f"{r['wq_kingman_measured_ca2_min'] / 60:.1f}",
             "Bracketed": "yes" if r["bracketed"] else "no"} for _, r in k.iterrows()]
    return md_table(pd.DataFrame(rows))


def uncertainty() -> str:
    """Variance decomposition and steeking cases."""
    v = _read("variance_decomposition.csv")
    v = v[v.metric.isin(["lt_mean_days", "throughput_eva_week"])]
    rows = [{"Demand": f"{r['demand_eva_per_week']:g}", "Output": r["metric"],
             "Total var.": f"{r['var_total']:.4f}",
             "Input uncertainty share": f"{100 * r['share_input']:.1f} %",
             "Process variability share": f"{100 * r['share_process']:.1f} %",
             "Design": f"{int(r['outer'])} × {int(r['inner'])}"} for _, r in v.iterrows()]
    t = _read("uncertainty_two_level_summary.csv")
    rows2 = [{"Demand": f"{r['demand_eva_per_week']:g}", "Model": r["model"],
              "LT mean (d)": f"{r['lt_mean_days_mean']:.2f}", "LT SD across reps (d)":
              f"{r['lt_mean_days_sd']:.2f}", "P95 (d)": f"{r['lt_p95_days_mean']:.1f}",
              "On-time": f"{100 * r['on_time_mean']:.1f} %"} for _, r in t.iterrows()]
    return md_table(pd.DataFrame(rows)) + "\n\n" + md_table(pd.DataFrame(rows2))


def steeking_cases() -> str:
    """What the stakeholder guesses imply."""
    c = _read("steeking_cases.csv")
    rows = [{"Steeking (h/EVA)": f"{r['steeking_hours_per_eva']:g}",
             "Capacity (EVA/wk)": f"{r['steeking_capacity_eva_week']:.2f}",
             "Throughput @ 3/wk": f"{r['throughput_eva_week']:.2f}",
             "Order LT (d)": f"{r['lt_mean_days']:.1f}", "On-time": f"{100 * r['on_time']:.0f} %",
             "Steeking util.": f"{100 * r['steeking_utilisation']:.0f} %",
             "Stable": "yes" if r["stable"] else "**no** (backlog grows)"} for _, r in c.iterrows()]
    return md_table(pd.DataFrame(rows))


def input_analysis() -> str:
    """Selected distribution per operation."""
    d = _read("input_analysis.csv")
    rows = []
    for _op, g in d.groupby("operation", sort=False):
        sel = g[g["selected"]].iloc[0]
        best = g.loc[g["aic"].idxmin()]
        ln = g[g.distribution == "lognormal"].iloc[0]
        rows.append({"Operation": sel["label"], "n": int(sel["n"]),
                     "Mean (min) [95 % CI]": f"{sel['sample_mean_min']:.1f} "
                     f"{_ci(sel['mean_ci95_low'], sel['mean_ci95_high'], 1)}",
                     "CV": f"{sel['sample_cv']:.3f}", "Lowest AIC": best["distribution"],
                     "Lognormal ΔAIC": f"{ln['delta_aic']:.2f}",
                     "KS p (selected)": f"{sel['ks_pvalue']:.2f}", "Selected": sel["distribution"]})
    return md_table(pd.DataFrame(rows))


def convergence() -> str:
    """Replications needed for given precision."""
    c = _read("convergence_required_replications.csv")
    return md_table(pd.DataFrame([{"Metric": r["metric"], "Target ± (% of mean)":
                                   f"{r['target_rel_half_width_pct']:g} %",
                                   "Replications required": int(r["required_replications"]),
                                   "Achieved": f"±{r['achieved_rel_half_width_pct']:.2f} % "
                                   f"({int(r['replications_run'])} reps)"}
                                  for _, r in c.iterrows()]))


def fin_press_block() -> str:
    """Fin-press OEE options (A23)."""
    o = _read("fin_press_oee_options.csv")
    return md_table(pd.DataFrame([{"Case": r["case"], "S (min)": f"{r['S']:g}",
                                   "P": f"{r['P']:g}", "Q": f"{r['Q']:g}",
                                   "MTBF/MTTR (min)": f"{r['MTBF']:g}/{r['MTTR']:.0f}",
                                   "t_r (min)": f"{r['t_r']:g}",
                                   "T_job (min/3 EVA)": f"{r['T_job_min']:.1f}",
                                   "OEE": f"{100 * r['OEE']:.1f} %"} for _, r in o.iterrows()]))


def weld_metrics() -> str:
    """Metrics 1-3 of the manual weld stations."""
    m = _read("station_metrics.csv")
    return md_table(pd.DataFrame([{"Station": r["label"], "t_op (min)": f"{r['t_op_min']:g}",
                                   "ops/min": f"{r['ops_per_min']:.3f}",
                                   "ops/h": f"{r['ops_per_hour']:.1f}",
                                   "n_ops/coil": int(r["n_ops"]),
                                   "min/coil": f"{r['min_per_coil']:g}",
                                   "min per 3 EVA": f"{r['min_per_lot']:g} "
                                   f"({r['hours_per_lot']:.1f} h)",
                                   "Operators": int(r["operators"]),
                                   "EVA/shift": f"{r['capacity_eva_per_shift']:.2f}",
                                   "Util. @ 3/wk": f"{100 * r['utilisation']:.1f} %"}
                                  for _, r in m.iterrows()]))


def vsm_summary() -> str:
    """Current vs future VSM numbers."""
    v = _read("vsm_summary.csv")
    rows = []
    for col, lab, nd, sc in (("throughput_eva_week", "Throughput (EVA/week)", 2, 1),
                             ("order_lead_time_days", "Order lead time (days)", 1, 1),
                             ("order_lead_time_p95_days", "Order lead time P95 (days)", 1, 1),
                             ("va_min_per_eva", "Value-added time (min/EVA)", 0, 1),
                             ("va_ratio", "VA ratio (%)", 1, 100), ("wip_eva", "WIP (EVA)", 1, 1),
                             ("steeking_queue_h", "Queue before steeking (h)", 1, 1),
                             ("on_time", "On-time (%)", 1, 100)):
        rows.append({"VSM measure": lab, **{f"{r['label']} @ {r['demand_eva_per_week']:g}/wk":
                                            f"{r[col] * sc:.{nd}f}" for _, r in v.iterrows()}})
    return md_table(pd.DataFrame(rows))


BLOCKS: dict[str, Callable[[], str]] = {
    "input_register": input_register,
    "hand_calc": hand_calc,
    "headline": headline,
    "scenarios": scenarios,
    "scenario_defs": scenario_defs,
    "bottleneck_ranking": bottleneck_ranking,
    "sweep": sweep,
    "sensitivity": sensitivity,
    "validation": validation,
    "calibration": calibration,
    "deterministic": deterministic,
    "kingman": kingman,
    "uncertainty": uncertainty,
    "steeking_cases": steeking_cases,
    "input_analysis": input_analysis,
    "convergence": convergence,
    "fin_press": fin_press_block,
    "weld_metrics": weld_metrics,
    "vsm_summary": vsm_summary,
}


def render_file(path: Path) -> list[str]:
    """Replace every known block in ``path``; return the block names updated."""
    text = path.read_text(encoding="utf-8")
    done = []
    for name, fn in BLOCKS.items():
        pat = re.compile(rf"(<!-- BEGIN:{name} -->)(.*?)(<!-- END:{name} -->)", re.S)
        if pat.search(text):
            content = fn()
            text = pat.sub(lambda m, c=content: f"{m.group(1)}\n{c}\n{m.group(3)}", text)
            done.append(name)
    path.write_text(text, encoding="utf-8")
    return done


def render_all() -> dict[str, list[str]]:
    """Update README.md and every Markdown file in docs/."""
    files = [PROJECT_ROOT / "README.md", *sorted(DOCS_DIR.glob("*.md"))]
    return {str(f.relative_to(PROJECT_ROOT)): render_file(f) for f in files if f.exists()}
