"""Read-only learned-dynamics query and explicit goal-selector scaffold.

Development CLI uses ONLY41/42. No confirming runner or task-quality claim.
"""
from __future__ import annotations
import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import pickle
import random
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.context import ContextBuffer
from core.initiative import InitiativeEngine
from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld,UNKNOWN
from experiments.diagnostics.ac0_operation_codec import OperationCodec,PredictionFrame,decode_prediction
from experiments.diagnostics.ac0_recall_ablation import train_snapshot


class BoundaryError(RuntimeError):
    """Fail the run, never convert budget/model mutation to ordinary abstention."""


class CountedBase:
    def __init__(self,base,limit):
        self.base=base
        self.limit=limit
        self.visits=0

    def _visit(self):
        self.visits+=1
        if self.visits>self.limit:raise BoundaryError('Gen record budget exceeded')

    def scan(self):
        for gen in self.base.all():
            self._visit()
            yield gen

    def get(self,gid):
        self._visit()
        return self.base.get(gid)


def select_goal(forecasts,operations,goal):
    outcomes={op:set() for op in operations}
    for row in forecasts:
        if row['operation_id'] not in outcomes:raise ValueError('unavailable forecast operation')
        outcomes[row['operation_id']].add(row['predicted_observation'])
    eligible=[op for op,values in outcomes.items() if values=={goal}]
    return eligible[0] if len(eligible)==1 else None


class FrozenGoalPredictor:
    def __init__(self,observer,*,max_gen_visits=4096,max_feature_lookups=12288,max_model_bytes=33554432):
        self.observer=observer
        self.max_gen_visits=max_gen_visits
        self.max_feature_lookups=max_feature_lookups
        self.codec=OperationCodec()
        raw=pickle.dumps(observer,protocol=5)
        if len(raw)>max_model_bytes:raise BoundaryError('serialized model budget exceeded')
        self.model_bytes=len(raw)
        self.frozen_digest=hashlib.sha256(raw).hexdigest()

    def _check_frozen(self):
        if hashlib.sha256(pickle.dumps(self.observer,protocol=5)).hexdigest()!=self.frozen_digest:
            raise BoundaryError('frozen observer mutated')

    def query(self,view):
        started=time.perf_counter()
        required={'channel_id','observation_id','available_operations','goal_observation_id'}
        if set(view)!=required:raise ValueError('only four public controller fields allowed')
        if any(not isinstance(view[k],str) or not view[k] for k in required-{'available_operations'}):
            raise ValueError('opaque IDs required')
        ops=view['available_operations']
        if not isinstance(ops,(tuple,list)) or len(ops)!=2 or any(not isinstance(op,str) or not op for op in ops) or len(set(ops))!=2:
            raise ValueError('two distinct public operations required')
        self._check_frozen()
        base=CountedBase(self.observer.system.base,self.max_gen_visits)
        lookups=0
        codec_encodings=0
        def lookup(mapping,key):
            nonlocal lookups
            lookups+=1
            if lookups>self.max_feature_lookups:raise BoundaryError('feature/origin lookup budget exceeded')
            return mapping.get(key)
        try:
            channel,cue=view['channel_id'],view['observation_id']
            anchor=self.codec.encode_role(channel,cue,cue,'cue_anchor');codec_encodings+=1
            known_anchor=lookup(self.observer.system.engine._features,anchor.feature_id)
            context=ContextBuffer()
            if known_anchor is not None and asdict(known_anchor)==asdict(anchor):
                for gen in base.scan():
                    if len(gen.feature_chain)>1 and gen.feature_chain[0]==anchor.feature_id:
                        context.add_active(gen.gen_id)
                        # Do NOT call confirm_feature: that would mutate Gen counters.
                        context._active[gen.gen_id].advance()
            proposals=InitiativeEngine().propose(context,base,self.observer.system.hedonic)
            expected=context.get_expected_features(base)
            proposed_fids={p.next_feature_id for p in proposals}
            forecasts=[]
            rejected=[]
            # propose groups by feature and keeps one best Gen. Expand ALL live
            # contributors to each proposed feature so confidence cannot hide conflict.
            for gid,fid in expected.items():
                if fid not in proposed_fids:continue
                gen=base.get(gid)
                feature=lookup(self.observer.system.engine._features,fid)
                origins=lookup(self.observer.provenance,fid) or set()
                if feature is None or len(origins)!=1:
                    rejected.append('unverified_operation_origin');continue
                role,ch,source,operation=next(iter(origins))
                if (role!='cue_to_operation' or ch!=channel or source!=cue or operation not in ops):
                    rejected.append('wrong_operation_role_or_source');continue
                canonical=self.codec.encode(ch,source,operation);codec_encodings+=1
                if asdict(canonical)!=asdict(feature):
                    rejected.append('operation_feature_mismatch');continue
                frame=PredictionFrame(channel,cue,1,'after_cue',self.codec.version,gid,feature)
                decoded=decode_prediction(frame,view,1,tolerance=self.observer.system.engine.feature_tolerance,codec=self.codec)
                codec_encodings+=len(ops)
                if decoded['status']!='unique_candidate' or decoded['operation_id']!=operation:
                    rejected.append('operation_decode_abstention');continue
                index=context._active[gid].current_feature_index
                if index+1>=len(gen.feature_chain):
                    rejected.append('missing_outcome_edge');continue
                outcome_fid=gen.feature_chain[index+1]
                outcome_feature=lookup(self.observer.system.engine._features,outcome_fid)
                outcome_origins=lookup(self.observer.provenance,outcome_fid) or set()
                if outcome_feature is None or len(outcome_origins)!=1:
                    rejected.append('unverified_outcome_origin');continue
                role,ch,source,outcome=next(iter(outcome_origins))
                if (role!='operation_to_observation' or ch!=channel or source!=operation):
                    rejected.append('wrong_outcome_role_or_source');continue
                canonical=self.codec.encode_role(ch,source,outcome,role);codec_encodings+=1
                if asdict(canonical)!=asdict(outcome_feature):
                    rejected.append('outcome_feature_mismatch');continue
                forecasts.append({'gen_id':gid,'gen_chain':list(gen.feature_chain),
                    'operation_id':operation,'predicted_observation':outcome,
                    'operation_feature_id':fid,'outcome_feature_id':outcome_fid})
            chosen=select_goal(forecasts,ops,view['goal_observation_id'])
            return {'operation_id':chosen,'status':'scaffold_choice' if chosen is not None else 'abstain',
                'forecasts':forecasts,'proposal_gen_ids':[p.gen_id for p in proposals],
                'rejected':rejected,'frozen_digest':self.frozen_digest,'model_bytes':self.model_bytes,
                'gen_records_visited':base.visits,'feature_origin_lookups':lookups,
                'codec_encodings':codec_encodings,'core_tokens':0,
                'query_seconds_before_final_hash':time.perf_counter()-started,
                'execution_authorized_by_this_query':False}
        finally:
            self._check_frozen()


