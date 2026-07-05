"""
CharTransitionDriver — калибровка feature_tolerance и сравнение с TextDriver.

Скрипт сканирует значения tolerance от 0.10 до 0.60 и для каждого выводит:
  MR_train — доля CONFIRMED/COMPLETED при повторном проходе по обучающему корпусу
  MR_test  — то же на тестовом (незнакомом) корпусе
  base     — размер базы Gen после обучения

Запуск: py -X utf8 training/char_calibration.py [--passes N] [--train N] [--test N]
"""
from __future__ import annotations

import argparse
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.algorithm import StepOutcome
from core.app import CoreApplication
from drivers.char_transition_driver import CharTransitionDriver
from drivers.text_driver import TextDriver
from training.serial_corpus import ALL_SERIAL_TEXTS

W = "\033[0m"; CY = "\033[96m"; GR = "\033[92m"; AM = "\033[93m"
RD = "\033[91m"; BD = "\033[1m"; DM = "\033[90m"


def _calc_mr(system, driver_cls, texts: list) -> float:
    """Вычислить match-rate (доля CONFIRMED+COMPLETED) на корпусе."""
    total = confirmed = 0
    drv = driver_cls(f"_mr_{id(system)}")
    for t in texts:
        for tok in drv.produce(t):
            r = system.process_token(tok)
            total += 1
            if r.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
                confirmed += 1
        system.reset_context()
    return confirmed / total if total else 0.0


def calibrate(
    tolerances: list,
    n_passes: int,
    n_train: int,
    n_test: int,
) -> None:
    train_texts = ALL_SERIAL_TEXTS[:n_train]
    test_texts  = ALL_SERIAL_TEXTS[n_train : n_train + n_test]

    print(f"\n{BD}{CY}{'═'*72}{W}")
    print(f"{BD}{CY}  CharTransitionDriver · calibration · {n_passes} passes · "
          f"train={len(train_texts)} test={len(test_texts)}{W}")
    print(f"{BD}{CY}{'═'*72}{W}\n")

    header = f"  {'tolerance':>10}  {'base_char':>10}  {'MR_train_char':>13}  "
    header += f"{'MR_test_char':>12}  {'base_text':>10}  {'MR_train_txt':>12}"
    print(f"{DM}{header}{W}")
    print(f"  {'-'*70}")

    for tol in tolerances:
        # CharTransitionDriver
        app_c = CoreApplication(config={"mock_teacher": False, "feature_tolerance": tol})
        app_c.startup()
        cd = CharTransitionDriver("cd_train")
        for _ in range(n_passes):
            for t in train_texts:
                for tok in cd.produce(t):
                    app_c.system.process_token(tok)
                app_c.system.reset_context()

        base_c = app_c.system.base.size()
        mr_train_c = _calc_mr(app_c.system, CharTransitionDriver, train_texts)
        mr_test_c  = _calc_mr(app_c.system, CharTransitionDriver, test_texts)

        # TextDriver (одна точка при том же tolerance для сравнения)
        app_t = CoreApplication(config={"mock_teacher": False, "feature_tolerance": tol})
        app_t.startup()
        td = TextDriver("td_train")
        for _ in range(n_passes):
            for t in train_texts:
                for tok in td.produce(t):
                    app_t.system.process_token(tok)
                app_t.system.reset_context()

        base_t = app_t.system.base.size()
        mr_train_t = _calc_mr(app_t.system, TextDriver, train_texts)

        # цветовая метка по MR
        def color_mr(mr: float) -> str:
            if mr >= 0.80:
                return f"{GR}{mr:.3f}{W}"
            elif mr >= 0.60:
                return f"{AM}{mr:.3f}{W}"
            return f"{RD}{mr:.3f}{W}"

        row = (f"  {tol:>10.2f}  {base_c:>10}  {color_mr(mr_train_c):>13}  "
               f"{color_mr(mr_test_c):>12}  {base_t:>10}  {color_mr(mr_train_t):>12}")
        print(row)

    print(f"\n{DM}  Рекомендация: tolerance при MR_test_char ≥ 0.80{W}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CharTransitionDriver tolerance calibration")
    parser.add_argument("--passes", type=int, default=3,
                        help="Число проходов по корпусу (default: 3)")
    parser.add_argument("--train", type=int, default=10,
                        help="Число текстов для обучения (default: 10)")
    parser.add_argument("--test", type=int, default=5,
                        help="Число текстов для теста (default: 5)")
    args = parser.parse_args()

    tolerances = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50]
    calibrate(tolerances, args.passes, args.train, args.test)
