"""
Демо: DualDriverLoop — «переосмысление в новом свете».

Три фазы:

  Фаза 0: text_system обучена на 5 ситуациях.
          smart_system — пуста.
          Прогоняем знакомые тексты через обе.
          → Много REINTERPRETATION: TextDriver CONFIRMED, SmartDriver REFUTED.
          → Кандидаты уже узкие (1–5 слов из активных цепочек).

  Фаза 1: smart_system набирает опыт (несколько проходов по тем же текстам).
          → REINTERPRETATION падает: SmartDriver усваивает известное пространство.
          → avg_probes падает: кандидаты точно предсказывают слово.

  Фаза 2: Новые ситуации (незнакомые обоим).
          → DISCOVERY: оба REFUTED — пространство действительно новое.
          → Кандидаты снова шире (text_system не знает контекста).
          → SmartDriver видит не только «новое», но и «знакомое в новой роли».

Запуск:
    py -X utf8 training/dual_driver_demo.py
    py -X utf8 training/dual_driver_demo.py --passes 8 --verbose
"""

from __future__ import annotations

import sys, os, argparse
from collections import defaultdict
from typing import Dict, List

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.algorithm import StepOutcome
from core.dual_driver import DualDriverLoop, DualPassResult, DualStep, get_next_expected_words
from drivers.text_driver import TextDriver
from training.serial_corpus import SITUATION_FAMILIES

TRAIN_SITUATIONS = ["встреча", "угощение", "игра", "помощь", "праздник"]
TEST_SITUATIONS  = ["опасность", "поиск", "спор", "потеря", "возвращение"]

# ── ANSI ──────────────────────────────────────────────────────────────────────
W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; BL = "\033[94m"

T_SYM = {
    StepOutcome.CONFIRMED : GR + "✓" + W,
    StepOutcome.COMPLETED : GR + BD + "★" + W,
    StepOutcome.REFUTED   : RD + "✗" + W,
    StepOutcome.EXPLORING : AM + "?" + W,
    StepOutcome.CYCLE_AVOIDED: DM + "~" + W,
}

def hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*70}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*70}{W}\n")

def sub(t: str) -> None:
    print(f"\n{BD}{BL}  ── {t} ──{W}\n")

def outcome_short(o: str) -> str:
    return T_SYM.get(o, DM + "?" + W)


# ══════════════════════════════════════════════════════════════════════════════
# Визуализация одного прогона
# ══════════════════════════════════════════════════════════════════════════════

def print_step_line(step: DualStep) -> None:
    """Одна строка: слово | TextOutcome | SmartOutcome | probes | role | candidates."""
    t_sym = outcome_short(step.text_outcome)
    s_sym = outcome_short(step.smart_outcome)

    # Тип шага
    if step.is_reinterpretation:
        marker = MG + "↺ REINTERP" + W
    elif step.is_discovery:
        marker = AM + "✦ DISCOVER" + W
    elif step.is_convergent:
        marker = GR + "≡ CONVERGENT" + W
    else:
        marker = DM + "  ..." + W

    cands_str = ", ".join(step.candidates[:4])
    if len(step.candidates) > 4:
        cands_str += f" +{len(step.candidates)-4}"
    cands_disp = f"[{cands_str}]" if cands_str else "[нет кандидатов]"

    print(
        f"    «{step.word:<12}»  "
        f"T:{t_sym}  S:{s_sym}  "
        f"p={step.probe_stats.probes_used}  "
        f"role={step.role[:2]}  "
        f"{marker}  {DM}{cands_disp[:50]}{W}"
    )


def print_pass_summary(result: DualPassResult, label: str = "") -> None:
    """Компактная строка итогов одного прогона."""
    n_r = len(result.reinterpretations)
    n_d = len(result.discoveries)
    n_c = len(result.convergent)
    col_tmr = GR if result.text_mr >= 0.7 else AM if result.text_mr >= 0.4 else RD
    col_smr = GR if result.smart_mr >= 0.7 else AM if result.smart_mr >= 0.4 else RD

    print(
        f"  {label:<30}  "
        f"T_MR={col_tmr}{result.text_mr:.3f}{W}  "
        f"S_MR={col_smr}{result.smart_mr:.3f}{W}  "
        f"probes={result.avg_probes:.2f}  "
        f"cands={result.avg_candidates:.1f}  "
        f"{MG}↺{n_r}{W}  {AM}✦{n_d}{W}  {GR}≡{n_c}{W}"
    )


# ══════════════════════════════════════════════════════════════════════════════
# Вспомогательные функции
# ══════════════════════════════════════════════════════════════════════════════

