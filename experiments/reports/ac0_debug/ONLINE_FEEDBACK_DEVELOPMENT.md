# Online feedback development: stale choice ceased; useful recovery failed

2026-10-31 Europe/Belgrade (execution2026-10-30 UTC).
**Development41/42 only. Negative scaffold result, not a confirming run or AC0 pass.**

The registered conflict-preserving readout does not recover useful choices after
a rule change, even though actual feedback reaches the existing core and named
Gen counters change. An adaptive table recovers. This localizes a gap at the
interface between persistent learned alternatives and their current applicability
in the explicit readout; it does not establish that the entire native core, or
the Abhidharma program, cannot learn or recover.

## Source and commands

- Runtime source: **05c4b98a1a58a2dcee15870f5f613adbffbedfdc**, clean at start.
- Recorded-data auditor/tests/data: **f5caba48a7b990c9aa4a347c23c09ef00e353290**.
- Registered protocol unchanged: SHA256
  **1e9d406567a5b6a0badb5a127c5457688cd1915b282674a7c54f1511b4f58347**.
- [Raw](online_feedback/v1/development_41_42_20261030T2334.json),
  [SHA](online_feedback/v1/development_41_42_20261030T2334.json.sha256),
  [completion](online_feedback/v1/development_41_42_20261030T2334.json.completion.json),
  [extended audit](online_feedback/v1/development_41_42_20261030T2334.audit_v2.json).
  Raw SHA256: **04039391fb7a1bd46598e90b7665d11b529dcb9bce9217c080f088b81ebe4829**.

One actual development execution, no replacement seeds or rerun. The original
audit is retained; v2 adds independent recomputation of window/fallback/cessation
metrics from the same raw records. Neither audit executes a learner or world.

From the PR revision containing source and artifacts:

~~~powershell
py -m pytest tests/test_ac0_online_feedback.py tests/test_ac0_online_audit.py tests/test_ac0_online_protocol.py -q
py experiments/diagnostics/ac0_online_audit.py experiments/reports/ac0_debug/online_feedback/v1/development_41_42_20261030T2334.json --out <fresh-audit.json>
# Optional reproduction on development tasks only, always a new output path:
py experiments/diagnostics/ac0_online_feedback.py --out <fresh-development.json>
~~~

The executable has **no confirming mode** and rejects reserved/consumed task pools
before training. Gen UUIDs, timestamps and full-state hashes can differ on a
reproduction; do not expect the raw byte SHA to repeat. Retain each execution.

## What executed

Existing96-attempt random warmup once per seed, finalized before cloning.
Nine policies share training receipts and the128-case registered schedule.
Four blocks preserve a stable second channel and change channel0 from block1.
Gated policies withhold channel0 outcome assimilation in block1, then restore it.
Actual withheld receipts remain observed. Unknown outcomes are not negative.

Native online arms process the cue with exact learned-prefix recall, query via
the unchanged read-only FrozenGoalPredictor, and assimilate only executed,
observed, admitted operation/outcome tokens through existing process_token.
The frozen arm ingests no evaluation tokens. Table updates only the executed,
observed, admitted key. Neither hidden block nor correct operation reaches the
learned policy; fixed/random/oracle remain evaluator fixtures.

Actual work:192 training actions,480 training core tokens,2304 evaluation
opportunities/actions,**2496 world actions**,**1592 total core tokens**.
1440 observed and864 unknown evaluation outcomes. Raw15191215bytes;
completion8.405673400033265seconds including raw/hash writes, below declared caps.
This is equal opportunity, not equal compute; no full local update-work or
table-store-byte audit is claimed.

## Late recovery, changed channel

Each cell is successes /10 observed opportunities, block3. Unknowns are separate.

| Policy | Seed41 | Seed42 | Late changed-channel interpretation |
|---|---:|---:|---|
| prefix_online | 4/10 | 6/10 | all20 actions use uniform fallback |
| prefix_feedback_gate | 4/10 | 6/10 | all20 actions use fallback after admission restored |
| prefix_frozen | 0/10 | 0/10 | old nonfallback choices persist |
| table_online | 10/10 | 10/10 | useful nonfallback choice recovered |
| table_feedback_gate | 10/10 | 10/10 | recovered after admission restored |
| table_frozen | 0/10 | 0/10 | old choices persist |
| fixed_first | 2/10 | 2/10 | display-order baseline |
| random_uniform | 5/10 | 5/10 | separately paired random stream |
| oracle_upper_bound | 10/10 | 10/10 | privileged upper bound |

