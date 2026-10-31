from copy import deepcopy
import pickle
import pytest
from core.generalization import Generalization
from core.initiative import InitiativeEngine
from core.context import ContextBuffer
from core.learning import LearningSystem
from experiments.diagnostics.ac0_kernel_binding import CodedKernelObserver
from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld
from experiments.diagnostics.ac0_recall_ablation import train_snapshot
from experiments.diagnostics.ac0_frozen_goal import (
    FrozenGoalPredictor,BoundaryError,select_goal,episode_schedule,opportunity_metrics,development_probe)


def wiring_fixture(outcomes=('goal',)):
    """Hand-built Gen ONLY for mechanical adversarial tests, not empirical results."""
    obs=CodedKernelObserver()
    view={'channel_id':'public-channel','observation_id':'public-cue',
          'available_operations':('0123456789abcdef','fedcba9876543210'),'goal_observation_id':'goal'}
    def register(source,target,role):
        f=obs.codec.encode_role(view['channel_id'],source,target,role)
        obs.system.engine._features[f.feature_id]=f
        obs.provenance[f.feature_id]={(role,view['channel_id'],source,target)}
        return f.feature_id
    cue=register(view['observation_id'],view['observation_id'],'cue_anchor')
    operation=register(view['observation_id'],view['available_operations'][0],'cue_to_operation')
    for i,outcome in enumerate(outcomes):
        fid=register(view['available_operations'][0],outcome,'operation_to_observation')
        g=Generalization.new(feature_chain=[cue,operation,fid]);g.success_count=10-i
        obs.system.base.add(g)
    return obs,view


def test_wiring_forecast_uses_same_gen_and_freezes_full_state():
    obs,view=wiring_fixture();before=pickle.dumps(obs,protocol=5)
    result=FrozenGoalPredictor(obs).query(view)
    assert result['operation_id']==view['available_operations'][0]
    assert result['forecasts'][0]['gen_chain']==obs.system.base.all()[0].feature_chain
    assert result['execution_authorized_by_this_query'] is False
    assert result['core_tokens']==0 and pickle.dumps(obs,protocol=5)==before
    assert result['gen_records_visited']==6
    assert result['feature_origin_lookups']==5


def test_proposal_grouping_cannot_hide_conflicting_same_operation_gens():
    obs,view=wiring_fixture(('goal','other'))
    result=FrozenGoalPredictor(obs).query(view)
    assert len(result['proposal_gen_ids'])==1  # native grouping kept one representative
    assert len(result['forecasts'])==2  # decision still sees BOTH contributors
    assert result['operation_id'] is None


def test_selector_abstains_on_conflict_two_goal_operations_and_no_forecast():
    row=lambda op,out:{'operation_id':op,'predicted_observation':out}
    assert select_goal([row('a','g'),row('a','bad')],('a','b'),'g') is None
    assert select_goal([row('a','g'),row('b','g')],('a','b'),'g') is None
    assert select_goal([],('a','b'),'g') is None
    assert select_goal([row('a','g'),row('a','g')],('a','b'),'g')=='a'


@pytest.mark.parametrize('mutation',['counter','hedonic','pending','feature'])
def test_external_model_changes_fail_closed(mutation):
    obs,view=wiring_fixture();frozen=FrozenGoalPredictor(obs)
    gen=obs.system.base.all()[0]
    if mutation=='counter':gen.success_count+=1
    elif mutation=='hedonic':obs.system.hedonic.record_completion(gen.gen_id)
    elif mutation=='pending':obs.system.generalizer._current_chain.append(gen.feature_chain[0])
    else:obs.system.engine._features[gen.feature_chain[1]].distance+=1
    with pytest.raises(BoundaryError,match='mutated'):frozen.query(view)


def test_mutation_during_propose_is_detected_in_finally(monkeypatch):
    obs,view=wiring_fixture();frozen=FrozenGoalPredictor(obs)
    original=InitiativeEngine.propose
    def bad(self,context,base,hedonic):
        obs.system.base.all()[0].success_count+=1
        return original(self,context,base,hedonic)
    monkeypatch.setattr(InitiativeEngine,'propose',bad)
    with pytest.raises(BoundaryError,match='mutated'):frozen.query(view)


