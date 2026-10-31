"""Boundary regressions without running the scheduled development study."""
from copy import deepcopy
from dataclasses import asdict, replace

import pytest

from experiments.diagnostics.ac0_applicability_on_policy import (
    Budget, Controller, causal_links, full_state_fingerprint, protocol, register_changes, run_development, write_output,
)
from experiments.diagnostics.ac0_applicability_shadow import ActualHistory, shadow_queries
from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld
from experiments.diagnostics.ac0_frozen_goal import BoundaryError
from experiments.diagnostics.ac0_kernel_binding import CodedKernelObserver


def fixture(name='prefix_actual_context_online', status=None):
    budget = Budget(protocol()['budgets'])
    controller = Controller(name, CodedKernelObserver(), {'events': []}, budget)
    world = TwoChannelWorld(41, 'on-policy-unit')
    channel = world.channels[0]
    view = {**world.view(channel), 'goal_observation_id': world._targets[channel]}
    query = controller.query(view)
    event = world.act(channel, view['available_operations'][0], forced_status=status)
    return controller, view, query, event


@pytest.mark.parametrize('status', ['interrupted', 'unavailable', 'cancelled', None])
@pytest.mark.parametrize('admitted', [True, False])
def test_feedback_guards_and_duplicate_before_charge(status, admitted):
    controller, _, _, event = fixture(status=status)
    old_history = controller.history.fingerprint()
    row = controller.feedback(event, admitted=admitted)
    if status or not admitted:
        assert controller.history.fingerprint() == old_history
        assert row['native']['native_unchanged']
        assert row['native']['tokens'] == []
    else:
        assert controller.history.fingerprint() != old_history
        assert len(row['native']['tokens']) == 2
    before = deepcopy(controller.budget.counts)
    state = controller.native.full_digest()
    with pytest.raises(ValueError, match='duplicate'):
        controller.feedback(event, admitted=True)
    assert controller.budget.counts == before
    assert controller.native.full_digest() == state


def test_own_history_training_copy_and_executed_key_only():
    a, view, _, event = fixture('table_online')
    b, _, _, _ = fixture('table_online')
    a.feedback(event, admitted=True)
    assert b.history.values == {} and b.receipts == set()
    assert a.history.values == {(event.channel_id, event.observation_id, event.chosen_operation): event.actual_observation}
    assert a.query(view)['history_before_digest'] != b.query(view)['history_before_digest']
    assert a.storage()['history_receipt_ids'] == 1
    assert a.storage()['delivery_receipt_ids'] == 1
    parts = a.storage()
    assert parts['serialized_all_stores_bytes'] == sum(parts[k] for k in (
        'observer_bytes', 'native_receipt_ids_bytes', 'actual_history_bytes_including_ids', 'delivery_receipt_ids_bytes'))


def test_future_or_oracle_fields_rejected_and_malformed_event_transactional():
    controller, view, _, event = fixture()
    with pytest.raises(ValueError, match='public'):
        controller.query({**view, 'phase': 1})
    before = controller.native.full_digest()
    with pytest.raises(ValueError):
        controller.feedback(replace(event, completion='cancelled'), admitted=True)
    assert controller.native.full_digest() == before
    assert controller.receipts == set() and controller.history.seen == set()


def test_missing_gen_never_synthesized_from_history():
    controller, view, _, event = fixture('table_online')
    history = ActualHistory()
    event = replace(event, actual_observation=view['goal_observation_id'])
    history.ingest(asdict(event), admitted=True)
    variants, coverage = shadow_queries(view, [], [], history)
    assert variants[2]['forecasts'] == [] and variants[2]['operation_id'] is None
    assert variants[3]['operation_id'] == event.chosen_operation
    assert coverage['Gen_covered_table_goal_keys'] == 0


def test_mask_retains_original_without_history_and_filters_only_known_key():
    _, view, _, event = fixture('table_online')
    forecasts = [{'gen_id': 'old', 'operation_id': event.chosen_operation, 'predicted_observation': 'old'},
                 {'gen_id': 'actual', 'operation_id': event.chosen_operation, 'predicted_observation': event.actual_observation},
                 {'gen_id': 'other', 'operation_id': view['available_operations'][1], 'predicted_observation': 'other'}]
    history = ActualHistory()
    assert shadow_queries(view, forecasts, [], history)[0][2]['forecasts'] == forecasts
    history.ingest(asdict(event), admitted=True)
    assert [r['gen_id'] for r in shadow_queries(view, forecasts, [], history)[0][2]['forecasts']] == ['actual', 'other']


