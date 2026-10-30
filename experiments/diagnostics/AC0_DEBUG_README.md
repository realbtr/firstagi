# AC0 event baseline v0.1 — debug scaffold, not a passed gate

This is the first executable action/outcome boundary for C-15. It uses the
existing `TextDriver` and `LearningSystem` as an **observer** of completed
transitions. The core does not yet select an operation, predict its outcome,
or update support for one named Gen from external evidence.

## Run

```powershell
python experiments/diagnostics/ac0_event_baseline.py --seed 41 --attempts 48 --out <new-directory>
python -m pytest -q tests/test_ac0_event_baseline.py
```

The directory must be new. Output includes fixed/random/oracle JSON traces,
source commit and dirty flag, core outcomes/Gen references, and SHA-256 receipts.
The environment trace repeats for the same seed/controller/budget. Random
UUIDs in existing core objects mean full JSON bytes need not repeat. Hashes
pin a particular artifact, not semantic correctness or repeatability of UUIDs.

## What the environment does

Two channels each have two opaque cue states and two opaque operations.
The sandbox owns a seeded hidden operation table. A successful operation
advances that channel to its other cue. A mismatch is observed divergence.
An interrupted/unavailable/cancelled attempt leaves the cue pending; other
channels can continue. Control scheduling is fixed alternation, **not learned**.

The controller view contains only channel, cue and available operations.
Expected/actual observations are written to the evaluator trace after an
attempt. The **oracle** intentionally has privileged access to the operation
table; fixed and random controllers do not. There is no LLM or network call.

Every attempt costs one synthetic budget unit, including unknown outcomes.
This is an attempt count, not CPU time, energy or measured local-frontier work.
The diagnostic injects unknowns at positions 3/5/7 modulo 12 for every control.
Changing this schedule is a new fixture, not evidence of general competence.

`TransitionEvent` means the operation and its external outcome (ONTOLOGY).
`prediction_support` here is relative to the **fixture task target**, explicitly
not a learned Gen prediction. Core `StepOutcome` values remain separate.
`CoreObserver` feeds completed cue/operation/outcome triples through the
existing text driver. The shared core context is not restored per channel;
this is not an AC1 continuity mechanism. Unknown events feed no core tokens;
that adapter rule is tested but does not prove native kernel handling of
interruptions. Duplicate delivery to this in-memory observer is rejected;
durable idempotency and partial-update recovery are not implemented.

The trace validator checks contiguous sequence, prior event in the same
channel, allowed operation/cost, observed outcome and support consistency.
Tests include tampered causal edges, fabricated success, coerced unknowns,
duplicate delivery and answer leakage through the controller view.

## What is still missing

- Learned operation/channel choice using existing proposals rather than a
  domain solver in the adapter; a full causal path for one useful Gen.
- Independent Gen-specific support updates, actual local-frontier counters.
- Frozen-model and held-out probes, a split preventing target leakage, and
  numerical success/retention/cost thresholds committed before confirming runs.
- Runtime restoration, checked immutable topology deltas and clean inheritance.

This fixture is a **debug scaffold**, not preregistration, skill acquisition,
passed AC0, or evidence for <=10M/200B+ reasoning parity. Its role is to make
the next missing mechanism executable and falsifiable. See the
[operational contract](../../FIRSTAGI_OPERATIONAL_PROTOCOL.md).

## Before wiring proposals to actions

The [operation readiness audit](../reports/ac0_debug/PROPOSAL_READINESS.md)
finds exact operation-feature aliases on seed42 and a before-token versus
after-observation proposal phase mismatch. Run
`python experiments/diagnostics/ac0_proposal_readiness.py --out <new-file.json>`.
This audit selects no actions and does not modify the core or driver vocabulary.

A separate experimental [operation codec boundary](../reports/ac0_debug/CODEC_BOUNDARY.md)
now checks public identity encoding, candidate margins and declared frames. It
is not connected to the original observer or a learned action controller.

The separate [coded observer/native proposal probe](../reports/ac0_debug/KERNEL_BINDING.md)
now feeds the codec to LearningSystem and revalidates actual live Gen/feature
state. Its unseeded native-context runs yielded zero bound operation candidates;
the original TextDriver diagnostic above remains unchanged.

A [paired learned-prefix recall ablation](../reports/ac0_debug/RECALL_ABLATION.md)
now compares native/default recall, an explicit existing-chain prefix adapter
and a minus-long-Gen control on copies of the same finalized warmup state.
Candidate coverage is measured separately from action quality; no actions execute.

Named-Gen outcome replay: [report](../reports/ac0_debug/OUTCOME_EVIDENCE.md), external receipts separate prediction agreement from task success; in-sample debug, no AC0 pass.

Next goal-choice design: [registered protocol v1](../reports/ac0_debug/GOAL_CHOICE_PROTOCOL_v1.md). Registered v1 confirming result is now available below; goal selection remains an explicit scaffold, not an AC0 pass.

Frozen-query development check: [128 immutable queries, conflict-preserving selector](../reports/ac0_debug/FROZEN_QUERY.md). This historical development probe had no task-quality score; the paired confirming report is linked below.

Paired evaluator: [development controls and training-Gen receipts](../reports/ac0_debug/PAIRED_GOAL_DEVELOPMENT.md); confirming101–108 were subsequently run once under the registered protocol (report below).

Registered result: [eight-seed frozen-goal scaffold pass](../reports/ac0_debug/GOAL_CHOICE_CONFIRMING_v1.md). Stable416/416 versus fixed/random212/416; swapped0/416. AC0 remains unpassed. Raw, completion, audit and costs are preserved.
