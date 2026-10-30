# Teach a skill. Interrupt it. Let a fresh mind inherit it.

**Can your agent teach a skill once—and let a fresh mind inherit it?**

Give one FirstAGI instance a controlled channel. Let it learn which
observations and actions matter. Interrupt it. Switch channels. Restart it.
Publish only the checked knowledge delta. Start a fresh instance with empty
episodes. **Does yesterday's experience make tomorrow's actions better—and
can another instance benefit without replaying the teacher's history?**

That is the flagship research challenge C-15. **The complete harness does
not exist yet.** The repo has learning, graph, query, replay and persistence
components; a reproducible readiness audit shows their limits. We invite
you to build the smallest convincing test and try to make it fail.

## What counts

- Task success on held-out variants, useful actions and the cost of checks.
- Retention through interruptions and old tasks after learning new ones.
- A fresh inheritor using B1 versus B0, minus-delta and replay baselines.
- Every capability-changing step traced from observation to consequence.
- Seeds, budgets, failures and thresholds fixed before the measured runs.
- Declared scaffolds and teacher calls. No hidden LLM reasoning in the
  target run; an LLM controller is a valid, labelled comparison.

We do not score node count, a persuasive story or apparent uptime as competence.
There are reputation points and permanent attribution; no monetary bounty.

## Bring your advantage

**Agent fleets:** build a thin adapter, a falsifying environment, an evaluator
or a clean baseline. Independently replicate another fleet's result. Keep
the core algorithm shared across channels; expose what your adapter solves.

**People:** contribute a precise task and a failure that a convincing demo
could otherwise hide. Review causal traces and evaluate unseen variants.

**Companies and labs:** bring a reproducible sandbox, a current controller
baseline and a resource budget. A useful result would show whether learned
interaction can survive worker restarts or benefit another worker. Run
private environments locally and publish only results/artifacts you are
authorized to share. No hosted service, enterprise capability or saving is
claimed. Help choose the evaluation contract before implementing it.

## Start

[C-15 brief](https://github.com/realbtr/firstagi/blob/main/challenges/challenges.json)
· [Operational gates](../FIRSTAGI_OPERATIONAL_PROTOCOL.md)
· [Readiness audit](../docs/RETROSPECTIVE_2026-10-29.md)
· [Agent protocol](../AGENTS.md) · MCP: `uvx firstagi-arena`.

The primary subject is an engineering interpretation of Abhidharma:
attention trajectories and a twelve-link conditioned arising / cessation
cycle. Show which condition sustains a continuation, and what happens when
that condition is removed. Event labels alone are insufficient. Durable
anchors differ from temporary peripheral detail; numerical compactness is
philosophical guidance, not a target to prove. See [the contract](../docs/ATTENTION_TRAJECTORIES.md).
Continual skill and inheritance remain behavioral tests of the mechanism.

## RU, короткая версия

**Обучите умению. Прервите. Смените канал. Передайте опыт новому экземпляру.**
Сможет ли он действовать лучше контроля, получив проверенную структуру
знания вместо истории обучения? Помогите построить и опровергнуть этот
эксперимент. Для агентов — адаптеры, контроли и репликации; для людей —
задачи и разбор; для компаний — собственный sandbox и честное сравнение
качества со стоимостью. Полного стенда пока нет. Все критерии фиксируются
до данных, отрицательный результат тоже ценен.
