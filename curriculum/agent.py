"""
Шаг 10: CurriculumAgent — автоматизированный агент обучения
с убывающей стабильностью учебной среды.

Алгоритм:
  1. assess_readiness()    → насколько система готова к усложнению
  2. select_texts(s)       → выбрать тексты под текущий уровень сложности
  3. learn each text       → получить match_rate feedback
  4. apply schedule        → уменьшить стабильность если система достаточно освоилась
  5. Повторить

Стабильность убывает: HIGH (повторяем знакомое) → LOW (новизна) → CHAOTIC (хаос).

Из концепции:
  «Убывающая стабильность» = контролируемый анниллинг предсказуемости.
  Система должна сначала консолидировать базовые паттерны,
  а затем сталкиваться с вариациями и исключениями.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.app import CoreApplication
    from core.inspector import GeneralizationInspector
    from core.driver_control import DriverController


# ══════════════════════════════════════════════════════════════════════
# График стабильности
# ══════════════════════════════════════════════════════════════════════

@dataclass
class StabilitySchedule:
    """
    График убывания стабильности учебной среды.

    initial   — начальная стабильность [0..1] (1.0 = повторяем знакомое)
    final     — минимальная стабильность (0.1 = почти случайный выбор)
    decay     — множитель убывания за один готовый шаг (0.95 = медленно)
    threshold — порог readiness для перехода к следующему уровню
    """
    initial:   float = 1.0
    final:     float = 0.1
    decay:     float = 0.95
    threshold: float = 0.5

    def apply(self, current: float, readiness: float) -> float:
        """Вернуть новую стабильность: уменьшить если система готова."""
        if readiness >= self.threshold:
            return max(self.final, current * self.decay)
        return current


# ══════════════════════════════════════════════════════════════════════
# Результат одного шага
# ══════════════════════════════════════════════════════════════════════

@dataclass
class CurriculumStep:
    """Результат одного шага CurriculumAgent."""
    step_n:             int
    stability:          float
    readiness:          float
    texts_fed:          List[str]
    match_rates:        List[float]
    new_stability:      float
    total_gens:         int
    new_gens_this_step: int

    @property
    def avg_match_rate(self) -> float:
        if not self.match_rates:
            return 0.0
        return sum(self.match_rates) / len(self.match_rates)

    @property
    def stability_decreased(self) -> bool:
        return self.new_stability < self.stability


# ══════════════════════════════════════════════════════════════════════
# Агент
# ══════════════════════════════════════════════════════════════════════

class CurriculumAgent:
    """
    Агент автоматического обучения с убывающей стабильностью.

    Управляет выбором учебных материалов исходя из текущего состояния
    системы и заданного графика сложности. Обратная связь через
    match_rate каждого текста формирует «историю знакомости» — основу
    для умного выбора следующей порции.

    Использование:
        agent = CurriculumAgent(inspector, controller, app, corpus=texts)
        results = agent.run(50)
        for step in results:
            print(f"s={step.stability:.2f} r={step.readiness:.2f} "
                  f"match={step.avg_match_rate:.2f} gens={step.total_gens}")
    """

    def __init__(
        self,
        inspector:      "GeneralizationInspector",
        controller:     "DriverController",
        app:            "CoreApplication",
        corpus:         Optional[List[str]] = None,
        schedule:       Optional[StabilitySchedule] = None,
        texts_per_step: int = 3,
        seed:           Optional[int] = None,
    ) -> None:
        self.inspector      = inspector
        self.controller     = controller
        self.app            = app
        self.corpus         = list(corpus) if corpus else []
        self.schedule       = schedule or StabilitySchedule()
        self.stability      = self.schedule.initial
        self.texts_per_step = texts_per_step
        self._rng           = random.Random(seed)
        self._history:      List[CurriculumStep] = []
        # text → список match_rate из прошлых подач (для оценки знакомости)
        self._text_stats:   Dict[str, List[float]] = {}

    # ------------------------------------------------------------------
    # Оценка готовности

    def assess_readiness(self) -> float:
        """
        Готовность системы к усложнению [0..1].

        70% — readiness из Inspector (значимость топ-5 Gen).
        30% — средний match_rate трёх последних шагов (если есть).
        """
        base_r = self.inspector.readiness()
        if len(self._history) >= 3:
            recent = self._history[-3:]
            avg_recent = sum(s.avg_match_rate for s in recent) / len(recent)
            return 0.7 * base_r + 0.3 * avg_recent
        return base_r

    # ------------------------------------------------------------------
    # Выбор текстов

    def _text_familiarity(self, text: str) -> float:
        """Средний match_rate текста в истории. 0.5 если не видели."""
        rates = self._text_stats.get(text, [])
        return sum(rates) / len(rates) if rates else 0.5

    def select_texts(
        self,
        stability: float,
        n: Optional[int] = None,
    ) -> List[str]:
        """
        Выбрать тексты из корпуса под текущий уровень стабильности.

        stability > 0.7  → знакомые тексты (высокий familiarity → консолидация)
        stability 0.3..0.7 → смешанные (disambiguation)
        stability < 0.3  → малознакомые (новизна → новые Gen)
        """
        n = n if n is not None else self.texts_per_step
        if not self.corpus:
            return []

        scored = [(t, self._text_familiarity(t)) for t in self.corpus]

        if stability > 0.7:
            # Знакомые: наибольший familiarity первым
            scored.sort(key=lambda x: -x[1])
        elif stability < 0.3:
            # Незнакомые: наименьший familiarity первым
            scored.sort(key=lambda x: x[1])
        else:
            # Смешанные: случайный порядок
            self._rng.shuffle(scored)

        candidates = [t for t, _ in scored]
        return self._rng.sample(candidates, min(n, len(candidates)))

    # ------------------------------------------------------------------
    # Основной шаг

    def step(self) -> CurriculumStep:
        """
        Один шаг агента:
          1. Оценить readiness.
          2. Выбрать тексты под текущую стабильность.
          3. Обучить систему (app.learn для каждого текста).
          4. Обновить стабильность через schedule.
          5. Вернуть CurriculumStep.
        """
        gens_before = self.app.system.base.size()
        readiness   = self.assess_readiness()
        texts       = self.select_texts(self.stability)

        match_rates: List[float] = []
        for text in texts:
            result = self.app.learn(text)
            mr = result.get("match_rate", 0.0)
            match_rates.append(mr)
            if text not in self._text_stats:
                self._text_stats[text] = []
            self._text_stats[text].append(mr)

        gens_after    = self.app.system.base.size()
        old_stability = self.stability
        self.stability = self.schedule.apply(self.stability, readiness)

        step_result = CurriculumStep(
            step_n             = len(self._history),
            stability          = old_stability,
            readiness          = round(readiness, 4),
            texts_fed          = texts,
            match_rates        = [round(r, 4) for r in match_rates],
            new_stability      = round(self.stability, 4),
            total_gens         = gens_after,
            new_gens_this_step = gens_after - gens_before,
        )
        self._history.append(step_result)
        return step_result

    def run(self, n_steps: int) -> List[CurriculumStep]:
        """Запустить n_steps шагов подряд."""
        return [self.step() for _ in range(n_steps)]

    # ------------------------------------------------------------------
    # История и статистика

    @property
    def history(self) -> List[CurriculumStep]:
        return list(self._history)

    def stats(self) -> Dict[str, Any]:
        """Сводная статистика агента."""
        if not self._history:
            return {
                "steps":          0,
                "stability":      round(self.stability, 4),
                "corpus_size":    len(self.corpus),
                "avg_match_rate": 0.0,
            }
        all_rates = [r for s in self._history for r in s.match_rates]
        return {
            "steps":          len(self._history),
            "stability":      round(self.stability, 4),
            "corpus_size":    len(self.corpus),
            "avg_match_rate": round(
                sum(all_rates) / max(len(all_rates), 1), 4
            ),
            "total_gens":     self._history[-1].total_gens,
        }

    def reset(self) -> None:
        """Сбросить историю и вернуться к начальной стабильности."""
        self.stability   = self.schedule.initial
        self._history    = []
        self._text_stats = {}
