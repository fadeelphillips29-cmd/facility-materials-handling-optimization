"""Instrumented SimPy building blocks: measurement window, timed resources and gates.

Every resource records the time it spends in each state (busy, changeover,
down), split by activity and clipped to the measurement window. Idle time is
reported as *starved*. Inter-station queues are unlimited (ASSUMPTIONS A13),
so *blocked* is always 0, but it is kept so the state model is complete.
Queue (waiting) times are recorded for every request that is granted inside
the window.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from dataclasses import dataclass, field

import simpy

BUSY, CHANGEOVER, DOWN = "busy", "changeover", "down"
STATES = ("busy", "starved", "blocked", "down", "changeover")


@dataclass(frozen=True)
class Window:
    """Measurement window [start, end) in working minutes."""

    start: float
    end: float
    week_min: float

    @property
    def length(self) -> float:
        """Window length (minutes)."""
        return self.end - self.start

    def overlap(self, a: float, b: float) -> float:
        """Length of [a, b) that lies inside the window."""
        lo, hi = max(a, self.start), min(b, self.end)
        return hi - lo if hi > lo else 0.0

    def contains(self, t: float) -> bool:
        """True if ``t`` lies in the window."""
        return self.start <= t < self.end

    def week_of(self, t: float) -> int:
        """Index of the measured week that contains ``t`` (0-based)."""
        return int((t - self.start) // self.week_min)


class TimeAverage:
    """Time-weighted average of an integer level, clipped to the window."""

    __slots__ = ("win", "level", "last", "area", "peak")

    def __init__(self, win: Window) -> None:
        self.win, self.level, self.last, self.area, self.peak = win, 0, 0.0, 0.0, 0

    def change(self, now: float, delta: int) -> None:
        """Add ``delta`` to the level at time ``now``."""
        self.area += self.level * self.win.overlap(self.last, now)
        self.level += delta
        self.last = now
        self.peak = max(self.peak, self.level)

    def mean(self, now: float) -> float:
        """Average level over the window (call once, at the end)."""
        self.change(now, 0)
        return self.area / self.win.length


@dataclass
class TimedResource:
    """A SimPy priority resource that times its own states.

    Args:
        env: Simulation environment.
        name: Resource id.
        servers: Number of parallel servers (stations or fixtures).
        win: Measurement window.
    """

    env: simpy.Environment
    name: str
    servers: int
    win: Window
    res: simpy.PriorityResource = field(init=False)
    acc: dict[tuple[str, str], float] = field(init=False)
    waits: dict[str, list[float]] = field(init=False)
    _open: dict[int, tuple[str, str, float]] = field(init=False)
    _ids: itertools.count = field(init=False)

    def __post_init__(self) -> None:
        self.res = simpy.PriorityResource(self.env, capacity=self.servers)
        self.acc = defaultdict(float)
        self.waits = defaultdict(list)
        self._open = {}
        self._ids = itertools.count()

    # --------------------------------------------------------------- queueing
    def request(self, priority: int = 1) -> simpy.resources.resource.PriorityRequest:
        """Create a request (lower ``priority`` value = served first)."""
        return self.res.request(priority=priority)

    def note_wait(self, activity: str, requested_at: float) -> float:
        """Record the queue time of a request just granted, and return it."""
        w = self.env.now - requested_at
        if self.win.contains(self.env.now):
            self.waits[activity].append(w)
        return w

    # ----------------------------------------------------------------- states
    def begin(self, state: str, activity: str) -> int:
        """Open a state interval; returns a token for :meth:`end`."""
        tok = next(self._ids)
        self._open[tok] = (state, activity, self.env.now)
        return tok

    def end(self, tok: int) -> None:
        """Close a state interval opened with :meth:`begin`."""
        state, activity, t0 = self._open.pop(tok)
        self.acc[(state, activity)] += self.win.overlap(t0, self.env.now)

    def hold(self, duration: float, state: str, activity: str):  # generator
        """Spend ``duration`` minutes in ``state`` doing ``activity``."""
        tok = self.begin(state, activity)
        yield self.env.timeout(duration)
        self.end(tok)

    def finalize(self) -> None:
        """Close intervals still open at the end of the run (clipped to the window)."""
        for state, activity, t0 in self._open.values():
            self.acc[(state, activity)] += self.win.overlap(t0, self.win.end)
        self._open.clear()

    def shares(self) -> dict[str, float]:
        """Share of server-time in each state (busy, starved, blocked, down, changeover)."""
        cap = self.servers * self.win.length
        out = {s: 0.0 for s in STATES}
        for (state, _a), t in self.acc.items():
            out[state] += t / cap
        out["starved"] = max(0.0, 1.0 - out["busy"] - out["down"] - out["changeover"])
        return out

    def activity_busy(self) -> dict[str, float]:
        """Busy share per activity (server-time basis)."""
        cap = self.servers * self.win.length
        out: dict[str, float] = defaultdict(float)
        for (state, a), t in self.acc.items():
            if state == BUSY:
                out[a] += t / cap
        return dict(out)


class Gate:
    """Transfer-batch gate for one order at one stage.

    EVA ``i`` belongs to group ``i // tb``. The group's event fires once
    every member of the group has called :meth:`done`, which releases the whole
    transfer batch to the next stage.
    """

    def __init__(self, env: simpy.Environment, n: int, tb: int) -> None:
        self.tb = tb
        self.groups = [list(range(g, min(n, g + tb))) for g in range(0, n, tb)]
        self.events = [env.event() for _ in self.groups]
        self.left = [len(g) for g in self.groups]
        self.done_at: list[float | None] = [None] * n
        self.env = env

    def event(self, i: int) -> simpy.Event:
        """Event that fires when EVA ``i``'s transfer batch is complete."""
        return self.events[i // self.tb]

    def done(self, i: int) -> None:
        """Mark EVA ``i`` as finished at this stage."""
        self.done_at[i] = self.env.now
        g = i // self.tb
        self.left[g] -= 1
        if self.left[g] == 0:
            self.events[g].succeed(self.env.now)
