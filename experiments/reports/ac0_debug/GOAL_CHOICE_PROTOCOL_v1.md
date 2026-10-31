# AC0 next experiment: goal choice from frozen learned dynamics v1

Status: **registered design; implementation and confirming results absent**.
Machine-readable contract: `../../protocols/ac0_goal_choice_v1.json`.
Starting code: `8fa759c6d908a98d7a3c03c02b51a62cd34b595b` (PR22).
This protocol must be committed and published before using its confirming seeds.

The last replay produced77 correct outcome predictions,57 of them predicting
task failure. The next falsifiable question is: do the learned chains contain
enough usable dynamics to select an operation toward a stated goal on fresh
episodes? The explicit goal selector is an experimental scaffold. Even meeting
every threshold does **not** establish native kernel action selection or AC0.
An insufficient result is useful and must not trigger seed replacement.

## Task, information and split

Use TwoChannelWorld and OperationCodec unchanged for training. Eight task seeds
101–108 each receive96 random-fixture attempts, alternating channels, RNG
`random.Random(task_seed+1000)`, native recall only. Unknown slots3/5/7 modulo12
remain interrupted/unavailable/cancelled. This gives72 observed and24 unknown
attempts,240 actual core tokens per seed. Finalize the pending chain once, as
in recall ablation, before freezing. Do not extend training if coverage is poor.
Development/smoke may use41/42 only. Do not inspect confirming-seed outcomes
until protocol and implementation commits, mechanical checks and budgets freeze.

For each task seed, construct64 new one-action episodes: channel index0/1 ×
initial phase0/1 ×16 repeats. Build this list in channel/phase/repeat order,
then shuffle with its paired schedule seed1101–1108. Continue the same RNG to
shuffle the two available operations separately for each episode. Store this
schedule before evaluating policies. RNG for random-policy choices is a separate
`random.Random(schedule_seed+20000)`; precompute64 choices by episode index.
Do not consume its draws conditionally on any other policy or outcome.

Each policy/condition receives a fresh world with the task seed and evaluator-set
initial phase for that episode. Controller receives **only** channel ID, cue ID,
available operations in scheduled order, and `goal_observation_id`: the channel's
target outcome ID. Giving a desired outcome is part of task specification; it
does not provide which operation reaches it. Controllers never receive a world
object, phase, answer table or evaluator success label. Public goal must be
logged before decision. The evaluator alone sets/reset phases and reads targets.

The test uses familiar opaque IDs and rules with new reset episodes/schedules;
it does not test unseen cues, new tasks, cross-channel transfer or inheritance.
No need to reject a trajectory that happens to overlap warmup: the claim is
explicitly episodic resampling, not unseen transitions. Coverage gaps stay in
the denominator. The two channels are independently reset, not one AC1 life.

## Frozen predictor and explicit selector

Freeze the entire finalized observer per seed. Serialize with pickle protocol5
and SHA-256 before and after every prediction query; abort on changes, including
Gen significance/counters, feature registrations, provenance, pending generalizer
chain or hidden predictor caches. Do not load peer-provided pickles. Existing
`model_fingerprint` omits runtime fields and alone is not this frozen-state check.

Important source constraint: `CodedKernelObserver.begin` calls `process_token`,
and `ContextBuffer.confirm_feature` calls `gen.confirm()`. Neither qualifies as
a frozen query. Use a separate ephemeral context: verify exact registered cue
anchor, activate pre-existing matching chains and advance their ActiveGen
position once to model the already-matched cue. A fresh InitiativeEngine may
propose against that context and the frozen base/hedonic state. Guard the frozen
state, feature origin and candidate decoding as in the current bindings. This
context plumbing must be tested before the confirming run; do not silently
relabel a discarded learning copy as frozen. No hand-built Gen in empirical runs.

For every current operation proposal, read the immediate next outcome feature
of that SAME Gen, requiring a unique channel/operation-matching origin and
registered feature. Retain all evidence, including competing Gen. For each
operation, reject it if verified forecasts disagree. Select only when exactly
one available operation has unanimous forecasts equal to the public goal;
otherwise abstain. Do not rank by UUID, list order, confidence, native counters
or a semantic teacher. There is no fallback action. Forecasts/action are sealed
before world.act; append the independent actual outcome and named-Gen evidence.
Training receipts must trace the selected Gen's creation to actual token events.

This is a **hand-specified goal selector over learned predictions**. It tests
the utility of those predictions in this scaffold, not whether core initiative
learned the goal-directed decision rule. Native policy and support-dependent
online reuse remain subsequent work requiring a separate protocol.

## Paired controls and rule change

Apply the identical public episode/operation-order/unknown schedule to:

