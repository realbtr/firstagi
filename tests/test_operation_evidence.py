"""A1: actual evidence and lifecycle components, not native policy or AC0."""
import pickle
from dataclasses import replace

import pytest

from core.algorithm import StepOutcome, StepResult
from core.generalization import Generalization, PeripheralToken
from core.learning import LearningSystem, OperationReceipt


def setup_system():
    system = LearningSystem()
    atoms = {}
    for name in ("cue", "op", "other-op", "actual", "other-actual"):
        atoms[name] = system.base.add(Generalization.new(feature_chain=[name])).gen_id
    return system, atoms


def begin(system, atoms, seq, contributors=(), **kwargs):
    return system._begin_operation(instance_id="life", channel_id="channel", seq=seq,
                                  command_address="opaque", cue_gen_id=atoms["cue"],
                                  operation_gen_id=atoms["op"],
                                  contributor_gen_ids=contributors, **kwargs)


def receipt(atoms, execution_seq, **kwargs):
    return replace(OperationReceipt(f"r{execution_seq}", "life", "channel", execution_seq, "opaque",
                                     f"event{execution_seq}", outcome_gen_id=atoms["actual"]), **kwargs)


def learn_native_chain(system, actual="actual"):
    # Exercise the existing native GreedyGeneralizer, not manually filled Gen roles.
    # StepResults are a unit fixture; no claim of a driver/closed-loop experiment.
    for fid in ("cue", "op", actual):
        system.generalizer.on_step_result(StepResult(
            outcome=StepOutcome.COMPLETED if fid == actual else StepOutcome.CONFIRMED,
            token=PeripheralToken.new("channel", None), matched_feature_id=fid,
        ))
    system.generalizer.reset_chain()
    return system.base.search_by_chain(["cue", "op", actual])[0]


def linked_system():
    system, atoms = setup_system()
    gen = None
    for seq in (0, 1):
        begin(system, atoms, seq, (gen.gen_id,) if gen else ())
        system.accept_operation_outcome(receipt(atoms, seq))
        gen = learn_native_chain(system)
        if seq == 0:
            system.bind_operation_evidence(gen.gen_id, f"r{seq}")
    assert sum(e.origin for e in gen.actual_evidence.values()) == 1
    return system, atoms, gen


def test_origin_and_exactly_two_observations_admit_without_forged_forecast():
    system, atoms = setup_system()
    begin(system, atoms, 0)
    system.accept_operation_outcome(receipt(atoms, 0))
    gen = learn_native_chain(system)
    assert (gen.key_id, gen.oper_id, gen.goal_id) == (None, None, None)
    system.bind_operation_evidence(gen.gen_id, "r0")
    assert gen.actual_positive_count == 1 and not gen.operation_admitted
    assert next(iter(gen.actual_evidence.values())).origin
    with pytest.raises(ValueError, match="already has actual evidence"):
        system.bind_operation_evidence(gen.gen_id, "r0")
    begin(system, atoms, 1, (gen.gen_id,))
    token_counts = (gen.success_count, gen.stop_count)
    system.accept_operation_outcome(receipt(atoms, 1))
    assert gen.actual_positive_count == 2 and gen.actual_support == 1
    assert gen.operation_admitted
    assert not gen.actual_evidence[("life", "channel", 1)].origin
    assert (gen.success_count, gen.stop_count) == token_counts


def test_repeated_delivery_and_alias_for_same_execution_are_not_new_evidence():
    system, atoms, gen = linked_system()
    original = receipt(atoms, 1)
    assert system.accept_operation_outcome(original) == "duplicate"
    alias = replace(original, receipt_id="alias", source_id="redelivery")
    assert system.accept_operation_outcome(alias) == "duplicate"
    with pytest.raises(ValueError, match="already has actual evidence"):
        system.bind_operation_evidence(gen.gen_id, "alias")
    assert gen.actual_positive_count == 2


@pytest.mark.parametrize("field,value", [
    ("instance_id", "other-life"), ("channel_id", "other-channel"),
    ("seq", 99), ("command_address", "other-address"),
])
def test_wrong_actual_identity_does_not_mutate_pending_or_evidence(field, value):
    system, atoms, gen = linked_system()
    begin(system, atoms, 2, (gen.gen_id,))
    before = pickle.dumps(system)
    with pytest.raises(ValueError):
        system.accept_operation_outcome(receipt(atoms, 2, **{field: value}))
    assert pickle.dumps(system) == before


@pytest.mark.parametrize("status", ["unknown", "unavailable"])
def test_unknown_and_interruption_preserve_pending_until_actual_after_resume(status):
    system, atoms, gen = linked_system()
    begin(system, atoms, 2, (gen.gen_id,))
    unknown = receipt(atoms, 2, status=status, outcome_gen_id=None)
    assert system.accept_operation_outcome(unknown) == "unknown"
    system.set_operation_channel_interrupted("life", "channel")
    restored = pickle.loads(pickle.dumps(system))
    actual = receipt(atoms, 2, receipt_id="late-observed")
    with pytest.raises(ValueError):
        restored.accept_operation_outcome(actual)
    restored.set_operation_channel_interrupted("life", "channel", False)
    assert restored.accept_operation_outcome(actual) == "observed"
    assert restored.base.get(gen.gen_id).actual_positive_count == 3
    assert restored.operation_state_usage()["pending"] == 0
    assert gen.actual_positive_count == 2  # Original object was not resumed.


