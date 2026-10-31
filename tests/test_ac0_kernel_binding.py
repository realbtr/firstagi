from dataclasses import replace,asdict
import pytest
from core.generalization import Generalization
from experiments.diagnostics.ac0_event_baseline import TwoChannelWorld
from experiments.diagnostics.ac0_kernel_binding import CodedKernelObserver,run_probe
from experiments.diagnostics.ac0_operation_codec import OperationCodec


def hand_built_binding_fixture():
    """Positive wiring fixture, NOT a learned or native-recalled Gen claim."""
    observer=CodedKernelObserver()
    view={'channel_id':'public-channel','observation_id':'public-cue',
          'available_operations':('0123456789abcdef','fedcba9876543210')}
    cue=observer._ingest(view['channel_id'],view['observation_id'],view['observation_id'],'cue_anchor')
    op=observer._ingest(view['channel_id'],view['observation_id'],view['available_operations'][0],'cue_to_operation')
    gen=Generalization.new(feature_chain=[cue['canonical_feature_id'],op['canonical_feature_id']])
    gen.success_count=3
    observer.system.base.add(gen)
    observer.begin(view)
    # Explicitly manufactured active context; the unseeded diagnostic does not do this.
    observer.system.engine.context.add_active(gen.gen_id)
    observer.system.engine.context.confirm_feature(cue['canonical_feature_id'],observer.system.base)
    bindings,info=observer._fresh_bindings()
    binding=next(b for b in bindings if b.frame.gen_id==gen.gen_id)
    return observer,view,binding


def test_positive_binding_comes_from_current_kernel_expected_gen_feature():
    observer,view,binding=hand_built_binding_fixture()
    expected=observer.system.engine.context.get_expected_features(observer.system.base)
    assert expected[binding.frame.gen_id]==binding.frame.feature.feature_id
    result=observer.decode_current(binding)
    assert result['operation_id']==view['available_operations'][0]
    assert result['execution_authorized_by_this_check'] is False


@pytest.mark.parametrize('mutation',['token','context','feature','origin','gen_counter'])
def test_live_mutations_reject_a_previously_valid_binding(mutation):
    observer,view,binding=hand_built_binding_fixture()
    if mutation=='token':
        observer._ingest(view['channel_id'],'another','another','cue_anchor')
    elif mutation=='context':
        observer.system.engine.context.remove_active(binding.frame.gen_id)
    elif mutation=='feature':
        observer.system.engine._features.pop(binding.frame.feature.feature_id)
    elif mutation=='origin':
        observer.provenance[binding.frame.feature.feature_id]={('cue_anchor','x','x','x')}
    else:
        observer.system.base.get(binding.frame.gen_id).confirm()
    assert observer.decode_current(binding)['operation_id'] is None


@pytest.mark.parametrize('status',['interrupted','unavailable','cancelled'])
def test_unknown_event_does_not_create_fake_action_or_outcome_tokens(status):
    world=TwoChannelWorld(41)
    observer=CodedKernelObserver()
    channel=world.channels[0]
    cue,bindings,info=observer.begin(world.view(channel))
    before=observer.system.engine.step_count
    event=world.act(channel,world.operations[0],forced_status=status)
    assert observer.complete(event)==[]
    assert observer.system.engine.step_count==before==1  # real cue was observed
    with pytest.raises(ValueError,match='duplicate'):
        observer.complete(event)


def test_old_operation_encoding_is_preserved_after_role_extension():
    import hashlib,json
    codec=OperationCodec()
    original=json.dumps([codec.version,'cue_to_operation','c','q','o'],
                        ensure_ascii=False,separators=(',',':')).encode()
    assert codec.encode('c','q','o').feature_id=='op:'+hashlib.sha256(original).hexdigest()
    assert codec.encode_role('c','q','o','cue_anchor').feature_id!=codec.encode('c','q','o').feature_id


def test_unseeded_probe_does_not_use_oracle_or_manufacture_actions(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('oracle is not a proposal source')
    monkeypatch.setattr(TwoChannelWorld,'oracle_operation',forbidden)
    result=run_probe(41,'random',12)
    assert result['core_tokens']==30  # 12 cues + 9 completed pairs
    assert result['kernel_selected_actions']==0
    assert all(not r['completion_steps'] for r in result['records'] if r['fixture_event']['completion'] in {'interrupted','unavailable','cancelled'})


def test_relabelled_frame_vector_cannot_borrow_a_live_gen_id():
    observer,view,binding=hand_built_binding_fixture()
    wrong=observer.codec.encode(view['channel_id'],view['observation_id'],view['available_operations'][1])
    wrong.feature_id=binding.frame.feature.feature_id
    altered=replace(binding,frame=replace(binding.frame,feature=wrong))
    assert observer.decode_current(altered)['status']=='abstain_kernel_state_changed'


def test_repeated_expected_id_at_another_chain_position_invalidates_binding():
    observer,view,binding=hand_built_binding_fixture()
    gen=observer.system.base.get(binding.frame.gen_id)
    gen.feature_chain.append(binding.frame.feature.feature_id)
    bindings,_=observer._fresh_bindings()
    binding=next(b for b in bindings if b.frame.gen_id==gen.gen_id)
    observer.system.engine.context._active[gen.gen_id].advance()
    assert observer.decode_current(binding)['operation_id'] is None


def test_unknown_status_is_rejected_before_outcome_ingestion():
    world=TwoChannelWorld(41);observer=CodedKernelObserver();channel=world.channels[0]
    observer.begin(world.view(channel))
    event=world.act(channel,world.operations[0])
    before=observer.system.engine.step_count
    with pytest.raises(ValueError,match='unsupported completion'):
        observer.complete(replace(event,completion='untrusted-new-status'))
    assert observer.system.engine.step_count==before
