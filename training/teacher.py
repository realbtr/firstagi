"""
Шаг 7: InteractiveTeacher — машина состояний обучения модели.

Учитель следит за «жизнью» модели (уровень ресурса), адаптирует сложность,
спасает при «смерти» и контролирует гедонический цикл.

Состояния жизни:
    ALIVE   — resource > 0.30  → нормальное обучение
    AT_RISK — 0.15 < resource ≤ 0.30 → усилить подкрепление
    DYING   — 0.05 < resource ≤ 0.15 → переход к лёгким текстам
    DEAD    — resource ≤ 0.05  → сброс контекста + реанимация
"""

from __future__ import annotations

import sys
import os

# Ensure the project root is in sys.path for absolute imports
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple, TYPE_CHECKING

from core.learning import LearningSystem
from core.initiative import Proposal
from core.algorithm import StepResult, StepOutcome
from core.generalization import PeripheralToken
from training.corpus import TextCorpus

if TYPE_CHECKING:
    from core.app import CoreApplication


# ══════════════════════════════════════════════════════════════════════
# Состояние жизни
# ══════════════════════════════════════════════════════════════════════

class LifeState(Enum):
    ALIVE   = "alive"     # resource > 0.30
    AT_RISK = "at_risk"   # 0.15 < resource ≤ 0.30
    DYING   = "dying"     # 0.05 < resource ≤ 0.15
    DEAD    = "dead"      # resource ≤ 0.05


# ══════════════════════════════════════════════════════════════════════
# Отчёты
# ══════════════════════════════════════════════════════════════════════

@dataclass
class StepReport:
    """Отчёт об одном шаге обучения."""
    step_result: StepResult
    proposals: List[Proposal]
    initiative_hit: bool
    bonus: float
    life_state: LifeState
    resource_level: float


@dataclass
class TrainingReport:
    """Итоговый отчёт о сеансе обучения."""
    total_steps: int
    deaths: int
    stable_loops: int
    final_base_size: int
    final_resource: float
    hit_rate: float
    difficulty_reached: int
    attractor_count: int
    narrative: str


# ══════════════════════════════════════════════════════════════════════
# Интерактивный учитель
# ══════════════════════════════════════════════════════════════════════