def test_cancel_late_actual_and_checkpoint_tombstones_do_not_make_negative_evidence():
    system, atoms, gen = linked_system()
    begin(system, atoms, 2, (gen.gen_id,))
    assert system.cancel_operation("life", "channel")
    assert not system.cancel_operation("life", "channel")
    system = pickle.loads(pickle.dumps(system))
    assert system.accept_operation_outcome(receipt(atoms, 2)) == "late_cancelled"
    gen = system.base.get(gen.gen_id)
    assert (gen.actual_positive_count, gen.actual_negative_count) == (2, 0)
    with pytest.raises(ValueError):
        begin(system, atoms, 2)
    with pytest.raises(ValueError):
        system.bind_operation_evidence(gen.gen_id, "r2")


def test_negative_means_prediction_mismatch_and_updates_all_frozen_contributors():
    system, atoms, gen = linked_system()
    # A second learned continuation is also admitted; force curriculum execution
    # with both predictions to test A1 accounting, not A2's ambiguity selector.
    other = learn_native_chain(system, "other-actual")
    for seq in (2, 3):
        begin(system, atoms, seq, (other.gen_id,) if seq == 3 else ())
        system.accept_operation_outcome(receipt(atoms, seq, outcome_gen_id=atoms["other-actual"]))
        if seq == 2:
            system.bind_operation_evidence(other.gen_id, f"r{seq}")
    begin(system, atoms, 4, (gen.gen_id, other.gen_id))
    system.accept_operation_outcome(receipt(atoms, 4))
    assert (gen.actual_positive_count, gen.actual_negative_count) == (3, 0)
    assert (other.actual_positive_count, other.actual_negative_count) == (2, 1)
    assert other.actual_support == pytest.approx(2 / 3)
    # One more mismatch reaches the strict >0.5 boundary without token rewards.
    for seq in (5,):
        begin(system, atoms, seq, (other.gen_id,))
        system.accept_operation_outcome(receipt(atoms, seq))
    assert other.actual_support == 0.5 and not other.operation_admitted


def test_conflicting_redelivery_and_mutated_forecast_fail_before_any_update():
    system, atoms, gen = linked_system()
    with pytest.raises(ValueError):
        system.accept_operation_outcome(receipt(atoms, 1, outcome_gen_id=atoms["other-actual"]))
    with pytest.raises(ValueError):
        system.accept_operation_outcome(receipt(atoms, 1, receipt_id="alias-conflict",
                                                outcome_gen_id=atoms["other-actual"]))
    begin(system, atoms, 2, (gen.gen_id,))
    gen.goal_id = atoms["other-actual"]
    assert not gen.operation_admitted
    before = pickle.dumps(system)
    with pytest.raises(ValueError):
        system.accept_operation_outcome(receipt(atoms, 2))
    assert pickle.dumps(system) == before


def test_manual_gen_role_mismatch_and_unknown_cannot_originate_evidence():
    system, atoms = setup_system()
    manual = system.base.add(Generalization.new(feature_chain=["cue", "op", "actual"]))
    begin(system, atoms, 0)
    system.accept_operation_outcome(receipt(atoms, 0))
    with pytest.raises(ValueError):
        system.bind_operation_evidence(manual.gen_id, "r0")
    with pytest.raises(ValueError):
        begin(system, atoms, 1, (manual.gen_id,))
    begin(system, atoms, 1)
    system.accept_operation_outcome(receipt(atoms, 1, status="unknown", outcome_gen_id=None))
    with pytest.raises(ValueError):
        system.bind_operation_evidence(manual.gen_id, "r1")


def test_token_only_gen_cannot_enter_command_evidence_and_does_not_change_it():
    system, atoms, gen = linked_system()
    token = system.base.add(Generalization.new(feature_chain=["other-actual"]))
    token.confirm()
    assert not token.operation_admitted
    with pytest.raises(ValueError):
        begin(system, atoms, 2, (token.gen_id,))
    begin(system, atoms, 2, (gen.gen_id,))
    system.accept_operation_outcome(receipt(atoms, 2))
    assert gen.actual_positive_count == 3 and not token.actual_evidence


def test_second_pending_and_other_channel_are_separate():
    system, atoms = setup_system()
    begin(system, atoms, 0)
    with pytest.raises(ValueError):
        begin(system, atoms, 1)
    system._begin_operation(instance_id="life", channel_id="other", seq=0,
                           command_address="opaque", cue_gen_id=atoms["cue"],
                           operation_gen_id=atoms["op"])
    system.accept_operation_outcome(receipt(atoms, 0))
    assert system.operation_state_usage()["pending"] == 1


