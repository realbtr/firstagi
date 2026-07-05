"""
TimescaleScheduler — явные пулы по временны́м масштабам.

Классифицирует Gen по длине цепочки признаков на три уровня:

    LONG_TERM   (chain 1-2) — трансцендентные, фундамент мировоззрения
    MEDIUM      (chain 3-4) — стратегические, текущая задача
    OPERATIONAL (chain 5+)  — оперативные, момент-к-моменту

Каждый уровень имеет свой «вес удержания» (retention_weight): OPERATIONAL
Gen стареют быстрее всего и первыми попадают в кандидаты на удаление.

Основные операции:
    classify(gen)               → Tier
    depth_profile(base)         → Dict[Tier, TierStats]
    eviction_candidates(...)    → List[Generalization]  (для CapacityBudget)
    tick(base, vitality, step)  → TickResult            (обновить внутр. статистику)

Использование:
    sched = TimescaleScheduler()
    profile = sched.depth_profile(app.system.base)
    for tier, stats in profile.items():
        print(tier, stats.count, stats.avg_sig)

    candidates = sched.eviction_candidates(
        app.system.base, app.system.vitality, current_step=10000, n=100
    )
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .generalization import Generalization, GeneralizationBase
    from .vitality import VitalityEngine


# ══════════════════════════════════════════════════════════════════════
# Тиры (уровни временны́х масштабов)
# ══════════════════════════════════════════════════════════════════════

class Tier(str, Enum):
    LONG_TERM   = "LONG_TERM"    # chain 1-2: трансцендентные
    MEDIUM      = "MEDIUM"       # chain 3-4: стратегические
    OPERATIONAL = "OPERATIONAL"  # chain 5+:  оперативные


# Граничные значения длины цепочки для каждого тира
_TIER_MAX_CHAIN: Dict[Tier, int] = {
    Tier.LONG_TERM:   2,
    Tier.MEDIUM:      4,
    Tier.OPERATIONAL: 10_000,   # без ограничения сверху
}

# «Вес удержания» [0..1]: 1.0 = никогда не удалять, 0.0 = кандидат всегда
_RETENTION_WEIGHT: Dict[Tier, float] = {
    Tier.LONG_TERM:   1.00,
    Tier.MEDIUM:      0.50,
    Tier.OPERATIONAL: 0.00,
}

# Метка chain_length=0 (мета-Gen без цепочки) — считаем LONG_TERM
_EMPTY_CHAIN_TIER = Tier.LONG_TERM


# ══════════════════════════════════════════════════════════════════════
# Статистика по тиру
# ══════════════════════════════════════════════════════════════════════

@dataclass
class TierStats:
    """
    Сводная статистика одного тира за последний tick().

    count       — число Gen в тире
    avg_sig     — средняя значимость
    avg_vitality — средний urgency (0 = не опоздал, >1 = просроченный)
    total_new   — прирост Gen за последний tick (если tick вызывался ранее)
    """
    tier:         Tier
    count:        int   = 0
    avg_sig:      float = 0.0
    avg_vitality: float = 0.0   # среднее urgency текущего шага
    total_new:    int   = 0     # прирост с прошлого tick

    def __repr__(self) -> str:
        return (
            f"TierStats({self.tier.value}: "
            f"n={self.count}, sig={self.avg_sig:.3f}, "
            f"urg={self.avg_vitality:.3f}, +{self.total_new})"
        )


# ══════════════════════════════════════════════════════════════════════
# Результат одного tick()
# ══════════════════════════════════════════════════════════════════════

@dataclass
class TickResult:
    """Результат TimescaleScheduler.tick()."""
    step:       int
    profile:    Dict[Tier, TierStats]
    total_gens: int

    @property
    def long_term_count(self) -> int:
        return self.profile[Tier.LONG_TERM].count

    @property
    def medium_count(self) -> int:
        return self.profile[Tier.MEDIUM].count

    @property
    def operational_count(self) -> int:
        return self.profile[Tier.OPERATIONAL].count

    def summary(self) -> str:
        lines = [f"  step={self.step}  total={self.total_gens}"]
        for tier in Tier:
            s = self.profile[tier]
            lines.append(
                f"  {tier.value:<12}  n={s.count:>6}  "
                f"sig={s.avg_sig:.3f}  urg={s.avg_vitality:.3f}  +{s.total_new}"
            )
        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════
# TimescaleScheduler
# ══════════════════════════════════════════════════════════════════════

class TimescaleScheduler:
    """
    Управляет тремя пулами Gen по временны́м масштабам.

    Параметры
    ----------
    long_term_max_chain : int
        Максимальная длина цепочки для LONG_TERM (по умолчанию 2).
    medium_max_chain : int
        Максимальная длина цепочки для MEDIUM (по умолчанию 4).
        Всё что длиннее — OPERATIONAL.
    """

    def __init__(
        self,
        long_term_max_chain: int = 2,
        medium_max_chain:    int = 4,
    ) -> None:
        self._lt_max  = long_term_max_chain
        self._med_max = medium_max_chain

        # Кэш: gen_id → tier (обновляется при tick/classify)
        self._tier_cache: Dict[str, Tier] = {}

        # История tick-профилей (последние N)
        self._history: List[TickResult] = []
        self._prev_counts: Dict[Tier, int] = {t: 0 for t in Tier}

    # ------------------------------------------------------------------
    # Классификация

    def classify(self, gen: "Generalization") -> Tier:
        """Определить тир Gen по длине его feature_chain."""
        chain_len = len(gen.feature_chain) if gen.feature_chain else 0
        if chain_len == 0 or chain_len <= self._lt_max:
            return Tier.LONG_TERM
        if chain_len <= self._med_max:
            return Tier.MEDIUM
        return Tier.OPERATIONAL

    def tier_of(self, gen_id: str) -> Optional[Tier]:
        """Вернуть тир из кэша (None если Gen ещё не классифицирован)."""
        return self._tier_cache.get(gen_id)

    def retention_weight(self, gen: "Generalization") -> float:
        """Вес удержания Gen [0..1]: чем ниже, тем скорее кандидат."""
        return _RETENTION_WEIGHT[self.classify(gen)]

    # ------------------------------------------------------------------
    # Профиль глубины

    def depth_profile(
        self,
        base: "GeneralizationBase",
        vitality: Optional["VitalityEngine"] = None,
        current_step: int = 0,
    ) -> Dict[Tier, TierStats]:
        """
        Подсчитать сводную статистику по каждому тиру.

        Если vitality передан, включает среднее urgency.
        """
        counts:     Dict[Tier, int]   = {t: 0   for t in Tier}
        sig_sum:    Dict[Tier, float] = {t: 0.0 for t in Tier}
        urg_sum:    Dict[Tier, float] = {t: 0.0 for t in Tier}

        for gen in base.all():
            tier = self.classify(gen)
            self._tier_cache[gen.gen_id] = tier
            counts[tier]  += 1
            sig_sum[tier] += gen.significance

            if vitality is not None:
                urg = vitality.urgency(gen.gen_id, current_step)
                urg_sum[tier] += urg

        result: Dict[Tier, TierStats] = {}
        for tier in Tier:
            n = counts[tier]
            result[tier] = TierStats(
                tier=tier,
                count=n,
                avg_sig=round(sig_sum[tier] / n, 4) if n else 0.0,
                avg_vitality=round(urg_sum[tier] / n, 4) if n else 0.0,
            )
        return result

    # ------------------------------------------------------------------
    # tick — обновить профиль и историю

    def tick(
        self,
        base:         "GeneralizationBase",
        vitality:     Optional["VitalityEngine"] = None,
        current_step: int = 0,
    ) -> TickResult:
        """
        Один шаг расписания:
          1. Пересчитать depth_profile
          2. Вычислить прирост Gen по тирам с прошлого tick
          3. Сохранить в историю

        Возвращает TickResult.
        """
        profile = self.depth_profile(base, vitality, current_step)

        # Прирост по тирам
        for tier in Tier:
            profile[tier].total_new = (
                profile[tier].count - self._prev_counts[tier]
            )
        self._prev_counts = {t: profile[t].count for t in Tier}

        result = TickResult(
            step=current_step,
            profile=profile,
            total_gens=sum(s.count for s in profile.values()),
        )
        self._history.append(result)
        return result

    # ------------------------------------------------------------------
    # Кандидаты на удаление (для CapacityBudget)

    def eviction_candidates(
        self,
        base:         "GeneralizationBase",
        vitality:     Optional["VitalityEngine"] = None,
        current_step: int = 0,
        n:            int = 100,
        min_sig:      float = 0.0,
    ) -> List["Generalization"]:
        """
        Вернуть топ-N Gen — наиболее «расходные» кандидаты к удалению.

        Score = (1 - retention_weight) × (1 - significance)
        При одинаковом score OPERATIONAL предпочтительнее MEDIUM.

        Параметры
        ----------
        min_sig : float
            Исключить Gen с significance < min_sig из кандидатов
            (защищает молодые Gen с sig=0 от немедленного удаления).
        """
        scored: List[tuple] = []

        for gen in base.all():
            if gen.significance < min_sig:
                continue
            rw    = self.retention_weight(gen)
            if rw >= 1.0:      # LONG_TERM — никогда не удаляем
                continue
            score = (1.0 - rw) * (1.0 - gen.significance)

            # urgency-буст: очень просроченные Gen менее ценны
            if vitality is not None:
                urg = vitality.urgency(gen.gen_id, current_step)
                # urgency > 2.0 → "давно не использовался"
                score = score * (1.0 + max(0.0, urg - 2.0) * 0.1)

            scored.append((score, gen))

        # Сортировка: высокий score = первый кандидат
        scored.sort(key=lambda x: x[0], reverse=True)
        return [g for _, g in scored[:n]]

    # ------------------------------------------------------------------
    # Вспомогательные

    @property
    def history(self) -> List[TickResult]:
        """История всех TickResult (один на вызов tick())."""
        return list(self._history)

    def last_tick(self) -> Optional[TickResult]:
        """Последний TickResult или None если tick() ещё не вызывался."""
        return self._history[-1] if self._history else None

    def tier_sizes(self, base: "GeneralizationBase") -> Dict[str, int]:
        """Быстрый подсчёт размеров тиров без статистики."""
        counts: Dict[str, int] = {t.value: 0 for t in Tier}
        for gen in base.all():
            counts[self.classify(gen).value] += 1
        return counts

    def __repr__(self) -> str:
        last = self.last_tick()
        if last is None:
            return "TimescaleScheduler(no ticks)"
        return (
            f"TimescaleScheduler("
            f"LT={last.long_term_count}, "
            f"M={last.medium_count}, "
            f"OP={last.operational_count}, "
            f"step={last.step})"
        )
