# Historical AC0 raw storage (D4)

2026-10-31. Source PR22: `d563398bf06fc274555cb6844a86e362081fa15f`.
The replacement PR imports code/tests/protocols/reports into current main
without importing PR22's raw-containing commit ancestry. This changes storage,
not any recorded scientific outcome. It does not erase historical Git objects.

Eight raw JSON files larger than1,000,000 bytes (85108775 bytes
total) are stored in a [GitHub prerelease archive](https://github.com/realbtr/firstagi/releases/download/ac0-debug-archive-20261031/ac0-debug-raw-d563398.tar.gz).
Compressed size: 3026774 bytes. SHA256:
`a1e27c982cea03e96dbeddd88476485e97852cab6ba7ef3d4e8336ca1e0fca17`.
Per-file byte sizes, SHA256 and source Git blob IDs are in
[RAW_ARTIFACTS.json](RAW_ARTIFACTS.json); every SHA256 matches the original sidecar.
Small audits, completion receipts, `.sha256` sidecars and reports remain in Git.
Original relative raw paths in reports refer to files after restoration below.

## Restore before tests or manual audit

Download the archive into any new local output directory (replace `<download-dir>`):

```text
gh release download ac0-debug-archive-20261031 --repo realbtr/firstagi --pattern ac0-debug-raw-d563398.tar.gz --dir <download-dir>
python experiments/diagnostics/ac0_restore_artifacts.py --archive <download-dir>/ac0-debug-raw-d563398.tar.gz
python -m pytest -q
```

Restoration checks the archive SHA256/size, exact regular-file member set,
destination containment, every original file SHA256/size, and existing contents
before writing. It refuses links, unsafe paths and replacement of differing
local files. Matching files can be reused. It runs no model/generator/network
code; downloading is a separate explicit step. Restored raw paths are ignored
by Git. CI downloads this pinned release and verifies/restores the same bytes
before the unchanged full test command; no artifact-dependent tests are skipped.

## Evidence boundary

The original `on_policy_dev_20261031T0540.json` remains **INCOMPLETE** because
its raw output exceeded the original32MiB limit. Compression, storage migration,
test success or replay does not upgrade that execution receipt. Known41/42
diagnostics and the old frozen-goal study are historical, not AC0 confirming v2.
No new experiment, training run, confirming seed or independent replication
was performed to create this archive. Keep the original reports/receipts.

There is an external storage dependency: if GitHub Releases is unavailable,
artifact-dependent tests need a previously verified copy. The restorer fails
closed instead of silently fabricating data or turning the tests into skips.

## Storage validation

Fresh Release download verified all8 original raw SHA256 receipts and85,108,775 bytes.
An isolated local clone without local credentials ran the complete suite:
python -m pytest -q: **1698 passed,3 skipped,59 existing datetime warnings,43.00s**.
Eleven new storage tests cover hashes, containment, archive links, duplicate paths,
idempotency and preservation of differing local files. Artifact-dependent tests
remain enabled. No new scientific rollout or confirming run was performed.
