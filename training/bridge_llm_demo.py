"""
training/bridge_llm_demo.py — Демо: что именно отправляется в LLM.

Показывает:
  1. Обучение системы
  2. Принудительный IDLE → Bridge → LEAST_CONFIRMED
  3. Точный ContextQuery, который ушёл в TeachingLog
  4. Полный промпт, который строится для LLM
  5. Mock-ответ LLM и его парсинг
  6. resume_after_llm — возобновление цикла

Запуск:
    py -X utf8 training/bridge_llm_demo.py
"""
from __future__ import annotations

import sys
import os
import json

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.attention_loop import AttentionLoop
from core.proposal_loop import ProposalCommandLoop, LoopStatus
from core.active_query_bridge import ActiveQueryBridge
from core.llm_broker import LLMPromptBuilder, LLMResponseParser, LLMDecision
from drivers.text_driver import TextDriver
from drivers.speech_driver import SpeechDriver
from drivers.context_broker import ContextBroker, SourceTextRegistry

# ── ANSI ──────────────────────────────────────────────────────────────
W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; BL = "\033[94m"

def hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*68}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*68}{W}\n")

def sub(t: str) -> None:
    print(f"  {AM}── {t} ──{W}")


# ──────────────────────────────────────────────────────────────────────
# Mock LLM
# ──────────────────────────────────────────────────────────────────────

class MockLLM:
    """Имитирует ответ LLM: возвращает релевантный текст."""

    def complete(self, prompt: str) -> str:
        # Имитируем ответ: текст про лес (домен, который система не знает)
        response = {
            "action": "TEACH",
            "text": "мальчик пошёл в лес и нашёл там грибы и ягоды",
            "amount": 0.0,
            "reason": "Система запросила данные о домене «лес». "
                      "Предоставляю текст с похожими паттернами."
        }
        return json.dumps(response, ensure_ascii=False)


