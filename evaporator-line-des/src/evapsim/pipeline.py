"""Analysis steps used by the CLI. Every step is seeded and writes to results/."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from . import equations as eq
from . import plots
from .config import DOCS_DIR, RESULTS_DIR, load_config


def out_dirs(quick: bool = False) -> tuple[Path, Path]:
    """Results and figure directories (results/quick/ in quick mode)."""
    out = RESULTS_DIR / "quick" if quick else RESULTS_DIR
    fig = out / "figures"
    fig.mkdir(parents=True, exist_ok=True)
    return out, fig


def log(msg: str) -> None:
    """Progress message."""
    print(f"[evapsim] {msg}", flush=True)


def step_handcalc() -> None:
    """Phase 1/2 analytical outputs: hand-calc VSM, loads, critical path, fin press."""
    cfg = load_config()
    out, fig = out_dirs()
    eq.hand_calc_vsm(cfg).round(4).to_csv(out / "vsm_hand_calc.csv", index=False)
    eq.resource_loads(cfg).round(4).to_csv(out / "resource_loads.csv", index=False)
    cp = eq.deterministic_lead_time(cfg)
    pd.DataFrame([cp]).round(3).to_csv(out / "deterministic_lead_time.csv", index=False)
    plots.process_flow_figure(DOCS_DIR / "process_flow.png",
                              cfg.raw["flags"]["wash_before_test"],
                              cfg.raw["flags"]["include_outsourced_coating"])
    log(f"hand calc: bottleneck {eq.bottleneck(cfg)}, single-order lead time "
        f"{cp['lead_time_min']:.0f} min = {cp['lead_time_days']:.2f} working days")
