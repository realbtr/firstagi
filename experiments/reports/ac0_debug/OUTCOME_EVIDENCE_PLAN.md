# Named-Gen outcome replay: debug plan v0.1

Before data: seeds 41/42, fixed/random native warmup 48 attempts per cohort.
Finalize pending warmup chain as in recall ablation. Replay exactly those 48
fixture operations in a fresh sandbox with the same seed/rules. Each cue uses
a fresh copy of the finalized trained observer, exact_learned_prefix scaffold,
one cue token; probe updates discarded. No manual Gen construction or oracle.

For every live eligible operation binding, read the immediately following
operation_to_observation feature of the SAME Gen only if its unique recorded
origin matches channel and proposed operation. Retain all forecasts matching
the fixture operation; do not choose a goal-seeking action or resolve conflicts.
Seal predictions in memory with a digest BEFORE world.act. Score each named
Gen forecast against actual observation, ignoring fixture expected_observation
and fixture prediction_support. Unknown is never negative. Native support
counters are not updated; evidence is an external receipt. Record repeated
use of Gen IDs and task-divergence/positive-prediction cases separately.

Mechanical checks: source unchanged; predictions sealed before action; every
receipt maps to its cue/operation; no target/oracle in forecast extraction;
positive/negative/three unknown statuses covered by unit interventions.
No numeric skill success threshold is declared: this is explicitly debug,
in-sample, and a non-independent replay. Counts are descriptive, not a gate.
Negative unit intervention is not an empirical rule-change experiment.
Remaining confirming controls: held-out episodes, frozen model, fixed/random
action baselines, preregistered numeric task-quality/cost thresholds and real
support-dependent reuse. Additional full-base scans are not equal compute.
