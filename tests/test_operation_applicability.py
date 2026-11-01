"""A3 causal component checks, not an environment experiment or AC0 pass."""
import pickle
from dataclasses import replace

import pytest

from core.generalization import Generalization
from tests.test_operation_choice import encoded, view
from tests.test_operation_evidence import linked_system, receipt


def ready():
    system, atoms, gen = linked_system()
    encoded(system, atoms)
    return system, atoms, gen


def condition(system, gid, available, **scope):
    return system.set_operation_applicability(gid, instance_id=scope.get('instance_id', 'life'),
                                             channel_id=scope.get('channel_id', 'channel'),
                                             available=available)


def test_available_sham_block_restore_from_identical_checkpoint_and_input():
    system, atoms, gen = ready()
    frame = view(system, atoms)
    checkpoint = pickle.dumps((system, frame))
    results = []
    for arm in ('available', 'sham', 'blocked', 'restored'):
        copy, same_frame = pickle.loads(checkpoint)
        before = pickle.dumps(copy.base.get(gen.gen_id))
        features = pickle.dumps(copy.engine._features)
        copy.base.start_applicability_audit(5000)
        if arm == 'sham':
            assert not condition(copy, gen.gen_id, True)
        if arm in ('blocked', 'restored'):
            condition(copy, gen.gen_id, False)
        if arm == 'restored':
            condition(copy, gen.gen_id, True)
        assert pickle.dumps(copy.base.get(gen.gen_id)) == before
        assert pickle.dumps(copy.engine._features) == features
        proposal = copy.propose_operations(same_frame)
        trace = copy.base.finish_applicability_audit()
        positions = dict(copy.engine.context.active_positions())
        results.append(proposal.command_address if proposal else None)
        assert (gen.gen_id in positions) == (arm != 'blocked')
        if arm == 'blocked':
            assert any(gid == gen.gen_id and not allowed for _, gid, _, allowed in trace)
        else:
            assert any(gid == gen.gen_id and stage == 'load' and allowed
                       for _, gid, stage, allowed in trace)
    assert results == ['address-A', 'address-A', None, 'address-A']


def test_shared_guard_covers_load_read_scan_prefix_and_parent_child_expansion():
    system, atoms, gen = ready()
    context, base = system.engine.context, system.base
    parent = base.add(Generalization.new(feature_chain=['cue']))
    base.link(parent.gen_id, gen.gen_id)
    base.record_transition(parent.gen_id, gen.gen_id)
    condition(system, gen.gen_id, False)
    base.start_applicability_audit()
    with base.applicability_view('life', 'channel'):
        context.add_active(gen.gen_id, current_feature_index=1)
        context.add_competing(gen.gen_id)
        assert gen.gen_id not in context.active_gen_ids() + context.competing_gen_ids()
        # Even a stale/external raw context insertion cannot reveal an expectation.
        from core.context import ActiveGen
        context._active[gen.gen_id] = ActiveGen(gen.gen_id, 1)
        assert gen.gen_id not in context.get_expected_features(base)
        assert base.get(gen.gen_id) is None
        assert gen.gen_id not in {g.gen_id for g in base.all()}
        assert gen.gen_id not in {g.gen_id for g in base.rank()}
        assert gen.gen_id not in {g.gen_id for g in base.search_by_prefix(['cue'])}
        assert gen.gen_id not in {g.gen_id for g in base.search_by_chain(gen.feature_chain)}
        assert base.get(parent.child_ids[0]) is None
        assert base.get_transitions(parent.gen_id) == {}
        assert base.most_likely_next(parent.gen_id) is None
        context.prune_inapplicable(base)
        assert gen.gen_id not in context.active_gen_ids()
    system.engine.recall_operation_context(atoms['cue'], 'life', 'channel')
    assert gen.gen_id not in context.active_gen_ids()
    audit = base.finish_applicability_audit()
    assert {'load', 'read', 'scan', 'expand', 'context'} <= {
        stage for _, gid, stage, allowed in audit if gid == gen.gen_id and not allowed}
    assert base.get(gen.gen_id) is gen  # Visibility never deletes knowledge.
    assert parent.child_ids == [gen.gen_id]
    assert base.get_transitions(parent.gen_id) == {gen.gen_id: 1}


@pytest.mark.parametrize('restore', [False, True])
def test_condition_change_invalidates_saved_proposal_even_after_restore(restore):
    system, atoms, gen = ready()
    proposal = system.propose_operations(view(system, atoms))
    condition(system, gen.gen_id, False)
    if restore:
        condition(system, gen.gen_id, True)
    with pytest.raises(ValueError):
        system.begin_proposed_operation(proposal)
    assert not system._operation_pending


