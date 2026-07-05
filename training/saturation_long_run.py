"""
Длинный прогон насыщения.

Два режима:
  --mode tiny    — 5 текстов, плато n_new=0 за ~30–50 проходов, 1000+ быстро
  --mode serial  — 65 текстов сериального корпуса, демонстрирует ненулевое плато

Цели:
  1. Найти реальное плато d(new_gen)/d(pass)
  2. Показать монотонный рост mean_interval (H8)
  3. Показать AdaptiveCounter при больших step-числах

Запуск:
    py -X utf8 training/saturation_long_run.py --mode tiny
    py -X utf8 training/saturation_long_run.py --mode tiny   --passes 2000
    py -X utf8 training/saturation_long_run.py --mode serial --passes 200  --report 10
"""
from __future__ import annotations

import sys, os, time, argparse
from typing import Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.app import CoreApplication
from core.algorithm import StepOutcome
from drivers.text_driver import TextDriver
from training.serial_corpus import ALL_SERIAL_TEXTS, SITUATION_FAMILIES
from training.adaptive_counter import AdaptiveActivationCounter

# ─── ANSI ─────────────────────────────────────────────────────────────────────
W  = "\033[0m";  CY = "\033[96m"; GR = "\033[92m"; AM = "\033[93m"
RD = "\033[91m"; DM = "\033[90m"; BD = "\033[1m"


def _hdr(t: str) -> None:
    print(f"\n{BD}{CY}{'═'*72}{W}")
    print(f"{BD}{CY}  {t}{W}")
    print(f"{BD}{CY}{'═'*72}{W}\n", flush=True)


# ══════════════════════════════════════════════════════════════════════════════
# Строим корпусы
# ══════════════════════════════════════════════════════════════════════════════

# Tiny: 5 текстов одной ситуации (встреча) — намеренно небольшое пространство
TINY_CORPUS: List[str] = SITUATION_FAMILIES["встреча"]   # 5 текстов

# Serial: весь сериальный корпус (65 текстов, высокое разнообразие)
SERIAL_CORPUS: List[str] = ALL_SERIAL_TEXTS


# ══════════════════════════════════════════════════════════════════════════════
# Основной прогон
# ══════════════════════════════════════════════════════════════════════════════

