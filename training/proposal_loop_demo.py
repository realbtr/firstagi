"""
Демо: ProposalCommandLoop — замкнутый цикл активного внимания (Шаг 13).

Показывает полный автономный цикл:
  1. Обучение на корпусе (5 проходов, 10 текстов)
  2. Загрузка незнакомых текстов в буфер
  3. run_cycle() — система читает буфер сама, наблюдает через SpeechDriver,
     детектирует разрывы, обращается к ContextBroker
  4. Если AWAITING_LLM — отправляем запросы в LLM (опционально)
  5. resume_after_llm() — возобновляем цикл, сравниваем match_rate до/после

Запуск:
    py -X utf8 training/proposal_loop_demo.py
    py -X utf8 training/proposal_loop_demo.py --api-key sk-ant-...
"""

from __future__ import annotations

import sys
import os
import argparse

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.attention_loop import AttentionLoop
from core.proposal_loop import ProposalCommandLoop, LoopStatus
from drivers.text_driver import TextDriver
from drivers.speech_driver import SpeechDriver
from drivers.context_broker import ContextBroker, SourceTextRegistry
from core.llm_broker import LLMPromptBuilder, AnthropicClient
from core.llm_broker import LLMResponseParser
from training.serial_corpus import ALL_SERIAL_TEXTS

# ── ANSI ──────────────────────────────────────────────────────────────
W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"

def hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*68}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*68}{W}\n")


# ──────────────────────────────────────────────────────────────────────
# Обучение
# ──────────────────────────────────────────────────────────────────────

def train(app, texts, n_passes=5):
    d = TextDriver("train")
    for p in range(1, n_passes + 1):
        n_new = 0
        for t in texts:
            for tok in d.produce(t):
                r = app.system.process_token(tok)
                if r.new_gen_id:
                    n_new += 1
            app.system.reset_context()
        if p in (1, 3, 5):
            bs = len(app.system.base.all())
            print(f"  Pass {p:2d}: base={bs}  n_new={n_new}")


