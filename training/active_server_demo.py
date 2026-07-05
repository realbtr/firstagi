"""
training/active_server_demo.py — Демонстрация Active Corpus Server + гетерархии.

Запуск:
    py -X utf8 training/active_server_demo.py
    py -X utf8 training/active_server_demo.py --cycles 20 --phase 2
    py -X utf8 training/active_server_demo.py --phase 3 --verbose

Три режима
──────────
  phase=1: ActiveTextServer базовая навигация — запросы, probe, shift
  phase=2: Автономный цикл — модель сама строит запросы из своих Gen
  phase=3: Гетерархия — молодая модель задаёт вопросы старшим сообществам
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from core.learning import LearningSystem
from core.capacity import CapacityBudget
from core.query_builder import QueryBuilder
from core.heterarchy import HeterarchyRouter, ModelNode
from app.text_server import ActiveTextServer, ZoomLevel
from drivers.text_driver import TextDriver

# ANSI
W  = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; YL = "\033[33m"

def hr(title: str = "", w: int = 68) -> None:
    if title:
        pad = (w - len(title) - 2) // 2
        print(f"\n{BD}{'═'*pad} {title} {'═'*pad}{W}")
    else:
        print(f"{DM}{'─'*w}{W}")


# ══════════════════════════════════════════════════════════════════════════════
# Корпус для демо
# ══════════════════════════════════════════════════════════════════════════════

CORPUS = {
    "children_1": {
        "domain": "children",
        "title": "Маша и медведь",
        "text": """Маша пошла в лес за грибами.
В лесу Маша встретила медведя.
Медведь принёс Маше пирог с грибами.
Маша обрадовалась и угостила медведя.
Медведь и Маша стали друзьями.""",
    },
    "children_2": {
        "domain": "children",
        "title": "Заяц и морковка",
        "text": """Заяц нашёл большую морковку в огороде.
Заяц принёс морковку маме.
Мама обрадовалась и сварила суп.
Заяц и мама съели суп вместе.
Это был вкусный суп из морковки.""",
    },
    "children_3": {
        "domain": "children",
        "title": "Кот и мышка",
        "text": """Кот жил в большом доме.
Кот мяукает когда хочет есть.
Мышка принесла коту сыр.
Кот обрадовался и не стал ловить мышку.
Кот и мышка подружились.""",
    },
    "astronomy_1": {
        "domain": "astronomy",
        "title": "Звёзды",
        "text": """Звёзды светят в ночном небе.
Каждая звезда имеет свою орбиту.
Телескоп позволяет увидеть далёкие звёзды.
Астрономы изучают движение звёзд и планет.
Планеты вращаются вокруг звезды.""",
    },
    "cooking_1": {
        "domain": "cooking",
        "title": "Рецепт пирога",
        "text": """Пирог готовят из муки и яиц.