def run_saturation(
    corpus: List[str],
    corpus_name: str,
    n_passes: int = 1000,
    report_every: int = 50,
) -> None:
    _hdr(f"Длинный прогон насыщения — {n_passes} проходов  ·  {corpus_name}")

    n_texts = len(corpus)
    # Подсчитать токены в первом прогоне заранее
    d_pre = TextDriver(driver_id="text")
    tokens_per_pass = sum(len(list(d_pre.produce(t))) for t in corpus)
    print(f"  Корпус: {n_texts} текстов · {tokens_per_pass} токенов/проход")
    print(f"  Проходов: {n_passes},  отчёт каждые {report_every}")
    print()

    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
    app.startup()
    d = TextDriver(driver_id="text")

    # AdaptiveCounter — агрегированные подтверждения
    ac = AdaptiveActivationCounter(window=16, ema_alpha=0.1)

    step_ctr: int = 0
    prev_base_size: int = 0
    pass_stats: List[Dict] = []
    prev_n_new: Optional[int] = None

    print(
        f"  {'Pass':>5}  {'Base':>7}  {'n_new':>5}  "
        f"{'Δn_new':>6}  {'avg_mi':>8}  {'mr':>5}  {'ms/p':>6}"
    )
    print(
        f"  {'─'*5}  {'─'*7}  {'─'*5}  "
        f"{'─'*6}  {'─'*8}  {'─'*5}  {'─'*6}"
    )

    t_start   = time.perf_counter()
    t_pass    = time.perf_counter()

    for pass_i in range(1, n_passes + 1):
        t0 = time.perf_counter()
        pass_confirmed = 0
        pass_tokens    = 0

        for text in corpus:
            for tok in d.produce(text):
                r = app.system.process_token(tok)
                step_ctr   += 1
                pass_tokens += 1
                if r.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
                    pass_confirmed += 1
                    ac.record(step_ctr)
            app.system.reset_context()

        t1 = time.perf_counter()
        ms_pass = (t1 - t0) * 1000

        curr_base = len(app.system.base.all())
        n_new     = curr_base - prev_base_size
        prev_base_size = curr_base
        mr        = pass_confirmed / pass_tokens if pass_tokens else 0.0

        # avg_mi прокси: P_tokens * B / confirmed  (среднее время между двумя
        # активациями одного Gen, в шагах)
        avg_mi = pass_tokens * curr_base / pass_confirmed if pass_confirmed > 0 else 0.0

        d_n_new = n_new - prev_n_new if prev_n_new is not None else 0
        prev_n_new = n_new

        pass_stats.append({
            "pass": pass_i, "base": curr_base, "n_new": n_new,
            "d_n_new": d_n_new, "avg_mi": avg_mi, "mr": mr,
            "step": step_ctr, "ms": ms_pass,
        })

        if pass_i % report_every == 0 or pass_i == 1:
            mark = f"  {GR}◀ ПЛАТО{W}" if n_new == 0 else ""
            d_str = f"{d_n_new:>+6}" if pass_i > 1 else f"{'':>6}"
            print(
                f"  {pass_i:>5}  {curr_base:>7,}  {n_new:>5}  "
                f"{d_str}  {avg_mi:>8.0f}  {mr:>5.3f}  {ms_pass:>6.0f}{mark}",
                flush=True,
            )

    elapsed = time.perf_counter() - t_start

    # ══════════════════════════════════════════════════════════════════════════
    # Финальный анализ
    # ══════════════════════════════════════════════════════════════════════════

    _hdr("Финальный анализ")

    n_news = [s["n_new"] for s in pass_stats]

    # Плато: n_new = 0
    hard_plateau = next((s["pass"] for s in pass_stats if s["n_new"] == 0), None)

    # Мягкое плато: |Δn_new| < 2 три прохода подряд
    soft_plateau: Optional[int] = None
    for i in range(2, len(pass_stats)):
        if all(abs(pass_stats[j]["d_n_new"]) <= 1
               for j in range(i-2, i+1)):
            soft_plateau = pass_stats[i]["pass"]
            break

    print(f"  {'Жёсткое плато (n_new=0)':<42} {hard_plateau or '—'}")
    print(f"  {'Мягкое плато (|Δn_new|≤1)':<42} {soft_plateau or '—'}")
    print(f"  {'n_new финальный':<42} {n_news[-1]}")
    print(f"  {'Финальный размер базы':<42} {pass_stats[-1]['base']:,}")
    print(f"  {'Итого токен-шагов':<42} {step_ctr:,}")
    print(f"  {'Время':<42} {elapsed:.1f}s  ({elapsed/n_passes*1000:.1f}ms/pass avg)")
    print()

    # Монотонность avg_mi
    mis = [s["avg_mi"] for s in pass_stats if s["avg_mi"] > 0]
    if len(mis) > 1:
        n_up = sum(1 for i in range(len(mis)-1) if mis[i+1] >= mis[i])
        mono = n_up / (len(mis)-1)
        print(f"  {'avg_mi монотонно растёт':<42} {mono:.1%} шагов вверх")
        print(f"  {'avg_mi pass=1 → pass=N':<42} {mis[0]:.0f} → {mis[-1]:.0f}")
    else:
        mono = 0.0
    print()

    # match_rate
    mrs = [s["mr"] for s in pass_stats]
    print(f"  {'match_rate pass=1':<42} {mrs[0]:.4f}")
    print(f"  {'match_rate pass=10%':<42} {mrs[len(mrs)//10]:.4f}")
    print(f"  {'match_rate pass=50%':<42} {mrs[len(mrs)//2]:.4f}")
    print(f"  {'match_rate pass=100%':<42} {mrs[-1]:.4f}")
    print()

    # ══════════════════════════════════════════════════════════════════════════
    # AdaptiveCounter при больших step-числах
    # ══════════════════════════════════════════════════════════════════════════

    _hdr("AdaptiveCounter при больших step-числах")
    print(f"  Финальный step  = {step_ctr:,}")
    print(f"  total_count     = {ac._total_count:,}  ≈ 2^{ac.log_total}  ({1<<ac.log_total:,})")
    ac_mi = ac.mean_interval("blend")
    print(f"  mean_interval   = {ac_mi:.2f}" if ac_mi else "  (недостаточно данных)")
    print(f"  urgency(now)    = {ac.urgency(step_ctr):.4f}  (0 = только что активировался)")
    print()
    print(f"  {DM}VitalityRecord (20 абсолютных шагов) хранит last_step≈{step_ctr:,}{W}")
    print(f"  {DM}AdaptiveCounter: 16 разностей + EMA + 6-бит log → O(1), "
          f"работает при step=10^9+{W}")
    print()

    # ══════════════════════════════════════════════════════════════════════════
    # Полная кривая n_new (сжатая)
    # ══════════════════════════════════════════════════════════════════════════

    _hdr("Кривая n_new · avg_mi · mr по проходам (выборка)")

    # Равномерная выборка ~30 строк
    n_total = len(pass_stats)
    step_r  = max(1, n_total // 30)
    sample  = [s for i, s in enumerate(pass_stats)
               if i % step_r == 0 or i == n_total - 1
               or s["n_new"] == 0]     # первое плато всегда показываем

    # Убрать дубли (плато может попасть дважды)
    seen = set()
    sample_u = []
    for s in sample:
        if s["pass"] not in seen:
            seen.add(s["pass"])
            sample_u.append(s)

    print(f"  {'Pass':>5}  {'n_new':>5}  {'Δn_new':>6}  {'avg_mi':>8}  "
          f"{'base':>7}  {'mr':>6}")
    print(f"  {'─'*5}  {'─'*5}  {'─'*6}  {'─'*8}  {'─'*7}  {'─'*6}")
    for s in sample_u:
        d_str = f"{s['d_n_new']:>+6}" if s["pass"] > 1 else f"{'':>6}"
        plateau_mark = f"  {GR}← 0{W}" if s["n_new"] == 0 else ""
        print(
            f"  {s['pass']:>5}  {s['n_new']:>5}  {d_str}  "
            f"{s['avg_mi']:>8.0f}  {s['base']:>7,}  {s['mr']:>6.4f}{plateau_mark}"
        )

    # ══════════════════════════════════════════════════════════════════════════
    # Итоговые выводы
    # ══════════════════════════════════════════════════════════════════════════

    _hdr("Выводы")

    if hard_plateau is not None:
        plateau_pct = sum(1 for s in pass_stats if s["n_new"] == 0) / n_passes * 100
        print(f"  {GR}✓ Жёсткое плато n_new=0 на pass={hard_plateau} "
              f"({plateau_pct:.0f}% всех проходов){W}")
        print(f"  {GR}✓ H15 ПОДТВЕРЖДЕНА: корпус полностью выучен{W}")
    elif soft_plateau is not None:
        print(f"  {AM}~ Мягкое плато (|Δn_new|≤1) на pass={soft_plateau}{W}")
        print(f"  {AM}  n_new стабилизировался ≈ {n_news[-1]} — корпус диверсифицирован{W}")
        print(f"  {AM}  Вывод: разнообразие корпуса > вместимость «идеального усвоения»{W}")
    else:
        print(f"  {RD}✗ Плато не найдено за {n_passes} проходов{W}")
        print(f"  {AM}  Нужно больше проходов или меньший корпус{W}")

    if len(mis) > 1 and mono >= 0.90:
        print(f"  {GR}✓ avg_mi монотонно растёт ({mono:.0%}) — H8 подтверждена повторно{W}")
    elif len(mis) > 1:
        print(f"  {AM}⚠ avg_mi: {mono:.0%} шагов вверх{W}")

    print()
    print(f"  {DM}N^M: база ≈ {pass_stats[-1]['base']:,} = 2^{pass_stats[-1]['base'].bit_length()-1} Gen{W}")
    if hard_plateau:
        print(f"  {DM}Сигнал учителю: сменить домен или ввести chain=5+ тексты.{W}")
    else:
        print(f"  {DM}Сигнал учителю: ненулевое плато = структурное разнообразие корпуса,{W}")
        print(f"  {DM}система не достигает полного усвоения — нужен более узкий фокус.{W}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode",    choices=["tiny", "serial"], default="tiny",
                        help="tiny = 5 текстов (встреча), serial = 65 текстов")
    parser.add_argument("--passes",  type=int, default=1000)
    parser.add_argument("--report",  type=int, default=50)
    args = parser.parse_args()

    if args.mode == "tiny":
        corpus      = TINY_CORPUS
        corpus_name = f"Tiny (встреча, {len(TINY_CORPUS)} текстов)"
    else:
        corpus      = SERIAL_CORPUS
        corpus_name = f"Serial (Лесная семья, {len(SERIAL_CORPUS)} текстов)"

    run_saturation(corpus, corpus_name, n_passes=args.passes, report_every=args.report)
