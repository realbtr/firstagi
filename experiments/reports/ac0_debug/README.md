# AC0 event boundary: first debug scaffold

2026-10-29 · C-15 · **debug / component validation; AC0 not passed**.

## Result

An executable two-channel environment now separates available operations,
the chosen operation, its actual external outcome, and the kernel's own
StepOutcome. An interrupted/unavailable/cancelled operation stays unknown.
Each completed transition reaches the existing TextDriver/LearningSystem
observer; that observer does not choose actions or evaluate a named Gen.

| Seed | Fixture controller | Successes / observed outcomes | Unknown | Attempt cost |
|---|---|---|---|---|
| 41 | fixed | 13/36 | 12 | 48 |
| 41 | random | 16/36 | 12 | 48 |
| 41 | oracle | 36/36 | 12 | 48 |
| 42 | fixed | 24/36 | 12 | 48 |
| 42 | random | 17/36 | 12 | 48 |
| 42 | oracle | 36/36 | 12 | 48 |

These six short diagnostic runs check the harness, not a learned skill.
The privileged oracle's 36/36 only checks the environment upper bound.
Fixed/random policies are supplied controls. There is no FirstAGI action
controller in this result, so no learning advantage can be inferred.

Every run has 48 causal events and 72 core token steps. All 12 unknown
events per run feed zero core tokens. All six traces and SHA-256 receipts
were checked. Ten added tests include rejecting changed causal edges,
fabricated success, duplicate delivery, and negative evidence for unknowns;
they also check hidden-answer exclusion from controller views and same-seed
environment repetition. Full suite: **1496 passed, 3 skipped**, 59 existing
datetime.utcnow warnings. Kernel source code is unchanged.

## Reproduce

Source commit: `462f6b3430ad45d5dbe41ac10cbeb29e9166968f` (source-only commit before data).

```powershell
python experiments/diagnostics/ac0_event_baseline.py --seed 41 --attempts 48 --out <new-directory-41>
python experiments/diagnostics/ac0_event_baseline.py --seed 42 --attempts 48 --out <new-directory-42>
python -m pytest -q tests/test_ac0_event_baseline.py
```

[Source and scope](../../diagnostics/AC0_DEBUG_README.md) ·
[environment and run provenance](ENVIRONMENT.json) ·
[seed41 raw data](v0_1/seed41/) · [seed42 raw data](v0_1/seed42/).

Seed41 ran with a clean source checkout. Seed42's `source_dirty=true`
records the already generated, then-untracked seed41 output; source files
were unchanged at the same commit. No confirming-run claim is made.
Core UUIDs differ between executions; compare the deterministic environment
events/task counters, not raw UUID bytes. Receipts pin these particular files.

## Limits and next test

The synthetic one-unit attempt cost is not CPU/energy or visited-index work.
The core context is shared, not restored per channel. Adapter filtering of
unknowns is not evidence of native interruption handling. No independent
Gen-specific support update, held-out skill test, preregistered numeric gate,
full runtime resume, or inheritance is implemented. This is not AC0–AC2 or
10M/200B+ evidence. It is a boundary on which to test the missing mechanism.

Next: connect existing proposals to an operation-selection adapter without
giving it the hidden operation table, then trace one named Gen's prediction,
external evidence and subsequent use. Keep fixed/random/frozen controls and
commit the confirming protocol before measuring a skill claim.