Нужно добавить сахар и масло.
Тесто раскатывают и кладут начинку.
Пирог пекут в духовке час.
Готовый пирог украшают кремом.""",
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# Phase 1: базовая навигация
# ══════════════════════════════════════════════════════════════════════════════

def phase_1_navigation() -> None:
    hr("ФАЗА 1: Курсорная навигация")

    server = ActiveTextServer()
    for doc_id, info in CORPUS.items():
        server.add_document(doc_id, info["text"], domain=info["domain"], title=info["title"])

    print(f"\n  Корпус: {server.document_count()} документов")
    print(f"  Домены: children, astronomy, cooking\n")

    from core.query_builder import LeakyTemplate, TemplateSlot

    # Запрос 1: найти все упоминания «принёс»
    hr("Запрос: «[?] принёс [?..?] маше|маме»")
    t1 = LeakyTemplate(slots=[
        TemplateSlot(kind="wildcard", words=[], max_gap=2),
        TemplateSlot(kind="anchor",   words=["принёс", "принесла"]),
        TemplateSlot(kind="required", words=["маше", "маме", "коту"], max_gap=3),
    ], source="manual", confidence=0.8)
    print(f"  Шаблон: {t1}")
    print(f"  Regex:  {t1.to_regex().pattern}\n")
    hits = server.search(t1, zoom=ZoomLevel.CORPUS)
    for h in hits:
        print(f"  → {CY}{h.doc_id}{W}[p{h.para_idx}:{h.token_idx}]: «{DM}{h.fragment}{W}»")

    # Probe: перейти к первому совпадению и проверить следующий токен
    if hits:
        hr("Probe: ожидаем следующий токен после «принёс»")
        server.navigate_to(hits[0])
        frag = server.read(8)
        print(f"  Текущий фрагмент: {AM}{' '.join(frag.tokens)}{W}")

        # Сдвинуть к «принёс» (token[1]), затем probe +1 → «маше»
        server.shift(1)
        probe_result = server.probe(expected="маше", delta=1)
        status = f"{GR}✓ HIT{W}" if probe_result.hit else f"{RD}✗ MISS{W}"
        print(f"  Probe(маше, delta=+1): {status}")
        print(f"  Реальный токен: «{probe_result.actual_token}»")
        if not probe_result.hit and probe_result.shift_to_next > 0:
            print(f"  Следующее вхождение «маше» через {AM}{probe_result.shift_to_next}{W} токенов")

    # Запрос 2: «дырявый» шаблон по домену
    hr("Запрос по домену astronomy: «звезда .* орбита»")
    t2 = LeakyTemplate(slots=[
        TemplateSlot(kind="anchor",   words=["звезда", "звёзды"]),
        TemplateSlot(kind="required", words=["орбита", "орбиту"], max_gap=5),
    ], source="astronomy_q", confidence=0.7)
    print(f"  Шаблон: {t2}\n")
    hits2 = server.search(t2, zoom=ZoomLevel.CORPUS)
    for h in hits2:
        print(f"  → {CY}{h.doc_id}{W}: «{DM}{h.fragment}{W}»")
    if not hits2:
        print(f"  {RD}Не найдено → нужна эскалация к учителю{W}")

    print(f"\n  Статистика навигации: {server.stats}")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2: автономный цикл
# ══════════════════════════════════════════════════════════════════════════════

def phase_2_autonomous(cycles: int = 10, verbose: bool = False) -> None:
    hr(f"ФАЗА 2: Автономный цикл ({cycles} итераций)")

    system = LearningSystem(capacity_budget=CapacityBudget(max_gens=5000))
    driver = TextDriver(system)
    server = ActiveTextServer()

    for doc_id, info in CORPUS.items():
        server.add_document(doc_id, info["text"], domain=info["domain"], title=info["title"])

    # Начальный прогрев на одном тексте
    for tok in driver.produce(CORPUS["children_1"]["text"]):
        system.process_token(tok)
    print(f"  Прогрев завершён: {system.base.size()} Gen\n")

    qbuilder = QueryBuilder()
    miss_count = 0

    def on_cycle(cycle: int, status: str) -> None:
        nonlocal miss_count
        if "miss" in status:
            miss_count += 1
            print(f"  [{cycle:>3}] {RD}miss{W}: {DM}{status}{W}")
        elif "hit" in status:
            print(f"  [{cycle:>3}] {GR}hit {W}: {DM}{status}{W}  base={system.base.size()}")
        elif verbose:
            print(f"  [{cycle:>3}] {AM}{status}{W}")

    def on_search_fail(template) -> None:
        print(f"       {YL}→ Эскалация к учителю: «{template}»{W}")

    server.on_search_fail(on_search_fail)

    print(f"  Запуск автономного цикла...\n")
    server.run_active_loop(system, driver, max_cycles=cycles, on_cycle=on_cycle)

    print(f"\n  Итог: {system.base.size()} Gen  |  "
          f"поисков={server.stats['searches']}  "
          f"попаданий={server.stats['hits']}  "
          f"промахов={miss_count}")


# ══════════════════════════════════════════════════════════════════════════════
# Phase 3: гетерархия
# ══════════════════════════════════════════════════════════════════════════════

def phase_3_heterarchy() -> None:
    hr("ФАЗА 3: Гетерархия моделей")

    # Создать 4 независимых LearningSystem
    def make_system(training_texts: list, passes: int = 5) -> LearningSystem:
        sys = LearningSystem(capacity_budget=CapacityBudget(max_gens=10_000))
        drv = TextDriver(sys)
        for _ in range(passes):
            for text in training_texts:
                for tok in drv.produce(text):
                    sys.process_token(tok)
        return sys

    print("  Создание сообществ (обучение займёт ~5 сек)...")

    # Детское сообщество — 2 уровня
    children_novice = make_system(
        [CORPUS["children_1"]["text"]],
        passes=3,
    )
    children_senior = make_system(
        [CORPUS[f"children_{i}"]["text"] for i in [1, 2, 3]],
        passes=8,
    )

    # Сообщество по астрономии — LLM-фоллбэк (имитация)
    astronomy_system = make_system(
        [CORPUS["astronomy_1"]["text"]],
        passes=10,
    )

    # Создать ModelNode для каждого
    router = HeterarchyRouter()

    novice_node = ModelNode(
        "novice",  children_novice, domains={"children"}, experience=0
    )
    senior_node = ModelNode(
        "children_senior", children_senior, domains={"children"}, experience=2
    )
    astro_node = ModelNode(
        "astronomy_master", astronomy_system, domains={"astronomy"}, experience=3
    )

    # Имитация LLM как мастер-узла с широким охватом
    def llm_fallback(req):
        from core.heterarchy import TeachResponse
        # В реальности здесь был бы Claude API
        print(f"  {MG}[LLM]{W} Запрос: «{req.question}»")
        answer_map = {
            "принёс": ["волк", "принёс", "корзинку", "маше"],
            "маше":   ["маша", "сказала", "спасибо", "медведю"],
            "звезда": ["большая", "звезда", "видна", "в", "телескоп"],
        }
        for kw, tokens in answer_map.items():
            if kw in req.question.lower():
                print(f"  {MG}[LLM]{W} Ответ: {tokens}")
                return TeachResponse(tokens=tokens, source_id="llm", confidence=0.7)
        return TeachResponse(tokens=[], source_id="llm")

    router.set_llm_fallback(llm_fallback)
    router.register(novice_node)
    router.register(senior_node)
    router.register(astro_node)

    novice_node.add_mentor(senior_node)
    novice_node.add_mentor(astro_node)

    print(f"\n  Гетерархия:\n{router.summary()}\n")
    print(f"  novice:  {children_novice.base.size()} Gen  (children×3)")
    print(f"  senior:  {children_senior.base.size()} Gen  (children×8)")
    print(f"  astro:   {astronomy_system.base.size()} Gen  (astronomy×10)")

    # Сгенерировать вопросы от новичка
    hr("Вопросы от новичка → роутинг")

    from drivers.narrator_driver import NarratorDriver
    narrator = NarratorDriver(children_novice.base, seed=42)
    questions = (
        narrator.pattern_questions(max_questions=4) +
        narrator.knowledge_gaps(max_questions=3)
    )

    if not questions:
        questions = [
            "Кто ещё принёс маше?",
            "Что дальше после обрадовалась?",
            "Где живёт звезда?",
        ]

    driver = TextDriver(children_novice)
    total_learned = 0

    for q in questions:
        domain = novice_node._detect_domain(q)
        print(f"\n  {YL}❓{W} «{q}»  {DM}(домен: {domain or 'неизвестен'}){W}")

        resp = router.route(q, novice_node, domain=domain)
        if resp:
            n = novice_node.learn_from_response(resp, driver)
            total_learned += n
            print(f"    {GR}← {resp.source_id}:{W} {resp.tokens}  (+{n} токен.)")
        else:
            print(f"    {RD}← нет ответа{W}")

    print(f"\n  Итог: новичок получил {total_learned} токенов от старших")
    print(f"  novice Gen: {children_novice.base.size()} (было: {children_novice.base.size() - total_learned//2})")

    hr("Статистика узлов")
    for node in [novice_node, senior_node, astro_node]:
        s = node.stats
        print(f"  {CY}{s['node_id']:<24}{W} gen={s['gen_count']:>5}  "
              f"taught={s['taught']}  learned={s['learned']}")


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Active Corpus Server Demo")
    parser.add_argument("--phase",   type=int, default=0,
                        choices=[0, 1, 2, 3],
                        help="1=навигация, 2=автономный, 3=гетерархия (0=все)")
    parser.add_argument("--cycles",  type=int, default=10,
                        help="Итераций в автономном цикле (phase 2)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    phases = [1, 2, 3] if args.phase == 0 else [args.phase]

    for p in phases:
        if p == 1:
            phase_1_navigation()
        elif p == 2:
            phase_2_autonomous(cycles=args.cycles, verbose=args.verbose)
        elif p == 3:
            phase_3_heterarchy()
        print()


if __name__ == "__main__":
    main()
