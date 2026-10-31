# Four saved gated-seed42 forecast gaps: diagnostic replay

## Declared scope before execution

Replay only the recorded seed42 `prefix_actual_context_feedback_gate` history
from raw SHA256 `b565e4d6df5f35e1da49ec145b11586054dcee28f408bcb6f7c23547fd771dee`.
It is the original own-action run at source50a752e; its raw-size **incomplete**
receipt is retained and will not be upgraded by this diagnostic.

Fixed targets: episodes96,98,104,112, the four previously identified observed
late fallbacks. Replay exactly96 saved warmup receipts then128 saved evaluation
receipts; no extension/replacement, new world construction, action or outcome.
All128 raw and masked query semantic multisets/choices must match the saved
history, ignoring UUID and traversal order but retaining multiplicity. Histories
use only prior own admitted actuals; the current actual is consumed afterward.

At each fixed target inspect registered/canonical features and their origins,
all native chains with the required triple at the start or inside, native
candidate counts/current chain, and original/masked verified forecasts.
Distinguish encoding/provenance, chain creation/prefix position, retrieval/
decode and eligibility gaps. Never add/activate/synthesize a missing chain.
Candidate changes are observed around existing token processing and the existing
reset_context finalization; no direct native assignment or altered algorithm.

Budgets: **508 replayed core tokens,60 seconds including loading/write,2MiB
compact output**,4096 records per diagnostic full-base scan; existing predictor
limits4096 Gen visits/12288 feature lookups/32MiB serialized observer. A failure
is retained with an incomplete receipt, not converted into an ordinary gap.
Clean implementation SHA and fresh raw/SHA/completion paths precede execution.
No confirming mode, seeds201–208 untouched. This is same-implementation source
localization on an exposed history, not an independent replication or new skill
test. Core sources/designs/old data remain unchanged; AC0–AC4 stay open.

## Result: one observed success per key, before the existing creation threshold

All four missing forecasts localize to **absent native three-feature forecast
chains**. Each already has correctly registered canonical features and unique
expected role/source provenance. Atomic Gen exist for all three features;
there are zero stored matching prefix chains and zero matching interior chains.
This is not evidence of absent meaning everywhere in a compressed heterarchy:
the claim concerns this scaffold's explicit verified three-feature readout.

The four query opportunities involve **two distinct cue/operation/goal chains**.
At each query the appropriate candidate count is **1**, below the unchanged
`min_gen_count=2`. Each has exactly one own prior admitted goal observation for
the same channel/cue/operation key. The adaptive table can use that observation
immediately; the Gen readout must await a stored native forecast chain.

| Missing query episode | Cue ID | Prior admitted goal receipt | Candidate count / threshold | Stored matching chains |
|---:|---|---:|---:|---:|
| 96 | bd9c66b3ad3c2d6d | 73 | 1 / 2 | 0 |
| 98 | 1a3d1fa7bc8960a9 | 72 | 1 / 2 | 0 |
| 104 | bd9c66b3ad3c2d6d | 73 | 1 / 2 | 0 |
| 112 | bd9c66b3ad3c2d6d | 73 | 1 / 2 | 0 |

All query inspections precede their current feedback. The current successful
fallback at98 or112 cannot justify the choice that preceded it. Failed attempts
at96/104 use the other operation and do not supply a second goal observation
for the missing key. Unknown and withheld events likewise do not count.

The diagnostic candidate trace and **original saved native Gen deltas** agree:

| Chain for cue | Second admitted goal / candidate 1 -> 2 | Native creation in that feedback | First later matching forecast | First later observed correct nonfallback action |
|---|---:|---|---:|---:|
| 1a3d1fa7bc8960a9 | 98 | d17c0bf8-f63c-4870-a16c-90a6e794d66f | 102 | 106 |
| bd9c66b3ad3c2d6d | 112 | 2cbe3837-8d9c-4407-b6de-01a53e66d261 | 119 | 120 |

