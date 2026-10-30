# Registered frozen-goal scaffold result v1

**Bounded scaffold criteria passed on the eight preregistered task seeds101–108.**
Stable goals:416/416 observed opportunities (100%); fixed-first212/416 (50.96%),
random212/416 (50.96%), minus-long-Gen0/416 and empty0/416. Every seed favored
the learned-dynamics scaffold over each comparator. Protocol and thresholds
were published before this one confirming run; no seed replacement or tuning.

**AC0 is NOT passed.** The selector is a hand-specified equality-to-goal rule
over actual learned transition predictions, with exact-prefix retrieval. Each
task seed first gets96 native-random training attempts. Evaluation resamples
familiar cues/IDs/rules in reset one-action episodes: it does not test unseen
tasks for a trained model, native learned action policy or continual attention.
These are eight independently seeded training fixtures, not416 independent
models. This is our first registered run, not an external independent replication.

| Task seed | Scaffold | Fixed-first | Random | Minus long Gen | Empty |
|---|---:|---:|---:|---:|---:|
| 101 | 52/52 | 29/52 | 25/52 | 0/52 | 0/52 |
| 102 | 52/52 | 27/52 | 23/52 | 0/52 | 0/52 |
| 103 | 52/52 | 26/52 | 31/52 | 0/52 | 0/52 |
| 104 | 52/52 | 27/52 | 25/52 | 0/52 | 0/52 |
| 105 | 52/52 | 25/52 | 21/52 | 0/52 | 0/52 |
| 106 | 52/52 | 26/52 | 28/52 | 0/52 | 0/52 |
| 107 | 52/52 | 23/52 | 31/52 | 0/52 | 0/52 |
| 108 | 52/52 | 29/52 | 28/52 | 0/52 | 0/52 |
| Total | 416/416 | 212/416 | 212/416 | 0/416 | 0/416 |

Oracle upper bound416/416. Macro goal success1.0 and action coverage1.0 exceed
the registered0.80 minima. Paired macro advantage over fixed/random is0.4903846
(required0.15), over minus/empty1.0 (required0.20), positive in8/8 seeds for
each comparator (required≥6). Observed prediction accuracy1.0 (required≥0.90).
The separate stdlib raw checker re-evaluated these criteria with exact fractions.

## Failure under changed rules, and unknown evidence

Swapping the correct operation for every channel/cue reduces the same frozen
scaffold to0/416 goals; fixed/random204/416, ablated/empty0/416 and privileged
oracle416/416. The scaffold emits416 observed negative prediction receipts,
negative fraction1.0 (registered minimum0.50 with at least32 observed receipts).
This control checks that changed external outcomes can refute a prediction.
The model never updates support, so it does not recover or learn the new rules.

Stable evidence:416 positive,0 negative,608 unknown. Swapped:0 positive,
416 negative,608 unknown. Per condition,608unknown=96 executed unknown outcomes
+512 unexecuted alternative forecasts. The checker grades only the executed
operation's actual observation; it does not use hidden answers to grade an
unexecuted alternative. Observed abstentions stay in task denominators. Every
policy/condition has52 observed+12 scheduled unknown opportunities per seed.

## One actual Gen: creation, useful choice, later contradiction

Seed101, episode0: Gen`69c3d1b1-46df-44c4-8221-099639414d0c` was first observed
at training core step39 (`context_reset_before_token`), with feature
witness token steps`[15, 20, 21]`. Its learned chain and
unique recorded feature origins supplied the operation and outcome forecast.
Before the action its prediction was sealed; actual`7c47571849dc9b34`
matched the public goal. The corresponding swapped-rule episode uses the same
frozen knowledge and operation but observes`543bcd04365e52e7`,
which refutes the prediction. All288 native creation receipts and all2048
forecast links are included. Feature witnesses establish observed provenance,
not the generalizer's entire internal derivation or evidence-dependent reuse.

## Reproducibility and the single-run record

Registered protocol commit:1907277baf41062dbc8d5e56934f0859780782dc.
Protocol SHA:2437f4fca7cfe683531b06175468573c482a2d2a88d7479fb57bbe5884370f3f.
Implementation:`c81166f11320628fb955d186f1d3c7597441661d`, clean. The exact command was published
in Discussion21#19294329 before data and executed once:

```powershell
py experiments/diagnostics/ac0_goal_evaluator.py --mode confirming --implementation-commit c81166f11320628fb955d186f1d3c7597441661d --out C:\!!!FirstAGI\_heartbeat\goal_choice_confirming_v1.json
```

The original output/receipts remain preserved there. Their exact bytes are
copied under`confirming_goal/v1/`; raw20647527bytes, SHA
`937ab033a63fc4de42001ce5370a804dadbe58c84e7fca7088f1629ed90d8568`. Completion receipt says complete at
8.449835s including raw/SHA writing, within300s;
the small completion-receipt write itself is outside that timestamp. Source
code/protocol/seeds were not changed after outcome inspection. Do not rerun the
original output path or treat another replay as independent confirmation.

For a deliberate replication, use the recorded implementation checkout and a
different fresh output path, label it replication, and report all outcomes.
Audit the existing artifact without training or running policies:

```powershell
py experiments/reports/ac0_debug/confirming_goal/v1/audit_confirming_v1.py experiments/reports/ac0_debug/confirming_goal/v1/goal_choice_confirming_v1.json
```

The standard-library checker reconstructs fixture IDs/rules/schedules from
recorded seeds, checks every actual outcome/goal score,6144 pre-outcome seals,
2048 feature/Gen forecast links,288 creation receipts, stored frozen digests,
paired inputs, unknown/abstention accounting, exact-fraction thresholds and
budgets. It is a separate recorded-data audit, not independent model execution
or proof of runtime immutability from logs alone. Runtime full-state checks
and their mutation tests remain in the recorded implementation. Audit output
and its SHA are adjacent. Original implementation CI:1576 passed,3 skipped.
This run changes no model/core code; validation adds the full raw-data audit.

## Costs and next question

Actual768 training actions/1920 core tokens;6144 evaluation opportunities and
4096 executed actions. Max explicit base reads54/query, feature/origin reads13,
serialized model2223–61180bytes including ablation/empty controls. Budgets held.
Serialization/full scans are additional computation; no equal-compute, system
energy, learned parameter count or large-language-model comparison is claimed.

Next: preregister evidence-dependent **online** reuse/recovery against this
matched frozen control, with unknown protected from negative updates and a
metric that requires reaching goals again rather than only abstaining. Native
goal/action selection remains unresolved; AC1 continuous life, AC2 inheritance
and≤10M versus200B+ reasoning remain unproven. Keep this v1 protocol/raw intact.
