"""Phase 7b - one-at-a-time (OAT) sensitivity analysis on daily throughput.

Factors: each station's mean cycle time, MTBF and MTTR (where breakdowns are
modelled) and the inter-station buffer size. Each factor is set to -10 % and
+10 % of its baseline value while all other factors stay at baseline. Buffer
size is changed by -1 / +1 unit on every buffer (5 -> 4 / 6), because 10 %
of 5 units is not a whole number (ASSUMPTIONS A32). Every run reuses the
baseline replication seeds (CRN), so each effect is a paired difference with
its own 95 % CI.

Elasticity = (% change in throughput) / (% change in the factor). It allows
factors to be compared even though the buffer step is +/-20 %.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from . import plots
from .config import LineConfig, apply_overrides, load_config
from .metrics import paired_difference
from .runner import run_replications

STEP = 0.10


@dataclass(frozen=True)
class Factor:
    """One sensitivity factor and how to perturb it."""

    key: str
    label: str
    station_id: int | None
    field: str


def factors(cfg: LineConfig) -> list[Factor]:
    """All OAT factors for the configuration."""
    out = [Factor(f"S{s.id}.ct", f"S{s.id} cycle time", s.id, "ct_mean_s") for s in cfg.stations]
    for s in cfg.stations:
        if s.has_breakdowns:
            out.append(Factor(f"S{s.id}.mtbf", f"S{s.id} MTBF", s.id, "mtbf_min"))
            out.append(Factor(f"S{s.id}.mttr", f"S{s.id} MTTR", s.id, "mttr_min"))
    out.append(Factor("buffers", "All buffer sizes (±1 unit)", None, "buffers"))
    return out


def perturbed(cfg: LineConfig, f: Factor, direction: int) -> tuple[LineConfig, float, float]:
    """Return (config, new value, % change) for factor ``f`` moved down (-1) or up (+1)."""
    if f.field == "buffers":
        base = cfg.buffer_capacities[0]
        new = max(1, base + direction)
        return apply_overrides(cfg, {"buffers": {"all": new}}), float(new), 100.0 * (new / base - 1)
    base = getattr(cfg.station(f.station_id), f.field)
    new = base * (1 + direction * STEP)
    return (apply_overrides(cfg, {"stations": {f.station_id: {f.field: new}}}), float(new),
            100.0 * direction * STEP)


def run_sensitivity(n_reps: int, out: Path, fig: Path, workers: int | None = None,
                    log=print) -> pd.DataFrame:
    """Run the OAT design, write ``sensitivity_oat.csv`` and the tornado chart."""
    cfg = load_config()
    base = run_replications(cfg, n_reps, label="base", workers=workers).reps
    rows = []
    for f in factors(cfg):
        for direction in (-1, +1):
            c, new, pct = perturbed(cfg, f, direction)
            reps = run_replications(c, n_reps, label=f.key, workers=workers).reps
            d_th = paired_difference(base["throughput_per_day"].to_numpy(),
                                     reps["throughput_per_day"].to_numpy())
            d_lt = paired_difference(base["lt_mean_min"].to_numpy(),
                                     reps["lt_mean_min"].to_numpy())
            base_val = (cfg.buffer_capacities[0] if f.field == "buffers"
                        else getattr(cfg.station(f.station_id), f.field))
            rows.append({
                "factor": f.key, "label": f.label, "station_id": f.station_id,
                "parameter": f.field, "level": "low" if direction < 0 else "high",
                "base_value": base_val, "value": new, "param_change_pct": pct,
                "throughput_base": float(base["throughput_per_day"].mean()),
                "throughput": float(reps["throughput_per_day"].mean()),
                "th_diff": d_th["diff_mean"], "th_diff_ci_low": d_th["diff_ci_low"],
                "th_diff_ci_high": d_th["diff_ci_high"],
                "th_rel_change_pct": d_th["rel_change_pct"],
                "th_significant": d_th["significant"],
                "elasticity": d_th["rel_change_pct"] / pct,
                "lt_diff_min": d_lt["diff_mean"],
                "lt_diff_ci_low": d_lt["diff_ci_low"], "lt_diff_ci_high": d_lt["diff_ci_high"],
            })
            log(f"[evapsim] sensitivity {f.key:<9} {'-+'[direction > 0]}: "
                f"dTH {d_th['diff_mean']:+6.2f} units/day")
    df = pd.DataFrame(rows)
    rng = (df.pivot_table(index="factor", columns="level", values="th_diff")
           .assign(swing=lambda x: (x["high"] - x["low"]).abs()))
    df["swing"] = df["factor"].map(rng["swing"])
    df = df.sort_values(["swing", "factor", "level"], ascending=[False, True, False])
    out.mkdir(parents=True, exist_ok=True)
    df.round(5).to_csv(out / "sensitivity_oat.csv", index=False)
    plots.tornado_figure(df, float(base["throughput_per_day"].mean()), n_reps,
                         fig / "sensitivity_tornado.png")
    return df


CONWIP_LIMITS = (10, 15, 20, 25, 30, 40, 60)


def conwip_sweep(n_reps: int, out: Path, fig: Path, scenario_ids: tuple[str, ...] = ("S0", "S5"),
                 limits: tuple[int, ...] = CONWIP_LIMITS, workers: int | None = None,
                 log=print) -> pd.DataFrame:
    """Throughput / lead time / WIP as a function of the CONWIP limit (operating curve).

    Each point is paired (CRN) against the scenario at its configured limit, so
    the throughput cost of a tighter WIP cap has its own 95 % CI.
    """
    from .config import load_scenarios

    scen = load_scenarios()
    rows = []
    for sid in scenario_ids:
        cfg = scen[sid].config
        ref = run_replications(cfg, n_reps, workers=workers).reps
        for lim in limits:
            c = apply_overrides(cfg, {"release": {"rule": "conwip", "conwip_limit": lim}})
            reps = run_replications(c, n_reps, workers=workers).reps
            d = paired_difference(ref["throughput_per_day"].to_numpy(),
                                  reps["throughput_per_day"].to_numpy())
            rows.append({
                "scenario": sid, "conwip_limit": lim,
                "reference_limit": cfg.release.conwip_limit,
                "throughput_per_day": float(reps["throughput_per_day"].mean()),
                "th_diff_vs_reference": d["diff_mean"], "th_diff_ci_low": d["diff_ci_low"],
                "th_diff_ci_high": d["diff_ci_high"],
                "lt_mean_min": float(reps["lt_mean_min"].mean()),
                "lt_p95_min": float(reps["lt_p95_min"].mean()),
                "wip_avg": float(reps["wip_avg"].mean()),
            })
            log(f"[evapsim] conwip {sid} limit {lim:>3}: TH {rows[-1]['throughput_per_day']:.1f}"
                f", LT {rows[-1]['lt_mean_min']:.1f} min")
    df = pd.DataFrame(rows)
    out.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(out / "conwip_sweep.csv", index=False)
    plots.conwip_figure(df, fig / "conwip_sweep.png")
    return df
