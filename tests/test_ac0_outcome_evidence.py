from copy import deepcopy
from dataclasses import asdict,replace
import pytest
from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld
from experiments.diagnostics.ac0_kernel_binding import digest
from experiments.diagnostics.ac0_outcome_evidence import evidence,forecast,replay
from experiments.diagnostics.ac0_recall_ablation import train_snapshot,model_fingerprint


def sample():
    world=TwoChannelWorld(41)
    event=world.act(world.channels[0],world.operations[0])
    prediction={'channel_id':event.channel_id,'observation_id':event.observation_id,
        'operation_id':event.chosen_operation,'predicted_observation':event.actual_observation}
    return prediction,event


def test_prediction_agreement_is_separate_from_task_success():
    p,e=sample()
    assert evidence(p,replace(e,completion='observed_divergence',prediction_support='negative'))=='positive'
    assert evidence(p,replace(e,actual_observation='contradiction',completion='success',prediction_support='positive'))=='negative'


@pytest.mark.parametrize('status',['interrupted','unavailable','cancelled'])
def test_unknown_is_not_negative(status):
    p,e=sample()
    assert evidence(p,replace(e,completion=status,actual_observation=None))=='unknown'
    with pytest.raises(ValueError):evidence(p,replace(e,completion=status))


@pytest.mark.parametrize('field',['channel_id','observation_id','operation_id'])
def test_cross_event_evidence_rejected(field):
    p,e=sample();p[field]='wrong'
    with pytest.raises(ValueError,match='mismatch'):evidence(p,e)


def test_forecast_uses_actual_learned_gen_without_oracle_and_does_not_mutate(monkeypatch):
    trained,views,_=train_snapshot(41,'fixed')
    probe=deepcopy(trained)
    def forbidden(*a,**k):raise AssertionError('forecast must not query world')
    monkeypatch.setattr(TwoChannelWorld,'act',forbidden)
    monkeypatch.setattr(TwoChannelWorld,'oracle_operation',forbidden)
    found=[]
    for view in views:
        probe=deepcopy(trained)
        _,bindings,_=probe.begin(view,recall_policy='exact_learned_prefix')
        before=model_fingerprint(probe)
        found.extend(p for b in bindings if (p:=forecast(probe,b)) is not None)
        assert model_fingerprint(probe)==before
    assert found
    assert all(p['gen_id'] in {g.gen_id for g in trained.system.base.all()} for p in found)


def test_replay_preserves_prediction_seal_and_scores_only_actual_outcomes():
    result=replay(41,'fixed')
    assert result['training_snapshot_unchanged']
    assert result['reused_gen_ids']
    assert result['support_counts']['positive']>0
    for r in result['records']:
        assert digest(r['pre_outcome'])==r['pre_outcome_digest']
        event=r['event']
        for p,e in zip(r['pre_outcome']['predictions'],r['evidence']):
            assert p['gen_id']==e['gen_id']
            expected='unknown' if event['actual_observation'] is None else ('positive' if p['predicted_observation']==event['actual_observation'] else 'negative')
            assert e['support']==expected
