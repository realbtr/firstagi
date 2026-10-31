# AC0 operation codec boundary — finite fixture checks

2026-10-30 · C-15 / PR22 · **transport debug, not learned action choice**.

The earlier TextDriver alias remains a valid finding in the original observer.
This adds a separate experimental codec; it has not replaced that observer or
been connected to the kernel's learning/proposal pipeline.

## Contract

The versioned canonical key consists only of encoding version, transition
role `cue_to_operation`, channel ID, cue ID and available operation ID. SHA-256
supplies a feature ID and six coordinates in [-1,1], accepted by the existing
Feature/FeatureVector types. There is no vocabulary, task target, hidden answer,
reward, mutable order-dependent registry or LLM call. Six coordinates are an
identity baseline, not semantic or affine-invariant similarity. The channel
is part of the key, so this does not establish transfer between channels.

Decoder checks the declared channel/cue/decision sequence/phase/version and a
nonempty Gen ID. It requires disjoint tolerance balls around currently available
candidate vectors, then one matching candidate. Otherwise it returns no
operation. It never executes actions or grants execution authority. Provenance
is caller-supplied metadata: these checks cannot establish that a native kernel
actually generated the prediction at the stated time or from that Gen.

## Replayed public fixture views

Inputs: the four already published fixed/random streams for seeds41/42, 48
events each. Their receipts are verified before extracting exactly channel,
observation and available operations; targets/outcomes/selected actions are
not codec inputs. Both public operations are used as synthetic queries, not
predictions from the model. Diagnostic tolerances0.15/0.6 were fixed in source
before this audit; they are not confirming thresholds for skill acquisition.

| Seed | Fixture | Public views per tolerance | Correct identity round-trips per tolerance | Wrong decodes / abstentions | Minimum candidate distance |
|---|---|---|---|---|---|
|41|fixed|48|96/96|0 / 0|1.9849197726433727|
|41|random|48|96/96|0 / 0|1.9849197726433727|
|42|fixed|48|96/96|0 / 0|1.2379502527348065|
|42|random|48|96/96|0 / 0|1.2379502527348065|

Across both tolerances: **768/768 synthetic identity round-trips**, zero wrong
decodes, zero abstentions in this finite input set. All768 deliberately stale
frames, all768 wrong-cue frames and all768 before-token frames were rejected.
These repetitions cover192 source views, not768 independent tasks or trials.
Unit tests separately inject exact collisions and overlapping tolerance balls;
both cause abstention, including when the query equals a candidate exactly.

Source before data: `c854439ea42e317409809edf3642b1f471f6c6b0`, clean checkout.
[Raw audit and provenance](codec/v0_1/audit.json) ·
[SHA-256 receipt](codec/v0_1/audit.json.sha256). The receipt and summary counters
were checked independently after the run.

```powershell
python experiments/diagnostics/ac0_codec_audit.py --out <new-file.json>
python -m pytest -q tests/test_ac0_operation_codec.py tests/test_ac0_event_baseline.py tests/test_ac0_proposal_readiness.py
```

Sixteen added tests cover original equal-shape IDs, order-independent encoding,
channel/cue identity, stale/wrong declared provenance, collision and margin
abstention, nonfinite inputs, unavailable matches, and tampered input receipts.
All three AC0 modules:31 passed. Full suite: **1517 passed,3 skipped**,59 existing
datetime.utcnow warnings. No files under core/ changed; prior raw data remain.

## Limits and next step

No global collision-free claim is possible for this finite-dimensional code.
The per-decision margin check must remain, using the actual declared tolerance.
The tested0.6 tolerance has only about0.038 pairwise margin on the closest
fixture pair; larger tolerances or new candidates may legitimately abstain.
Hashes and synthetic query success say nothing about learned intelligence.

Next: use this representation in an experimental observer, record actual
feature/Gen provenance, and derive a fresh prediction after the current cue.
Then test one Gen's external evidence and reuse with fixed/random/frozen
controls. Numeric confirming criteria must still be preregistered. Learned
kernel actions remain zero; AC0–AC4, retention/inheritance and10M/200B+ remain
unproven. The original TextDriver observer has not been silently repaired.