def test_reserved_pool_rejected_before_training(monkeypatch):
    monkeypatch.setattr('experiments.diagnostics.ac0_applicability_on_policy.traced_training',
                        lambda *args: pytest.fail('training must not start'))
    for seeds in ((201, 202), (101, 102), (41,), (42, 41)):
        with pytest.raises(ValueError, match='development'):
            run_development(seeds=seeds)


def test_transactional_budget_and_complete_wall():
    limits = protocol()['budgets']
    limits['max_all_core_tokens'] = 1
    budget = Budget(limits)
    budget.charge('train_core_tokens')
    before = dict(budget.counts)
    with pytest.raises(BoundaryError):
        budget.charge('all_core_tokens')
    assert budget.counts == before
    ticks = iter([0, 61])
    with pytest.raises(BoundaryError, match='wall'):
        Budget(protocol()['budgets'], lambda: next(ticks)).check()


def test_partial_and_companion_outputs_are_preserved(tmp_path):
    out = tmp_path / 'partial.json'
    result = {'status': 'incomplete', 'error': 'injected'}
    receipt = write_output(out, result, Budget(protocol()['budgets']))
    assert receipt['status'] == 'incomplete' and out.exists()
    with pytest.raises((ValueError, FileExistsError)):
        write_output(out, result, Budget(protocol()['budgets']))


def test_stop_only_not_positive_update_and_missing_witness_rejected():
    state = {'feature_chain': ['f'], 'success_count': 1, 'stop_count': 1}
    updates = []
    register_changes(updates, [{'gen_id': 'g', 'before': state, 'after': {**state, 'stop_count': 2}}],
                     episode=0, stage='feedback', witnesses={})
    assert updates == []
    with pytest.raises(ValueError, match='witness'):
        register_changes(updates, [{'gen_id': 'g', 'before': None, 'after': state}],
                         episode=0, stage='feedback', witnesses={})


def test_causal_link_requires_prior_own_correct_nonfallback_and_changed_actual_witness():
    f = {'gen_id': 'g', 'gen_chain': ['f'], 'operation_id': 'op',
         'predicted_observation': 'goal', 'outcome_feature_id': 'f'}
    witness = {'canonical_feature_id': 'f', 'episode_index': 0,
               'channel_id': 'ch', 'source': 'op', 'target': 'goal'}
    update = {'gen_id': 'g', 'episode_index': 0, 'stage': 'feedback',
              'state_delta': {'after': {'feature_chain': ['f']}}, 'feature_witnesses': [witness]}
    row = {'goal_reached': True, 'fallback': False, 'case': {'episode_index': 1, 'channel_index': 0, 'block_index': 1},
           'event': {'chosen_operation': 'op', 'actual_observation': 'goal', 'channel_id': 'ch'},
           'pre_outcome': {'selected_query': {'forecasts': [f]}}}
    records = [{**row, 'goal_reached': None, 'case': {**row['case'], 'episode_index': 0}}, row]
    assert causal_links(records, [update])[0]['changed_channel_actual_witness']
    assert causal_links(records, [{**update, 'episode_index': 1}]) == []
    assert causal_links([records[0], {**row, 'fallback': True}], [update]) == []
    assert not causal_links(records, [{**update, 'feature_witnesses': [{**witness, 'episode_index': -1}]}])[0]['changed_channel_actual_witness']


def test_complete_graph_guard_ignores_unordered_insertion_but_detects_runtime_and_aliases():
    a = CodedKernelObserver()
    a.seen = {('run', str(i)) for i in range(96)}
    b = deepcopy(a)
    b.seen = set(reversed(list(a.seen)))
    assert full_state_fingerprint(a) == full_state_fingerprint(b)
    b.system.engine._step_count += 1
    assert full_state_fingerprint(a) != full_state_fingerprint(b)
    shared = []
    assert full_state_fingerprint([shared, shared]) != full_state_fingerprint([[], []])
    assert full_state_fingerprint({'b': {1, 2}, 'a': 3}) == full_state_fingerprint({'a': 3, 'b': {2, 1}})
    with pytest.raises(TypeError, match='unsupported'):
        full_state_fingerprint(object())
