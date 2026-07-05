"""
Интерактивная сессия активного обучения через AttentionLoop.

Принцип: предоставляем системе пространство — загружаем буфер
и наблюдаем, как она сама интегрирует контент.

Запуск: py -X utf8 training/active_run.py
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.app import CoreApplication
from curriculum.debug_session import DebugSession

# ══════════════════════════════════════════════════════════════════════
# Вывод
# ══════════════════════════════════════════════════════════════════════

W  = "\033[0m"
CY = "\033[96m"
GR = "\033[92m"
AM = "\033[93m"
RD = "\033[91m"
DM = "\033[90m"
PU = "\033[95m"
BLD= "\033[1m"

def hdr(title):
    print(f"\n{BLD}{CY}{'═'*60}{W}")
    print(f"{BLD}{CY}  {title}{W}")
    print(f"{BLD}{CY}{'═'*60}{W}")

def sub(title):
    print(f"\n{AM}── {title} ──{W}")

def snapshot(session, label=""):
    snap = session.inspect()
    st   = snap["stats"]
    if label:
        sub(label)
    print(f"  {DM}Gen всего:    {W}{BLD}{st['base_size']}{W}")
    print(f"  {DM}Признаков:    {W}{BLD}{st['features']}{W}")
    print(f"  {DM}Шагов:        {W}{BLD}{st['steps']}{W}")
    print(f"  {DM}Readiness:    {W}{BLD}{snap['readiness']:.3f}{W}")
    res = st.get("resource", {})
    print(f"  {DM}Ресурс:       {W}{BLD}{res.get('level', 0):.2f}{W} "
          f"({DM}{res.get('mode', '?')}{W})")

def show_top(session, n=6):
    top = session.top(n)
    if not top:
        print(f"  {DM}(нет обобщений){W}")
        return
    for g in top:
        bar = "█" * int(g["significance"] * 20)
        print(f"  {GR}{g['gen_id']}{W}  "
              f"sig={AM}{g['significance']:.3f}{W}  "
              f"L{g['chain_len']}  "
              f"{DM}{bar}{W}  "
              f"{PU}{g['label']}{W}")

def show_weak(session, n=4):
    weak = session.weak(n)
    if not weak:
        print(f"  {DM}(нет слабых Gen){W}")
        return
    for g in weak:
        print(f"  {RD}{g['gen_id']}{W}  sig={g['significance']:.3f}  "
              f"L{g['chain_len']}  {DM}{g['label']}{W}")

def run_lesson(session, texts, label, iterations=2):
    """Загрузить тексты в буфер и запустить активное внимание."""
    sub(f"Урок: {label}")
    print(f"  {DM}Тексты: {texts}{W}")

    all_outcomes = []
    for it in range(1, iterations + 1):
        # Загружаем всё снова каждую итерацию
        for text in texts:
            session.load_buffer(text)

        buf = session.buffer_sizes()
        print(f"  {DM}iter {it} · буфер: {buf}{W}", end="  ")

        steps = session.run_attention_until_empty()
        non_idle = [s for s in steps if s["outcome"] != "IDLE"]
        outcomes = [s["outcome"] for s in non_idle]

        confirmed  = outcomes.count("CONFIRMED") + outcomes.count("COMPLETED")
        refuted    = outcomes.count("REFUTED")
        exploring  = outcomes.count("EXPLORING")
        match_rate = confirmed / max(len(outcomes), 1)

        all_outcomes.extend(outcomes)
        print(f"steps={len(non_idle)}  "
              f"{GR}✓{confirmed}{W}  "
              f"{RD}✗{refuted}{W}  "
              f"{AM}?{exploring}{W}  "
              f"match={GR if match_rate > 0.5 else RD}{match_rate:.2f}{W}")

    return all_outcomes


# ══════════════════════════════════════════════════════════════════════
# Главная сессия
# ══════════════════════════════════════════════════════════════════════

def main():
    app = CoreApplication(config={
        "mock_teacher":      False,
        "feature_tolerance": 0.40,   # немного шире для текста
    })
    app.startup()
    session = DebugSession(app)

    # Строим vocab из всего корпуса заранее — единая система координат
    all_texts = [
        "кот сидит",
        "кот спит",
        "кот бежит",
        "кот сидит на окне",
        "кот спит на диване",
        "большой кот сидит",
        "собака бежит",
        "собака лает",
        "маленькая собака бежит",
        "большая собака лает громко",
        "кот и собака",
        "утром кот сидит у окна",
        "вечером кот спит на диване",
    ]
    app.peripherals.get("text").build_vocab(all_texts)

    hdr("FirstAGI · Активное обучение")
    print(f"  {DM}Vocab построен по {len(all_texts)} текстам{W}")
    snapshot(session, "Начальное состояние")

    # ── УРОК 1: Базовые паттерны (высокая стабильность) ───────────────
    hdr("УРОК 1 — Базовые паттерны")
    print(f"  {DM}Стратегия: повторение знакомого, консолидация{W}")

    run_lesson(session, ["кот сидит", "кот спит", "кот бежит"],
               "кот · 3 действия", iterations=3)

    snapshot(session, "После урока 1")
    print(f"\n  {BLD}Топ Gen:{W}")
    show_top(session)

    # ── УРОК 2: Расширение цепочек ─────────────────────────────────────
    hdr("УРОК 2 — Расширение: добавляем контекст места")
    print(f"  {DM}Стратегия: знакомый субъект + новое окружение{W}")

    run_lesson(session,
               ["кот сидит на окне", "кот спит на диване"],
               "кот + место", iterations=3)

    snapshot(session, "После урока 2")
    print(f"\n  {BLD}Топ Gen:{W}")
    show_top(session)
    print(f"\n  {BLD}Слабые Gen (точки роста):{W}")
    show_weak(session)

    # ── УРОК 3: Вариации — добавляем прилагательные ────────────────────
    hdr("УРОК 3 — Вариации субъекта")
    print(f"  {DM}Стратегия: вариация знакомого → новые Gen на стыке{W}")

    run_lesson(session,
               ["большой кот сидит", "большой кот спит"],
               "большой кот", iterations=2)

    snapshot(session, "После урока 3")
    print(f"\n  {BLD}Топ Gen:{W}")
    show_top(session, 8)

    # ── УРОК 4: Новый объект (собака) ─────────────────────────────────
    hdr("УРОК 4 — Новый объект: собака")
    print(f"  {DM}Стратегия: другая сущность · ожидаем REFUTED → новые Gen{W}")

    run_lesson(session,
               ["собака бежит", "собака лает"],
               "собака · базовые", iterations=2)

    snapshot(session, "После урока 4")
    print(f"\n  {BLD}Топ Gen:{W}")
    show_top(session, 8)

    # ── УРОК 5: Интеграция — общие паттерны ───────────────────────────
    hdr("УРОК 5 — Интеграция: смешанный корпус")
    print(f"  {DM}Стратегия: система должна найти общие основания{W}")

    run_lesson(session, [
        "кот сидит на окне",
        "собака бежит",
        "маленькая собака бежит",
        "большая собака лает громко",
        "кот и собака",
    ], "смешанный", iterations=2)

    snapshot(session, "После урока 5")

    # ── УРОК 6: Временной контекст ────────────────────────────────────
    hdr("УРОК 6 — Временно́й контекст (медленные Gen)")
    print(f"  {DM}Стратегия: длинные цепочки · устойчивые контексты{W}")

    run_lesson(session, [
        "утром кот сидит у окна",
        "вечером кот спит на диване",
        "утром кот сидит у окна",
    ], "утро / вечер", iterations=3)

    snapshot(session, "После урока 6")

    # ── ФИНАЛЬНЫЙ СРЕЗ ────────────────────────────────────────────────
    hdr("ФИНАЛЬНЫЙ СРЕЗ")

    snap = session.inspect()
    st   = snap["stats"]
    attn = session.attention_stats()

    print(f"\n  {BLD}Итоговая статистика:{W}")
    print(f"  Gen всего:          {BLD}{st['base_size']}{W}")
    print(f"  Признаков:          {BLD}{st['features']}{W}")
    print(f"  Шагов движка:       {BLD}{st['steps']}{W}")
    print(f"  Readiness:          {BLD}{snap['readiness']:.3f}{W}")
    print(f"  Шагов внимания:     {BLD}{attn['steps']}{W}")
    print(f"  Avg match rate:     {BLD}{attn['avg_match_rate']:.3f}{W}")
    print(f"  Confirmed:          {GR}{attn.get('confirmed', 0)}{W}")
    print(f"  Refuted:            {RD}{attn.get('refuted', 0)}{W}")
    print(f"  New Gens:           {AM}{attn.get('total_new_gens', 0)}{W}")

    print(f"\n  {BLD}Топ-10 обобщений по значимости:{W}")
    show_top(session, 10)

    print(f"\n  {BLD}Точки роста (слабые Gen):{W}")
    show_weak(session, 6)

    # Предсказание — что система ожидает
    print(f"\n  {BLD}Предсказание: «кот сидит на окне»{W}")
    pred = session.predict("кот сидит на окне")
    print(f"  match_rate={GR if pred['match_rate'] > 0.5 else RD}"
          f"{pred['match_rate']:.2f}{W}  "
          f"outcomes={pred['outcomes']}")

    print(f"\n  {BLD}Предсказание: «собака бежит быстро»{W}")
    pred2 = session.predict("собака бежит быстро")
    print(f"  match_rate={GR if pred2['match_rate'] > 0.5 else RD}"
          f"{pred2['match_rate']:.2f}{W}  "
          f"outcomes={pred2['outcomes']}")

    print(f"\n{DM}{'─'*60}{W}")
    print(f"{DM}Сессия завершена. Аттрактор работает.{W}\n")


if __name__ == "__main__":
    main()