# ──────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-key", default="", help="Anthropic API key")
    parser.add_argument("--passes",  type=int, default=5)
    parser.add_argument("--n-train", type=int, default=10)
    parser.add_argument("--gap",     type=float, default=0.30)
    parser.add_argument("--streak",  type=int, default=2)
    args = parser.parse_args()

    # ── 1. Инициализация ─────────────────────────────────────────────
    hdr("Фаза 1: Обучение")
    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
    app.startup()

    registry = SourceTextRegistry()
    broker   = ContextBroker(
        teaching_log=app.system.teaching_log,
        registry=registry,
    )
    train_texts = ALL_SERIAL_TEXTS[:args.n_train]
    for i, t in enumerate(train_texts):
        broker.register_source(t, source_id=f"train_{i}", origin="serial")

    train(app, train_texts, n_passes=args.passes)
    base_size = len(app.system.base.all())
    print(f"\n  {BD}База после обучения: {base_size} Gen{W}")

    # ── 2. Сборка ProposalCommandLoop ────────────────────────────────
    hdr("Фаза 2: Сборка замкнутого цикла")
    loop   = AttentionLoop(app.system, app.peripherals)
    speech = SpeechDriver(verbosity=1, lang="ru")
    pcl    = ProposalCommandLoop(
        loop,
        speech=speech,
        broker=broker,
        default_driver_id="text",
        gap_threshold=args.gap,
        min_streak=args.streak,
    )
    print(f"  {pcl}")

    # ── 3. Прогон: знакомый текст ────────────────────────────────────
    hdr("Фаза 3: Знакомый текст (ожидаем мало GAP)")
    known_text = "маша пошла в лес и встретила медведя"
    print(f"  {BD}«{known_text}»{W}\n")
    pcl.load_buffer(known_text)
    r1 = pcl.run_cycle(max_steps=50, verbose=True)
    print(f"\n  Шагов: {r1.total_steps}  MR: {r1.match_rate:.3f}  "
          f"GAP: {r1.queries_generated}  "
          f"LOCAL: {r1.queries_resolved_local}  "
          f"LLM: {r1.queries_sent_to_llm}  "
          f"Status: {BD}{r1.status}{W}")

    # ── 4. Прогон: незнакомые тексты ─────────────────────────────────
    hdr("Фаза 4: Незнакомые тексты — автономный цикл с GAP-детекцией")
    unknown_texts = [
        "мальчик нашёл ключ открыл дверь вошёл внутрь",
        "девочка увидела незнакомца испугалась позвала маму",
        "кот залез на крышу соседи удивились позвонили пожарным",
    ]

    all_pending = []
    for text in unknown_texts:
        print(f"  {BD}«{text}»{W}")
        app.system.reset_context()
        pcl.load_buffer(text)
        r = pcl.run_cycle(max_steps=50, verbose=True)
        status_color = RD if r.status == LoopStatus.AWAITING_LLM else GR
        print(f"\n  {status_color}Status: {r.status}{W}  "
              f"MR: {r.match_rate:.3f}  GAP: {r.queries_generated}  "
              f"LOCAL: {r.queries_resolved_local}  LLM: {r.queries_sent_to_llm}")
        all_pending.extend(r.pending_queries)
        print()

    # ── 5. Уникальные запросы ────────────────────────────────────────
    seen = set()
    unique_pending = []
    for q in all_pending:
        if q.query_text not in seen:
            seen.add(q.query_text)
            unique_pending.append(q)

    hdr(f"Фаза 5: Сводка — {len(unique_pending)} уникальных ContextQuery")
    if not unique_pending:
        print(f"  {GR}Все разрывы разрешены локально или GAP не обнаружен.{W}")
        print(f"  Попробуй: --gap 0.5 --streak 1")
        return

    for i, q in enumerate(unique_pending, 1):
        print(f"  {AM}{i}. [{q.trigger_outcome}]{W} «{q.trigger_token}»  "
              f"gap={q.confidence_gap:.2f}")
        print(f"     {q.query_text}")
        print()

    # ── 6. LLM-запрос ─────────────────────────────────────────────────
    if not args.api_key:
        print(f"  {AM}API ключ не передан — пропускаем реальный LLM-вызов.{W}")
        print(f"  Запусти: py -X utf8 training/proposal_loop_demo.py --api-key sk-ant-...")
        return

    hdr(f"Фаза 6: Отправляем {len(unique_pending)} запрос(а) в LLM")
    for q in unique_pending:
        app.system.teaching_log.push_query(q)

    client = AnthropicClient(
        api_key=args.api_key,
        model="claude-haiku-4-5-20251001",
        max_tokens=256,
    )
    prompt = LLMPromptBuilder.build(
        app.system,
        app.system.teaching_log.get_recent(20),
        queries=unique_pending,
    )
    print(f"  Промпт: {len(prompt)} символов")
    raw = client.complete(prompt)
    decision = LLMResponseParser.parse(raw)

    received_texts = []
    if decision and decision.action == "TEACH" and decision.text:
        print(f"  {GR}LLM → TEACH:{W} «{decision.text}»")
        received_texts.append(decision.text)
        registry.register(decision.text, source_id="llm_reply", origin="llm")
    else:
        print(f"  {AM}LLM → {decision.action if decision else '?'}{W}")

    app.system.teaching_log.clear_queries()

    if not received_texts:
        return

    # ── 7. resume_after_llm ──────────────────────────────────────────
    hdr("Фаза 7: resume_after_llm — возобновляем цикл")
    app.system.reset_context()
    r_resume = pcl.resume_after_llm(received_texts, max_steps=50, verbose=True)

    new_base = len(app.system.base.all())
    print(f"\n  {BD}База: {base_size} → {new_base} Gen (+{new_base - base_size}){W}")
    print(f"  MR после LLM: {r_resume.match_rate:.3f}  "
          f"Status: {r_resume.status}  "
          f"GAP: {r_resume.queries_generated}")

    # ── 8. Повторный тест ────────────────────────────────────────────
    hdr("Фаза 8: Повторный тест после resume_after_llm")
    for text in unknown_texts[:2]:
        app.system.reset_context()
        print(f"  {BD}«{text}»{W}")
        pcl.load_buffer(text)
        r2 = pcl.run_cycle(max_steps=50, verbose=False)
        color = GR if r2.match_rate > r1.match_rate * 0.9 else AM
        print(f"  {color}MR: {r2.match_rate:.3f}  GAP: {r2.queries_generated}  "
              f"Status: {r2.status}{W}")
        print()


if __name__ == "__main__":
    main()