def main():
    # ── 1. Инициализация ─────────────────────────────────────────────
    hdr("Фаза 1: Инициализация")
    app = CoreApplication(config={
        "mock_teacher": False,
        "feature_tolerance": 0.15,
    })
    app.startup()

    registry = SourceTextRegistry()
    broker = ContextBroker(
        teaching_log=app.system.teaching_log,
        registry=registry,
    )

    train_texts = [
        "маша пошла в лес",
        "волк встретил зайца",
        "кот сидит на окне",
        "маша нашла грибы",
        "заяц побежал в поле",
    ]
    for i, t in enumerate(train_texts):
        registry.register(t, source_id=f"train_{i}", origin="serial")

    print(f"  Реестр: {registry.size()} текстов")

    # ── 2. Обучение ──────────────────────────────────────────────────
    hdr("Фаза 2: Обучение (3 прохода)")
    d = TextDriver("train")
    for p in range(1, 4):
        n_new = 0
        for t in train_texts:
            for tok in d.produce(t):
                r = app.system.process_token(tok)
                if r.new_gen_id:
                    n_new += 1
            app.system.reset_context()
        bs = len(app.system.base.all())
        print(f"  Pass {p}: base={bs}  n_new={n_new}")

    base_size = len(app.system.base.all())

    # ── 3. Сборка цикла ─────────────────────────────────────────────
    hdr("Фаза 3: Сборка замкнутого цикла")
    loop = AttentionLoop(app.system, app.peripherals)
    speech = SpeechDriver(verbosity=0, lang="ru")
    pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
    bridge = ActiveQueryBridge(app.system, broker)
    print(f"  {pcl}")
    print(f"  {bridge}")

    # ── 4. Прогон с принудительным IDLE ──────────────────────────────
    hdr("Фаза 4: Прогон с FORCE IDLE=15")
    text = "маша пошла в лес и встретила медведя"
    print(f"  {BD}«{text}»{W}\n")

    pcl.load_buffer(text)
    result = pcl.run_cycle(max_steps=15, verbose=False)
    print(f"  Шагов: {result.total_steps}  MR: {result.match_rate:.3f}")

    # Принудительный IDLE
    sub("FORCE IDLE → Bridge")
    for did in loop._peripherals.driver_ids():
        d = loop._peripherals.get(did)
        if d:
            d.clear_buffer()

    bridge_result = bridge.on_idle()

    # ── 5. Показать ContextQuery ─────────────────────────────────────
    hdr("Фаза 5: ContextQuery (что отправлено в TeachingLog)")

    if bridge_result.query:
        q = bridge_result.query
        print(f"  {BD}Стратегия:{W} {bridge_result.strategy}")
        print(f"  {BD}trigger_token:{W} «{q.trigger_token}»")
        print(f"  {BD}trigger_outcome:{W} {q.trigger_outcome}")
        print(f"  {BD}missing_hint:{W} «{q.missing_hint}»")
        print(f"  {BD}confidence_gap:{W} {q.confidence_gap:.2f}")
        print()
        print(f"  {BD}query_text:{W}")
        print(f"    {q.query_text}")
    else:
        print(f"  {RD}Bridge не сформировал запрос{W}")
        return

    # ── 6. Показать TeachingLog ──────────────────────────────────────
    hdr("Фаза 6: TeachingLog — накопленные запросы")
    queries = app.system.teaching_log.peek_queries()
    print(f"  Запросов в очереди: {len(queries)}")
    for i, q in enumerate(queries, 1):
        tt = getattr(q, "trigger_token", "?")
        qt = getattr(q, "query_text", str(q))
        print(f"  {i}. [{getattr(q, 'trigger_outcome', '?')}] «{tt}»")
        print(f"     {qt[:100]}...")

    # ── 7. Построить промпт для LLM ─────────────────────────────────
    hdr("Фаза 7: Полный промпт для LLM")
    log_entries = app.system.teaching_log.get_recent(20)
    prompt = LLMPromptBuilder.build(
        app.system,
        log_entries,
        queries=queries,
    )

    print(f"  {BD}Длина промпта:{W} {len(prompt)} символов\n")
    print(f"{DM}{'─'*68}{W}")
    print(prompt)
    print(f"{DM}{'─'*68}{W}")

    # ── 8. Mock-ответ LLM ───────────────────────────────────────────
    hdr("Фаза 8: Ответ Mock LLM")
    mock = MockLLM()
    raw_response = mock.complete(prompt)

    print(f"  {BD}Raw JSON:{W}")
    print(f"  {raw_response}\n")

    decision = LLMResponseParser.parse(raw_response)
    if decision:
        print(f"  {BD}Parsed decision:{W}")
        print(f"    action: {decision.action}")
        print(f"    text:   «{decision.text}»")
        print(f"    reason: {decision.reason}")
    else:
        print(f"  {RD}Не удалось распарсить ответ{W}")
        return

    # ── 9. Resume после LLM ─────────────────────────────────────────
    if decision.action == "TEACH" and decision.text:
        hdr("Фаза 9: resume_after_llm")
        print(f"  {BD}Полученный текст:{W} «{decision.text}»")
        print()

        # Регистрируем в реестре
        registry.register(decision.text, source_id="llm_reply", origin="llm")
        app.system.teaching_log.clear_queries()

        # Возобновляем цикл
        app.system.reset_context()
        r2 = pcl.resume_after_llm([decision.text], max_steps=50, verbose=True)

        print(f"\n  {BD}Итог resume:{W}")
        print(f"    Шагов: {r2.total_steps}")
        print(f"    MR: {r2.match_rate:.3f}")
        print(f"    GAP: {r2.queries_generated}")
        print(f"    LOCAL: {r2.queries_resolved_local}")
        print(f"    Status: {r2.status}")

        # Сравнение
        print(f"\n  {BD}Сравнение:{W}")
        print(f"    До LLM:  MR={result.match_rate:.3f}  "
              f"steps={result.total_steps}")
        print(f"    После:   MR={r2.match_rate:.3f}  "
              f"steps={r2.total_steps}")

        # Новые Gen
        new_base = len(app.system.base.all())
        print(f"\n  {BD}База Gen:{W} {new_base}")

        # ── 10. Повторный прогон того же текста ──────────────────────
        hdr("Фаза 10: Повторный прогон (показывает рост MR)")
        print(f"  {BD}Текст:{W} «{decision.text}»")
        print(f"  {DM}(тот же текст, который прислал LLM){W}\n")

        app.system.reset_context()
        r3 = pcl.run_cycle(max_steps=50, verbose=False)

        print(f"  {BD}Итог повторного прогона:{W}")
        print(f"    Шагов: {r3.total_steps}")
        print(f"    MR: {r3.match_rate:.3f}")
        print(f"    GAP: {r3.queries_generated}")
        print(f"    LOCAL: {r3.queries_resolved_local}")
        print(f"    Status: {r3.status}")

        base_after = len(app.system.base.all())
        print(f"    База Gen: {base_after}")

        # ── 11. Полная таблица ───────────────────────────────────────
        hdr("Фаза 11: Динамика MR по итерациям")
        print(f"  {'Итерация':<30} {'Текст':<35} {'MR':>6} {'GAP':>5} {'Gen':>5}")
        print(f"  {'─'*85}")
        print(f"  {'1. До LLM (исходный текст)':<30} "
              f"{'маша пошла...':<35} "
              f"{result.match_rate:>6.3f} {result.queries_generated:>5} {base_size:>5}")
        print(f"  {'2. После LLM (новый текст)':<30} "
              f"{'мальчик пошёл...':<35} "
              f"{r2.match_rate:>6.3f} {r2.queries_generated:>5} {new_base:>5}")
        print(f"  {'3. Повтор (тот же текст)':<30} "
              f"{'мальчик пошёл...':<35} "
              f"{r3.match_rate:>6.3f} {r3.queries_generated:>5} {base_after:>5}")

        # График
        print(f"\n  {BD}Динамика MR:{W}")
        for label, mr in [("1. До LLM", result.match_rate),
                          ("2. После LLM (новый)", r2.match_rate),
                          ("3. Повтор (тот же)", r3.match_rate)]:
            bar = "█" * int(mr * 40)
            color = GR if mr > 0.5 else (AM if mr > 0.3 else RD)
            print(f"    {label:<28} {color}{bar} {mr:.3f}{W}")

    # ── 12. Итог ────────────────────────────────────────────────────
    hdr("Итог")
    print(f"  {BD}Полный цикл:{W}")
    print(f"    1. System processing → REFUTED → Gen «лес» (success=0)")
    print(f"    2. FORCE IDLE → Bridge → LEAST_CONFIRMED")
    print(f"    3. ContextQuery → TeachingLog")
    print(f"    4. LLMPromptBuilder → промпт ({len(prompt)} символов)")
    print(f"    5. Mock LLM → TEACH: «мальчик пошёл в лес...»")
    print(f"    6. resume_after_llm → система обучена новому тексту")
    print(f"    7. Повторный прогон → MR растёт (система узнала паттерн)")
    print(f"\n{DM}{'─'*68}{W}")
    print(f"{DM}Цикл замкнут: IDLE → Bridge → LLM → resume → обучение → рост MR{W}\n")


if __name__ == "__main__":
    main()
