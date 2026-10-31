"""Read-only operation decoding audit; does not select or execute actions.

The fixture controllers still act. We inspect a COPY of the observer driver
and current context, never a hidden answer table or an external success label.
"""
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
from drivers.text_driver import TextDriver
from experiments.diagnostics.ac0_event_baseline import CoreObserver, TwoChannelWorld


def inspect_decoding(view: dict, driver: TextDriver | None, system) -> dict:
    """Inspect only public candidates and existing kernel state; no updates."""
    cached={p.next_feature_id for p in system.last_proposals()}
    current=set(system.engine.context.get_expected_features(system.base).values())
    result={'cached_proposal_count':len(cached),'current_expected_count':len(current),
            'cached_matches_current_feature_set':cached==current,
            'unknown_symbols':[], 'candidate_pair_distance':None,
            'candidate_vectors':[], 'blockers':[]}
    if driver is None or not driver._vocab:
        result['blockers'].append('driver_vocabulary_uninitialized')
        return result
    symbols=[view['observation_id'],*view['available_operations']]
    result['unknown_symbols']=sorted(set(s for s in symbols if s not in driver._vocab))
    if result['unknown_symbols']:
        result['blockers'].append('unseen_symbols_use_default_rank')
    for op in view['available_operations']:
        # Work on a copy: produce() may initialize vocabulary on first use.
        token=next(deepcopy(driver).produce(view['observation_id']+' '+op))
        result['candidate_vectors'].append(asdict(token.data.vector))
    vectors=result['candidate_vectors']
    from core.feature import FeatureVector
    distance=FeatureVector(**vectors[0]).distance_to(FeatureVector(**vectors[1]))
    result['candidate_pair_distance']=distance
    if distance==0:
        result['blockers'].append('distinct_operations_have_identical_features')
    if cached!=current:
        result['blockers'].append('cached_proposals_do_not_match_current_context')
    # This is a diagnostic, not an action decoder; absence of these blockers
    # does not verify candidate provenance, timing or task competence.
    return result


def alias_counterexample() -> dict:
    driver=TextDriver('alias-fixture','anchor known target')
    list(driver.produce())
    system=CoreObserver().system
    view={'channel_id':'alias-fixture','observation_id':'anchor',
          'available_operations':('0123456789abcdef','fedcba9876543210')}
    result=inspect_decoding(view,driver,system)
    return {'fixture':'distinct_unseen_equal_shape_symbols', 'view':view, **result}


def audit_run(seed: int, controller: str, attempts: int=48) -> dict:
    if controller not in {'fixed','random'} or attempts<1:
        raise ValueError('audit uses fixed/random fixtures only, positive budget')
    world=TwoChannelWorld(seed,f'ac0-readiness-{seed}-{controller}')
    observer=CoreObserver()
    rng=random.Random(seed+1000)
    records=[]
    for step in range(attempts):
        channel=world.channels[step%2]
        view=world.view(channel)
        before=inspect_decoding(view,observer.drivers.get(channel),observer.system)
        operation=(view['available_operations'][0] if controller=='fixed'
                   else rng.choice(view['available_operations']))
        forced={3:'interrupted',5:'unavailable',7:'cancelled'}.get(step%12)
        event=world.act(channel,operation,forced_status=forced)
        observer.observe(event)
        after=inspect_decoding(view,observer.drivers.get(channel),observer.system)
        records.append({'seq':event.seq,'channel_id':channel,
                        'fixture_operation':operation,'completion':event.completion,
                        'before_action':before,'after_observation':after})
    initialized=[r['before_action'] for r in records
                 if 'driver_vocabulary_uninitialized' not in r['before_action']['blockers']]
    observed=[r for r in records if r['completion'] not in {'interrupted','unavailable','cancelled'}]
    return {'seed':seed,'controller':controller,'attempts':attempts,
            'initialized_decoding_views':len(initialized),
            'views_with_unknown_symbols':sum(bool(r['unknown_symbols']) for r in initialized),
            'views_with_exact_operation_collision':sum(r['candidate_pair_distance']==0 for r in initialized),
            'completed_observations':len(observed),
            'cached_vs_current_changes_after_completed_observation':sum(
                not r['after_observation']['cached_matches_current_feature_set'] for r in observed),
            'records':records}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():parser.error('use a fresh output file')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    results=[audit_run(seed,controller) for seed in (41,42) for controller in ('fixed','random')]
    result={'schema':'firstagi.ac0-operation-readiness/v0.1','status':'debug_source_audit_not_gate',
            'source_commit':commit,'source_dirty':dirty,
            'python':sys.version,'platform':platform.platform(),
            'hidden_answer_access_in_audit':False,'actions_selected_by_kernel':0,
            'counterexample':alias_counterexample(),'results':results,
            'limits':['TextDriver vocabulary behavior only; not all possible drivers',
                      'feature-set comparison ignores confidence/rank and does not prove cached actions are wrong',
                      'equal feature sets do not prove freshness or correct operation provenance',
                      'no learned-action experiment or Gen-specific external support update']}
    raw=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('xb') as handle:handle.write(raw)
    receipt=args.out.with_suffix(args.out.suffix+'.sha256')
    with receipt.open('x',encoding='utf-8') as handle:
        handle.write(hashlib.sha256(raw).hexdigest()+'  '+args.out.name+'\n')
    print(json.dumps([{k:v for k,v in r.items() if k!='records'} for r in results],indent=2))
    print('Synthetic distinct-operation feature distance:',result['counterexample']['candidate_pair_distance'])


if __name__=='__main__':main()
