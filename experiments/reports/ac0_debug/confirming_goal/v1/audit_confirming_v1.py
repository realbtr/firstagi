"""Standard-library audit of recorded v1 data; never trains or runs a policy."""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import sys

if sys.flags.optimize:raise RuntimeError('audit requires assertions enabled')
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('raw',type=Path)
parser.add_argument('--protocol',type=Path,default=Path(__file__).resolve().parents[2]/'goal_choice/v1/protocol.json')
parser.add_argument('--out',type=Path)
args=parser.parse_args()
raw=args.raw.read_bytes();d=json.loads(raw)
sha=hashlib.sha256(raw).hexdigest()
assert args.raw.with_suffix(args.raw.suffix+'.sha256').read_text().split()[0]==sha
completion=json.loads(args.raw.with_suffix(args.raw.suffix+'.completion.json').read_text())
assert completion['status']=='complete' and completion['raw_sha256']==sha
protocol_raw=args.protocol.read_bytes();config=json.loads(protocol_raw)
assert hashlib.sha256(protocol_raw).hexdigest()==d['protocol_sha256']=='2437f4fca7cfe683531b06175468573c482a2d2a88d7479fb57bbe5884370f3f'
assert d['source_commit']=='c81166f11320628fb955d186f1d3c7597441661d' and not d['source_dirty']
assert d['mode']=='confirming' and d['status']=='execution_complete_pending_write_receipt'
assert [r['seed'] for r in d['runs']]==config['confirming_task_seeds']
assert [t['seed'] for t in d['training']]==config['confirming_task_seeds']
assert completion['elapsed_including_raw_write']<=config['budgets']['max_wall_seconds_complete_run']

