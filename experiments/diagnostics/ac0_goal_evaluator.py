"""Paired frozen-goal evaluator; explicit scaffold, never an AC0 gate."""
from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import random
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld,UNKNOWN
from experiments.diagnostics.ac0_kernel_binding import CodedKernelObserver,digest
from experiments.diagnostics.ac0_frozen_goal import FrozenGoalPredictor,BoundaryError,episode_schedule,opportunity_metrics

PROTOCOL_SHA='2437f4fca7cfe683531b06175468573c482a2d2a88d7479fb57bbe5884370f3f'


def protocol():
    raw=(ROOT/'experiments/reports/ac0_debug/goal_choice/v1/protocol.json').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=PROTOCOL_SHA:raise BoundaryError('registered protocol hash mismatch')
    return json.loads(raw)


class RunBudget:
    def __init__(self,limits,clock=time.perf_counter):
        self.limits=limits
        self.clock=clock
        self.started=clock()
        self.counts={'train_actions':0,'train_core_tokens':0,'evaluation_opportunities':0,'evaluation_actions':0}

    def check(self):
        if self.clock()-self.started>self.limits['max_wall_seconds_complete_run']:
            raise BoundaryError('whole-run wall budget exceeded')

    def charge(self,name):
        self.check()
        if self.counts[name]+1>self.limits['max_'+name+'_total']:
            raise BoundaryError(name+' budget exceeded')
        self.counts[name]+=1


class ReceiptObserver(CodedKernelObserver):
    def _ingest(self,channel,source,target,role):
        sink=getattr(self,'_receipt_sink',None)
        if sink is None:return super()._ingest(channel,source,target,role)
        sink.capture_new('context_reset_before_token')
        sink.budget.charge('train_core_tokens')
        step=super()._ingest(channel,source,target,role)
        token={**step,'training_event_index':sink.event_index,'channel_id':channel,'source':source,'target':target}
        sink.log['tokens'].append(token)
        sink.witnesses.setdefault(step['canonical_feature_id'],step['core_step'])
        sink.capture_new('token_step')
        return step


class CreationReceipts:
    def __init__(self,observer,log,budget):
        self.observer=observer;self.log=log;self.budget=budget
        self.witnesses={};self.event_index=0

    def capture_new(self,stage):
        for gen in self.observer.system.base.all():
            if gen.gen_id in self.log['gen_creation']:continue
            if any(fid not in self.witnesses for fid in gen.feature_chain):
                raise BoundaryError('new Gen has no observed token witness')
            self.log['gen_creation'][gen.gen_id]={'gen_id':gen.gen_id,'feature_chain':list(gen.feature_chain),
                'first_observed_stage':stage,'core_step':self.observer.system.engine.step_count,
                'training_event_index':self.event_index,
                'feature_token_witness_steps':[self.witnesses[fid] for fid in gen.feature_chain]}


def traced_training(seed,log,budget):
    observer=ReceiptObserver();sink=CreationReceipts(observer,log,budget);observer._receipt_sink=sink
    world=TwoChannelWorld(seed,f'goal-training-{seed}');rng=random.Random(seed+1000)
    for index in range(96):
        budget.check();sink.event_index=index
        channel=world.channels[index%2];view=world.view(channel)
        observer.begin(view)
        operation=rng.choice(view['available_operations'])
        budget.charge('train_actions')
        event=world.act(channel,operation,forced_status={3:'interrupted',5:'unavailable',7:'cancelled'}.get(index%12))
        log['events'].append(asdict(event))
        observer.complete(event)
    observer.system.reset_context();sink.capture_new('final_context_reset')
    del observer._receipt_sink  # no mutable receipt log enters the frozen observer
    log['training_core_tokens']=observer.system.engine.step_count
    return observer


def prediction_receipts(forecasts,operation,event):
    records=[]
    for p in forecasts:
        if event is None or p['operation_id']!=operation:
            support,reason='unknown','not_executed'
        elif event.completion in UNKNOWN:
            support,reason='unknown',event.completion
        else:
            support='positive' if p['predicted_observation']==event.actual_observation else 'negative'
            reason='observed'
        records.append({'gen_id':p['gen_id'],'operation_id':p['operation_id'],
            'support':support,'reason':reason})
    return records


