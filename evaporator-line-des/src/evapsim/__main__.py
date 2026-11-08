"""Command-line interface: ``python -m evapsim <step> [--quick] [--reps N] [--workers N]``.

Steps
-----
data         regenerate the fictional data sets in data/
input        Phase 2 input analysis (distribution fitting)
capacity     static capacity hand-calculation (results/static_capacity.csv)
baseline     Phase 4-5 baseline Monte Carlo run + convergence analysis
validate     Phase 6 validation against data/observed_line_data.csv
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


STEPS = {
    "data": _data,
    "input": _input,
    "capacity": _capacity,
    "baseline": _baseline,
    "validate": _validate,
}


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    STEPS[args.step](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
