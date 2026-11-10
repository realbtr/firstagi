"""Compare opt-in repeat recognition with the current token path in K1."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from core.generalization import PeripheralToken
from core.learning import LearningSystem
from drivers.nested_region_driver import make_fixture
from experiments.diagnostics.ac0_operation_codec import OperationCodec


def run(features, *, debug: bool) -> dict:
    system = LearningSystem(feature_tolerance=0.0)
    system.engine.debug_repeat_recognition = debug
    completions = Counter()
    outcomes = Counter()
    sizes = []
    for index, feature in enumerate(features):
        token = PeripheralToken(token_id=f"probe/{index}", driver_id="k1", data=feature)
        result = system.process_token(token)
        outcomes[result.outcome.name] += 1
        completions.update(result.completed_gen_ids)
        sizes.append(system.base.size())
    pair = features[:2]
    return {
        "gens_by_step": sizes,
        "outcomes": dict(outcomes),
        "covering_pairs": [
            {
                "success_count": gen.success_count,
                "full_completions": completions[gen.gen_id],
            }
            for gen in system.base.all()
            if gen.feature_chain == [feature.feature_id for feature in pair]
        ],
        "actual_evidence_entries": system.base.actual_evidence_entries,
    }


def compare() -> dict:
    driver = make_fixture(17)[0]
    codec = OperationCodec()
    alternating = []
    for _ in range(24):
        transition, = driver.tick().transitions
        alternating.append(codec.encode_role(
            f"k1/{transition.command}", transition.key, transition.goal,
            "operation_to_observation",
        ))
    unique = [codec.encode("k1-unique", f"cue/{i}", "observe") for i in range(24)]
    return {
        name: {arm: run(features, debug=arm == "debug") for arm in ("current", "debug")}
        for name, features in (("alternating", alternating), ("unique", unique))
    }


if __name__ == "__main__":
    print(json.dumps(compare(), indent=2))
