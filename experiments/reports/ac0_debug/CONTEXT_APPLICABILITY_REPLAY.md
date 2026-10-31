# Context replay: stored knowledge, active applicability and event closure differ

2026-10-31. **Saved-receipt replay on41/42, no new world/actions/outcomes,
no confirming run, no AC0 or twelve-link gate pass.**

The previous online development failure is now localized more precisely.
A filter that merely intersects the existing readout with the current live
operation frontier would remove none of its contributors in these256 queries.
The stale alternatives are already in live context. The synthetic readout
context is therefore not the sole explanation.

## Reproducible inputs and actual work

Runtime source: **eccd9300c0fdc01d59926838c68fcb5aed69c216**, clean at start.
Input: the single saved development run, SHA256
**04039391fb7a1bd46598e90b7665d11b529dcb9bce9217c080f088b81ebe4829**.
Only its prefix_online policy histories on41/42 are replayed.
Actions and actual receipts are fixed input, not newly selected or generated.

[Replay raw](online_feedback/v1/context_replay_20261031T0135.json),
[SHA](online_feedback/v1/context_replay_20261031T0135.json.sha256),
[completion](online_feedback/v1/context_replay_20261031T0135.json.completion.json).
Replay raw SHA256:
**35b1ca6656a6faaae3592eb8968d992dd5831c32c37f2f4032141713b49dd7fc**.
5158371bytes;4.1191823000553995seconds including raw/hash write;
1056 replayed native core tokens, **zero new world constructions/actions/outcomes**.
Gen UUIDs/hashes can differ on a later replay.

~~~powershell
py -m pytest tests/test_ac0_context_replay.py -q
py experiments/diagnostics/ac0_context_replay.py --out <fresh-replay.json>
~~~

The program checks the pinned input SHA before replay. New observer instances
consume the saved96 warmup receipts/seed, finalize context, and replay the128
saved prefix-online evaluation actions/receipts per seed. Every current query
must match the original forecast multiset by chain/operation/outcome and original
raw choice. UUIDs are intentionally excluded from this equality; duplicate
contributors remain counted. It captures each real cursor before/after native
tokens, not a manufactured cursor used for selecting a successful action.

## Measured distinctions

| Recorded replay event/query | Count |
|---|---:|
| Queries matching original forecast semantics and raw choice | 256/256 |
| Queries whose frozen readout contains a Gen outside the live operation frontier | 0/256 |
| Executed forecasts disagreeing with actual observed outcome | 60 |
| Such forecasts removed from live context but retained in base | 16 |
| Later readout reappearances after those removals | 16 |
| Such negative forecasts still active after feedback | 44 |
| Still waiting at their old outcome edge, with unchanged stop_count | 44 |

Counts are forecast occurrences/removal-reappearance events, not60 distinct Gen.
They cover prefix_online only, unlike the previous report's180 negatives across
three native policies. Original task scores are not re-estimated as new skill.

Witness from seed41: replay Gen3db8bcc3-ddd0-4714-a6c0-7d9ca2d1a111 at
episode32 predicts c36492adbb4bb95c, receives3fc31a98c7fd59a0, leaves live
context with stop0→1, and remains stored. At episode38 the same stored Gen
reappears in both the live operation frontier and readout.

At episode50 that same forecast is again contradicted by the executed outcome,
but remains live at cursor2, expecting the old outcome; stop_count stays2.
The native token outcomes are CONFIRMED/COMPLETED/COMPLETED. Completion of some
other branch is not confirmation of every forecast about this attempt.

## Source path and interpretation

1. CodedKernelObserver.begin explicitly resets the trial context, then
   exact-prefix recall activates all matching stored long chains before the cue.
   A prior deactivation is not a persistent applicability condition.
2. FrozenGoalPredictor separately reconstructs a context from all stored
   matching prefixes and preserves conflicting contributors. In these receipts
   its contributors are already live; replacing only this context source does
   not eliminate the measured conflicts.
3. In core/algorithm.py, step matches an incoming feature against all expected
   features. If any matches, confirm_feature advances matching Gen. The global
   _handle_refuted path runs only if none match. It does not grade every other
   waiting branch as negative for the same external operation attempt.
4. ContextBuffer.refute_feature removes active entries and increments their stop
   counts; it does not delete the persistent Gen from the base.

The third point is a **contract gap for this one-operation/one-outcome fixture**,
not an established universal bug in the kernel. In an interleaved stream, a
nonmatching branch may legitimately be waiting for a different event/channel.
Blindly removing every nonmatch on every token would be an unsupported fix.
An observed receipt can be positive for one prediction and negative for another;
a single global step outcome cannot substitute for event-scoped prediction
evidence. Unexecuted operations and unknown outcomes remain unknown.

The engineering distinction is now concrete: retain a learned support; determine
whether its forecast applies to this channel/cue/operation attempt; close that
attempt on actual evidence; decide separately what context persists into the
next attempt. Neither TTL nor deletion of historical knowledge supplies this
missing condition by itself. No canonical Abhidharma equivalence is inferred.

## A separately declared next comparison, not yet executed

[Shadow replay design v1](../../protocols/ac0_applicability_shadow_v1.json),
SHA256 **738b96c253066651c026028d15eb030ed4faf7b542db11c20adc22c300a8c925**,
is fixed before the new applicability-mask analysis.

Four readouts on the fixed saved prefix-online history:

- Original all-prefix contributors and unchanged unanimous public-goal selector.
- Its intersection with the live operation frontier (null-filter control).
- Original Gen forecasts compatible with the latest prior admitted actual
  receipt for that channel/cue/executed-operation key. With no such receipt,
  retain the forecast; never synthesize a missing Gen forecast from the table.
- An adaptive last-actual table from exactly the same permitted receipts.

Seal all shadow outputs before consuming the current actual receipt. Unknown or
withheld receipts never overwrite context. No evaluator block, rule label,
correct operation, future outcome or counterfactual unexecuted outcome is input.
The last-actual map is an explicit contextual proxy, not proven sufficient
regime inference or a native learned solution.

Budget:256 saved cases,1024 shadow queries,0 new world actions/outcomes/core
tokens,30seconds,2MiB raw. Report abstention/conflicts, agreement only for the
operation actually executed in the saved trajectory, Gen coverage and disagreement
with the saved action. **Do not report counterfactual task success or on-policy
recovery.** A table tie establishes no heterarchy advantage. Divergent proposed
actions keep unknown counterfactual outcomes and require a later separately
registered on-policy test.

This shadow comparison has not been run. The previous online protocol is
unchanged;201–208 remain ungenerated/untrained/unexecuted. No core patch,
support threshold retuning, history deletion or trial-reset workaround was made.

## Checks and limits

Five observational-census tests passed(1.35s): full pickle state preserved by
census; real cursor/completed-entry distinction; ambiguous/foreign origin
exclusion; semantic equality with duplicate contributors; reserved pool rejected
before replay observer construction. Full suite: **1619 passed,3 skipped,
59 existing utcnow warnings(33.96s)**.

This is a same-agent/same-core replay of known development receipts, not an
independent execution or a new rollout. The census only measures compatible
recorded forecast chains, not every possible meaning in the active context.
No alternative policy has demonstrated useful recovery. Full continuous life,
inheritance, twelve-link functional correspondence and cessation are untested.

