"""
Демо: любопытство модели на сериальном корпусе «Лесная семья».

Сценарий:
  1. Обучение на 5 типах ситуаций (встреча, угощение, игра, помощь, праздник) — 15 проходов
  2. ProposalCommandLoop прогоняет 5 новых типов (опасность, поиск, спор, потеря, возвращение)
  3. Все ContextQuery группируются по ситуации и ключевым словам
  4. Показывается «карта любопытства»: что именно модель хочет узнать
  5. При наличии API-ключа — отправляем все запросы в LLM, обучаемся на ответах,
     повторяем прогон и смотрим как GAP уменьшается

Запуск:
    py -X utf8 training/serial_curiosity_demo.py
    py -X utf8 training/serial_curiosity_demo.py --passes 20 --gap 0.4
    py -X utf8 training/serial_curiosity_demo.py --api-key sk-ant-...
"""

from __future__ import annotations

import sys, os, argparse, time
from collections import defaultdict
from typing import Dict, List, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.attention_loop import AttentionLoop
from core.proposal_loop import ProposalCommandLoop, LoopStatus, CycleResult
from core.algorithm import StepOutcome
from drivers.text_driver import TextDriver
from drivers.speech_driver import SpeechDriver
from drivers.context_broker import ContextBroker, SourceTextRegistry
from training.serial_corpus import ALL_SERIAL_TEXTS, SITUATION_FAMILIES

# ── ANSI ──────────────────────────────────────────────────────────────
W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; BL = "\033[94m"

def hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*70}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*70}{W}\n")

def sub(t: str) -> None:
    print(f"\n{BD}{BL}  ── {t} ──{W}\n")


# ══════════════════════════════════════════════════════════════════════
# Конфигурация разбивки корпуса
# ══════════════════════════════════════════════════════════════════════

TRAIN_SITUATIONS = ["встреча", "угощение", "игра", "помощь", "праздник"]
TEST_SITUATIONS  = ["опасность", "поиск", "спор", "потеря", "возвращение"]

# Тексты «за горизонтом» — не из сериала, но похожи по стилю
OUT_OF_DOMAIN = [
    "мальчик потерялся в лесу долго искал дорогу нашёл тропинку вышел домой",
    "девочка нашла котёнка принесла домой накормила котёнок заурчал остался жить",
    "охотник шёл по лесу увидел следы остановился прислушался ушёл тихо",
    "рыбак поймал рыбу рыба сказала отпусти меня рыбак удивился отпустил",
    "старик посадил репку репка выросла большая потянул не вытащил позвал бабку",
]


# ══════════════════════════════════════════════════════════════════════
# Шаг 1: Обучение
# ══════════════════════════════════════════════════════════════════════

def build_train_corpus() -> List[str]:
    corpus = []
    for sit in TRAIN_SITUATIONS:
        corpus.extend(SITUATION_FAMILIES[sit])
    return corpus


def train(app, texts: List[str], registry: SourceTextRegistry,
          n_passes: int = 15) -> int:
    """Обучить систему, зарегистрировать тексты в реестре."""
    d = TextDriver("train")
    for i, t in enumerate(texts):
        registry.register(t, source_id=f"train_{i}", origin="serial")

    t0 = time.perf_counter()
    for p in range(1, n_passes + 1):
        n_new = 0
        for t in texts:
            for tok in d.produce(t):
                r = app.system.process_token(tok)
                if r.new_gen_id:
                    n_new += 1
            app.system.reset_context()
        if p in (1, 5, 10, n_passes):
            bs = len(app.system.base.all())
            print(f"  Pass {p:2d}: base={bs:4d}  n_new={n_new}")

    elapsed = time.perf_counter() - t0
    bs = len(app.system.base.all())
    print(f"\n  {BD}База: {bs} Gen  |  Время: {elapsed:.1f}s{W}")
    return bs


# ══════════════════════════════════════════════════════════════════════
# Шаг 2: Прогон одного текста через ProposalCommandLoop
# ══════════════════════════════════════════════════════════════════════

