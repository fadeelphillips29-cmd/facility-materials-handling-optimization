"""Configuration loading, validation, time scaling and scenario overrides.

The model is driven by ``config/line_parameters.yaml``. :class:`LineConfig`
wraps that YAML dictionary, validates it, and gives the derived quantities the
model needs, for example operation means per EVA after ``time_scale_factor``
and the crew-size adjustment, or calendar delays in working minutes. Scenario
overrides in ``config/scenarios.yaml`` are applied to the plain dictionary,
and the result is validated again.
"""

from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = PROJECT_ROOT / "config"
DEFAULT_LINE_FILE = CONFIG_DIR / "line_parameters.yaml"
DEFAULT_SCENARIO_FILE = CONFIG_DIR / "scenarios.yaml"
RESULTS_DIR = PROJECT_ROOT / "results"
FIGURES_DIR = RESULTS_DIR / "figures"
DATA_DIR = PROJECT_ROOT / "data"
DOCS_DIR = PROJECT_ROOT / "docs"

DEPARTMENTS = ("engineering", "evaporator", "sheet_metal", "outsourced", "assembly")
SOURCES = ("time study", "estimate", "assumed")


class ConfigError(ValueError):
    """Raised when a configuration is missing fields or has invalid values."""


def load_yaml(path: str | Path) -> dict[str, Any]:
    """Read a YAML mapping from ``path``."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not contain a YAML mapping")
    return data


class LineConfig:
    """Validated model input with derived (scaled) quantities.

    Args:
        raw: YAML-shaped dictionary (see ``config/line_parameters.yaml``).
    """

    def __init__(self, raw: dict[str, Any]) -> None:
        self.raw = copy.deepcopy(raw)
        self.raw["crew_efficiency"] = {int(k): float(v)
                                       for k, v in self.raw.get("crew_efficiency", {}).items()}
        validate(self)

    # ---------------------------------------------------------------- sections
    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def to_dict(self) -> dict[str, Any]:
        """Deep copy of the underlying dictionary."""
        return copy.deepcopy(self.raw)

    @property
    def tsf(self) -> float:
        """Global ``time_scale_factor`` applied to every process time."""
        return float(self.raw.get("time_scale_factor", 1.0))

    @property
    def day_min(self) -> float:
        """Working minutes per day."""
        return float(self.raw["calendar"]["minutes_per_day"])

    @property
    def week_min(self) -> float:
        """Working minutes per week."""
        return self.day_min * float(self.raw["calendar"]["days_per_week"])

    @property
    def demand(self) -> float:
        """Demand in EVA per week."""
        return float(self.raw["demand"]["eva_per_week"])

    @property
    def lot(self) -> int:
        """Work-order size B (EVA per order = process lot)."""
        return int(self.raw["orders"]["lot_size"])

    @property
    def transfer_batch(self) -> int:
        """Transfer batch between stations (EVA)."""
        return int(self.raw["orders"]["transfer_batch"])

    @property
    def interarrival_min(self) -> float:
        """Mean time between work-order arrivals (working minutes)."""
        return self.lot / self.demand * self.week_min

    @property
    def takt_min(self) -> float:
        """Takt time per EVA = available time / demand (working minutes)."""
        return self.week_min / self.demand

    @property
    def deterministic(self) -> bool:
        """Zero-variance verification mode."""
        return bool(self.raw["simulation"].get("deterministic", False))

    @property
    def operations(self) -> dict[str, dict[str, Any]]:
        """Operation definitions keyed by operation id."""
        return self.raw["operations"]

    @property
    def resources(self) -> dict[str, dict[str, Any]]:
        """Resource definitions keyed by resource id."""
        return self.raw["resources"]

    # ------------------------------------------------------------- derivations
    def eta(self, crew: int) -> float:
        """Crew efficiency eta(c); beyond the table the last value is used."""
        table = self.raw["crew_efficiency"]
        if crew in table:
            return table[crew]
        return table[max(table)]

    def op_base_min(self, op: str) -> float:
        """Standard time per EVA of ``op`` at its basis crew, before scaling."""
        o = self.operations[op]
        if "t_op_min" in o:
            return float(o["n_ops"]) * float(o["t_op_min"]) + float(o.get("handling_min", 0.0))
        return float(o["mean_min"])

    def op_labour_min(self, op: str) -> float:
        """Labour content (operator-minutes per EVA), scaled."""
        o = self.operations[op]
        basis = int(o.get("crew_basis", 1))
        return self.op_base_min(op) * basis * self.raw["crew_efficiency"].get(basis, 1.0) * self.tsf

    def op_crew(self, op: str) -> int:
        """Crew size of the resource that performs ``op``."""
        return int(self.resources[self.operations[op]["resource"]].get("crew", 1))

    def op_mean_min(self, op: str) -> float:
        """Mean ELAPSED time per EVA of ``op`` with the configured crew (scaled).

        elapsed = labour content / (crew * eta(crew))
        """
        crew = self.op_crew(op)
        return self.op_labour_min(op) / (crew * self.eta(crew))

    def op_cv(self, op: str) -> float:
        """Coefficient of variation of the operation time (0 in deterministic mode)."""
        return 0.0 if self.deterministic else float(self.operations[op].get("cv", 0.0))

    def lead_time_mean_min(self, key: str) -> float:
        """Mean calendar delay ``key`` in working minutes (NOT time-scaled)."""
        return float(self.raw["lead_times"][key]["mean_days"]) * self.day_min

    def lead_time_cv(self, key: str) -> float:
        """CV of the calendar delay (0 in deterministic mode)."""
        return 0.0 if self.deterministic else float(self.raw["lead_times"][key].get("cv", 0.0))

    @property
    def fin_press(self) -> dict[str, float]:
        """Fin-press parameters with time scaling applied.

        Times (setup, reload, MTTR, MTBF and the run time through the rate) are
        multiplied by ``time_scale_factor``. Availability and OEE are unchanged.
        """
        fp = self.raw["fin_press"]
        k = self.tsf
        return {
            "r_n": float(fp["nominal_rate_fpm"]) / k,
            "F": float(fp["good_fins_per_eva"]),
            "S": float(fp["setup_min"]) * k,
            "setup_cv": 0.0 if self.deterministic else float(fp["setup_cv"]),
            "P": float(fp["performance"]),
            "Q": float(fp["quality"]),
            "MTBF": float(fp["mtbf_min"]) * k,
            "MTTR": float(fp["mttr_min"]) * k,
            "mttr_cv": float(fp.get("mttr_cv", 0.5)),
            "R": float(fp["reel_fins"]),
            "t_r": float(fp["reload_min"]) * k,
            "B": float(self.lot),
        }

    @property
    def rework(self) -> dict[str, Any]:
        """Rework parameters (time scaled, failure probability 0 when deterministic)."""
        rw = self.raw["rework"]
        return {"fail_prob": 0.0 if self.deterministic else float(rw["fail_prob"]),
                "rework_min": float(rw["rework_min"]) * self.tsf,
                "cv": 0.0 if self.deterministic else float(rw.get("cv", 0.0)),
                "resource": rw["resource"]}

    def resource_label(self, res: str) -> str:
        """Human-readable resource name."""
        return str(self.resources[res].get("label", res))

    def resource_ops(self, res: str) -> list[str]:
        """Operations performed by resource ``res`` (fin press included)."""
        ops = [o for o, d in self.operations.items() if d["resource"] == res]
        if self.raw["fin_press"]["resource"] == res:
            ops = ["fin_press", *ops]
        return ops


# ------------------------------------------------------------------ validation
def validate(cfg: LineConfig) -> None:
    """Check ranges and consistency; raise :class:`ConfigError` listing every problem."""
    r = cfg.raw
    errs: list[str] = []

    def need(cond: bool, msg: str) -> None:
        if not cond:
            errs.append(msg)

    for sec in ("calendar", "demand", "orders", "release", "flags", "fin_press", "operations",
                "resources", "lead_times", "rework", "simulation"):
        need(sec in r, f"missing section '{sec}'")
    if errs:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errs))
    need(cfg.tsf > 0, "time_scale_factor must be > 0")
    need(cfg.day_min > 0, "calendar.minutes_per_day must be > 0")
    need(r["calendar"]["days_per_week"] >= 1, "calendar.days_per_week must be >= 1")
    need(cfg.demand > 0, "demand.eva_per_week must be > 0")
    need(r["demand"].get("interarrival_cv", 0) >= 0, "demand.interarrival_cv must be >= 0")
    need(r["demand"].get("due_date_weeks", 1) > 0, "demand.due_date_weeks must be > 0")
    need(cfg.lot >= 1, "orders.lot_size must be >= 1")
    need(1 <= cfg.transfer_batch <= cfg.lot, "orders.transfer_batch must be in 1..lot_size")
    need(r["release"]["rule"] in ("push", "conwip"), "release.rule must be push or conwip")
    need(int(r["release"].get("conwip_limit_orders", 1)) >= 1,
         "release.conwip_limit_orders must be >= 1")
    fp = r["fin_press"]
    for k in ("nominal_rate_fpm", "good_fins_per_eva", "mtbf_min", "mttr_min", "reel_fins"):
        need(float(fp[k]) > 0, f"fin_press.{k} must be > 0")
    for k in ("performance", "quality"):
        need(0 < float(fp[k]) <= 1, f"fin_press.{k} must be in (0, 1]")
    need(float(fp["setup_min"]) >= 0 and float(fp["reload_min"]) >= 0,
         "fin_press setup/reload must be >= 0")
    need(fp["resource"] in r["resources"], "fin_press.resource must be a defined resource")
    for name, res in r["resources"].items():
        need(int(res.get("servers", 1)) >= 1, f"resource {name}: servers must be >= 1")
        need(int(res.get("crew", 1)) >= 1, f"resource {name}: crew must be >= 1")
    for name, o in r["operations"].items():
        need(o.get("resource") in r["resources"], f"operation {name}: unknown resource")
        need(o.get("department") in DEPARTMENTS, f"operation {name}: unknown department")
        need(o.get("source") in SOURCES, f"operation {name}: source must be one of {SOURCES}")
        if "t_op_min" in o:
            need(float(o["t_op_min"]) > 0 and int(o["n_ops"]) >= 1,
                 f"operation {name}: t_op_min > 0 and n_ops >= 1 required")
        else:
            need(float(o.get("mean_min", -1)) > 0, f"operation {name}: mean_min must be > 0")
        need(0 <= float(o.get("cv", 0)) <= 2, f"operation {name}: cv must be in [0, 2]")
    required_ops = {"boxing", "trim_tubes", "weld_hairpins", "steeking", "weld_return_bends",
                    "expansion", "prepare_headers", "header_welding", "wash", "pressure_test",
                    "press_brake", "flat_welding", "plenum_assembly", "drip_tray_weld",
                    "drip_tray_assembly", "complete_assembly"}
    missing = required_ops - set(r["operations"])
    need(not missing, f"operations missing: {sorted(missing)}")
    for key in ("engineering_release", "procurement_sheet_metal", "procurement_tubing",
                "drip_tray_external", "coating"):
        lt = r["lead_times"].get(key)
        need(lt is not None, f"lead_times.{key} missing")
        if lt is not None:
            need(float(lt["mean_days"]) >= 0 and float(lt.get("cv", 0)) >= 0,
                 f"lead_times.{key}: mean_days >= 0 and cv >= 0 required")
    need(0 <= float(r["rework"]["fail_prob"]) < 1, "rework.fail_prob must be in [0, 1)")
    need(r["rework"]["resource"] in r["resources"], "rework.resource must be a defined resource")
    eff = r["crew_efficiency"]
    need(1 in eff and all(0 < v <= 1 for v in eff.values()),
         "crew_efficiency must define crew 1 and values in (0, 1]")
    sim = r["simulation"]
    need(sim["measure_weeks"] >= 1 and sim["warmup_weeks"] >= 0,
         "simulation.measure_weeks >= 1 and warmup_weeks >= 0 required")
    need(sim["replications"] >= 2 and sim["quick_replications"] >= 2,
         "replication counts must be >= 2")
    iu = r.get("input_uncertainty", {})
    if iu:
        lo, mode, hi = iu["steeking_triangular_min"]
        need(0 < lo <= mode <= hi, "input_uncertainty.steeking_triangular_min must be ordered")
    if errs:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errs))


def load_config(path: str | Path = DEFAULT_LINE_FILE) -> LineConfig:
    """Load and validate the line configuration."""
    return LineConfig(load_yaml(path))


# ------------------------------------------------------------------- overrides
def _is_operator(v: Any) -> bool:
    return isinstance(v, dict) and bool(v) and set(v) <= {"scale", "add"}


def _apply_value(current: Any, new: Any) -> Any:
    if _is_operator(new):
        if current is None:
            return None
        val = current
        if "scale" in new:
            val = val * new["scale"]
        if "add" in new:
            val = val + new["add"]
        return val
    return copy.deepcopy(new)


def _merge(base: dict[str, Any], upd: dict[str, Any]) -> None:
    for k, v in upd.items():
        if isinstance(v, dict) and not _is_operator(v) and isinstance(base.get(k), dict):
            _merge(base[k], v)
        else:
            base[k] = _apply_value(base.get(k), v)


def apply_overrides(cfg: LineConfig | dict[str, Any], overrides: dict[str, Any] | None
                    ) -> LineConfig:
    """Return a new validated config with nested ``overrides`` merged in.

    Values may be literals or operators ``{scale: x}`` / ``{add: x}``. Integer
    fields (servers, crew, batch sizes) are rounded after the operator is applied.
    """
    d = cfg.to_dict() if isinstance(cfg, LineConfig) else copy.deepcopy(cfg)
    _merge(d, copy.deepcopy(overrides or {}))
    for res in d["resources"].values():
        for k in ("servers", "crew"):
            if k in res:
                res[k] = int(round(res[k]))
    for k in ("lot_size", "transfer_batch"):
        d["orders"][k] = int(round(d["orders"][k]))
    if "conwip_limit_orders" in d["release"]:
        d["release"]["conwip_limit_orders"] = int(round(d["release"]["conwip_limit_orders"]))
    return LineConfig(d)


def with_demand(cfg: LineConfig, eva_per_week: float) -> LineConfig:
    """Copy of ``cfg`` at a different demand level."""
    return apply_overrides(cfg, {"demand": {"eva_per_week": float(eva_per_week)}})


@dataclass(frozen=True)
class Scenario:
    """A named scenario with its resolved configuration."""

    sid: str
    name: str
    description: str
    config: LineConfig


def load_scenarios(base: LineConfig | None = None,
                   path: str | Path = DEFAULT_SCENARIO_FILE) -> dict[str, Scenario]:
    """Load all scenarios (resolving ``extends`` chains) in file order."""
    base = base or load_config()
    spec = load_yaml(path).get("scenarios", {})

    def chain(sid: str, seen: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        if sid in seen:
            raise ConfigError(f"circular 'extends' at scenario {sid}")
        if sid not in spec:
            raise ConfigError(f"unknown scenario '{sid}'")
        out: list[dict[str, Any]] = []
        for parent in spec[sid].get("extends", []) or []:
            out += chain(parent, (*seen, sid))
        out.append(spec[sid].get("overrides", {}) or {})
        return out

    result = {}
    for sid, s in spec.items():
        cfg = base
        for ov in chain(sid):
            cfg = apply_overrides(cfg, ov)
        result[sid] = Scenario(sid, str(s.get("name", sid)), str(s.get("description", "")), cfg)
    return result


def isclose(a: float, b: float, rel: float = 1e-9) -> bool:
    """Relative float comparison helper."""
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-12)
