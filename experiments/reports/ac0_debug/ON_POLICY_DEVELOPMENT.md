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
