"""Recorded-data audit must reject tampered measurement, not just valid JSON."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from experiments.diagnostics.ac0_online_audit import audit

RAW = Path(__file__).resolve().parents[1] / 'experiments/reports/ac0_debug/online_feedback/v1/development_41_42_20261030T2334.json'


@pytest.fixture(scope='module')
def recorded():
    return json.loads(RAW.read_bytes())


def test_recorded_development_consistency_and_missing_changed_reuse(recorded):
    result = audit(recorded)
    assert result['counts']['evaluation_records'] == 2304
    assert result['counts']['named_negative_native_stop_delta'] > 0
    assert result['counts']['changed_channel_update_then_correct_reuse'] == 0


@pytest.mark.parametrize('tamper', ['goal_score', 'actual', 'view', 'admission', 'guard', 'window'])
def test_audit_rejects_corrupted_measurement(recorded, tamper):
    data = deepcopy(recorded)
    row = data['runs'][0]['policies'][0]
    r = row['records'][0]
    if tamper == 'goal_score':
        r['goal_reached'] = not r['goal_reached']
    elif tamper == 'actual':
        r['event']['actual_observation'] = 'fabricated'
    elif tamper == 'view':
        r['public_view']['oracle_operation'] = 'leak'
    elif tamper == 'admission':
        r['feedback']['admitted'] = False
    elif tamper == 'guard':
        r = next(x for x in row['records'] if x['event']['completion'] == 'interrupted')
        r['feedback']['native_unchanged'] = False
    else:
        row['windows']['block3_channel0']['goal_rate'] = 1.0
    with pytest.raises(ValueError):
        audit(data)

