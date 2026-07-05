"""
Шаг 7: Демо-скрипт сеанса обучения FirstAGI.

Использование:
    py -X utf8 training/run.py              # 1000 шагов
    py -X utf8 training/run.py --steps 200  # 200 шагов
    py -X utf8 training/run.py --verbose    # подробный вывод
"""

from __future__ import annotations

import sys
import os
import argparse

# Ensure project root in path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.learning import LearningSystem
from core.algorithm import StepOutcome
from training.corpus import TextCorpus
from training.teacher import InteractiveTeacher, LifeState, TrainingReport


def print_report(report: TrainingReport) -> None:
    print()
    print("=" * 60)
    print("[Итог сеанса обучения FirstAGI]")
    print("=" * 60)
    print(f"  Шагов обработано:      {report.total_steps}")
    print(f"  Смертей:               {report.deaths}")
    print(f"  Устойчивых петель:     {report.stable_loops}")
    print(f"  Аттракторов:           {report.attractor_count}")
    print(f"  Размер базы Gen:       {report.final_base_size}")
    print(f"  Hit rate (инициатива): {report.hit_rate:.1%}")
    print(f"  Финальный уровень:     {report.difficulty_reached}")
    print(f"  Финальный ресурс:      {report.final_resource:.3f}")
    print()
    print("  Нарратив:")
    print(f"    {report.narrative}")
    print("=" * 60)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Сеанс обучения FirstAGI (Шаг 7)"
    )
    parser.add_argument(
        "--steps", type=int, default=1000,
        help="Количество токенов для обучения (по умолчанию 1000)"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Подробный вывод каждого шага"
    )
    args = parser.parse_args()

    n_steps = args.steps
    verbose = args.verbose

    print()
    print("=" * 60)
    print("[Сеанс обучения FirstAGI — Шаг 7]")
    print(f"  Шагов: {n_steps}")
    print("=" * 60)

    system = LearningSystem(
        feature_tolerance=0.35,
        min_gen_count=2,
        initial_resource=0.5,
    )
    corpus = TextCorpus()
    teacher = InteractiveTeacher(system, corpus, difficulty=1)

    step_counter = 0
    phase_size = max(1, n_steps // 10)

    # Callbacks для вывода
    prev_difficulty = teacher.difficulty
    death_steps: list[int] = []
    loop_steps: list[int] = []

    from drivers.text_driver import TextDriver

    while step_counter < n_steps:
        teacher.adjust_difficulty()

        # Сообщить о смене уровня
        if teacher.difficulty != prev_difficulty:
            direction = "→" if teacher.difficulty > prev_difficulty else "←"
            print(
                f"  [Шаг {step_counter:4d}] "
                f"Уровень {prev_difficulty} {direction} {teacher.difficulty} "
                f"(hit_rate={system.initiative.hit_rate:.1%})"
            )
            prev_difficulty = teacher.difficulty

        # Выбрать текст
        life = teacher.detect_life_state()
        if life in (LifeState.DYING, LifeState.DEAD):
            text = corpus.easy_rescue()
        else:
            text = corpus.next_text(teacher.difficulty)

        driver = TextDriver(driver_id="run")
        tokens = list(driver.produce(text))

        prev_deaths = teacher.death_count
        prev_loops = teacher.stable_loop_count

        for token in tokens:
            if step_counter >= n_steps:
                break
            report = teacher.step_token(token)

            if verbose:
                outcome = report.step_result.outcome.name
                res = report.resource_level
                hit = "HIT" if report.initiative_hit else "---"
                print(
                    f"    step={step_counter:5d} "
                    f"[{outcome:12s}] res={res:.3f} {hit} "
                    f"life={report.life_state.value}"
                )

            # Смерть
            if teacher.death_count > prev_deaths:
                death_steps.append(step_counter)
                print(
                    f"  [Шаг {step_counter:4d}] "
                    f"Смерть #{teacher.death_count} "
                    f"(ресурс={system.resource.level:.3f})"
                )
                prev_deaths = teacher.death_count

            # Стабильная петля
            if teacher.stable_loop_count > prev_loops:
                loop_steps.append(step_counter)
                print(
                    f"  [Шаг {step_counter:4d}] "
                    f"Устойчивая петля #{teacher.stable_loop_count}"
                )
                prev_loops = teacher.stable_loop_count

            step_counter += 1

        system.reset_context()

    final_report = teacher.report()
    print_report(final_report)


if __name__ == "__main__":
    main()