def train_text_system(app: CoreApplication, texts: List[str], n_passes: int) -> None:
    """Обучить text_system стандартным TextDriver."""
    drv = TextDriver("td_train")
    for p in range(n_passes):
        n_new = 0
        for t in texts:
            for tok in drv.produce(t):
                r = app.system.process_token(tok)
                if r.new_gen_id:
                    n_new += 1
            app.system.reset_context()
    print(f"  text_system: {len(app.system.base.all())} Gen")


def print_candidate_quality(
    loop: DualDriverLoop,
    texts: List[str],
    label: str,
) -> None:
    """Показать качество кандидатов: сколько их и как часто они верны."""
    total_steps, correct_pred, zero_cand = 0, 0, 0
    total_cands, total_probes = 0, 0

    for t in texts:
        r = loop.process_text(t)
        for step in r.steps:
            total_steps += 1
            total_cands += step.probe_stats.candidates_before
            total_probes += step.probe_stats.probes_used
            if step.probe_stats.candidates_before == 0:
                zero_cand += 1
            if step.probe_stats.was_predicted:
                correct_pred += 1

    n = max(total_steps, 1)
    print(f"  [{label}]  "
          f"шагов={total_steps}  "
          f"avg_cands={total_cands/n:.1f}  "
          f"avg_probes={total_probes/n:.2f}  "
          f"predicted={correct_pred/n:.0%}  "
          f"zero_cand={zero_cand/n:.0%}")


