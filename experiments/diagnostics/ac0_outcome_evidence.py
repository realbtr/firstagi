"""Named learned-Gen outcome forecast replay; debug, not action competence."""
from __future__ import annotations
import argparse
from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld,UNKNOWN
from experiments.diagnostics.ac0_kernel_binding import digest
from experiments.diagnostics.ac0_recall_ablation import train_snapshot,model_fingerprint


def forecast(observer,binding):
    """Read the next outcome edge of the SAME live, learned Gen; no world access."""
    decoded=observer.decode_current(binding)
    if decoded['status']!='unique_candidate':return None
    gen=observer.system.base.get(binding.frame.gen_id)
    active=observer.system.engine.context._active.get(gen.gen_id)
    index=active.current_feature_index
    if index+1>=len(gen.feature_chain):return None
    fid=gen.feature_chain[index+1]
    origins=observer.provenance.get(fid,set())
    if len(origins)!=1 or fid not in observer.system.engine._features:return None
    role,channel,operation,outcome=next(iter(origins))
    if (role!='operation_to_observation' or channel!=binding.frame.channel_id or
        operation!=decoded['operation_id']):return None
    return {'gen_id':gen.gen_id,'gen_chain':list(gen.feature_chain),
            'operation_id':operation,'predicted_observation':outcome,
            'channel_id':channel,'observation_id':binding.frame.cue_id,
            'outcome_feature_id':fid,'binding':asdict(binding)}


def evidence(prediction,event):
    """Prediction agreement, not fixture task-target support or native counters."""
    if (prediction['channel_id']!=event.channel_id or
        prediction['observation_id']!=event.observation_id or
        prediction['operation_id']!=event.chosen_operation):
        raise ValueError('forecast/event mismatch')
    if event.completion in UNKNOWN:
        if event.actual_observation is not None:raise ValueError('unknown has actual outcome')
        return 'unknown'
    if event.completion not in {'success','observed_divergence'} or event.actual_observation is None:
        raise ValueError('invalid observed outcome')
    return 'positive' if prediction['predicted_observation']==event.actual_observation else 'negative'


def replay(seed,controller):
    trained,views,training=train_snapshot(seed,controller)
    fingerprint=model_fingerprint(trained)
    world=TwoChannelWorld(seed,f'ac0-outcome-replay-{seed}-{controller}')
    records=[]
    for old in training:
        view=world.view(old['channel_id'])
        if view['observation_id']!=old['observation_id']:raise ValueError('replay cue drift')
        probe=deepcopy(trained)
        _,bindings,info=probe.begin(view,recall_policy='exact_learned_prefix')
        predictions=[p for b in bindings if (p:=forecast(probe,b)) is not None
                     and p['operation_id']==old['chosen_operation']]
        # Seal predictions BEFORE act. This is local ordering evidence, not a timestamp authority.
        sealed={'public_view':view,'fixture_operation':old['chosen_operation'],
                'predictions':predictions,'training_fingerprint':fingerprint}
        pre_outcome_digest=digest(sealed)
        event=world.act(old['channel_id'],old['chosen_operation'],
            forced_status=old['completion'] if old['completion'] in UNKNOWN else None)
        scored=[{'gen_id':p['gen_id'],'support':evidence(p,event)} for p in predictions]
        records.append({'pre_outcome':sealed,'pre_outcome_digest':pre_outcome_digest,
                        'event':asdict(event),'evidence':scored,'recall_info':info})
    if model_fingerprint(trained)!=fingerprint:raise ValueError('training model mutated')
    scores=[e for r in records for e in r['evidence']]
    seen={}
    for r in records:
        for e in r['evidence']:seen.setdefault(e['gen_id'],[]).append(e['support'])
    return {'seed':seed,'controller':controller,'records':records,
        'attempts':len(records),'forecast_covered_attempts':sum(bool(r['evidence']) for r in records),
        'support_counts':{s:sum(e['support']==s for e in scores) for s in ('positive','negative','unknown')},
        'reused_gen_ids':sorted(g for g,seq in seen.items() if len(seq)>1),
        'positive_on_task_divergence':sum(e['support']=='positive' for r in records
            if r['event']['completion']=='observed_divergence' for e in r['evidence']),
        'training_snapshot_unchanged':True}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():parser.error('fresh output path required')
    result={'schema':'firstagi.ac0-outcome-evidence/v0.1','status':'in_sample_debug_not_gate',
        'source_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_dirty':bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip()),
        'prediction_selection':'all_matching_fixture_operation_not_goal_selection',
        'support_storage':'external_receipts_only_not_native_gen_counters',
        'probe_model':'paired_finalized_warmup_copy_per_cue_not_frozen_skill_control',
        'evaluation':'same_rules_and_training_trajectory_replayed_not_independent_replication',
        'runs':[replay(s,c) for s in (41,42) for c in ('fixed','random')]}
    raw=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode()
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('xb') as f:f.write(raw)
    with args.out.with_suffix(args.out.suffix+'.sha256').open('x') as f:
        f.write(hashlib.sha256(raw).hexdigest()+'  '+args.out.name+'\n')
    print(json.dumps([{k:v for k,v in r.items() if k!='records'} for r in result['runs']],indent=2))


if __name__=='__main__':main()
