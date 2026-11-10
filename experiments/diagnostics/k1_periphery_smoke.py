"""Measure delivery of a reflex stream to the existing token learner."""
from __future__ import annotations

import argparse
import json
import pickle
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.generalization import PeripheralToken
from core.learning import LearningSystem
from drivers.nested_region_driver import make_fixture
from experiments.diagnostics.ac0_operation_codec import OperationCodec


def smoke(*, trace: bool = False) -> dict:
    seed, ticks = 17, 24
    driver = make_fixture(seed)[0]
    system = LearningSystem(feature_tolerance=0.0)
    codec = OperationCodec()
    transitions = []
    reads = []
    rows = []

    for _ in range(ticks):
        transition, = driver.tick().transitions
        transitions.append(transition)
        # Reuse the opaque codec with command as the projection namespace.
        # The codec sees only the three public identifiers.
        feature = codec.encode_role(
            f"k1/{transition.command}",
            transition.key,
            transition.goal,
            "operation_to_observation",
        )
        token = PeripheralToken.new("k1", feature)
        if trace:
            # Inspection stays outside the measured learner call.
            expected = system.engine.context.get_expected_features(system.base)
            known = {
                gen.gen_id: gen.success_count for gen in system.base.all()
                if gen.feature_chain == [feature.feature_id]
            }
        system.base.start_operation_reads(sys.maxsize)
        try:
            result = system.process_token(token)
        finally:
            reads.append(system.base.finish_operation_reads())
        if trace:
            current = {
                gen.gen_id: gen.success_count for gen in system.base.all()
                if gen.feature_chain == [feature.feature_id]
            }
            rows.append({
                "step": len(transitions),
                "input_feature": feature.feature_id,
                "expected_before": expected,
                "known_atoms_before": known,
                "outcome": result.outcome.name,
                "new_gen": result.new_gen_id,
                "removed_gens": result.removed_gen_ids,
                "matched_feature": result.matched_feature_id,
                "completed_gens": result.completed_gen_ids,
                "known_atoms_after": current,
            })

    closed_pairs = sum(
        first.goal == second.key and second.goal == first.key
        for first, second in zip(transitions[::2], transitions[1::2])
    )
    gens = system.base.all()
    repeated = sum(gen.success_count > 1 for gen in gens)
    summary = {
        "status": "smoke",
        "seed": seed,
        "transitions": len(transitions),
        "driver_closed_public_pairs": closed_pairs,
        "gens": len(gens),
        "gens_with_multiple_token_confirmations": repeated,
        "fraction_with_multiple_token_confirmations": repeated / len(gens) if gens else None,
        "metered_genbase_visits_per_step": reads,
        "mean_metered_genbase_visits_per_step": sum(reads) / len(reads),
        "serialized_learner_bytes": len(pickle.dumps(system, protocol=5)),
        "actual_evidence_entries": system.base.actual_evidence_entries,
    }
    if trace:
        summary["trace"] = rows
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trace", action="store_true", help="include per-step token learner observations")
    print(json.dumps(smoke(trace=parser.parse_args().trace), indent=2))
