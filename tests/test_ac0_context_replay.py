"""Census is observational; fixture Gens below are unit-test objects only."""
from copy import deepcopy
import hashlib
import pickle

import pytest
from core.generalization import Generalization
from experiments.diagnostics.ac0_context_replay import frontier_census, replay, forecast_signatures
from experiments.diagnostics.ac0_kernel_binding import CodedKernelObserver


def fixture_frontier():
    observer = CodedKernelObserver()
    view = {'channel_id': 'channel', 'observation_id': 'cue',
            'available_operations': ('op-a', 'op-b'), 'goal_observation_id': 'target'}
    chain = []
    for role, source, target in (('cue_anchor', 'cue', 'cue'),
                                ('cue_to_operation', 'cue', 'op-a'),
                                ('operation_to_observation', 'op-a', 'target')):
        feature = observer.codec.encode_role('channel', source, target, role)
        observer.system.engine.register_feature(feature)
        observer.provenance[feature.feature_id] = {(role, 'channel', source, target)}
        chain.append(feature.feature_id)
    gen = Generalization.new(feature_chain=chain)
    gen.success_count, gen.stop_count = 5, 2
    observer.system.base.add(gen)
    observer.system.engine.context.add_active(gen.gen_id)
    observer.system.engine.context._active[gen.gen_id].current_feature_index = 1
    return observer, view, gen


def test_census_preserves_full_state_and_real_cursor():
    observer, view, gen = fixture_frontier()
    before = hashlib.sha256(pickle.dumps(observer, protocol=5)).hexdigest()
    rows = frontier_census(observer, view)
    assert hashlib.sha256(pickle.dumps(observer, protocol=5)).hexdigest() == before
    assert len(rows) == 1 and rows[0]['gen_id'] == gen.gen_id
    assert rows[0]['cursor'] == 1 and rows[0]['expected_feature_id'] == gen.feature_chain[1]
    assert rows[0]['stop_count'] == 2 and not rows[0]['completed']


def test_completed_active_entry_is_not_a_current_operation_prediction():
    observer, view, gen = fixture_frontier()
    observer.system.engine.context._active[gen.gen_id].current_feature_index = 3
    row = frontier_census(observer, view)[0]
    assert row['completed'] and row['expected_feature_id'] is None
    assert row['cursor'] == 3


def test_census_excludes_ambiguous_or_wrong_channel_outcome_origin():
    observer, view, gen = fixture_frontier()
    observer.provenance[gen.feature_chain[2]].add(('operation_to_observation', 'foreign', 'op-a', 'target'))
    assert frontier_census(observer, view) == []
    observer.provenance[gen.feature_chain[2]] = {('operation_to_observation', 'foreign', 'op-a', 'target')}
    assert frontier_census(observer, view) == []


def test_semantic_signature_ignores_uuid_but_keeps_duplicate_contributors():
    a = {'gen_id': 'first', 'gen_chain': ['a', 'b', 'c'],
         'operation_id': 'op', 'predicted_observation': 'outcome'}
    b = {**a, 'gen_id': 'second'}
    assert forecast_signatures([a]) == forecast_signatures([b])
    assert forecast_signatures([a, b]) != forecast_signatures([a])


def test_reserved_pool_rejected_before_observer_construction(monkeypatch):
    def forbidden():
        pytest.fail('must reject before native ingestion')
    monkeypatch.setattr('experiments.diagnostics.ac0_context_replay.ReplayObserver', forbidden)
    with pytest.raises(ValueError, match='41/42'):
        replay({'runs': [{'seed': 201}, {'seed': 202}]})

