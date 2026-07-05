"""
Шаг 12: Витальность обобщений — внутренний ритм жизни гетерархии.

Каждый Gen в контексте имеет «сторожок»: он помнит, как часто его
обычно подтверждают, и тревожится, если прошло слишком много шагов
без подтверждения. Это создаёт автономный ритм внимания, независимый
от внешнего потока токенов.

Аналог: буддийские дхармы стучатся в ворота сознания — так и Gen,
накопившие историю активаций, сигнализируют: «проверь, актуален ли я».

Компоненты:
  VitalityRecord   — жизненный журнал одного Gen: история активаций,
                     среднеинтервальный ритм, срочность и витальность.
  VitalityEngine   — агрегатный трекер: record_activation / urgency /
                     knock_candidates / report.
  WakeUpRestorer   — восстановление контекста после паузы: пауза → уровень
                     обобщения → якорный Gen → загрузить в контекст.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .generalization import Generalization, GeneralizationBase
    from .context import ContextBuffer


# ──────────────────────────────────────────────────────────────────────
# 1. Запись жизненности одного Gen
# ──────────────────────────────────────────────────────────────────────

class VitalityRecord:
    """
    Жизненный журнал одного Gen.

    Хранит скользящее окно из последних (max_history-1) **интервалов** между
    активациями (не абсолютных шагов) плюс один абсолютный шаг последней
    активации (_last_step).  Это в разы экономнее при больших значениях step:

      Старый подход:  20 абсолютных шагов × 28 байт ≈ 560 байт/Gen
      Новый подход:   19 малых интервалов + 1 last_step ≈ те же 28 байт каждый,
                      но интервалы порядка 10–1000, а не 10^6 — меньше памяти
                      при сериализации и выгоднее для будущей компактизации.

    На основе истории вычисляет:
      • mean_interval  — средний ожидаемый интервал между активациями
      • urgency        — насколько Gen «опоздал» (elapsed / mean_interval)
      • vitality       — «живость» = значимость * exp-затухание при просрочке

    Угасание начинается только когда urgency > 1.0:
      vitality = significance * exp(-max(0, urgency - 1.0))
    Это даёт Gen «льготный период» в 1x mean_interval прежде чем он начнёт
    «стучаться в ворота».
    """

    _URGENCY_CAP: float = 10.0   # максимальная срочность (защита от outlier)

    def __init__(self, gen_id: str, max_history: int = 20) -> None:
        self.gen_id: str = gen_id
        # Храним интервалы (разности), а не абсолютные шаги.
        # max_history-1 интервалов соответствуют max_history точкам.
        self._gaps: deque = deque(maxlen=max(1, max_history - 1))
        self._last_step: Optional[int] = None
        self._total: int = 0

    # ------------------------------------------------------------------

    def record(self, step: int) -> None:
        """Зафиксировать активацию на шаге step."""
        if self._last_step is not None:
            gap = step - self._last_step
            if gap > 0:
                self._gaps.append(gap)
        self._last_step = step
        self._total += 1

    def last_step(self) -> Optional[int]:
        """Шаг последней активации, или None."""
        return self._last_step

    def mean_interval(self) -> Optional[float]:
        """
        Средний интервал между активациями (в шагах).
        None — если меньше одного интервала (менее двух точек).
        """
        if not self._gaps:
            return None
        return sum(self._gaps) / len(self._gaps)

    def urgency(self, current_step: int) -> float:
        """
        Срочность: насколько Gen «опоздал» относительно ожидаемого ритма.

          urgency = elapsed / mean_interval

        0.0  — Gen ещё не активировался (нет истории).
        1.0  — ровно вовремя.
        >1.0 — опоздал, пора проверить.
        Зажат в [0.0, URGENCY_CAP].
        """
        last = self._last_step
        if last is None:
            return 0.0
        elapsed = current_step - last
        interval = self.mean_interval()
        if interval is None or interval <= 0:
            # Только одна точка — нет данных об ожидаемом ритме.
            # Возвращаем нейтральную срочность вместо raw elapsed,
            # чтобы не перегружать knock_candidates при первом появлении.
            return min(float(elapsed), self._URGENCY_CAP)
        return min(elapsed / interval, self._URGENCY_CAP)

    def vitality(self, gen_significance: float, current_step: int) -> float:
        """
        Витальность = значимость Gen * затухание при просрочке.

        vitality = significance * exp(-max(0, urgency - 1.0))

        До urgency=1.0 затухания нет.
        При urgency=2.0: exp(-1) ≈ 0.37 × significance.
        При urgency=3.0: exp(-2) ≈ 0.14 × significance.
        """
        u = self.urgency(current_step)
        decay = math.exp(-max(0.0, u - 1.0))
        return gen_significance * decay

    def __repr__(self) -> str:
        return (
            f"VitalityRecord(gen={self.gen_id[:8]}, "
            f"n={self._total}, "
            f"last={self._last_step})"
        )


# ──────────────────────────────────────────────────────────────────────
# 2. Агрегатный трекер
# ──────────────────────────────────────────────────────────────────────

class VitalityEngine:
    """
    Агрегатный трекер витальности всей базы обобщений.

    Один VitalityRecord на gen_id, создаётся лениво при первой активации.
    """

    def __init__(self, window: int = 20) -> None:
        self._window: int = window
        self._records: Dict[str, VitalityRecord] = {}

    # ------------------------------------------------------------------

    def record_activation(self, gen_id: str, step: int) -> None:
        """Зафиксировать, что gen_id был активен на шаге step."""
        if gen_id not in self._records:
            self._records[gen_id] = VitalityRecord(gen_id, max_history=self._window)
        self._records[gen_id].record(step)

    def gap_for(self, gen_id: str, current_step: int) -> int:
        """
        Сколько шагов прошло с последней активации gen_id.
        Возвращает 0 если gen_id никогда не активировался.
        """
        rec = self._records.get(gen_id)
        if rec is None or rec.last_step() is None:
            return 0
        return current_step - rec.last_step()

    def urgency(self, gen_id: str, current_step: int) -> float:
        """
        Срочность для конкретного gen_id.
        0.0 если gen_id никогда не активировался (нет записи).
        """
        rec = self._records.get(gen_id)
        if rec is None:
            return 0.0
        return rec.urgency(current_step)

    def knock_candidates(
        self,
        gen_ids: List[str],
        base: "GeneralizationBase",
        current_step: int,
        threshold: float = 2.0,
    ) -> List[Tuple[str, float]]:
        """
        Найти Gen, которые «стучатся» (urgency >= threshold).

        Исключает:
          • Gen без записи (никогда не активировались — они не «опоздали»)
          • Gen с urgency < threshold

        Возвращает [(gen_id, urgency), ...] sorted descending urgency.
        """
        result: List[Tuple[str, float]] = []
        for gid in gen_ids:
            if gid not in self._records:
                continue
            u = self.urgency(gid, current_step)
            if u >= threshold:
                result.append((gid, u))
        result.sort(key=lambda x: x[1], reverse=True)
        return result

    def report(
        self,
        gen_ids: List[str],
        base: "GeneralizationBase",
        current_step: int,
    ) -> List[Dict[str, Any]]:
        """
        Полный отчёт о витальности для набора gen_ids.

        Каждый элемент:
            gen_id        str
            label         str
            chain_len     int
            significance  float
            urgency       float
            vitality      float
            mean_interval Optional[float]
            last_step     Optional[int]

        Сортировка: vitality ascending (самые «угасающие» — первые).
        Gen без записи включаются с urgency=0, vitality=significance.
        """
        rows: List[Dict[str, Any]] = []
        for gid in gen_ids:
            gen = base.get(gid)
            if gen is None:
                continue
            rec = self._records.get(gid)
            sig = gen.significance
            if rec is not None:
                u   = rec.urgency(current_step)
                v   = rec.vitality(sig, current_step)
                mi  = rec.mean_interval()
                ls  = rec.last_step()
            else:
                u, v, mi, ls = 0.0, sig, None, None
            rows.append({
                "gen_id":        gid,
                "label":         gen.label or gid[:8],
                "chain_len":     len(gen.feature_chain),
                "significance":  round(sig, 4),
                "urgency":       round(u,   4),
                "vitality":      round(v,   4),
                "mean_interval": round(mi,  4) if mi is not None else None,
                "last_step":     ls,
            })
        rows.sort(key=lambda r: r["vitality"])
        return rows

    def stats(self) -> Dict[str, Any]:
        """
        Сводная статистика по всем записям.

        Для max_step берём максимальный last_step — «эталонное текущее время»
        для усреднения срочности (не требует аргумента current_step извне).
        """
        if not self._records:
            return {
                "tracked_gens":   0,
                "avg_urgency":    0.0,
                "critical_count": 0,
            }
        max_step = max(
            (rec.last_step() or 0) for rec in self._records.values()
        )
        urgencies = [rec.urgency(max_step) for rec in self._records.values()]
        return {
            "tracked_gens":   len(self._records),
            "avg_urgency":    round(sum(urgencies) / len(urgencies), 4),
            "critical_count": sum(1 for u in urgencies if u >= 2.0),
        }


# ──────────────────────────────────────────────────────────────────────
# 3. Восстановитель контекста после паузы
# ──────────────────────────────────────────────────────────────────────

# gap (шагов) → минимальная длина цепочки якоря
# Чем больше пауза — тем более общий (короткий) Gen нужен
_GAP_THRESHOLDS: List[Tuple[int, int]] = [
    (5,  5),   # < 5  шагов: ищем конкретный Gen (L5+)
    (10, 4),   # < 10 шагов: L4+
    (20, 3),   # < 20 шагов: L3+
    (50, 2),   # < 50 шагов: L2+
               # ≥ 50 шагов: L1+ (самый общий)
]


class WakeUpRestorer:
    """
    Восстанавливает контекст после паузы внимания.

    Философия: чем дольше система «не смотрела» на некий паттерн,
    тем с более высокого уровня абстракции нужно начинать — потому что
    только самые устойчивые (короткие, много раз подтверждённые) Gen
    точно ещё актуальны. Детали могли поменяться.

    gap (шагов) → min_chain_len якорного Gen:
        < 5   → 5  (конкретный, детальный)
        < 10  → 4
        < 20  → 3
        < 50  → 2
        ≥ 50  → 1  (самый общий)
    """

    def __init__(self, min_significance: float = 0.1) -> None:
        self.min_significance: float = min_significance
        self._restore_count: int = 0

    @property
    def restore_count(self) -> int:
        return self._restore_count

    def min_chain_len_for_gap(self, step_gap: int) -> int:
        """Перевести gap (шаги) → минимальная длина цепочки якоря."""
        for threshold, chain_len in _GAP_THRESHOLDS:
            if step_gap < threshold:
                return chain_len
        return 1

    def find_anchor(
        self,
        base: "GeneralizationBase",
        min_chain_len: int,
    ) -> Optional["Generalization"]:
        """
        Найти наиболее значимый Gen с цепочкой ≥ min_chain_len.

        Предпочитает мета-Gen (метка meta_*), потом сортирует по значимости.
        Возвращает None если нет подходящих кандидатов.
        """
        candidates = [
            g for g in base.all()
            if len(g.feature_chain) >= min_chain_len
            and g.significance >= self.min_significance
        ]
        if not candidates:
            # Fallback: снижаем планку до любого значимого Gen
            candidates = [g for g in base.all() if g.significance >= self.min_significance]
        if not candidates:
            return None
        # Предпочесть мета-Gen
        candidates.sort(
            key=lambda g: (
                1 if (g.label and g.label.startswith("meta_")) else 0,
                g.significance,
            ),
            reverse=True,
        )
        return candidates[0]

    def restore(
        self,
        base: "GeneralizationBase",
        context: "ContextBuffer",
        step_gap: int,
    ) -> Optional[str]:
        """
        Загрузить якорный Gen в контекст.

        Алгоритм:
          1. gap → min_chain_len
          2. Найти лучший якорь
          3. Если ещё не в активном контексте — добавить
          4. Вернуть gen_id или None

        Идемпотентно: если якорь уже активен — ничего не делает.
        """
        min_len = self.min_chain_len_for_gap(step_gap)
        anchor  = self.find_anchor(base, min_len)
        if anchor is None:
            return None
        already_active = anchor.gen_id in context.active_gen_ids()
        if not already_active:
            context.add_active(anchor.gen_id)
            self._restore_count += 1
        return anchor.gen_id