def evaluate_seed(seed,schedule_seed,trained,training,run,budget,config):
    schedule=episode_schedule(schedule_seed);run['schedule']=schedule;run['policies']=[]
    minus=deepcopy(trained)
    for gen in list(minus.system.base.all()):
        if len(gen.feature_chain)>1:minus.system.base.remove(gen.gen_id)
    kw={'max_gen_visits':budget.limits['max_gen_records_visited_per_learned_query'],
        'max_feature_lookups':budget.limits['max_feature_origin_lookups_per_learned_query'],
        'max_model_bytes':budget.limits['max_serialized_model_bytes_per_seed']}
    predictors={'frozen_prefix_goal':FrozenGoalPredictor(trained,**kw),
        'minus_long_gen_goal':FrozenGoalPredictor(minus,**kw),
        'empty_goal':FrozenGoalPredictor(CodedKernelObserver(),**kw)}
    run['models']={name:{'frozen_digest':p.frozen_digest,'serialized_bytes':p.model_bytes} for name,p in predictors.items()}
    for condition in config['evaluation']['conditions']:
        for name in config['evaluation']['policies']:
            row={'condition':condition,'policy':name,'records':[]};run['policies'].append(row)
            for case in schedule:
                budget.charge('evaluation_opportunities')
                world=TwoChannelWorld(seed,f'goal-eval-{seed}-{condition}-{name}-{case["episode_index"]}')
                channel=world.channels[case['channel_index']];world._phase[channel]=case['initial_phase']
                if condition=='all_cue_answers_swapped':
                    world._answers={k:next(op for op in world.operations if op!=v) for k,v in world._answers.items()}
                view={**world.view(channel),'goal_observation_id':world._targets[channel]}
                view['available_operations']=tuple(world.operations[i] for i in case['operation_order'])
                record={'case':case,'public_view':view,'state':'pending'};row['records'].append(record)
                if name in predictors:
                    query=predictors[name].query(view);operation=query['operation_id']
                else:
                    operation=(view['available_operations'][0] if name=='fixed_first' else
                        world.operations[case['random_operation_index']] if name=='random_uniform' else
                        world.oracle_operation(channel))
                    query={'operation_id':operation,'forecasts':[],'privileged':name=='oracle_upper_bound'}
                for p in query['forecasts']:
                    creation=training['gen_creation'].get(p['gen_id'])
                    if creation is None or creation['feature_chain']!=p['gen_chain']:
                        raise BoundaryError('forecast has no matching native training creation receipt')
                seal={'query':query,'public_view':view}
                record.update(pre_outcome=seal,pre_outcome_digest=digest(seal))
                budget.check();event=None
                if operation is not None:
                    budget.charge('evaluation_actions')
                    event=world.act(channel,operation,forced_status=case['scheduled_status'])
                score=None if case['scheduled_status'] else bool(event and event.actual_observation==view['goal_observation_id'])
                record.update(state='finished',operation_id=operation,scheduled_status=case['scheduled_status'],
                    goal_reached=score,event=asdict(event) if event else None,
                    prediction_evidence=prediction_receipts(query['forecasts'],operation,event))
            row['metrics']=opportunity_metrics(row['records'])
            row['evidence_counts']={s:sum(e['support']==s for r in row['records'] for e in r['prediction_evidence']) for s in ('positive','negative','unknown')}
            budget.check()


def aggregate(runs,config):
    stable={name:[] for name in config['evaluation']['policies']}
    for run in runs:
        for row in run['policies']:
            if row['condition']=='stable':stable[row['policy']].append(row)
    if any(len(rows)!=len(runs) for rows in stable.values()):raise BoundaryError('missing paired policy')
    mean=lambda values:sum(values)/len(values)
    rates={name:mean([r['metrics']['goal_success'] for r in rows]) for name,rows in stable.items()}
    cover=mean([r['metrics']['action_coverage'] for r in stable['frozen_prefix_goal']])
    criteria=config['criteria'];checks={'seed_count':len(runs)==criteria['seed_count'],
        'stable_goal_success':rates['frozen_prefix_goal']>=criteria['stable_goal_success_macro_mean_min'],
        'stable_coverage':cover>=criteria['stable_action_coverage_macro_mean_min']}
    differences={}
    for name in ('fixed_first','random_uniform','minus_long_gen_goal','empty_goal'):
        diff=[a['metrics']['goal_success']-b['metrics']['goal_success'] for a,b in zip(stable['frozen_prefix_goal'],stable[name])]
        differences[name]={'per_seed':diff,'macro':mean(diff),'positive_seeds':sum(x>0 for x in diff)}
        key='paired_macro_advantage_over_each_fixed_random_min' if name in ('fixed_first','random_uniform') else 'paired_macro_advantage_over_each_minus_empty_min'
        checks['advantage_'+name]=mean(diff)>=criteria[key] and sum(x>0 for x in diff)>=criteria['positive_seed_differences_per_comparator_min']
    evidence={condition:{s:0 for s in ('positive','negative','unknown')} for condition in config['evaluation']['conditions']}
    for run in runs:
        for row in run['policies']:
            if row['policy']=='frozen_prefix_goal':
                for s,n in row['evidence_counts'].items():evidence[row['condition']][s]+=n
    counts=evidence['stable'];observed=counts['positive']+counts['negative']
    accuracy=counts['positive']/observed if observed else None
    checks['observed_forecast_accuracy']=accuracy is not None and accuracy>=criteria['observed_prediction_receipt_accuracy_min']
    counts=evidence['all_cue_answers_swapped'];changed=counts['positive']+counts['negative']
    fraction=counts['negative']/changed if changed else None
    change_check='insufficient' if changed<criteria['changed_rules_observed_prediction_receipts_min'] else ('pass' if fraction>=criteria['changed_rules_negative_receipt_fraction_min'] else 'fail')
    return {'macro_goal_success':rates,'macro_action_coverage':cover,'paired_differences':differences,
        'micro_goal_counts':{name:{'successes':sum(r['metrics']['goal_successes'] for r in rows),
            'observed_opportunities':sum(r['metrics']['observed_opportunities'] for r in rows)} for name,rows in stable.items()},
        'prediction_evidence':evidence,'stable_prediction_accuracy':accuracy,'rule_change_negative_fraction':fraction,
        'rule_change_check':change_check,'checks':checks,'bounded_scaffold_criteria_pass':all(checks.values()),'AC0_gate_pass':False}


