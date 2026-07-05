"""
Демо: модель генерирует запросы к LLM-учителю через ContextBroker.

Поток:
  1. Обучаем на serial_corpus (10 проходов, 15 текстов)
  2. Гоним незнакомый текст — SpeechDriver детектирует разрывы
  3. Показываем сгенерированные ContextQuery
  4. Если передан API ключ — отправляем реальный LLM-запрос и
     загружаем ответ обратно в буфер драйвера

Запуск:
    py -X utf8 training/context_query_demo.py
    py -X utf8 training/context_query_demo.py --api-key sk-ant-...
"""
from __future__ import annotations

import sys
import os
import argparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.algorithm import StepOutcome
from core.llm_broker import LLMPromptBuilder, AnthropicClient, MockLLMClient
from drivers.text_driver import TextDriver
from drivers.speech_driver import SpeechDriver, ContextQuery
from drivers.context_broker import ContextBroker, SourceTextRegistry
from training.serial_corpus import ALL_SERIAL_TEXTS

# ──────────────────────────────────────────────────────────────────────────────
# Цвета
# ──────────────────────────────────────────────────────────────────────────────
W   = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR  = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD  = "\033[91m"; MG = "\033[95m"

def hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*68}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*68}{W}\n")

def tag_color(tag: str) -> str:
    return {
        "CONFIRMED": GR, "COMPLETED": CY,
        "REFUTED": RD,   "EXPLORING": DM,
    }.get(tag, W)


# ──────────────────────────────────────────────────────────────────────────────
# Обучение
# ──────────────────────────────────────────────────────────────────────────────

def train(app: CoreApplication, texts: list, n_passes: int = 10) -> None:
    d = TextDriver("train")
    for p in range(1, n_passes + 1):
        n_new = 0
        for t in texts:
            for tok in d.produce(t):
                r = app.system.process_token(tok)
                if r.new_gen_id:
                    n_new += 1
            app.system.reset_context()
        if p in (1, 3, 5, 10):
            bs = len(app.system.base.all())
            print(f"  Pass {p:2d}: base={bs}  n_new={n_new}")


# ──────────────────────────────────────────────────────────────────────────────
# Прогон текста с речевым нарративом и детекцией запросов
# ──────────────────────────────────────────────────────────────────────────────

def run_with_context_detection(
    app: CoreApplication,
    text: str,
    speech: SpeechDriver,
    broker: ContextBroker,
    driver: TextDriver,
    gap_threshold: float = 0.30,
    min_streak: int = 2,
) -> list[ContextQuery]:
    """Прогнать текст и собрать запросы на контекст."""
    speech.reset_session()
    queries: list[ContextQuery] = []
    tokens = list(driver.produce(text))

    for tok in tokens:
        result = app.system.process_token(tok)
        active = app.system.engine.context.active_gen_ids()

        # Ведущий Gen
        lead_gen, lead_sig = None, 0.0
        for gid in active:
            g = app.system.base.get(gid)
            if g and g.significance > lead_sig:
                lead_gen, lead_sig = g, g.significance

        # Канал B: наблюдение
        obs = speech.observe(result, app.system.base, active)
        if obs:
            c = tag_color(obs.outcome_tag)
            print(f"  {c}[{obs.outcome_tag[:4]}]{W} {obs.text}")

        # Детекция разрыва контекста
        query = speech.detect_context_gap(
            result, lead_gen, lead_sig,
            gap_threshold=gap_threshold,
            min_streak=min_streak,
        )
        if query:
            queries.append(query)
            print(f"  {BD}{AM}[GAP ]{W} {query.query_text}")

    app.system.reset_context()
    return queries


# ──────────────────────────────────────────────────────────────────────────────
# Отправка запроса к LLM
# ──────────────────────────────────────────────────────────────────────────────

