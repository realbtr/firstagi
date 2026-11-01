"""A2 component contracts; trained fixtures are not an AC0 run."""
import pickle
from dataclasses import replace

import pytest

from core.algorithm import StepOutcome, StepResult
from core.feature import Feature, FeatureVector
from core.generalization import Generalization, PeripheralToken
from core.learning import OperationView
from tests.test_operation_evidence import linked_system, setup_system, receipt, learn_native_chain


def encoded(system, atoms):
    for i, (name, gid) in enumerate(atoms.items()):
        system.engine.register_feature(Feature(name, 0, 1, FeatureVector(delta_size=5.0 * i)))
    return system, atoms


def view(system, atoms, seq=20, goal="actual", menu=None, **kw):
    frame = OperationView("life", "channel", seq, atoms["cue"], atoms[goal],
                          menu or (("address-A", atoms["op"]), ("address-B", atoms["other-op"])),
                          PeripheralToken.new("channel", system.engine.get_feature("cue")), 10000)
    return replace(frame, **kw)


def another_relation(system, atoms, operation="op", outcome="other-actual", seq=100):
    gen = None
    for number in (seq, seq+1):
        system._begin_operation(instance_id="life", channel_id="channel", seq=number,
                                 command_address="training", cue_gen_id=atoms["cue"],
                                 operation_gen_id=atoms[operation],
                                 contributor_gen_ids=(gen.gen_id,) if gen else ())
        system.accept_operation_outcome(replace(receipt(atoms, number), command_address="training",
                                                outcome_gen_id=atoms[outcome]))
        for fid in ("cue", operation, outcome):
            system.generalizer.on_step_result(StepResult(
                StepOutcome.COMPLETED if fid == outcome else StepOutcome.CONFIRMED,
                PeripheralToken.new("channel", None), matched_feature_id=fid))
        system.generalizer.reset_chain()
        gen = system.base.search_by_chain(["cue", operation, outcome])[0]
        if number == seq:
            system.bind_operation_evidence(gen.gen_id, f"r{number}")
    return gen


def test_proposal_uses_post_cue_live_context_and_executes_without_external_selection():
    system, atoms, gen = linked_system()
    encoded(system, atoms)
    system.initiative._last_proposals = ["stale-token-proposal"]
    before = system.engine.step_count
    proposal = system.propose_operations(view(system, atoms))
    assert proposal.command_address == "address-A"
    assert proposal.tick > before and proposal.tick == system.engine.step_count
    assert gen.gen_id in dict(system.engine.context.active_positions())
    assert proposal.contributor_gen_ids == (gen.gen_id,)
    pending = system.begin_proposed_operation(proposal)
    assert pending.forecasts[0][0] == gen.gen_id
    with pytest.raises(ValueError, match="Stale"):
        system.begin_proposed_operation(proposal)


def test_forced_curriculum_core_gathers_unadmitted_forecast_after_one_origin():
    system, atoms = setup_system()
    encoded(system, atoms)
    system._begin_operation(instance_id="life", channel_id="channel", seq=0,
                             command_address="opaque", cue_gen_id=atoms["cue"], operation_gen_id=atoms["op"])
    system.accept_operation_outcome(receipt(atoms, 0))
    gen = learn_native_chain(system)
    system.bind_operation_evidence(gen.gen_id, "r0")
    assert not gen.operation_admitted
    frame = view(system, atoms, seq=1)
    pending = system.begin_operation(public_view=frame, command_address="address-A")
    assert pending.forecasts[0][0] == gen.gen_id
    system.accept_operation_outcome(replace(receipt(atoms, 1), command_address="address-A"))
    assert gen.operation_admitted
    assert [e.origin for e in gen.actual_evidence.values()] == [True, False]
    with pytest.raises(TypeError):
        system.begin_operation(public_view=frame, command_address="address-A", contributor_gen_ids=())


@pytest.mark.parametrize("reverse", [False, True])
def test_goal_and_menu_control_choice_without_uuid_or_order_tiebreak(reverse):
    system, atoms, _ = linked_system()
    encoded(system, atoms)
    another_relation(system, atoms, "other-op", "other-actual")
    menu = (("z-opaque", atoms["op"]), ("a-opaque", atoms["other-op"]))
    if reverse:
        menu = tuple(reversed(menu))
    assert system.propose_operations(view(system, atoms, menu=menu)).command_address == "z-opaque"
    assert system.propose_operations(view(system, atoms, goal="other-actual", menu=menu)).command_address == "a-opaque"


def test_unknown_goal_and_operation_abstain_instead_of_guessing():
    system, atoms, _ = linked_system()
    encoded(system, atoms)
    assert system.propose_operations(view(system, atoms, goal="other-actual")) is None
    assert system.propose_operations(view(system, atoms, menu=(("only", atoms["other-op"]),))) is None


def test_conflicting_fourth_contributor_is_not_hidden_by_top3_or_max_weight():
    system, atoms, gen = linked_system()
    encoded(system, atoms)
    # Redundant sufficient chains are component fixtures here, not separately learned claims.
    for _ in range(2):
        duplicate = pickle.loads(pickle.dumps(gen))
        duplicate.gen_id = Generalization.new().gen_id
        system.base.add(duplicate)
    conflict = another_relation(system, atoms)
    assert conflict.operation_admitted
    assert system.propose_operations(view(system, atoms)) is None
    pending = system.begin_operation(public_view=view(system, atoms, seq=21), command_address="address-A")
    assert len(pending.forecasts) == 4 and conflict.gen_id in {f[0] for f in pending.forecasts}


