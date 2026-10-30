# Learned-prefix recall: paired in-sample ablation

2026-10-30 · C-15 / PR22 · **mechanistic debug, not an action-quality result**.

## Result

Activating only already learned chains with the exact current cue prefix made
operation proposals accessible in191/192 probe views. Native atomic recall
yielded0/192; removing long Gen before the same prefix recall also yielded0/192.
No Gen was manually seeded, and no proposed action was executed or scored.

|Seed|Warmup fixture|Recall condition|Views with decoded operation candidates|One distinct operation|Competing operations|
|---|---|---|---|---|---|
|41|fixed|native_atomic|0/48|0|0|
|41|fixed|exact_learned_prefix|47/48|47|0|
|41|fixed|minus_long_gen|0/48|0|0|
|41|random|native_atomic|0/48|0|0|
|41|random|exact_learned_prefix|48/48|24|24|
|41|random|minus_long_gen|0/48|0|0|
|42|fixed|native_atomic|0/48|0|0|
|42|fixed|exact_learned_prefix|48/48|48|0|
|42|fixed|minus_long_gen|0/48|0|0|
|42|random|native_atomic|0/48|0|0|
|42|random|exact_learned_prefix|48/48|0|48|
|42|random|minus_long_gen|0/48|0|0|

Among191 prefix-recall covered views,119 had one distinct operation and72 had
competing operations. These are not correct/incorrect action counts. The192
views repeat **8 distinct public channel/cue/action-set frames** from warmup;
they are not192 independent tasks or held-out variants. The result supports
the availability of learned transition chains under this explicit adapter,
not useful control, general reasoning or AC0 completion.

## What was held equal

For each seed41/42 and fixed/random warmup, one CodedKernelObserver learned
48 attempts through the real kernel. Warmup always used native recall.
For every probe cue, all three conditions began as deep copies of that same
trained in-memory observer. Base/feature/provenance/step fingerprints were
checked equal before intervention, and the training snapshot was checked
unchanged after all probes. The minus-long control then explicitly removed
chain>1 Gen before applying the exact same prefix-recall policy.

Every condition observed one cue token per probe (48 per cohort/condition).
No world operation, oracle or task-success evaluation ran during probing.
Cue processing may update the discarded copy; this is **not** a frozen-model
skill control. Different recall policies do extra retrieval work, which is
not charged by equal cue-token budgets; no compute-efficiency claim is made.
Existing prefix search scans the base, not a proven bounded local frontier.

`exact_learned_prefix` is a labelled experimental adapter, not a silent core
loader change. It activates only pre-existing chain>1 Gen starting with the
exact public cue-anchor feature. No correct operation/target is consulted.
The regular fresh-proposal, actual provenance, live-binding and ambiguity
checks still apply. Native default behavior is preserved; core/ is unchanged.

## A control failure caught before measurement

The initial tests rejected a supposedly removed Gen that reappeared before
the minus-control cue. Cause: reset_context finalizes a pending greedy chain.
Deleting chains before that finalization allowed the last warmup chain to
be recreated. The fix flushes the common warmup once through the normal reset
API **before** snapshotting/ablation. All conditions inherit the same finalized
knowledge. Tests retain the assertion that recalled Gen predate the probe;
the check was not weakened. No data from that invalid setup are presented as
experiment results.

## Reproduction and checks

Source committed before artifact: `113f960ea69c6d10cfcde090a3ddc4b3eccf1c42`; clean source checkout.
[All raw paired records](recall_ablation/v0_1/probe.json) ·
[SHA-256 receipt](recall_ablation/v0_1/probe.json.sha256).

```powershell
python experiments/diagnostics/ac0_recall_ablation.py --out <new-file.json>
python -m pytest -q tests/test_ac0_recall_ablation.py
```

Receipt, paired fingerprints, pre-existing-Gen origin, one-cue budgets and
zero minus-control activations were independently rechecked after the run.
Six added tests check empty recall, existing matching chains, paired equality,
source-snapshot preservation, invalid policy, oracle/world exclusion and the
pending-chain control regression. Full suite: **1537 passed,3 skipped**,59
existing datetime.utcnow warnings. Positive binding unit fixtures from earlier
work are not used here. UUIDs/timestamps prevent raw byte repeatability across
fresh training runs; receipts pin these particular artifacts.

## Next evidence required

Trace one named recalled Gen through a prediction of an actual externally
observed outcome, positive/negative/unknown support, and subsequent reuse.
Preregister numerical criteria and held-out probe generation before confirming
skill runs. Compare random/fixed/frozen controls and keep task utility separate
from candidate coverage. Current probes use memorized views, not new IDs/rules;
they do not establish a goal-conditioned learned action policy, retention,
inheritance, AC0–AC4 or <=10M/200B+ parity.
