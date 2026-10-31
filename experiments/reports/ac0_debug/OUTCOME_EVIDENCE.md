# Named-Gen outcome forecast replay v0.1

**105/192 replay attempts had a forecast for the fixture-selected operation:
77 positive, 0 negative, 28 unknown named-Gen receipts.** This is in-sample
dynamics recall, not a successful learned action policy or AC0 gate pass.
57 positive receipts describe a task-divergent operation. Correctly predicting
failure is positive prediction evidence but does not make the action useful.

| Seed | Native training fixture | Forecast-covered /48 | Positive | Negative | Unknown | Positive on task divergence |
|---|---|---:|---:|---:|---:|---:|
| 41 | fixed | 35 | 29 | 0 | 6 | 23 |
| 41 | random | 12 | 9 | 0 | 3 | 7 |
| 42 | fixed | 36 | 24 | 0 | 12 | 12 |
| 42 | random | 22 | 15 | 0 | 7 | 15 |

All forecast extraction uses actual live after-cue bindings to a pre-existing
learned Gen. The next edge of that SAME Gen must have a unique recorded
operation_to_observation origin matching channel and operation. It does not
read fixture target, task success label, expected_observation or answer table.
All matching forecasts are retained: this does not resolve competition.

Before world.act the prediction payload is sealed with a digest. The independent
sandbox driver then emits actual observation. Each external receipt compares
that observation with the prediction. This is separate from the fixture's
task-target prediction_support and from native success/stop counters, which
are not updated by these receipts. The digest proves local recorded ordering
in this runner, not third-party timestamping or tamper-proof execution.

For example, seed41/fixed learned Gen `51dba223-bc8d-4c50-8b1f-daf6a27e7653` predicted
`3fc31a98c7fd59a0` before replay events3,5,7,9; all observed that same ID.
All four actions were task divergences, yet the prediction was correct.
Gen IDs are generated per run; use this raw artifact to address this trace.
Repeated use is across fresh copies of the same finalized warmup snapshot,
not one continuing life or evidence-driven policy adaptation.

## Reproduction and controls

Source-before-data: `64148cae1a3e3ce716591c6833e62813150c1601`, clean source. Debug plan
OUTCOME_EVIDENCE_PLAN.md was committed before the run. Reproduce on PR22:

```powershell
py experiments/diagnostics/ac0_outcome_evidence.py --out <fresh-path.json>
py -m pytest -q
```

Raw: outcome_evidence/v0_1/probe.json, SHA-256
`6c75f1f28c2eba8e3bac05ed8e2483bf52000563f94297a71729f656c0dff582` (adjacent receipt).
Exact JSON/UUIDs may differ on rerun; descriptive counts should match.
The four native warmups each have48 attempts; replay follows the same operations,
rules and trajectory. The final training state is copied per cue; one cue update
is allowed then discarded. There is no post-outcome learning in these copies.
This is neither held-out evaluation nor independent replication/frozen skill
control. Additional global-prefix lookup cost remains unbounded/uncharged.

Nine new tests cover actual learned forecast/no oracle/no mutation, prediction
versus task support, all three unknown statuses, cross-event rejection, seals
and repeated named-Gen use. Negative evidence is exercised by a unit outcome
intervention, **not an observed negative in this replay**. Full suite:
1546 passed,3 skipped,59 existing utcnow warnings. Existing core unchanged.

Next: preregister a bounded held-out-episode task-choice trial on familiar rules,
including a frozen predictor, fixture fixed/random baselines, goal availability,
numeric quality/cost criteria and observed rule-change control. Current code
does not choose an operation to reach a goal, change support from these receipts,
or demonstrate AC1/AC2/10M versus200B+ competence.
