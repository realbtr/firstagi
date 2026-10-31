"""Diagnostic boundaries on small fixtures, without executing the saved replay."""
from copy import deepcopy
from pathlib import Path
import json

import pytest

from core.generalization import Generalization
from experiments.diagnostics.ac0_applicability_on_policy import full_state_fingerprint
from experiments.diagnostics.ac0_forecast_gap_replay import (
    DEFAULT, INPUT_SHA, ReplayObserver, candidate_delta, inspect_goal, replay,
    semantics, source_rows, write_output,
)
from experiments.diagnostics.ac0_frozen_goal import BoundaryError


def fixture():
    observer = ReplayObserver(0, clock=lambda: 0)
    view = {'channel_id': 'channel', 'observation_id': 'cue',
            'available_operations': ('left', 'right'), 'goal_observation_id': 'goal'}
    observer._ingest('channel', 'cue', 'cue', 'cue_anchor')
    observer._ingest('channel', 'cue', 'left', 'cue_to_operation')
    observer._ingest('channel', 'left', 'goal', 'operation_to_observation')
    observer.system.reset_context()
    return observer, view


def test_semantic_agreement_ignores_uuid_and_order_but_not_multiplicity():
    a = {'gen_id': 'one', 'gen_chain': ['f', 'g', 'h'], 'operation_id': 'op', 'predicted_observation': 'goal'}
    b = {**a, 'gen_id': 'two'}
    assert semantics([a, b]) == semantics([b, a])
    assert semantics([a]) == semantics([b])
    assert semantics([a]) != semantics([a, b])
    assert semantics([a]) != semantics([{**a, 'predicted_observation': 'other'}])


def test_candidate_delta_tracks_absent_zero_and_count_changes():
    assert candidate_delta({('x',): 1}, {('x',): 2, ('y',): 1}) == [
        {'chain': ['x'], 'before': 1, 'after': 2}, {'chain': ['y'], 'before': 0, 'after': 1}]
    assert candidate_delta({}, {('x',): 0}) == []


def test_registered_atoms_are_not_forecast_chain_and_inspection_is_readonly():
    observer, view = fixture()
    before = full_state_fingerprint(observer)
    result = inspect_goal(observer, view, 'left', {'forecasts': []}, {'forecasts': []})
    assert result['classification'] == 'missing_native_forecast_chain'
    assert all(x['registered'] and x['canonical_match'] and x['unique_expected_origin'] for x in result['features'])
    assert result['stored_prefix_chains'] == []
    assert full_state_fingerprint(observer) == before


@pytest.mark.parametrize('kind', ['encoding', 'prefix_position', 'retrieval', 'eligibility', 'present'])
def test_distinguish_failure_stages_without_fabricating_real_forecast(kind):
    observer, view = fixture()
    first = inspect_goal(observer, view, 'left', {'forecasts': []}, {'forecasts': []})
    wanted = first['desired_chain']
    forecast = {'gen_chain': wanted, 'operation_id': 'left', 'predicted_observation': 'goal'}
    # Manual chains exist only in this synthetic unit fixture, never saved replay.
    if kind == 'encoding':
        observer.provenance[wanted[2]].add(('operation_to_observation', 'other', 'left', 'goal'))
    else:
        observer.system.base.add(Generalization.new(feature_chain=(['unrelated'] + wanted if kind == 'prefix_position' else wanted)))
    raw = [forecast] if kind in ('eligibility', 'present') else []
    selected = [forecast] if kind == 'present' else []
    result = inspect_goal(observer, view, 'left', {'forecasts': raw}, {'forecasts': selected})
    expected = {'encoding': 'feature_encoding_or_provenance_gap', 'prefix_position': 'prefix_position_gap',
                'retrieval': 'verified_retrieval_or_decode_gap', 'eligibility': 'actual_context_eligibility_gap',
                'present': 'forecast_present'}
    assert result['classification'] == expected[kind]


def test_budget_failure_precedes_next_native_token():
    observer = ReplayObserver(0, clock=lambda: 0, max_tokens=0)
    with pytest.raises(BoundaryError, match='token'):
        observer._ingest('ch', 'cue', 'cue', 'cue_anchor')
    assert observer.system.engine.step_count == 0
    observer = ReplayObserver(0, clock=lambda: 61)
    with pytest.raises(BoundaryError, match='wall'):
        observer._ingest('ch', 'cue', 'cue', 'cue_anchor')
    assert observer.system.engine.step_count == 0


@pytest.fixture(scope='module')
def saved():
    return json.loads(DEFAULT.read_bytes())


def test_source_preflight_only_pinned_known_pool_and_fixed_four_targets(saved, monkeypatch):
    training, policy = source_rows(saved)
    assert training['seed'] == 42 and len(policy['records']) == 128
    bad = {**saved, 'runs': [{**saved['runs'][0], 'seed': 201}, saved['runs'][1]]}
    monkeypatch.setattr('experiments.diagnostics.ac0_forecast_gap_replay.ReplayObserver',
                        lambda *a, **kw: pytest.fail('must reject before model creation'))
    with pytest.raises(ValueError, match='development'):
        replay(bad)
    with pytest.raises(ValueError, match='source'):
        replay({**saved, 'source_dirty': True})


def test_saved_source_sha_is_pinned_without_replaying_model():
    import hashlib
    assert hashlib.sha256(DEFAULT.read_bytes()).hexdigest() == INPUT_SHA


def test_partial_and_oversize_outputs_preserve_original_files(tmp_path):
    path = tmp_path / 'partial.json'
    result = {'status': 'incomplete', 'error': 'fixture'}
    receipt = write_output(path, result, 0, clock=lambda: 1)
    assert receipt['status'] == 'incomplete'
    with pytest.raises((ValueError, FileExistsError)):
        write_output(path, result, 0, clock=lambda: 1)
    large = tmp_path / 'large.json'
    receipt = write_output(large, {'status': 'finished', 'data': 'x' * 2097152}, 0, clock=lambda: 1)
    assert receipt['status'] == 'incomplete' and large.exists()
