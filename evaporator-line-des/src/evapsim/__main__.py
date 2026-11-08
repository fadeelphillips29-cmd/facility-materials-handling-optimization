"""Command-line interface: ``python -m evapsim <step> [--quick] [--reps N] [--workers N]``.

Steps
-----
handcalc     hand-calculated VSM, resource loads, critical path, process-flow figure
analytic     fin-press calibration, OEE options, weld metrics, analytic Kingman
data         regenerate data/time_study_samples.csv and data/observed_weekly_output.csv
input        Phase 3 input analysis (distribution fitting)
baseline     Phase 5 baseline Monte Carlo + convergence
validate     Phase 6 validation vs data/observed_weekly_output.csv + Kingman check
uncertainty  Phase 5 two-level Monte Carlo, variance decomposition, steeking cases
report       regenerate README/docs tables from config and results
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

STEPS: dict[str, Callable[[argparse.Namespace], None]] = {}


def step(name: str) -> Callable[[Callable[[argparse.Namespace], None]],
                                Callable[[argparse.Namespace], None]]:
    """Register a CLI step."""
    def deco(fn: Callable[[argparse.Namespace], None]) -> Callable[[argparse.Namespace], None]:
        STEPS[name] = fn
        return fn
    return deco


@step("handcalc")
def _handcalc(args: argparse.Namespace) -> None:
    from .pipeline import step_handcalc

    step_handcalc()


@step("analytic")
def _analytic(args: argparse.Namespace) -> None:
    from .pipeline import step_analytic

    step_analytic()


@step("data")
def _data(args: argparse.Namespace) -> None:
    from .datagen import write_observed, write_time_study

    print(write_time_study())
    print(write_observed())


@step("input")
def _input(args: argparse.Namespace) -> None:
    from .input_analysis import run_input_analysis

    d = run_input_analysis()
    print(d[d["selected"]][["operation", "distribution", "delta_aic", "ks_pvalue"]]
          .round(3).to_string(index=False))


@step("baseline")
def _baseline(args: argparse.Namespace) -> None:
    from .pipeline import step_baseline

    step_baseline(args.quick, args.reps, args.workers)


@step("uncertainty")
def _uncertainty(args: argparse.Namespace) -> None:
    from .pipeline import step_uncertainty

    step_uncertainty(args.quick, args.workers)


@step("validate")
def _validate(args: argparse.Namespace) -> None:
    from .pipeline import step_validate

    step_validate(args.quick, args.workers)


@step("report")
def _report(args: argparse.Namespace) -> None:
    from .report import render_all

    for f, blocks in render_all().items():
        print(f"{f}: {', '.join(blocks) if blocks else 'no blocks'}")


def build_parser() -> argparse.ArgumentParser:
    """Argument parser."""
    p = argparse.ArgumentParser(prog="evapsim", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("step", choices=sorted(STEPS))
    p.add_argument("--quick", action="store_true", help="quick mode -> results/quick/")
    p.add_argument("--reps", type=int, default=None, help="override replication count")
    p.add_argument("--workers", type=int, default=None, help="worker processes")
    return p


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    args = build_parser().parse_args(argv)
    STEPS[args.step](args)
    return 0


if __name__ == "__main__":
    sys.exit(main())
