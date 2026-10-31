from dataclasses import asdict
import copy
import pytest
from experiments.diagnostics.ac0_event_baseline import (
    CoreObserver, TwoChannelWorld, run_debug, validate_trace,
)


@pytest.mark.parametrize('status', ['interrupted', 'unavailable', 'cancelled'])
def test_unknown_preserves_pending_cue_and_does_not_feed_core(status):
    world, observer = TwoChannelWorld(41), CoreObserver()
    channel = world.channels[0]
    before = world.view(channel)
    event = world.act(channel, world.oracle_operation(channel), forced_status=status)
    assert event.prediction_support == 'unknown'
    assert event.actual_observation is None
    assert world.view(channel) == before
    assert observer.observe(event)['processed_tokens'] == 0
    assert observer.system.base.size() == 0
    resumed = world.act(channel, world.oracle_operation(channel))
    assert resumed.completion == 'success'
    assert resumed.causal_parents == (event.event_id,)
    assert observer.observe(resumed)['processed_tokens'] > 0


def test_external_failure_is_observed_and_not_unknown():
    world = TwoChannelWorld(41)
    channel = world.channels[0]
    wrong = next(op for op in world.operations if op != world.oracle_operation(channel))
    event = world.act(channel, wrong)
    assert event.completion == 'observed_divergence'
    assert event.prediction_support == 'negative'
    assert event.actual_observation != event.expected_observation
    validate_trace([asdict(event)])


def test_observer_rejects_duplicate_evidence_before_second_update():
    world, observer = TwoChannelWorld(42), CoreObserver()
    channel = world.channels[0]
    event = world.act(channel, world.oracle_operation(channel))
    observer.observe(event)
    steps = observer.system.engine.step_count
    with pytest.raises(ValueError, match='duplicate event'):
        observer.observe(event)
    assert observer.system.engine.step_count == steps


def test_controller_view_does_not_disclose_answers_or_task_targets():
    world = TwoChannelWorld(41)
    assert set(world.view(world.channels[0])) == {
        'channel_id', 'observation_id', 'available_operations'}


def test_trace_rejects_cross_channel_parent_and_coerced_unknown():
    world = TwoChannelWorld(41)
    events = []
    for channel in world.channels:
        events.append(asdict(world.act(channel, world.oracle_operation(channel))))
    validate_trace(events)
    bad = copy.deepcopy(events)
    bad[1]['causal_parents'] = [bad[0]['event_id']]
    with pytest.raises(ValueError, match='causal chain'):
        validate_trace(bad)
    fresh = TwoChannelWorld(42)
    event = asdict(fresh.act(fresh.channels[0], fresh.operations[0],
                           forced_status='interrupted'))
    event['prediction_support'] = 'negative'
    with pytest.raises(ValueError, match='unknown must not'):
        validate_trace([event])


def test_oracle_upper_bound_and_equal_control_budgets():
    results = [run_debug(41, control, 12) for control in ('fixed', 'random', 'oracle')]
    assert all(r['operation_cost'] == r['attempt_budget'] == 12 for r in results)
    assert all(r['unknown_outcomes'] == 3 for r in results)
    oracle = results[-1]
    assert oracle['task_successes'] == oracle['observed_outcomes'] == 9
    assert all(r['gate_passed'] is False for r in results)
    for result in results:
        for event, update in zip(result['events'], result['core_updates']):
            if event['prediction_support'] == 'unknown':
                assert update['processed_tokens'] == 0
            assert update['gen_support_evaluated'] is False


def test_repeated_seed_reproduces_environment_not_random_kernel_ids():
    first = run_debug(42, 'random', 12)
    repeat = run_debug(42, 'random', 12)
    assert first['events'] == repeat['events']
    assert first['task_successes'] == repeat['task_successes']


def test_trace_rejects_success_claim_without_observed_success():
    world = TwoChannelWorld(41)
    event = asdict(world.act(world.channels[0], world.oracle_operation(world.channels[0])))
    event['completion'] = 'observed_divergence'
    with pytest.raises(ValueError, match='task verdict'):
        validate_trace([event])
