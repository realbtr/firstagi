from copy import deepcopy
import hashlib
import json
import pytest
from experiments.diagnostics.ac0_kernel_binding import digest
from experiments.diagnostics.ac0_goal_evaluator import run_suite,protocol,aggregate,write_artifact,RunBudget


@pytest.fixture(scope='module')
def development():
    result,budget=run_suite('development')
    assert result['status']=='execution_complete_pending_write_receipt',result.get('error')
    return result,budget


def test_full_development_schedule_and_oracle_upper_bound(development):
    result,_=development
    assert [r['seed'] for r in result['runs']]==[41,42]
    assert result['budget_counts']['train_actions']==192
    assert result['budget_counts']['train_core_tokens']==480
    assert result['budget_counts']['evaluation_opportunities']==1536
    assert result['AC0_gate_pass'] is False
    assert result['aggregate']['checks']['seed_count'] is False
    for run in result['runs']:
        assert len(run['policies'])==12
        for row in run['policies']:
            assert len(row['records'])==64
            assert row['metrics']['observed_opportunities']==52
            assert row['metrics']['unknown_opportunities']==12
            if row['policy']=='oracle_upper_bound':assert row['metrics']['goal_success']==1
            if row['policy'] in ('empty_goal','minus_long_gen_goal'):
                assert row['metrics']['goal_success']==0
                assert all(r['event'] is None and r['operation_id'] is None for r in row['records'])


def test_all_policies_conditions_receive_identical_public_cases(development):
    result,_=development
    for run in result['runs']:
        first=run['policies'][0]['records']
        for row in run['policies']:
            assert [(r['case'],r['public_view']) for r in row['records']]==[(r['case'],r['public_view']) for r in first]
            assert all(set(r['public_view'])=={'channel_id','observation_id','available_operations','goal_observation_id'} for r in row['records'])


def test_every_forecast_links_actual_training_creation_and_prior_token_witness(development):
    result,_=development
    found=0
    for training,run in zip(result['training'],result['runs']):
        token_features={r['core_step']:r['canonical_feature_id'] for r in training['tokens']}
        for creation in training['gen_creation'].values():
            assert [token_features[s] for s in creation['feature_token_witness_steps']]==creation['feature_chain']
            assert all(s<=creation['core_step'] for s in creation['feature_token_witness_steps'])
        for row in run['policies']:
            for r in row['records']:
                assert digest(r['pre_outcome'])==r['pre_outcome_digest']
                for p in r['pre_outcome']['query']['forecasts']:
                    assert training['gen_creation'][p['gen_id']]['feature_chain']==p['gen_chain'];found+=1
    assert found>0


def test_prediction_unknown_never_becomes_negative_and_abstention_has_no_event(development):
    result,_=development
    for run in result['runs']:
        for row in run['policies']:
            for r in row['records']:
                if r['operation_id'] is None:
                    assert r['event'] is None
                    assert r['goal_reached'] in (False,None)
                for e in r['prediction_evidence']:
                    if r['scheduled_status'] or e['operation_id']!=r['operation_id']:
                        assert e['support']=='unknown'
                    elif e['reason']=='observed':assert r['event']['actual_observation'] is not None


def test_frozen_hash_is_constant_across_both_conditions(development):
    result,_=development
    for run in result['runs']:
        for row in run['policies']:
            if row['policy'] not in run['models']:continue
            expected=run['models'][row['policy']]['frozen_digest']
            assert all(r['pre_outcome']['query']['frozen_digest']==expected for r in row['records'])


def test_budget_failure_preserves_partial_training_without_aggregate():
    limits=deepcopy(protocol()['budgets']);limits['max_train_actions_total']=0
    result,_=run_suite('development',limits=limits)
    assert result['status']=='incomplete' and 'budget exceeded' in result['error']
    assert result['training'][0]['tokens'] and not result['training'][0]['events']
    assert 'aggregate' not in result


def test_timeout_preserves_incomplete_status():
    class Clock:
        def __init__(self):self.value=0
        def __call__(self):self.value+=1;return self.value
    limits=deepcopy(protocol()['budgets']);limits['max_wall_seconds_complete_run']=.5
    result,_=run_suite('development',limits=limits,clock=Clock())
    assert result['status']=='incomplete' and 'wall budget' in result['error']


def test_raw_and_completion_receipt_distinguish_write_overrun(tmp_path):
    now=[0.]
    budget=RunBudget(protocol()['budgets'],clock=lambda:now[0])
    result={'status':'execution_complete_pending_write_receipt','runs':[]}
    now[0]=301
    path=tmp_path/'partial.json'
    receipt=write_artifact(path,result,budget)
    assert receipt['status']=='incomplete'
    assert receipt['raw_sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    assert json.loads(path.with_suffix('.json.completion.json').read_text())['status']=='incomplete'
    with pytest.raises(FileExistsError):write_artifact(path,result,budget)


def test_existing_companion_receipt_is_never_overwritten(tmp_path):
    budget=RunBudget(protocol()['budgets'])
    path=tmp_path/'new.json'
    receipt=path.with_suffix('.json.sha256');receipt.write_text('prior artifact receipt')
    with pytest.raises(FileExistsError):write_artifact(path,{'status':'incomplete'},budget)
    assert not path.exists() and receipt.read_text()=='prior artifact receipt'


def synthetic_runs():
    """Fabricated calculator fixture, NOT an empirical confirming pool."""
    runs=[]
    for _ in range(8):
        policies=[]
        for condition in protocol()['evaluation']['conditions']:
            for name in protocol()['evaluation']['policies']:
                rate=1 if name in ('frozen_prefix_goal','oracle_upper_bound') else .5 if name in ('fixed_first','random_uniform') else 0
                policies.append({'condition':condition,'policy':name,
                    'metrics':{'goal_success':rate,'action_coverage':1,'goal_successes':int(rate*52),'observed_opportunities':52},
                    'evidence_counts':{'positive':40 if condition=='stable' else 0,
                        'negative':40 if condition!='stable' else 0,'unknown':12}})
        runs.append({'policies':policies})
    return runs


def test_preregistered_calculator_requires_all_comparators_seed_count_and_evidence():
    runs=synthetic_runs();config=protocol()
    result=aggregate(runs,config)
    assert result['bounded_scaffold_criteria_pass'] and result['rule_change_check']=='pass'
    assert result['AC0_gate_pass'] is False
    assert not aggregate(runs[:7],config)['checks']['seed_count']
    for run in runs:
        for row in run['policies']:
            if row['policy']=='fixed_first':row['metrics']['goal_success']=1
    assert not aggregate(runs,config)['checks']['advantage_fixed_first']


def test_absent_prediction_evidence_is_not_successful_accuracy():
    runs=synthetic_runs()
    for run in runs:
        for row in run['policies']:
            row['evidence_counts']={'positive':0,'negative':0,'unknown':50}
    result=aggregate(runs,protocol())
    assert result['stable_prediction_accuracy'] is None
    assert result['checks']['observed_forecast_accuracy'] is False
    assert result['rule_change_check']=='insufficient'
