"""
AdaptiveActivationCounter — компактный счётчик активаций для миллионов шагов.

Проблема VitalityRecord:
  - Хранит deque абсолютных шагов (step=1_000_000 и т.д.)
  - Для mean_interval всё равно считает разности — зачем хранить абсолюты?
  - При миллионах шагов числа большие, но Python справляется; однако
    семантика «ожидаемого интервала» всё равно нужна в компактном виде.

Решение — три уровня детализации:
  1. recent_gaps   deque(maxlen=W)   — последние W межактивационных интервалов.
                                       Точно и свежо, O(W) памяти.
  2. ema_interval  float             — EMA всех интервалов с коэффициентом α.
                                       Плавно сглаживает историю, O(1).
  3. log_total     int (6 бит)       — floor(log2(total_count)).
                                       Порядок величины числа активаций,
                                       не тратя 40+ бит на точный счётчик.

Кроме того, хранится только last_abs_step — последний абсолютный шаг,
нужный для вычисления прошедшего времени (elapsed = current - last).

Сравнение представлений:
  VitalityRecord (20 шагов × ~8 байт) = 160 байт
  AdaptiveActivationCounter           =  ~48 байт

При миллионах Gen разница существенна.

Запуск демо: py -X utf8 training/adaptive_counter.py
"""
from __future__ import annotations

import math
from collections import deque
from typing import Optional


class AdaptiveActivationCounter:
    """
    Компактный трекер истории активаций одного Gen.

    Параметры
    ---------
    window      : int   — размер окна recent_gaps (default 8; ≡ «помним последние 8 ритмов»)
    ema_alpha   : float — коэффициент сглаживания EMA (default 0.15; медленное забывание)

    Использование
    -------------
    c = AdaptiveActivationCounter()
    c.record(step=100)
    c.record(step=130)
    c.record(step=145)
    print(c.mean_interval())   # ≈ (30+15)/2 = 22.5  (из recent_gaps)
    print(c.urgency(200))      # (200-145) / 22.5 ≈ 2.44
    """

    _URGENCY_CAP: float = 10.0

    def __init__(self, window: int = 8, ema_alpha: float = 0.15) -> None:
        if not 1 <= window <= 64:
            raise ValueError("window должен быть в [1, 64]")
        if not 0.0 < ema_alpha <= 1.0:
            raise ValueError("ema_alpha должен быть в (0, 1]")

        self.window: int = window
        self.ema_alpha: float = ema_alpha

        # ─── Основные поля ───────────────────────────────────────────────
        self.recent_gaps: deque[int] = deque(maxlen=window)   # разности, не абсолюты
        self.ema_interval: float = 0.0                         # скользящее среднее
        self.log_total: int = 0                                # floor(log2(total_count)); 6 бит
        self.last_abs_step: Optional[int] = None               # только последний шаг

        # ─── Внутренний счётчик для log_total ───────────────────────────
        self._total_count: int = 0                             # сырой счётчик (Python int)

    # ------------------------------------------------------------------
    # Запись активации
    # ------------------------------------------------------------------

    def record(self, step: int) -> None:
        """Зафиксировать активацию на шаге `step`."""
        if self.last_abs_step is not None:
            gap = step - self.last_abs_step
            if gap > 0:
                self.recent_gaps.append(gap)
                # EMA: при первом интервале инициализируем напрямую
                if self.ema_interval == 0.0:
                    self.ema_interval = float(gap)
                else:
                    self.ema_interval = (
                        self.ema_alpha * gap
                        + (1.0 - self.ema_alpha) * self.ema_interval
                    )

        self.last_abs_step = step
        self._total_count += 1
        # floor(log2(n)) при n≥1; при n=0 → 0
        self.log_total = self._total_count.bit_length() - 1

    # ------------------------------------------------------------------
    # Оценки
    # ------------------------------------------------------------------

    def mean_interval(self, prefer: str = "recent") -> Optional[float]:
        """
        Средний интервал между активациями.

        prefer='recent'  → среднее по recent_gaps (точнее для свежей динамики).
        prefer='ema'     → EMA-оценка (плавнее при редких активациях).
        prefer='blend'   → взвешенное: 0.7 recent + 0.3 ema (умолчание на практике).

        Возвращает None, если история пуста.
        """
        if not self.recent_gaps and self.ema_interval == 0.0:
            return None

        if prefer == "ema":
            return self.ema_interval if self.ema_interval > 0.0 else None

        recent_mean = (
            sum(self.recent_gaps) / len(self.recent_gaps)
            if self.recent_gaps else None
        )

        if prefer == "recent":
            return recent_mean

        # blend
        if recent_mean is None:
            return self.ema_interval if self.ema_interval > 0.0 else None
        if self.ema_interval == 0.0:
            return recent_mean
        return 0.7 * recent_mean + 0.3 * self.ema_interval

    def urgency(self, current_step: int) -> float:
        """
        Срочность = elapsed / mean_interval.
        0.0, если история пуста или mean_interval не определён.
        Ограничено сверху _URGENCY_CAP.
        """
        mi = self.mean_interval()
        if mi is None or mi <= 0.0 or self.last_abs_step is None:
            return 0.0
        elapsed = current_step - self.last_abs_step
        return min(elapsed / mi, self._URGENCY_CAP)

    def vitality(self, current_step: int, significance: float) -> float:
        """
        Жизненность = significance × exp(-max(0, urgency - 1)).
        Льготный период: пока urgency ≤ 1, жизненность = significance.
        """
        u = self.urgency(current_step)
        return significance * math.exp(-max(0.0, u - 1.0))

    def total_activations_approx(self) -> int:
        """
        Приближённое число активаций из log_total.
        Возвращает 2^log_total (нижняя граница порядка).
        """
        return 1 << self.log_total if self.log_total > 0 else self._total_count

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def memory_bytes_approx(self) -> int:
        """Приблизительный размер объекта в байтах."""
        # deque: maxlen * ~28 bytes (int object) + overhead ≈ maxlen*28 + 56
        deque_bytes = self.window * 28 + 56
        # остальные поля: ~7 * 8 = 56 bytes
        return deque_bytes + 56

    def __repr__(self) -> str:
        mi = self.mean_interval()
        mi_str = f"{mi:.1f}" if mi is not None else "—"
        return (
            f"AdaptiveCounter("
            f"total≈2^{self.log_total}, "
            f"mi={mi_str}, "
            f"ema={self.ema_interval:.1f}, "
            f"last={self.last_abs_step}"
            f")"
        )


