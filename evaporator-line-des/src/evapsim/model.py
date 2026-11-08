"""Core SimPy model of the evaporator coil assembly flow line.

Model logic (one replication)
-----------------------------
* **Entities**: units (one coil each) belonging to batches of ``batch_size``
  units of a single product model.
* **Resources**: each station has ``servers`` identical machines, each modelled
  as its own SimPy process so its state (busy / starved / blocked / down /
  changeover) can be timed exactly.
* **Queues**: finite inter-station buffers implemented as a priority store plus
  a slot counter. Forward units need a slot (so a full buffer blocks the
  upstream machine: blocking-after-service); reworked units re-enter the
  rework station's input with priority 0 and without a slot, which keeps the
  rework loop deadlock-free (ASSUMPTIONS A17).
* **Release**: Station 1 pulls a new unit from the (infinite) raw-material
  supply whenever it is free and, under CONWIP, a card is available (A8).
* **Events**: unit release, start of processing, failure, repair complete,
  changeover start/end, end of processing, scrap, rework, buffer entry/exit,
  line exit.

Randomness and common random numbers
------------------------------------
Every random quantity comes from a stream keyed by
``SeedSequence(base_seed, spawn_key=(rep, kind, ...))``. Unit-level draws
(model of the batch, standard normals for each station's cycle time, uniforms
for scrap/test/rework decisions) are taken *when the unit is created*, in
release order, so unit *k* of replication *r* is identical in every scenario.
Failure and changeover draws come from per-machine streams and are scaled from
standard variates, so changing MTBF/MTTR/changeover means keeps them aligned.

Time unit inside the model is the **second**; simulated time is productive
time only (ASSUMPTIONS A3).
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import simpy

from .config import LineConfig
from .distributions import lognormal_from_z, lognormal_params

BUSY, STARVED, BLOCKED, DOWN, CHANGEOVER = range(5)
STATE_NAMES = ("busy", "starved", "blocked", "down", "changeover")


def _rng(base_seed: int, *key: int) -> np.random.Generator:
    """Independent generator for stream ``key`` (CRN-friendly, order-free)."""
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(base_seed, spawn_key=key)))


class _Window:
    """Measurement window [start, end) in seconds and per-day bookkeeping."""

    __slots__ = ("start", "end", "day_s", "n_days")

    def __init__(self, start: float, end: float, day_s: float, n_days: int) -> None:
        self.start, self.end, self.day_s, self.n_days = start, end, day_s, n_days

    def overlap(self, a: float, b: float) -> float:
        """Length of [a, b) inside the window."""
        lo = a if a > self.start else self.start
        hi = b if b < self.end else self.end
        return hi - lo if hi > lo else 0.0


class _TimeAverage:
    """Time-weighted average of an integer level, clipped to the window."""

    __slots__ = ("win", "level", "last", "area")

    def __init__(self, win: _Window) -> None:
        self.win, self.level, self.last, self.area = win, 0, 0.0, 0.0

    def change(self, now: float, delta: int) -> None:
        self.area += self.level * self.win.overlap(self.last, now)
        self.level += delta
        self.last = now

    def mean(self, now: float) -> float:
        self.change(now, 0)
        length = self.win.end - self.win.start
        return self.area / length if length > 0 else float("nan")


@dataclass(slots=True)
class Unit:
    """One coil travelling through the line."""

    uid: int
    batch: int
    model: int
    release_t: float
    z: np.ndarray            # standard normals: one per station + one for rework
    u: np.ndarray            # uniforms: scrap per station + rework decision + re-test
    va_s: float = 0.0        # accumulated processing (value-added) time
    holds_slot: bool = False
    in_rework: bool = False
    reworks: int = 0
    tests: int = 0
    failed_test: bool = False
    start_t: list[float] = field(default_factory=list)
    end_t: list[float] = field(default_factory=list)


class _Server:
    """State bookkeeping for one machine/workstation."""

    __slots__ = ("state", "since", "acc", "win", "ttf", "last_model", "rng_fail", "rng_co",
                 "failures", "changeovers")

    def __init__(self, win: _Window, total_days: int, rng_fail: np.random.Generator,
                 rng_co: np.random.Generator) -> None:
        self.state = STARVED
        self.since = 0.0
        self.acc = np.zeros((total_days, 5))
        self.win = win
        self.ttf: float | None = None
        self.last_model: int | None = None
        self.rng_fail = rng_fail
        self.rng_co = rng_co
        self.failures = 0
        self.changeovers = 0

    def set(self, now: float, state: int) -> None:
        """Close the current state interval at ``now`` and enter ``state``."""
        a, day_s, acc = self.since, self.win.day_s, self.acc
        old = self.state
        last_day = acc.shape[0] - 1
        while a < now:
            d = int(a // day_s)
            if d > last_day:
                break
            b = min(now, (d + 1) * day_s)
            acc[d, old] += b - a
            a = b
        self.state = state
        self.since = now


class _Buffer:
    """Finite FIFO buffer with a priority lane for rework (no slot needed)."""

    def __init__(self, env: simpy.Environment, capacity: int, win: _Window) -> None:
        self.env = env
        self.store = simpy.PriorityStore(env)
        self.slots = simpy.Container(env, capacity=capacity, init=capacity)
        self.level = _TimeAverage(win)
        self._seq = itertools.count()

    def put(self, unit: Unit):  # generator
        """Wait for a free slot, then enqueue (the caller is *blocked* meanwhile)."""
        yield self.slots.get(1)
        unit.holds_slot = True
        self.store.put(simpy.PriorityItem((1, next(self._seq)), unit))
        self.level.change(self.env.now, +1)

    def put_rework(self, unit: Unit) -> None:
        """Enqueue a reworked unit at the front lane without taking a slot."""
        unit.holds_slot = False
        self.store.put(simpy.PriorityItem((0, next(self._seq)), unit))
        self.level.change(self.env.now, +1)

    def get(self):  # generator
        """Take the next unit (rework first), releasing its slot."""
        item = yield self.store.get()
        unit: Unit = item.item
        if unit.holds_slot:
            unit.holds_slot = False
            self.slots.put(1)
        self.level.change(self.env.now, -1)
        return unit


@dataclass
class ReplicationResult:
    """Raw outputs of one replication (measurement window only unless noted)."""

    rep: int
    measure_s: float
    day_s: float
    station_ids: list[int]
    servers: np.ndarray                 # (n_stations,)
    state_time_s: np.ndarray            # (n_stations, 5) summed over servers, window only
    daily_state_time_s: np.ndarray      # (days, n_stations, 5) window days only
    daily_output: np.ndarray            # (days,) good units completed per measured day
    lead_times_min: np.ndarray          # per good unit exiting in window
    va_time_s: np.ndarray               # per good unit exiting in window
    unit_models: np.ndarray             # product index per good unit exiting in window
    sojourn_all_min: np.ndarray         # per departure (good or scrap) in window
    wip_avg: float
    buffer_avg: np.ndarray              # (n_stations-1,) time-avg units in each buffer
    released: int
    good: int
    scrapped: int
    first_pass_good: int
    scrap_by_station: np.ndarray        # (n_stations,) scrapped there (window)
    processed_by_station: np.ndarray    # (n_stations,) first-pass completions there (window)
    test_failures: int
    reworked: int
    failures_by_station: np.ndarray     # whole run
    changeovers_by_station: np.ndarray  # whole run
    batch_records: list[dict[str, Any]]
    units: list[dict[str, Any]] | None = None

    @property
    def daily_busy_share(self) -> np.ndarray:
        """(days, n_stations) busy share per day, averaged over parallel servers."""
        return self.daily_state_time_s[:, :, BUSY] / (self.servers[None, :] * self.day_s)


class LineModel:
    """Builds and runs one replication of the line."""

    def __init__(self, cfg: LineConfig, rep: int = 0, base_seed: int | None = None,
                 keep_units: bool = False) -> None:
        self.cfg = cfg
        self.rep = rep
        self.seed = cfg.sim.base_seed if base_seed is None else int(base_seed)
        self.keep_units = keep_units
        self.env = simpy.Environment()
        self.n = cfg.n_stations
        day_s = cfg.day_seconds
        self.total_days = cfg.sim.warmup_days + cfg.sim.days
        self.win = _Window(cfg.sim.warmup_days * day_s, self.total_days * day_s, day_s,
                           cfg.sim.days)
        self.cv_scale = 0.0 if cfg.sim.deterministic else 1.0

        self.rng_units = _rng(self.seed, rep, 0)
        self.mix = np.array([p.mix for p in cfg.products])
        self.mult = [p.ct_multiplier for p in cfg.products]
        self.batch_id = -1
        self.batch_left = 0
        self.batch_model = 0
        self.uid = itertools.count()
        self.batches: dict[int, dict[str, Any]] = {}

        self.buffers = [_Buffer(self.env, c, self.win) for c in cfg.buffer_capacities]
        self.conwip = (
            simpy.Container(self.env, capacity=cfg.release.conwip_limit,
                            init=cfg.release.conwip_limit)
            if cfg.release.rule == "conwip" else None
        )
        self.wip = _TimeAverage(self.win)
        self.test_idx = cfg.rework.test_station - 1
        self.rework_idx = cfg.rework.rework_station - 1
        self.rework_on = cfg.rework.rework_share > 0

        # Pre-computed lognormal parameters per station (Medium model).
        self.servers: list[list[_Server]] = []
        for si, st in enumerate(cfg.stations):
            row = []
            for k in range(st.servers):
                srv = _Server(self.win, self.total_days, _rng(self.seed, rep, 1, si, k),
                              _rng(self.seed, rep, 2, si, k))
                if cfg.sim.breakdowns and st.has_breakdowns:
                    srv.ttf = float(srv.rng_fail.standard_exponential()) * st.mtbf_min * 60.0
                row.append(srv)
            self.servers.append(row)

        # Counters (window only unless noted).
        days = cfg.sim.days
        self.daily_output = np.zeros(days, dtype=int)
        self.lead_times: list[float] = []
        self.va_times: list[float] = []
        self.unit_models: list[int] = []
        self.sojourn_all: list[float] = []
        self.released = self.good = self.scrapped = self.first_pass_good = 0
        self.test_failures = self.reworked = 0
        self.scrap_by_station = np.zeros(self.n, dtype=int)
        self.processed_by_station = np.zeros(self.n, dtype=int)
        self.unit_log: list[dict[str, Any]] = []

        for si, st in enumerate(cfg.stations):
            for k in range(st.servers):
                self.env.process(self._server(si, k))

    # ----------------------------------------------------------------- helpers
    def _in_window(self, t: float) -> bool:
        return self.win.start <= t < self.win.end

    def _new_unit(self) -> Unit:
        """Create the next unit from the order sequence (draws unit-level randomness)."""
        rng = self.rng_units
        if self.batch_left == 0:
            self.batch_id += 1
            self.batch_model = int(rng.choice(len(self.mix), p=self.mix))
            self.batch_left = self.cfg.batch_size
            self.batches[self.batch_id] = {
                "batch_id": self.batch_id, "model": self.batch_model, "released": 0,
                "departed": 0, "good": 0, "first_release": self.env.now, "last_departure": None,
            }
        self.batch_left -= 1
        unit = Unit(
            uid=next(self.uid), batch=self.batch_id, model=self.batch_model,
            release_t=self.env.now, z=rng.standard_normal(self.n + 1),
            u=rng.random(self.n + 2),
            start_t=[math.nan] * self.n, end_t=[math.nan] * self.n,
        )
        self.batches[self.batch_id]["released"] += 1
        self.wip.change(self.env.now, +1)
        if self._in_window(self.env.now):
            self.released += 1
        return unit

    def _depart(self, unit: Unit, good: bool, station_idx: int) -> None:
        """Remove a unit from the line (exit or scrap) and update all statistics."""
        now = self.env.now
        self.wip.change(now, -1)
        if self.conwip is not None:
            self.conwip.put(1)
        b = self.batches[unit.batch]
        b["departed"] += 1
        b["last_departure"] = now
        if good:
            b["good"] += 1
        if self._in_window(now):
            self.sojourn_all.append((now - unit.release_t) / 60.0)
            if good:
                self.good += 1
                d = int((now - self.win.start) // self.win.day_s)
                self.daily_output[d] += 1
                self.lead_times.append((now - unit.release_t) / 60.0)
                self.va_times.append(unit.va_s)
                self.unit_models.append(unit.model)
                if not unit.failed_test:
                    self.first_pass_good += 1
            else:
                self.scrapped += 1
                self.scrap_by_station[station_idx] += 1
        if self.keep_units:
            self.unit_log.append({
                "uid": unit.uid, "batch": unit.batch, "model": unit.model,
                "release_s": unit.release_t, "depart_s": now,
                "status": "good" if good else f"scrap@S{station_idx + 1}",
                "reworks": unit.reworks, "va_s": unit.va_s,
                **{f"start_S{i + 1}": unit.start_t[i] for i in range(self.n)},
                **{f"end_S{i + 1}": unit.end_t[i] for i in range(self.n)},
            })

    def _operate(self, srv: _Server, si: int, duration: float):  # generator
        """Process for ``duration`` seconds, suffering operation-dependent failures."""
        env = self.env
        srv.set(env.now, BUSY)
        if srv.ttf is None:
            yield env.timeout(duration)
            return
        st = self.cfg.stations[si]
        remaining = duration
        while remaining > 0:
            if srv.ttf >= remaining:
                yield env.timeout(remaining)
                srv.ttf -= remaining
                remaining = 0.0
            else:
                yield env.timeout(srv.ttf)
                remaining -= srv.ttf
                srv.set(env.now, DOWN)
                srv.failures += 1
                yield env.timeout(float(srv.rng_fail.standard_exponential()) * st.mttr_min * 60.0)
                srv.ttf = float(srv.rng_fail.standard_exponential()) * st.mtbf_min * 60.0
                srv.set(env.now, BUSY)

    # ------------------------------------------------------------------ server
    def _server(self, si: int, k: int):  # generator
        """Life cycle of machine ``k`` at station index ``si``."""
        env, cfg = self.env, self.cfg
        st = cfg.stations[si]
        srv = self.servers[si][k]
        in_buf = self.buffers[si - 1] if si > 0 else None
        out_buf = self.buffers[si] if si < self.n - 1 else None
        ct_cv = st.ct_cv * self.cv_scale
        has_co = st.changeover and st.changeover_min > 0
        co_mu, co_sigma = (
            lognormal_params(st.changeover_min * 60.0, cfg.sim.changeover_cv * self.cv_scale)
            if has_co else (0.0, 0.0)
        )
        rw = cfg.rework
        is_test = self.rework_on and si == self.test_idx
        is_rework_st = self.rework_on and si == self.rework_idx

        while True:
            # 1. Wait for work (starved).
            srv.set(env.now, STARVED)
            if in_buf is None:
                if self.conwip is not None:
                    yield self.conwip.get(1)
                unit = self._new_unit()
            else:
                unit = yield from in_buf.get()
            rework_job = is_rework_st and unit.in_rework

            # 2. Changeover on model switch (new work only, ASSUMPTIONS A13).
            if has_co and not rework_job:
                if srv.last_model is not None and srv.last_model != unit.model:
                    srv.set(env.now, CHANGEOVER)
                    srv.changeovers += 1
                    z = float(srv.rng_co.standard_normal())
                    yield env.timeout(math.exp(co_mu + co_sigma * z))
                srv.last_model = unit.model

            # 3. Process (busy, possibly interrupted by failures).
            if rework_job:
                pt = lognormal_from_z(rw.rework_time_s, rw.rework_cv * self.cv_scale,
                                      float(unit.z[self.n]))
            else:
                pt = lognormal_from_z(st.ct_mean_s, ct_cv, float(unit.z[si])) * self.mult[
                    unit.model]
            if not rework_job:
                unit.start_t[si] = env.now
            unit.va_s += pt
            yield from self._operate(srv, si, pt)
            unit.end_t[si] = env.now
            in_win = self._in_window(env.now)

            # 4. Quality decision.
            if rework_job:
                unit.in_rework = False
            elif is_test:
                u = unit.u[si] if unit.tests == 0 else unit.u[self.n + 1]
                unit.tests += 1
                if unit.tests == 1 and in_win:
                    self.processed_by_station[si] += 1
                if u < st.scrap_rate:
                    unit.failed_test = True
                    if in_win:
                        self.test_failures += 1
                    if unit.reworks < rw.max_reworks_per_unit and unit.u[self.n] < rw.rework_share:
                        unit.reworks += 1
                        unit.in_rework = True
                        if in_win:
                            self.reworked += 1
                        self.buffers[self.rework_idx - 1].put_rework(unit)
                    else:
                        self._depart(unit, good=False, station_idx=si)
                    continue
            else:
                if in_win:
                    self.processed_by_station[si] += 1
                if unit.u[si] < st.scrap_rate:
                    self._depart(unit, good=False, station_idx=si)
                    continue

            # 5. Hand over downstream (blocked while the next buffer is full).
            if out_buf is None:
                self._depart(unit, good=True, station_idx=si)
            else:
                srv.set(env.now, BLOCKED)
                yield from out_buf.put(unit)

    # --------------------------------------------------------------------- run
    def run(self) -> ReplicationResult:
        """Run the replication to the end of the horizon and collect results."""
        env, win = self.env, self.win
        env.run(until=win.end)
        for row in self.servers:
            for srv in row:
                srv.set(win.end, srv.state)
        w0 = self.cfg.sim.warmup_days
        daily_state = np.stack(
            [sum(srv.acc for srv in row)[w0:] for row in self.servers], axis=1
        )  # (days, n, 5)
        batch_records = []
        for b in self.batches.values():
            done = b["released"] == self.cfg.batch_size and b["departed"] == b["released"]
            if not done or b["first_release"] < win.start or b["last_departure"] >= win.end:
                continue
            batch_records.append({
                "batch_id": b["batch_id"], "model": b["model"], "good": b["good"],
                "release_s": b["first_release"], "complete_s": b["last_departure"],
                "lead_time_min": (b["last_departure"] - b["first_release"]) / 60.0,
                "complete_day": int((b["last_departure"] - win.start) // win.day_s),
            })
        return ReplicationResult(
            rep=self.rep,
            measure_s=win.end - win.start,
            day_s=win.day_s,
            station_ids=[s.id for s in self.cfg.stations],
            servers=np.array([s.servers for s in self.cfg.stations]),
            state_time_s=daily_state.sum(axis=0),
            daily_state_time_s=daily_state,
            daily_output=self.daily_output,
            lead_times_min=np.asarray(self.lead_times),
            va_time_s=np.asarray(self.va_times),
            unit_models=np.asarray(self.unit_models, dtype=int),
            sojourn_all_min=np.asarray(self.sojourn_all),
            wip_avg=self.wip.mean(win.end),
            buffer_avg=np.array([b.level.mean(win.end) for b in self.buffers]),
            released=self.released,
            good=self.good,
            scrapped=self.scrapped,
            first_pass_good=self.first_pass_good,
            scrap_by_station=self.scrap_by_station,
            processed_by_station=self.processed_by_station,
            test_failures=self.test_failures,
            reworked=self.reworked,
            failures_by_station=np.array([sum(s.failures for s in row) for row in self.servers]),
            changeovers_by_station=np.array(
                [sum(s.changeovers for s in row) for row in self.servers]),
            batch_records=batch_records,
            units=self.unit_log if self.keep_units else None,
        )


def simulate_replication(cfg: LineConfig, rep: int = 0, base_seed: int | None = None,
                         keep_units: bool = False) -> ReplicationResult:
    """Run replication ``rep`` of ``cfg`` and return its :class:`ReplicationResult`."""
    return LineModel(cfg, rep=rep, base_seed=base_seed, keep_units=keep_units).run()
