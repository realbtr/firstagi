from copy import deepcopy
import pytest
from experiments.diagnostics.ac0_kernel_binding import CodedKernelObserver
from experiments.diagnostics.ac0_recall_ablation import train_snapshot,paired_probe,model_fingerprint


def test_empty_base_prefix_recall_cannot_invent_learned_chains():
    observer=CodedKernelObserver()
    view={'channel_id':'c','observation_id':'q','available_operations':('a','b')}
    ids=observer._recall_exact_prefix(view)
    assert ids==[]
    assert observer.system.base.size()==0


def test_recall_only_activates_preexisting_matching_long_gen():
    observer,views,_=train_snapshot(41,'fixed')
    observer.system.reset_context()
    before=model_fingerprint(observer)
    seen=set()
    for view in views:
        observer.system.engine.context.reset()
        ids=observer._recall_exact_prefix(view)
        feature=observer.codec.encode_role(view['channel_id'],view['observation_id'],view['observation_id'],'cue_anchor')
        for gid in ids:
            gen=observer.system.base.get(gid)
            assert len(gen.feature_chain)>1 and gen.feature_chain[0]==feature.feature_id
        seen.update(ids)
    assert seen  # this fixed fixture creates learned chains in real warmup
    assert model_fingerprint(observer)==before


def test_paired_snapshots_remain_identical_and_source_unchanged():
    trained,views,_=train_snapshot(41,'fixed')
    before=model_fingerprint(trained)
    result=paired_probe(trained,views[:6])
    assert result['training_fingerprint']==before==model_fingerprint(trained)
    for record in result['records']:
        for row in record['conditions']:
            assert row['paired_initial_fingerprint']==before
            assert row['cue_tokens']==1
            assert row['recalled_all_preexisting_long_gens']
    minus=next(s for s in result['summaries'] if s['condition']=='minus_long_gen')
    assert minus['recalled_gen_activations']==0


def test_invalid_recall_policy_fails_before_kernel_state_changes():
    observer=CodedKernelObserver()
    before=model_fingerprint(observer)
    with pytest.raises(ValueError,match='recall policy'):
        observer.begin({'channel_id':'c','observation_id':'q','available_operations':('a','b')},recall_policy='hidden-oracle')
    assert model_fingerprint(observer)==before
    assert observer.event_pending is False


def test_probe_does_not_execute_model_candidates_or_query_oracle(monkeypatch):
    from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld
    def forbidden(*args,**kwargs):raise AssertionError('no world/oracle access during paired probe')
    trained,views,_=train_snapshot(42,'random')
    monkeypatch.setattr(TwoChannelWorld,'act',forbidden)
    monkeypatch.setattr(TwoChannelWorld,'oracle_operation',forbidden)
    result=paired_probe(trained,views[:2])
    assert all(s['probe_views']==2 for s in result['summaries'])


def test_minus_control_cannot_recreate_pending_chain_on_reset():
    trained,views,_=train_snapshot(41,'fixed')
    assert trained.system.generalizer._current_chain==[]
    probe=deepcopy(trained)
    for gen in list(probe.system.base.all()):
        if len(gen.feature_chain)>1:probe.system.base.remove(gen.gen_id)
    _,_,info=probe.begin(views[3],recall_policy='exact_learned_prefix')
    assert info['recalled_gen_ids']==[]
    assert all(len(gen.feature_chain)<=1 for gen in probe.system.base.all())
