# Frozen query and conflict-preserving goal selector: development check

**128/128 development queries left the complete learned observer unchanged.**
These are mechanics checks on seeds41/42, not confirming goal-quality results.
No world action was executed during the query phase and no task score was
computed. The registered101–108 pool remains unused.

| Seed | Native random warmup attempts | Queries | Serialized observer bytes | Max counted Gen visits/query | Max feature/origin reads/query |
|---|---:|---:|---:|---:|---:|
| 41 | 96 | 64 | 59074 | 54 | 13 |
| 42 | 96 | 64 | 60422 | 54 | 13 |

Full observer pickle-protocol5 SHA is checked before/after each query. The query
uses a separate ContextBuffer and fresh InitiativeEngine, advances only ephemeral
ActiveGen positions, and never invokes process_token/begin/confirm_feature.
Registered features and origins are read and verified; Gen counters, hedonic
counts, pending generalizer chain and original initiative caches remain frozen.
External changes or mutation during proposal generation raise BoundaryError.
Budget errors stop the caller; they do not become ordinary abstentions.

## Prevent the representative from hiding a contradiction

Native InitiativeEngine groups by next feature and retains one best Gen. The
query uses the resulting proposed feature set, then expands **all live Gen
contributors** for those features before reading their immediate outcome edges.
Goal selection requires one available operation with unanimous verified forecasts
equal to the public goal. Confidence, UUID and list order never resolve a conflict.

An adversarial **hand-built unit fixture** has two chains for the same operation
with different outcome predictions: native propose emits one representative,
but the query retains both forecasts and abstains. This fixture is only a wiring
test; no hand-built Gen is used in the empirical development artifact.

## Mechanical boundaries and reproduction

Source-before-data: `1795d14f535dbd726e2d7dc38331971562ce6f10`, clean source.
From PR22 at that source or its descendants:

```powershell
py experiments/diagnostics/ac0_frozen_goal.py --out <fresh-development-path.json>
py -m pytest tests/test_ac0_frozen_goal.py -q
py -m pytest -q
```

The CLI accepts no arbitrary task-seed argument; its entry point rejects any seed
outside41/42. It trains the existing native observer, then constructs public
four-field views for64 reset cases per seed. It receives no world/answer table,
and tests forbid world.act/oracle as well as learning/confirm calls during query.
Model/Gen UUIDs and raw bytes can differ on rerun; use this artifact's addresses
when citing a particular forecast. Frozen-state equality is within each run.

Raw: `frozen_query/v0_1/development.json`, SHA-256
`de4514ed0af11c00a0f19d8adbf14e58053e0f45a7fe2071802b05f7bf73ec73`,
with an adjacent receipt. Both cohorts preserve their full-state hash in every
query record. Registered protocol and thresholds from1907277 remain unchanged.

18 new tests cover actual learned forecasts without learning/world access,
full-state changes before/during query, grouped-Gen conflict, live feature origin,
unknown cue, removed chains, budget failure, paired schedules, unknown accounting,
abstention denominators and the development seed guard. Source scans count every
record, including rejected prefixes, and each repeated get from context/initiative.
The one-chain wiring fixture has exactly6 counted Gen reads and5 feature/origin
reads; a5-read Gen budget fails. Serialized observer size and query wall time
are recorded separately. Gen visit counters measure explicit base access, not
internal pickle traversal/CPU work; two full-state hash passes still incur cost.
The recorded query timer excludes its final hash (field names make this explicit);
the future complete-run wall budget must include both hashes and raw output.
No equal-compute, memory-scaling or whole-system energy claim is made.

Schedule construction precomputes all channel/phase/operation orders and independent
random choices before evaluation. The denominator helper counts abstentions as
observed failures, never as missing data; only scheduled unknown is excluded.
Tests check52 observed/12 unknown opportunities and16 cases per channel/phase.
This is schedule/denominator plumbing, not the full paired confirming evaluator.

Remaining before confirming data: implement all six policy/two-condition execution,
budget-stop/partial artifact handling, named-Gen training-creation receipts and
the preregistered aggregate criteria. Then test on41/42, publish the exact
implementation commit/command, and run101–108 without tuning thresholds/seeds.
Goal equality selection is a hand-specified scaffold, not native learned action
policy, evidence-driven online reuse or an AC0/AC1/AC2 pass.

Full local suite at source1795d14: **1564 passed,3 skipped**,59 existing utcnow warnings. No core/ files changed.