def test_token_only_gen_is_not_command_conflict():
    system, atoms, _ = linked_system()
    encoded(system, atoms)
    token = system.base.add(Generalization.new(feature_chain=["cue", "other-actual"]))
    token.success_count = 1000
    system.engine.context.add_active(token.gen_id)
    proposal = system.propose_operations(view(system, atoms))
    assert proposal and token.gen_id not in proposal.contributor_gen_ids


def test_tied_commands_abstain_and_near_tie_uses_registered_absolute_tolerance():
    system, atoms, _ = linked_system()
    encoded(system, atoms)
    another_relation(system, atoms, "other-op", "actual")
    assert system.propose_operations(view(system, atoms)) is None
    other = system.base.search_by_chain(["cue", "other-op", "actual"])[0]
    system.hedonic.novelty_score = lambda gid: 1 - 1e-12 if gid == other.gen_id else 1
    assert system.propose_operations(view(system, atoms)) is None
    system.hedonic.novelty_score = lambda gid: 1 - 1e-8 if gid == other.gen_id else 1
    assert system.propose_operations(view(system, atoms)).command_address == "address-A"


@pytest.mark.parametrize("change", ["new-cue", "context", "evidence"])
def test_stale_or_changed_competition_cannot_execute_saved_proposal(change):
    system, atoms, gen = linked_system()
    encoded(system, atoms)
    proposal = system.propose_operations(view(system, atoms))
    if change == "new-cue":
        system.propose_operations(view(system, atoms, seq=22, goal="other-actual"))
    elif change == "context":
        system.engine.context.remove_active(gen.gen_id)
    else:
        gen.actual_evidence = {}
    with pytest.raises(ValueError):
        system.begin_proposed_operation(proposal)
    assert not system._operation_pending


def test_scope_change_cannot_recall_foreign_links():
    system, atoms, gen = linked_system()
    encoded(system, atoms)
    frame = view(system, atoms, instance_id="other-life")
    assert system.propose_operations(frame) is None
    assert gen.gen_id not in system.engine.context.active_gen_ids()


def test_base_read_budget_counts_misses_and_stops_without_returning_stale_choice():
    system, atoms, _ = linked_system()
    encoded(system, atoms)
    system.propose_operations(view(system, atoms))
    for i in range(20):
        system.base.add(Generalization.new(feature_chain=[f"miss-{i}"]))
    with pytest.raises(OverflowError, match="INCOMPLETE"):
        system.propose_operations(view(system, atoms, read_limit=3))
    assert system._last_operation_proposal is None
    assert system._last_operation_read_work <= 3
    system.base.start_operation_reads(10000)
    try:
        visited = list(system.base.iter_operation_records())
    finally:
        reads = system.base.finish_operation_reads()
    assert reads == system.base.size() == len(visited)


def test_capacity_has_no_base_scan_and_evidence_counter_tracks_eviction_and_restore():
    system, atoms, gen = linked_system()
    assert system.base.actual_evidence_entries == 2
    old_all = system.base.all
    system.base.all = lambda: (_ for _ in ()).throw(AssertionError("hidden full scan"))
    system._operation_capacity(0)
    system.base.all = old_all
    restored = pickle.loads(pickle.dumps(system))
    assert restored.base.actual_evidence_entries == 2
    restored.base.remove(gen.gen_id)
    assert restored.base.actual_evidence_entries == 0


@pytest.mark.parametrize("field,value", [("read_limit", 0), ("seq", True), ("channel_id", "foreign")])
def test_invalid_frame_does_not_produce_a_command(field, value):
    system, atoms, _ = linked_system()
    encoded(system, atoms)
    with pytest.raises(ValueError):
        system.propose_operations(view(system, atoms, **{field: value}))



def test_desired_goal_is_not_ingested_as_an_observed_fact():
    system, atoms, _ = linked_system()
    encoded(system, atoms)
    goal = system.base.get(atoms["actual"])
    before = (goal.success_count, goal.stop_count, dict(goal.actual_evidence))
    system.propose_operations(view(system, atoms))
    assert (goal.success_count, goal.stop_count, goal.actual_evidence) == before


def test_isomorphic_gen_ids_do_not_encode_the_choice():
    from core.learning import LearningSystem
    source, atoms, _ = linked_system()
    renamed = LearningSystem()
    gens = source.base.all()
    ids = {g.gen_id: f"opaque-role-{len(gens)-i}" for i, g in enumerate(gens)}
    for old in gens:
        gen = pickle.loads(pickle.dumps(old))
        gen.gen_id = ids[old.gen_id]
        for role in ("key_id", "oper_id", "goal_id"):
            setattr(gen, role, ids.get(getattr(gen, role)))
        gen.parent_ids = [ids[p] for p in gen.parent_ids]
        gen.child_ids = [ids[p] for p in gen.child_ids]
        if gen.actual_link:
            gen.actual_link = (*gen.actual_link[:2], *(ids[v] for v in gen.actual_link[2:]))
            gen.actual_evidence = {k: replace(e, outcome_gen_id=ids[e.outcome_gen_id])
                                   for k, e in gen.actual_evidence.items()}
        renamed.base.add(gen)
    mapped = {name: ids[gid] for name, gid in atoms.items()}
    encoded(renamed, mapped)
    assert renamed.propose_operations(view(renamed, mapped)).command_address == "address-A"