class InteractiveTeacher:
    """
    Машина состояний учителя.

    Управляет потоком текстов, следит за ресурсом, адаптирует сложность,
    спасает при «смерти».
    """

    def __init__(
        self,
        system: LearningSystem,
        corpus: Optional[TextCorpus] = None,
        difficulty: int = 1,
    ) -> None:
        self.system = system
        self.corpus = corpus or TextCorpus()
        self.difficulty = max(1, min(4, difficulty))

        self.death_count: int = 0
        self.stable_loop_count: int = 0
        self.proposal_history: List[Tuple[Proposal, bool]] = []
        self._step_reports: List[StepReport] = []

        # Для отслеживания стабильных петель
        self._consecutive_completed: int = 0
        self._consecutive_refuted: int = 0
        self._recent_deaths: int = 0

    # ------------------------------------------------------------------

    def detect_life_state(self) -> LifeState:
        """Определить текущее состояние жизни модели по уровню ресурса."""
        level = self.system.resource.level
        if level <= 0.05:
            return LifeState.DEAD
        if level <= 0.15:
            return LifeState.DYING
        if level <= 0.30:
            return LifeState.AT_RISK
        return LifeState.ALIVE

    def rescue(self) -> None:
        """
        Реанимация: сброс контекста + подача лёгкого текста.
        Вызывается при DEAD.
        """
        self.death_count += 1
        self._recent_deaths += 1
        self.system.reset_context()
        # Небольшой прямой вброс ресурса, чтобы выйти из DEAD
        self.system.resource.recover(0.15)
        # Сбросить счётчики
        self._consecutive_completed = 0
        self._consecutive_refuted = 0

    def adjust_difficulty(self) -> None:
        """
        Адаптировать сложность:
          +1 если hit_rate > 0.6 и много стабильных петель
          -1 если много недавних смертей (> 2)
        Не выходит за пределы [1, 4].
        """
        hit_rate = self.system.initiative.hit_rate
        if hit_rate > 0.6 and self.stable_loop_count >= 3 and self.difficulty < 4:
            self.difficulty = min(4, self.difficulty + 1)
        elif self._recent_deaths >= 2 and self.difficulty > 1:
            self.difficulty = max(1, self.difficulty - 1)
            self._recent_deaths = 0

    def _make_text_driver(self) -> "TextDriver":
        from drivers.text_driver import TextDriver
        return TextDriver(driver_id="training_teacher")

    def step_token(self, token: PeripheralToken) -> StepReport:
        """
        Обработать один токен через систему.
        Собрать StepReport: результат + предложения + бонус + состояние.
        """
        # Предложения фиксируются внутри process_token (шаг 0 там)
        result = self.system.process_token(token)

        proposals = self.system.initiative.last_proposals
        bonus = 0.0
        initiative_hit = False

        # Проверить — угадала ли инициатива (по последнему evaluate)
        if proposals and result.matched_feature_id:
            for p in proposals:
                if p.next_feature_id == result.matched_feature_id:
                    initiative_hit = True
                    break

        # Отследить стабильные петли
        if result.outcome == StepOutcome.COMPLETED:
            self._consecutive_completed += 1
            self._consecutive_refuted = 0
            if self._consecutive_completed >= 3:
                self.stable_loop_count += 1
        elif result.outcome == StepOutcome.REFUTED:
            self._consecutive_refuted += 1
            self._consecutive_completed = 0
        else:
            pass  # CONFIRMED / EXPLORING не сбрасывают, но и не наращивают

        life_state = self.detect_life_state()
        report = StepReport(
            step_result=result,
            proposals=list(proposals),
            initiative_hit=initiative_hit,
            bonus=bonus,
            life_state=life_state,
            resource_level=self.system.resource.level,
        )
        self._step_reports.append(report)

        # Обработка DEAD
        if life_state == LifeState.DEAD:
            self.rescue()
            # Подать лёгкий текст
            rescue_text = self.corpus.easy_rescue()
            self.feed_text(rescue_text)

        return report

    def feed_text(self, text: str) -> List[StepReport]:
        """
        Подать текст как последовательность токенов через TextDriver.
        Возвращает список StepReport для каждого токена.
        """
        driver = self._make_text_driver()
        tokens = list(driver.produce(text))
        reports = []
        for token in tokens:
            r = self.step_token(token)
            reports.append(r)
        # Граница предложения
        self.system.reset_context()
        return reports

    def run(self, n_steps: int = 500) -> TrainingReport:
        """
        Запустить сеанс обучения на n_steps токенов.
        Автоматически подбирает тексты нужного уровня.
        """
        step_counter = 0

        while step_counter < n_steps:
            # Адаптировать сложность
            self.adjust_difficulty()

            # Выбрать текст
            life = self.detect_life_state()
            if life in (LifeState.DYING, LifeState.DEAD):
                text = self.corpus.easy_rescue()
            else:
                text = self.corpus.next_text(self.difficulty)

            driver = self._make_text_driver()
            tokens = list(driver.produce(text))

            for token in tokens:
                if step_counter >= n_steps:
                    break
                self.step_token(token)
                step_counter += 1

            self.system.reset_context()

        return self.report()

    def report(self) -> TrainingReport:
        """Собрать итоговый отчёт."""
        stats = self.system.stats()
        ps = stats.get("phase_space", {})
        attractor_count = ps.get("attractor_count", 0)

        # Попробовать получить нарратив, если есть NarrativeVoice
        narrative = ""
        try:
            from core.narrative import NarrativeVoice
            voice = NarrativeVoice(self.system)
            narrative = voice.state_report()
        except Exception:
            narrative = f"base_size={stats['base_size']}, steps={stats['steps']}"

        return TrainingReport(
            total_steps=stats["steps"],
            deaths=self.death_count,
            stable_loops=self.stable_loop_count,
            final_base_size=stats["base_size"],
            final_resource=round(self.system.resource.level, 4),
            hit_rate=round(self.system.initiative.hit_rate, 4),
            difficulty_reached=self.difficulty,
            attractor_count=attractor_count,
            narrative=narrative,
        )
