"""Auditor rejects corrupted shadows on a synthetic fixed-history fixture."""
from copy import deepcopy
import json

import pytest
from experiments.diagnostics.ac0_applicability_shadow import (
    POLICIES, PROTOCOL, analyze, audit_output, digest,
)


@pytest.fixture(scope='module')
def fixture_result():
    # Artificial unit receipts, no world/model or experimental task generation.
    view = {'channel_id': 'ch', 'observation_id': 'cue',
            'available_operations': ['a', 'b'], 'goal_observation_id': 'goal'}
    forecasts = [{'gen_id': 'old', 'operation_id': 'a', 'predicted_observation': 'goal'},
                 {'gen_id': 'new', 'operation_id': 'a', 'predicted_observation': 'other'}]
    def receipt(run_id, i):
        return {'run_id': run_id, 'event_id': str(i), 'channel_id': 'ch',
                'observation_id': 'cue', 'available_operations': ['a', 'b'],
                'chosen_operation': 'a', 'completion': 'success' if i < 32 else 'observed_divergence',
                'actual_observation': 'goal' if i < 32 else 'other'}
    source = {'runs': [{'seed': 41}, {'seed': 42}], 'training': []}
    replay = {'runs': []}
    for seed in (41, 42):
        source['training'].append({'seed': seed, 'events': [receipt(f'train{seed}', i) for i in range(96)]})
        replay['runs'].append({'seed': seed, 'records': [
            {'episode_index': i, 'case': {'block_index': i // 32},
             'public_view': view, 'readout_query': {'operation_id': None, 'forecasts': forecasts},
             'live_after_cue': [{'gen_id': 'old', 'cursor': 1, 'completed': False},
                                {'gen_id': 'new', 'cursor': 1, 'completed': False}],
             'saved_event': receipt(f'eval{seed}', i),
             'feedback': {'admitted': i != 20}} for i in range(128)]})
    config = json.loads(PROTOCOL.read_bytes())
    result = analyze(source, replay, config)
    assert result['status'] == 'shadow_analysis_complete_not_policy_rollout'
    return result, source, replay


def test_recorded_shadow_audit_passes_fixed_unit_fixture(fixture_result):
    result, source, replay = fixture_result
    assert audit_output(result, source, replay)['checked_queries'] == 1024


@pytest.mark.parametrize('tamper', ['future_history', 'counterfactual', 'invented_Gen',
                                    'summary', 'admission', 'missing_policy', 'metric_label'])
def test_auditor_rejects_measurement_tampering(fixture_result, tamper):
    original, source, replay = fixture_result
    result = deepcopy(original)
    row = result['runs'][0]['records'][0]
    if tamper == 'future_history':
        row['history_before_digest'] = 'current-outcome-used-too-early'
    elif tamper == 'counterfactual':
        row['policies'][0]['grade']['choice_outcome']['actual_observation'] = 'goal'
    elif tamper == 'invented_Gen':
        p = row['policies'][2]
        p['query']['forecasts'].append({'gen_id': 'invented', 'operation_id': 'a', 'predicted_observation': 'goal'})
        p['pre_outcome_digest'] = digest(p['query'])
    elif tamper == 'summary':
        result['summary'][0]['raw_abstentions'] += 1
    elif tamper == 'admission':
        result['runs'][0]['records'][20]['receipt_admitted'] = True
    elif tamper == 'missing_policy':
        row['policies'].pop()
    else:
        p = row['policies'][0]
        p['query']['conflicting_operations'] = 0
        p['pre_outcome_digest'] = digest(p['query'])
    with pytest.raises(ValueError):
        audit_output(result, source, replay)

