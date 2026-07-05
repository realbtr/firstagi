"""
training/peephole_demo.py — Демонстрация InferencePeephole.

Запуск (быстро, без LLM):
    py -X utf8 training/peephole_demo.py

Режимы:
    --every N         показывать снимок каждые N токенов (по умолч. 1)
    --top K           топ-K Gen в снимке (по умолч. 6)
    --cascade C       порог цепочки для каскада (по умолч. 2)
    --cycles N        остановиться после N токенов (0 = весь текст)
    --text "…"        использовать произвольный текст вместо встроенного
    --phase 1|2|3     выбрать один из трёх сценариев (по умолч. 1)
    --quiet           только заголовки шагов, без развёрнутого списка Gen
"""
from __future__ import annotations

import argparse
import sys

from core.learning import LearningSystem
from core.inference_peephole import InferencePeephole, CycleSnapshot
from core.capacity import CapacityBudget
from drivers.text_driver import TextDriver
from data.gen_base import GenBaseDB

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
# Сценарии
# ══════════════════════════════════════════════════════════════════════════════

SCENARIOS = {
    1: {
        "name": "Ритмический корпус — цикл утро/вечер",
        "train": [
            "утро кот оделся пришла мама",
            "вечер кот мяукает ушла мама",
            "утро папа оделся пошёл работа",
            "вечер папа пришла ужин мама",
            "утро кот мяукает оделся папа",
            "вечер маша пришла дом мама",
        ],
        "test": "утро кот оделся пришла вечер мяукает",
        "comment": (
            "После обучения на ритмичных текстах Gen верхнего уровня должны\n"
            "кодировать бинарный цикл утро→вечер и роль кота как агента."
        ),
    },
    2: {
        "name": "Кооперативные сцены — дарение",
        "train": [
            "заяц принёс морковку маше подарок",
            "медведь принёс пирог маше угощение",
            "папа принёс цветы маме праздник",
            "кот принёс мышку маше игра",
            "друг принёс книгу маше день рождения",
            "мама принёс торт маше праздник",
        ],
        "test": "медведь принёс пирог маше праздник",
        "comment": (
            "Предикат «принёс» должен стать мостовым Gen с высокой степенью.\n"
            "Каскад ожидается когда агент меняется (медведь→кот)."
        ),
    },
    3: {
        "name": "Конфликт → совы (смешанный)",
        "train": [
            "утро кот мяукает маше",
            "заяц принёс морковку маше",
            "медведь принёс пирог маше",
            "совы сказали маше дорога",
            "хемуль знает дорога маше",
            "утро вечер кот мяукает",
        ],
        "test": "совы принёс маше медведь пирог",
        "comment": (
            "Смешение доменов: временной цикл + дарение + мудрые советники.\n"
            "Контекстные сдвиги (↺SHIFT) покажут где домены пересекаются."
        ),
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# Вспомогательные функции
# ══════════════════════════════════════════════════════════════════════════════

def build_system(db_path: str = "") -> LearningSystem:
    cap = CapacityBudget(max_gens=10_000)
    # max_chain=6 — достаточно для L2-L4 Gen без «бесконечных» цепочек
    system = LearningSystem(capacity_budget=cap, min_gen_count=2)
    system.generalizer.max_chain = 6
    if db_path:
        from pathlib import Path
        db = GenBaseDB(Path(db_path))
        loaded = db.load(system.base)
        print(f"  {GR}Загружено {loaded} Gen из {db_path}{W}")
    return system


def train_phase(system: LearningSystem, texts: list[str], passes: int = 5) -> None:
    """Обучение: непрерывный поток текстов (как BackgroundRunner), без изоляции."""
    drv = TextDriver(system)
    for _ in range(passes):
        for text in texts:
            for tok in drv.produce(text):
                system.process_token(tok)


def run_peephole(
    system: LearningSystem,
    test_text: str,
    *,
    top_k: int,
    cascade_threshold: int,
    every_n: int,
    max_cycles: int,
    verbose: bool,
) -> list[CycleSnapshot]:
    # Чистый старт после обучения
    system.engine.context.reset()
    system.generalizer.reset_chain()

    peep = InferencePeephole(
        system,
        top_k=top_k,
        cascade_threshold=cascade_threshold,
    )
    drv = TextDriver(system)
    snaps: list[CycleSnapshot] = []
    for tok in drv.produce(test_text):
        snap = peep.step(tok)
        snaps.append(snap)
        if snap.step % every_n == 0:
            print(peep.render(snap, verbose=verbose))
        if max_cycles and snap.step >= max_cycles:
            break

    print()
    hr("Итог наблюдения")
    print(peep.summary())
    return snaps, peep


def show_cascade_map(snaps: list[CycleSnapshot]) -> None:
    """Карта каскадов и сдвигов по шагам."""
    hr("Карта каскадов и сдвигов контекста")
    print(f"\n  {'Шаг':<5} {'Токен':<18} {'Исход':<12} {'MaxL':<5} {'Каскад':^7} {'↺Сдвиг':^7}")
    hr()
    for s in snaps:
        from core.algorithm import StepOutcome
        oc_col = (GR if s.outcome == StepOutcome.CONFIRMED  else
                  AM if s.outcome == StepOutcome.COMPLETED   else
                  RD if s.outcome == StepOutcome.REFUTED     else
                  CY if s.outcome == StepOutcome.EXPLORING   else DM)
        casc = f"{RD}⚡{W}" if s.is_cascade else "  "
        shft = f"{MG}↺{W}"  if s.is_context_shift else "  "
        print(f"  {s.step:<5} {s.token_label:<18} "
              f"{oc_col}{s.outcome.name:<12}{W} "
              f"{AM}{s.max_chain:<5}{W} "
              f"  {casc}     {shft}")


def show_bridge_summary(snaps: list[CycleSnapshot]) -> None:
    """Какие Gen верхнего уровня встречались чаще всего."""
    from collections import Counter
    freq: Counter = Counter()
    for s in snaps:
        for gi in s.active:
            if not gi.is_competing and gi.chain_len >= 2:
                lbl = gi.label or gi.gen_id[:8]
                freq[(gi.chain_len, lbl)] += 1

    if not freq:
        return

    hr("Топ Gen верхнего уровня в контексте (по частоте)")
    print(f"\n  {'Gen (L=уровень)':<28} {'Встреч':<8} {'Sig'}")
    hr()
    # Подтянем significance из последнего вхождения
    sig_map: dict = {}
    for s in snaps:
        for gi in s.active:
            lbl = gi.label or gi.gen_id[:8]
            key = (gi.chain_len, lbl)
            sig_map[key] = gi.significance

    for (lvl, lbl), cnt in freq.most_common(12):
        sig = sig_map.get((lvl, lbl), 0)
        sig_col = GR if sig >= 0.7 else (AM if sig >= 0.4 else RD)
        print(f"  L{lvl} {CY}{lbl:<24}{W}  {cnt:<8}  {sig_col}{sig:.3f}{W}")


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="InferencePeephole demo")
    parser.add_argument("--every",   type=int, default=1,
                        help="Показывать снимок каждые N токенов")
    parser.add_argument("--top",     type=int, default=6,
                        help="Топ-K Gen в снимке")
    parser.add_argument("--cascade", type=int, default=2,
                        help="Мин. длина цепочки для регистрации каскада")
    parser.add_argument("--cycles",  type=int, default=0,
                        help="Остановиться после N токенов (0 = весь текст)")
    parser.add_argument("--text",    type=str, default="",
                        help="Произвольный тестовый текст")
    parser.add_argument("--phase",   type=int, default=1,
                        choices=[1, 2, 3],
                        help="Сценарий 1/2/3")
    parser.add_argument("--db",      type=str, default="",
                        help="Путь к gen_base.db для загрузки обученных Gen (пропустить обучение)")
    parser.add_argument("--passes",  type=int, default=5,
                        help="Число проходов обучения (по умолч. 5)")
    parser.add_argument("--quiet",   action="store_true",
                        help="Только заголовки шагов")
    parser.add_argument("--no-map",  action="store_true",
                        help="Не показывать карту каскадов")
    args = parser.parse_args()

    sc = SCENARIOS[args.phase]

    hr(f"INFERENCE PEEPHOLE — Сценарий {args.phase}: {sc['name']}")
    print(f"\n  {DM}{sc['comment']}{W}\n")

    # ── Обучение или загрузка из DB ───────────────────────────────────────────
    if args.db:
        system = build_system(db_path=args.db)
    else:
        system = build_system()
        print(f"  Обучение на {len(sc['train'])} текстах × {args.passes} проходов… ",
              end="", flush=True)
        train_phase(system, sc["train"], passes=args.passes)
        print(f"OK — {system.base.size()} Gen")

    # ── Тестовый текст ────────────────────────────────────────────────────────
    test_text = args.text or sc["test"]
    hr(f"Тест: «{test_text}»")
    print(f"\n  every_n={args.every}  top_k={args.top}  cascade_threshold={args.cascade}\n")

    snaps, peep = run_peephole(
        system,
        test_text,
        top_k=args.top,
        cascade_threshold=args.cascade,
        every_n=args.every,
        max_cycles=args.cycles,
        verbose=not args.quiet,
    )

    # ── Аналитика ─────────────────────────────────────────────────────────────
    if not args.no_map:
        show_cascade_map(snaps)
    show_bridge_summary(snaps)
    print()


if __name__ == "__main__":
    main()
