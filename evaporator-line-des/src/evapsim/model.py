"""SimPy network model of the Company's evaporator production system (illustrative data).

Structure (per work order of B EVA, see docs/MODEL_DESCRIPTION.md)
------------------------------------------------------------------
arrival → engineering drawing release (delay) → procure sheet metal and tubing
(delays started at release) → parallel branches:

* fin press job (setup + punch B EVA, shared operator), started at release
* sheet metal → press brake → flat welding → plenum assembly (shared assembler)
* sheet metal → external drip-tray bend & punch (lot delay) → weld → assembly
  (shared assembler)
* tubing arrives → [CONWIP card, if used: shop-floor release of the coil line] →
  boxing (fin-press operator, after the EVA's fins), trim tubes → weld hairpins
  (circuits), prepare headers

coil route per EVA: JOIN(fin pack, boxed module, circuits) → steeking (crew) →
return bends → expansion → JOIN(headers) → header welding → wash ↔ pressure
test (failure → rework at the header welder → retest) → outsourced coating
(delay per transfer batch) → JOIN(plenum, drip tray) → complete assembly (crew).

EVA move between stages in transfer batches (Gate). Each EVA requests a
station separately, so different orders interleave FIFO at shared resources.

Common random numbers: every order pre-draws all of its normals and uniforms in
arrival order from stream (rep, 0). The fin press has its own stream (rep, 1).
The input-uncertainty sample uses stream (rep, 9).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
import simpy

from . import equations as eq
from .config import LineConfig, apply_overrides
from .distributions import lognormal_from_z, variate_from_z
from .resources import BUSY, CHANGEOVER, DOWN, Gate, TimeAverage, TimedResource, Window

OPS = ["boxing", "trim_tubes", "weld_hairpins", "steeking", "weld_return_bends", "expansion",
       "prepare_headers", "header_welding", "wash", "pressure_test", "press_brake",
       "flat_welding", "plenum_assembly", "drip_tray_weld", "drip_tray_assembly",
       "complete_assembly"]
DELAYS = ["engineering_release", "procurement_sheet_metal", "procurement_tubing",
          "drip_tray_external"]
STAGES = ["engineering", "awaiting_material", "prep", "coil_line", "coating", "final_assembly"]
MAX_TESTS = 10


def rng_for(seed: int, *key: int) -> np.random.Generator:
    """Independent PCG64 stream for ``key`` (equivalent to SeedSequence.spawn keys)."""
    return np.random.Generator(np.random.PCG64(np.random.SeedSequence(seed, spawn_key=key)))


def sample_input_uncertainty(cfg: LineConfig, rep: int, seed: int) -> float:
    """Outer-loop sample of the steeking mean (min/EVA) for replication ``rep``."""
    lo, mode, hi = cfg.raw["input_uncertainty"]["steeking_triangular_min"]
    return float(rng_for(seed, rep, 9).triangular(lo, mode, hi))


@dataclass
class Order:
    """A work order of B EVA with its pre-drawn random numbers."""

    oid: int
    arrival: float
    z_ops: np.ndarray        # (B, len(OPS)) normals for operation times
    z_delay: np.ndarray      # (len(DELAYS),) normals for calendar delays
    z_coat: np.ndarray       # (B,) normals for coating, one per transfer batch
    u_test: np.ndarray       # (B, MAX_TESTS) uniforms for test outcomes
    z_rework: np.ndarray     # (B, MAX_TESTS) normals for rework times
    release: float = math.nan
    tube_arrival: float = math.nan
    card: float = math.nan
    completion: float = math.nan
    done: int = 0
    tested: int = 0
    fin_job_min: float = math.nan
    evas: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class SimResult:
    """Outputs of one replication."""

    rep: int
    theta_steeking: float
    win: Window
    orders: pd.DataFrame
    evas: pd.DataFrame
    weekly_output: np.ndarray
    resources: pd.DataFrame
    activities: pd.DataFrame
    waits: pd.DataFrame
    wip_by_stage: dict[str, float]
    wip_total: float
    wip_peak: int
    tests: int
    first_tests: int
    first_test_failures: int
    reworks: int
    arrived: int
    completed_evas_total: int
    in_system_end: int
    fin_jobs: pd.DataFrame


class EvaporatorModel:
    """Builds and runs one replication.

    Args:
        cfg: Validated configuration.
        rep: Replication index (selects the random streams).
        base_seed: Root seed (defaults to ``simulation.base_seed``).
        theta_steeking: Optional steeking mean (min/EVA at basis crew) for the
            outer loop. If None, it is sampled when input uncertainty is enabled.
    """

    def __init__(self, cfg: LineConfig, rep: int = 0, base_seed: int | None = None,
                 theta_steeking: float | None = None) -> None:
        seed = int(cfg.raw["simulation"]["base_seed"] if base_seed is None else base_seed)
        self.seed, self.rep = seed, rep
        if theta_steeking is None and cfg.raw.get("input_uncertainty", {}).get("enabled"):
            theta_steeking = sample_input_uncertainty(cfg, rep, seed)
        if theta_steeking is not None:
            cfg = apply_overrides(cfg, {"operations": {"steeking": {"mean_min": theta_steeking}}})
        self.theta = float(cfg.raw["operations"]["steeking"]["mean_min"])
        self.cfg = cfg
        self.det = cfg.deterministic
        self.env = simpy.Environment()
        sim = cfg.raw["simulation"]
        wk = cfg.week_min
        self.win = Window(sim["warmup_weeks"] * wk, (sim["warmup_weeks"] + sim["measure_weeks"])
                          * wk, wk)
        self.B, self.tb = cfg.lot, cfg.transfer_batch
        self.R = {r: TimedResource(self.env, r, int(d.get("servers", 1)), self.win)
                  for r, d in cfg.resources.items()}
        self.rng_orders = rng_for(seed, rep, 0)
        self.rng_fp = rng_for(seed, rep, 1)
        self.fp = cfg.fin_press
        self.fp_eq = eq.fin_press(**self.fp)
        self.fp_ttf = (math.inf if self.det else
                       float(self.rng_fp.standard_exponential()) * self.fp["MTBF"])
        self.reel_left = self.fp["R"]
        self.op_mean = {op: cfg.op_mean_min(op) for op in OPS}
        self.op_cv = {op: cfg.op_cv(op) for op in OPS}
        self.op_fam = {op: cfg.op_family(op) for op in OPS}
        self.op_res = {op: cfg.operations[op]["resource"] for op in OPS}
        self.rw = cfg.rework
        self.flags = cfg.raw["flags"]
        rel = cfg.raw["release"]
        self.conwip = (simpy.Container(self.env, capacity=rel["conwip_limit_orders"],
                                       init=rel["conwip_limit_orders"])
                       if rel["rule"] == "conwip" else None)
        self.stage_avg = {s: TimeAverage(self.win) for s in STAGES}
        self.total = TimeAverage(self.win)
        self.orders: list[Order] = []
        self.fin_jobs: list[dict[str, float]] = []
        self.weekly = np.zeros(int(sim["measure_weeks"]), dtype=int)
        self.tests = self.first_tests = self.first_fail = self.reworks = 0
        self.completed_total = 0
        self.env.process(self._arrivals())

    # ------------------------------------------------------------ randomness
    def _new_order(self, oid: int) -> Order:
        r, B = self.rng_orders, self.B
        return Order(oid=oid, arrival=self.env.now,
                     z_ops=r.standard_normal((B, len(OPS))), z_delay=r.standard_normal(len(DELAYS)),
                     z_coat=r.standard_normal(B), u_test=r.random((B, MAX_TESTS)),
                     z_rework=r.standard_normal((B, MAX_TESTS)))

    def _op_time(self, o: Order, i: int, op: str) -> float:
        j = OPS.index(op)
        return variate_from_z(self.op_fam[op], self.op_mean[op], self.op_cv[op],
                              float(o.z_ops[i, j]))

    def _delay(self, o: Order, key: str, z: float | None = None) -> float:
        cfg = self.cfg
        zz = float(o.z_delay[DELAYS.index(key)]) if z is None else z
        return lognormal_from_z(cfg.lead_time_mean_min(key), cfg.lead_time_cv(key), zz)

    # -------------------------------------------------------------- tracking
    def _stage(self, eva: dict[str, Any], new: str | None) -> None:
        now = self.env.now
        old = eva.get("stage")
        if old is not None:
            self.stage_avg[old].change(now, -1)
        if new is not None:
            self.stage_avg[new].change(now, +1)
        eva["stage"] = new
        eva[f"stage_{new or 'done'}_t"] = now

    def _work(self, o: Order, i: int, op: str, priority: int = 1, duration: float | None = None,
              activity: str | None = None, record: bool = True):  # generator
        """Request the operation's resource, wait, then process EVA i (busy state)."""
        res = self.R[self.op_res[op] if activity != "rework" else self.rw["resource"]]
        eva = o.evas[i]
        act = activity or op
        t_req = self.env.now
        with res.request(priority) as req:
            yield req
            res.note_wait(act, t_req)
            d = self._op_time(o, i, op) if duration is None else duration
            if record:
                eva[f"{act}_ready"] = t_req
                eva[f"{act}_start"] = self.env.now
                eva["va_min"] += d
            yield from res.hold(d, BUSY, act)
            if record:
                eva[f"{act}_end"] = self.env.now

    # ------------------------------------------------------------- processes
    def _arrivals(self):  # generator
        k = 0
        cfg = self.cfg
        cv = 0.0 if self.det else float(cfg.raw["demand"].get("interarrival_cv", 0.0))
        while True:
            o = self._new_order(k)
            self.orders.append(o)
            self.env.process(self._order(o))
            k += 1
            z = float(self.rng_orders.standard_normal())
            yield self.env.timeout(lognormal_from_z(cfg.interarrival_min, cv, z))

    def _order(self, o: Order):  # generator
        env, B, tb = self.env, self.B, self.tb
        for i in range(B):
            eva = {"order": o.oid, "idx": i, "arrival": o.arrival, "va_min": 0.0, "stage": None,
                   "tests": 0, "failed": False}
            o.evas.append(eva)
            self._stage(eva, "engineering")
            self.total.change(env.now, +1)
        yield env.timeout(self._delay(o, "engineering_release"))
        o.release = env.now
        sheet = env.timeout(self._delay(o, "procurement_sheet_metal"))
        tube = env.timeout(self._delay(o, "procurement_tubing"))
        for eva in o.evas:
            self._stage(eva, "awaiting_material")
        g = {k: Gate(env, B, tb) for k in ("fins", "box", "trim", "hp", "hdr", "stk", "rb", "ex",
                                           "hw", "wash", "test", "pb", "fw", "pa", "dtw", "dta")}
        punched = [env.event() for _ in range(B)]
        # fin press (step 3, in parallel with procurement) and sheet metal are not gated
        env.process(self._fin_press_job(o, g["fins"], punched))
        env.process(self._drip_tray_lot(o, sheet, g))
        for i in range(B):
            env.process(self._plenum(o, i, sheet, g))
        # shop-floor release of the coil line: tubing kitted + CONWIP card (if used)
        yield tube
        o.tube_arrival = env.now
        if self.conwip is not None:
            yield self.conwip.get(1)
        o.card = env.now
        for eva in o.evas:
            self._stage(eva, "prep")
        for i in range(B):
            env.process(self._boxing(o, i, punched[i], g["box"]))
            env.process(self._tubes(o, i, g))
            env.process(self._headers(o, i, g["hdr"]))
            env.process(self._coil(o, i, g))

    def _fin_press_job(self, o: Order, gate: Gate, punched: list[simpy.Event]):  # generator
        """Fin-press job: setup, then punch B EVA (equations A9 when stochastic)."""
        res = self.R[self.cfg.raw["fin_press"]["resource"]]
        fp, env = self.fp, self.env
        t_req = env.now
        with res.request(1) as req:
            yield req
            res.note_wait("fin_press", t_req)
            t0 = env.now
            for eva in o.evas:
                eva["fin_press_ready"], eva["fin_press_start"] = t_req, t0
            setup = lognormal_from_z(fp["S"], fp["setup_cv"], float(self.rng_fp.standard_normal()))
            yield from res.hold(setup, CHANGEOVER, "fin_press")
            for i in range(self.B):
                if self.det:
                    r = self.fp_eq
                    yield from res.hold(r.T_run, BUSY, "fin_press")
                    yield from res.hold(r.T_run * (1 / r.A_u - 1), DOWN, "fin_press")
                    yield from res.hold(r.reloads_per_eva * fp["t_r"], CHANGEOVER, "fin_press")
                else:
                    yield from self._punch_eva(res)
                o.evas[i]["fin_press_end"] = env.now
                punched[i].succeed()
                gate.done(i)
            o.fin_job_min = env.now - t0
            for eva in o.evas:
                eva["va_min"] += o.fin_job_min / self.B
            self.fin_jobs.append({"order": o.oid, "start": t0, "end": env.now,
                                  "job_min": o.fin_job_min, "setup_min": setup})

    def _punch_eva(self, res: TimedResource):  # generator
        """Punch one EVA: scrap ~ NegBin, run with stops at rate 1/MTBF, reel changes."""
        fp, rng = self.fp, self.rng_fp
        gross = fp["F"] + float(rng.negative_binomial(fp["F"], fp["Q"]))
        rate = fp["r_n"] * fp["P"]
        while gross > 1e-9:
            chunk = min(gross, self.reel_left)
            run = chunk / rate
            while run > 1e-12:
                if self.fp_ttf >= run:
                    yield from res.hold(run, BUSY, "fin_press")
                    self.fp_ttf -= run
                    run = 0.0
                else:
                    yield from res.hold(self.fp_ttf, BUSY, "fin_press")
                    run -= self.fp_ttf
                    rep = lognormal_from_z(fp["MTTR"], fp["mttr_cv"], float(rng.standard_normal()))
                    yield from res.hold(rep, DOWN, "fin_press")
                    self.fp_ttf = float(rng.standard_exponential()) * fp["MTBF"]
            gross -= chunk
            self.reel_left -= chunk
            if self.reel_left <= 1e-9:
                yield from res.hold(fp["t_r"], CHANGEOVER, "fin_press")
                self.reel_left = fp["R"]

    def _boxing(self, o: Order, i: int, punched: simpy.Event, gate: Gate):  # generator
        yield punched
        yield from self._work(o, i, "boxing")
        gate.done(i)

    def _tubes(self, o: Order, i: int, g: dict[str, Gate]):  # generator
        yield from self._work(o, i, "trim_tubes")
        g["trim"].done(i)
        yield g["trim"].event(i)
        yield from self._work(o, i, "weld_hairpins")
        g["hp"].done(i)

    def _headers(self, o: Order, i: int, gate: Gate):  # generator
        yield from self._work(o, i, "prepare_headers")
        gate.done(i)

    def _plenum(self, o: Order, i: int, sheet: simpy.Event, g: dict[str, Gate]):  # generator
        yield sheet
        yield from self._work(o, i, "press_brake")
        g["pb"].done(i)
        yield g["pb"].event(i)
        yield from self._work(o, i, "flat_welding")
        g["fw"].done(i)
        yield g["fw"].event(i)
        yield from self._work(o, i, "plenum_assembly")
        g["pa"].done(i)

    def _drip_tray_lot(self, o: Order, sheet: simpy.Event, g: dict[str, Gate]):  # generator
        yield sheet
        yield self.env.timeout(self._delay(o, "drip_tray_external"))
        for i in range(self.B):
            o.evas[i]["drip_tray_external_end"] = self.env.now
            self.env.process(self._drip_tray_eva(o, i, g))

    def _drip_tray_eva(self, o: Order, i: int, g: dict[str, Gate]):  # generator
        yield from self._work(o, i, "drip_tray_weld")
        g["dtw"].done(i)
        yield g["dtw"].event(i)
        yield from self._work(o, i, "drip_tray_assembly")
        g["dta"].done(i)

    def _test_loop(self, o: Order, i: int):  # generator
        eva = o.evas[i]
        for k in range(MAX_TESTS):
            first = k == 0
            yield from self._work(o, i, "pressure_test", record=first,
                                  activity="pressure_test")
            self.tests += 1
            eva["tests"] += 1
            if first and self.win.contains(self.env.now):
                self.first_tests += 1
            failed = (not self.det) and k < MAX_TESTS - 1 and o.u_test[i, k] < self.rw["fail_prob"]
            if not failed:
                eva["test_pass_t"] = self.env.now
                return
            eva["failed"] = True
            if first and self.win.contains(self.env.now):
                self.first_fail += 1
            d = lognormal_from_z(self.rw["rework_min"], self.rw["cv"], float(o.z_rework[i, k]))
            self.reworks += 1
            yield from self._work(o, i, "header_welding", priority=0, duration=d,
                                  activity="rework", record=False)

    def _coil(self, o: Order, i: int, g: dict[str, Gate]):  # generator
        env, eva = self.env, o.evas[i]
        inputs = [g["fins"].event(i), g["box"].event(i), g["hp"].event(i)]
        yield simpy.AllOf(env, inputs)
        eva["steeking_join_t"] = env.now
        self._stage(eva, "coil_line")
        for op, key in (("steeking", "stk"), ("weld_return_bends", "rb"), ("expansion", "ex")):
            yield from self._work(o, i, op)
            g[key].done(i)
            yield g[key].event(i)
        yield g["hdr"].event(i)
        eva["header_join_t"] = env.now
        yield from self._work(o, i, "header_welding")
        g["hw"].done(i)
        yield g["hw"].event(i)
        seq = (["wash", "test"] if self.flags["wash_before_test"] else ["test", "wash"])
        for step in seq:
            if step == "wash":
                yield from self._work(o, i, "wash")
                g["wash"].done(i)
                yield g["wash"].event(i)
            else:
                yield from self._test_loop(o, i)
                g["test"].done(i)
                yield g["test"].event(i)
        o.tested += 1
        if o.tested == self.B and self.conwip is not None:
            self.conwip.put(1)
        if self.flags["include_outsourced_coating"]:
            self._stage(eva, "coating")
            grp = i // self.tb
            yield env.timeout(self._delay(o, "coating", z=float(o.z_coat[grp])))
            eva["coating_end"] = env.now
        self._stage(eva, "final_assembly")
        yield simpy.AllOf(env, [g["pa"].event(i), g["dta"].event(i)])
        eva["assembly_join_t"] = env.now
        yield from self._work(o, i, "complete_assembly")
        eva["completion"] = env.now
        self._stage(eva, None)
        self.total.change(env.now, -1)
        self.completed_total += 1
        if self.win.contains(env.now):
            self.weekly[self.win.week_of(env.now)] += 1
        o.done += 1
        if o.done == self.B:
            o.completion = env.now

    # -------------------------------------------------------------------- run
    def run(self) -> SimResult:
        """Run to the end of the measurement window and collect the results."""
        env, win, cfg = self.env, self.win, self.cfg
        env.run(until=win.end)
        for r in self.R.values():
            r.finalize()
        due = cfg.raw["demand"]["due_date_weeks"] * cfg.week_min
        orows = []
        for o in self.orders:
            done = not math.isnan(o.completion)
            lt = o.completion - o.arrival if done else math.nan
            orows.append({
                "order": o.oid, "arrival": o.arrival, "release": o.release,
                "tube_arrival": o.tube_arrival, "card": o.card,
                "card_wait_min": o.card - o.tube_arrival,
                "completion": o.completion, "lead_time_min": lt,
                "lead_time_days": lt / cfg.day_min, "due": o.arrival + due,
                "on_time": bool(done and o.completion <= o.arrival + due),
                "completed_in_window": bool(done and win.contains(o.completion)),
                "completion_week": win.week_of(o.completion) if done else -1,
                "fin_job_min": o.fin_job_min,
            })
        evas = pd.DataFrame([e for o in self.orders for e in o.evas])
        rrows, arows = [], []
        for name, r in self.R.items():
            sh = r.shares()
            rrows.append({"resource": name, "label": cfg.resource_label(name),
                          "servers": r.servers, **sh,
                          "active": sh["busy"] + sh["down"] + sh["changeover"],
                          "mean_wait_min": (float(np.mean([w for ws in r.waits.values()
                                                           for w in ws]))
                                            if any(r.waits.values()) else 0.0)})
            for act, b in r.activity_busy().items():
                ws = r.waits.get(act, [])
                arows.append({"resource": name, "activity": act, "busy": b,
                              "mean_wait_min": float(np.mean(ws)) if ws else 0.0,
                              "n_waits": len(ws)})
        waits = pd.DataFrame([{"activity": a, "resource": n, "mean_wait_min": float(np.mean(ws)),
                               "n": len(ws)} for n, r in self.R.items()
                              for a, ws in r.waits.items() if ws])
        return SimResult(
            rep=self.rep, theta_steeking=self.theta, win=win, orders=pd.DataFrame(orows),
            evas=evas, weekly_output=self.weekly, resources=pd.DataFrame(rrows),
            activities=pd.DataFrame(arows), waits=waits,
            wip_by_stage={s: a.mean(win.end) for s, a in self.stage_avg.items()},
            wip_total=self.total.mean(win.end), wip_peak=self.total.peak,
            tests=self.tests, first_tests=self.first_tests,
            first_test_failures=self.first_fail, reworks=self.reworks,
            arrived=len(self.orders) * self.B, completed_evas_total=self.completed_total,
            in_system_end=self.total.level, fin_jobs=pd.DataFrame(self.fin_jobs),
        )


def simulate(cfg: LineConfig, rep: int = 0, base_seed: int | None = None,
             theta_steeking: float | None = None) -> SimResult:
    """Run replication ``rep`` of ``cfg``."""
    return EvaporatorModel(cfg, rep, base_seed, theta_steeking).run()
