"""
Шаг 4: Ресурсный драйвер — интегральный сигнал состояния системы.

Ресурс — глобальный нейромодулятор: скаляр [0, 1], который меняет
режим работы Ядра. Ядро не знает, из чего он складывается
(усталость, голод, скука, возбуждение), — оно получает только
агрегированный уровень и адаптирует под него свои параметры.

Уровень ресурса модулирует:
  • Терпимость к ошибке (feature_tolerance) — при высоком ресурсе шире
  • Размер контекста (min_context_gens) — при высоком ресурсе больше
  • Разрешение фазового пространства (Resolution) — подсказка для AttractorEncoder
  • «Окраску» обобщений — к каким аттракторам тянуться

Режимы (по уровню):
  rest      [0.0, 0.2)  — восстановление, только знакомые паттерны
  conserve  [0.2, 0.4)  — экономия, короткие цепочки
  normal    [0.4, 0.7)  — обычное обучение
  explore   [0.7, 0.9)  — активное исследование
  abundant  [0.9, 1.0]  — максимальная экспансия
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import List, Optional, Callable
import time

from .algorithm import StepResult, StepOutcome
from .attractor import Resolution


# ══════════════════════════════════════════════════════════════════════
# Состояние ресурса
# ══════════════════════════════════════════════════════════════════════

@dataclass
class ResourceState:
    """
    Мгновенный снимок ресурсного состояния системы.

    level: текущий уровень [0.0 → 1.0]
    trend: производная (>0 = восполняется, <0 = тратится)
    """
    level: float = 0.5
    trend: float = 0.0

    @property
    def mode(self) -> str:
        """Текстовый режим — для логов и промптов LLM-учителей."""
        if self.level < 0.2:
            return "rest"
        if self.level < 0.4:
            return "conserve"
        if self.level < 0.7:
            return "normal"
        if self.level < 0.9:
            return "explore"
        return "abundant"

    def modulate_tolerance(self, base: float) -> float:
        """
        Адаптировать feature_tolerance под текущий ресурс.
        Низкий ресурс → строже (только знакомые паттерны).
        Высокий ресурс → мягче (принимаем новые похожие паттерны).
        """
        return base * (0.5 + self.level)

    def modulate_context_size(self, base: int) -> int:
        """Адаптировать min_context_gens: больше гипотез при высоком ресурсе."""
        return max(1, int(base * (0.5 + self.level)))

    def resolution_hint(self) -> Resolution:
        """
        Подсказка AttractorEncoder: при низком ресурсе — COARSE
        (экономим внимание), при высоком — FINE/EXACT (различаем тонкости).
        """
        if self.level < 0.3:
            return Resolution.COARSE
        if self.level < 0.6:
            return Resolution.MEDIUM
        if self.level < 0.85:
            return Resolution.FINE
        return Resolution.EXACT

    def is_depleted(self) -> bool:
        return self.level < 0.2

    def is_abundant(self) -> bool:
        return self.level >= 0.9


# ══════════════════════════════════════════════════════════════════════
# Драйвер ресурса
# ══════════════════════════════════════════════════════════════════════

class ResourceDriver:
    """
    Агрегирует сигналы состояния в единый ResourceState.

    Первый этап — программное API:
        driver.set_level(0.8)
        driver.add_reward(50.0)
        driver.consume(0.02)
        driver.recover(0.05)

    Автоматическое обновление через step(result) встроено в LearningSystem.

    Расходование:
      COMPLETED → небольшое восстановление (успех приятен)
      CONFIRMED → лёгкий расход (работа идёт)
      REFUTED   → умеренный расход (ошибка стоит сил)
      EXPLORING → минимальный расход (пустой поиск)
    """

    # Стоимости и прибыли разных исходов
    _OUTCOME_DELTA: dict = {
        StepOutcome.COMPLETED:     +0.03,
        StepOutcome.CONFIRMED:     -0.005,
        StepOutcome.REFUTED:       -0.02,
        StepOutcome.EXPLORING:     -0.01,
        StepOutcome.CYCLE_AVOIDED: -0.001,
    }

    def __init__(
        self,
        initial_level: float = 0.5,
        reward_scale: float = 0.1,   # нормировка внешней награды в [0,1]
    ) -> None:
        self._level: float = max(0.0, min(1.0, initial_level))
        self._prev_level: float = self._level
        self.reward_scale = reward_scale
        self._history: List[float] = [self._level]

    # ------------------------------------------------------------------
    # Программное API

    def set_level(self, level: float) -> None:
        """Прямая установка уровня ресурса."""
        self._prev_level = self._level
        self._level = max(0.0, min(1.0, level))
        self._history.append(self._level)

    def add_reward(self, amount: float) -> None:
        """
        Дофаминовый удар: вброс ресурса от TeacherDriver.
        amount — условные единицы (нормируются через reward_scale).
        """
        delta = amount * self.reward_scale
        self.set_level(self._level + delta)

    def consume(self, cost: float) -> None:
        """Потратить ресурс (когнитивная нагрузка, ошибка)."""
        self.set_level(self._level - cost)

    def recover(self, amount: float) -> None:
        """Восстановить ресурс (успех, отдых)."""
        self.set_level(self._level + amount)

    # ------------------------------------------------------------------
    # Автоматическое обновление

    def step(self, result: StepResult) -> None:
        """Обновить ресурс по результату шага Ядра."""
        delta = self._OUTCOME_DELTA.get(result.outcome, 0.0)
        self.set_level(self._level + delta)

    # ------------------------------------------------------------------
    # Состояние

    @property
    def state(self) -> ResourceState:
        trend = self._level - self._prev_level
        return ResourceState(level=self._level, trend=trend)

    @property
    def level(self) -> float:
        return self._level

    @property
    def history(self) -> List[float]:
        return list(self._history)

    def __repr__(self) -> str:
        s = self.state
        return f"ResourceDriver(level={s.level:.3f}, mode={s.mode!r})"
