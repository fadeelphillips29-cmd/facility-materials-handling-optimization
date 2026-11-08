"""Configuration loading, validation and scenario overrides.

The model is driven entirely by ``config/line_parameters.yaml``. This module
turns that YAML into typed, validated dataclasses (:class:`LineConfig`) and
applies scenario overrides from ``config/scenarios.yaml``.

Overrides are applied to the plain-dict form of the configuration and the
result is re-validated, so a scenario can never produce an inconsistent model.
"""

from __future__ import annotations

import copy
from dataclasses import asdict, dataclass, field
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


class ConfigError(ValueError):
    """Raised when a configuration file is missing fields or has invalid values."""


@dataclass(frozen=True)
class Product:
    """A product model (coil size) in the mix."""

    name: str
    mix: float
    ct_multiplier: float


@dataclass(frozen=True)
class VSMFields:
    """Gemba-walk snapshot shown on a VSM process box (fictional observed values)."""

    operators: int = 1
    value_added_time_s: float = 0.0
    inventory_in_front_units: float = 0.0
    uptime_pct: float = 100.0
    first_pass_yield_pct: float = 100.0


@dataclass(frozen=True)
class Station:
    """A processing station in the flow line.

    Attributes:
        id: 1-based station number (also the routing order).
        name: Descriptive name.
        ct_mean_s: Mean cycle time of the Medium model, seconds.
        ct_cv: Coefficient of variation of the lognormal cycle time.
        servers: Number of identical parallel machines/workstations.
        mtbf_min: Mean operating time between failures, minutes (None = no failures).
        mttr_min: Mean time to repair, minutes (None = no failures).
        scrap_rate: Probability a unit is scrapped at this station (fraction).
        changeover: Whether a model switch triggers a changeover here.
        changeover_min: Mean changeover duration, minutes.
        vsm: Observed VSM box data.
    """

    id: int
    name: str
    ct_mean_s: float
    ct_cv: float
    servers: int = 1
    mtbf_min: float | None = None
    mttr_min: float | None = None
    scrap_rate: float = 0.0
    changeover: bool = False
    changeover_min: float = 0.0
    vsm: VSMFields = field(default_factory=VSMFields)

    @property
    def has_breakdowns(self) -> bool:
        """True when both MTBF and MTTR are defined and positive."""
        return bool(self.mtbf_min) and bool(self.mttr_min)

    @property
    def short(self) -> str:
        """Short label such as ``S4``."""
        return f"S{self.id}"


@dataclass(frozen=True)
class Release:
    """Order release rule at the line entrance."""

    rule: str = "conwip"
    conwip_limit: int = 40


@dataclass(frozen=True)
class Rework:
    """Rework loop from a test station back to an upstream station."""

    test_station: int = 5
    rework_station: int = 4
    rework_share: float = 0.4
    rework_time_s: float = 90.0
    rework_cv: float = 0.2
    max_reworks_per_unit: int = 1


@dataclass(frozen=True)
class SimSettings:
    """Run-length, replication and randomness settings."""

    days: int = 20
    warmup_days: int = 1
    replications: int = 500
    quick_replications: int = 50
    sensitivity_replications: int = 100
    base_seed: int = 20260415
    changeover_cv: float = 0.1
    deterministic: bool = False
    breakdowns: bool = True


@dataclass(frozen=True)
class VSMGlobal:
    """VSM data outside the simulated scope (stock levels, supplier, customer)."""

    raw_material_stock_days: float = 3.0
    finished_goods_stock_days: float = 2.0
    supplier: str = "Supplier"
    customer: str = "Customer"
    shipments_per_week: int = 5


