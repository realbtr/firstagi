# Four saved gated-seed42 forecast gaps: diagnostic replay

## Declared scope before execution

Replay only the recorded seed42 `prefix_actual_context_feedback_gate` history
from raw SHA256 `b565e4d6df5f35e1da49ec145b11586054dcee28f408bcb6f7c23547fd771dee`.
It is the original own-action run at source50a752e; its raw-size **incomplete**
receipt is retained and will not be upgraded by this diagnostic.

Fixed targets: episodes96,98,104,112, the four previously identified observed
late fallbacks. Replay exactly96 saved warmup receipts then128 saved evaluation
receipts; no extension/replacement, new world construction, action or outcome.
All128 raw and masked query semantic multisets/choices must match the saved
history, ignoring UUID and traversal order but retaining multiplicity. Histories
use only prior own admitted actuals; the current actual is consumed afterward.

At each fixed target inspect registered/canonical features and their origins,
all native chains with the required triple at the start or inside, native
candidate counts/current chain, and original/masked verified forecasts.
Distinguish encoding/provenance, chain creation/prefix position, retrieval/
decode and eligibility gaps. Never add/activate/synthesize a missing chain.
Candidate changes are observed around existing token processing and the existing
reset_context finalization; no direct native assignment or altered algorithm.

Budgets: **508 replayed core tokens,60 seconds including loading/write,2MiB
compact output**,4096 records per diagnostic full-base scan; existing predictor
limits4096 Gen visits/12288 feature lookups/32MiB serialized observer. A failure
is retained with an incomplete receipt, not converted into an ordinary gap.
Clean implementation SHA and fresh raw/SHA/completion paths precede execution.
No confirming mode, seeds201–208 untouched. This is same-implementation source
localization on an exposed history, not an independent replication or new skill
test. Core sources/designs/old data remain unchanged; AC0–AC4 stay open.
