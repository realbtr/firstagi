"""Measure Z5 and its pinned controls on the frozen synthetic streams."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import pickle
import sys


def run(system, symbols, drivers, *, arm):
    from core.generalization import PeripheralToken
    from experiments.diagnostics.ac0_operation_codec import OperationCodec

    if arm == "z3":
        system.engine.debug_repeat_recognition = True
    elif arm == "z5":
        system.engine.debug_chain_recall = True
    codec = OperationCodec()
    features = {
        symbol: codec.encode(driver, symbol, "observe")
        for symbol, driver in zip(symbols, drivers)
    }
    names = {feature.feature_id: symbol for symbol, feature in features.items()}
    rows = []
    for index, (symbol, driver) in enumerate(zip(symbols, drivers), 1):
        feature = features[symbol]
        token = PeripheralToken(token_id=f"z5/{index}", driver_id=driver, data=feature)
        # Read expectations for classification outside the measured call.
        active = dict(system.engine.context.active_positions())
        expected = system.engine.context.get_expected_features(system.base)
        confirming_ab = any(
            position > 0
            and expected.get(gen_id) == feature.feature_id
            and set(names.get(fid) for fid in system.base.get(gen_id).feature_chain)
            <= {"A", "B"}
            for gen_id, position in active.items()
        )
        system.base.start_operation_reads(sys.maxsize)
        try:
            result = system.process_token(token)
        finally:
            visits = system.base.finish_operation_reads()
        completed = [
            "".join(names[fid] for fid in system.base.get(gen_id).feature_chain)
            for gen_id in result.completed_gen_ids
            if gen_id in active and len(system.base.get(gen_id).feature_chain) > 1
        ]
        rows.append({
            "feature": symbol,
            "outcome": result.outcome.name,
            "visits": visits,
            "gens": system.base.size(),
            "completed": completed,
            "confirmed_ab": confirming_ab and result.matched_feature_id == feature.feature_id,
        })
        if index in (24, 48):
            rows[-1]["bytes"] = len(pickle.dumps(system, protocol=5))
    return {
        "rows": rows,
        "chains": {
            "".join(names[fid] for fid in gen.feature_chain): gen.success_count
            for gen in system.base.all() if len(gen.feature_chain) > 1
        },
        "actual_entries": system.base.actual_evidence_entries,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--arm", choices=("current", "z3", "z5"), required=True)
    args = parser.parse_args()
    sys.path.insert(0, str(args.source.resolve()))
    from core.learning import LearningSystem

    patterns = {
        "AB": "AB" * 24,
        "ABC": "ABC" * 16,
        "ABCD": "ABCD" * 12,
        "AXBY": "AXBY" * 12,
        "interrupted": "ABABAX" * 4,
        "unique": [f"U{index:02d}" for index in range(1, 25)],
    }
    measurements = {}
    for name, symbols in patterns.items():
        drivers = ["second" if name == "AXBY" and symbol in "XY" else "first" for symbol in symbols]
        measurements[name] = run(
            LearningSystem(feature_tolerance=0.0), symbols, drivers, arm=args.arm
        )
    print(json.dumps(measurements))


if __name__ == "__main__":
    main()
