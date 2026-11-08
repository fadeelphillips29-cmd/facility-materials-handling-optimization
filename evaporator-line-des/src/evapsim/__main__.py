"""Command-line interface: ``python -m evapsim <step> [--quick] [--reps N] [--workers N]``.

Steps
-----
data         regenerate the fictional data sets in data/
input        Phase 2 input analysis (distribution fitting)
capacity     static capacity hand-calculation (results/static_capacity.csv)
baseline     Phase 4-5 baseline Monte Carlo run + convergence analysis
validate     Phase 6 validation against data/observed_line_data.csv
scenarios    Phase 7 scenario comparison S0-S6 (paired CRN differences)
sensitivity  Phase 7 one-at-a-time sensitivity and tornado chart
conwip       Phase 7 CONWIP-limit sweep (WIP / throughput operating curve)
vsm          Phase 8 current/future-state VSM diagrams (docs/vsm_*.png)
report       Phase 10 regenerate README/docs result tables from results/*.csv
"""

from __future__ import annotations

import argparse
import sys

from . import pipeline


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    p = argparse.ArgumentParser(prog="evapsim", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=sorted(STEPS), help="analysis step to run")
    p.add_argument("--quick", action="store_true",
                   help="use quick_replications and write to results/quick/")
    p.add_argument("--reps", type=int, default=None, help="override the replication count")
    p.add_argument("--workers", type=int, default=None,
                   help="worker processes (default: all CPUs or $EVAPSIM_WORKERS)")
    return p


def _data(args: argparse.Namespace) -> None:
    from .datagen import write_observed, write_time_study

    print(write_time_study())
    print(write_observed())


def _input(args: argparse.Namespace) -> None:
    from .input_analysis import run_input_analysis

    df = run_input_analysis()
    sel = df[df["selected"]][["station_id", "distribution", "aic", "ks_pvalue"]]
    print(sel.to_string(index=False))


def _capacity(args: argparse.Namespace) -> None:
    from .config import load_config

    out, _ = pipeline.out_dirs(False)
    df = pipeline.static_capacity(load_config())
    df.round(3).to_csv(out / "static_capacity.csv", index=False)
    print(df.round(2).to_string(index=False))


def _baseline(args: argparse.Namespace) -> None:
    pipeline.step_baseline(quick=args.quick, reps=args.reps, workers=args.workers)


def _validate(args: argparse.Namespace) -> None:
    from .validation import run_validation

    out, fig = pipeline.out_dirs(args.quick)
    if not (out / "baseline_replications.csv").exists():
        pipeline.step_baseline(quick=args.quick, reps=args.reps, workers=args.workers)
    summary = run_validation(out, fig)
    print(summary.round(3).to_string(index=False))


def _scenarios(args: argparse.Namespace) -> None:
    from .config import load_config
    from .scenarios import run_and_save

    out, fig = pipeline.out_dirs(args.quick)
    n = pipeline.n_reps(load_config(), args.quick, args.reps)
    summary = run_and_save(n, out, fig, workers=args.workers,
                           progress=lambda sid: pipeline._progress(f"scenario {sid}"))
    pipeline.write_meta(out, "scenarios", {"replications": n})
    cols = ["scenario", "name", "throughput_per_day_mean", "lt_mean_min_mean",
            "takt_compliance_mean", "bottleneck_station", "bottleneck_share"]
    print(summary[cols].round(3).to_string(index=False))


def _sensitivity(args: argparse.Namespace) -> None:
    from .config import load_config
    from .sensitivity import run_sensitivity

    out, fig = pipeline.out_dirs(args.quick)
    cfg = load_config()
    n = args.reps or (max(20, cfg.sim.quick_replications // 2) if args.quick
                      else cfg.sim.sensitivity_replications)
    df = run_sensitivity(n, out, fig, workers=args.workers)
    pipeline.write_meta(out, "sensitivity", {"replications": n})
    print(df[["label", "level", "th_diff", "th_rel_change_pct", "elasticity"]].head(12)
          .round(2).to_string(index=False))


def _conwip(args: argparse.Namespace) -> None:
    from .config import load_config
    from .sensitivity import conwip_sweep

    out, fig = pipeline.out_dirs(args.quick)
    cfg = load_config()
    n = args.reps or (max(20, cfg.sim.quick_replications // 2) if args.quick
                      else cfg.sim.sensitivity_replications)
    conwip_sweep(n, out, fig, workers=args.workers)
    pipeline.write_meta(out, "conwip", {"replications": n})


def _vsm(args: argparse.Namespace) -> None:
    from .vsm import build_vsms

    out, _ = pipeline.out_dirs(args.quick)
    if not (out / "scenario_stations.csv").exists():
        _scenarios(args)
    docs = out / "figures" if args.quick else None
    summary = build_vsms(out, docs) if docs else build_vsms(out)
    print(summary.round(3).to_string(index=False))


def _report(args: argparse.Namespace) -> None:
    from .report import render_all

    for f, blocks in render_all().items():
        print(f"{f}: {', '.join(blocks) if blocks else 'no blocks'}")


STEPS = {
    "data": _data,
    "input": _input,
    "capacity": _capacity,
    "baseline": _baseline,
    "validate": _validate,
    "scenarios": _scenarios,
    "sensitivity": _sensitivity,
    "conwip": _conwip,
    "vsm": _vsm,
    "report": _report,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    STEPS[args.step](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
