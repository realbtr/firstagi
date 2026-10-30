"""Native kernel proposal provenance probe, not a learned action experiment."""
from __future__ import annotations
import argparse
from dataclasses import dataclass,asdict
import hashlib
import json
from pathlib import Path
import platform
import random
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.learning import LearningSystem
from core.generalization import PeripheralToken
from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld,UNKNOWN
from experiments.diagnostics.ac0_operation_codec import OperationCodec,PredictionFrame,decode_prediction


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@dataclass(frozen=True)
class KernelBinding:
    frame:PredictionFrame
    core_step:int
    context_digest:str
    feature_digest:str
    origin:tuple


class CodedKernelObserver:
    """Uses real process_token/propose, then verifies live Gen/feature linkage.

    Trial context reset is a declared fixture. No manual Gen seeding or recall
    policy is used by the diagnostic. The fixture still chooses every action.
    """
    def __init__(self):
        self.codec=OperationCodec()
        self.system=LearningSystem(feature_tolerance=.15)
        self.provenance={}
        self.seq=0
        self.view=None
        self.seen=set()
        self.event_pending=False

    def _ingest(self,channel,source,target,role):
        feature=self.codec.encode_role(channel,source,target,role)
        result=self.system.process_token(PeripheralToken.new(channel,feature))
        fid=self.system.engine.find_matching_feature(feature)
        if fid is not None:
            self.provenance.setdefault(fid,set()).add((role,channel,source,target))
        return {'role':role,'input_feature_id':feature.feature_id,'canonical_feature_id':fid,
                'core_step':self.system.engine.step_count,'outcome':result.outcome.name,
                'matched_feature_id':result.matched_feature_id,'new_gen_id':result.new_gen_id,
                'completed_gen_ids':result.completed_gen_ids}

    def _context_digest(self):
        expected=self.system.engine.context.get_expected_features(self.system.base)
        return digest(sorted((gid,fid,self.system.engine.context._active[gid].current_feature_index,
                              self.system.base.get(gid).feature_chain,self.system.base.get(gid).success_count,
                              self.system.base.get(gid).stop_count)
                             for gid,fid in expected.items()))

    def _fresh_bindings(self):
        # Explicit fresh proposal generation AFTER processing the current cue.
        proposals=self.system.initiative.propose(self.system.engine.context,self.system.base,self.system.hedonic)
        expected=self.system.engine.context.get_expected_features(self.system.base)
        bindings=[]
        rejected=[]
        for proposal in proposals:
            fid=proposal.next_feature_id
            origins=self.provenance.get(fid,set())
            if expected.get(proposal.gen_id)!=fid or len(origins)!=1:
                rejected.append('unverified_or_ambiguous_feature_origin');continue
            role,channel,cue,op=next(iter(origins))
            if (role!='cue_to_operation' or channel!=self.view['channel_id'] or
                cue!=self.view['observation_id'] or op not in self.view['available_operations']):
                rejected.append('not_a_current_cue_operation_feature');continue
            feature=self.system.engine._features.get(fid)
            if feature is None:
                rejected.append('missing_registered_feature');continue
            frame=PredictionFrame(channel,cue,self.seq,'after_cue',self.codec.version,proposal.gen_id,feature)
            bindings.append(KernelBinding(frame,self.system.engine.step_count,
                            self._context_digest(),digest(asdict(feature)),next(iter(origins))))
        return bindings,{'fresh_proposals':len(proposals),'rejected':rejected}

    def begin(self,view):
        if self.event_pending:
            raise ValueError('previous event still pending')
        self.system.reset_context()  # explicit trial scaffold, not AC1 retention
        self.seq+=1
        self.view={k:view[k] for k in ('channel_id','observation_id','available_operations')}
        self.event_pending=True
        cue=self._ingest(self.view['channel_id'],self.view['observation_id'],
                         self.view['observation_id'],'cue_anchor')
        bindings,info=self._fresh_bindings()
        prefix=self.system.base.search_by_prefix([cue['canonical_feature_id']])
        info['long_prefix_gens_present']=sum(len(g.feature_chain)>1 for g in prefix)
        return cue,bindings,info

    def decode_current(self,binding):
        frame=binding.frame
        expected=self.system.engine.context.get_expected_features(self.system.base)
        known=self.system.engine._features.get(frame.feature.feature_id)
        if (not self.event_pending or self.view is None or known is None or binding.core_step!=self.system.engine.step_count or
            binding.context_digest!=self._context_digest() or expected.get(frame.gen_id)!=frame.feature.feature_id or
            digest(asdict(known))!=binding.feature_digest or digest(asdict(frame.feature))!=binding.feature_digest):
            return {'status':'abstain_kernel_state_changed','operation_id':None}
        origins=self.provenance.get(frame.feature.feature_id,set())
        if origins!={binding.origin}:
            return {'status':'abstain_origin_changed','operation_id':None}
        return decode_prediction(frame,self.view,self.seq,tolerance=self.system.engine.feature_tolerance,codec=self.codec)

    def complete(self,event):
        key=(event.run_id,event.event_id)
        if key in self.seen:raise ValueError('duplicate event')
        if not self.event_pending or event.channel_id!=self.view['channel_id'] or event.observation_id!=self.view['observation_id']:
            raise ValueError('event does not belong to pending cue')
        if event.chosen_operation not in self.view['available_operations']:
            raise ValueError('operation is not available')
        if event.completion not in UNKNOWN|{'success','observed_divergence'}:
            raise ValueError('unsupported completion status')
        steps=[]
        if event.completion not in UNKNOWN:
            if event.actual_observation is None:raise ValueError('missing actual outcome')
            steps.append(self._ingest(event.channel_id,event.observation_id,event.chosen_operation,'cue_to_operation'))
            steps.append(self._ingest(event.channel_id,event.chosen_operation,event.actual_observation,'operation_to_observation'))
        self.seen.add(key)
        self.event_pending=False
        return steps


