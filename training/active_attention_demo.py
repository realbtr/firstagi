"""
training/active_attention_demo.py — Демо: полный цикл активного внимания.

Показывает:
  1. Обучение на корпусе (формирование базы Gen)
  2. Активное внимание: система читает буфер сама
  3. При IDLE: ActiveQueryBridge формирует запрос
  4. ContextBroker ищет ответ локально или отправляет к LLM
  5. Возобновление цикла после пополнения буфера

Запуск:
    py -X utf8 training/active_attention_demo.py
    py -X utf8 training/active_attention_demo.py --passes 10
    py -X utf8 training/active_attention_demo.py --api-key sk-ant-...
"""
from __future__ import annotations

import argparse
import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.attention_loop import AttentionLoop
from core.proposal_loop import ProposalCommandLoop, LoopStatus
from core.active_query_bridge import ActiveQueryBridge
from drivers.text_driver import TextDriver
from drivers.speech_driver import SpeechDriver
from drivers.context_broker import ContextBroker, SourceTextRegistry
from training.serial_corpus import ALL_SERIAL_TEXTS

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
# Обучение
# ──────────────────────────────────────────────────────────────────────

def train(app: CoreApplication, texts: list, n_passes: int = 5) -> None:
    d = TextDriver("train")
    for p in range(1, n_passes + 1):
        n_new = 0
        for t in texts:
            for tok in d.produce(t):
                r = app.system.process_token(tok)
                if r.new_gen_id:
                    n_new += 1
            app.system.reset_context()
        bs = len(app.system.base.all())
        print(f"  Pass {p:2d}: base={bs}  n_new={n_new}")


# ──────────────────────────────────────────────────────────────────────
# Активное внимание с bridge
# ──────────────────────────────────────────────────────────────────────

def run_active_cycle(
    pcl: ProposalCommandLoop,
    bridge: ActiveQueryBridge,
    text: str,
    max_rounds: int = 5,
    force_idle_after: int = 0,
    verbose: bool = True,
) -> dict:
    """
    Запустить полный цикл активного внимания для одного текста.

    Алгоритм:
      1. Загрузить текст в буфер
      2. pcl.run_cycle() — обработать буфер (или force_idle_after шагов)
      3. Если IDLE → bridge.on_idle() → пополнение буфера → повтор
      4. Повторять max_rounds раз или пока не IDLE

    force_idle_after > 0: прервать цикл после N шагов и принудительно
    вызвать bridge (для тестирования Bridge без реального IDLE).
    """
    stats = {
        "text": text,
        "rounds": 0,
        "total_steps": 0,
        "total_gaps": 0,
        "total_resolved": 0,
        "total_bridge_idle": 0,
        "final_status": LoopStatus.DONE,
    }

    for round_n in range(1, max_rounds + 1):
        stats["rounds"] = round_n

        # Загрузить текст в буфер
        pcl.load_buffer(text)

        # Запустить цикл (с ограничением по шагам если force_idle_after)
        max_steps = force_idle_after if force_idle_after > 0 else 200
        result = pcl.run_cycle(max_steps=max_steps, verbose=verbose)

        stats["total_steps"] += result.total_steps
        stats["total_gaps"] += result.queries_generated
        stats["total_resolved"] += result.queries_resolved_local
        stats["final_status"] = result.status

        if verbose:
            print(f"\n  {BD}Round {round_n}:{W} "
                  f"steps={result.total_steps}  "
                  f"MR={result.match_rate:.3f}  "
                  f"GAP={result.queries_generated}  "
                  f"LOCAL={result.queries_resolved_local}  "
                  f"Status={result.status}")

        # Определяем: был ли IDLE自然но или принудительно
        non_idle = [s for s in result.steps if s.outcome != "IDLE"]
        natural_idle = (len(non_idle) == 0)
        forced_idle = (force_idle_after > 0 and result.total_steps >= force_idle_after
                       and not natural_idle)

        # Принудительный IDLE: симулируем пустой буфер для Bridge
        if forced_idle:
            stats["total_bridge_idle"] += 1
            if verbose:
                print(f"  {AM}[FORCE IDLE] after {force_idle_after} steps{W}")
            # Очищаем буферы чтобы Bridge сработал на чистом состоянии
            for did in pcl._loop._peripherals.driver_ids():
                d = pcl._loop._peripherals.get(did)
                if d is not None:
                    d.clear_buffer()

        # Если естественный IDLE — тоже триггерим bridge
        if natural_idle:
            stats["total_bridge_idle"] += 1

        # Вызываем bridge (при любом IDLE: естественном или принудительном)
        if forced_idle or natural_idle:
            bridge_result = bridge.on_idle()
            if bridge_result.query_generated:
                if verbose:
                    print(f"  {MG}Bridge:{W} {bridge_result.strategy} → "
                          f"{bridge_result.reason}")
                    if bridge_result.query:
                        q_text = bridge_result.query.query_text
                        print(f"    Query: {q_text[:100]}...")

                if not bridge_result.query_resolved:
                    stats["final_status"] = LoopStatus.AWAITING_LLM
                    if verbose:
                        print(f"  {AM}→ Sent to LLM (AWAITING_LLM){W}")
                    break
                else:
                    if verbose:
                        print(f"  {GR}→ Resolved locally, continuing...{W}")
            else:
                if verbose:
                    print(f"  {DM}Bridge: no strategy applicable{W}")
                break
        elif non_idle:
            # Буфер обработан, но не пуст — выходим
            break

    return stats


