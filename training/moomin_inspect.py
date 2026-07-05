"""
Анализ «сознания» модели после обучения на корпусе Муми-тролля.

Запуск: py -X utf8 training/moomin_inspect.py
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.capacity import CapacityBudget
from core.dream import ContextQueryLog, CrossDomainDetector, DomainRegistry, SleepDriver
from core.learning import LearningSystem
from core.provisional import ProvisionalBase
from core.algorithm import StepOutcome
from drivers.text_driver import TextDriver
from training.moomin_corpus import ALL_DOMAINS, MOOMIN_CORPUS

W  = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; YL = "\033[33m"

def hr(title=""):
    w = 64
    if title:
        pad = (w - len(title) - 2) // 2
        print(f"\n{BD}{'═'*pad} {title} {'═'*pad}{W}")
    else:
        print(f"{DM}{'─'*w}{W}")

# ── 1. Обучение ───────────────────────────────────────────────────────────────
hr("ОБУЧЕНИЕ")
query_log   = ContextQueryLog()
capacity    = CapacityBudget(max_gens=8_000)
provisional = ProvisionalBase(min_confirmations=2, max_age=200)
system      = LearningSystem(
    capacity_budget=capacity,
    query_log=query_log,
    provisional_base=provisional,
)

drv = TextDriver("moomin")
total = confirmed = completed = refuted = exploring = 0

# 5 проходов по всему корпусу (≈ 64 тексты × ~8 слов × 5 = ~2560 токенов)
for pass_n in range(5):
    for text in MOOMIN_CORPUS:
        for tok in drv.produce(text):
            r = system.process_token(tok)
            total += 1
            if r.outcome == StepOutcome.CONFIRMED:  confirmed += 1
            elif r.outcome == StepOutcome.COMPLETED: completed += 1
            elif r.outcome == StepOutcome.REFUTED:   refuted   += 1
            elif r.outcome == StepOutcome.EXPLORING: exploring += 1
        system.reset_context()

print(f"  Токенов:    {total:,}")
print(f"  CONFIRMED:  {confirmed:,}  ({confirmed/total:.1%})")
print(f"  COMPLETED:  {completed:,}  ({completed/total:.1%})")
print(f"  REFUTED:    {refuted:,}   ({refuted/total:.1%})")
print(f"  EXPLORING:  {exploring:,}  ({exploring/total:.1%})")
print(f"  MR = {(confirmed+completed)/total:.3f}")
print(f"  Base size:  {system.base.size()}")
print(f"  Provisional pending: {provisional.size()}, promoted={provisional.stats()['promoted']}, evicted={provisional.stats()['evicted']}")

# ── 2. Топ Gen по значимости ──────────────────────────────────────────────────
hr("ТОП-25 Gen ПО ЗНАЧИМОСТИ")
all_gens = sorted(system.base.all(), key=lambda g: -g.significance)
print(f"  {'sig':>6}  {'chain':>5}  {'s':>5}  {'st':>4}  label")
hr()
for g in all_gens[:25]:
    label = g.label or "(auto)"
    print(f"  {g.significance:6.3f}  {g.generalization_level:>5}  {g.success_count:>5}  {g.stop_count:>4}  {CY}{label}{W}")

# ── 3. Распределение по generalization_level ─────────────────────────────────────────
hr("РАСПРЕДЕЛЕНИЕ ПО ГЛУБИНЕ ЦЕПОЧКИ")
from collections import defaultdict
chain_dist = defaultdict(list)
for g in system.base.all():
    chain_dist[g.generalization_level].append(g.significance)

for cl in sorted(chain_dist):
    sigs = chain_dist[cl]
    avg  = sum(sigs) / len(sigs)
    bar  = "█" * min(len(sigs), 40)
    print(f"  chain={cl:2d}  n={len(sigs):4d}  avg_sig={avg:.3f}  {DM}{bar}{W}")

# ── 4. Длинные цепочки (глубокие обобщения) ───────────────────────────────────
hr("ДЛИННЫЕ ЦЕПОЧКИ (chain ≥ 4) — ГЛУБОКИЕ ПАТТЕРНЫ")
deep = [g for g in system.base.all() if g.generalization_level >= 4]
deep.sort(key=lambda g: -g.significance)
for g in deep[:15]:
    print(f"  {GR}chain={g.generalization_level}{W}  sig={g.significance:.3f}  «{g.label}»")

# ── 5. «Сон» — запустим sleep_cycle ─────────────────────────────────────────
hr("СОН И КОНСОЛИДАЦИЯ")
from core.dream import (
    sleep_cycle, ReplayEngine, CrossDomainDetector, DomainRegistry, SleepDriver
)
from core.timescale import TimescaleScheduler

ts = TimescaleScheduler()
profile = ts.depth_profile(system.base)
print(f"\n  TimescaleScheduler — пулы Gen:")
for tier, stats in profile.items():
    print(f"    {str(tier):20s}: n={stats.count:4d}  avg_sig={stats.avg_sig:.3f}")

# Топ кандидаты для сна (urgency)
evict_cands = ts.eviction_candidates(system.base, n=10)
if evict_cands:
    print(f"\n  Кандидаты на вытеснение (низкая значимость):")
    for g in evict_cands[:5]:
        print(f"    sig={g.significance:.3f}  chain={g.generalization_level}  «{g.label}»")

# Запуск sleep_cycle
domain_reg = DomainRegistry()
cross_det  = CrossDomainDetector(domain_registry=domain_reg, min_domains=2)
replay_eng = ReplayEngine(system)
print(f"\n  Запуск sleep_cycle (n_replays=5)...")
try:
    result = sleep_cycle(system, replay_eng, cross_det, n_replays=5, replay_steps=10)
    print(f"  meta_gen созданы: {result.meta_gen_created}")
    print(f"  replays:          {result.replays_done}")
    if result.meta_gen_created:
        # Показать новые Meta-Gen
        new_gens = sorted(system.base.all(), key=lambda g: -g.generalization_level)[:5]
        for g in new_gens:
            print(f"    chain={g.generalization_level}  «{g.label}»")
except Exception as e:
    print(f"  sleep_cycle: {e}")

# ── 6. ContextQueryLog — что модель запрашивает ───────────────────────────────
hr("CURIOSITY — ЧТО МОДЕЛЬ ХОЧЕТ УВИДЕТЬ СНОВА")

# Пропустим корпус ещё раз собирая queries
system.reset_context()
for text in MOOMIN_CORPUS:
    for tok in drv.produce(text):
        system.process_token(tok)
    system.reset_context()

queries = []
try:
    queries = system.teaching_log.peek_queries()
except Exception:
    pass
print(f"\n  ContextQuery записей: {len(queries)}")
for q in queries[:15]:
    qt   = getattr(q, 'query_text', str(q))
    tt   = getattr(q, 'trigger_token', '?')
    gap  = getattr(q, 'confidence_gap', 0.0)
    out  = getattr(q, 'trigger_outcome', '?')
    print(f"  [{out}] триггер=«{tt}»  gap={gap:.2f}")
    print(f"         → {AM}{qt}{W}")

# ── 7. Свободный запуск — что модель «хочет» без входа ──────────────────────
hr("СВОБОДНЫЙ ЗАПУСК — кандидаты на следующий токен")
system.reset_context()
candidates_free = system.get_next_word_candidates()
print(f"\n  Кандидаты (из активного контекста, без входных данных):")
if candidates_free:
    for w in candidates_free[:20]:
        print(f"    «{CY}{w}{W}»")
else:
    print(f"    (контекст пуст — нет активных Gen)")

# ── 8. Инициатива модели ─────────────────────────────────────────────────────
hr("ИНИЦИАТИВА — что модель предсказывает")
proposals = system.initiative.last_proposals if hasattr(system, 'initiative') else []
hit_rate  = system.initiative.hit_rate if hasattr(system, 'initiative') else 0
print(f"\n  Hit rate инициативы: {hit_rate:.1%}")
for p in proposals[:10]:
    print(f"  «{p.label}»  conf={p.confidence:.2f}  → next_feat={p.next_feature_id[:8]}…")

# ── 9. Нарратив модели ───────────────────────────────────────────────────────
hr("НАРРАТИВ МОДЕЛИ")
try:
    narrative = system.get_minimal_narrative()
    print(narrative)
except Exception as e:
    print(f"  (нарратив недоступен: {e})")

hr()
print(f"\n{BD}Анализ завершён.{W}\n")
