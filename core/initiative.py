"""
Шаг 7: Двигатель инициативы — модель предлагает следующий признак ДО его прихода.

Принцип: инициатива = способность предсказывать следующий токен из активного
контекста. Модель «делает ставку» на конкретный feature_id; если угадала —
получает бонусную награду. Если нет — нет штрафа (ставка была осознанной).

Из концепции:
  «Инициатива = predict(next_feature) на основе активного контекста →
   предложить учителю»
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .context import ContextBuffer
    from .generalization import GeneralizationBase
    from .hedonic import HedonicAdapter
    from .resource import ResourceDriver


# ══════════════════════════════════════════════════════════════════════
# Предложение (ставка на следующий признак)
# ══════════════════════════════════════════════════════════════════════

@dataclass
class Proposal:
    """
    Предложение модели: ожидаемый следующий признак.

    Атрибуты:
        gen_id          — Gen, из цепочки которого взято предсказание
        next_feature_id — ожидаемый feature_id
        confidence      — уверенность (значимость * новизна)
        label           — человекочитаемая метка (опционально)
    """
    gen_id: str
    next_feature_id: str
    confidence: float
    label: str = ""


# ══════════════════════════════════════════════════════════════════════
# Двигатель инициативы
# ══════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class OperationProposal:
    instance_id: str
    channel_id: str
    seq: int
    cue_gen_id: str
    goal_gen_id: str
    command_address: str
    operation_gen_id: str
    confidence: float
    contributor_gen_ids: tuple
    context_positions: tuple
    tick: int
    applicability_revision: int = 0


class InitiativeEngine:
    """
    Двигатель инициативы.

    При каждом шаге (до прихода токена) — строит список предложений:
    какой следующий признак ожидается из активных Gen.

    После прихода токена — оценивает, попал ли прогноз (evaluate).
    """

    # Бонусные множители по рангу предложения
    RANK_BONUSES = [5.0, 2.5, 1.0]   # rank 1, 2, 3

    def __init__(self, resource: Optional["ResourceDriver"] = None) -> None:
        self._resource = resource
        self._last_proposals: List[Proposal] = []
        self._total_proposals: int = 0
        self._total_hits: int = 0
        self._total_misses: int = 0

    # ------------------------------------------------------------------

    def choose_operation(self, groups, goal_matches, hedonic):
        """All linked contributors before ranking; no top-3 or ID tie-break."""
        import math
        scores = {}
        for operation_id, contributors in groups.items():
            eligible = [g for g in contributors if g.oper_id == operation_id and g.operation_admitted]
            if not eligible or any(not goal_matches(g.goal_id) for g in eligible):
                continue
            weights = []
            for gen in eligible:
                novelty = hedonic.novelty_score(gen.gen_id)
                if not math.isfinite(novelty) or not 0 <= novelty <= 1:
                    raise ValueError("Invalid novelty in command competition")
                weights.append(gen.actual_support * (0.5 + 0.5 * novelty))
            scores[operation_id] = max(weights)
        if not scores:
            return None
        maximum = max(scores.values())
        winners = [op for op, score in scores.items() if maximum - score <= 1e-12]
        return (winners[0], maximum) if len(winners) == 1 else None

    def propose(
        self,
        context: "ContextBuffer",
        base: "GeneralizationBase",
        hedonic: "HedonicAdapter",
    ) -> List[Proposal]:
        """
        Построить список предложений из активного контекста.

        Алгоритм:
          1. Получить ожидаемые признаки из контекста (gen_id → feature_id).
          2. Взвесить каждый: weight = significance * (0.5 + 0.5*novelty_score).
          3. Сгруппировать по feature_id (сохраняем максимальный вес).
          4. Для каждой группы выбрать gen_id с максимальным весом.
          5. Отсортировать по убыванию confidence.

        Возвращает список Proposal (не более 3-х).
        """
        expected = context.get_expected_features(base)
        if not expected:
            self._last_proposals = []
            return []

        # feature_id → (best_confidence, best_gen_id)
        feature_scores: Dict[str, tuple] = {}

        for gen_id, feat_id in expected.items():
            gen = base.get(gen_id)
            if gen is None:
                continue
            sig = gen.significance
            novelty = hedonic.novelty_score(gen_id)
            weight = sig * (0.5 + 0.5 * novelty)

            if feat_id not in feature_scores or weight > feature_scores[feat_id][0]:
                feature_scores[feat_id] = (weight, gen_id)

        # Сортируем по убыванию confidence
        sorted_features = sorted(
            feature_scores.items(),
            key=lambda kv: kv[1][0],
            reverse=True,
        )

        proposals = []
        for feat_id, (confidence, gen_id) in sorted_features[:3]:
            gen = base.get(gen_id)
            label = (gen.label or gen_id[:8]) if gen else gen_id[:8]
            proposals.append(Proposal(
                gen_id=gen_id,
                next_feature_id=feat_id,
                confidence=confidence,
                label=label,
            ))

        self._last_proposals = proposals
        self._total_proposals += len(proposals)
        return proposals

    def evaluate(
        self,
        proposals: List[Proposal],
        actual_feature_id: Optional[str],
    ) -> float:
        """
        Оценить предложения по фактически пришедшему признаку.

        Если actual_feature_id совпал с предложением ранга k:
            bonus = proposals[k].confidence * RANK_BONUSES[k]
        Иначе: bonus = 0.0.

        Обновляет счётчики hit/miss.
        Возвращает бонус (>0 если угадали, 0 если нет).
        """
        if actual_feature_id is None or not proposals:
            if proposals:
                self._total_misses += 1
            return 0.0

        for rank, proposal in enumerate(proposals):
            if proposal.next_feature_id == actual_feature_id:
                self._total_hits += 1
                bonus_mult = self.RANK_BONUSES[rank] if rank < len(self.RANK_BONUSES) else 0.5
                return proposal.confidence * bonus_mult

        self._total_misses += 1
        return 0.0

    @property
    def hit_rate(self) -> float:
        """Доля угаданных предложений от всех оцениваемых попыток."""
        total = self._total_hits + self._total_misses
        if total == 0:
            return 0.0
        return self._total_hits / total

    @property
    def last_proposals(self) -> List[Proposal]:
        """Последние сформированные предложения."""
        return list(self._last_proposals)

    def stats(self) -> dict:
        """Статистика двигателя инициативы."""
        return {
            "total_proposals": self._total_proposals,
            "total_hits":      self._total_hits,
            "total_misses":    self._total_misses,
            "hit_rate":        round(self.hit_rate, 4),
        }

    def __repr__(self) -> str:
        return (
            f"InitiativeEngine("
            f"hits={self._total_hits}, "
            f"misses={self._total_misses}, "
            f"hit_rate={self.hit_rate:.2%})"
        )