@dataclass(frozen=True)
class LineConfig:
    """Complete, validated model input."""

    line_name: str
    shift_minutes: float
    shifts_per_day: int
    demand_per_day: float
    batch_size: int
    products: tuple[Product, ...]
    stations: tuple[Station, ...]
    buffer_capacities: tuple[int, ...]
    release: Release
    rework: Rework
    sim: SimSettings
    vsm: VSMGlobal
    raw: dict[str, Any] = field(repr=False, compare=False, default_factory=dict)

    # ------------------------------------------------------------------ derived
    @property
    def day_seconds(self) -> float:
        """Productive seconds per day (all shifts)."""
        return self.shift_minutes * 60.0 * self.shifts_per_day

    @property
    def takt_s(self) -> float:
        """Takt time in seconds = available time / customer demand."""
        return self.day_seconds / self.demand_per_day

    @property
    def mix_ct_multiplier(self) -> float:
        """Demand-weighted average cycle-time multiplier of the product mix."""
        return sum(p.mix * p.ct_multiplier for p in self.products)

    @property
    def n_stations(self) -> int:
        """Number of stations."""
        return len(self.stations)

    def station(self, station_id: int) -> Station:
        """Return the station with the given 1-based id."""
        for st in self.stations:
            if st.id == station_id:
                return st
        raise KeyError(f"No station with id {station_id}")

    def to_dict(self) -> dict[str, Any]:
        """Return the YAML-shaped dictionary this config was built from."""
        return copy.deepcopy(self.raw)


# --------------------------------------------------------------------------- IO
def load_yaml(path: str | Path) -> dict[str, Any]:
    """Read a YAML file into a dictionary."""
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ConfigError(f"{path} does not contain a YAML mapping")
    return data


def load_config(path: str | Path = DEFAULT_LINE_FILE) -> LineConfig:
    """Load and validate ``line_parameters.yaml``."""
    return config_from_dict(load_yaml(path))


def _req(d: dict[str, Any], key: str, ctx: str) -> Any:
    if key not in d:
        raise ConfigError(f"Missing field '{key}' in {ctx}")
    return d[key]


def config_from_dict(d: dict[str, Any]) -> LineConfig:
    """Build a :class:`LineConfig` from a YAML-shaped dictionary and validate it."""
    d = copy.deepcopy(d)
    products = tuple(
        Product(name=str(p["name"]), mix=float(p["mix"]), ct_multiplier=float(p["ct_multiplier"]))
        for p in _req(d, "products", "root")
    )
    stations = []
    for s in _req(d, "stations", "root"):
        vsm_raw = s.get("vsm", {}) or {}
        stations.append(
            Station(
                id=int(_req(s, "id", "station")),
                name=str(_req(s, "name", "station")),
                ct_mean_s=float(_req(s, "ct_mean_s", "station")),
                ct_cv=float(_req(s, "ct_cv", "station")),
                servers=int(s.get("servers", 1)),
                mtbf_min=None if s.get("mtbf_min") is None else float(s["mtbf_min"]),
                mttr_min=None if s.get("mttr_min") is None else float(s["mttr_min"]),
                scrap_rate=float(s.get("scrap_rate", 0.0)),
                changeover=bool(s.get("changeover", False)),
                changeover_min=float(s.get("changeover_min", 0.0) or 0.0),
                vsm=VSMFields(**vsm_raw),
            )
        )
    stations.sort(key=lambda st: st.id)
    rel = d.get("release", {}) or {}
    rw = d.get("rework", {}) or {}
    sim = d.get("simulation", {}) or {}
    vsm = d.get("vsm", {}) or {}
    cfg = LineConfig(
        line_name=str(d.get("meta", {}).get("line_name", "Flow line")),
        shift_minutes=float(_req(d["shift"], "net_productive_minutes", "shift")),
        shifts_per_day=int(d["shift"].get("shifts_per_day", 1)),
        demand_per_day=float(_req(d["demand"], "units_per_day", "demand")),
        batch_size=int(_req(d["orders"], "batch_size", "orders")),
        products=products,
        stations=tuple(stations),
        buffer_capacities=tuple(int(c) for c in _req(d["buffers"], "capacities", "buffers")),
        release=Release(**rel),
        rework=Rework(**rw),
        sim=SimSettings(**sim),
        vsm=VSMGlobal(**vsm),
        raw=d,
    )
    validate(cfg)
    return cfg


