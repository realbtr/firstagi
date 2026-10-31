# Coded observations and live native proposal binding

2026-10-30 · C-15 / PR22 · **debug probe, no passed gate**.

## What now reaches the kernel

A separate experimental observer feeds real public cue anchors and completed
cue→operation / operation→actual-observation edges through the existing
Feature, PeripheralToken and LearningSystem APIs. Transport role is included
in the versioned key. The earlier cue→operation encoding is unchanged (tested).
The original TextDriver observer and all earlier raw reports remain unchanged.

After processing the current cue, the adapter calls InitiativeEngine.propose
again. This is a fresh after-cue call, not relabelled last_proposals. It checks
the active Gen's expected registered feature against provenance recorded when
actual tokens were ingested. A binding captures core step, context including
chain position/counters, registered feature contents and its observed origin.
Before decoding, it rechecks the live state and current cue/channel/sequence.
Changes to a token step, context, feature, origin or Gen counters abstain.
Substituting another vector under a live feature ID also fails the check.

Bindings remain local diagnostic structures, not authenticated permissions or
security against arbitrary code in the process. A decoder never executes an
action. Gen support from external task success is still not implemented.

## Unseeded native-context probe

Four48-attempt fixture streams: fixed/random controllers, seeds41/42. No oracle,
manual Gen insertion, manually activated long chain or alternate recall policy
is used. Each trial explicitly resets runtime context before its cue (a debug
scaffold, **not AC1 continuity**). Every cue is observed, even if the subsequent
operation outcome is unknown; unknowns feed no invented action/outcome tokens.

|Seed|Fixture|Core tokens|Fresh native proposals|Bound operation candidates|Views with long prefix Gen present|Long Gen at end|
|---|---|---|---|---|---|---|
|41|fixed|120|3|0|38/48|6|
|41|random|120|3|0|32/48|11|
|42|fixed|120|2|0|39/48|6|
|42|random|120|3|0|34/48|15|

**Eleven fresh proposals, zero eligible current-cue operation bindings.** All
eleven were rejected for current cue/operation provenance. These are not eleven
incorrect actions: they were not executed. Every action still came from the
declared fixed/random fixture. Long prefix Gen were present in143/192 views,
but presence in the base did not make them actionable native predictions.

Source audit: AttractorEngine._load_context_for_feature only loads chain-length1
Gen on a matching prefix, with atomic fallback. That is a concrete mismatch with
assuming learned multi-step chains are recalled at each reset cue. This probe
does not establish that this filter alone causes the observed zero coverage;
context reset, learning dynamics, role/context and task utility also matter.
The next experiment should vary recall policy explicitly rather than silently
manufacturing the desired context or rewriting the core globally.

## Reproduce and validation

Source committed before data: `1c2a31a`; clean source checkout.
[Raw probe](kernel_binding/v0_1/probe.json) ·
[SHA-256 receipt](kernel_binding/v0_1/probe.json.sha256).
Raw receipt,120-token counts and unknown-outcome boundaries were rechecked.
Core UUIDs mean full raw bytes need not reproduce across executions.

```powershell
python experiments/diagnostics/ac0_kernel_binding.py --out <new-file.json>
python -m pytest -q tests/test_ac0_kernel_binding.py tests/test_ac0_operation_codec.py tests/test_ac0_event_baseline.py tests/test_ac0_proposal_readiness.py
```

Fourteen added test cases cover live mutation/relabel rejection, changed chain
position with the same feature ID, unknown statuses, unknown outcomes, duplicate
events, role encoding compatibility and oracle exclusion. The positive binding
unit fixture deliberately constructs a Gen/context by hand; it proves wiring
and rejection mechanics, **not learned recall**. The unseeded runs above never
use that fixture. Four AC0 modules:45 passed. Full suite: **1531 passed,3 skipped**,
59 existing datetime.utcnow warnings. No source under core/ changed.

## Next bounded test

Compare native atomic recall with an explicitly labelled experimental prefix
recall of already learned chains, under the same cue/stream/action budgets.
Log actual Gen/feature/cue provenance and abstentions. Do not assume that greater
candidate coverage means useful decisions: task utility, independent outcome
support, action reuse, held-out variants and frozen controls remain necessary.
Numeric confirming thresholds still need preregistration before skill claims.
No learned controller task score, AC0 pass, retention/inheritance or10M/200B+
comparison has been established by this diagnostic.
