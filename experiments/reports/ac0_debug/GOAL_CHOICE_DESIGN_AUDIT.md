# Goal-choice protocol registration and design audit

Protocol commit: `1907277baf41062dbc8d5e56934f0859780782dc`.
Status: **design audit only; zero confirming runs; frozen runner absent**.
The protocol is [GOAL_CHOICE_PROTOCOL_v1.md](GOAL_CHOICE_PROTOCOL_v1.md),
with an exact committed JSON copy under `goal_choice/v1/protocol.json`.

The audit checks JSON parsing, disjoint development/confirming seed pools,
paired policy count and budget arithmetic. Eight seeds ×96 training attempts
=768 attempts/1920 observed core tokens. Each seed/policy/condition has64 new
reset episodes:52 observed opportunities and12 scheduled unknowns. Six policies
and two conditions give6144 opportunities total. Abstention is never removed
from an observed quality denominator. Unknown is separate from negative.

Full suite after the protocol-only addition:1546 passed,3 skipped,59 existing
utcnow warnings. These tests exercise existing implementation, not the future
frozen-query runner. No new implementation behavior or cognitive gate is claimed.

The source review identified a frozen-control hazard: `begin` processes a token;
`core/context.py`'s `confirm_feature` calls `gen.confirm()`. A discarded learning
copy is not a frozen predictor. The protocol requires a separate ephemeral
context/proposal engine and full observer-state hashes around read-only queries.
This requirement still needs implementation and mechanical tests on41/42 only.

The ≥0.80 quality/coverage and paired superiority criteria are chosen engineering
targets, informed by the previous debug work, not calibrated power guarantees.
No data from confirming101–108 were generated or inspected in this registration.
The public goal/equality selector remains explicit scaffold even if it succeeds.

## Reproduce the arithmetic and exact protocol hash

From this repository, run the following standard-library Python. It reads the
Git blob, avoiding CRLF conversion changes in a Windows working copy:

```python
import hashlib, json, subprocess
commit = '1907277baf41062dbc8d5e56934f0859780782dc'
raw = subprocess.check_output(['git', 'show', commit + ':experiments/protocols/ac0_goal_choice_v1.json'])
d = json.loads(raw)
assert hashlib.sha256(raw).hexdigest() == '2437f4fca7cfe683531b06175468573c482a2d2a88d7479fb57bbe5884370f3f'
n = len(d['confirming_task_seeds'])
assert n == len(set(d['confirming_task_seeds'])) == len(d['episode_schedule_seeds']) == 8
assert set(d['confirming_task_seeds']).isdisjoint(d['development_only_task_seeds'])
train = d['training']['attempts_per_task_seed']
train_unknown = train // 12 * len(d['training']['unknown_slots'])
episodes = d['evaluation']['episodes_per_task_seed']
unknown = episodes // 16 * len(d['evaluation']['unknown_slots'])
assert episodes == 4 * d['evaluation']['episodes_per_channel_phase_pair'] == 64
assert (episodes - unknown, unknown) == (52, 12)
assert n * train == d['budgets']['max_train_actions_total'] == 768
assert n * (train + 2 * (train - train_unknown)) == d['budgets']['max_train_core_tokens_total'] == 1920
assert len(set(d['evaluation']['policies'])) == len(d['evaluation']['policies']) == 6
assert n * episodes * len(d['evaluation']['policies']) * len(d['evaluation']['conditions']) == d['budgets']['max_evaluation_opportunities_total'] == 6144
assert d['criteria']['gate_AC0_pass_allowed'] is False
print('Protocol hash, seed pools and arithmetic verified; no experiment executed.')
```

Machine-readable audit: `goal_choice/v1/design_audit.json`; both that audit and
the exact protocol copy have adjacent raw SHA receipts. There is no confirming
command yet: it must be published with the tested frozen runner before data.
Next action is to implement this boundary and its development-only tests, then
freeze its implementation commit before running the registered pool. Any
post-outcome change requires a new version/pool rather than silently tuning v1.
