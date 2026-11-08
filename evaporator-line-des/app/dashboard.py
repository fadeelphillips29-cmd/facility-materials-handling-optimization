"""Streamlit dashboard for the evaporator coil line simulation.

Run with:  streamlit run app/dashboard.py

Pick a scenario as the starting point, edit key parameters in the sidebar,
choose the number of replications and press **Run simulation**. The run is
compared with the baseline (S0) using the same replication seeds (common
random numbers), so the paired difference shows the effect of the edits alone.
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
    apply_overrides,
    config_from_dict,
    load_config,
    load_scenarios,
)
from evapsim.metrics import bottleneck_frequency, paired_difference, t_ci  # noqa: E402
from evapsim.runner import LT_BIN_EDGES, run_replications, station_summary  # noqa: E402

st.set_page_config(page_title="Evaporator line DES", layout="wide")
plots.apply_style()

EDITABLE = ["ct_mean_s", "ct_cv", "servers", "mtbf_min", "mttr_min", "changeover_min",
            "scrap_rate"]


@st.cache_data(show_spinner=False)
def scenario_dicts() -> dict[str, dict]:
    """YAML-shaped config dict and label of every scenario."""
    return {sid: {"name": s.name, "description": s.description, "cfg": s.config.to_dict()}
            for sid, s in load_scenarios().items()}


@st.cache_data(show_spinner=False, max_entries=16)
def simulate(cfg_json: str, reps: int, workers: int) -> dict:
    """Run replications (cached on the full configuration and replication count)."""
    cfg = config_from_dict(json.loads(cfg_json))
    run = run_replications(cfg, reps, label="run", workers=workers)
    return {"reps": run.reps, "stations": station_summary(run), "lt_hist": run.lt_hist,
            "daily": run.daily, "bneck": bottleneck_frequency(run.reps, cfg)}


@st.cache_data(show_spinner=False)
def precomputed_scenarios() -> pd.DataFrame | None:
    """Scenario summary from the committed full run (results/scenario_summary.csv)."""
    path = RESULTS_DIR / "scenario_summary.csv"
    return pd.read_csv(path) if path.exists() else None


# ------------------------------------------------------------------- sidebar
scen = scenario_dicts()
sb = st.sidebar
sb.header("1. Starting point")
sid = sb.selectbox("Scenario", list(scen), format_func=lambda s: f"{s} - {scen[s]['name']}",
                   key="scenario")
sb.caption(scen[sid]["description"])
base = scen[sid]["cfg"]

sb.header("2. Line parameters")
demand = sb.number_input("Customer demand (units/day)", 50, 2000,
                         int(base["demand"]["units_per_day"]), step=10, key="demand")
buf = sb.slider("Buffer capacity, all buffers (units)", 1, 30,
                int(base["buffers"]["capacities"][0]), key="buffer")
rule = sb.radio("Release rule", ["conwip", "unlimited"],
                index=0 if base["release"]["rule"] == "conwip" else 1, horizontal=True,
                key="rule")
limit = sb.number_input("CONWIP limit (units)", 1, 500, int(base["release"]["conwip_limit"]),
                        disabled=rule != "conwip", key="conwip")
batch = sb.number_input("Batch size (units)", 1, 200, int(base["orders"]["batch_size"]),
                        key="batch")

sb.header("3. Run settings")
reps = sb.slider("Replications", 5, 200, 30, step=5, key="reps")
days = sb.slider("Measured days per replication", 5, 40, int(base["simulation"]["days"]),
                 key="days")
workers = sb.slider("Worker processes", 1, 8, 4, key="workers")
compare = sb.checkbox("Compare with baseline S0 (paired, same seeds)", value=True,
                      key="compare")

# ---------------------------------------------------------------------- main
st.title("Evaporator Coil Assembly Line: DES + Monte Carlo")
st.warning("**Fictional data.** The line, its parameters and all results are illustrative "
           "and do not describe any real company or plant.", icon="⚠️")

st.subheader("Station parameters")
st.caption("Edit cells to change the model. Cycle times are seconds for the Medium model, "
           "MTBF/MTTR are minutes of operating time (empty = no breakdowns), changeover in "
           "minutes, scrap as a fraction.")
st_table = pd.DataFrame(base["stations"])[["id", "name", *EDITABLE]]
edited = st.data_editor(st_table, disabled=["id", "name"], hide_index=True,
                        width="stretch", key=f"stations_{sid}")

cfg_dict = json.loads(json.dumps(base))
cfg_dict["simulation"]["days"] = int(days)
for _, row in edited.iterrows():
    target = next(s for s in cfg_dict["stations"] if int(s["id"]) == int(row["id"]))
    for col in EDITABLE:
        val = row[col]
        target[col] = None if (val is None or (isinstance(val, float) and np.isnan(val))) else (
            int(val) if col == "servers" else float(val))
    target["changeover"] = bool(target["changeover_min"] and target["changeover_min"] > 0)
try:
    cfg = apply_overrides(cfg_dict, {
        "demand": {"units_per_day": float(demand)},
        "buffers": {"all": int(buf)},
        "release": {"rule": rule, "conwip_limit": int(limit)},
        "orders": {"batch_size": int(batch)},
    })
except ConfigError as exc:
    st.error(str(exc))
    st.stop()

base_cfg = apply_overrides(load_config(), {"simulation": {"days": int(days)}})
st.caption(f"Takt time {cfg.takt_s:.1f} s · {cfg.n_stations} stations · "
           f"{cfg.sim.warmup_days} warm-up day + {days} measured days per replication")

if st.button("Run simulation", type="primary", key="run"):
    with st.spinner(f"Simulating {reps} replications..."):
        st.session_state["result"] = simulate(json.dumps(cfg.to_dict(), sort_keys=True), reps,
                                              workers)
        st.session_state["baseline"] = (
            simulate(json.dumps(base_cfg.to_dict(), sort_keys=True), reps, workers)
            if compare else None)
        st.session_state["demand_run"] = cfg.demand_per_day

res = st.session_state.get("result")
if res is None:
    st.info("Set the parameters and press **Run simulation**.")
    summary = precomputed_scenarios()
    if summary is not None:
        st.subheader("Committed scenario results (full run)")
        st.dataframe(summary[["scenario", "name", "replications", "throughput_per_day_mean",
                              "takt_compliance_mean", "lt_mean_min_mean", "wip_avg_mean",
                              "bottleneck_station"]].round(2), hide_index=True,
                     width="stretch")
    st.stop()

r = res["reps"]
bl = st.session_state.get("baseline")
d_run = st.session_state.get("demand_run", cfg.demand_per_day)


def tile(col, label: str, metric: str, fmt: str, unit: str = "", scale: float = 1.0,
         inverse: bool = False) -> None:
    m, h, _ = t_ci(r[metric] * scale)
    delta = None
    if bl is not None:
        d = paired_difference(bl["reps"][metric].to_numpy() * scale, r[metric].to_numpy() * scale)
        delta = f"{d['diff_mean']:+{fmt}} vs S0"
    col.metric(label, f"{m:{fmt}}{unit}", delta=delta,
               delta_color="inverse" if inverse else "normal",
               help=f"95% CI ± {h:{fmt}}{unit} over {len(r)} replications")


c = st.columns(6)
tile(c[0], "Throughput", "throughput_per_day", ".1f", " /day")
tile(c[1], "Takt compliance", "takt_compliance", ".0f", " %", scale=100)
tile(c[2], "Lead time (mean)", "lt_mean_min", ".1f", " min", inverse=True)
tile(c[3], "Lead time (P95)", "lt_p95_min", ".1f", " min", inverse=True)
tile(c[4], "WIP", "wip_avg", ".1f", " units", inverse=True)
bn = res["bneck"].loc[res["bneck"]["share"].idxmax()]
c[5].metric("Bottleneck", f"S{int(bn['station_id'])}",
            help=f"{bn['station']}: bottleneck in {bn['share'] * 100:.0f}% of replications")
st.caption(f"Demand {d_run:.0f}/day: attainment "
           f"{100 * r['throughput_per_day'].mean() / d_run:.1f} %")

t1, t2, t3, t4 = st.tabs(["Lead time", "Station states", "Bottleneck", "Scenario comparison"])
with t1:
    hist = res["lt_hist"][: len(LT_BIN_EDGES) - 1].astype(float)
    share = hist / max(1.0, hist.sum()) * 100
    upto = int(np.searchsorted(np.cumsum(share), 99.5)) + 2
    fig, ax = plt.subplots(figsize=(9, 3.6))
    ax.bar(LT_BIN_EDGES[:upto], share[:upto], width=1.8, align="edge", color=plots.SERIES[0])
    for k in ("p50", "p90", "p95"):
        v = r[f"lt_{k}_min"].mean()
        ax.axvline(v, color=plots.INK_2, lw=1)
        ax.text(v, ax.get_ylim()[1] * 0.92, f" {k.upper()} {v:.1f}", fontsize=8,
                color=plots.INK_2)
    ax.set_xlabel("Line lead time (productive minutes)")
    ax.set_ylabel("Share of good units (%)")
    st.pyplot(fig)
    plt.close(fig)
with t2:
    sst = res["stations"].sort_values("station_id", ascending=False)
    fig, ax = plt.subplots(figsize=(9, 3.8))
    left = np.zeros(len(sst))
    labels = [f"S{i} {n}" for i, n in zip(sst["station_id"], sst["station"], strict=True)]
    for s in plots.STATE_ORDER:
        v = sst[s].to_numpy() * 100
        ax.barh(labels, v, left=left, color=plots.STATE_COLORS[s], label=s, height=0.62,
                edgecolor=plots.SURFACE, linewidth=1.5)
        left += v
    ax.set_xlim(0, 100)
    ax.set_xlabel("Share of scheduled time (%)")
    ax.grid(axis="y", visible=False)
    ax.legend(ncol=5, loc="lower center", bbox_to_anchor=(0.5, 1.0))
    st.pyplot(fig)
    plt.close(fig)
    st.dataframe(res["stations"][["station_id", "station", "busy", "starved", "blocked", "down",
                                  "changeover", "uptime", "fpy", "buffer_in_front_avg"]]
                 .round(3), hide_index=True, width="stretch")
with t3:
    b = res["bneck"]
    fig, ax = plt.subplots(figsize=(9, 3.2))
    ax.bar([f"S{i}" for i in b["station_id"]], b["share"] * 100, color=plots.SERIES[0],
           width=0.6)
    ax.set_ylim(0, 105)
    ax.set_xlabel("Station")
    ax.set_ylabel("Replications as bottleneck (%)")
    st.pyplot(fig)
    plt.close(fig)
    st.caption("Bottleneck = station with the highest active share (busy + down + "
               "changeover) in a replication (active-period method).")
with t4:
    if bl is not None:
        rows = []
        for m, lab in (("throughput_per_day", "Throughput (units/day)"),
                       ("lt_mean_min", "Mean lead time (min)"),
                       ("lt_p95_min", "P95 lead time (min)"), ("wip_avg", "WIP (units)"),
                       ("takt_compliance", "Takt compliance (share of days)")):
            d = paired_difference(bl["reps"][m].to_numpy(), r[m].to_numpy())
            rows.append({"metric": lab, "S0 baseline": bl["reps"][m].mean(),
                         "this run": r[m].mean(), "difference": d["diff_mean"],
                         "95% CI low": d["diff_ci_low"], "95% CI high": d["diff_ci_high"],
                         "significant": d["significant"]})
        st.markdown("**This run vs baseline S0** (paired, common random numbers)")
        st.dataframe(pd.DataFrame(rows).round(3), hide_index=True, width="stretch")
    summary = precomputed_scenarios()
    if summary is not None:
        st.markdown("**Committed scenario results** (`results/scenario_summary.csv`)")
        fig, ax = plt.subplots(figsize=(9, 3.6))
        y = np.arange(len(summary))[::-1]
        ax.barh(y, summary["throughput_per_day_mean"], color=plots.SERIES[0], height=0.6)
        ax.axvline(summary["demand_per_day"].iloc[0], color=plots.CRITICAL, lw=1.5)
        ax.set_yticks(y, summary["scenario"] + " " + summary["name"].str.split(" \\(").str[0])
        ax.set_xlabel("Throughput (units/day); red line = demand")
        ax.grid(axis="y", visible=False)
        st.pyplot(fig)
        plt.close(fig)