def validate(cfg: LineConfig) -> None:
    """Check ranges and internal consistency; raise :class:`ConfigError` on failure."""
    errs: list[str] = []
    if cfg.shift_minutes <= 0:
        errs.append("shift.net_productive_minutes must be > 0")
    if cfg.shifts_per_day < 1:
        errs.append("shift.shifts_per_day must be >= 1")
    if cfg.demand_per_day <= 0:
        errs.append("demand.units_per_day must be > 0")
    if cfg.batch_size < 1:
        errs.append("orders.batch_size must be >= 1")
    if not cfg.products:
        errs.append("at least one product is required")
    mix = sum(p.mix for p in cfg.products)
    if abs(mix - 1.0) > 1e-6:
        errs.append(f"product mix must sum to 1.0 (got {mix:.4f})")
    for p in cfg.products:
        if p.mix < 0 or p.ct_multiplier <= 0:
            errs.append(f"product {p.name}: mix >= 0 and ct_multiplier > 0 required")
    ids = [s.id for s in cfg.stations]
    if ids != list(range(1, len(ids) + 1)):
        errs.append(f"station ids must be 1..N without gaps (got {ids})")
    for s in cfg.stations:
        if s.ct_mean_s <= 0:
            errs.append(f"{s.short}: ct_mean_s must be > 0")
        if not 0 <= s.ct_cv <= 2:
            errs.append(f"{s.short}: ct_cv must be in [0, 2]")
        if s.servers < 1:
            errs.append(f"{s.short}: servers must be >= 1")
        if (s.mtbf_min is None) != (s.mttr_min is None):
            errs.append(f"{s.short}: give both mtbf_min and mttr_min or neither")
        if s.mtbf_min is not None and (s.mtbf_min <= 0 or (s.mttr_min or 0) <= 0):
            errs.append(f"{s.short}: mtbf_min and mttr_min must be > 0")
        if not 0 <= s.scrap_rate < 1:
            errs.append(f"{s.short}: scrap_rate must be in [0, 1)")
        if s.changeover_min < 0:
            errs.append(f"{s.short}: changeover_min must be >= 0")
    if len(cfg.buffer_capacities) != max(len(cfg.stations) - 1, 0):
        errs.append(
            f"buffers.capacities needs {len(cfg.stations) - 1} entries "
            f"(got {len(cfg.buffer_capacities)})"
        )
    if any(c < 1 for c in cfg.buffer_capacities):
        errs.append("buffer capacities must be >= 1")
    if cfg.release.rule not in {"conwip", "unlimited"}:
        errs.append("release.rule must be 'conwip' or 'unlimited'")
    if cfg.release.rule == "conwip" and cfg.release.conwip_limit < 1:
        errs.append("release.conwip_limit must be >= 1")
    rw = cfg.rework
    if rw.rework_share > 0:
        if rw.test_station not in ids or rw.rework_station not in ids:
            errs.append("rework stations must be valid station ids")
        elif rw.rework_station >= rw.test_station:
            errs.append("rework_station must be upstream of test_station")
    if not 0 <= rw.rework_share <= 1:
        errs.append("rework.rework_share must be in [0, 1]")
    if cfg.sim.days < 1 or cfg.sim.warmup_days < 0:
        errs.append("simulation.days >= 1 and warmup_days >= 0 required")
    if cfg.sim.replications < 2 or cfg.sim.quick_replications < 2:
        errs.append("replication counts must be >= 2 (needed for confidence intervals)")
    if errs:
        raise ConfigError("Invalid configuration:\n  - " + "\n  - ".join(errs))


# -------------------------------------------------------------------- overrides
def _station_selector(key: Any, n: int) -> list[int]:
    """Expand a station selector (id, 'a-b', 'all', list) into station ids."""
    if isinstance(key, int):
        return [key]
    if isinstance(key, (list, tuple)):
        out: list[int] = []
        for k in key:
            out += _station_selector(k, n)
        return out
    k = str(key).strip().lower()
    if k == "all":
        return list(range(1, n + 1))
    if "-" in k:
        a, b = (int(x) for x in k.split("-", 1))
        return list(range(a, b + 1))
    return [int(k)]


