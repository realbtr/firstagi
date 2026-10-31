# Actual-context on-policy development (known tasks 41/42)

This is an explicit readout/actual-receipt sidecar scaffold, not native policy,
independent replication, a heterarchy advantage or an AC0/twelve-link gate.
The frozen design is `ac0_applicability_on_policy_dev_v1.json`, SHA256
`047058453db47b6229365b1929ab53066bed1a8c64544d96ed867fee58aaf29c`.
The original online protocol is unchanged; reserved seeds 201–208 are untouched.

## Preserved implementation failure before evaluation

Implementation c949a81055a6c353153debd5489a491587578af6, clean source:

```powershell
py experiments/diagnostics/ac0_applicability_on_policy.py --out experiments/reports/ac0_debug/online_feedback/v1/on_policy_dev_20261031T0537.json
```

The first attempt stopped on `paired training copy changed`: 96 warmup actions,
240 core tokens, **zero evaluation actions**, 0.324 seconds including write.
Raw SHA256 `00601d69969a5c7bf96bdbc115f75e2c409f5cfc74377fbfd05fe424ceb07012`,
278,296 bytes; the raw, SHA and incomplete completion receipt are retained.
It yields no task-quality result.

The implementation compared pickle bytes across deepcopy. Such bytes can
differ for equal state because unordered-container iteration and pickle memo
encoding are representation-dependent. The guard is replaced by a canonical
complete object-graph digest including runtime fields, mutable aliases and
receipt bookkeeping. Unsupported runtime objects fail closed. Physical model
cost still uses actual pickle byte lengths, including all stored sidecars/IDs.
Same-object immutable query guards in FrozenGoalPredictor are unchanged.
Tests check deepcopy equality and sensitivity to runtime/alias changes.

A new clean implementation commit precedes a fresh-path retry on the same
known development tasks; no design, seed, quality threshold, training length,
schedule or policy changes are permitted. This is an implementation repair,
not replacement of an unfavorable completed task result.

## Full rollout retained as incomplete: raw-output budget exceeded

Clean execution source **50a752ece7a1ebdc4d6827d3d3a7ac7d4ab7547e**:

```powershell
py experiments/diagnostics/ac0_applicability_on_policy.py --out experiments/reports/ac0_debug/online_feedback/v1/on_policy_dev_20261031T0540.json
```

[Raw actual execution](online_feedback/v1/on_policy_dev_20261031T0540.json),
[SHA](online_feedback/v1/on_policy_dev_20261031T0540.json.sha256),
[original completion](online_feedback/v1/on_policy_dev_20261031T0540.json.completion.json),
[diagnostic audit](online_feedback/v1/on_policy_dev_20261031T0540.audit.json).
Raw SHA256 **b565e4d6df5f35e1da49ec145b11586054dcee28f408bcb6f7c23547fd771dee**.

All scheduled actions finished: 192 warmup + 1,536 evaluation = 1,728 world
actions, 480 warmup / 2,168 total native core tokens. Wall time including raw
write: 12.806 seconds. The formatted raw JSON is **35,160,493 bytes**, above
the unchanged **33,554,432-byte** cap by 1,606,061 bytes. Therefore the original
completion is **incomplete**, despite all descriptive quality checks being true.
**Complete-budget pass and development-candidate pass are false.**

Both attempts are retained: aggregate work this cycle was 288 warmup actions,
1,536 evaluation actions, 1,824 total world actions, 2,408 total core tokens.
There was only one full evaluation trajectory per policy/seed; no quality
result was dropped or repeated. No further rollout was run to obtain a pass.

The future writer now uses compact JSON without removing evidence fields.
Serializing the same saved object compactly would take 20,605,784 bytes; that
calculation executes no model/world. It **does not change this run's original
receipt, budget failure or status**. Both the artifact size and inspection
exception are visible to reviewers; thresholds/design are unchanged.

## Descriptive own-action observations, not a completed protocol pass

Each policy has a private evolving model/history initialized from one shared
finalized 96-action warmup per seed. Evaluation receipts are never exchanged.
The public input is only channel, cue, operations and public goal. A sealed
readout precedes each real action/outcome. The masked variant may retain only
existing verified Gen forecasts compatible with its own prior actual receipt;
it cannot manufacture a Gen forecast from the sidecar table.

The unchanged 4 x 32 schedule flips channel 0 after block 0. Block 1 withholds
channel-0 outcomes from gated policies. The final window has **10 observed
outcomes per channel/policy/seed**, separate from scheduled unknown outcomes.