@pytest.mark.parametrize('limits',[{'max_gen_visits':5},{'max_feature_lookups':1},{'max_model_bytes':1}])
def test_budget_overrun_is_error_not_ordinary_abstention(limits):
    obs,view=wiring_fixture();before=pickle.dumps(obs,protocol=5)
    with pytest.raises(BoundaryError,match='budget'):FrozenGoalPredictor(obs,**limits).query(view)
    assert pickle.dumps(obs,protocol=5)==before


def test_unknown_cue_and_ablation_cannot_invent_a_candidate():
    obs,view=wiring_fixture()
    assert FrozenGoalPredictor(obs).query({**view,'observation_id':'never-seen'})['operation_id'] is None
    for g in list(obs.system.base.all()):obs.system.base.remove(g.gen_id)
    assert FrozenGoalPredictor(obs).query(view)['forecasts']==[]


def test_wrong_outcome_origin_abstains_without_changing_model():
    obs,view=wiring_fixture();fid=obs.system.base.all()[0].feature_chain[2]
    obs.provenance[fid]={('operation_to_observation',view['channel_id'],'wrong-operation','goal')}
    assert FrozenGoalPredictor(obs).query(view)['operation_id'] is None


def test_controller_rejects_hidden_fields_before_query():
    obs,view=wiring_fixture()
    with pytest.raises(ValueError,match='four public'):FrozenGoalPredictor(obs).query({**view,'_answers':{}})


def test_real_learned_query_never_processes_tokens_confirms_or_contacts_world(monkeypatch):
    obs,views,_=train_snapshot(41,'random',96)
    frozen=FrozenGoalPredictor(obs)
    before=pickle.dumps(obs,protocol=5)
    def forbidden(*args,**kwargs):raise AssertionError('frozen query cannot learn or access world')
    monkeypatch.setattr(LearningSystem,'process_token',forbidden)
    monkeypatch.setattr(ContextBuffer,'confirm_feature',forbidden)
    monkeypatch.setattr(CodedKernelObserver,'begin',forbidden)
    monkeypatch.setattr(TwoChannelWorld,'act',forbidden)
    monkeypatch.setattr(TwoChannelWorld,'oracle_operation',forbidden)
    rows=[frozen.query({**v,'goal_observation_id':'public-goal'}) for v in views[:16]]
    assert any(r['forecasts'] for r in rows)
    assert all(p['gen_id'] in {g.gen_id for g in obs.system.base.all()} for r in rows for p in r['forecasts'])
    assert pickle.dumps(obs,protocol=5)==before


def test_schedule_is_precomputed_balanced_and_pairs_without_policy_consumption():
    a=episode_schedule(1041);b=episode_schedule(1041)
    assert a==b and len(a)==64
    for ch in (0,1):
        for phase in (0,1):assert sum(r['channel_index']==ch and r['initial_phase']==phase for r in a)==16
    assert sum(r['scheduled_status'] is None for r in a)==52
    for status in ('interrupted','unavailable','cancelled'):assert sum(r['scheduled_status']==status for r in a)==4
    assert all(sorted(r['operation_order'])==[0,1] for r in a)


def test_denominator_keeps_abstentions_and_excludes_only_scheduled_unknown():
    rows=[{'scheduled_status':None,'operation_id':'a','goal_reached':True},
          {'scheduled_status':None,'operation_id':None,'goal_reached':False},
          {'scheduled_status':'interrupted','operation_id':None,'goal_reached':None}]
    result=opportunity_metrics(rows)
    assert result['observed_opportunities']==2 and result['unknown_opportunities']==1
    assert result['goal_success']==result['action_coverage']==.5
    rows[1]['goal_reached']=True
    with pytest.raises(ValueError,match='abstention'):opportunity_metrics(rows)


def test_development_entry_point_cannot_run_confirming_seeds():
    with pytest.raises(ValueError,match='development'):development_probe(101)