def _apply_value(current: Any, new: Any) -> Any:
    """Apply a literal or an operator ({scale: x} / {add: x}) to ``current``."""
    if isinstance(new, dict) and set(new) <= {"scale", "add"} and new:
        if current is None:
            return None  # scaling a disabled feature keeps it disabled
        val = current
        if "scale" in new:
            val = val * new["scale"]
        if "add" in new:
            val = val + new["add"]
        return val
    return new


def _merge(base: dict[str, Any], upd: dict[str, Any]) -> None:
    for k, v in upd.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict) and not (
            set(v) <= {"scale", "add"} and v
        ):
            _merge(base[k], v)
        else:
            base[k] = _apply_value(base.get(k), v)


def apply_overrides(cfg: LineConfig | dict[str, Any], overrides: dict[str, Any]) -> LineConfig:
    """Return a new validated config with ``overrides`` applied.

    Args:
        cfg: Base configuration (dataclass or YAML-shaped dict).
        overrides: Mapping in the format documented in ``config/scenarios.yaml``.
    """
    d = cfg.to_dict() if isinstance(cfg, LineConfig) else copy.deepcopy(cfg)
    ov = copy.deepcopy(overrides or {})
    n = len(d["stations"])
    st_ov = ov.pop("stations", None) or {}
    for sel, fields in st_ov.items():
        for sid in _station_selector(sel, n):
            target = next((s for s in d["stations"] if int(s["id"]) == sid), None)
            if target is None:
                raise ConfigError(f"Override refers to unknown station {sid}")
            _merge(target, fields)
    buf_ov = ov.pop("buffers", None) or {}
    if "all" in buf_ov:
        caps = d["buffers"]["capacities"]
        d["buffers"]["capacities"] = [
            int(round(_apply_value(c, buf_ov["all"]))) for c in caps
        ]
    if "capacities" in buf_ov:
        d["buffers"]["capacities"] = [int(c) for c in buf_ov["capacities"]]
    _merge(d, ov)
    return config_from_dict(d)


@dataclass(frozen=True)
class Scenario:
    """A named scenario: id, label, description and the resolved config."""

    sid: str
    name: str
    description: str
    config: LineConfig


def load_scenarios(
    base: LineConfig | None = None,
    path: str | Path = DEFAULT_SCENARIO_FILE,
) -> dict[str, Scenario]:
    """Load all scenarios, resolving ``extends`` chains, in file order."""
    base = base or load_config()
    spec = load_yaml(path).get("scenarios", {})
    resolved: dict[str, Scenario] = {}

    def overrides_chain(sid: str, seen: tuple[str, ...] = ()) -> list[dict[str, Any]]:
        if sid in seen:
            raise ConfigError(f"Circular 'extends' in scenario {sid}")
        if sid not in spec:
            raise ConfigError(f"Unknown scenario '{sid}'")
        chain: list[dict[str, Any]] = []
        for parent in spec[sid].get("extends", []) or []:
            chain += overrides_chain(parent, (*seen, sid))
        chain.append(spec[sid].get("overrides", {}) or {})
        return chain

    for sid, s in spec.items():
        cfg = base
        for ov in overrides_chain(sid):
            cfg = apply_overrides(cfg, ov)
        resolved[sid] = Scenario(
            sid=sid,
            name=str(s.get("name", sid)),
            description=str(s.get("description", "")),
            config=cfg,
        )
    return resolved


def station_table(cfg: LineConfig) -> list[dict[str, Any]]:
    """Flat per-station parameter records (for tables and the dashboard)."""
    rows = []
    for s in cfg.stations:
        r = asdict(s)
        r.pop("vsm")
        rows.append(r)
    return rows
