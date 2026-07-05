"""
Шаг 10: Инспектор обобщений и предиктивный симулятор.

GeneralizationInspector — read-only срез текущего состояния базы:
  top_gens()    — топ Gen по значимости
  weak_gens()   — слабоподтверждённые Gen (точки роста)
  readiness()   — готовность системы к усложнению [0..1]
  snapshot()    — полный срез состояния

PredictiveSimulator — «сухой прогон» без мутации состояния:
  simulate(text) — что произошло бы, если бы мы обучили этот текст

Не изменяют состояние LearningSystem.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .learning import LearningSystem
    from .generalization import Generalization


# ══════════════════════════════════════════════════════════════════════
# Результат симуляции
# ══════════════════════════════════════════════════════════════════════

@dataclass
class SimulationResult:
    """Результат предиктивного прогона (без мутации состояния)."""
    outcomes: List[str]              # CONFIRMED / COMPLETED / REFUTED / EXPLORING
    confirmed_features: List[str]    # feature_id подтверждённых признаков
    refuted_count: int               # количество опровержений
    match_rate: float                # (confirmed+completed) / total
    would_create_gens: int           # сколько новых Gen было бы создано


# ══════════════════════════════════════════════════════════════════════
# Инспектор
# ══════════════════════════════════════════════════════════════════════

class GeneralizationInspector:
    """
    Read-only инспектор базы обобщений.

    Не изменяет состояние системы. Используется CurriculumAgent
    и отладчиком для понимания текущего уровня обученности.
    """

    def __init__(self, system: "LearningSystem") -> None:
        self._system = system

    @property
    def system(self) -> "LearningSystem":
        return self._system

    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, Any]:
        """Полный срез состояния системы."""
        stats = self._system.stats()
        proposals = [
            {
                "gen_id":     p.gen_id[:8],
                "feature":    p.next_feature_id,
                "confidence": round(p.confidence, 4),
                "label":      p.label,
            }
            for p in self._system.last_proposals()
        ]
        return {
            "stats":       stats,
            "top_gens":    self.top_gens(10),
            "weak_gens":   self.weak_gens(),
            "proposals":   proposals,
            "active_gens": len(self._system.engine.context.active_gen_ids()),
            "readiness":   round(self.readiness(), 4),
        }

    def top_gens(self, n: int = 10) -> List[Dict[str, Any]]:
        """Топ-N обобщений по значимости (success / total)."""
        gens = self._system.base.rank(min_significance=0.0)[:n]
        return [self._to_dict(g) for g in gens]

    def weak_gens(
        self,
        max_significance: float = 0.4,
        min_attempts: int = 1,
    ) -> List[Dict[str, Any]]:
        """
        Слабоподтверждённые обобщения — точки роста.
        Именно их стоит подкреплять при следующих обучающих итерациях.
        """
        result = []
        for g in self._system.base.all():
            total = g.success_count + g.stop_count
            if total >= min_attempts and g.significance <= max_significance:
                result.append(self._to_dict(g))
        return sorted(result, key=lambda d: d["significance"])

    def gens_by_chain_len(
        self,
        min_len: int = 1,
        max_len: int = 999,
    ) -> List[Dict[str, Any]]:
        """Обобщения с цепочкой заданной длины."""
        result = [
            self._to_dict(g)
            for g in self._system.base.all()
            if min_len <= g.generalization_level <= max_len
        ]
        return sorted(result, key=lambda d: -d["significance"])

    def readiness(self) -> float:
        """
        Готовность системы к более сложному материалу [0..1].

        Среднее значимости топ-5 Gen.
        0.0 = система «пустая», 1.0 = уверенно обобщила известное.
        """
        top = self._system.base.rank(min_significance=0.0)[:5]
        if not top:
            return 0.0
        return sum(g.significance for g in top) / len(top)

    # ------------------------------------------------------------------

    def _to_dict(self, g: "Generalization") -> Dict[str, Any]:
        return {
            "gen_id":        g.gen_id[:8],
            "full_id":       g.gen_id,
            "label":         g.label or f"L{g.generalization_level}",
            "chain_len":     g.generalization_level,
            "success":       g.success_count,
            "stop":          g.stop_count,
            "significance":  round(g.significance, 4),
            "feature_chain": list(g.feature_chain),
        }


# ══════════════════════════════════════════════════════════════════════
# Предиктивный симулятор
# ══════════════════════════════════════════════════════════════════════

class PredictiveSimulator:
    """
    Предиктивный симулятор: «сухой прогон» без мутации состояния.

    Копирует весь движок в shadow-объекты и прогоняет текст через них.
    Исходное состояние LearningSystem не изменяется.

    text_driver — ссылка на обучающий TextDriver. Если передан, симулятор
    использует его текущий vocab (копию), чтобы feature-векторы совпадали
    с теми, что создавались при обучении. Без него vocab строится заново
    из текста предсказания — это корректно только если vocab не менялся.
    """

    def __init__(
        self,
        system:      "LearningSystem",
        text_driver: Any = None,
    ) -> None:
        self._system      = system
        self._text_driver = text_driver   # PeripheralDriver или совместимый объект

    def simulate(self, text: str) -> SimulationResult:
        """
        Прогнать текст через изолированную копию движка.

        Возвращает SimulationResult без изменения состояния.
        Deepcopy охватывает base, context и features — полная изоляция.
        """
        from .algorithm import AttractorEngine
        from drivers.text_driver import TextDriver

        # Полная изолированная копия — мутации не вытекут наружу
        shadow_base     = copy.deepcopy(self._system.base)
        shadow_features = copy.deepcopy(self._system.engine._features)
        # Намеренно используем пустой контекст: предсказание должно работать
        # с «чистого листа» (не из середины обучающей последовательности).
        # Иначе любая незакрытая цепочка в текущем контексте вызовет REFUTED.

        shadow_engine = AttractorEngine(
            shadow_base,
            feature_tolerance=self._system.engine.feature_tolerance,
        )
        shadow_engine._features = shadow_features
        # context остаётся пустым (по умолчанию в AttractorEngine.__init__)

        # Токенизировать текст с тем же vocab что при обучении
        driver = TextDriver("_sim_")
        if self._text_driver is not None and getattr(self._text_driver, "_vocab", None):
            driver._vocab = dict(self._text_driver._vocab)   # snapshot текущего vocab
        tokens = list(driver.produce(text=text))

        outcomes: List[str] = []
        confirmed_features: List[str] = []
        refuted_count   = 0
        would_create    = 0

        for token in tokens:
            result = shadow_engine.step(token)
            outcomes.append(result.outcome.name)
            if result.matched_feature_id:
                confirmed_features.append(result.matched_feature_id)
            if result.outcome.name == "REFUTED":
                refuted_count += 1
                if result.new_gen_id:
                    would_create += 1

        total = max(len(outcomes), 1)
        match_rate = (
            outcomes.count("CONFIRMED") + outcomes.count("COMPLETED")
        ) / total

        return SimulationResult(
            outcomes=outcomes,
            confirmed_features=confirmed_features,
            refuted_count=refuted_count,
            match_rate=round(match_rate, 4),
            would_create_gens=would_create,
        )
