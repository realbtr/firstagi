"""
CapacityBudget — ограничение размера базы обобщений.

Использует TimescaleScheduler.eviction_candidates() для выбора кандидатов
на удаление: сначала OPERATIONAL Gen с низкой значимостью, затем MEDIUM.
LONG_TERM Gen (chain 1–2) никогда не вытесняются.

Подключение к GeneralizationBase:

    sched = TimescaleScheduler()
    budget = CapacityBudget(max_gens=6000, scheduler=sched)
    base = GeneralizationBase(evict_callback=budget.enforce)

Для urgency-буста подключить VitalityEngine:

    budget.attach_vitality(vitality_engine)

Шаг обновляется перед вызовом process_token():

    budget.set_step(current_step)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from .timescale import TimescaleScheduler

if TYPE_CHECKING:
    from .generalization import GeneralizationBase
    from .vitality import VitalityEngine


class CapacityBudget:
    """
    Бюджет ёмкости: поддерживает размер GeneralizationBase не выше max_gens.

    Параметры
    ----------
    max_gens : int
        Жёсткий предел числа Gen в базе (по умолчанию 6 000 ≈ 5^5–5^6).
    scheduler : TimescaleScheduler | None
        Планировщик тиров. Если не передан — создаётся по умолчанию.
    evict_batch : int
        Сколько «лишних» Gen удалять сверх необходимого минимума
        (амортизирует частые одиночные вставки).
    """

    def __init__(
        self,
        max_gens: int = 6_000,
        scheduler: Optional[TimescaleScheduler] = None,
        evict_batch: int = 10,
    ) -> None:
        self.max_gens = max_gens
        self._scheduler = scheduler or TimescaleScheduler()
        self._evict_batch = evict_batch
        self._vitality: Optional["VitalityEngine"] = None
        self._current_step: int = 0
        self._total_evicted: int = 0

    # ------------------------------------------------------------------
    # Подключение зависимостей

    def attach_vitality(self, vitality: "VitalityEngine") -> None:
        """Подключить VitalityEngine для urgency-буста при выборе кандидатов."""
        self._vitality = vitality

    def set_step(self, step: int) -> None:
        """Обновить текущий шаг (нужно для urgency-расчётов)."""
        self._current_step = step

    # ------------------------------------------------------------------
    # Основная операция

    def enforce(self, base: "GeneralizationBase") -> int:
        """
        Вытеснить лишние Gen если base.size() > max_gens.

        Вызывается как evict_callback из GeneralizationBase.add().
        Возвращает число удалённых Gen (0 если не требовалось).
        """
        if base.size() <= self.max_gens:
            return 0

        overflow = base.size() - self.max_gens
        n_to_evict = overflow + self._evict_batch

        candidates = self._scheduler.eviction_candidates(
            base,
            vitality=self._vitality,
            current_step=self._current_step,
            n=n_to_evict,
        )

        evicted = 0
        for gen in candidates:
            if base.size() <= self.max_gens:
                break
            if base.remove(gen.gen_id):
                evicted += 1

        self._total_evicted += evicted
        return evicted

    # ------------------------------------------------------------------
    # Информационные методы

    @property
    def total_evicted(self) -> int:
        """Суммарное число вытесненных Gen за всё время работы."""
        return self._total_evicted

    def is_at_capacity(self, base: "GeneralizationBase") -> bool:
        """True если база достигла лимита."""
        return base.size() >= self.max_gens

    def headroom(self, base: "GeneralizationBase") -> int:
        """Свободных мест до лимита (0 если лимит превышен)."""
        return max(0, self.max_gens - base.size())

    def stats(self, base: "GeneralizationBase") -> EvictionStats:
        """Текущая статистика бюджета."""
        return EvictionStats(
            max_gens=self.max_gens,
            current_gens=base.size(),
            headroom=self.headroom(base),
            total_evicted=self._total_evicted,
            is_at_capacity=self.is_at_capacity(base),
        )

    def __repr__(self) -> str:
        return (
            f"CapacityBudget(max={self.max_gens}, "
            f"evicted={self._total_evicted})"
        )


@dataclass
class EvictionStats:
    """Снимок состояния бюджета ёмкости."""
    max_gens:        int
    current_gens:    int
    headroom:        int
    total_evicted:   int
    is_at_capacity:  bool

    def __repr__(self) -> str:
        return (
            f"EvictionStats(current={self.current_gens}/{self.max_gens}, "
            f"headroom={self.headroom}, evicted={self.total_evicted})"
        )
