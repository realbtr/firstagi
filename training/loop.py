"""
Шаг 7: TrainingLoop — низкоуровневый цикл обработки токенов.

Используется InteractiveTeacher.run() внутри.
Также может использоваться напрямую для тестирования.
"""

from __future__ import annotations

import sys
import os

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from typing import List, Optional, TYPE_CHECKING

from core.learning import LearningSystem
from core.generalization import PeripheralToken
from training.teacher import InteractiveTeacher, StepReport

if TYPE_CHECKING:
    pass


class TrainingLoop:
    """
    Низкоуровневый цикл обучения.

    Принимает токены и прогоняет их через InteractiveTeacher.
    """

    def __init__(
        self,
        system: Optional[LearningSystem] = None,
        teacher: Optional[InteractiveTeacher] = None,
    ) -> None:
        if teacher is not None:
            self.teacher = teacher
            self.system = teacher.system
        else:
            self.system = system or LearningSystem()
            self.teacher = InteractiveTeacher(self.system)

        self._all_reports: List[StepReport] = []

    def run_tokens(
        self,
        tokens: List[PeripheralToken],
        verbose: bool = False,
    ) -> List[StepReport]:
        """
        Прогнать список токенов через учителя.
        Возвращает список StepReport.
        """
        reports = []
        for token in tokens:
            report = self.teacher.step_token(token)
            reports.append(report)
            if verbose:
                outcome = report.step_result.outcome.name
                res = round(report.resource_level, 3)
                hit = "HIT" if report.initiative_hit else "---"
                print(
                    f"[{outcome:12s}] res={res:.3f} {hit} "
                    f"life={report.life_state.value}"
                )
        self._all_reports.extend(reports)
        return reports

    def run_text(
        self,
        text: str,
        driver_id: str = "text",
        verbose: bool = False,
    ) -> List[StepReport]:
        """
        Прогнать текст через учителя.
        Текст токенизируется через TextDriver.
        """
        from drivers.text_driver import TextDriver
        driver = TextDriver(driver_id=driver_id)
        tokens = list(driver.produce(text))
        reports = self.run_tokens(tokens, verbose=verbose)
        self.system.reset_context()
        return reports

    def stats(self) -> dict:
        """Агрегированная статистика по всем пройденным шагам."""
        if not self._all_reports:
            return {
                "total_steps": 0,
                "deaths": 0,
                "hits": 0,
                "misses": 0,
                "hit_rate": 0.0,
            }
        hits = sum(1 for r in self._all_reports if r.initiative_hit)
        misses = len(self._all_reports) - hits
        return {
            "total_steps": len(self._all_reports),
            "deaths": self.teacher.death_count,
            "hits": hits,
            "misses": misses,
            "hit_rate": round(hits / len(self._all_reports), 4) if self._all_reports else 0.0,
            "system": self.system.stats(),
        }
