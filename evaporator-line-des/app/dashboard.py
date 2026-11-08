"""Streamlit dashboard for the evaporator production system model (illustrative data).

Run with:  streamlit run app/dashboard.py

Pick a scenario, edit the key inputs (operation times, crews, stations, demand,
transfer batch, release rule), choose the number of replications and press
**Run simulation**. The run is compared with the baseline S0 at the same demand,
using the same seeds (common random numbers).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:  # allow running without `pip install -e .`
    sys.path.insert(0, str(ROOT / "src"))

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from evapsim import plots  # noqa: E402
from evapsim.config import (  # noqa: E402
    RESULTS_DIR,
    ConfigError,
    LineConfig,
    apply_overrides,
    load_config,
    load_scenarios,
    with_demand,
)
from evapsim.metrics import bottleneck_frequency, paired_difference, t_ci  # noqa: E402
from evapsim.runner import LT_BINS_DAYS, resource_summary, run_replications  # noqa: E402

st.set_page_config(page_title="Evaporator line DES", layout="wide")
plots.apply_style()


@st.cache_data(show_spinner=False)
def scenarios() -> dict[str, dict]:
    """YAML-shaped config of every scenario."""
    return {sid: {"name": s.name, "description": s.description, "cfg": s.config.to_dict()}
            for sid, s in load_scenarios().items()}


@st.cache_data(show_spinner=False, max_entries=24)
def simulate(cfg_json: str, reps: int, workers: int) -> dict:
    """Run replications (cached on the exact configuration)."""
    cfg = LineConfig(json.loads(cfg_json))
    run = run_replications(cfg, reps, "run", workers)
    return {"reps": run.reps, "res": resource_summary(run), "hist": run.lt_hist,
            "bneck": bottleneck_frequency(run.reps)}


@st.cache_data(show_spinner=False)
def committed(name: str) -> pd.DataFrame | None:
    """A committed results table, if present."""
    p = RESULTS_DIR / name
    return pd.read_csv(p) if p.exists() else None


# ----------------------------------------------------------------- sidebar
sc = scenarios()
sb = st.sidebar
sb.header("1. Starting point")
sid = sb.selectbox("Scenario", list(sc), format_func=lambda s: f"{s} - {sc[s]['name']}",
                   key="scenario")
sb.caption(sc[sid]["description"])
base = sc[sid]["cfg"]
sb.header("2. Key inputs")
demand = sb.number_input("Demand (EVA/week)", 0.5, 12.0, float(base["demand"]["eva_per_week"]),
                         step=0.5, key="demand")
tb = sb.select_slider("Transfer batch (EVA)", options=list(range(1, base["orders"]["lot_size"]
                                                                  + 1)),
                      value=int(base["orders"]["transfer_batch"]), key="tb")
crew = sb.slider("Steeking crew (operators)", 1, 4, int(base["resources"]["steeking_crew"]["crew"]),
                 key="crew")
hw = sb.slider("Header-welding stations", 1, 3, int(base["resources"]["header_welder"]["servers"]),
               key="hw")
rule = sb.radio("Release rule", ["push", "conwip"],
                index=0 if base["release"]["rule"] == "push" else 1, horizontal=True, key="rule")
limit = sb.number_input("CONWIP limit (work orders on the coil line)", 1, 20,
                        int(base["release"]["conwip_limit_orders"]), disabled=rule == "push",
                        key="limit")
tsf = sb.number_input("time_scale_factor", 0.1, 5.0, float(base.get("time_scale_factor", 1.0)),
                      step=0.1, key="tsf")
unc = sb.checkbox("Input uncertainty on steeking (triangular 360/420/600)", value=False,
                  key="unc")
sb.header("3. Run settings")
reps = sb.slider("Replications", 5, 300, 30, step=5, key="reps")
weeks = sb.slider("Measured weeks", 10, 52, int(base["simulation"]["measure_weeks"]), key="weeks")
workers = sb.slider("Worker processes", 1, 8, 4, key="workers")
compare = sb.checkbox("Compare with S0 at the same demand (paired)", value=True, key="compare")

# -------------------------------------------------------------------- main
st.title("Evaporator production system: DES + Monte Carlo")
st.warning("**Illustrative, anonymised data.** The organisation is called 'the Company'. "
           "No figure here is measured company data.", icon="⚠️")
st.subheader("Operation times (per EVA)")
st.caption("Edit the mean time per EVA (min, at the basis crew) or the CV. Weld stations scale "
           "their minutes per weld. Crew and station counts are set in the sidebar.")
rows = []
for op, o in base["operations"].items():
    t = o["n_ops"] * o["t_op_min"] + o.get("handling_min", 0) if "t_op_min" in o else o["mean_min"]
    rows.append({"operation": op, "label": o["label"], "department": o["department"],
                 "time_per_eva_min": float(t), "cv": float(o["cv"]), "source": o["source"]})
table = pd.DataFrame(rows)
edited = st.data_editor(table, disabled=["operation", "label", "department", "source"],
                        hide_index=True, width="stretch", key=f"ops_{sid}")

ov: dict = {"demand": {"eva_per_week": float(demand)}, "orders": {"transfer_batch": int(tb)},
            "resources": {"steeking_crew": {"crew": int(crew)},
                          "header_welder": {"servers": int(hw)}},
            "release": {"rule": rule, "conwip_limit_orders": int(limit)},
            "time_scale_factor": float(tsf), "simulation": {"measure_weeks": int(weeks)},
            "input_uncertainty": {"enabled": bool(unc)}, "operations": {}}
for (_, a), (_, b) in zip(table.iterrows(), edited.iterrows(), strict=True):
    o = base["operations"][a["operation"]]
    d: dict = {"cv": float(b["cv"])}
    if b["time_per_eva_min"] != a["time_per_eva_min"] and a["time_per_eva_min"] > 0:
        k = float(b["time_per_eva_min"]) / float(a["time_per_eva_min"])
        d["t_op_min" if "t_op_min" in o else "mean_min"] = {"scale": k}
    ov["operations"][a["operation"]] = d
try:
    cfg = apply_overrides(base, ov)
except ConfigError as exc:
    st.error(str(exc))
    st.stop()
ref_cfg = apply_overrides(with_demand(load_config(), demand),
                          {"simulation": {"measure_weeks": int(weeks)}})
cap = cfg.week_min / cfg.op_mean_min("steeking")
st.caption(f"Takt {cfg.takt_min:.0f} min/EVA · steeking capacity {cap:.2f} EVA/week · "
           f"{cfg.raw['simulation']['warmup_weeks']} warm-up + {weeks} measured weeks")
if cap < demand:
    st.error("Steeking capacity is below demand: the system is unstable and lead time grows "
             "without bound over the horizon.")

if st.button("Run simulation", type="primary", key="run"):
    with st.spinner(f"Simulating {reps} replications..."):
        st.session_state["res"] = simulate(json.dumps(cfg.to_dict(), sort_keys=True), reps,
                                           workers)
        st.session_state["ref"] = (simulate(json.dumps(ref_cfg.to_dict(), sort_keys=True), reps,
                                            workers) if compare else None)

res = st.session_state.get("res")
if res is None:
    st.info("Set the inputs and press **Run simulation**.")
    s = committed("scenario_summary.csv")
    if s is not None:
        st.subheader("Committed scenario results (full run)")
        st.dataframe(s[["scenario", "name", "demand_eva_per_week", "throughput_eva_week_mean",
                        "lt_mean_days_mean", "lt_p95_days_mean", "on_time_mean",
                        "bottleneck"]].round(2), hide_index=True, width="stretch")
    st.stop()

r, ref = res["reps"], st.session_state.get("ref")


def tile(col, label: str, metric: str, fmt: str, unit: str, scale: float = 1.0,
         inverse: bool = False) -> None:
    m, h, _ = t_ci(r[metric] * scale)
    delta = None
    if ref is not None:
        d = paired_difference(ref["reps"][metric].to_numpy() * scale, r[metric].to_numpy() * scale)
        delta = f"{d['diff_mean']:+{fmt}} vs S0"
    col.metric(label, f"{m:{fmt}}{unit}", delta=delta, delta_color="inverse" if inverse else
               "normal", help=f"95% CI ± {h:{fmt}}{unit} ({len(r)} replications)")


c = st.columns(6)
tile(c[0], "Throughput (EVA/wk)", "throughput_eva_week", ".2f", "")
tile(c[1], "Order lead time", "lt_mean_days", ".1f", " d", inverse=True)
tile(c[2], "Lead time P95", "lt_p95_days", ".1f", " d", inverse=True)
tile(c[3], "On-time delivery", "on_time", ".0f", " %", scale=100)
tile(c[4], "WIP", "wip_total", ".1f", " EVA", inverse=True)
bn = res["bneck"].iloc[0]
c[5].metric("Bottleneck", cfg.resource_label(bn["resource"]).split()[0],
            help=f"{cfg.resource_label(bn['resource'])}: highest active share in "
                 f"{100 * bn['share']:.0f}% of replications")

t1, t2, t3, t4, t5 = st.tabs(["Lead time", "Resource states", "Bottleneck", "Demand curve",
                              "Scenario comparison"])
with t1:
    fig, ax = plt.subplots(figsize=(9, 3.4))
    h = res["hist"][:-1] / max(1, res["hist"].sum()) * 100
    ax.bar(LT_BINS_DAYS[:-1], h, width=0.9, align="edge", color=plots.SERIES[0])
    due = cfg.raw["demand"]["due_date_weeks"] * cfg.raw["calendar"]["days_per_week"]
    ax.axvline(due, color=plots.CRITICAL, lw=1.2)
    nz = np.nonzero(h > 0.05)[0]
    ax.set_xlim(0, max(due + 3, (nz.max() + 3) if len(nz) else due + 3))
    ax.set_xlabel("Order lead time (working days); red = due date")
    ax.set_ylabel("Share of orders (%)")
    st.pyplot(fig)
    plt.close(fig)
with t2:
    rs = res["res"].sort_values("active")
    fig, ax = plt.subplots(figsize=(9, 5))
    left = np.zeros(len(rs))
    for s_ in plots.STATE_ORDER:
        v = rs[s_].to_numpy() * 100
        ax.barh(rs["label"], v, left=left, color=plots.STATE_COLORS[s_], label=s_, height=0.65,
                edgecolor=plots.SURFACE, linewidth=1.2)
        left += v
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of available server time (%)")
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=5, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    st.pyplot(fig)
    plt.close(fig)
    st.dataframe(res["res"][["label", "servers", "busy", "changeover", "down", "starved",
                             "mean_wait_min"]].round(3), hide_index=True, width="stretch")
with t3:
    b = res["bneck"]
    fig, ax = plt.subplots(figsize=(9, 2.8))
    ax.barh([cfg.resource_label(x) for x in b["resource"]], b["share"] * 100,
            color=plots.SERIES[0], height=0.6)
    ax.set_xlim(0, 105)
    ax.set_xlabel("Replications as bottleneck (%) - highest active share")
    ax.grid(axis="y", visible=False)
    st.pyplot(fig)
    plt.close(fig)
with t4:
    sw = committed("demand_sweep.csv")
    if sw is not None:
        fig, ax = plt.subplots(figsize=(9, 3.8))
        for s_, g in sw.groupby("scenario", sort=False):
            ax.plot(g["demand_eva_per_week"], g["lt_mean_days_mean"], "-o", ms=4,
                    color=plots.SCEN_COLORS.get(s_, plots.INK), label=s_)
        ax.plot([demand], [r["lt_mean_days"].mean()], "*", ms=16, color=plots.CRITICAL,
                label="this run")
        ax.set_xlabel("Demand (EVA/week)")
        ax.set_ylabel("Mean order lead time (days)")
        ax.legend(fontsize=8, ncol=3)
        st.pyplot(fig)
        plt.close(fig)
        st.caption("Curves: committed demand sweep (results/demand_sweep.csv). Star: this run.")
with t5:
    if ref is not None:
        out = []
        for m, lab in (("throughput_eva_week", "Throughput (EVA/week)"),
                       ("lt_mean_days", "Order lead time (days)"),
                       ("lt_p95_days", "P95 lead time (days)"), ("on_time", "On-time share"),
                       ("wip_total", "WIP (EVA)")):
            d = paired_difference(ref["reps"][m].to_numpy(), r[m].to_numpy())
            out.append({"metric": lab, "S0": ref["reps"][m].mean(), "this run": r[m].mean(),
                        "difference": d["diff_mean"], "95% CI low": d["diff_ci_low"],
                        "95% CI high": d["diff_ci_high"], "significant": d["significant"]})
        st.markdown(f"**This run vs S0 at {demand:g} EVA/week** (paired, common random numbers)")
        st.dataframe(pd.DataFrame(out).round(3), hide_index=True, width="stretch")
    s = committed("scenario_summary.csv")
    if s is not None:
        st.markdown("**Committed scenario results** (`results/scenario_summary.csv`)")
        st.dataframe(s[["scenario", "name", "demand_eva_per_week", "lt_mean_days_mean",
                        "lt_p95_days_mean", "on_time_mean", "bottleneck"]].round(2),
                     hide_index=True, width="stretch")
