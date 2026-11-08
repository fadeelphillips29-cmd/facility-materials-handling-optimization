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
        rows.append({"Input": f"lead_times.{k}", "Value": f"{lt['mean_days']} d, CV {lt['cv']}",
                     "Unit": "working days", "Source": lt["source"]})
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


BLOCKS: dict[str, Callable[[], str]] = {
    "input_register": input_register,
    "hand_calc": hand_calc,
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
