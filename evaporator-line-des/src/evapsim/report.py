"""Phase 10 - write result tables into README.md and docs/*.md from results/*.csv.

Each table sits between marker comments in a Markdown file::

    <!-- BEGIN:scenarios -->
    ...generated...
    <!-- END:scenarios -->

``python -m evapsim report`` regenerates every block from the CSV files, so the
documentation can never drift away from the committed results.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

import pandas as pd

from .config import DOCS_DIR, PROJECT_ROOT, RESULTS_DIR, load_config, load_scenarios


def _read(name: str) -> pd.DataFrame:
    return pd.read_csv(RESULTS_DIR / name)


def _md(df: pd.DataFrame) -> str:
    cols = list(df.columns)
    out = ["| " + " | ".join(cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for _, r in df.iterrows():
        out.append("| " + " | ".join(str(v) for v in r.to_numpy()) + " |")
    return "\n".join(out)


def _ci(lo: float, hi: float, fmt: str = ".1f") -> str:
    return f"[{lo:{fmt}}, {hi:{fmt}}]"


# ----------------------------------------------------------------- generators
def headline() -> str:
    """Baseline vs S5 (and S6) key-results table."""
    s = _read("scenario_summary.csv").set_index("scenario")
    p = _read("scenario_paired_differences.csv")
    names = {"S0": "Baseline (S0)", "S5": "Combined (S5)", "S6": "S5 + 2nd fixture (S6)"}
    cols = [c for c in ("S0", "S5", "S6") if c in s.index]
    rows = []

    def row(label: str, metric: str, fmt: str, scale: float = 1.0, unit: str = "") -> None:
        r = {"KPI": label}
        for sid in cols:
            m = s.loc[sid, f"{metric}_mean"] * scale
            lo = s.loc[sid, f"{metric}_ci_low"] * scale
            hi = s.loc[sid, f"{metric}_ci_high"] * scale
            r[names[sid]] = f"{m:{fmt}}{unit} (±{(hi - lo) / 2:{fmt}})"
        rows.append(r)

    row("Throughput (good units/day)", "throughput_per_day", ".1f")
    rows.append({"KPI": "Demand attainment (demand 380/day)",
                 **{names[sid]: f"{s.loc[sid, 'attainment_pct']:.1f} %" for sid in cols}})
    row("Takt compliance (days ≥ 380)", "takt_compliance", ".1f", 100, " %")
    row("Line lead time, mean (min)", "lt_mean_min", ".1f")
    row("Line lead time, P95 (min)", "lt_p95_min", ".1f")
    row("WIP (units)", "wip_avg", ".1f")
    rows.append({"KPI": "Bottleneck (share of replications)",
                 **{names[sid]: f"S{int(s.loc[sid, 'bottleneck_station'])} "
                                f"({100 * s.loc[sid, 'bottleneck_share']:.0f} %)" for sid in cols}})
    th = p[p.metric == "throughput_per_day"].set_index("scenario")
    rows.append({"KPI": "Paired throughput gain vs S0 (95 % CI)", names["S0"]: "-",
                 **{names[sid]: f"{th.loc[sid, 'diff_mean']:+.1f} "
                                f"{_ci(th.loc[sid, 'diff_ci_low'], th.loc[sid, 'diff_ci_high'])}"
                                f" = {th.loc[sid, 'rel_change_pct']:+.1f} %"
                    for sid in cols if sid != "S0"}})
    n = int(s.loc["S0", "replications"])
    return _md(pd.DataFrame(rows)) + (
        f"\n\n_Mean (± 95 % CI half-width) over {n} replications of 20 measured days each, "
        "common random numbers. Source: `results/scenario_summary.csv`, "
        "`results/scenario_paired_differences.csv`._")


def scenarios() -> str:
    """Scenario comparison table with paired differences."""
    s = _read("scenario_summary.csv")
    p = _read("scenario_paired_differences.csv")
    th = p[p.metric == "throughput_per_day"].set_index("scenario")
    lt = p[p.metric == "lt_mean_min"].set_index("scenario")
    rows = []
    for _, r in s.iterrows():
        sid = r["scenario"]
        gain = "-" if sid == "S0" else (
            f"{th.loc[sid, 'diff_mean']:+.1f} "
            f"{_ci(th.loc[sid, 'diff_ci_low'], th.loc[sid, 'diff_ci_high'])}")
        rel = "-" if sid == "S0" else f"{th.loc[sid, 'rel_change_pct']:+.1f} %"
        pval = "-" if sid == "S0" else (
            "< 0.001" if th.loc[sid, "p_value"] < 0.001 else f"{th.loc[sid, 'p_value']:.3f}")
        dlt = "-" if sid == "S0" else (
            f"{lt.loc[sid, 'diff_mean']:+.1f} "
            f"{_ci(lt.loc[sid, 'diff_ci_low'], lt.loc[sid, 'diff_ci_high'])}")
        rows.append({
            "Scenario": f"**{sid}** {r['name']}",
            "TH (units/day)": f"{r['throughput_per_day_mean']:.1f}",
            "ΔTH vs S0 [95 % CI]": gain, "ΔTH %": rel, "p (paired t)": pval,
            "Takt compliance": f"{100 * r['takt_compliance_mean']:.1f} %",
            "LT mean (min)": f"{r['lt_mean_min_mean']:.1f}",
            "ΔLT vs S0 [95 % CI]": dlt,
            "WIP": f"{r['wip_avg_mean']:.1f}",
            "Bottleneck": f"S{int(r['bottleneck_station'])} "
                          f"({100 * r['bottleneck_share']:.0f} %)",
        })
    return _md(pd.DataFrame(rows))


def validation() -> str:
    """Validation summary table."""
    v = _read("validation_summary.csv")
    rows = []
    for _, r in v.iterrows():
        if r["measure"].startswith("Station utilisation"):
            u = _read("validation_station_utilisation.csv")
            worst = u.loc[u["rel_error_pct"].abs().idxmax()]
            rows.append({"Measure": "Station utilisation (7 stations)",
                         "Observed": "-", "Simulated": "-",
                         "Error": f"mean abs. {r['error_pct']:.2f} pp; worst S"
                                  f"{int(worst['station_id'])} {worst['rel_error_pct']:+.1f} %",
                         "Sim. 95 % PI": "-", "PI p-value": "-", "Welch p": "-",
                         "Verdict": r["verdict"]})
            continue
        rows.append({
            "Measure": f"{r['measure']} ({r['unit']})",
            "Observed": f"{r['observed_mean']:.1f}", "Simulated": f"{r['simulated_mean']:.1f}",
            "Error": f"{r['error_pct']:+.2f} %",
            "Sim. 95 % PI": _ci(r["sim_pi95_low"], r["sim_pi95_high"]),
            "PI p-value": f"{r['prediction_interval_p']:.2f}",
            "Welch p": f"{r['welch_t_p']:.2f}", "Verdict": r["verdict"],
        })
    return _md(pd.DataFrame(rows))


def stations() -> str:
    """Line description table (inputs + static capacity)."""
    cfg = load_config()
    cap = _read("static_capacity.csv").set_index("station_id")
    rows = []
    for st in cfg.stations:
        rows.append({
            "#": st.id, "Station": st.name, "CT mean (s)": f"{st.ct_mean_s:g}",
            "CV": f"{st.ct_cv:.2f}", "Servers": st.servers,
            "MTBF / MTTR (min)": f"{st.mtbf_min:g} / {st.mttr_min:g}" if st.has_breakdowns
            else "-",
            "C/O (min)": f"{st.changeover_min:g}" if st.changeover else "-",
            "Scrap": f"{100 * st.scrap_rate:.1f} %",
            "Operators": st.vsm.operators,
            "Eff. time/unit (s)": f"{cap.loc[st.id, 't_eff_s']:.1f}",
            "Static capacity (/day)": f"{cap.loc[st.id, 'capacity_per_day']:.0f}",
        })
    return _md(pd.DataFrame(rows)) + (
        f"\n\n_Takt = 480 × 60 / {cfg.demand_per_day:.0f} = {cfg.takt_s:.1f} s. Effective "
        "time per unit = CT × mix multiplier (1.005) × (1 + MTTR/MTBF) + P(model switch) "
        "(0.62) × C/O ÷ batch size, plus the rework load at S4, divided by the number of "
        "servers. Static capacity ignores blocking and starving, so it is an upper bound. "
        "Source: `results/static_capacity.csv`._")


def baseline_states() -> str:
    """Baseline station state shares."""
    s = _read("baseline_stations.csv")
    rows = []
    for _, r in s.iterrows():
        rows.append({"Station": f"S{int(r['station_id'])} {r['station']}",
                     **{k.capitalize(): f"{100 * r[k]:.1f} %" for k in
                        ("busy", "changeover", "down", "blocked", "starved")},
                     "Active (bottleneck metric)": f"{100 * r['active']:.1f} %",
                     "Avg. units in front": "-" if pd.isna(r["buffer_in_front_avg"])
                     else f"{r['buffer_in_front_avg']:.2f}"})
    return _md(pd.DataFrame(rows))


def sensitivity(top: int = 8) -> str:
    """Largest OAT effects."""
    d = _read("sensitivity_oat.csv")
    order = list(dict.fromkeys(d["factor"]))[:top]
    rows = []
    for f in order:
        sub = d[d.factor == f].set_index("level")
        rows.append({
            "Factor": sub["label"].iloc[0],
            "−10 % (buffers −1)": f"{sub.loc['low', 'th_diff']:+.1f} "
                                  f"{_ci(sub.loc['low', 'th_diff_ci_low'], sub.loc['low', 'th_diff_ci_high'])}",  # noqa: E501
            "+10 % (buffers +1)": f"{sub.loc['high', 'th_diff']:+.1f} "
                                  f"{_ci(sub.loc['high', 'th_diff_ci_low'], sub.loc['high', 'th_diff_ci_high'])}",  # noqa: E501
            "Elasticity (+)": f"{sub.loc['high', 'elasticity']:+.2f}",
        })
    return _md(pd.DataFrame(rows)) + (
        "\n\n_Change in throughput (units/day) against the baseline, as a paired mean with its "
        "95 % CI. Factors are ranked by swing. Source: `results/sensitivity_oat.csv`._")


def convergence() -> str:
    """Replications required for given precision."""
    c = _read("convergence_required_replications.csv")
    rows = [{"Metric": r["metric"],
             "Target CI half-width": f"±{r['target_rel_half_width_pct']:g} %",
             "Replications required": int(r["required_replications"]),
             "Achieved with run": f"±{r['achieved_rel_half_width_pct']:.2f} % "
                                  f"({int(r['replications_run'])} reps)"}
            for _, r in c.iterrows()]
    return _md(pd.DataFrame(rows))


def input_analysis() -> str:
    """Selected distributions per station."""
    d = _read("input_analysis.csv")
    rows = []
    for sid, g in d.groupby("station_id"):
        sel = g[g["selected"]].iloc[0]
        best = g.loc[g["aic"].idxmin()]
        rows.append({
            "Station": f"S{sid}", "Sample mean (s) [95 % CI]":
            f"{sel['sample_mean_s']:.1f} {_ci(sel['mean_ci95_low_s'], sel['mean_ci95_high_s'])}",
            "Spec mean in CI": "yes" if sel["spec_mean_in_ci"] else "no",
            "Sample CV": f"{sel['sample_cv']:.3f}",
            "Lowest AIC": best["distribution"],
            "Lognormal ΔAIC": f"{sel['delta_aic']:.2f}",
            "KS p (lognormal)": f"{sel['ks_pvalue']:.2f}",
            "Selected": sel["distribution"],
        })
    return _md(pd.DataFrame(rows))


def vsm_summary() -> str:
    """Current vs future VSM timeline numbers."""
    v = _read("vsm_summary.csv")
    rows = []
    labels = [("throughput_per_day", "Throughput (units/day)", ".1f"),
              ("line_lead_time_min", "Line lead time (min)", ".1f"),
              ("va_time_s", "Value-added time per unit (s)", ".0f"),
              ("va_ratio_line_pct", "VA ratio, line (%)", ".1f"),
              ("door_to_door_lead_time_days", "Door-to-door lead time (days)", ".2f"),
              ("va_ratio_door_pct", "VA ratio, door-to-door (%)", ".2f"),
              ("wip", "Line WIP (units)", ".1f")]
    for col, lab, fmt in labels:
        rows.append({"VSM measure": lab,
                     **{f"{r['state'].capitalize()} ({r['scenario']})": f"{r[col]:{fmt}}"
                        for _, r in v.iterrows()}})
    return _md(pd.DataFrame(rows))


def scenario_defs() -> str:
    """Scenario definitions from scenarios.yaml."""
    sc = load_scenarios()
    return _md(pd.DataFrame([{"ID": s.sid, "Scenario": s.name, "Change": s.description}
                             for s in sc.values()]))


def conwip() -> str:
    """CONWIP sweep table for the combined scenario (and S0)."""
    d = _read("conwip_sweep.csv")
    rows = []
    for _, r in d.iterrows():
        ref = int(r["reference_limit"])
        rows.append({
            "Scenario": r["scenario"],
            "CONWIP limit": f"**{int(r['conwip_limit'])}**" if int(r["conwip_limit"]) == ref
            else str(int(r["conwip_limit"])),
            "TH (units/day)": f"{r['throughput_per_day']:.1f}",
            f"ΔTH vs limit {ref} [95 % CI]":
            "-" if int(r["conwip_limit"]) == ref else
            f"{r['th_diff_vs_reference']:+.1f} {_ci(r['th_diff_ci_low'], r['th_diff_ci_high'])}",
            "WIP": f"{r['wip_avg']:.1f}",
            "LT mean (min)": f"{r['lt_mean_min']:.1f}",
            "LT P95 (min)": f"{r['lt_p95_min']:.1f}",
        })
    return _md(pd.DataFrame(rows)) + (
        "\n\n_Paired against the scenario at its configured limit (bold), 100 replications "
        "per point. Source: `results/conwip_sweep.csv`, figure "
        "`results/figures/conwip_sweep.png`._")


BLOCKS: dict[str, Callable[[], str]] = {
    "headline": headline,
    "scenarios": scenarios,
    "scenario_defs": scenario_defs,
    "validation": validation,
    "stations": stations,
    "baseline_states": baseline_states,
    "sensitivity": sensitivity,
    "convergence": convergence,
    "input_analysis": input_analysis,
    "vsm_summary": vsm_summary,
    "conwip": conwip,
}


def render_file(path: Path) -> list[str]:
    """Replace every known marker block in ``path``; return the block names updated."""
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