# ──────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--passes", type=int, default=5,
                        help="Количество проходов обучения")
    parser.add_argument("--n-train", type=int, default=15,
                        help="Количество текстов для обучения")
    parser.add_argument("--gap", type=float, default=0.30,
                        help="Порог GAP в SpeechDriver")
    parser.add_argument("--streak", type=int, default=2,
                        help="Минимальная серия REFUTED для GAP")
    parser.add_argument("--force-idle", type=int, default=0,
                        help="Принудительный IDLE после N шагов (0=отключен)")
    parser.add_argument("--api-key", default="",
                        help="Anthropic API key (опционально)")
    args = parser.parse_args()

    # ── 1. Инициализация ─────────────────────────────────────────────
    hdr("Фаза 1: Инициализация")
    app = CoreApplication(config={
        "mock_teacher": False,
        "feature_tolerance": 0.15,
    })
    app.startup()

    # Реестр текстов + брокер
    registry = SourceTextRegistry()
    broker = ContextBroker(
        teaching_log=app.system.teaching_log,
        registry=registry,
    )

    # Обучающие тексты
    train_texts = ALL_SERIAL_TEXTS[:args.n_train]
    for i, t in enumerate(train_texts):
        broker.register_source(t, source_id=f"train_{i}", origin="serial")

    print(f"  Обучающих текстов: {len(train_texts)}")
    print(f"  Реестр: {registry.size()} текстов")
    if args.force_idle > 0:
        print(f"  {AM}Force IDLE: каждые {args.force_idle} шагов{W}")

    # ── 2. Обучение ──────────────────────────────────────────────────
    hdr("Фаза 2: Обучение")
    train(app, train_texts, n_passes=args.passes)
    base_size = len(app.system.base.all())
    print(f"\n  {BD}База после обучения: {base_size} Gen{W}")

    # ── 3. Сборка замкнутого цикла ───────────────────────────────────
    hdr("Фаза 3: Сборка замкнутого цикла")

    loop = AttentionLoop(app.system, app.peripherals)
    speech = SpeechDriver(verbosity=0, lang="ru")  # verbosity=0 для компактности
    pcl = ProposalCommandLoop(
        loop,
        speech=speech,
        broker=broker,
        default_driver_id="text",
        gap_threshold=args.gap,
        min_streak=args.streak,
    )
    bridge = ActiveQueryBridge(app.system, broker, driver_id="text")

    print(f"  {pcl}")
    print(f"  {bridge}")

    # ── 4. Тест: знакомый текст ──────────────────────────────────────
    hdr("Фаза 4: Знакомый текст (ожидаем высокий MR)")
    known_text = "маша пошла в лес и встретила медведя"
    print(f"  {BD}«{known_text}»{W}")

    stats_known = run_active_cycle(pcl, bridge, known_text, max_rounds=3,
                                   force_idle_after=args.force_idle)
    print(f"\n  {BD}Итог:{W} rounds={stats_known['rounds']}  "
          f"steps={stats_known['total_steps']}  "
          f"gaps={stats_known['total_gaps']}  "
          f"resolved={stats_known['total_resolved']}  "
          f"status={stats_known['final_status']}")

    # ── 5. Тест: незнакомый текст ────────────────────────────────────
    hdr("Фаза 5: Незнакомый текст — автономный цикл с Bridge")
    unknown_text = "мальчик нашёл ключ открыл дверь вошёл внутрь"
    print(f"  {BD}«{unknown_text}»{W}")

    app.system.reset_context()
    stats_unknown = run_active_cycle(pcl, bridge, unknown_text, max_rounds=3,
                                     force_idle_after=args.force_idle)
    print(f"\n  {BD}Итог:{W} rounds={stats_unknown['rounds']}  "
          f"steps={stats_unknown['total_steps']}  "
          f"gaps={stats_unknown['total_gaps']}  "
          f"resolved={stats_unknown['total_resolved']}  "
          f"status={stats_unknown['final_status']}")

    # ── 6. Тест: серия незнакомых текстов ────────────────────────────
    hdr("Фаза 6: Серия незнакомых текстов")
    test_texts = [
        "девочка увидела незнакомца испугалась позвала маму",
        "кот залез на крышу соседи удивились позвонили пожарным",
        "рыбка выпрыгнула из воды поймала муху вернулась обратно",
    ]

    all_stats = []
    for text in test_texts:
        print(f"\n  {BD}«{text}»{W}")
        app.system.reset_context()
        s = run_active_cycle(pcl, bridge, text, max_rounds=2, verbose=False,
                             force_idle_after=args.force_idle)
        all_stats.append(s)
        status_color = GR if s["final_status"] == LoopStatus.DONE else AM
        print(f"  {status_color}steps={s['total_steps']}  "
              f"gaps={s['total_gaps']}  "
              f"resolved={s['total_resolved']}  "
              f"status={s['final_status']}{W}")

    # ── 7. Сводка ────────────────────────────────────────────────────
    hdr("Фаза 7: Сводка")

    total_steps = sum(s["total_steps"] for s in all_stats)
    total_gaps = sum(s["total_gaps"] for s in all_stats)
    total_resolved = sum(s["total_resolved"] for s in all_stats)
    total_bridge_idle = sum(s.get("total_bridge_idle", 0) for s in all_stats)
    n_done = sum(1 for s in all_stats if s["final_status"] == LoopStatus.DONE)

    print(f"  {BD}Общая статистика:{W}")
    print(f"  Всего шагов:      {BD}{total_steps}{W}")
    print(f"  GAP-запросов:     {BD}{total_gaps}{W}")
    print(f"  Разрешено локально: {BD}{total_resolved}{W}")
    print(f"  Bridge IDLE:      {BD}{total_bridge_idle}{W}")
    print(f"  Завершено (DONE):  {BD}{n_done}/{len(all_stats)}{W}")

    print(f"\n  {BD}Bridge:{W}")
    for k, v in bridge.stats().items():
        print(f"    {k}: {v}")

    print(f"\n  {BD}InitiativeEngine:{W}")
    ie_stats = app.system.engine.initiative.stats() if hasattr(app.system.engine, 'initiative') else {}
    for k, v in ie_stats.items():
        print(f"    {k}: {v}")

    # ── 8. Топ Gen ───────────────────────────────────────────────────
    hdr("Фаза 8: Топ Gen по значимости")
    top = sorted(app.system.base.all(), key=lambda g: g.significance, reverse=True)[:10]
    for g in top:
        bar = "█" * int(g.significance * 20)
        print(f"  {GR}{g.gen_id[:8]}{W}  "
              f"sig={AM}{g.significance:.3f}{W}  "
              f"L{len(g.feature_chain)}  "
              f"{DM}{bar}{W}  "
              f"{MG}{g.label}{W}")

    print(f"\n{DM}{'─'*68}{W}")
    print(f"{DM}Демо завершено. Полный цикл активного внимания работает.{W}\n")


if __name__ == "__main__":
    main()
