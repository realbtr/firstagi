import copy
import json
from pathlib import Path
import pytest

from training.h22_counterfactual import (
    PROTOCOL, digest, execute_run, frozen_probes, index_digest, measure,
    synthetic_controls, training_stream, without_timing,
)


def test_measure_includes_missing_cues_and_keeps_index_unchanged():
    index = {"cue": ["one", "two"]}
    before = copy.deepcopy(index)
    result = measure(index, ["cue one", "absent target"])
    assert result["n"] == 2
    assert result["avg_candidates"] == 1.0
    assert result["target_coverage"] == 0.5
    assert index == before


def test_synthetic_control_can_measure_outside_miller_band():
    assert [r["measured"] for r in synthetic_controls()] == [1, 7, 16]


def test_empty_evaluation_is_an_error_not_zero_success():
    with pytest.raises(ValueError):
        measure({}, ["single"])


def test_index_digest_ignores_set_order_but_not_content():
    assert index_digest({"a": ["b", "c"]}) == index_digest({"a": ["c", "b"]})
    assert index_digest({"a": ["b"]}) != index_digest({"a": ["c"]})


def test_training_stream_pairs_conditions_and_excludes_eval_texts():
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    probes = frozen_probes(protocol)
    excluded = set(probes["familiar"] + probes["novel"])
    first = training_stream(42, 100, excluded)
    assert first == training_stream(42, 100, excluded)
    assert first != training_stream(41, 100, excluded)
    assert not set(first).intersection(excluded)


def test_real_short_run_is_reproducible_and_evaluation_frozen(tmp_path):
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    protocol["pilot"] = {"transitions": 100, "checkpoints": [50, 100]}
    protocol["corpus"]["evaluation_texts_per_domain"] = 2
    condition = protocol["conditions"][0]
    first = execute_run(protocol, condition, 42, "pilot", tmp_path/"a")
    second = execute_run(protocol, condition, 42, "pilot", tmp_path/"b")
    assert first["nontiming_sha256"] == second["nontiming_sha256"]
    assert first["checkpoints"][-1]["training_steps"] == 100
    assert all(row["frozen_state_unchanged"] for row in first["checkpoints"])
    assert digest(without_timing(first)) == first["nontiming_sha256"]


def test_protocol_changes_separate_factors():
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    baseline = protocol["baseline"]
    for condition in protocol["conditions"][1:]:
        assert sum(condition[k] != v for k, v in baseline.items()) == 1
    assert not protocol["confirmatory"]["enabled"]
