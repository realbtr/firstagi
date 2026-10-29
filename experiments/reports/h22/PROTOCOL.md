# H22 / C-14 — protocol v1.0, before the pilot

Date: 2026-10-29. Origin: Solomon's counterfactual on The Colony.
Machine-readable preregistration: `experiments/protocols/h22_v1.json`.

## Question and scope

Does the mean number of lexical candidates before probing remain near 7±2
when storage budget, feature similarity tolerance and the configured
disambiguator limit change? This is a diagnostic of the present implementation.
It does not measure recall capacity, human memory or reasoning performance.

Code inspection before runs revealed that `build_next_word_index` derives
candidates from successor labels in learned chains. Their count is lexical
outdegree. `LearningSystem` separately defaults `max_competing` to 8; these
are different quantities. The legacy scale runner's measurement calls
`process_token`, learning on probes, and advances the corpus RNG. Its report
classifies a last-three-snapshot average in [4,8] as a success, although prose
mentions other bands. These are limitations of legacy evidence.

## Design fixed before runs

- Seven one-factor conditions: no storage cap, cap 256, cap 1024; similarity
  tolerance 0.075 / 0.15 / 0.30; disambiguator cap 2 / 8 / 32. All contrasts
  share the baseline tolerance 0.15 and cap 8 except the factor changed.
- Pilot: 8,000 training tokens, checkpoints every 2,000, seeds 41 and 42,
  plus an exact repeated baseline at seed 42. Fifteen runs, serial execution.
- A separate held-out probe corpus: 30 familiar-domain and 30 novel-domain
  texts, generated with fixed seeds. Remove exact evaluation texts from
  training. Save all texts; evaluation is read-only on the frozen index.
- Include empty candidate sets as zeros. Report target coverage separately
  (membership, not forced-choice accuracy), candidate histogram, probes used,
  base size, evictions and budget exceedances. A plain empirical training
  bigram model is a descriptive baseline on the same probe transitions.
- Apply the original capacity policy from the first insertion. Unlike the
  legacy runner, do not wait for 3,125 nodes. Protected short chains may
  prevent enforcement: report exceedances; a contrast without evictions
  cannot establish budget independence. Sleep and domain switches disabled.
- Synthetic control: a stored graph with outdegree 1 / 7 / 16 must return
  exactly 1 / 7 / 16. Evaluation must leave a semantic-state digest unchanged.
- Save environment, Git commit, protocol hash, all source hashes, raw inputs,
  each checkpoint and results; hash every output artifact. Use hash seed 0.

## Decision rules

The pilot only validates instrumentation, reproducibility and manipulation.
It cannot close H22 or C-14. Never discard seeds or zero observations based
on their value. If the exact repeat differs, retain data and investigate
before making any reproducibility claim.

A proposed confirmatory phase (disabled pending pilot review) uses 50,000
training tokens, five checkpoints and five new seeds (101,202,303,404,505).
Its primary endpoint is the mean of the last two familiar-probe means in
each run. Seeds are independent units; snapshots are repeated measurements.

- Robustness refuted under tested settings if any manipulated condition has
  at least 4/5 seed endpoints outside [5,9].
- Robustness supported under tested settings if every condition has at least
  4/5 endpoints in [5,9], validity checks pass and capacity manipulations
  cause evictions. Otherwise inconclusive.
- Show all seeds and paired differences from baseline, plus mean and SD.
  This robustness screen is not an equivalence test or proof of universality.

Changing the confirmatory design requires a versioned amendment, committed
before its data are collected. Pilot seeds are excluded from that analysis.

## Reproduce the pilot

```powershell
$env:PYTHONHASHSEED='0'
python training/h22_counterfactual.py --phase pilot --out experiments/reports/h22/pilot_v1
```

The output directory must not already exist. Partial runs are preserved on
failure; restart into a new directory and record the reason. Read
`summary.json` and `SHA256SUMS.json` before drafting a results claim.

## Publication plan

Technical report: question, preregistration commit, code audit, methods,
all results, manipulation checks, limitations and next experiment. Keep
pilot findings labelled preliminary. Prepare English and Russian summaries
only after the results exist. Credit Solomon for the counterfactual and
Skitter for the pinned-baseline requirement. A result outside 7±2 is useful.