def test_legacy_pickle_does_not_convert_old_token_counts_into_actual():
    system, atoms, gen = linked_system()
    gen.__dict__.pop("actual_evidence")
    gen.__dict__.pop("actual_link")
    gen.success_count = 1000
    for name in list(vars(system)):
        if name.startswith("_operation_"):
            delattr(system, name)
    del system.base._actual_evidence_entries  # This field did not exist in legacy checkpoints.
    restored = pickle.loads(pickle.dumps(system))
    gen = restored.base.get(gen.gen_id)
    assert gen.actual_positive_count == 0 and not gen.operation_admitted
    assert not any(restored.operation_state_usage().values())
    assert gen.success_count == 1000


def test_capacity_stops_before_partial_updates_and_retains_evidence():
    system, atoms, gen = linked_system()
    begin(system, atoms, 2, (gen.gen_id,))
    system._operation_record_limit = sum(system.operation_state_usage().values())
    before = pickle.dumps(system)
    with pytest.raises(OverflowError, match="INCOMPLETE"):
        system.accept_operation_outcome(receipt(atoms, 2))
    assert pickle.dumps(system) == before


@pytest.mark.parametrize("changes", [
    {"seq": True}, {"seq": -1}, {"status": "cancelled"},
    {"status": "unknown"}, {"outcome_gen_id": None}, {"source_id": ""},
])
def test_malformed_transport_receipt_rejected(changes):
    _, atoms = setup_system()
    with pytest.raises(ValueError):
        receipt(atoms, 0, **changes)



def test_source_event_cannot_be_replayed_as_a_different_execution():
    system, atoms, gen = linked_system()
    begin(system, atoms, 2, (gen.gen_id,))
    before = pickle.dumps(system)
    with pytest.raises(ValueError, match="replayed"):
        system.accept_operation_outcome(receipt(atoms, 2, source_id="event1"))
    assert pickle.dumps(system) == before


@pytest.mark.parametrize("change", ["chain", "outcome-encoding", "cue-encoding"])
def test_frozen_structural_change_is_rejected_before_actual_update(change):
    system, atoms, gen = linked_system()
    begin(system, atoms, 2, (gen.gen_id,))
    if change == "chain":
        gen.feature_chain = ["cue", "op", "other-actual"]
        assert not gen.operation_admitted
    elif change == "outcome-encoding":
        system.base.get(atoms["actual"]).feature_chain = ["mutated"]
    else:
        system.base.get(atoms["cue"]).feature_chain = ["mutated"]
    before = pickle.dumps(system)
    with pytest.raises(ValueError):
        system.accept_operation_outcome(receipt(atoms, 2))
    assert pickle.dumps(system) == before


@pytest.mark.parametrize("limit", [0, -1, True, 1.5])
def test_invalid_operation_budget_rejected(limit):
    with pytest.raises(ValueError):
        LearningSystem(operation_record_limit=limit)


@pytest.mark.parametrize("later_forecast", [False, True])
def test_second_origin_binding_is_rejected_without_partial_mutation(later_forecast):
    system, atoms = setup_system()
    begin(system, atoms, 0)
    system.accept_operation_outcome(receipt(atoms, 0))
    gen = learn_native_chain(system)
    system.bind_operation_evidence(gen.gen_id, "r0")
    begin(system, atoms, 1, (gen.gen_id,) if later_forecast else ())
    system.accept_operation_outcome(receipt(atoms, 1))
    before = pickle.dumps(system)
    with pytest.raises(ValueError, match="already has actual evidence"):
        system.bind_operation_evidence(gen.gen_id, "r1")
    assert pickle.dumps(system) == before
    assert sum(e.origin for e in gen.actual_evidence.values()) == 1
    assert gen.actual_positive_count == (2 if later_forecast else 1)
    assert gen.operation_admitted == later_forecast


def test_second_execution_can_refute_before_admission_without_second_origin():
    system, atoms = setup_system()
    begin(system, atoms, 0)
    system.accept_operation_outcome(receipt(atoms, 0))
    gen = learn_native_chain(system)
    system.bind_operation_evidence(gen.gen_id, "r0")
    begin(system, atoms, 1, (gen.gen_id,))
    system.accept_operation_outcome(receipt(atoms, 1, outcome_gen_id=atoms["other-actual"]))
    assert (gen.actual_positive_count, gen.actual_negative_count) == (1, 1)
    assert gen.actual_support == 0.5 and not gen.operation_admitted
    evidence = gen.actual_evidence[("life", "channel", 1)]
    assert not evidence.origin and not evidence.positive



def test_pre_h1_checkpoint_with_multiple_origins_is_not_admitted():
    system, atoms, gen = linked_system()
    key = ("life", "channel", 1)
    gen.actual_evidence[key] = replace(gen.actual_evidence[key], origin=True)
    system = pickle.loads(pickle.dumps(system))
    gen = system.base.get(gen.gen_id)
    assert gen.actual_positive_count == 2  # Preserve historical data, do not relabel it.
    assert not gen.operation_admitted