Both online native arms retain10/10 in the stable channel on both seeds.
Changed-channel old **nonfallback** choices fall to0/10 late, but useful native
nonfallback successes also equal0/10. Thus local cessation and useful recovery
give different answers. The quality criterion0.8 is not reached; no confirming
aggregator or formal protocol acceptance verdict is emitted.

During withdrawal, native online changed-channel success is3/10 and4/10 versus
gated0/10 and0/10. Table online is4/10 and8/10 versus gated0/10 and0/10.
These development contrasts are descriptive; native online improvement there
includes fallback and does not demonstrate recovered skill or broad necessity.

## Actual negative evidence reaches a named Gen

Example from seed41/prefix_online, episode32, channel0, event e0001 in the
unique run online-dev-41-prefix_online-32:

- Gen **a5bafe3f-e269-4854-8adc-e3d208a9e95c** predicts c36492adbb4bb95c for
  the operation actually executed; actual outcome is3fc31a98c7fd59a0.
- Native operation/outcome tokens are steps314/315.
- During feedback its stop_count changes0→1, success_count51→52. These are
  feature/sequence matching counters; the additional success is not task success
  and must not be described as a whole-Gen confirmation.
- Late episode96 retains both old/new outcome forecasts for both operations.
  The unanimous public-goal rule therefore returns no choice and uses fallback.

Across recorded native forecasts:180 observed negative receipts;32 joins of
an executed negative forecast to that same Gen's increased native stop counter.
There are184 update→later correct nonfallback reuse joins overall, but
**zero in the changed channel after the rule change**. Stable-channel reuse
does not stand in for changed-channel recovery. These are receipt associations
inside this scaffold, not an independent causal proof of all native semantics.

All40 late observed queries across the two online native arms/two seeds expose
conflicting outcomes and abstain. The all-contributors rule deliberately retains
conflicts and ignores support/recency for selection. A changing support count
therefore cannot by itself remove the contradiction from this readout.

## Checks and limits

Focused boundary/protocol/audit tests: **38 passed(2.49s)**, including17 new
feedback tests and7 auditor tests. Corrupted scores, actual outcomes, leaked
views, admission, guard receipts and summary rates are rejected.
Full suite: **1614 passed,3 skipped,59 existing utcnow warnings(31.17s)**.

The stdlib auditor checks all2304 evaluation records, pre-outcome seals,
training-derived actual transitions and the declared local change, all table
choices/updates, forecast evidence, native chain/feature witnesses, window
denominators and fallback/cessation metrics.468 no-ingest guard receipts
cover native unknown/withheld/frozen records. Duplicate rejection is exercised
in tests; no duplicate outcome is injected into the development schedule.

Runtime guards fingerprint native base/features/provenance/step AFTER begin,
before/after feedback; cue processing is not incorrectly called feedback.
Read-only queries retain full pickle hashes. Recorded-data audit checks the
receipts' consistency but cannot reconstruct complete native snapshots from
hashes. It is by the same project agent, **not independent execution**.

This is still a partial development implementation: confirming aggregator,
full store/update-work accounting and a clean confirming manifest are absent.
Context is reset per cue as a declared fixture; private in-memory pending
bookkeeping is not durable idempotency. Full twelve-link arising/cessation,
continuous life, room-orientation/threat priority and inheritance are untested.
Social agents are not instances of this core. AC0–AC4/M0 remain unpassed.

## Decision and next step

Follow the registered failure branch: **localize the applicability/conflict
readout gap before any confirming run**. Do not tune a significance threshold,
delete historical Gen, expose evaluator block IDs or rewrite the registered
protocol to make this data pass. Preserve201–208 ungenerated/untrained.

Next development task: trace the same-cue/opposite-outcome pair through existing
active context and the all-Gen readout; specify which observable condition could
make an old forecast currently inapplicable while retaining the learned support.
A proposed alternative needs a separately declared comparison against the
unchanged readout and adaptive table. This result does not yet choose an
alternative or justify a core rewrite.

