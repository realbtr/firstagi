# Online AC0 feedback and local cessation · protocol v1

2026-10-30 · З-0064 · **Registered design; implementation pending; no task run.**

## Question and boundary

Can actual observed feedback change a named native Gen and later behavior,
and does withdrawing this feedback pathway prevent the corresponding change?
Can stale choices cease locally while a second stable channel remains useful?
Recovery of successful action is a separate endpoint from cessation of a stale
nonfallback choice. This design tests one dependency, not the full twelve-link
cycle, continuous life, inheritance, or equivalence to a Buddhist interpretation.

The owner's room-orientation episode motivated distinguishing transient
activation and durable knowledge. This fixture does **not** reproduce that
episode, memory restoration, fear priority, or the birth of unnamed distinctions.
It retains the existing two-channel opaque-ID world and labelled goal/recall
scaffold. Numerical model-size intuitions are not acceptance criteria.

## Frozen registration

- [Machine protocol](../../protocols/ac0_online_feedback_v1.json).
- Protocol SHA256: `1e9d406567a5b6a0badb5a127c5457688cd1915b282674a7c54f1511b4f58347`.
- Baseline source: `4ea31da1a7a87368e4db1df93363ded9dfd7ac92`;
  current interpretation: `f46c114475cf123ee20cd2213782a87b14f7574c`.
- New task seeds **201–208 are reserved and unexecuted**; schedule seeds
  1201–1208. Development remains41/42. Old confirming101–108 remain consumed.
- The online runner is not implemented. Before any new confirming task is
  constructed/trained, publish its exact clean source SHA and command in a
  separate execution manifest; retain this protocol/hash. The null implementation
  field records the present design status, not permission to substitute code silently.

## One controlled dependency

The manipulated carrier is **admission of observed outcome evidence to the
native update route**, not whether the real receipt exists or is true.
All actual receipts retain their original observed/unknown status. Withholding
an observed outcome must not relabel it as `unknown` or as an observed negative.

Each seed has128 one-action reset episodes per policy: four32-episode blocks.
Within each block all two-channel/two-phase cases occur eight times; three
repeats have unknown outcomes (interrupted/unavailable/cancelled). Each block
therefore has20 observed and12 unknown opportunities, with10 observed per channel.

| Block | World | Gated arms |
|---|---|---|
|0 stable|original rules|admit observed feedback|
|1 changed/withdrawal|only channel0 answers flip|withhold channel0 outcome assimilation; channel1 stays admitted|
|2 restored|changed rules persist|restore feedback admission|
|3 late recovery|changed rules persist|measure recovery/retention|

Nine policies share the same initial native training snapshot, actual training
receipts, episode cases, operation display orders and unknown schedule:
prefix-online / prefix-feedback-gate / prefix-frozen; matching latest-observation
table-online / table-feedback-gate / table-frozen; fixed-first; random-uniform;
privileged oracle upper bound. No requirement forces the native model to beat
the adaptive table; the comparison may identify unnecessary complexity.

The prefix readout preserves all conflicting native forecasts and the existing
unanimous public-goal selection rule. Significance/UUID tie-breaking is not added.
On raw abstention, a declared paired uniform fallback executes an operation;
fallback success is counted in task quality but never called learned action.
The fallback and random policy use separate precomputed RNG streams.

Online native arms call existing `begin(..., recall_policy=exact_learned_prefix)`
and ingest actual operation/outcome features only when observed and admitted.
They must not assign Gen counters or call confirm/refute directly. The read-only
query is checked against its current frozen digest; a new predictor is made
after updates. The frozen arm ingests no evaluation tokens. The table replaces
only an executed, observed, admitted key with its latest actual outcome.

Unknown and withheld delivery guards compare native base/features/counters
**after cue processing, immediately before and after feedback delivery**.
Cue processing can legitimately change native state; receipt bookkeeping can
change too. These are not attributed to unknown outcome evidence. Duplicate
delivery is rejected before an update. Unexecuted forecasts remain ungraded.

## Prespecified endpoints and decision

Primary quality uses all observed opportunities in block3 per channel (10/seed,
80 over eight seeds), including fallback outcomes. Report raw abstention,
fallback/nonfallback success and stale-choice rate separately.

- Late changed and stable channel macro goal success each≥0.80; native-online
  advantage over each prefix-frozen/random≥0.15, positive in≥6/8 seeds.
- In block1, online versus gated changed-channel advantage≥0.15; absolute gap
  in the stable channel≤0.10. Gated arm after restoration must reach≥0.80 late.
- Late stale **nonfallback** choice fraction≤0.20 is a separate cessation
  endpoint; it cannot compensate for poor overall task success.
- At least one observed-negative named-Gen causal trace and one native
  update→later correct nonfallback reuse trace, with actual receipt/token links.
- All unknown, withheld, duplicate and read-only-query integrity guards hold.

These criteria are descriptive paired checks, not a population significance
claim. A missing trace or implementation function is a reported failure, not
permission to manufacture support from the task score. All bounded checks
passing still does not pass full AC0 or the twelve-link cycle.

If native support changes while the preserved conflict readout cannot recover,
localize that gap and design a later version; do not retune on201–208. If
withdrawing admission has no effect, the local necessity claim is unsupported
in this fixture; inspect alternative routes. Stopping stale choices without
recovery is reported as those two separate results. Equality/loss to a table
does not establish heterarchy advantage.

## Budgets and actual work this cycle

Declared/derived counts, **not measured experiment output**:768 training
actions/1920 training core tokens;9216 evaluation opportunities/actions;
9984 world actions including training; nominal6368 core tokens within a7000
cap. Query caps4096 Gen visits and12288 feature/origin lookups; serialized
model≤32MiB/instance; raw≤128MiB; complete run≤300s including raw/hash writes.
Budgets count query and update work separately; equal opportunities are not
equal compute. A violation stops the run with partial records; no seed removal
or extension. Fresh raw/SHA/completion paths are checked before training.

Only a standard-library structural validator and symbolic case-index scheduler
were executed here. They do not import the learner/world or construct hidden
task answers. Layout tests use development schedule1041/1042. Validation is
not experimental acceptance or a guarantee that future code follows the design.

Reproduce from the commit containing this report:

```powershell
py experiments/diagnostics/ac0_online_protocol.py
py -m pytest tests/test_ac0_online_protocol.py -q
```

Actual result: **14 passed** for structural tests. Before modification the full
PR22 suite was1576 passed,3 skipped,59 existing utcnow warnings. After addition:
**1590 passed, 3 skipped, 59 existing utcnow warnings (107.55s)**. Core, old experiment protocols/raw data and model policy
code are unchanged. No new training, action outcomes or confirming scores exist.

Structural arithmetic artifact: [JSON](online_feedback/v1/structural_validation.json)
and [SHA](online_feedback/v1/structural_validation.json.sha256). The protocol and
report are committed with the validator; exact source commit is recorded in
JOURNAL/Discussion21. Next: implement the frozen design on41/42, including
post-begin evidence snapshots and explicit withheld-receipt handling, then
audit before publishing any confirming command.
