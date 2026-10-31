# AC0 operation decoding readiness — a negative result before action wiring

2026-10-29 23Z (2026-10-30 Europe/Belgrade) · C-15 · debug/source audit,
**not a learned policy experiment or passed gate**.

## Finding

Do not wire the current observer's cached proposals straight to operations.
Two concrete prerequisites are missing in this adapter:

1. **Distinguishable action encoding.** TextDriver initializes a vocabulary
   from its first triple, then assigns unseen words the default rank 0.5.
   Equal-length opaque operations with equal character complexity can map
   to the exact same FeatureVector. The seed42 fixture actually exhibits
   this alias in every initialized decoding view, for fixed and random
   streams. An expected vector cannot identify one of these two commands.
2. **An explicit proposal phase.** LearningSystem forms initiative proposals
   before each token. After process_token returns, last_proposals describes
   the earlier prediction, not a newly computed action for the current cue.
   Its feature-ID set differs from the current context in the cases below.
   This is not a bug in InitiativeEngine's documented before-token contract;
   it is an invalid assumption for an after-observation action adapter.

| Seed | Fixture | Initialized views | Views with unseen symbols | Exact action aliases | Cached/current changes after completed observations |
|---|---|---|---|---|---|
| 41 | fixed | 46 | 46 | 0 | 36/36 |
| 41 | random | 46 | 46 | 0 | 14/36 |
| 42 | fixed | 46 | 46 | 46 | 36/36 |
| 42 | random | 46 | 46 | 46 | 36/36 |

Each stream contains 48 fixture attempts, 36 completed outcomes and 12
unknowns. The first view in each channel has no vocabulary (2 per stream).
The read-only audit processes 192 fixture attempts total, 184 initialized
views, 92 exact action aliases, and 122 feature-set changes after 144 completed
observations. These are diagnostic counts for this fixture, not error rates
for general reasoning. A second execution reproduced these aggregate counts.

An isolated counterexample also compares distinct unseen operations
`0123456789abcdef` and `fedcba9876543210` after the same cue. Their distance
is exactly **0.0**, despite distinct command IDs. It is included in the raw
artifact, with candidate vectors and blockers.

## Reproduce and verify

Source committed before data: `ae4e8b0fb1e9e4bd76060f65058efb58fd9c1813`;
source_dirty=`false`.

```powershell
python experiments/diagnostics/ac0_proposal_readiness.py --out <new-file.json>
python -m pytest -q tests/test_ac0_proposal_readiness.py tests/test_ac0_event_baseline.py
```

[Raw records and counterexample](operation_readiness/v0_1/readiness.json) ·
[SHA-256 receipt](operation_readiness/v0_1/readiness.json.sha256).

The audit inspects copies of drivers and current expected features. It does
not change driver vocabulary, token counts or initiative counters, does not
read hidden answers, and does not select an action. Tests cover these
boundaries, the collision, missing vocabulary and cached/current comparison.
Core source files and earlier v0.1 raw reports remain unchanged.
Full local suite: **1501 passed, 3 skipped**, 59 existing datetime.utcnow
warnings. The two AC0 test modules together passed 15 tests.

## Interpretation and next change

These findings apply to the dynamic opaque-symbol adapter using TextDriver;
they do not show that every driver is ambiguous or that core predictions
are wrong. Feature-set comparison ignores confidence/rank and does not
establish which action a fresh proposal would select. Matching sets would
not prove freshness or correct cue/action provenance either. Private driver
and context APIs are inspected at the pinned source revision only.

Before claiming learned actions, provide a stable, domain-neutral encoding
for public cue/operation transitions and collision/ambiguity checks. Make
proposal phase and cue/channel/Gen provenance explicit. An ambiguous decode
must abstain rather than choose an arbitrary action. This is the next
bounded task in PR22; no hidden correct-operation table may enter it.

No Gen-specific external support, held-out task improvement, retention or
inheritance was tested. AC0–AC4 and <=10M/200B+ remain unproven. Existing
v0.1 environment scores still describe fixture controllers only.