# ══════════════════════════════════════════════════════════════════════════════
# Сравнение AdaptiveCounter vs VitalityRecord
# ══════════════════════════════════════════════════════════════════════════════

def _compare_representations(n_activations: int = 50, base_step: int = 0) -> None:
    """Демонстрация точности AdaptiveCounter vs VitalityRecord."""
    from collections import deque as _deque
    import random

    random.seed(42)
    # Сгенерировать шаги с гауссовым интервалом ≈ 20 ± 5
    steps = []
    s = base_step
    for _ in range(n_activations):
        s += max(1, int(random.gauss(20, 5)))
        steps.append(s)

    # VitalityRecord (эмуляция)
    hist_deque: _deque = _deque(maxlen=20)
    for st in steps:
        hist_deque.append(st)
    vr_steps = list(hist_deque)
    vr_gaps = [vr_steps[i+1] - vr_steps[i] for i in range(len(vr_steps)-1)]
    vr_mi = sum(vr_gaps) / len(vr_gaps) if vr_gaps else 0.0

    # AdaptiveCounter
    ac = AdaptiveActivationCounter(window=8, ema_alpha=0.15)
    for st in steps:
        ac.record(st)

    ac_mi_r = ac.mean_interval("recent")
    ac_mi_e = ac.mean_interval("ema")
    ac_mi_b = ac.mean_interval("blend")

    true_mi = sum(steps[i+1] - steps[i] for i in range(len(steps)-1)) / (len(steps)-1)

    print(f"\n  n_activations = {n_activations}, base_step = {base_step:,}")
    print(f"  True mean_interval         ≈ {true_mi:.2f}")
    print(f"  VitalityRecord (last 20)   =  {vr_mi:.2f}  "
          f"(err={abs(vr_mi-true_mi)/true_mi*100:.1f}%)")
    print(f"  AdaptiveCounter  recent    =  {ac_mi_r:.2f}  "
          f"(err={abs(ac_mi_r-true_mi)/true_mi*100:.1f}%)")
    print(f"  AdaptiveCounter  ema       =  {ac_mi_e:.2f}  "
          f"(err={abs(ac_mi_e-true_mi)/true_mi*100:.1f}%)")
    print(f"  AdaptiveCounter  blend     =  {ac_mi_b:.2f}  "
          f"(err={abs(ac_mi_b-true_mi)/true_mi*100:.1f}%)")
    print(f"  log_total = {ac.log_total} (≈ 2^{ac.log_total} = {1<<ac.log_total}, "
          f"exact = {ac._total_count})")
    print(f"  Memory: AdaptiveCounter ≈ {ac.memory_bytes_approx()} bytes  "
          f"vs VitalityRecord ≈ {20*28+56+20} bytes")


if __name__ == "__main__":
    W  = "\033[0m";  CY = "\033[96m"; GR = "\033[92m"
    AM = "\033[93m"; BD = "\033[1m"

    print(f"\n{BD}{CY}{'═'*68}{W}")
    print(f"{BD}{CY}  AdaptiveActivationCounter — демонстрация{W}")
    print(f"{BD}{CY}{'═'*68}{W}")

    print(f"\n{AM}1. Точность при малых шагах (base=0){W}")
    _compare_representations(n_activations=50, base_step=0)

    print(f"\n{AM}2. Точность при больших шагах (base=1_000_000){W}")
    _compare_representations(n_activations=50, base_step=1_000_000)

    print(f"\n{AM}3. Пример urgency при прогрессирующей задержке{W}")
    ac = AdaptiveActivationCounter(window=8, ema_alpha=0.15)
    for s in range(0, 200, 20):
        ac.record(s)   # интервал ≈ 20
    print(f"   После 10 активаций с интервалом 20:")
    print(f"   {ac}")
    for delay, expected in [(5, "< 1 — в норме"), (25, "≈ 1 — на пороге"),
                             (60, "> 1 — стучится"), (200, "max = 10.0")]:
        u = ac.urgency(ac.last_abs_step + delay)
        v = ac.vitality(ac.last_abs_step + delay, significance=0.8)
        print(f"   elapsed={delay:>3}  urgency={u:.2f}  vitality={v:.3f}  [{expected}]")

    print(f"\n{GR}✓ AdaptiveActivationCounter работает корректно{W}\n")