def run_text(pcl: ProposalCommandLoop, text: str,
             situation: str, verbose: bool = False) -> CycleResult:
    """Прогнать один текст, вернуть CycleResult."""
    pcl.inner_loop._system.reset_context()
    pcl.load_buffer(text)
    r = pcl.run_cycle(max_steps=80, verbose=verbose, clear_pending=True)
    return r


# ══════════════════════════════════════════════════════════════════════
# Шаг 3: Карта любопытства
# ══════════════════════════════════════════════════════════════════════

def print_curiosity_map(
    results: Dict[str, List[Tuple[str, CycleResult]]]
) -> List:
    """
    Вывести карту: ситуация → список запросов.
    Вернуть все уникальные pending_queries.
    """
    all_queries = []
    seen_texts = set()

    for situation, text_results in results.items():
        sit_queries = []
        for text, r in text_results:
            # all_queries содержит ВСЕ ContextQuery (local + remote)
            source = r.all_queries if r.all_queries else r.pending_queries
            for q in source:
                if q.query_text not in seen_texts:
                    seen_texts.add(q.query_text)
                    sit_queries.append((text, q))
                    all_queries.append(q)

        n_total = len(text_results)
        n_gap   = sum(1 for _, r in text_results if r.queries_generated > 0)
        mr_avg  = sum(r.match_rate for _, r in text_results) / n_total

        color = RD if n_gap > n_total // 2 else AM if n_gap > 0 else GR
        print(f"  {color}[{situation:>12}]{W}  "
              f"MR={mr_avg:.3f}  GAP={n_gap}/{n_total}  "
              f"queries={len(sit_queries)}")

        for text, q in sit_queries[:3]:          # показываем до 3 запросов
            snippet = text[:45]
            print(f"    {DM}«{snippet}»{W}")
            print(f"    {AM}→ [{q.trigger_outcome}] «{q.trigger_token}»  "
                  f"gap={q.confidence_gap:.2f}{W}")
            print(f"      {q.query_text}")
        if len(sit_queries) > 3:
            print(f"    {DM}  ... и ещё {len(sit_queries)-3} запрос(ов){W}")
        print()

    return all_queries


# ══════════════════════════════════════════════════════════════════════
# Шаг 4: LLM-ответы и обучение на них
# ══════════════════════════════════════════════════════════════════════

def ask_llm_batch(app, queries: list, api_key: str,
                  registry: SourceTextRegistry) -> List[str]:
    """Отправить все уникальные запросы в LLM, вернуть полученные тексты."""
    from core.llm_broker import LLMPromptBuilder, AnthropicClient, LLMResponseParser

    client = AnthropicClient(
        api_key=api_key,
        model="claude-haiku-4-5-20251001",
        max_tokens=400,
    )

    received = []
    # Отправляем по одному запросу (наиболее информативная стратегия)
    for q in queries[:5]:   # лимит — первые 5
        app.system.teaching_log.push_query(q)
        prompt = LLMPromptBuilder.build(
            app.system,
            app.system.teaching_log.get_recent(10),
            queries=[q],
        )
        raw = client.complete(prompt)
        decision = LLMResponseParser.parse(raw)

        if decision and decision.action == "TEACH" and decision.text:
            print(f"  {GR}✓ TEACH:{W} «{decision.text}»")
            received.append(decision.text)
            registry.register(decision.text, source_id="llm", origin="llm")
        else:
            action = decision.action if decision else "?"
            print(f"  {AM}  {action}{W}")

        app.system.teaching_log.clear_queries()

    return received


def learn_from_texts(app, texts: List[str]) -> int:
    """Дообучиться на полученных текстах, вернуть прирост базы."""
    bs_before = len(app.system.base.all())
    d = TextDriver("llm_learn")
    for t in texts:
        for tok in d.produce(t):
            app.system.process_token(tok)
        app.system.reset_context()
    return len(app.system.base.all()) - bs_before


