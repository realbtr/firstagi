"""Saved-data cross-check and tamper rejection; never instantiate learner/world."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from experiments.diagnostics.ac0_forecast_gap_audit import audit
from experiments.diagnostics.ac0_forecast_gap_replay import DEFAULT


@pytest.fixture(scope='module')
def saved():
    replay_path = DEFAULT.parent / 'forecast_gap_replay_20261031T0737.json'
    return json.loads(replay_path.read_bytes()), json.loads(DEFAULT.read_bytes())


def test_saved_audit_joins_threshold_actual_creation_and_later_reuse(saved, monkeypatch):
    monkeypatch.setattr('experiments.diagnostics.ac0_forecast_gap_replay.ReplayObserver',
                        lambda *a, **k: pytest.fail('recorded-data audit must not instantiate learner'))
    result = audit(*saved)
    assert result['matched_queries'] == 128 and result['missing_chain_cases'] == 4
    assert result['distinct_chains'] == 2 and result['original_rollout_status'] == 'incomplete_unchanged'
    summaries = result['threshold_then_creation_then_reuse']
    assert [(s['original_Gen_birth']['episode'], s['first_later_correct_nonfallback_episode']) for s in summaries] == [(98,106),(112,120)]
    assert result['new_world_actions'] == result['new_model_tokens'] == 0


@pytest.mark.parametrize('kind', ['threshold', 'existing_chain', 'future_receipt', 'encoding', 'token', 'incomplete_upgrade', 'semantic'])
def test_reject_tampered_evidence_without_new_execution(saved, kind):
    replay, source = saved
    original_inspection = replay['inspections'][0]
    original_record = replay['records'][0]
    original_token = replay['token_trace'][0]
    old_scope = replay['original_execution_completion']
    source_record = source['runs'][1]['policies'][2]['records'][96]
    old_deltas = source_record['pre_outcome']['begin']['begin_gen_deltas']
    replay['inspections'][0] = deepcopy(original_inspection)
    replay['records'][0] = deepcopy(original_record)
    replay['token_trace'][0] = deepcopy(original_token)
    try:
        inspection = replay['inspections'][0]
        if kind == 'threshold':
            inspection['native']['desired_candidate_count'] = 2
        elif kind == 'existing_chain':
            source_record['pre_outcome']['begin']['begin_gen_deltas'] = [*old_deltas,
                {'gen_id':'fabricated_existing','before':None,'after':{'feature_chain':inspection['native']['desired_chain'],
                 'success_count':2,'stop_count':0,'variation_count':0}}]
        elif kind == 'future_receipt':
            inspection['past_executed_key_receipts'].append({'stage':'evaluation','event_index':96,'event':{},'admitted':True})
        elif kind == 'encoding':
            inspection['native']['features'][0]['unique_expected_origin'] = False
        elif kind == 'token':
            replay['token_trace'][0]['canonical_feature_id'] = 'invented'
        elif kind == 'incomplete_upgrade':
            replay['original_execution_completion'] = 'complete'
        else:
            replay['records'][0]['raw_semantic_digest'] = 'invented'
        with pytest.raises(ValueError):
            audit(replay, source)
    finally:
        replay['inspections'][0] = original_inspection
        replay['records'][0] = original_record
        replay['token_trace'][0] = original_token
        replay['original_execution_completion'] = old_scope
        source_record['pre_outcome']['begin']['begin_gen_deltas'] = old_deltas