| Policy | Late changed, seed41 | Late changed, seed42 | Late stable, seeds41/42 | Changed during withdrawal, seeds41/42 |
|---|---:|---:|---:|---:|
| Original prefix online | 4/10 | 6/10 | 10/10, 10/10 | 3/10, 4/10 |
| Prior-actual-compatible Gen | 10/10 | 10/10 | 10/10, 10/10 | 4/10, 7/10 |
| Same, feedback gated | 10/10 | 8/10 | 10/10, 10/10 | 0/10, 0/10 |
| Adaptive table | 10/10 | 10/10 | 10/10, 10/10 | 4/10, 8/10 |
| Adaptive table, feedback gated | 10/10 | 10/10 | 10/10, 10/10 | 0/10, 0/10 |
| Random uniform | 5/10 | 5/10 | 5/10, 4/10 | 6/10, 4/10 |

All 20 late changed choices of original prefix are fallback: its 10 successes
are random recovery, **zero Gen-supported successes**. Unwithdrawn masked Gen
has 20/20 late changed nonfallback successes. Gated masked seed41 has 10/10
nonfallback; seed42 has 6 nonfallback successes plus 2 successes among 4 random
fallbacks. Its 8/10 must not be described as eight learned choices.

The table matches or exceeds late recovery; this establishes **no heterarchy
advantage**. Gating jointly withdraws actual input to native learning and to
the explicit sidecar, so the contrast cannot isolate which of those mechanisms
caused the difference. Small known-task counts are descriptive, not population
significance or fresh-task confirmation. Every policy has 80 observed and 48
unknown evaluation outcomes; unknowns are not scored as failures/successes.

## Named Gen witnesses and remaining coverage gap

Across masked policies there are **58 repeated changed-channel joins involving
8 distinct Gen IDs** (two per policy/seed): seed41 online19 / gated10, seed42
online23 / gated6. Three joins use an earlier Gen creation, 55 an earlier native
positive-support update. Total stable+changed native joins: 334.

These are time-ordered, same-policy provenance joins, not causal necessity
ablations. The unanimous selector does not use a success-count weight; an
increased counter alone does not explain the selected action.

A concrete creation example in seed41 gated policy: Gen
`538e299c-93ee-4328-8d53-ceedba577f53` first appears in feedback at episode94,
with the cue -> operation -> observed-goal feature chain witnessed by its own
actual core steps431/432/433. At episode96 that same Gen forecasts operation
`e6e9d6a12a8161e5` and outcome `c36492adbb4bb95c`; the policy executes that
nonfallback action and observes the predicted goal. The update is a real
native chain creation through process_token, without direct counter assignment
or persistent Gen deletion. Trial-reset/exact-prefix/readout scaffolds remain.

For gated seed42, all four observed late fallbacks (episodes96,98,104,112)
have two known operation keys and one table-goal-eligible key, but **zero
matching goal forecasts in the verified original Gen readout**. Two random
fallbacks happen to succeed. This localizes a verified forecast-coverage gap;
it does not yet distinguish missing native creation from retrieval/encoding.

## Integrity, cost and reproduction

The recorded-data audit reconstructs each policy's own past actual map, checks
1,536 seals/choices/receipts, named-chain provenance, executed-only prediction
grading, admission, coverage, bookkeeping and 308 post-begin unknown/withheld
native guards. No current/future/foreign receipt can select the current action.
Read-only inspection explicitly requires acknowledgement of the size failure:

```powershell
py experiments/diagnostics/ac0_on_policy_audit.py --raw experiments/reports/ac0_debug/online_feedback/v1/on_policy_dev_20261031T0540.json --inspect-incomplete
py -m pytest -q
```

The audit reports consistent saved data, zero new world actions, **original
completion incomplete / complete-budget pass false**. It is a same-agent
consistency check, not independent execution. Eight recorded-data tests reject
seal/history/Gen/unknown-native/receipt-count/duplicate/causal-order tampering.
Eighteen controller tests cover admission, key/history isolation, no synthetic
Gen, duplicate-before-update, reserved-pool rejection, budget/fresh outputs and
the full-state copy guard. Full suite: 1667 passed, 3 skipped, 59 existing
utcnow warnings (33.83 seconds locally).

Largest serialized retained stores: masked online196,516 bytes, masked gated
192,355; table online14,469, table gated16,261; original prefix190,988. Every
controller report includes observer, native policy receipt IDs, actual context
and its receipt IDs, and delivery IDs; up to eight actual-context value keys.
Observer bookkeeping is included inside observer bytes, not omitted as a
"small model" exception. Original-prefix control also maintains an unused
diagnostic actual map; this cost is included. Shared training logs, evidence
records, token witnesses and joining indexes are evaluator audit artifacts,
not inputs to action selection, and their full cost is in raw-output size.
This is not an equal-compute/CPU/energy or total-process-RSS comparison.

Next: replay **only the recorded gated seed42 actual history**, without new
world actions/outcomes, to localize its four missing goal forecasts to native
chain creation, verified retrieval or encoding. Keep the compact writer repair
reviewable; do not repeat this trajectory to retroactively erase the failure.
Any future confirming design needs separate review/registration. AC0–AC4,
continuous life, inheritance and full conditioned arising/cessation remain open.