def run_probe(seed,controller,attempts=48):
    if controller not in ('fixed','random'):raise ValueError('fixed/random fixtures only')
    world=TwoChannelWorld(seed,f'ac0-kernel-binding-{seed}-{controller}')
    observer=CodedKernelObserver()
    rng=random.Random(seed+1000)
    records=[]
    for step in range(attempts):
        channel=world.channels[step%2]
        view=world.view(channel)
        cue,bindings,info=observer.begin(view)
        decoded=[observer.decode_current(b) for b in bindings]
        # No kernel candidate is used to act: this is a provenance probe only.
        operation=view['available_operations'][0] if controller=='fixed' else rng.choice(view['available_operations'])
        status={3:'interrupted',5:'unavailable',7:'cancelled'}.get(step%12)
        event=world.act(channel,operation,forced_status=status)
        steps=observer.complete(event)
        records.append({'seq':event.seq,'cue_step':cue,'proposal_info':info,
                        'bindings':[asdict(b) for b in bindings],'decoded_candidates':decoded,
                        'fixture_event':asdict(event),'completion_steps':steps})
    return {'seed':seed,'controller':controller,'attempts':attempts,
            'core_tokens':observer.system.engine.step_count,
            'fresh_proposals':sum(r['proposal_info']['fresh_proposals'] for r in records),
            'bound_operation_proposals':sum(len(r['bindings']) for r in records),
            'unique_operation_candidates':sum(d['status']=='unique_candidate' for r in records for d in r['decoded_candidates']),
            'views_with_long_prefix_gens':sum(r['proposal_info']['long_prefix_gens_present']>0 for r in records),
            'long_gens_at_end':sum(len(g.feature_chain)>1 for g in observer.system.base.all()),
            'kernel_selected_actions':0,'records':records}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():parser.error('use a fresh output path')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    runs=[run_probe(s,c) for s in (41,42) for c in ('fixed','random')]
    result={'schema':'firstagi.ac0-kernel-binding/v0.1','status':'debug_not_gate',
            'source_commit':commit,'source_dirty':dirty,'python':sys.version,'platform':platform.platform(),
            'context_policy':'reset_before_each_cue_fixture_not_AC1','manual_seed_or_recall':False,
            'gen_specific_external_support_updated':False,'runs':runs}
    raw=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('xb') as handle:handle.write(raw)
    with args.out.with_suffix(args.out.suffix+'.sha256').open('x',encoding='utf-8') as handle:
        handle.write(hashlib.sha256(raw).hexdigest()+'  '+args.out.name+'\n')
    print(json.dumps([{k:v for k,v in r.items() if k!='records'} for r in runs],indent=2))


if __name__=='__main__':main()
