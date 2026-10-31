from dataclasses import asdict,replace
import hashlib,json
import math
import pytest
from core.feature import Feature,FeatureVector
from experiments.diagnostics.ac0_operation_codec import (
    OperationCodec,PredictionFrame,decode_prediction,
)


def fixture():
    codec=OperationCodec()
    view={'channel_id':'public-channel','observation_id':'public-cue',
          'available_operations':('0123456789abcdef','fedcba9876543210')}
    feature=codec.encode(view['channel_id'],view['observation_id'],view['available_operations'][0])
    frame=PredictionFrame(view['channel_id'],view['observation_id'],7,'after_cue',
                          codec.version,'fixture-Gen-not-learned',feature)
    return codec,view,frame


def test_former_equal_shape_alias_is_distinguishable_without_vocabulary():
    codec,view,frame=fixture()
    other=codec.encode(view['channel_id'],view['observation_id'],view['available_operations'][1])
    assert other.vector.distance_to(frame.feature.vector)>0
    assert other.feature_id!=frame.feature.feature_id
    assert decode_prediction(frame,view,7,tolerance=.15)['operation_id']==view['available_operations'][0]


def test_encoding_is_order_independent_and_preserves_channel_and_cue_identity():
    codec,view,frame=fixture()
    fresh=OperationCodec()
    fresh.encode('other','other','other')
    assert asdict(fresh.encode(view['channel_id'],view['observation_id'],view['available_operations'][0]))==asdict(frame.feature)
    assert fresh.encode('other',view['observation_id'],view['available_operations'][0]).feature_id!=frame.feature.feature_id
    assert fresh.encode(view['channel_id'],'other',view['available_operations'][0]).feature_id!=frame.feature.feature_id


@pytest.mark.parametrize('change',[
    {'phase':'before_token'}, {'decision_seq':6}, {'channel_id':'another'},
    {'cue_id':'another'}, {'encoding_version':'another'}, {'gen_id':''},
])
def test_declared_stale_or_wrong_provenance_abstains(change):
    _,view,frame=fixture()
    result=decode_prediction(replace(frame,**change),view,7,tolerance=.15)
    assert result['operation_id'] is None
    assert result['status']=='abstain_frame_mismatch'


def test_exact_collision_abstains_even_for_an_exact_prediction():
    codec,view,frame=fixture()
    class CollidingCodec(OperationCodec):
        def encode(self,*args):
            return Feature('collision',0.,1.,FeatureVector())
    frame=replace(frame,feature=Feature('query',0.,1.,FeatureVector()))
    result=decode_prediction(frame,view,7,tolerance=.15,codec=CollidingCodec())
    assert result['status']=='abstain_ambiguous_candidates'
    assert result['operation_id'] is None


def test_overlapping_tolerance_balls_abstain_before_arbitrary_tie_break():
    codec,view,frame=fixture()
    class CloseCodec(OperationCodec):
        def encode(self,channel,cue,op):
            return Feature(op,0.,1.,FeatureVector(delta_size=0. if op==view['available_operations'][0] else .2))
    frame=replace(frame,feature=Feature('query',0.,1.,FeatureVector()))
    result=decode_prediction(frame,view,7,tolerance=.15,codec=CloseCodec())
    assert result['status']=='abstain_ambiguous_candidates'


@pytest.mark.parametrize('tolerance',[math.nan,math.inf,-.1])
def test_invalid_tolerance_cannot_enable_decoding(tolerance):
    _,view,frame=fixture()
    with pytest.raises(ValueError,match='tolerance'):
        decode_prediction(frame,view,7,tolerance=tolerance)


def test_nonfinite_query_and_duplicate_operations_are_rejected():
    _,view,frame=fixture()
    bad=replace(frame,feature=Feature('bad',0.,1.,FeatureVector(delta_size=math.nan)))
    with pytest.raises(ValueError,match='finite'):
        decode_prediction(bad,view,7,tolerance=.15)
    view={**view,'available_operations':('same','same')}
    with pytest.raises(ValueError,match='distinct'):
        decode_prediction(frame,view,7,tolerance=.15)


def test_no_matching_candidate_abstains_and_success_is_not_execution_authority():
    _,view,frame=fixture()
    far=replace(frame,feature=Feature('far',0.,1.,FeatureVector(delta_size=100.)))
    assert decode_prediction(far,view,7,tolerance=.15)['operation_id'] is None
    assert decode_prediction(frame,view,7,tolerance=.15)['execution_authorized_by_this_check'] is False


def test_raw_input_receipt_is_verified_before_candidate_extraction(tmp_path):
    from experiments.diagnostics.ac0_codec_audit import public_views
    path=tmp_path/'fixed.json'
    _,view,_=fixture()
    path.write_text(json.dumps({'events':[{**view,'expected_observation':'private-target',
                                         'chosen_operation':'private-choice'}]}))
    digest=hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path/'SHA256SUMS.json').write_text(json.dumps({path.name:digest}))
    extracted=public_views(path)
    assert set(extracted[0])==set(view)
    path.write_text('{"events":[]}')
    with pytest.raises(ValueError,match='hash mismatch'):
        public_views(path)
