"""P1-a: derived process view over the operation ledger; component tests, not a gate."""
import pickle
from dataclasses import replace

from core.dependent_process import process_views
from tests.test_operation_evidence import begin, learn_native_chain, receipt, setup_system


def execute(system, atoms, seq, outcome, known):
    """One observed execution; binds a native chain on a first-seen outcome."""
    begin(system, atoms, seq, tuple(known.values()))
    system.accept_operation_outcome(replace(receipt(atoms, seq), outcome_gen_id=atoms[outcome]))
    if outcome not in known:
        gen = learn_native_chain(system, outcome)
        system.bind_operation_evidence(gen.gen_id, f"r{seq}")
        known[outcome] = gen.gen_id


def test_single_outcome_point_is_not_a_process():
    system, atoms = setup_system()
    known = {}
    for seq in range(3):
        execute(system, atoms, seq, "actual", known)
    view, = process_views(system)
    assert not view.is_bifurcation and view.status == "none"
    assert (view.executions, view.hidden_executions, view.detected_seq) == (3, 3, None)


def test_divergent_outcome_opens_a_process_at_first_difference():
    system, atoms = setup_system()
    known = {}
    for seq, outcome in enumerate(["actual", "actual", "other-actual", "actual"]):
        execute(system, atoms, seq, outcome, known)
    view, = process_views(system)
    assert view.is_bifurcation and view.status == "active"
    assert view.outcomes == (atoms["actual"], atoms["other-actual"])
    assert (view.detected_seq, view.hidden_executions) == (2, 2)
    # The contradicted Gen had an origin and one fulfilled forecast: admitted.
    assert (view.failed_forecasts_at_detection, view.failed_admitted_at_detection) == (1, 1)


def test_unadmitted_forecast_failure_is_not_counted_as_confident():
    system, atoms = setup_system()
    known = {}
    for seq, outcome in enumerate(["actual", "other-actual"]):
        execute(system, atoms, seq, outcome, known)
    view, = process_views(system)
    assert (view.failed_forecasts_at_detection, view.failed_admitted_at_detection) == (1, 0)


def test_cancelled_and_unknown_executions_are_not_outcomes():
    system, atoms = setup_system()
    known = {}
    execute(system, atoms, 0, "actual", known)
    begin(system, atoms, 1, tuple(known.values()))
    system.cancel_operation("life", "channel")
    begin(system, atoms, 2, tuple(known.values()))
    assert system.accept_operation_outcome(
        replace(receipt(atoms, 2), status="unknown", outcome_gen_id=None)) == "unknown"
    view, = process_views(system)
    assert (view.executions, view.cancelled, view.is_bifurcation) == (1, 1, False)


def test_view_is_a_pure_read():
    system, atoms = setup_system()
    known = {}
    for seq, outcome in enumerate(["actual", "other-actual", "actual"]):
        execute(system, atoms, seq, outcome, known)
    before = pickle.dumps(system, protocol=5)
    assert process_views(system) == process_views(system)
    assert pickle.dumps(system, protocol=5) == before


def scope(atoms, operation="op"):
    return dict(instance_id="life", channel_id="channel",
                cue_gen_id=atoms["cue"], operation_gen_id=atoms[operation])


def test_bid_is_due_only_after_outcomes_diverged():
    from core.dependent_process import resolution_due
    system, atoms = setup_system()
    known = {}
    assert not resolution_due(system, **scope(atoms))
    execute(system, atoms, 0, "actual", known)
    execute(system, atoms, 1, "actual", known)
    assert not resolution_due(system, **scope(atoms))
    execute(system, atoms, 2, "other-actual", known)
    assert resolution_due(system, **scope(atoms))
    assert not resolution_due(system, **scope(atoms, "other-op"))


def test_refused_request_is_an_attempt_without_evidence():
    from core.learning import OperationReceipt
    system, atoms = setup_system()
    known = {}
    for seq, outcome in enumerate(["actual", "other-actual"]):
        execute(system, atoms, seq, outcome, known)
    evidence = system.base.actual_evidence_entries
    for seq, refused in ((2, True), (3, False)):  # refused by the driver, then no slot
        system._begin_operation(command_address="opaque", seq=seq, **scope(atoms, "other-op"))
        if refused:
            assert system.accept_operation_outcome(OperationReceipt(
                f"r{seq}", "life", "channel", seq, "opaque", f"refused{seq}",
                status="unavailable")) == "unknown"
        system.cancel_operation("life", "channel")
    views = {v.operation_gen_id: v for v in process_views(system, atoms["other-op"])}
    move = views[atoms["op"]]
    assert (move.resolution_attempts, move.resolution_refused) == (1, 1)
    assert views[atoms["other-op"]].resolution_attempts == 0
    assert system.base.actual_evidence_entries == evidence
