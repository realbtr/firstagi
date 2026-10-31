"""Post-hoc baseline on recorded v1; no learner/world run or new confirmation."""
from collections import defaultdict
import argparse
import hashlib,json
from pathlib import Path
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('raw',type=Path)
parser.add_argument('--out',type=Path)
args=parser.parse_args()
p=args.raw
raw=p.read_bytes();d=json.loads(raw)
assert hashlib.sha256(raw).hexdigest()=='937ab033a63fc4de42001ce5370a804dadbe58c84e7fca7088f1629ed90d8568'
results=[]
for training,run in zip(d['training'],d['runs']):
    table=defaultdict(set)
    for event in training['events']:
        if event['actual_observation'] is not None:
            table[event['channel_id'],event['observation_id'],event['chosen_operation']].add(event['actual_observation'])
    rows=[]
    for policy in run['policies']:
        if policy['policy']!='frozen_prefix_goal':continue
        identical=success=observed=0
        for r in policy['records']:
            v=r['public_view']
            candidates=[op for op in v['available_operations'] if table.get((v['channel_id'],v['observation_id'],op))=={v['goal_observation_id']}]
            chosen=candidates[0] if len(candidates)==1 else None
            assert chosen==r['operation_id']  # only reuse actual outcome when action is identical
            identical+=1
            if r['scheduled_status'] is None:
                observed+=1
                success+=bool(r['event'] and r['event']['actual_observation']==v['goal_observation_id'])
        rows.append({'condition':policy['condition'],'identical_choices':identical,'goal_successes':success,'observed_opportunities':observed})
    results.append({'seed':run['seed'],'table_entries':len(table),'nondeterministic_entries':sum(len(x)>1 for x in table.values()),'conditions':rows})
out={'status':'post_hoc_descriptive_baseline_not_preregistered',
    'source_raw_sha256':hashlib.sha256(raw).hexdigest(),
    'method':'training actual-outcome table(channel,cue,operation); same explicit public-goal equality selector; factual scores reused only after per-record action equality check',
    'learner_or_world_executed':False,'uses_Gen_heterarchy_vectors_native_scores':False,
    'results':results,
    'conclusion':'This task/result does not establish advantage over an eight-entry per-task transition table. This does not refute heterarchy outside this task.'}
payload=(json.dumps(out,indent=2)+'\n').encode()
if args.out:
    with args.out.open('xb') as f:f.write(payload)
    with args.out.with_suffix(args.out.suffix+'.sha256').open('x') as f:f.write(hashlib.sha256(payload).hexdigest()+'  '+args.out.name+'\n')
print(json.dumps({'status':out['status'],'seeds':len(results),
    'entries_per_task':[r['table_entries'] for r in results],
    'identical_choices':sum(c['identical_choices'] for r in results for c in r['conditions']),
    'stable_goal_successes':sum(c['goal_successes'] for r in results for c in r['conditions'] if c['condition']=='stable'),
    'swapped_goal_successes':sum(c['goal_successes'] for r in results for c in r['conditions'] if c['condition']!='stable'),
    'conclusion':out['conclusion']},indent=2))
