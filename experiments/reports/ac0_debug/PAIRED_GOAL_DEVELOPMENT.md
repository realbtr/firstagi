# Paired goal evaluator: development result on41/42

**Development only:** the explicit frozen-goal scaffold reaches104/104 observed
goals under stable rules, versus54/104 fixed-first,57/104 random and0/104 without
long learned chains or with an empty base. It reaches0/104 after answer swaps.
This is a useful known-task sanity check, not a confirming result or native
kernel action competence. Registered confirming task seeds101–108 remain unused.

| Policy | Stable goal success | All answers swapped |
|---|---:|---:|
| frozen_prefix_goal | 104/104 | 0/104 |
| fixed_first | 54/104 | 50/104 |
| random_uniform | 57/104 | 47/104 |
| minus_long_gen_goal | 0/104 | 0/104 |
| empty_goal | 0/104 | 0/104 |
| oracle_upper_bound | 104/104 | 104/104 |

The two task seeds receive96 native-random training attempts each. Each of six
policies and two conditions gets64 reset opportunities per seed, including52
observed and12 scheduled unknown. All public views/order/schedules are paired;
only evaluator answers differ in the swap condition. Desired outcome ID is
public; correct operation remains evaluator-only except privileged oracle.
Per-seed scores, micro/macro metrics and all raw opportunities are retained.

There are1536 evaluation opportunities,1024 actual actions,192 training actions
and480 actual core tokens. Ablated/empty models abstain; these failures remain
in all observed denominators. Unknown opportunities do not enter goal-quality
denominators and are never converted into observed prediction negatives.
Scaffold stable evidence:104 positive,0 negative,152 unknown. Swapped rules:
0 positive,104 negative,152 unknown. Each condition's152 unknown includes24
executed-but-unknown forecasts and128 forecasts for operations not executed.
All forecasts remain in raw; unexecuted alternatives are not counterfactually
graded using the evaluator's answer table. Prediction evidence does not update
the frozen model or select future actions. Rule-change failure is not adaptation.

## Trace from actual training to a decision

Tracing records real token steps and first observation of each native-created
Gen after a token or context reset;36 Gen creation receipts per seed. The tracing
sink is removed before model freeze. Every queried forecast links a registered
feature chain to its matching training creation receipt and prior token witnesses.
These feature witnesses prove observed feature provenance; they are not claimed
to reconstruct the generalizer's entire internal justification or an independent
replication. No Gen is manually inserted in empirical development runs.

Example seed41, episode0: selected Gen
`a27fb293-eb79-40de-aa4a-39709d1b5e54` first observed at core step144, stage
`context_reset_before_token`, training event index58
(zero-based). Feature witness token steps: `[10, 29, 6]`.
Its predicted outcome `026355459390c87c` matched actual
`026355459390c87c`. The pre-outcome digest is
`496a20df590b42767e44c77c983277938be2137dad496427a14965d5693bac86`. Other episodes reuse the same frozen knowledge.
Full observer hashes stay constant across both conditions; no evaluation learning.

## Reproduction, budgets and completion

Registered protocol commit:1907277baf41062dbc8d5e56934f0859780782dc.
Exact protocol SHA:2437f4fca7cfe683531b06175468573c482a2d2a88d7479fb57bbe5884370f3f.
Source-before-data: `a6ecf72c4d696e1a43475f10f1a39495be035261`, clean. Commands:

```powershell
py experiments/diagnostics/ac0_goal_evaluator.py --mode development --out <fresh-path.json>
py -m pytest tests/test_ac0_goal_evaluator.py -q
py -m pytest -q
```

Raw:paired_goal/v0_1/development.json, SHA-256
`2c91aa58517716e603901ffe0565a3522ad99f57992d76bb55c3a401a389817b`. Adjacent raw SHA and completion.json are
required together: execution status alone is pending-write. Completion says
complete at1.741914s including raw serialization/write
and SHA output (small completion-receipt write itself is outside that timestamp).
Budget violations/unexpected exceptions preserve partial training/evaluation
records and mark incomplete. Companion receipts are never overwritten. No partial
run can acquire successful aggregate results from an omitted seed or policy.

11 new tests verify all6×2 schedules on41/42, oracle upper bounds, ablations,
native creation/feature witnesses, seals, immutable hashes, unknown/abstention
accounting, partial training, timeout, write-overrun and calculator failures.
Fabricated eight-row calculator fixtures are labelled synthetic; they do not
execute confirming seeds. Full1575 passed,3 skipped,59 existing utcnow warnings.
Core/ andregistered thresholds/seeds unchanged. No equal-compute claim: base
lookup costs, model bytes and full-run wall time are distinct from token budgets.

The registered calculator returns bounded_scaffold_criteria_pass=false on this
development artifact: only two seeds exist; the eight-seed and≥6-positive-paired-
differences requirements are intentionally unmet. This is not a failed confirming
trial. Before running101–108, publish the final clean implementation commit and
exact confirming command. The CLI requires an exact matching --implementation-commit
and clean source. Do not retune using the fresh pool or silently replace failures.
Even a future bounded scaffold pass will not pass AC0–AC4, establish online
evidence-dependent reuse, new-task generalization, inheritance or10M/200B+ parity.