def run_suite(mode='development',*,limits=None,clock=time.perf_counter):
    config=protocol()
    if mode not in ('development','confirming'):raise ValueError('unknown run mode')
    seeds=config['development_only_task_seeds'] if mode=='development' else config['confirming_task_seeds']
    schedules=[s+1000 for s in seeds] if mode=='development' else config['episode_schedule_seeds']
    budget=RunBudget(limits or config['budgets'],clock)
    result={'schema':'firstagi.ac0-paired-goal-evaluation/v1','mode':mode,'status':'running',
        'protocol_sha256':PROTOCOL_SHA,'training':[],'runs':[],'AC0_gate_pass':False}
    try:
        for seed,schedule_seed in zip(seeds,schedules):
            log={'seed':seed,'events':[],'tokens':[],'gen_creation':{}};result['training'].append(log)
            trained=traced_training(seed,log,budget)
            run={'seed':seed};result['runs'].append(run)
            evaluate_seed(seed,schedule_seed,trained,log,run,budget,config)
        result['aggregate']=aggregate(result['runs'],config)
        result['aggregate']['interpretation']='development_only_no_confirming_result' if mode=='development' else 'preregistered_bounded_scaffold_result_not_gate'
        budget.check();result['status']='execution_complete_pending_write_receipt'
    except Exception as error:
        result['status']='incomplete';result['error']=type(error).__name__+': '+str(error)
    result['budget_counts']=dict(budget.counts)
    result['elapsed_before_write']=clock()-budget.started
    return result,budget


def write_artifact(path,result,budget):
    receipt=path.with_suffix(path.suffix+'.completion.json')
    sha_path=path.with_suffix(path.suffix+'.sha256')
    if any(p.exists() for p in (path,receipt,sha_path)):
        raise FileExistsError('fresh output path and companion receipts required')
    path.parent.mkdir(parents=True,exist_ok=True)
    raw=(json.dumps(result,indent=2)+'\n').encode()
    with path.open('xb') as f:f.write(raw)
    with sha_path.open('x') as f:f.write(hashlib.sha256(raw).hexdigest()+'  '+path.name+'\n')
    final={'status':'incomplete' if result['status']=='incomplete' else 'complete',
        'raw_sha256':hashlib.sha256(raw).hexdigest(),'elapsed_including_raw_write':budget.clock()-budget.started}
    try:budget.check()
    except BoundaryError as error:final.update(status='incomplete',error=str(error))
    with receipt.open('x',encoding='utf-8') as f:f.write(json.dumps(final,indent=2)+'\n')
    return final


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',required=True,type=Path)
    parser.add_argument('--mode',choices=('development','confirming'),default='development')
    parser.add_argument('--implementation-commit')
    args=parser.parse_args()
    if args.out.exists():parser.error('fresh output path required')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    if args.mode=='confirming' and (dirty or args.implementation_commit!=commit):
        parser.error('confirming requires clean source and exact --implementation-commit HEAD')
    result,budget=run_suite(args.mode)
    result.update(source_commit=commit,source_dirty=dirty,python=sys.version,platform=platform.platform())
    completion=write_artifact(args.out,result,budget)
    print(json.dumps({'status':completion,'budget_counts':result['budget_counts'],'aggregate':result.get('aggregate')},indent=2))


if __name__=='__main__':main()
