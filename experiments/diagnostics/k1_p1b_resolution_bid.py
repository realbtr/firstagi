"""P1-b smoke: the core asks for a nested region at a bifurcation point.

Four arms on the K1 fixture: the core without requests, the core with the bid
rule, a coarse table and a table that always requests. Every command goes
through the part-A operation ledger; the probe schedule belongs to the
evaluator and is the same for all arms.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.dependent_process import process_views, resolution_due
from core.generalization import PeripheralToken
from core.learning import OperationReceipt, OperationView
from drivers.nested_region_driver import ProgramStep, Request, Status, make_fixture
from experiments.diagnostics.k1_p1a_process_view import (
    CHANNEL, INSTANCE, Adapter, labels,
)

ARMS = ("core_no_request", "core_bid", "table_coarse", "table_always_request")


def settle(driver) -> None:
    """Evaluator: empty ticks until the branch is on side A in a tick with a slot."""
    while driver._state[0] or driver._tick % 3 == 0:
        driver.tick()


def place_of(driver, seed: int) -> int:
    """Evaluator-only label of the private place."""
    name = labels(seed)[driver._coarse]
    return int(name[1:])


class CoreArm(Adapter):
    def __init__(self, bid: bool) -> None:
        super().__init__()
        self.bid = bid

    def _begin(self, driver, request: Request):
        observation = driver.observation
        cue_gid, cue_feature = self.atom(observation.key)
        op_gid, op_feature = self.atom(f"request/{request.value}")
        seq, self.seq = self.seq, self.seq + 1
        view = OperationView(INSTANCE, CHANNEL, seq, cue_gid, cue_gid,
                             ((request.value, op_gid),),
                             PeripheralToken.new(CHANNEL, cue_feature), 1_000_000)
        pending = self.system.begin_operation(public_view=view, command_address=request.value)
        report = driver.tick(ProgramStep(request, observation))
        return seq, cue_feature, op_feature, pending, report

    def _observe(self, branch, seq, request, cue_feature, op_feature, transition):
        goal_gid, goal_feature = self.atom(transition.goal)
        receipt = OperationReceipt(f"r{seq}", INSTANCE, CHANNEL, seq, request.value,
                                   f"branch{branch}/rev{transition.revision}",
                                   outcome_gen_id=goal_gid)
        self.system.accept_operation_outcome(receipt)
        chain = (cue_feature.feature_id, op_feature.feature_id, goal_feature.feature_id)
        if not self.system.base.search_by_chain(list(chain)):
            gen = self._learn_chain(chain)
            self.system.bind_operation_evidence(gen.gen_id, receipt.receipt_id)
        return goal_gid

    def wants_resolution(self, driver) -> bool:
        if not self.bid:
            return False
        cue_gid, _ = self.atom(driver.observation.key)
        move_gid, _ = self.atom(f"request/{Request.MOVE.value}")
        return resolution_due(self.system, instance_id=INSTANCE, channel_id=CHANNEL,
                              cue_gen_id=cue_gid, operation_gen_id=move_gid)

    def resolve(self, driver, branch) -> Status:
        seq, cue_feature, op_feature, _, report = self._begin(driver, Request.RESOLVE)
        if report.program_status is Status.EXECUTED:
            self._observe(branch, seq, Request.RESOLVE, cue_feature, op_feature,
                          report.transitions[0])
        else:
            if report.program_status is Status.REFUSED:
                # The driver answered: an observed fact about the request,
                # not evidence for or against any forecast.
                self.system.accept_operation_outcome(OperationReceipt(
                    f"r{seq}", INSTANCE, CHANNEL, seq, Request.RESOLVE.value,
                    f"branch{branch}/refused{seq}", status="unavailable"))
            self.system.cancel_operation(INSTANCE, CHANNEL)
        return report.program_status

    def move(self, driver, branch) -> str:
        seq, cue_feature, op_feature, pending, report = self._begin(driver, Request.MOVE)
        assert report.program_status is Status.EXECUTED, report.program_status
        goals = {goal for gid, goal, _, _ in pending.forecasts
                 if self.system.base.get(gid).operation_admitted}
        actual = self._observe(branch, seq, Request.MOVE, cue_feature, op_feature,
                               report.transitions[0])
        if len(goals) != 1:
            return "abstain"
        return "correct" if goals == {actual} else "wrong"


class TableArm:
    """Key -> most frequent observed goal; ties and no data abstain."""

    def __init__(self, always_request: bool) -> None:
        self.always_request = always_request
        self.counts = {}

    def wants_resolution(self, driver) -> bool:
        return self.always_request

    def resolve(self, driver, branch) -> Status:
        return driver.tick(ProgramStep(Request.RESOLVE, driver.observation)).program_status

    def move(self, driver, branch) -> str:
        key = driver.observation.key
        ranked = self.counts.get(key, Counter()).most_common(2)
        guess = None
        if ranked and (len(ranked) == 1 or ranked[0][1] > ranked[1][1]):
            guess = ranked[0][0]
        report = driver.tick(ProgramStep(Request.MOVE, driver.observation))
        assert report.program_status is Status.EXECUTED, report.program_status
        actual = report.transitions[0].goal
        self.counts.setdefault(key, Counter())[actual] += 1
        if guess is None:
            return "abstain"
        return "correct" if guess == actual else "wrong"


def run_arm(name: str, *, seed: int, rounds: int) -> dict:
    arm = {
        "core_no_request": lambda: CoreArm(bid=False),
        "core_bid": lambda: CoreArm(bid=True),
        "table_coarse": lambda: TableArm(always_request=False),
        "table_always_request": lambda: TableArm(always_request=True),
    }[name]()
    fixture = make_fixture(seed)
    rows = {place: Counter() for place in range(3)}
    for _ in range(rounds):
        for branch, driver in enumerate(fixture):
            place = place_of(driver, seed)
            settle(driver)
            if arm.wants_resolution(driver):
                status = arm.resolve(driver, branch)
                assert status in (Status.EXECUTED, Status.REFUSED), status
                rows[place]["request_" + status.value] += 1
                settle(driver)
            rows[place][arm.move(driver, branch)] += 1
    result = {"places": {
        str(place): {key: row[key] for key in
                     ("correct", "wrong", "abstain", "request_executed", "request_refused")}
        for place, row in rows.items()}}
    if isinstance(arm, CoreArm):
        name_of = labels(seed)
        by_gid = {gid: name_of.get(ident, ident) for ident, (gid, _) in arm.atoms.items()}
        resolve_gid = arm.atoms.get(f"request/{Request.RESOLVE.value}", (None,))[0]
        result["bifurcation_points"] = sorted(
            ({"cue": by_gid[v.cue_gen_id], "operation": by_gid[v.operation_gen_id],
              "outcomes": sorted(by_gid[o] for o in v.outcomes),
              "resolution_attempts": v.resolution_attempts,
              "resolution_refused": v.resolution_refused, "status": v.status}
             for v in process_views(arm.system, resolve_gid) if v.is_bifurcation),
            key=lambda row: (row["cue"], row["operation"]))
        negatives = sum(
            not e.positive for gen in arm.system.base.all()
            for e in getattr(gen, "actual_evidence", {}).values())
        result["negative_evidence_entries"] = negatives
        result["operation_state_usage"] = arm.system.operation_state_usage()
    return result


def run(*, seed: int = 17, rounds: int = 8) -> dict:
    return {"status": "smoke", "seed": seed, "rounds": rounds,
            "arms": {name: run_arm(name, seed=seed, rounds=rounds) for name in ARMS}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--rounds", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(run(seed=args.seed, rounds=args.rounds), indent=2, ensure_ascii=False))
