"""
Демо NarratorDriver — активная фаза модели.

Обучаем систему на корпусе Муми-тролля (5 проходов),
затем запускаем нарратор на всех 4 уровнях творчества.

Запуск:
    py -X utf8 training/narrator_demo.py
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.capacity import CapacityBudget
from core.dream import ContextQueryLog
from core.learning import LearningSystem
from core.provisional import ProvisionalBase
from drivers.text_driver import TextDriver
from drivers.narrator_driver import NarratorDriver, CreativityLevel, NarratorBridge
from training.moomin_corpus import MOOMIN_CORPUS

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


# ── 1. Обучение ────────────────────────────────────────────────────────────────
hr("ОБУЧЕНИЕ (5 проходов)")

capacity    = CapacityBudget(max_gens=8_000)
provisional = ProvisionalBase(min_confirmations=2, max_age=200)
system      = LearningSystem(
    capacity_budget=capacity,
    query_log=ContextQueryLog(),
    provisional_base=provisional,
)

drv = TextDriver("moomin")
total = confirmed = completed = 0
for _ in range(5):
    for text in MOOMIN_CORPUS:
        for tok in drv.produce(text):
            r = system.process_token(tok)
            total += 1
            if r.outcome.name == "CONFIRMED": confirmed += 1
            elif r.outcome.name == "COMPLETED": completed += 1
        system.reset_context()

mr = (confirmed + completed) / max(total, 1)
print(f"  токенов={total:,}  base_size={system.base.size()}  MR={mr:.3f}")


# ── 2. Создание нарратора ──────────────────────────────────────────────────────
hr("НАРРАТОР")
narrator = NarratorDriver(system.base, seed=42)

graph = narrator._graph
print(f"  WordGraph: {len(graph._nodes)} узлов, {len(graph._edges)} рёбер")
print(f"\n  Топ-15 узлов по средн. значимости:")
for node in graph.high_significance_words(top_n=15):
    nbs = [w for w, _ in graph.neighbors(node.word, top_n=3)]
    print(f"    {CY}{node.word:<18}{W} sig={node.avg_significance:.3f}  cnt={node.occurrence_count:3d}  → {', '.join(nbs)}")

# Персонажи
profiles = narrator.character_profiles(max_profiles=12)
print(f"\n  Персонажи ({len(profiles)}):")
for p in profiles:
    print(f"    {p}")


# ── 3. Генерация по уровням творчества ────────────────────────────────────────
# Выбираем реальные стартовые слова из графа — объекты/цели персонажей
# (TextDriver кодирует ПЕРЕХОДЫ: label = слово-назначение, не слово-субъект.
#  Субъекты предложений не попадают в граф.)
top_nodes = [n.word for n in graph.high_significance_words(top_n=30)]
# Предпочитаем семантически богатые слова (не союзы/предлоги)
STOPWORDS = {"и", "в", "на", "у", "к", "с", "а", "но", "по", "за", "из", "не"}
good_starts = [w for w in top_nodes if w not in STOPWORDS and len(w) >= 4][:6]
print(f"\n  Стартовые слова для демо: {good_starts}\n")

LEVELS = [
    (CreativityLevel.RECALL,  "RECALL  — точное воспроизведение"),
    (CreativityLevel.RETELL,  "RETELL  — пересказ"),
    (CreativityLevel.COMPOSE, "COMPOSE — свободное сочинение"),
    (CreativityLevel.DREAM,   "DREAM   — творческая аналогия"),
]

for level, desc in LEVELS:
    hr(desc)
    for start in good_starts[:4]:
        result = narrator.generate(level, start_word=start, max_words=12)
        if not result.text:
            continue
        coh = f"{result.coherence_score:.3f}"
        chars = ", ".join(result.characters_mentioned) or "—"
        print(f"\n  {CY}«{result.text}»{W}")
        print(f"  {DM}start={start}  coherence={coh}  chars=[{chars}]{W}")


# ── 4. Кросс-доменный нарратив ────────────────────────────────────────────────
hr("КРОСС-ДОМЕННЫЙ НАРРАТИВ")
# Используем реальные слова из графа: снусмумрика(объект), сумочку, мемуары, играет
pairs_words = good_starts
pairs = [
    (pairs_words[0], pairs_words[1]) if len(pairs_words) >= 2 else ("занят", "длинная"),
    (pairs_words[2], pairs_words[3]) if len(pairs_words) >= 4 else ("играет", "сумочку"),
    (pairs_words[4], pairs_words[5]) if len(pairs_words) >= 6 else ("мемуары", "реки"),
]
for a, b in pairs:
    result = narrator.generate_cross_domain(a, b, max_words=14)
    coh = f"{result.coherence_score:.3f}"
    print(f"\n  {AM}«{result.text}»{W}")
    print(f"  {DM}{a} → {b}  coherence={coh}{W}")


# ── 5. Что модель знает о ключевых словах ─────────────────────────────────────
hr("ЧТО МОДЕЛЬ ЗНАЕТ")
words_to_check = ["снусмумрик", "зима", "море", "дом", "гармошке", "палатку", "маяк"]
for w in words_to_check:
    knows = narrator.what_i_know_about(w, top_n=6)
    print(f"  {CY}{w}{W}: {' · '.join(knows) or '(нет данных)'}")


# ── 6. Пробелы знания ─────────────────────────────────────────────────────────
hr("ВОПРОСЫ О ПРОБЕЛАХ ЗНАНИЯ")
gaps = narrator.knowledge_gaps(max_questions=8)
for i, q in enumerate(gaps, 1):
    print(f"  {AM}{i}. {q}{W}")


# ── 7. NarratorBridge — онлайн-обновление ─────────────────────────────────────
hr("NARRATOR BRIDGE — онлайн-обновление графа")
bridge = NarratorBridge(narrator)
test_text = "Снусмумрик вернулся с тёплым ветром"
for tok in drv.produce(test_text):
    r = system.process_token(tok)
    bridge.on_step(tok.label or "", r.outcome.name)
system.reset_context()
print(f"  Обработан текст: «{test_text}»")
print(f"  Пробелы обнаруженные bridge: {bridge.recent_gaps(n=5) or '(нет)'}")

# Генерируем после обновления
narrator.rebuild_graph()
result = narrator.generate(CreativityLevel.RETELL, start_word="снусмумрик", max_words=10)
print(f"\n  {GR}«{result.text}»{W}  (после bridge-обновления)")

hr()
print(f"\n{BD}Демо завершено.{W}\n")
