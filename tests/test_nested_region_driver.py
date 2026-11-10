from collections import defaultdict
from dataclasses import asdict

from drivers.nested_region_driver import (
    Origin,
    ProgramStep,
    Request,
    Status,
    make_fixture,
)


def test_reflex_stream_is_reproducible_without_a_program():
    first = make_fixture(17)
    second = make_fixture(17)
    assert [driver.observation for driver in first] == [
        driver.observation for driver in second
    ]
    for left, right in zip(first, second):
        for revision in range(1, 5):
            report = left.tick()
            assert report == right.tick()
            assert report.program_status is None
            transition, = report.transitions
            assert transition.origin is Origin.REFLEX
            assert transition.revision == revision
            assert transition.goal == report.observation.key
            assert set(asdict(transition)) == {"command", "key", "goal", "origin", "revision"}
            assert all(len(bytes.fromhex(value)) == 32 for value in (
                transition.command, transition.key, transition.goal
            ))


def test_program_interleaves_with_reflex_and_reports_missing_slot():
    driver = make_fixture(17)[0]

    def steps():
        for _ in range(3):
            yield ProgramStep(Request.MOVE, driver.observation)

    first, second, third = driver.run_program(steps())
    assert first.program_status is Status.NO_SLOT
    assert [t.origin for t in first.transitions] == [Origin.REFLEX]
    for report in (second, third):
        assert report.program_status is Status.EXECUTED
        assert [t.origin for t in report.transitions] == [Origin.PROGRAM, Origin.REFLEX]
        assert report.transitions[0].goal == report.transitions[1].key
    assert [t.revision for r in (first, second, third) for t in r.transitions] == list(range(1, 6))


def test_reverse_closes_each_hidden_branch_before_the_next_reflex():
    for driver in make_fixture(17):
        initial = driver.observation
        initial_state = driver._state
        outward, = driver.tick().transitions
        report = driver.tick(ProgramStep(Request.REVERSE, driver.observation))
        inward, reflex = report.transitions
        assert report.program_status is Status.EXECUTED
        assert inward.origin is Origin.PROGRAM
        assert inward.command != outward.command
        assert (outward.key, outward.goal) == (inward.goal, inward.key)
        assert inward.goal == initial.key
        # The following reflex records the restored physical source state.
        assert driver._previous == initial_state
        assert (reflex.key, reflex.goal) == (outward.key, outward.goal)


def test_reflex_round_trip_invalidates_same_key_program():
    driver = make_fixture(17)[0]
    saved = driver.observation
    driver.tick()
    driver.tick()
    assert driver.observation.key == saved.key
    report = driver.tick(ProgramStep(Request.MOVE, saved))
    assert report.program_status is Status.STALE
    assert [t.origin for t in report.transitions] == [Origin.REFLEX]


def test_nested_keys_disambiguate_only_where_driver_allows():
    by_coarse = defaultdict(list)
    for driver in make_fixture(17):
        coarse = driver.observation.key
        outward, = driver.tick().transitions
        driver.tick()
        report = driver.tick(ProgramStep(Request.RESOLVE, driver.observation))
        by_coarse[coarse].append((outward.goal, report))
    assert len(by_coarse) == 3
    profiles = set()
    for cases in by_coarse.values():
        assert len(cases) == 2
        reports = [report for _, report in cases]
        statuses = {r.program_status for r in reports}
        assert len(statuses) == 1
        status, = statuses
        targets = {target for target, _ in cases}
        profiles.add((len(targets), status))
        if status is Status.EXECUTED:
            nested = {r.transitions[0].goal for r in reports}
            assert len(nested) == 2
            assert nested.isdisjoint(by_coarse)
            assert all(r.transitions[0].origin is Origin.PROGRAM for r in reports)
        else:
            assert all([t.origin for t in r.transitions] == [Origin.REFLEX] for r in reports)
    assert profiles == {
        (1, Status.EXECUTED), (2, Status.EXECUTED), (2, Status.REFUSED),
    }