| Policy | Learned state | Action |
|---|---|---|
| frozen_prefix_goal | Finalized frozen warmup | Explicit selector above |
| fixed_first | Same budget; no learning/query | First scheduled operation |
| random_uniform | Same budget; separate seeded RNG | Precomputed uniform choice |
| minus_long_gen_goal | Copy with all chain>1 Gen removed before freeze | Same selector |
| empty_goal | Empty frozen observer | Same selector |
| oracle_upper_bound | Evaluator-only answers, labelled privileged | Correct operation |

Run two conditions from the same frozen models and episode schedules. `stable`
retains answers. `all_cue_answers_swapped` replaces the correct operation by the
other operation for every channel/phase without changing IDs, goal or observations.
The evaluator alone applies this change; no controller gets the condition label.
Oracle uses the condition's answers, remains separate and is never a proposal
source. No condition updates model/support or feeds outcomes into later decisions.
Changed-rule negatives test evidence semantics, not adaptation/recovery.

Episodes13/14/15 modulo16 are scheduled unknown:12 per64, with4 occurrences
of each status. Indices are zero-based. Unknown opportunities do not become
negative Gen evidence. An abstention has no world.act and cost0; nevertheless
record its scheduled episode, unknown status and opportunity in the paired log.
An observed opportunity with abstention is a task failure. Never exclude it
because no forecast/action exists. Every seed has52 observed opportunities,
regardless of its controller's coverage. No ratio uses only emitted actions.

## Frozen numeric criteria, interpretation and budget

For each seed/policy/condition report goal successes and action coverage divided
by52 observed opportunities, plus all64 opportunity counts, actual action costs,
unknown status counts and prediction evidence separately. Compare paired seed
rates; the primary aggregation is equal-weight mean across all8 seeds. Also
report micro totals and every per-seed rate, without treating repeated episodes
as independent model-training seeds. These are engineering thresholds, not a
population-significance test or proof about reasoning in general.

The stable scaffold passes this **bounded diagnostic** only if all hold:

- Macro goal success and action coverage each ≥0.80.
- Paired macro goal-success advantage ≥0.15 over EACH fixed and random policy.
- Advantage ≥0.20 over EACH minus-long and empty policy.
- For EACH of those four comparators, strictly positive paired difference in
  at least6/8 seeds. No seed or comparator selection after results.
- Stable observed prediction receipt accuracy ≥0.90 (all emitted forecasts,
  correct / observed; unknown excluded and separately counted). An empty
  prediction denominator fails; all raw receipts remain available.
- Every frozen-state/information/budget invariant holds. Independently report
  the oracle upper bound; it does not rescue a failed learned-policy criterion.

Rule-change evidence check: at least32 observed named-Gen prediction receipts
across all seeds for frozen_prefix_goal and negative fraction ≥0.50 among them.
If there are fewer receipts, mark this check insufficient rather than silently
passing it. Do not combine unknown with negative. This check is separately
reported and is not a claim that the frozen controller adapts.

Budgets:768 training attempts/1920 training core tokens;6144 evaluation
opportunities maximum (8×64×6×2), at most one action per opportunity. Each learned
query visits at most4096 Gen records and12288 feature/origin lookups. Include
full scans as visits, including records rejected by prefix; do not count only
returned candidates. Every repeated base scan counts again. At most32MiB
serialized frozen observer per seed; whole run wall limit300s. Clock starts
before first training attempt and includes snapshots/serialization/evaluation/
raw writing. If exceeded, preserve partial data and mark incomplete, without
extending budgets, dropping seeds or turning wall time into an abstention.
Count codec work, actual core tokens, scans, feature lookups, serialized bytes
and wall time separately. Equal external opportunity budgets are not equal
compute; oracle has privileged access. Full-system energy/memory bounds absent.

## Release of the experiment

Before confirming data: commit this JSON/Markdown and the implemented runner;
record both commits and raw protocol SHA. Run source-boundary, frozen-state,
paired-schedule, denominator, abstention, unknown/negative, ablation and cost
counter tests on development seeds. Test-only fabricated positive Gen must
remain clearly separate from empirical runs. No confirming seeds in unit tests.
Publish the implementation's exact reproducible command before running it.

Afterward publish every seed/condition/policy, failures/partial runs, environment,
protocol/implementation commits, raw schedule/event/prediction/evidence traces,
model checksums and source checks with SHA receipts. Report protocol deviations
and inconclusive/failed thresholds. Fixes after outcome inspection require a
new protocol version and a fresh confirming pool, not overwritten v1 data.
No results were produced when registering this protocol. No AC0–AC4 or10M/200B+
claim is authorized by this design, even if every scaffold threshold passes.
