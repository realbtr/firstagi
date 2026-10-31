from copy import deepcopy
from drivers.text_driver import TextDriver
from experiments.diagnostics.ac0_event_baseline import CoreObserver,TwoChannelWorld
from experiments.diagnostics.ac0_proposal_readiness import (
    alias_counterexample,audit_run,inspect_decoding,
)


def test_diagnostic_detects_distinct_operation_alias_not_a_unique_command():
    result=alias_counterexample()
    assert result['view']['available_operations'][0]!=result['view']['available_operations'][1]
    assert 'distinct_operations_have_identical_features' in result['blockers']
    assert result['candidate_pair_distance']==0


def test_candidate_inspection_does_not_mutate_vocabulary_or_kernel():
    world,observer=TwoChannelWorld(41),CoreObserver()
    channel=world.channels[0]
    observer.observe(world.act(channel,world.operations[0]))
    driver=observer.drivers[channel]
    vocab=deepcopy(driver._vocab)
    steps=observer.system.engine.step_count
    stats=observer.system.initiative.stats()
    result=inspect_decoding(world.view(channel),driver,observer.system)
    assert driver._vocab==vocab
    assert observer.system.engine.step_count==steps
    assert observer.system.initiative.stats()==stats
    assert result['unknown_symbols']


def test_uninitialized_driver_is_reported_without_initializing_from_first_action():
    world,observer=TwoChannelWorld(42),CoreObserver()
    driver=TextDriver(world.channels[0])
    result=inspect_decoding(world.view(world.channels[0]),driver,observer.system)
    assert result['blockers']==['driver_vocabulary_uninitialized']
    assert not driver._vocab


def test_fresh_context_comparison_uses_existing_expected_features():
    world,observer=TwoChannelWorld(41),CoreObserver()
    channel=world.channels[0]
    observer.observe(world.act(channel,world.operations[0]))
    result=inspect_decoding(world.view(channel),observer.drivers[channel],observer.system)
    expected=observer.system.engine.context.get_expected_features(observer.system.base)
    assert result['current_expected_count']==len(set(expected.values()))
    assert not result['cached_matches_current_feature_set']
    assert 'cached_proposals_do_not_match_current_context' in result['blockers']


def test_diagnostic_actions_remain_fixture_actions_without_oracle_access(monkeypatch):
    def forbidden(*args,**kwargs):
        raise AssertionError('audit must not query oracle')
    monkeypatch.setattr(TwoChannelWorld,'oracle_operation',forbidden)
    result=audit_run(41,'random',12)
    assert result['completed_observations']==9
    assert result['attempts']==12
    assert len(result['records'])==12
