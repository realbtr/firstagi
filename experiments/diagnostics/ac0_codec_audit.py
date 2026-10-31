"""Finite fixture encoding/decoding audit, NOT a learned action experiment."""
from __future__ import annotations
import argparse
from dataclasses import asdict,replace
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from experiments.diagnostics.ac0_operation_codec import OperationCodec,PredictionFrame,decode_prediction


def public_views(path:Path) -> list[dict]:
    hashes=json.loads((path.parent/'SHA256SUMS.json').read_text(encoding='utf-8'))
    raw=path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=hashes[path.name]:
        raise ValueError('input artifact hash mismatch')
    # Strip outcomes, expected targets, selected fixture operations and core
    # state. The codec receives ONLY the currently public transport fields.
    return [{k:e[k] for k in ('channel_id','observation_id','available_operations')}
            for e in json.loads(raw)['events']]


def audit_views(views:list[dict],tolerance:float) -> dict:
    codec=OperationCodec()
    records=[]
    for seq,view in enumerate(views,1):
        queries=[]
        for operation in view['available_operations']:
            feature=codec.encode(view['channel_id'],view['observation_id'],operation)
            frame=PredictionFrame(view['channel_id'],view['observation_id'],seq,
                'after_cue',codec.version,'synthetic-fixture-not-a-learned-Gen',feature)
            decoded=decode_prediction(frame,view,seq,tolerance=tolerance,codec=codec)
            stale=decode_prediction(replace(frame,decision_seq=seq-1),view,seq,tolerance=tolerance)
            wrong_cue=decode_prediction(replace(frame,cue_id='wrong-cue'),view,seq,tolerance=tolerance)
            wrong_phase=decode_prediction(replace(frame,phase='before_token'),view,seq,tolerance=tolerance)
            queries.append({'queried_operation':operation,'feature':asdict(feature),
                'decoded':decoded,'stale_status':stale['status'],
                'wrong_cue_status':wrong_cue['status'],'wrong_phase_status':wrong_phase['status']})
        records.append({'view_index':seq,'public_view':view,'queries':queries})
    flat=[q for record in records for q in record['queries']]
    return {'tolerance':tolerance,'public_views':len(views),'synthetic_queries':len(flat),
            'correct_roundtrips':sum(q['decoded']['operation_id']==q['queried_operation'] for q in flat),
            'abstentions':sum(q['decoded']['operation_id'] is None for q in flat),
            'wrong_operation_decodes':sum(q['decoded']['operation_id'] not in (None,q['queried_operation']) for q in flat),
            'rejected_stale_frames':sum(q['stale_status']=='abstain_frame_mismatch' for q in flat),
            'rejected_wrong_cue_frames':sum(q['wrong_cue_status']=='abstain_frame_mismatch' for q in flat),
            'rejected_wrong_phase_frames':sum(q['wrong_phase_status']=='abstain_frame_mismatch' for q in flat),
            'minimum_candidate_distance':min(q['decoded'].get('minimum_candidate_distance',float('inf')) for q in flat),
            'records':records}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--out',type=Path,required=True)
    args=parser.parse_args()
    if args.out.exists():parser.error('use a new output file')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    dirty=bool(subprocess.check_output(['git','status','--porcelain'],cwd=ROOT,text=True).strip())
    runs=[]
    for seed in (41,42):
        for control in ('fixed','random'):
            path=ROOT/f'experiments/reports/ac0_debug/v0_1/seed{seed}/{control}.json'
            views=public_views(path)
            for tolerance in (.15,.6):
                runs.append({'seed':seed,'controller':control,'source_artifact':path.relative_to(ROOT).as_posix(),
                    'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),**audit_views(views,tolerance)})
    result={'schema':'firstagi.ac0-codec-audit/v0.1','status':'finite-fixture-debug-not-gate',
            'encoding_version':OperationCodec.version,'source_commit':commit,'source_dirty':dirty,
            'python':sys.version,'platform':platform.platform(),
            'prediction_source':'each_public_candidate_encoded_directly_not_a_kernel_proposal',
            'actual_provenance_established':False,'kernel_selected_actions':0,
            'tolerances_are_diagnostic_only_not_confirming_thresholds':[.15,.6],'runs':runs}
    raw=(json.dumps(result,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open('xb') as handle:handle.write(raw)
    with args.out.with_suffix(args.out.suffix+'.sha256').open('x',encoding='utf-8') as handle:
        handle.write(hashlib.sha256(raw).hexdigest()+'  '+args.out.name+'\n')
    print(json.dumps([{k:v for k,v in r.items() if k!='records'} for r in runs],indent=2))


if __name__=='__main__':main()