def episode_schedule(schedule_seed):
    rng=random.Random(schedule_seed)
    cases=[(channel,phase) for channel in (0,1) for phase in (0,1) for _ in range(16)]
    rng.shuffle(cases)
    random_policy=random.Random(schedule_seed+20000)
    records=[]
    for index,(channel,phase) in enumerate(cases):
        order=[0,1];rng.shuffle(order)
        records.append({'episode_index':index,'channel_index':channel,'initial_phase':phase,
            'operation_order':order,'random_operation_index':order[random_policy.randrange(2)],
            'scheduled_status':{13:'interrupted',14:'unavailable',15:'cancelled'}.get(index%16)})
    return records


def opportunity_metrics(records):
    observed=[]
    for row in records:
        status=row['scheduled_status']
        if status is not None and status not in UNKNOWN:raise ValueError('invalid scheduled status')
        if status is not None:
            if row['goal_reached'] is not None:raise ValueError('unknown outcome must not be scored')
        else:
            if type(row['goal_reached']) is not bool:raise ValueError('observed opportunity needs boolean task score')
            if row['operation_id'] is None and row['goal_reached']:raise ValueError('abstention cannot reach goal')
            observed.append(row)
    denominator=len(observed)
    return {'opportunities':len(records),'observed_opportunities':denominator,
        'unknown_opportunities':len(records)-denominator,
        'goal_successes':sum(r['goal_reached'] for r in observed),
        'action_coverage':sum(r['operation_id'] is not None for r in observed)/denominator if denominator else None,
        'goal_success':sum(r['goal_reached'] for r in observed)/denominator if denominator else None}


def development_probe(seed):
    if seed not in (41,42):raise ValueError('development seeds41/42 only; no confirming runner')
    observer,_,_=train_snapshot(seed,'random',96)
    predictor=FrozenGoalPredictor(observer)
    world=TwoChannelWorld(seed)
    records=[]
    for case in episode_schedule(seed+1000):
        channel=world.channels[case['channel_index']]
        # Evaluator-only construction; query receives four public values, not world.
        world._phase[channel]=case['initial_phase']
        view={**world.view(channel),'goal_observation_id':world._targets[channel]}
        view['available_operations']=tuple(world.operations[i] for i in case['operation_order'])
        records.append({'case':case,'public_view':view,'query':predictor.query(view)})
    return {'seed':seed,'training_attempts':96,'queries':len(records),'frozen_digest':predictor.frozen_digest,
        'model_bytes':predictor.model_bytes,'full_state_unchanged':True,
        'max_gen_visits':max(r['query']['gen_records_visited'] for r in records),
        'max_feature_lookups':max(r['query']['feature_origin_lookups'] for r in records),
        'world_actions_during_probe':0,'task_quality_scored':False,'records':records}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():parser.error('fresh output path required')
    started=time.perf_counter()
    result={'schema':'firstagi.ac0-frozen-query-development/v1','status':'development_mechanics_only',
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
        'confirming_runs_executed':0,'confirming_runner_implemented':False,
        'runs':[development_probe(seed) for seed in (41,42)]}
    result['wall_seconds_before_raw_write']=time.perf_counter()-started
    raw=(json.dumps(result,indent=2)+'\n').encode()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('xb') as f:f.write(raw)
    with args.out.with_suffix(args.out.suffix+'.sha256').open('x') as f:
        f.write(hashlib.sha256(raw).hexdigest()+'  '+args.out.name+'\n')
    print(json.dumps([{k:v for k,v in r.items() if k!='records'} for r in result['runs']],indent=2))


if __name__=='__main__':main()
