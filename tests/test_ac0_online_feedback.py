"""Native feedback-boundary regressions; development tasks only."""
from copy import deepcopy
from dataclasses import replace
import json

import pytest

from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld
from experiments.diagnostics.ac0_kernel_binding import CodedKernelObserver
from experiments.diagnostics.ac0_recall_ablation import model_fingerprint
from experiments.diagnostics.ac0_online_feedback import (
    AdaptiveTable, Budget, NativePolicy, deliver_feedback, protocol,
    run_development, state_delta, write_development,
)
from experiments.diagnostics.ac0_frozen_goal import BoundaryError


def pending(status=None):
    world = TwoChannelWorld(41, 'unit-feedback')
    observer = CodedKernelObserver()
    channel = world.channels[0]
    view = {**world.view(channel), 'goal_observation_id': world._targets[channel]}
    observer.begin(view, recall_policy='exact_learned_prefix')
    event = world.act(channel, view['available_operations'][0], forced_status=status)
    return observer, view, event


@pytest.mark.parametrize('status', ['interrupted', 'unavailable', 'cancelled'])
@pytest.mark.parametrize('admitted', [True, False])
def test_unknown_preserves_post_begin_native_snapshot(status, admitted):
    observer, _, event = pending(status)
    before = model_fingerprint(observer)
    row = deliver_feedback(observer, event, admitted=admitted)
    assert row['native_before'] == row['native_after'] == before
    assert not row['assimilated'] and row['tokens'] == [] and row['gen_deltas'] == []
    assert not observer.event_pending
    assert (event.run_id, event.event_id) in observer.seen
    assert event.completion == status and event.actual_observation is None


def test_withheld_observed_keeps_real_receipt_and_no_native_update():
    observer, _, event = pending()
    assert event.actual_observation is not None
    before = model_fingerprint(observer)
    original = deepcopy(event)
    row = deliver_feedback(observer, event, admitted=False)
    assert event == original
    assert row['actual_completion'] in {'success', 'observed_divergence'}
    assert row['native_unchanged'] and not row['assimilated']
    assert row['native_before'] == before and row['tokens'] == []
    assert not observer.event_pending


def test_admitted_observed_routes_two_actual_tokens_through_existing_core():
    observer, _, event = pending()
    before_steps = observer.system.engine.step_count
    row = deliver_feedback(observer, event, admitted=True)
    assert row['assimilated'] and not row['native_unchanged']
    assert observer.system.engine.step_count == before_steps + 2
    assert [x['role'] for x in row['tokens']] == ['cue_to_operation', 'operation_to_observation']
    origins = set().union(*observer.provenance.values())
    assert ('operation_to_observation', event.channel_id,
            event.chosen_operation, event.actual_observation) in origins


@pytest.mark.parametrize('admitted', [True, False])
def test_duplicate_rejected_before_any_native_change(admitted):
    observer, _, event = pending()
    deliver_feedback(observer, event, admitted=admitted)
    before = model_fingerprint(observer)
    with pytest.raises(ValueError, match='duplicate'):
        deliver_feedback(observer, event, admitted=True)
    assert model_fingerprint(observer) == before


def test_wrong_cue_and_malformed_unknown_reject_before_bookkeeping():
    observer, _, event = pending()
    before = model_fingerprint(observer)
    for bad in (replace(event, observation_id='other'),
                replace(event, completion='cancelled'),
                replace(event, chosen_operation='unavailable')):
        with pytest.raises(ValueError):
            deliver_feedback(observer, bad, admitted=False)
        assert model_fingerprint(observer) == before
        assert observer.event_pending and observer.seen == set()


def test_table_only_updates_executed_observed_admitted_key():
    _, view, event = pending()
    table = AdaptiveTable([])
    table.update(event, admitted=False)
    assert table.values == {}
    _, _, event2 = pending()
    event2 = replace(event2, run_id='another')
    table.update(event2, admitted=True)
    assert table.values == {(event.channel_id, event.observation_id,
                             event.chosen_operation): event.actual_observation}
    before = deepcopy(table.values)
    _, _, unknown = pending('interrupted')
    unknown = replace(unknown, run_id='unknown')
    table.update(unknown, admitted=True)
    assert table.values == before
    with pytest.raises(ValueError, match='duplicate'):
        table.update(unknown, admitted=True)
    with pytest.raises(ValueError, match='public'):
        table.query({**view, 'block_index': 1})


def test_frozen_policy_ingests_no_cues_or_feedback():
    observer, view, event = pending()
    deliver_feedback(observer, event, admitted=True)
    observer.system.reset_context()
    policy = NativePolicy(observer, online=False, limits=protocol()['budgets'])
    budget = Budget(protocol()['budgets'])
    before = policy.full_digest()
    query, begin = policy.query(view, budget)
    policy.feedback(event, admitted=True, budget=budget)
    assert begin['cue_token'] is None
    assert policy.full_digest() == before
    assert budget.counts['all_core_tokens'] == 0
    assert query['core_tokens'] == 0
    with pytest.raises(ValueError, match='public'):
        policy.query({**view, 'oracle_operation': event.chosen_operation}, budget)


def test_reserved_or_consumed_seed_rejected_before_training(monkeypatch):
    def forbidden(*args):
        pytest.fail('task training must not start')
    monkeypatch.setattr('experiments.diagnostics.ac0_online_feedback.traced_training', forbidden)
    for seeds in ((201, 202), (101, 102), (41,)):
        with pytest.raises(ValueError, match='development'):
            run_development(seeds=seeds)


def test_budget_failure_does_not_commit_counter_charge():
    limits = protocol()['budgets']
    limits['max_all_core_tokens_total'] = 1
    budget = Budget(limits)
    budget.charge('train_core_tokens')
    before = dict(budget.counts)
    with pytest.raises(BoundaryError):
        budget.charge('all_core_tokens')
    assert budget.counts == before


def test_fresh_output_companions_and_incomplete_receipt(tmp_path):
    path = tmp_path / 'run.json'
    budget = Budget(protocol()['budgets'])
    result = {'status': 'incomplete', 'error': 'injected'}
    receipt = write_development(path, result, budget)
    assert receipt['status'] == 'incomplete'
    assert json.loads(path.read_bytes()) == result
    assert path.with_suffix('.json.sha256').exists()
    with pytest.raises(FileExistsError):
        write_development(path, result, budget)


def test_named_delta_keeps_counter_change_distinct_from_birth():
    before = {'g1': {'success_count': 2, 'stop_count': 1}}
    after = {'g1': {'success_count': 2, 'stop_count': 2}, 'g2': {'success_count': 0}}
    rows = state_delta(before, after)
    assert rows[0]['before']['stop_count'] == 1
    assert rows[0]['after']['stop_count'] == 2
    assert rows[1]['before'] is None

