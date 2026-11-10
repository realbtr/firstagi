"""Bounded K1 fixture with a private sensorimotor space."""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from enum import Enum
from hashlib import sha256
from random import Random


class Request(Enum):
    MOVE = "move"
    REVERSE = "reverse"
    RESOLVE = "resolve"


class Origin(Enum):
    REFLEX = "reflex"
    PROGRAM = "program"


class Status(Enum):
    EXECUTED = "executed"
    NO_SLOT = "no_slot"
    STALE = "stale"
    REFUSED = "refused"


@dataclass(frozen=True, slots=True)
class Observation:
    key: str
    revision: int


@dataclass(frozen=True, slots=True)
class ProgramStep:
    request: Request
    expected: Observation


@dataclass(frozen=True, slots=True)
class Transition:
    command: str
    key: str
    goal: str
    origin: Origin
    revision: int


@dataclass(frozen=True, slots=True)
class Report:
    transitions: tuple[Transition, ...]
    program_status: Status | None
    observation: Observation


def _opaque_id(seed: int, namespace: str) -> str:
    return sha256(f"k1/v1/{seed}/{namespace}".encode()).hexdigest()


class NestedRegionDriver:
    """One private branch of the fixture. Clients use make_fixture()."""

    def __init__(self, seed: int, place: int, branch: int) -> None:
        self._move = _opaque_id(seed, "move")
        self._reverse = _opaque_id(seed, "reverse")
        self._resolve = _opaque_id(seed, "resolve")
        self._coarse = _opaque_id(seed, f"{place}/a")
        self._nested = _opaque_id(seed, f"{place}/a/{branch}")
        self._target = _opaque_id(seed, f"{place}/b/{branch if place else 0}")
        self._allows_resolution = place != 2
        # State records physical phase and resolution. The private branch
        # stays the same across coarse views, movement and its inverse.
        self._state = (False, False)
        self._previous: tuple[bool, bool] | None = None
        self._revision = 0
        self._tick = 0

    @property
    def observation(self) -> Observation:
        at_target, resolved = self._state
        key = self._target if at_target else self._nested if resolved else self._coarse
        return Observation(key, self._revision)

    def _transition(
        self, command: str, state: tuple[bool, bool], origin: Origin,
    ) -> Transition:
        key = self.observation.key
        self._previous, self._state = self._state, state
        self._revision += 1
        return Transition(command, key, self.observation.key, origin, self._revision)

    def _movement(self, origin: Origin) -> Transition:
        at_target, resolved = self._state
        return self._transition(self._move, (not at_target, resolved), origin)

    def _execute(self, request: Request) -> Transition | None:
        if request is Request.MOVE:
            return self._movement(Origin.PROGRAM)
        if request is Request.REVERSE:
            if self._previous is not None:
                return self._transition(self._reverse, self._previous, Origin.PROGRAM)
            return None
        if request is Request.RESOLVE:
            if self._allows_resolution and self._state == (False, False):
                return self._transition(self._resolve, (False, True), Origin.PROGRAM)
            return None
        raise ValueError(f"Unsupported request: {request!r}")

    def tick(self, step: ProgramStep | None = None) -> Report:
        """Run one reflex, optionally preceded by a guarded program command."""
        status = None
        program_transition = None
        if step is not None:
            if self._tick % 3 == 0:
                status = Status.NO_SLOT
            elif step.expected != self.observation:
                status = Status.STALE
            else:
                program_transition = self._execute(step.request)
                status = Status.EXECUTED if program_transition else Status.REFUSED
        reflex = self._movement(Origin.REFLEX)
        self._tick += 1
        transitions = (program_transition, reflex) if program_transition else (reflex,)
        return Report(transitions, status, self.observation)

    def run_program(self, steps: Iterable[ProgramStep]) -> Iterator[Report]:
        """Execute one request per tick, returning a report before the next request."""
        for step in steps:
            yield self.tick(step)


def make_fixture(seed: int) -> tuple[NestedRegionDriver, ...]:
    """Two branches per place in private seeded order, with no public case labels."""
    cases = [(place, branch) for place in range(3) for branch in range(2)]
    Random(seed).shuffle(cases)
    return tuple(NestedRegionDriver(seed, place, branch) for place, branch in cases)