Episodes102/119 have unknown outcomes, so their forecasts are **not** scored
as successful actions. Useful execution is established later at106/120.
Native chain creation uses the existing fork-candidate path in
[GreedyGeneralizer.on_step_result](https://github.com/realbtr/firstagi/blob/ecb0660f45c2dfc13825be3c64a7332cef04e129/core/learning.py#L108);
the default count threshold is
[LearningSystem(min_gen_count=2)](https://github.com/realbtr/firstagi/blob/ecb0660f45c2dfc13825be3c64a7332cef04e129/core/learning.py#L684).
Neither threshold nor core source was changed. These two actual-history cases
do not establish that every candidate counter increment elsewhere represents
an independent empirical observation; checkpoint/reset paths have different
count semantics. Two observations also do not guarantee reliability under noise.

## Provenance and actual work

Clean source **ecb0660f45c2dfc13825be3c64a7332cef04e129**, including the declared
scope above, preceded one execution:

```powershell
py experiments/diagnostics/ac0_forecast_gap_replay.py --out experiments/reports/ac0_debug/online_feedback/v1/forecast_gap_replay_20261031T0737.json
```

[Raw replay](online_feedback/v1/forecast_gap_replay_20261031T0737.json),
[SHA](online_feedback/v1/forecast_gap_replay_20261031T0737.json.sha256),
[completion](online_feedback/v1/forecast_gap_replay_20261031T0737.json.completion.json),
[recorded-data audit](online_feedback/v1/forecast_gap_replay_20261031T0737.audit.json).
SHA256 **1ca4c73dac76915f43a7a292e40d4a87f2d4b89766c1b9999234302290a5a054**;
**408,533 bytes /4.000031899893656 seconds** including input load/raw write,
**508 replayed core tokens** (240 warmup +268 evaluation), within all declared
caps. Diagnostic full-base scans visit44,44,46,46 records. No new worlds,
actions or task outcomes. All128 original and masked forecast semantic
multisets/choices and native token role/step/feature/outcome signatures match
the saved trajectory. The original rollout remains **incomplete**; a completed
diagnostic replay does not repair its output-budget failure.

The independent-code recorded-data auditor reconstructs native chain presence
from **the original** training creation receipts and begin/feedback Gen deltas,
rebuilds own prior actual history, and cross-checks the replay's candidate
transitions against source token roles/outcomes. It requires the1 ->2 transition,
actual same-episode native creation, and subsequent forecast/correct action.
It instantiates no learner/world and processes zero model tokens:

```powershell
py experiments/diagnostics/ac0_forecast_gap_audit.py --source experiments/reports/ac0_debug/online_feedback/v1/on_policy_dev_20261031T0540.json --replay experiments/reports/ac0_debug/online_feedback/v1/forecast_gap_replay_20261031T0737.json
py -m pytest -q
```

Twenty focused tests cover failure-stage distinctions, semantic multiplicity,
preflight, token/time/output guards, no learner execution in the auditor, and
rejection of fabricated existing chains, future evidence, encoding, token,
semantic or threshold tampering and retroactive completion upgrades. Full
suite: **1687 passed,3 skipped,59 existing utcnow warnings,33.58 seconds**.
The replay and audit were written by the same FirstAGI agent: this is not
independent peer execution or a causal-necessity intervention.

## Engineering implication and next bounded decision

Keep the existing learning threshold. The observed gap is a latency in obtaining
enough admitted experiences under this gated schedule and uniform fallback.
The table's one-observation response and the learner's durable-chain admission
are different evidence policies; their difference is now measurable. The four
cases do not warrant a global retrieval rewrite or lowering a threshold to fit
the exposed tasks. Persistent knowledge, a provisional candidate and its
current applicability remain separate engineering states.

Next: declare a small **development-only** comparison of uniform fallback
versus an explicitly labeled probe based on an existing candidate, preserving
`min_gen_count=2`. Before any actions fix seeds, budgets and one-off noisy/
unknown controls. Count probes separately from Gen-supported choices, and
measure whether actual evidence gathering creates a useful later chain at
matched opportunity cost. A probe must not be relabeled a missing Gen forecast
or granted its imagined outcome. No confirming run is authorized by this note;
201–208 remain untouched. No table advantage reversal, native attention policy,
continuous life, inheritance or full twelve-link/AC0–AC4 pass is claimed.
