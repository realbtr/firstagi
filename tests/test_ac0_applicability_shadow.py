"""Information boundaries for read-only shadows; synthetic receipt fixtures."""
from copy import deepcopy

import pytest
from experiments.diagnostics.ac0_applicability_shadow import (
    ActualHistory, POLICIES, analyze, grade_saved_execution, shadow_queries,
)

VIEW = {'channel_id': 'ch', 'observation_id': 'cue',
        'available_operations': ['a', 'b'], 'goal_observation_id': 'goal'}


def event(actual='goal', *, status='success', op='a', event_id='e1', channel='ch'):
    return {'run_id': 'synthetic-unit', 'event_id': event_id, 'channel_id': channel,
            'observation_id': 'cue', 'available_operations': ['a', 'b'],
            'chosen_operation': op, 'actual_observation': actual, 'completion': status}


def f(gid, op, actual):
    return {'gen_id': gid, 'operation_id': op, 'predicted_observation': actual}


def test_seal_before_current_receipt_and_then_update_future_query():
    history = ActualHistory()
    history.ingest(event(), admitted=True)
    forecasts = [f('old', 'a', 'goal'), f('new', 'a', 'other')]
    before = history.fingerprint()
    queries, _ = shadow_queries(VIEW, forecasts, [], history)
    assert queries[2]['forecasts'] == [forecasts[0]]
    assert history.fingerprint() == before
    # This actual event is unavailable to the query already returned.
    history.ingest(event('other', status='observed_divergence', event_id='e2'), admitted=True)
    assert queries[2]['forecasts'] == [forecasts[0]]
    later, _ = shadow_queries(VIEW, forecasts, [], history)
    assert later[2]['forecasts'] == [forecasts[1]]


@pytest.mark.parametrize('status', ['interrupted', 'unavailable', 'cancelled'])
def test_unknown_never_overwrites_prior_actual(status):
    history = ActualHistory()
    history.ingest(event(), admitted=True)
    before = history.fingerprint()
    assert not history.ingest(event(None, status=status, event_id='unknown'), admitted=True)
    assert history.fingerprint() == before


def test_withheld_observed_stays_observed_and_cannot_replace_context():
    history = ActualHistory()
    history.ingest(event(), admitted=True)
    e = event('other', status='observed_divergence', event_id='withheld')
    original = deepcopy(e)
    before = history.fingerprint()
    assert not history.ingest(e, admitted=False)
    assert history.fingerprint() == before and e == original


def test_duplicate_and_invalid_receipt_rejected_before_history_mutation():
    history = ActualHistory()
    e = event()
    history.ingest(e, admitted=True)
    before = history.fingerprint()
    for bad in (e, event(op='unavailable', event_id='bad-op'),
                event(None, status='success', event_id='bad-actual')):
        with pytest.raises(ValueError):
            history.ingest(bad, admitted=True)
        assert history.fingerprint() == before


def test_context_isolated_by_channel_cue_and_executed_operation():
    history = ActualHistory()
    history.ingest(event(), admitted=True)
    history.ingest(event('other', op='b', event_id='e2'), admitted=True)
    history.ingest(event('foreign', event_id='e3', channel='another'), admitted=True)
    assert history.values[('ch', 'cue', 'a')] == 'goal'
    assert history.values[('ch', 'cue', 'b')] == 'other'
    assert history.values[('another', 'cue', 'a')] == 'foreign'


def test_mask_cannot_synthesize_missing_Gen_forecast_from_table():
    history = ActualHistory()
    history.ingest(event(), admitted=True)
    queries, coverage = shadow_queries(VIEW, [], [], history)
    assert queries[2]['operation_id'] is None and queries[2]['forecasts'] == []
    assert queries[3]['operation_id'] == 'a'
    assert coverage['table_goal_eligible_keys'] == 1
    assert coverage['Gen_covered_table_goal_keys'] == 0


def test_no_receipt_is_not_evidence_to_remove_a_forecast():
    forecasts = [f('g1', 'a', 'goal'), f('g2', 'a', 'other')]
    before = deepcopy(forecasts)
    queries, _ = shadow_queries(VIEW, forecasts, [], ActualHistory())
    assert queries[2]['forecasts'] == before and queries[2]['operation_id'] is None
    assert forecasts == before


def test_live_filter_uses_real_cursor_and_does_not_treat_completed_as_prediction():
    forecasts = [f('live', 'a', 'goal'), f('waiting', 'a', 'other'), f('done', 'b', 'goal')]
    live = [{'gen_id': 'live', 'cursor': 1, 'completed': False},
            {'gen_id': 'waiting', 'cursor': 2, 'completed': False},
            {'gen_id': 'done', 'cursor': 3, 'completed': True}]
    queries, _ = shadow_queries(VIEW, forecasts, live, ActualHistory())
    assert queries[1]['forecasts'] == [forecasts[0]]


def test_hidden_case_fields_rejected():
    with pytest.raises(ValueError, match='public'):
        shadow_queries({**VIEW, 'block_index': 3}, [], [], ActualHistory())


def test_unexecuted_choice_and_forecast_remain_unknown_even_when_actual_is_goal():
    query = {'operation_id': 'b', 'forecasts': [f('a', 'a', 'goal'), f('b', 'b', 'goal')]}
    grade = grade_saved_execution(query, event())
    assert grade['forecast_support'] == ['positive', 'unknown']
    assert grade['choice_outcome'] == {'status': 'unknown', 'reason': 'not_executed', 'actual_observation': None}


def test_observed_divergence_can_confirm_a_dynamics_forecast_without_task_success():
    query = {'operation_id': 'a', 'forecasts': [f('g', 'a', 'other')]}
    grade = grade_saved_execution(query, event('other', status='observed_divergence'))
    assert grade['forecast_support'] == ['positive']
    assert 'goal_success' not in grade


def test_reserved_pool_rejected_before_receipt_history_creation(monkeypatch):
    def forbidden():
        pytest.fail('history must not be consumed')
    monkeypatch.setattr('experiments.diagnostics.ac0_applicability_shadow.ActualHistory', forbidden)
    with pytest.raises(ValueError, match='41/42'):
        analyze({'runs': [{'seed': 201}]}, {'runs': [{'seed': 201}]},
                {'task_seeds': [201], 'policies': list(POLICIES)})

