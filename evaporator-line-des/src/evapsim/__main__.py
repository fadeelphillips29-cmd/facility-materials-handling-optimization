"""Command-line interface: ``python -m evapsim <step> [--quick] [--reps N] [--workers N]``.

Steps
-----
handcalc     hand-calculated VSM, resource loads, critical path, process-flow figure
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