# ══════════════════════════════════════════════════════════════════════════════
# Главная функция
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--passes",  type=int,   default=6,
                        help="Число проходов обучения SmartDriver на знакомых текстах")
    parser.add_argument("--tol",     type=float, default=0.15)
    parser.add_argument("--verbose", action="store_true",
                        help="Детальный вывод каждого шага")
    parser.add_argument("--text",    default="",
                        help="Ввести свой текст вместо корпуса")
    args = parser.parse_args()

    train_texts = [t for sit in TRAIN_SITUATIONS for t in SITUATION_FAMILIES[sit]]
    test_texts  = [t for sit in TEST_SITUATIONS  for t in SITUATION_FAMILIES[sit]]

    # ── Инициализация ─────────────────────────────────────────────────────
    hdr("Инициализация: text_system и smart_system")

    cfg = {"mock_teacher": False, "feature_tolerance": args.tol}
    text_app  = CoreApplication(config=cfg)
    smart_app = CoreApplication(config=cfg)
    text_app.startup()
    smart_app.startup()

    loop = DualDriverLoop(text_app, smart_app, min_entropy=0.5, max_probes=5)

    # ── Фаза 0: Обучение text_system ──────────────────────────────────────
    hdr("Фаза 0: Обучение text_system (TextDriver, 10 проходов)")

    train_text_system(text_app, train_texts, n_passes=10)
    print(f"  smart_system: {len(smart_app.system.base.all())} Gen  (пустая)")

    # Показать качество кандидатов ДО обучения SmartDriver
    print()
    sub("Качество кандидатов из text_system (ДО обучения SmartDriver)")
    print_candidate_quality(loop, train_texts[:5], "знакомые тексты")
    print_candidate_quality(loop, test_texts[:5],  "новые тексты")

    # ── Фаза 1: Первый прогон через DualDriverLoop ────────────────────────
    hdr("Фаза 1: Первый прогон — smart_system видит знакомые тексты впервые")
    print(f"  Ожидаем много REINTERPRETATION (TextDriver уже знает, SmartDriver нет)\n")

    first_pass_results: List[DualPassResult] = []
    all_reinterp: List[DualStep] = []

    for sit in TRAIN_SITUATIONS[:2]:
        sub(sit)
        for text in SITUATION_FAMILIES[sit][:3]:
            result = loop.process_text(text)
            first_pass_results.append(result)
            all_reinterp.extend(result.reinterpretations)
            print_pass_summary(result, text[:45])
            if args.verbose:
                for step in result.steps:
                    print_step_line(step)

    # Топ переосмыслений
    if all_reinterp:
        sub("Топ-10 REINTERPRETATION (знакомо по смыслу, ново по роли)")
        seen = set()
        count = 0
        for step in sorted(all_reinterp,
                           key=lambda s: s.probe_stats.probes_used, reverse=True):
            if step.word in seen:
                continue
            seen.add(step.word)
            cands_str = ", ".join(step.candidates[:5])
            print(
                f"  {MG}↺{W} «{step.word:<12}»  "
                f"role={step.role}  p={step.probe_stats.probes_used}  "
                f"candidates: [{cands_str}]"
            )
            count += 1
            if count >= 10:
                break

    # ── Фаза 2: Обучение SmartDriver (несколько проходов) ─────────────────
    hdr(f"Фаза 2: SmartDriver учится ({args.passes} проходов)")
    print(
        "  Ожидаем: REINTERPRETATION ↓ (SmartDriver усваивает пространство)\n"
        "           avg_probes ↓ (кандидаты точнее предсказывают слово)\n"
    )

    print(
        f"  {'Проход':>7}  {'T_MR':>6}  {'S_MR':>6}  "
        f"{'probes':>7}  {'cands':>6}  {'↺ reinterp':>11}  "
        f"{'✦ disco':>8}  {'≡ conv':>8}  "
        f"{'T_base':>7}  {'S_base':>7}"
    )
    print(f"  {'─'*7}  {'─'*6}  {'─'*6}  {'─'*7}  {'─'*6}  {'─'*11}  "
          f"{'─'*8}  {'─'*8}  {'─'*7}  {'─'*7}")

    for p in range(1, args.passes + 1):
        all_steps: List[DualStep] = []
        for t in train_texts:
            r = loop.process_text(t)
            all_steps.extend(r.steps)

        n = max(len(all_steps), 1)
        t_mr    = sum(1 for s in all_steps
                      if s.text_outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED)) / n
        s_mr    = sum(1 for s in all_steps
                      if s.smart_outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED)) / n
        n_r     = sum(1 for s in all_steps if s.is_reinterpretation)
        n_d     = sum(1 for s in all_steps if s.is_discovery)
        n_c     = sum(1 for s in all_steps if s.is_convergent)
        avg_p   = sum(s.probe_stats.probes_used for s in all_steps) / n
        avg_c   = sum(s.probe_stats.candidates_before for s in all_steps) / n
        t_base  = len(text_app.system.base.all())
        s_base  = len(smart_app.system.base.all())

        col_s = GR if s_mr >= 0.7 else AM if s_mr >= 0.4 else RD
        print(
            f"  {p:>7d}  {t_mr:>6.3f}  {col_s}{s_mr:>6.3f}{W}  "
            f"{avg_p:>7.2f}  {avg_c:>6.1f}  {MG}{n_r:>11d}{W}  "
            f"{AM}{n_d:>8d}{W}  {GR}{n_c:>8d}{W}  "
            f"{t_base:>7d}  {s_base:>7d}"
        )

    # ── Фаза 3: Новые ситуации ─────────────────────────────────────────────
    hdr("Фаза 3: Новые ситуации — что видят оба драйвера?")
    print(f"  Ситуации: {', '.join(TEST_SITUATIONS)}\n")
    print(
        "  Ожидаем:\n"
        "    • DISCOVERY (оба REFUTED) — текст новый для обоих\n"
        "    • REINTERPRETATION — SmartDriver видит знакомых персонажей в новых ролях\n"
        "    • avg_probes ≈ 1–2 (кандидатов мало — контекст пуст для text_system)\n"
    )

    test_results: Dict[str, List[DualPassResult]] = defaultdict(list)
    for sit in TEST_SITUATIONS:
        for text in SITUATION_FAMILIES[sit]:
            r = loop.process_text(text)
            test_results[sit].append(r)

    # Сводка по ситуациям
    print(
        f"  {'Ситуация':<14}  {'T_MR':>6}  {'S_MR':>6}  "
        f"{'probes':>7}  {'cands':>6}  {'↺':>5}  {'✦':>5}  {'≡':>5}"
    )
    print(f"  {'─'*14}  {'─'*6}  {'─'*6}  {'─'*7}  {'─'*6}  {'─'*5}  {'─'*5}  {'─'*5}")

    all_test_steps: List[DualStep] = []
    for sit in TEST_SITUATIONS:
        recs = test_results[sit]
        all_steps_sit = [s for r in recs for s in r.steps]
        all_test_steps.extend(all_steps_sit)
        n = max(len(all_steps_sit), 1)
        t_mr  = sum(1 for s in all_steps_sit
                    if s.text_outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED)) / n
        s_mr  = sum(1 for s in all_steps_sit
                    if s.smart_outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED)) / n
        avg_p = sum(s.probe_stats.probes_used for s in all_steps_sit) / n
        avg_c = sum(s.probe_stats.candidates_before for s in all_steps_sit) / n
        n_r   = sum(1 for s in all_steps_sit if s.is_reinterpretation)
        n_d   = sum(1 for s in all_steps_sit if s.is_discovery)
        n_c   = sum(1 for s in all_steps_sit if s.is_convergent)

        col_t = GR if t_mr >= 0.7 else AM if t_mr >= 0.4 else RD
        col_s = GR if s_mr >= 0.7 else AM if s_mr >= 0.4 else RD
        print(
            f"  {sit:<14}  {col_t}{t_mr:>6.3f}{W}  {col_s}{s_mr:>6.3f}{W}  "
            f"{avg_p:>7.2f}  {avg_c:>6.1f}  "
            f"{MG}{n_r:>5}{W}  {AM}{n_d:>5}{W}  {GR}{n_c:>5}{W}"
        )

    # Детальный вывод одного текста из каждой новой ситуации
    if args.verbose or True:
        sub("Детальный вывод: один текст из каждой новой ситуации")
        for sit in TEST_SITUATIONS[:3]:
            r = test_results[sit][0]
            print(f"\n  [{sit}] «{r.text}»")
            for step in r.steps:
                print_step_line(step)

    # ── Топ REINTERPRETATION в тестовых ситуациях ─────────────────────────
    test_reinterp = [s for s in all_test_steps if s.is_reinterpretation]
    if test_reinterp:
        sub(f"REINTERPRETATION в новых ситуациях ({len(test_reinterp)} событий)")
        print("  Знакомое слово, неожиданная роль — SmartDriver обнаруживает")
        print("  что накопленное знание требует «переосмысления» в новом контексте\n")
        seen = set()
        count = 0
        for step in sorted(test_reinterp,
                           key=lambda s: s.probe_stats.probes_used, reverse=True):
            if step.word in seen:
                continue
            seen.add(step.word)
            cands_str = ", ".join(step.candidates[:6])
            print(
                f"  {MG}↺{W} «{step.word:<14}»  "
                f"role={step.role:<6}  p={step.probe_stats.probes_used}  "
                f"candidates: [{cands_str}]"
            )
            count += 1
            if count >= 12:
                break

    # ── Финальная сводка ──────────────────────────────────────────────────
    hdr("Итоговая картина")

    t_base = len(text_app.system.base.all())
    s_base = len(smart_app.system.base.all())
    n_all  = max(len(all_test_steps), 1)
    n_r_all = sum(1 for s in all_test_steps if s.is_reinterpretation)
    n_d_all = sum(1 for s in all_test_steps if s.is_discovery)
    n_c_all = sum(1 for s in all_test_steps if s.is_convergent)

    print(f"  text_system  Gen: {t_base:5d}  (TextDriver, 10 проходов)")
    print(f"  smart_system Gen: {s_base:5d}  (SmartDriver, {args.passes} проходов)")
    print()
    print(f"  В новых ситуациях ({len(all_test_steps)} слов):")
    print(f"    {MG}↺ REINTERPRETATION{W}  {n_r_all:4d} = {n_r_all/n_all:.0%}")
    print(f"      «знакомое слово, но SmartDriver не видел его в этой роли»")
    print(f"    {AM}✦ DISCOVERY       {W}  {n_d_all:4d} = {n_d_all/n_all:.0%}")
    print(f"      «новое для обеих систем — истинно неизвестный паттерн»")
    print(f"    {GR}≡ CONVERGENT      {W}  {n_c_all:4d} = {n_c_all/n_all:.0%}")
    print(f"      «оба согласны — базовые персонажи/структуры совпадают»")
    print()

    # Динамика avg_candidates по мере роста smart_system
    # (показывает что text_system направляет внимание SmartDriver)
    avg_cands = sum(s.probe_stats.candidates_before for s in all_test_steps) / n_all
    avg_probes = sum(s.probe_stats.probes_used for s in all_test_steps) / n_all
    print(f"  avg candidates от text_system: {avg_cands:.1f}  "
          f"(узкие → точное предсказание)")
    print(f"  avg probes SmartDriver:        {avg_probes:.2f}  "
          f"(мало проб = кандидаты помогли)")

    if n_r_all > n_d_all:
        print(f"\n  {MG}Доминирует REINTERPRETATION:{W}")
        print(f"  Пространство не новое — оно уже знакомо обоими драйверам,")
        print(f"  но SmartDriver видит его в иных ролях (тема↔рема).")
        print(f"  Это именно «переосмысление в новом свете».")
    else:
        print(f"\n  {AM}Доминирует DISCOVERY:{W}")
        print(f"  Пространство новое — ни один драйвер не знает этих паттернов.")
        print(f"  Увеличь --passes чтобы SmartDriver успел освоить базу.")

    print()


if __name__ == "__main__":
    main()
