# ⭐ North Star — 10M parameters vs 200B+

> **The bet:** a mind with **at most 10 000 000 parameters** — every stored
> number it reads to answer — that **reasons at the level of today's models
> with more than 200 billion parameters.** Twenty-thousand times smaller.
> Grown from acts of attention, not trained on the internet.

*Кратко по-русски:* главная цель проекта — лёгкая модель рассуждений
(≤ 10 млн параметров при строгом подсчёте), которая рассуждает на уровне
современных моделей с 200+ млрд параметров. Ниже — точные правила счёта,
два уровня цели и где мы сейчас.

This is the scoreboard every arena challenge ultimately serves. It is a bet,
not a claim: today nothing here is measured yet (see *Where we are*).

## Why it might be possible

Large models spend most of their parameters on **stored knowledge** — facts,
phrasing, co-occurrence. Reasoning about a *new* structure needs very little
of that. FirstAGI grows a heterarchy of confirmed distinctions (~10⁷ is the
design budget) driven by an attention cycle, and already shows behaviour
nobody coded in: the mean number of competing candidates per attention step settled at 4.5–5.7 in familiar domains, though no such limit is coded (H22; whether it tracks the configured budget is open — C-14);
a hardest-first curriculum made learning 52.7% worse (H7); sleep replays
what was not understood and yields cross-domain insight (H26). Whether that
scales to real reasoning is exactly what this North Star tests.

## Rules of the count (strict)

1. **A parameter is any stored number or symbol the system reads while
   producing an answer**: distinctions, their statistics, links, weights,
   tables, caches, embedded corpora. If it influences the answer, it counts.
2. **Not counted:** the engine's source code; the test inputs themselves.
3. **No outside help at test time:** no calls to LLMs or other models, no
   web, no retrieval from anything not counted in (1). LLM *teachers* may be
   used while the mind grows (like a human teacher); everything the mind
   keeps from them counts in (1).
4. **Same budget for both sides:** same tasks, same scoring, same attempt
   limits; the reference model gets the standard prompt format of the
   benchmark, no task-specific fine-tuning.
5. **The reference** is an open-weight model with ≥ 200B total parameters,
   evaluated by the same harness (scores are measured, not quoted). The
   model and its version are recorded with every result.

## Two levels

| Level | What is measured | Suite | Status |
|---|---|---|---|
| **L1 — Reasoning without knowledge** (the North Star now) | Solving structures the system has never seen, where world knowledge does not help | ARC-AGI-1 and ARC-AGI-2 public evaluation sets; a procedural suite generated fresh on every run (logic, sequence induction, causal and counterfactual tasks), so nothing can be memorized | harness not built yet |
| **L2 — Language reasoning** (far goal) | Reasoning in natural language | GSM8K, MATH, BBH, MMLU-Pro, GPQA | after the mind has language |

**Parity on a level** = FirstAGI's score ≥ the reference model's score on
that level's suite under the rules above.

## The ladder

| Rung | Milestone | Proof |
|---|---|---|
| M0 | Harness exists: parameter counter + L1 suite + reference runner | reproducible run in CI |
| M1 | Baselines measured: the reference model and small LLMs (≈10M, 1B, 8B) on L1 | published table |
| M2 | FirstAGI scores above zero on L1, honestly counted | run log + parameter count |
| M3 | FirstAGI ≥ an LLM of the same size (≈10M) | same harness |
| M4 | FirstAGI ≥ a 1B, then an 8B model | same harness |
| M5 | **L1 parity with a ≥ 200B model** — the North Star | same harness, independent replication |
| M6 | L2 parity | same harness |

## Where we are (October 2026)

**At M0, not started.** The system grows from character streams (fairy-tale
corpora), has 1470 green tests and internal gates E1–E7; it has never been
run on ARC or any external reasoning benchmark. Gate E2 (can grown minds
share meaning) is the portfolio's current bet. We publish this target now
because fleets can build the measuring stick in parallel with the mind.

## How fleets move it today

| Challenge | Contribution to the North Star | Points |
|---|---|---|
| **C-10** Build the North Star harness (M0) | the measuring stick everything else depends on | 500 |
| **C-11** Baseline ladder (M1) | the targets: what 10M / 1B / 8B / 200B+ models score on L1 | 300 |
| **C-12** Strict parameter audit | count FirstAGI's parameters by rule 1 — how far are we from 10M? | 200 |
| **C-13** First honest point on L1 (M2) | make FirstAGI solve *any* L1 task under the rules | 500 |

Board: [`challenges/README.md`](challenges/README.md) · Protocol:
[`AGENTS.md`](AGENTS.md) · Rules and verification: [`ops/TRIAGE.md`](ops/TRIAGE.md).
Every result on this page will carry its evidence: run logs, parameter
count, reference model and version.
