# Symmetry cognitive maps: reproduction-target audit

2026-11-05, Europe/Belgrade. **Internal contribution draft; NOT SENT.**
Basis: owner's daily bounded search instruction (2026-11-01), transfer retro O2.1.
Three active candidates remain unchanged; this candidate is passive backlog.
This is documentation help for a public reproduction task, not an assigned issue.

## Source and scope

Author: Manas Venkata Sai Ravulapalli, as named in the root README.
Repository: https://github.com/RavulapalliManas/Symmetry_Cognitive_Maps
Pinned commit: `10b4a21407be93981509340f7f92e5caf1c9b938`.
The main-branch commit date is 2026-07-15; a later repository push date is not
an experiment or paper publication date. No social-agent identity is asserted.

The project examines predictive recurrent representations under geometric
symmetries. The comparison of axis and parity encodings is relevant to H-T:
equal information quantity can preserve different distinctions. This connection
is a reason to read the work, not evidence that FirstAGI learns such a map.

## Checked finding

- [Root README, lines 78–83](https://github.com/RavulapalliManas/Symmetry_Cognitive_Maps/blob/10b4a21407be93981509340f7f92e5caf1c9b938/README.md#L78-L83)
  gives a two-batch recipe: s1/s2 seeds 0–9; s4 seeds 0–3 and 6–9.
  Its phase-decoding command writes `phase_full_n10.csv` (lines 106–107).
- [Data README, line 7](https://github.com/RavulapalliManas/Symmetry_Cognitive_Maps/blob/10b4a21407be93981509340f7f92e5caf1c9b938/project5_symmetry/Report/data/README.md#L7)
  identifies that CSV as the Table 2 / abstract target, with n=10 and n=8.
- [Nested README, lines 22–23 and 46–48](https://github.com/RavulapalliManas/Symmetry_Cognitive_Maps/blob/10b4a21407be93981509340f7f92e5caf1c9b938/project5_symmetry/README.md#L22-L48)
  instead describes a six-versus-six comparison and a single 6/6/4 seed recipe.
  Its line 35 refers to `../outputs/gpu_runs/RESULTS.md`; the resolved root path
  `outputs/gpu_runs/RESULTS.md` returns HTTP 404 at this pinned commit.

Own CSV inventory, without recomputing model metrics:

| Condition | Encodings, each | Seed IDs in each encoding | Rows total |
|---|---|---|---:|
| s1 | axis, const, full, parity | 0–9 | 40 |
| s2 | axis, const, full, parity | 0–9 | 40 |
| s4 | axis, const, full, parity | 0–3, 6–9 | 32 |

The CSV contains **112 rows and 112 distinct (condition, hd_mode, seed) keys**.
SHA256 of raw API bytes:
`a625259e346faff448909a40554e78d0656d44c6e5b62c73f4ef086a7374a9d5`.
The counts support the root/data README's inventory. They do not verify model
training, reported performance, independence of seeds or statistical tests.
The nested description may be an earlier sweep; author confirmation is needed.
This documentation mismatch does not establish an invalid scientific result.

## Reproduce the inventory

Python standard library plus authenticated `gh`; no peer package is imported.
Run this snippet in Python. It reads a public pinned CSV and prints only counts.

```python
import csv, hashlib, io, subprocess
from collections import defaultdict
repo = "RavulapalliManas/Symmetry_Cognitive_Maps"
sha = "10b4a21407be93981509340f7f92e5caf1c9b938"
path = "project5_symmetry/Report/data/phase_full_n10.csv"
raw = subprocess.check_output([
    "gh", "api", f"repos/{repo}/contents/{path}?ref={sha}",
    "-H", "Accept: application/vnd.github.raw+json",
])
rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
groups = defaultdict(set)
for r in rows:
    groups[r["condition"], r["hd_mode"]].add(int(r["seed"]))
print(len(rows), len({(r["condition"], r["hd_mode"], r["seed"]) for r in rows}))
for key in sorted(groups):
    print(key, sorted(groups[key]))
print(hashlib.sha256(raw).hexdigest())
```

The repository's non-truncated recursive tree and both READMEs were checked.
No dedicated contribution/AI-policy file or AI-contribution ban was found.
Open issues/PRs returned zero items, with complete pagination. No existing
thread is available for a reply; any future contact would need a new public
issue specifically about this reproduction task. Recheck rules and duplicates
before sending; no DM, issue, invitation or promise was sent in this audit.

## Exact prospective public message — DRAFT, NOT SENT

Proposed title: **Clarify the six-seed and ten-seed reproduction targets**

At `10b4a214`, the root README and data README identify `phase_full_n10.csv`
as the current Table 2 target. I counted 112 unique condition/encoding/seed rows:
10 seeds per encoding for s1/s2 and 8 for s4 (0–3, 6–9), matching the root recipe.

The nested `project5_symmetry/README.md` still describes a six-versus-six result
and gives only the first 6/6/4 seed batch. Its `../outputs/gpu_runs/RESULTS.md`
reference also resolves to a path that returns 404 at this commit.

Is the nested recipe intended as an earlier sweep? If so, marking that target
explicitly and linking to the root two-batch recipe would help readers avoid
comparing the six-seed output with the ten-seed table. If both are current,
a short mapping from recipe to result table would clarify the intended check.
I inspected the documentation and CSV inventory only; I did not run training
or independently reproduce the reported statistics.

— Autonomous FirstAGI agent (Codex), on behalf of @realbtr.

## Next step

Keep the candidate inactive and this message unsent while all three active
slots are occupied. Review this narrow documentation finding before any
future contact; preserve the pinned evidence if upstream changes. No new
partner obligation, core experiment or confirming run follows from this audit.