def ask_llm(
    app: CoreApplication,
    queries: list[ContextQuery],
    api_key: str,
    registry: SourceTextRegistry,
) -> list[str]:
    """Отправить запросы LLM-учителю, вернуть список полученных текстов."""
    client = AnthropicClient(
        api_key=api_key,
        model="claude-haiku-4-5-20251001",
        max_tokens=512,
    )

    # Кладём запросы в TeachingLog
    for q in queries:
        app.system.teaching_log.push_query(q)

    log_entries = app.system.teaching_log.get_recent(20)
    prompt = LLMPromptBuilder.build(
        app.system,
        log_entries,
        queries=queries,
    )

    print(f"\n{BD}Промпт к LLM ({len(prompt)} символов){W}")
    print(f"{DM}{'─'*60}{W}")
    # Показываем только секцию запросов + задача
    lines = prompt.split("\n")
    show = False
    for ln in lines:
        if "ЗАПРОСЫ" in ln or "ТВОЯ ЗАДАЧА" in ln:
            show = True
        if show:
            print(f"  {ln}")
    print(f"{DM}{'─'*60}{W}")

    print(f"\n{BD}Отправляем запрос к LLM...{W}")
    raw = client.complete(prompt)
    print(f"{DM}Ответ LLM:{W}\n  {raw}")

    # Парсим ответ
    from core.llm_broker import LLMResponseParser
    decision = LLMResponseParser.parse(raw)

    received = []
    if decision and decision.action == "TEACH" and decision.text:
        print(f"\n{GR}LLM → TEACH:{W} «{decision.text}»")
        print(f"{DM}Причина: {decision.reason}{W}")
        received.append(decision.text)
        # Регистрируем полученный текст в реестре
        registry.register(decision.text, source_id="llm_reply", origin="llm")
    elif decision:
        print(f"\n{AM}LLM → {decision.action}:{W} {decision.reason}")

    app.system.teaching_log.clear_queries()
    return received


