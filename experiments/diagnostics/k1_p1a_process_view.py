"""P1-a smoke: derive dependent-process views from the ledger on the K1 stream.

Forced MOVE commands on the nested-region fixture are recorded through the
existing part-A operation ledger. The native chain (key, command, goal) is
created by the existing GreedyGeneralizer from step events, as in the A1/A2
component tests: a ledger fixture, not a closed-loop choice experiment.
"""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.algorithm import StepOutcome, StepResult
from core.dependent_process import process_views
from core.generalization import Generalization, PeripheralToken
from core.learning import LearningSystem, OperationReceipt, OperationView
from drivers.nested_region_driver import (
    ProgramStep, Request, Status, _opaque_id, make_fixture,
)
from experiments.diagnostics.ac0_operation_codec import OperationCodec

INSTANCE, CHANNEL = "life", "k1"


class Adapter:
    """Transport only: opaque public identifiers become native atoms."""

    def __init__(self) -> None:
        self.system = LearningSystem(feature_tolerance=0.0)
        self.codec = OperationCodec()
        self.atoms = {}
        self.seq = 0

    def atom(self, ident: str):
        if ident not in self.atoms:
            feature = self.codec.encode_role(CHANNEL, ident, ident, "cue_anchor")
            self.system.engine.register_feature(feature)
            gen = self.system.base.add(Generalization.new(feature_chain=[feature.feature_id]))
            self.atoms[ident] = (gen.gen_id, feature)
        return self.atoms[ident]

    def _learn_chain(self, chain):
        generalizer = self.system.generalizer
        generalizer.reset_chain()
        for fid in chain:
            generalizer.on_step_result(StepResult(
                outcome=StepOutcome.COMPLETED if fid == chain[-1] else StepOutcome.CONFIRMED,
                token=PeripheralToken.new(CHANNEL, None), matched_feature_id=fid))
        generalizer.reset_chain()
        return self.system.base.search_by_chain(list(chain))[0]

    def forced(self, driver, branch: int, request: Request) -> Status:
        """One forced program command; returns the driver's program status."""
        system = self.system
        observation = driver.observation
        cue_gid, cue_feature = self.atom(observation.key)
        op_gid, op_feature = self.atom(f"request/{request.value}")
        seq, self.seq = self.seq, self.seq + 1
        view = OperationView(INSTANCE, CHANNEL, seq, cue_gid, cue_gid,
                             ((request.value, op_gid),),
                             PeripheralToken.new(CHANNEL, cue_feature), 1_000_000)
        system.begin_operation(public_view=view, command_address=request.value)
        report = driver.tick(ProgramStep(request, observation))
        if report.program_status is not Status.EXECUTED:
            system.cancel_operation(INSTANCE, CHANNEL)
            return report.program_status
        transition = report.transitions[0]
        goal_gid, goal_feature = self.atom(transition.goal)
        receipt = OperationReceipt(f"r{seq}", INSTANCE, CHANNEL, seq, request.value,
                                   f"branch{branch}/rev{transition.revision}",
                                   outcome_gen_id=goal_gid)
        system.accept_operation_outcome(receipt)
        chain = (cue_feature.feature_id, op_feature.feature_id, goal_feature.feature_id)
        if not system.base.search_by_chain(list(chain)):
            gen = self._learn_chain(chain)
            system.bind_operation_evidence(gen.gen_id, receipt.receipt_id)
        return report.program_status


def labels(seed: int) -> dict:
    """Evaluator-only names of opaque keys; never shown to the core."""
    names = {}
    for place in range(3):
        names[_opaque_id(seed, f"{place}/a")] = f"A{place}"
        for branch in range(2):
            names[_opaque_id(seed, f"{place}/a/{branch}")] = f"a{place}/{branch}"
            target = _opaque_id(seed, f"{place}/b/{branch if place else 0}")
            names[target] = f"B{place}/{branch}" if place else "B0"
    return names


def run(*, seed: int = 17, rounds: int = 8) -> dict:
    adapter = Adapter()
    fixture = make_fixture(seed)
    statuses = {"executed": 0, "no_slot": 0, "stale": 0, "refused": 0}
    for _ in range(rounds):
        for branch, driver in enumerate(fixture):
            while True:
                status = adapter.forced(driver, branch, Request.MOVE)
                statuses[status.value] += 1
                if status is Status.EXECUTED:
                    break

    system = adapter.system
    before = pickle.dumps(system, protocol=5)
    views = process_views(system)
    unchanged = pickle.dumps(system, protocol=5) == before

    name = labels(seed)
    by_gid = {gid: name.get(ident, ident) for ident, (gid, _) in adapter.atoms.items()}
    points = []
    for view in sorted(views, key=lambda v: by_gid[v.cue_gen_id]):
        points.append({
            "cue": by_gid[view.cue_gen_id],
            "operation": by_gid[view.operation_gen_id],
            "executions": view.executions,
            "cancelled": view.cancelled,
            "outcomes": [by_gid[o] for o in view.outcomes],
            "bifurcation": view.is_bifurcation,
            "detected_seq": view.detected_seq,
            "hidden_executions": view.hidden_executions,
            "failed_forecasts_at_detection": view.failed_forecasts_at_detection,
            "failed_admitted_at_detection": view.failed_admitted_at_detection,
            "status": view.status,
            "resolution_attempts": view.resolution_attempts,
        })
    support = []
    for gen in system.base.all():
        evidence = getattr(gen, "actual_evidence", {})
        if not evidence:
            continue
        positive = sum(e.positive for e in evidence.values())
        first = min(seq for _, _, seq in evidence)
        support.append({
            "cue": by_gid[gen.key_id], "goal": by_gid[gen.goal_id],
            "first_seq": first, "p": positive, "n": len(evidence) - positive,
            "admitted": gen.operation_admitted,
        })
    support.sort(key=lambda row: (row["cue"], row["first_seq"]))
    return {
        "status": "smoke",
        "seed": seed,
        "rounds": rounds,
        "program_statuses": statuses,
        "points": points,
        "bifurcation_points": [p["cue"] for p in points if p["bifurcation"]],
        "support": support,
        "view_left_state_unchanged": unchanged,
        "operation_state_usage": system.operation_state_usage(),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=17)
    parser.add_argument("--rounds", type=int, default=8)
    args = parser.parse_args()
    print(json.dumps(run(seed=args.seed, rounds=args.rounds), indent=2, ensure_ascii=False))