def seal(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def fid(role,ch,source,target):
    raw=json.dumps(['ac0-opaque-operation/0.1',role,ch,source,target],ensure_ascii=False,separators=(',',':')).encode()
    return 'op:'+hashlib.sha256(raw).hexdigest()

rates={condition:{name:[] for name in config['evaluation']['policies']} for condition in config['evaluation']['conditions']}
evidence={condition:Counter() for condition in rates}
counts=Counter();seals=forecasts=creation_count=0
per_seed=[]
for training,run,schedule_seed in zip(d['training'],d['runs'],config['episode_schedule_seeds']):
    seed=run['seed'];rng=random.Random(seed);opaque=lambda:f'{rng.getrandbits(64):016x}'
    channels=tuple(opaque() for _ in range(2));ops=tuple(opaque() for _ in range(2))
    cues={c:(opaque(),opaque()) for c in channels}
    targets={c:opaque() for c in channels};divergences={c:opaque() for c in channels}
    answers={(c,p):rng.choice(ops) for c in channels for p in (0,1)}
    cases=[(c,p) for c in (0,1) for p in (0,1) for _ in range(16)]
    schedule_rng=random.Random(schedule_seed);schedule_rng.shuffle(cases)
    choice_rng=random.Random(schedule_seed+20000)
    expected_schedule=[]
    for i,(c,p) in enumerate(cases):
        order=[0,1];schedule_rng.shuffle(order)
        expected_schedule.append({'episode_index':i,'channel_index':c,'initial_phase':p,'operation_order':order,
            'random_operation_index':order[choice_rng.randrange(2)],
            'scheduled_status':{13:'interrupted',14:'unavailable',15:'cancelled'}.get(i%16)})
    assert expected_schedule==run['schedule']
    assert len(training['events'])==96 and len(training['tokens'])==training['training_core_tokens']==240
    assert [t['core_step'] for t in training['tokens']]==list(range(1,241))
    counts['train_actions']+=len(training['events']);counts['train_core_tokens']+=len(training['tokens'])
    token_map={t['core_step']:t for t in training['tokens']}
    for t in training['tokens']:assert t['input_feature_id']==fid(t['role'],t['channel_id'],t['source'],t['target'])
    creation_count+=len(training['gen_creation'])
    for gid,c in training['gen_creation'].items():
        assert gid==c['gen_id']
        assert [token_map[s]['canonical_feature_id'] for s in c['feature_token_witness_steps']]==c['feature_chain']
        assert all(s<=c['core_step']<=240 for s in c['feature_token_witness_steps'])
    assert len(run['policies'])==12
    seen=set();pub=None;decisions={};seed_values={}
    for row in run['policies']:
        condition,name=row['condition'],row['policy'];key=(condition,name)
        assert key not in seen;seen.add(key)
        assert len(row['records'])==64
        row_public=[(r['case'],r['public_view']) for r in row['records']]
        if pub is None:pub=row_public
        assert row_public==pub
        success=covered=observed=0;row_evidence=Counter()
        for i,r in enumerate(row['records']):
            counts['evaluation_opportunities']+=1
            assert r['state']=='finished' and r['case']==expected_schedule[i]
            case=r['case'];ch=channels[case['channel_index']];phase=case['initial_phase']
            view=r['public_view'];operation=r['operation_id'];event=r['event']
            assert set(view)=={'channel_id','observation_id','available_operations','goal_observation_id'}
            assert view=={'channel_id':ch,'observation_id':cues[ch][phase],
                'available_operations':[ops[j] for j in case['operation_order']],'goal_observation_id':targets[ch]}
            assert r['pre_outcome']['public_view']==view and seal(r['pre_outcome'])==r['pre_outcome_digest'];seals+=1
            q=r['pre_outcome']['query'];assert q['operation_id']==operation
            correct=answers[ch,phase]
            if condition=='all_cue_answers_swapped':correct=next(op for op in ops if op!=correct)
            if operation is not None:
                counts['evaluation_actions']+=1
                assert event['operation_cost']==1 and event['chosen_operation']==operation
                assert event['channel_id']==ch and event['observation_id']==view['observation_id']
                if case['scheduled_status'] is not None:
                    assert event['completion']==case['scheduled_status'] and event['actual_observation'] is None
                else:
                    actual=targets[ch] if operation==correct else divergences[ch]
                    assert event['actual_observation']==actual
                    assert event['completion']==('success' if operation==correct else 'observed_divergence')
            else:assert event is None
            if name=='fixed_first':assert operation==view['available_operations'][0]
            if name=='random_uniform':assert operation==ops[case['random_operation_index']]
            if name=='oracle_upper_bound':assert operation==correct and q['privileged']
            else:
                decision_key=(name,i)
                if decision_key in decisions:assert decisions[decision_key]==operation
                decisions[decision_key]=operation
            if name in run['models']:
                model=run['models'][name]
                assert q['frozen_digest']==model['frozen_digest'] and q['model_bytes']==model['serialized_bytes']
                assert model['serialized_bytes']<=config['budgets']['max_serialized_model_bytes_per_seed']
                assert q['gen_records_visited']<=config['budgets']['max_gen_records_visited_per_learned_query']
                assert q['feature_origin_lookups']<=config['budgets']['max_feature_origin_lookups_per_learned_query']
                assert q['core_tokens']==0
            expected_score=None if case['scheduled_status'] else bool(event and event['actual_observation']==view['goal_observation_id'])
            assert r['scheduled_status']==case['scheduled_status'] and r['goal_reached']==expected_score
            if case['scheduled_status'] is None:
                observed+=1;covered+=operation is not None;success+=expected_score
            assert len(q['forecasts'])==len(r['prediction_evidence'])
            for f,e in zip(q['forecasts'],r['prediction_evidence']):
                forecasts+=1
                creation=training['gen_creation'][f['gen_id']]
                assert creation['feature_chain']==f['gen_chain']
                assert f['gen_chain'][0]==fid('cue_anchor',ch,view['observation_id'],view['observation_id'])
                assert f['gen_chain'][1]==f['operation_feature_id']==fid('cue_to_operation',ch,view['observation_id'],f['operation_id'])
                assert f['gen_chain'][2]==f['outcome_feature_id']==fid('operation_to_observation',ch,f['operation_id'],f['predicted_observation'])
                expected='unknown' if event is None or f['operation_id']!=operation or case['scheduled_status'] else ('positive' if f['predicted_observation']==event['actual_observation'] else 'negative')
                assert e['support']==expected and e['gen_id']==f['gen_id'] and e['operation_id']==f['operation_id']
                row_evidence[expected]+=1
        if name=='frozen_prefix_goal':evidence[condition].update(row_evidence)
        assert observed==52 and row['metrics']['goal_successes']==success
        assert row['metrics']['observed_opportunities']==52 and row['metrics']['unknown_opportunities']==12
        assert row['metrics']['goal_success']==float(Fraction(success,52)) and row['metrics']['action_coverage']==float(Fraction(covered,52))
        assert all(row['evidence_counts'][s]==row_evidence[s] for s in ('positive','negative','unknown'))
        rates[condition][name].append((Fraction(success,52),Fraction(covered,52)))
        seed_values[condition+':'+name]=success
    per_seed.append({'seed':seed,'goal_successes_out_of_52':seed_values})

assert dict(counts)==d['budget_counts']
for name,n in counts.items():assert n<=config['budgets']['max_'+name+'_total']
stable=rates['stable'];mean=lambda xs:sum(xs,Fraction())/len(xs)
criteria=config['criteria'];threshold=lambda name:Fraction(str(criteria[name]))
quality=mean([v[0] for v in stable['frozen_prefix_goal']]);coverage=mean([v[1] for v in stable['frozen_prefix_goal']])
checks={'seed_count':len(d['runs'])==8,'stable_goal_success':quality>=threshold('stable_goal_success_macro_mean_min'),
    'stable_coverage':coverage>=threshold('stable_action_coverage_macro_mean_min')}
for name in ('fixed_first','random_uniform','minus_long_gen_goal','empty_goal'):
    delta=[a[0]-b[0] for a,b in zip(stable['frozen_prefix_goal'],stable[name])]
    key='paired_macro_advantage_over_each_fixed_random_min' if name in ('fixed_first','random_uniform') else 'paired_macro_advantage_over_each_minus_empty_min'
    checks['advantage_'+name]=mean(delta)>=threshold(key) and sum(x>0 for x in delta)>=criteria['positive_seed_differences_per_comparator_min']
accuracy=Fraction(evidence['stable']['positive'],evidence['stable']['positive']+evidence['stable']['negative'])
checks['observed_forecast_accuracy']=accuracy>=threshold('observed_prediction_receipt_accuracy_min')
changed=evidence['all_cue_answers_swapped'];changed_observed=changed['positive']+changed['negative']
rule_check=changed_observed>=criteria['changed_rules_observed_prediction_receipts_min'] and Fraction(changed['negative'],changed_observed)>=threshold('changed_rules_negative_receipt_fraction_min')
assert checks==d['aggregate']['checks'] and all(checks.values())==d['aggregate']['bounded_scaffold_criteria_pass']
assert rule_check and d['aggregate']['rule_change_check']=='pass' and d['AC0_gate_pass'] is False
summary={'schema':'firstagi.confirming-goal-raw-audit/v1','status':'recorded_data_audit_pass',
    'raw_sha256':sha,'source_commit':d['source_commit'],'protocol_sha256':d['protocol_sha256'],
    'completion_seconds':completion['elapsed_including_raw_write'],'raw_bytes':len(raw),
    'budget_counts':dict(counts),'pre_outcome_seals_checked':seals,'forecasts_checked':forecasts,
    'native_creation_receipts_checked':creation_count,'checks':checks,'rule_change_check':rule_check,
    'bounded_scaffold_pass':all(checks.values()),'AC0_gate_pass':False,'per_seed':per_seed,
    'scope':'stdlib fixture reconstruction, hashes, arithmetic and recorded consistency; not independent replication or proof of frozen runtime state'}
if args.out:
    payload=(json.dumps(summary,indent=2)+'\n').encode()
    with args.out.open('xb') as f:f.write(payload)
    with args.out.with_suffix(args.out.suffix+'.sha256').open('x') as f:f.write(hashlib.sha256(payload).hexdigest()+'  '+args.out.name+'\n')
print(json.dumps({k:v for k,v in summary.items() if k!='per_seed'},indent=2))