def test_redundant_sufficient_gen_and_parent_are_not_cascaded_into_knockout():
    system, atoms, gen = ready()
    # This clone is an explicit redundancy fixture, not independent evidence.
    alternative = pickle.loads(pickle.dumps(gen))
    alternative.gen_id = Generalization.new().gen_id
    system.base.add(alternative)
    system.base.link(alternative.gen_id, gen.gen_id)
    children_before = list(alternative.child_ids)
    condition(system, gen.gen_id, False)
    proposal = system.propose_operations(view(system, atoms))
    assert proposal.command_address == 'address-A'
    assert proposal.contributor_gen_ids == (alternative.gen_id,)
    pending = system.begin_proposed_operation(proposal)
    assert [f[0] for f in pending.forecasts] == [alternative.gen_id]
    assert alternative.child_ids == children_before and gen.gen_id in children_before


@pytest.mark.parametrize('foreign', [{'instance_id': 'foreign'}, {'channel_id': 'foreign'}])
def test_block_is_scoped_and_does_not_suppress_another_life_or_channel(foreign):
    system, atoms, gen = ready()
    condition(system, gen.gen_id, False, **foreign)
    assert system.propose_operations(view(system, atoms)).command_address == 'address-A'


def test_forced_command_cannot_reintroduce_blocked_forecasts_or_evidence():
    system, atoms, gen = ready()
    condition(system, gen.gen_id, False)
    pending = system.begin_operation(public_view=view(system, atoms), command_address='address-A')
    assert pending.forecasts == ()
    system.accept_operation_outcome(replace(receipt(atoms, 20), command_address='address-A'))
    assert gen.actual_positive_count == 2


def test_private_execution_primitive_cannot_bypass_guard_with_manual_id():
    system, atoms, gen = ready()
    condition(system, gen.gen_id, False)
    with pytest.raises(ValueError, match='not applicable'):
        system._begin_operation(instance_id='life', channel_id='channel', seq=20,
                                command_address='address-A', cue_gen_id=atoms['cue'],
                                operation_gen_id=atoms['op'], contributor_gen_ids=(gen.gen_id,))
    assert not system._operation_pending


def test_block_does_not_rewrite_executed_pending_or_reject_its_later_actual():
    system, atoms, gen = ready()
    pending = system.begin_proposed_operation(system.propose_operations(view(system, atoms)))
    condition(system, gen.gen_id, False)
    assert system._operation_pending[('life', 'channel')] is pending
    assert system.accept_operation_outcome(replace(receipt(atoms, 20), command_address='address-A')) == 'observed'
    assert gen.actual_positive_count == 3
    assert system.propose_operations(view(system, atoms, seq=21)) is None


def test_checkpoint_preserves_block_and_old_session_migrates_without_fake_block():
    system, atoms, gen = ready()
    condition(system, gen.gen_id, False)
    restored = pickle.loads(pickle.dumps(system))
    assert restored.engine.context._base is restored.base
    assert restored.propose_operations(view(restored, atoms)) is None
    condition(restored, gen.gen_id, True)
    assert restored.propose_operations(view(restored, atoms)).command_address == 'address-A'
    for field in ('_applicability_blocks', '_applicability_revisions', '_applicability_scope'):
        restored.base.__dict__.pop(field, None)
    restored.engine.context.__dict__.pop('_base', None)
    legacy = pickle.loads(pickle.dumps(restored))
    assert legacy.propose_operations(view(legacy, atoms)).command_address == 'address-A'


def test_audit_and_guard_state_overflows_stop_without_command_or_partial_condition():
    system, atoms, gen = ready()
    system._operation_record_limit = 1
    with pytest.raises(OverflowError, match='INCOMPLETE'):
        condition(system, gen.gen_id, False)
    assert system.base.is_applicable(gen.gen_id, ('life', 'channel'))
    system._operation_record_limit = 4096
    system.base.start_applicability_audit(limit=1)
    condition(system, gen.gen_id, True)  # Sham is recorded, but does not change availability.
    with pytest.raises(OverflowError, match='INCOMPLETE'):
        system.propose_operations(view(system, atoms))
    assert system._last_operation_proposal is None and not system._operation_pending
    assert getattr(system.base, '_applicability_scope', None) is None
    assert not system.base._operation_meter
    assert len(system.base.finish_applicability_audit()) == 1


def test_nested_visibility_restores_scope_on_error_and_counts_guard_lookups():
    system, atoms, gen = ready()
    condition(system, gen.gen_id, False)
    system.base.start_operation_reads(100)
    with system.base.applicability_view('life', 'channel'):
        assert system.base.get(gen.gen_id) is None
        with pytest.raises(RuntimeError):
            with system.base.applicability_view('life', 'other'):
                assert system.base.get(gen.gen_id) is gen
                raise RuntimeError('synthetic interruption')
        assert system.base.get(gen.gen_id) is None
    assert system.base.finish_operation_reads() == 6  # Three record + guard-index reads.
    assert system.base.get(gen.gen_id) is gen