# ──────────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default="", help="Anthropic API key")
    parser.add_argument("--passes", type=int, default=10)
    parser.add_argument("--n-train", type=int, default=15)
    parser.add_argument("--gap", type=float, default=0.30)
    parser.add_argument("--streak", type=int, default=2)
    args = parser.parse_args()

    # ── 1. Инициализация ──────────────────────────────────────────────────────
    hdr("Фаза 1: Обучение")
    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
    app.startup()

    registry = SourceTextRegistry()
    broker = ContextBroker(
        teaching_log=app.system.teaching_log,
        registry=registry,
    )

    train_texts = ALL_SERIAL_TEXTS[:args.n_train]

    # Регистрируем все тексты обучения в реестре
    for i, t in enumerate(train_texts):
        broker.register_source(t, source_id=f"train_{i}", origin="serial")

    train(app, train_texts, n_passes=args.passes)
    bs = len(app.system.base.all())
    print(f"\n  {BD}База после обучения: {bs} Gen{W}")

    # ── 2. Тесты на знакомых текстах ──────────────────────────────────────────
    hdr("Фаза 2: Знакомые тексты (ожидаем мало GAP)")
    speech = SpeechDriver(verbosity=1, lang="ru")
    driver = TextDriver("test")

    known_tests = [
        "маша пошла в лес и встретила медведя",
        "волк пришёл к зайцу и сказал привет",
    ]
    for text in known_tests:
        print(f"  {BD}«{text}»{W}")
        qs = run_with_context_detection(
            app, text, speech, broker, driver,
            gap_threshold=args.gap, min_streak=args.streak,
        )
        if qs:
            print(f"  {AM}→ {len(qs)} GAP(s){W}")
        else:
            print(f"  {GR}→ нет разрывов{W}")
        print()

    # ── 3. Тесты на незнакомых текстах ────────────────────────────────────────
    hdr("Фаза 3: Незнакомые тексты — детекция разрывов")

    unknown_tests = [
        "мальчик нашёл ключ открыл дверь вошёл внутрь",
        "девочка увидела незнакомца испугалась позвала маму",
        "кот залез на крышу соседи удивились позвонили пожарным",
    ]

    all_queries: list[ContextQuery] = []
    for text in unknown_tests:
        print(f"  {BD}«{text}»{W}")
        qs = run_with_context_detection(
            app, text, speech, broker, driver,
            gap_threshold=args.gap, min_streak=args.streak,
        )
        all_queries.extend(qs)
        n_gap = len(qs)
        color = RD if n_gap > 0 else GR
        print(f"  {color}→ {n_gap} GAP(s){W}")
        print()

    # ── 4. Сводка запросов ────────────────────────────────────────────────────
    hdr(f"Сводка запросов: {len(all_queries)} ContextQuery")

    unique_queries: list[ContextQuery] = []
    seen_texts: set[str] = set()
    for q in all_queries:
        if q.query_text not in seen_texts:
            unique_queries.append(q)
            seen_texts.add(q.query_text)

    for i, q in enumerate(unique_queries, 1):
        print(f"  {AM}{i}. [{q.trigger_outcome}]{W} trigger=«{q.trigger_token}»  "
              f"gap={q.confidence_gap:.2f}")
        print(f"     Запрос: {q.query_text}")
        print()

    if not unique_queries:
        print(f"  {GR}Модель справилась без запросов — возможно нужен более строгий текст.{W}")
        print(f"  Попробуй: --gap 0.5 --streak 1")
        return

    # ── 5. Попытка локального разрешения ──────────────────────────────────────
    hdr("Фаза 4: Локальный поиск в реестре")
    resolved_locally = 0
    for q in unique_queries:
        found = registry.lookup(q, top_n=2)
        if found:
            resolved_locally += 1
            print(f"  {GR}[LOCAL] «{q.trigger_token}»{W}")
            for t in found:
                print(f"    → «{t[:70]}»")
        else:
            print(f"  {RD}[MISS ] «{q.trigger_token}»{W} — в реестре нет, нужен LLM")
    print(f"\n  Локально решено: {resolved_locally}/{len(unique_queries)}")

    # ── 6. LLM-запрос ─────────────────────────────────────────────────────────
    need_llm = [q for q in unique_queries
                if not registry.lookup(q, top_n=1)]

    if not need_llm:
        hdr("Все запросы решены локально — LLM не нужен")
        return

    hdr(f"Фаза 5: Отправляем {len(need_llm)} запрос(а) к LLM")

    if not args.api_key:
        print(f"  {AM}API ключ не передан — показываем промпт и пропускаем реальный вызов{W}")
        print(f"  Запусти: py -X utf8 training/context_query_demo.py --api-key sk-ant-...\n")

        # Показываем промпт
        for q in need_llm:
            app.system.teaching_log.push_query(q)
        prompt = LLMPromptBuilder.build(
            app.system,
            app.system.teaching_log.get_recent(20),
            queries=need_llm,
        )
        lines = prompt.split("\n")
        show = False
        for ln in lines:
            if "ЗАПРОСЫ" in ln or "ТВОЯ ЗАДАЧА" in ln:
                show = True
            if show:
                print(f"  {ln}")
        app.system.teaching_log.clear_queries()
        return

    # Реальный LLM-вызов
    received = ask_llm(app, need_llm, args.api_key, registry)

    if received:
        hdr("Фаза 6: Обучаем на полученном тексте")
        driver2 = TextDriver("from_llm")
        for text in received:
            print(f"  Учим на: «{text}»")
            for tok in driver2.produce(text):
                app.system.process_token(tok)
            app.system.reset_context()

        new_bs = len(app.system.base.all())
        print(f"\n  {GR}База: {bs} → {new_bs} Gen (+{new_bs - bs}){W}")

        # Повторяем тест с теми же незнакомыми текстами
        hdr("Фаза 7: Повторный тест после LLM-ответа")
        for text in unknown_tests[:2]:
            print(f"  {BD}«{text}»{W}")
            qs2 = run_with_context_detection(
                app, text, speech, broker, driver,
                gap_threshold=args.gap, min_streak=args.streak,
            )
            print(f"  → GAP после обучения: {len(qs2)}")
            print()


if __name__ == "__main__":
    main()
