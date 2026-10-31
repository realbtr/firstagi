"""Tamper regressions on saved actual history; zero new model/world execution."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from experiments.diagnostics.ac0_applicability_shadow import digest
from experiments.diagnostics.ac0_on_policy_audit import audit


@pytest.fixture(scope='module')
def saved():
    path = Path(__file__).resolve().parents[1] / 'experiments/reports/ac0_debug/online_feedback/v1/on_policy_dev_20261031T0540.json'
    return json.loads(path.read_bytes())


def test_saved_rollout_consistent_but_original_completion_still_incomplete(saved):
    result = audit(saved)
    assert result['counts']['records'] == 1536
    assert result['counts']['changed_channel_causal_links'] == 58
    assert result['counts']['unknown_withheld_native_guards'] == 308
    assert result['new_world_actions'] == 0 and not result['AC0_gate_pass']
    path = Path(__file__).resolve().parents[1] / 'experiments/reports/ac0_debug/online_feedback/v1/on_policy_dev_20261031T0540.json.completion.json'
    receipt = json.loads(path.read_bytes())
    assert receipt['status'] == 'incomplete' and receipt['error'] == 'raw bytes budget exceeded'


@pytest.mark.parametrize('kind', ['seal', 'future_history', 'invented_Gen', 'unknown_native', 'receipt_ids', 'duplicate_event'])
def test_audit_rejects_tampering_without_rerunning_task(saved, kind):
    records = saved['runs'][0]['policies'][1]['records']
    index = next(i for i, r in enumerate(records) if r['event']['actual_observation'] is None) if kind == 'unknown_native' else 1
    original = records[index]
    row = deepcopy(original)
    records[index] = row
    try:
        if kind == 'seal':
            row['pre_outcome']['operation_id'] = 'fabricated'
        elif kind == 'future_history':
            row['pre_outcome']['history_before_digest'] = 'future'
            row['feedback']['history_before_digest'] = 'future'
        elif kind == 'invented_Gen':
            row['pre_outcome']['selected_query']['forecasts'].append(
                {'gen_id': 'invented', 'operation_id': row['event']['chosen_operation'],
                 'predicted_observation': row['event']['actual_observation']})
        elif kind == 'unknown_native':
            row['feedback']['native']['native_after'] = 'mutated'
        elif kind == 'receipt_ids':
            row['storage']['history_receipt_ids'] = 0
        else:
            row['event']['run_id'] = records[0]['event']['run_id']
        if kind != 'seal':
            row['pre_outcome_digest'] = digest(row['pre_outcome'])
        with pytest.raises(ValueError):
            audit(saved)
    finally:
        records[index] = original


def test_audit_rejects_later_update_relabelled_as_prior_reuse(saved):
    policy = saved['runs'][0]['policies'][1]
    link = policy['causal_links'][0]
    old = link['update_episode_index']
    try:
        link['update_episode_index'] = link['reuse_episode_index']
        with pytest.raises(ValueError, match='precede'):
            audit(saved)
    finally:
        link['update_episode_index'] = old
