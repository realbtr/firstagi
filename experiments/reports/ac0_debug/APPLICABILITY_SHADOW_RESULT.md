# Applicability shadows reduce ambiguity; verified forecast coverage still lags

2026-10-31. **Read-only shadows on fixed saved41/42 history. No new model
execution, core tokens, world actions or task outcomes. No on-policy recovery.**

A prior-actual compatibility condition reduces raw abstentions from84 to31
out of256 saved cases and removes the145 operation-query conflicts counted by
the original readout. The adaptive table abstains22 times. All9 extra masked
abstentions coincide with a table-supported goal alternative absent from the
verified original Gen forecasts. No forecast was invented to close that gap.

This tests the declared context/readout boundary. It does not show improved
behavior:33 masked choices differ from the action actually executed in the
saved history, so their counterfactual outcomes remain unknown.

## Source, design and actual work

Runtime source **cc2fc5bf500e97bf779c158ebec9f1559bac8953**, clean at start.
Declared shadow design SHA256:
**738b96c253066651c026028d15eb030ed4faf7b542db11c20adc22c300a8c925**.
It was committed before this analysis and is unchanged.

Pinned actual-history input:
**04039391fb7a1bd46598e90b7665d11b529dcb9bce9217c080f088b81ebe4829**;
pinned live-frontier replay input:
**35b1ca6656a6faaae3592eb8968d992dd5831c32c37f2f4032141713b49dd7fc**.

[Raw](online_feedback/v1/applicability_shadow_20261031T0324.json),
[SHA](online_feedback/v1/applicability_shadow_20261031T0324.json.sha256),
[completion](online_feedback/v1/applicability_shadow_20261031T0324.json.completion.json).
Raw SHA256:
**a255fa5c3373d0de12244267ed46fe4f7b25dbf0cb14ff45d41f5c4aca6e79bf**.
One analysis:256 saved cases,1024 shadow queries;1067695bytes;
0.5135899001033977seconds including raw/hash write, within30s/2MiB.
The implementation imports only standard-library modules.

~~~powershell
py -m pytest tests/test_ac0_applicability_shadow.py tests/test_ac0_shadow_audit.py -q
py experiments/diagnostics/ac0_applicability_shadow.py --out <fresh-shadow.json>
~~~

The CLI checks all three pinned input/design hashes and fresh raw/SHA/completion
paths. The fixed development pool is checked before receipt consumption.
New raw output may differ in source/runtime metadata; never overwrite a prior run.

## Four pre-outcome readouts

All share the same original prefix-online action/receipt history, not their
hypothetical own action trajectories:

1. Recorded all-prefix Gen forecasts.
2. Their intersection with the real live operation frontier at cursor1.
3. Original Gen forecasts compatible with the latest prior admitted actual
   outcome for the same channel/cue/operation key; with no such history, retain
   the forecast.
4. Adaptive last-actual table using exactly the same permitted receipts.

Every readout keeps the same unanimous public-goal selector. Context initially
comes from actual observed training receipts. All four query outputs are sealed
before the current receipt is consumed. Unknown/withheld receipts never replace
the latest actual. Each key isolates channel, cue and executed operation.

The compatibility condition is an explicit sidecar proxy. It is neither a
learned native context nor evidence that latest actual is a sufficient statistic.
The table can emit a value from a receipt; the Gen variant must retain an
existing verified forecast and abstains when the needed forecast is absent.

## Actual results

Totals across both seeds; each readout has256 queries. Conflicts count
**operation-query pairs**, not distinct situations or Gen.

| Readout | Raw abstentions | Conflicting operation-query pairs | Proposed choices not executed in saved history |
|---|---:|---:|---:|
| Original all-prefix | 84 | 145 | 0 |
| Intersect live frontier | 84 | 145 | 0 |
| Prior-actual-compatible Gen | 31 | 0 | 33 |
| Adaptive last-actual table | 22 | 0 | 37 |

Original/live forecast lists and choices match256/256. Mask/table choices match
247/256. Every mismatch is mask abstention versus a table choice, not a different
Gen-selected operation:6 on seed41 and3 on seed42.

Coverage is495/512 known operation-key opportunities, including225/234
table-goal-eligible key opportunities. These denominators count repeated query
opportunities, not512 distinct stored meanings or context keys. “Gen coverage”
means an applicable decoded forecast in the checked original query, not proof
that no corresponding chain exists anywhere in the base. Retrieval, creation
and encoding causes are not distinguished here.

Example: seed41/episode53, table proposes e6e9d6a12a8161e5; masked Gen readout
abstains. There are2 known table keys,1 with a compatible original Gen forecast;
the1 goal-eligible table key has0 such forecasts. The sidecar does not fabricate
a forecast to fill it.

On forecasts about actually executed operations, original has144 positive/
60 negative receipts; mask144 positive/8 negative; table152 positive/8 negative.
**Prediction denominators differ because forecasts are filtered.** These counts
are not matched task accuracy or a causal improvement estimate. Forecasts for
unexecuted operations and unknown observations remain unknown. Matching a saved
action also includes unknown-completion cases and does not mean task success.

Zero conflicts is expected from a single-valued latest-actual map when every
operation has history. It alone is not generalization, reasoning, native
condition learning or evidence of a better architecture.

## Validation and limits

22 focused tests passed(0.42s), including synthetic tamper cases: future-history
digest, fabricated counterfactual outcome/Gen, admission, omitted policy,
metric label and summary corruption. Boundary tests retain unknown/withheld
truth, reject duplicates before update, isolate keys, preserve missing-history
uncertainty and forbid table values from becoming invented Gen forecasts.

Full suite: **1641 passed,3 skipped,59 existing utcnow warnings(33.16s)**.

The recorded-data auditor rebuilds prior receipt state, checks1024 sealed
queries, Gen/table provenance/eligibility, selector labels and executed-only
grading. This is consistency checking by the same project agent, not independent
execution. It does not establish how a different action would have changed
subsequent observations, native training or context. No counterfactual task
success, on-policy recovery or heterarchy advantage is reported.

Core, persistent Gen support, old raw data and original online protocol are
unchanged.201–208 remain reserved and unexecuted. AC0–AC4/M0 and the functional
twelve-link model remain unpassed.

## Decision: next test must execute its own choices

The live-intersection control does not resolve ambiguity. The compatibility
condition resolves it on recorded history, while preserving a measurable
forecast-coverage deficit relative to the table. This supports testing explicit
applicability context, without asserting native recovery.

A separate [on-policy development design](../../protocols/ac0_applicability_on_policy_dev_v1.json)
is now declared **after exposure to these shadow results, before any new rollout**.
SHA256: **047058453db47b6229365b1929ab53066bed1a8c64544d96ed867fee58aaf29c**.
It has not been implemented or executed.

Next: implement that known-task41/42 comparison using unchanged prefix, masked
prefix, masked feedback-gate, online/gated table and random controls. Every
policy executes its own choice/fallback and updates only from its own actual
receipts. Preserve observed-withheld/unknown and named-Gen evidence→later
correct nonfallback choice. Report full model plus sidecar/receipt-store costs.

Budget:192 training actions,1536 evaluation actions,1728 world actions total;
nominal2168/cap2300 core tokens;60seconds complete,32MiB raw and≤8 actual-context
keys with receipt bookkeeping separately accounted. Numeric development checks
and stop decisions are fixed in the JSON. No confirming mode/201–208 is allowed.
Even recovery on this two-seed scaffold would justify only a development
candidate. A table tie supplies no heterarchy advantage.

