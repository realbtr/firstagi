"""Experimental opaque-operation encoding and conservative decoding guards.

Pure transport fixture: no world answers, LLM, rewards or learned controller.
Six hash coordinates provide identity, not semantic similarity. Finite candidate
margins are checked on every decode; no global collision-freedom is claimed.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from core.feature import Feature,FeatureVector

VERSION='ac0-opaque-operation/0.1'


class OperationCodec:
    """Stateless, domain-neutral code for (channel, cue, available operation)."""
    version=VERSION

    def encode(self,channel_id:str,cue_id:str,operation_id:str) -> Feature:
        return self.encode_role(channel_id,cue_id,operation_id,'cue_to_operation')

    def encode_role(self,channel_id:str,source_id:str,target_id:str,role:str) -> Feature:
        if role not in {'cue_anchor','cue_to_operation','operation_to_observation'}:
            raise ValueError('unsupported transport role')
        if any(not isinstance(x,str) or not x for x in (channel_id,source_id,target_id)):
            raise ValueError('opaque IDs must be nonempty strings')
        raw=json.dumps([self.version,role,channel_id,source_id,target_id],
                       ensure_ascii=False,separators=(',',':')).encode('utf-8')
        digest=hashlib.sha256(raw).digest()
        coords=[2*int.from_bytes(digest[i:i+4],'big')/(2**32-1)-1
                for i in range(0,24,4)]
        return Feature(feature_id='op:'+digest.hex(),direction=0.,distance=1.,
                       vector=FeatureVector(*coords))


@dataclass(frozen=True)
class PredictionFrame:
    """Declared provenance; caller must establish it, this is not authentication."""
    channel_id:str
    cue_id:str
    decision_seq:int
    phase:str
    encoding_version:str
    gen_id:str
    feature:Feature


def _finite(feature:Feature) -> bool:
    return all(math.isfinite(v) for v in vars(feature.vector).values())


def decode_prediction(frame:PredictionFrame,view:dict,current_seq:int,*,
                      tolerance:float,codec:OperationCodec|None=None) -> dict:
    """Return a candidate or abstain, never execute an action.

    Balls around the available candidate vectors must be disjoint. Declared
    cue/channel/phase/seq/version must match; actual provenance establishment
    and deriving a prediction from a learned Gen are separate, unimplemented.
    """
    codec=codec or OperationCodec()
    if not math.isfinite(tolerance) or tolerance<0:
        raise ValueError('tolerance must be finite and nonnegative')
    if not _finite(frame.feature):
        raise ValueError('prediction vector must be finite')
    if (frame.phase!='after_cue' or frame.decision_seq!=current_seq or
        frame.channel_id!=view['channel_id'] or frame.cue_id!=view['observation_id'] or
        frame.encoding_version!=codec.version or not frame.gen_id):
        return {'status':'abstain_frame_mismatch','operation_id':None}
    operations=tuple(view['available_operations'])
    if len(set(operations))!=len(operations):
        raise ValueError('available operation IDs must be distinct')
    candidates=[codec.encode(view['channel_id'],view['observation_id'],op) for op in operations]
    if any(not _finite(c) for c in candidates):
        raise ValueError('candidate vectors must be finite')
    margins=[a.vector.distance_to(b.vector) for i,a in enumerate(candidates)
             for b in candidates[i+1:]]
    minimum=min(margins) if margins else None
    if minimum is not None and minimum<=2*tolerance:
        return {'status':'abstain_ambiguous_candidates','operation_id':None,
                'minimum_candidate_distance':minimum}
    matches=[op for op,c in zip(operations,candidates)
             if frame.feature.vector.distance_to(c.vector)<=tolerance]
    if len(matches)!=1:
        return {'status':'abstain_no_unique_match','operation_id':None,
                'matching_candidates':len(matches),'minimum_candidate_distance':minimum}
    return {'status':'unique_candidate','operation_id':matches[0],
            'gen_id':frame.gen_id,'minimum_candidate_distance':minimum,
            'execution_authorized_by_this_check':False}