# ══════════════════════════════════════════════════════════════════════
# Главная функция
# ══════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key",  default="",  help="Anthropic API key")
    parser.add_argument("--passes",   type=int, default=15)
    parser.add_argument("--gap",      type=float, default=0.35)
    parser.add_argument("--streak",   type=int, default=2)
    parser.add_argument("--verbose",  action="store_true", help="Вывод канала B")
    parser.add_argument("--ood",      action="store_true",
                        help="Включить out-of-domain тексты")
    args = parser.parse_args()

    # ── 1. Инициализация ─────────────────────────────────────────────
    hdr("Шаг 1: Обучение на 5 типах ситуаций")

    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
    app.startup()

    registry = SourceTextRegistry()
    broker   = ContextBroker(teaching_log=app.system.teaching_log,
                              registry=registry)
    train_texts = build_train_corpus()
    print(f"  Обучающих текстов: {len(train_texts)}  "
          f"({len(TRAIN_SITUATIONS)} ситуаций × 5 вариантов)\n")
    print(f"  Ситуации: {', '.join(TRAIN_SITUATIONS)}\n")

    base_size = train(app, train_texts, registry, n_passes=args.passes)

    # ── 2. Сборка ProposalCommandLoop ────────────────────────────────
    hdr("Шаг 2: Сборка замкнутого цикла")

    loop   = AttentionLoop(app.system, app.peripherals)
    speech = SpeechDriver(verbosity=1, lang="ru")
    # pcl_full — с брокером: восстанавливает контекст из реестра (контроль)
    # pcl_curious — без брокера: все GAP → pending_queries (карта любопытства)
    pcl_full = ProposalCommandLoop(
        loop, speech=speech, broker=broker,
        default_driver_id="text",
        gap_threshold=args.gap,
        min_streak=args.streak,
    )
    pcl_curious = ProposalCommandLoop(
        loop, speech=speech, broker=None,
        default_driver_id="text",
        gap_threshold=args.gap,
        min_streak=args.streak,
    )
    print(f"  gap_threshold={args.gap}  min_streak={args.streak}")
    print(f"  full : {pcl_full}")
    print(f"  naive: {pcl_curious}")

    # ── 3. Контрольный прогон: знакомые ситуации ─────────────────────
    hdr("Шаг 3: Контроль — знакомые ситуации (ожидаем низкий GAP)")
    control_results: Dict[str, List] = defaultdict(list)
    for sit in TRAIN_SITUATIONS[:3]:   # 3 ситуации для контроля
        sub(sit)
        for text in SITUATION_FAMILIES[sit][:2]:
            r = run_text(pcl_full, text, sit, verbose=args.verbose)
            control_results[sit].append((text, r))
            gap_color = GR if r.queries_generated == 0 else AM
            print(f"  {DM}«{text[:55]}»{W}")
            print(f"  MR={r.match_rate:.3f}  "
                  f"{gap_color}GAP={r.queries_generated}{W}  "
                  f"Status={r.status}")

    print(f"\n  {BD}Контроль: среднее GAP = "
          f"{sum(r.queries_generated for _, r in sum(control_results.values(), []))}"
          f" / {sum(len(v) for v in control_results.values())} текстов{W}")

    # ── 4. Тест: незнакомые ситуации → Карта любопытства ─────────────
    hdr("Шаг 4: Новые ситуации — карта любопытства модели")
    print(f"  Ситуации: {', '.join(TEST_SITUATIONS)}\n")

    # pcl_curious (без брокера) — все GAP идут в pending_queries / all_queries
    test_results: Dict[str, List] = defaultdict(list)
    for sit in TEST_SITUATIONS:
        for text in SITUATION_FAMILIES[sit]:
            r = run_text(pcl_curious, text, sit, verbose=False)
            test_results[sit].append((text, r))

    # Out-of-domain
    if args.ood:
        sub("out-of-domain")
        ood_results = []
        for text in OUT_OF_DOMAIN:
            r = run_text(pcl_curious, text, "ood", verbose=False)
            ood_results.append((text, r))
        test_results["out-of-domain"] = ood_results

    # ── 5. Карта любопытства ─────────────────────────────────────────
    hdr("Карта любопытства: что модель хочет узнать")
    all_queries = print_curiosity_map(test_results)

    # Сводка по всем тестовым ситуациям
    total_texts   = sum(len(v) for v in test_results.values())
    total_gap     = sum(r.queries_generated
                        for results in test_results.values()
                        for _, r in results)
    total_pending = len(all_queries)
    avg_mr        = (sum(r.match_rate
                         for results in test_results.values()
                         for _, r in results) / total_texts
                     if total_texts else 0.0)

    print(f"  {'Итого текстов':<30} {total_texts}")
    print(f"  {'Итого GAP-событий':<30} {total_gap}")
    print(f"  {'Уникальных ContextQuery':<30} {total_pending}")
    print(f"  {'Средний MR':<30} {avg_mr:.3f}")

    # ── 6. Топ-запросы по gap ────────────────────────────────────────
    if all_queries:
        hdr("Топ ContextQuery (по confidence_gap)")
        sorted_q = sorted(all_queries, key=lambda q: q.confidence_gap, reverse=True)
        for i, q in enumerate(sorted_q[:8], 1):
            print(f"  {AM}{i:2d}.{W} gap={q.confidence_gap:.2f}  "
                  f"[{q.trigger_outcome}] «{q.trigger_token}»")
            print(f"      {q.query_text}")
            print()

    # ── 7. LLM-запрос ─────────────────────────────────────────────────
    if not all_queries:
        print(f"\n  {GR}Все ситуации распознаны без запросов — "
              f"попробуй --gap 0.5 --streak 1{W}")
        return

    if not args.api_key:
        print(f"\n  {AM}API ключ не передан — пропускаем LLM-фазу.{W}")
        print(f"  Запусти: py -X utf8 training/serial_curiosity_demo.py --api-key sk-ant-...\n")
        return

    hdr(f"Шаг 5: Отправляем {min(len(all_queries), 5)} запрос(а) в LLM")
    received = ask_llm_batch(app, all_queries, args.api_key, registry)

    if not received:
        print(f"  {AM}LLM не вернул TEACH-ответ{W}")
        return

    # ── 8. Дообучение на ответах LLM ────────────────────────────────
    hdr("Шаг 6: Дообучение на ответах LLM")
    delta = learn_from_texts(app, received)
    new_size = len(app.system.base.all())
    print(f"  База: {base_size} → {new_size} Gen (+{delta})")

    # ── 9. Повторный прогон тестовых ситуаций ────────────────────────
    hdr("Шаг 7: Повторный прогон после обучения")
    print("  Сравнение MR и GAP до/после:\n")
    print(f"  {'Ситуация':<15} {'MR до':>7} {'MR после':>9} {'GAP до':>7} {'GAP после':>9}")
    print(f"  {'─'*15} {'─'*7} {'─'*9} {'─'*7} {'─'*9}")

    for sit in TEST_SITUATIONS[:4]:
        texts = [t for t, _ in test_results[sit]]
        mr_before = sum(r.match_rate for _, r in test_results[sit]) / len(texts)
        gap_before = sum(r.queries_generated for _, r in test_results[sit])

        new_results = []
        for text in texts:
            r = run_text(pcl_curious, text, sit, verbose=False)
            new_results.append((text, r))

        mr_after  = sum(r.match_rate for _, r in new_results) / len(texts)
        gap_after = sum(r.queries_generated for _, r in new_results)

        delta_mr  = mr_after - mr_before
        color = GR if delta_mr >= 0 else RD
        print(f"  {sit:<15} {mr_before:>7.3f} {color}{mr_after:>9.3f}{W} "
              f"{gap_before:>7d} {gap_after:>9d}")

    print()


if __name__ == "__main__":
    main()
