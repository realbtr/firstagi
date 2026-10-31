"""Paired learned-prefix recall diagnostic; no task-quality or gate claim."""
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

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld
from experiments.diagnostics.ac0_kernel_binding import CodedKernelObserver,digest


def model_fingerprint(observer):
    """Base/features/provenance/step fingerprint, not full runtime serialization."""
    return digest({'gens':sorted([asdict(g) for g in observer.system.base.all()],key=lambda x:x['gen_id']),
                   'features':{k:asdict(v) for k,v in observer.system.engine._features.items()},
                   'origins':{k:sorted(v) for k,v in observer.provenance.items()},
                   'core_step':observer.system.engine.step_count})


def train_snapshot(seed,controller,attempts=48):
    if controller not in ('fixed','random'):raise ValueError('fixed/random training fixtures only')
    world=TwoChannelWorld(seed,f'ac0-recall-training-{seed}-{controller}')
    observer=CodedKernelObserver()
    rng=random.Random(seed+1000)
    views=[]
    events=[]
    for step in range(attempts):
        channel=world.channels[step%2]
        view=world.view(channel)
        observer.begin(view)  # warmup always native; no hand-built Gen or recall
        operation=view['available_operations'][0] if controller=='fixed' else rng.choice(view['available_operations'])
        event=world.act(channel,operation,forced_status={3:'interrupted',5:'unavailable',7:'cancelled'}.get(step%12))
        observer.complete(event)
        views.append({k:deepcopy(view[k]) for k in ('channel_id','observation_id','available_operations')})
        events.append(asdict(event))
    # reset_context() can finalize a pending learned chain. Flush it ONCE
    # before snapshotting/ablation, otherwise the minus control recreates it.
    observer.system.reset_context()
    return observer,views,events


def paired_probe(trained,views):
    before=model_fingerprint(trained)
    original_ids={g.gen_id for g in trained.system.base.all()}
    long_ids={g.gen_id for g in trained.system.base.all() if len(g.feature_chain)>1}
    records=[]
    for index,view in enumerate(views,1):
        conditions=[]
        for condition in ('native_atomic','exact_learned_prefix','minus_long_gen'):
            probe=deepcopy(trained)  # same complete in-memory state before each cue
            paired_initial=model_fingerprint(probe)
            if paired_initial!=before:raise ValueError('paired base/features differ before intervention')
            if condition=='minus_long_gen':
                for gid in long_ids:probe.system.base.remove(gid)
            post_ablation=model_fingerprint(probe)
            policy='native_atomic' if condition=='native_atomic' else 'exact_learned_prefix'
            start=probe.system.engine.step_count
            cue,bindings,info=probe.begin(view,recall_policy=policy)
            if not set(info['recalled_gen_ids'])<=original_ids:
                raise ValueError('recall invented a Gen')
            decoded=[probe.decode_current(binding) for binding in bindings]
            operations=sorted({d['operation_id'] for d in decoded if d['status']=='unique_candidate'})
            conditions.append({'condition':condition,'paired_initial_fingerprint':paired_initial,
                'post_ablation_fingerprint':post_ablation,'cue_step':cue,'proposal_info':info,
                'bindings':[asdict(b) for b in bindings],'decoded_candidates':decoded,
                'distinct_operation_candidates':operations,
                'cue_tokens':probe.system.engine.step_count-start,
                'recalled_all_preexisting_long_gens':set(info['recalled_gen_ids'])<=long_ids})
        records.append({'view_index':index,'public_view':view,'conditions':conditions})
    if model_fingerprint(trained)!=before:raise ValueError('probe mutated training snapshot')
    summaries=[]
    for condition in ('native_atomic','exact_learned_prefix','minus_long_gen'):
        rows=[c for record in records for c in record['conditions'] if c['condition']==condition]
        summaries.append({'condition':condition,'probe_views':len(rows),
            'cue_tokens':sum(r['cue_tokens'] for r in rows),
            'views_with_bound_operations':sum(bool(r['bindings']) for r in rows),
            'views_with_any_unique_decoded_candidate':sum(bool(r['distinct_operation_candidates']) for r in rows),
            'views_with_one_distinct_operation':sum(len(r['distinct_operation_candidates'])==1 for r in rows),
            'views_with_competing_operations':sum(len(r['distinct_operation_candidates'])>1 for r in rows),
            'recalled_gen_activations':sum(len(r['proposal_info']['recalled_gen_ids']) for r in rows)})
    return {'training_fingerprint':before,'training_snapshot_unchanged':True,
            'long_gens_before_probes':len(long_ids),'summaries':summaries,'records':records}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():parser.error('use a new output path')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    runs=[]
    for seed in (41,42):
        for controller in ('fixed','random'):
            trained,views,events=train_snapshot(seed,controller)
            runs.append({'seed':seed,'training_controller':controller,'training_attempts':48,
                'training_core_tokens':trained.system.engine.step_count,'training_events':events,
                **paired_probe(trained,views)})
    result={'schema':'firstagi.ac0-recall-ablation/v0.1','status':'in_sample_debug_not_gate',
            'source_commit':commit,'source_dirty':dirty,'python':sys.version,'platform':platform.platform(),
            'probe_query_source':'public_views_from_warmup_not_held_out',
            'initial_state':'paired_deepcopies_of_same_trained_observer_before_each_probe',
            'training_finalization':'reset_context_flushes_pending_chain_before_snapshot_and_ablation',
            'cue_updates':'allowed_within_each_probe_then_discarded_not_a_frozen_model_control',
            'manual_gen_seeding':False,'kernel_selected_actions':0,'task_success_scored':False,'runs':runs}
    raw=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('xb') as handle:handle.write(raw)
    with args.out.with_suffix(args.out.suffix+'.sha256').open('x',encoding='utf-8') as handle:
        handle.write(hashlib.sha256(raw).hexdigest()+'  '+args.out.name+'\n')
    print(json.dumps([{'seed':r['seed'],'training_controller':r['training_controller'],
                       'long_gens_before_probes':r['long_gens_before_probes'],'summaries':r['summaries']} for r in runs],indent=2))


if __name__=='__main__':main()
