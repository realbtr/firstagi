"""
Шаг 7: Гедонический адаптер — модуляция удовольствия от аттракторов.

Принцип: чем чаще петля повторяется, тем меньше удовольствия она приносит.
Это вынуждает модель искать новые аттракторы — «гедонический распад».

Из концепции:
  «Гедонический распад = повторный аттрактор даёт меньше удовольствия → тяга к риску»
"""

from __future__ import annotations
from typing import Dict, List, Optional


class HedonicAdapter:
    """
    Адаптер гедонического распада.

    Хранит счётчик завершений per gen_id и вычисляет новизну как
    decay^count. Чем больше раз петля закрылась — тем меньше награда.

    Параметры:
        decay     — множитель затухания [0, 1]. По умолчанию 0.75.
        min_novelty — минимальный множитель (нижний порог удовольствия).
    """

    def __init__(self, decay: float = 0.75, min_novelty: float = 0.05) -> None:
        if not 0.0 < decay <= 1.0:
            raise ValueError("decay должен быть в (0, 1]")
        if not 0.0 <= min_novelty < 1.0:
            raise ValueError("min_novelty должен быть в [0, 1)")
        self.decay = decay
        self.min_novelty = min_novelty
        self._completion_counts: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Основной API

    def record_completion(self, gen_id: str) -> None:
        """Зафиксировать завершение петли для данного Gen."""
        self._completion_counts[gen_id] = self._completion_counts.get(gen_id, 0) + 1

    def novelty_score(self, gen_id: str) -> float:
        """
        Вычислить коэффициент новизны для Gen.

        Первое завершение: 1.0 (до record_completion)
        После 1-го:        decay^1
        После 2-го:        decay^2
        ...
        Всегда >= min_novelty.
        """
        count = self._completion_counts.get(gen_id, 0)
        score = self.decay ** count
        return max(self.min_novelty, score)

    def reward_for(self, gen_id: str, base_reward: float) -> float:
        """
        Вычислить награду с учётом гедонического распада.

        reward = base_reward * novelty_score(gen_id)
        После record_completion (когда count уже обновлён).
        """
        return base_reward * self.novelty_score(gen_id)

    def most_novel(self, gen_ids: List[str]) -> Optional[str]:
        """
        Найти gen_id с максимальной новизной из списка.
        Возвращает None если список пустой.
        """
        if not gen_ids:
            return None
        return max(gen_ids, key=lambda gid: self.novelty_score(gid))

    def completion_count(self, gen_id: str) -> int:
        """Количество зафиксированных завершений для gen_id."""
        return self._completion_counts.get(gen_id, 0)

    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Статистика адаптера."""
        counts = self._completion_counts
        if not counts:
            return {
                "tracked_gens": 0,
                "total_completions": 0,
                "avg_novelty": 1.0,
                "min_novelty_reached": 0,
            }
        total = sum(counts.values())
        novelties = [self.novelty_score(gid) for gid in counts]
        avg_novelty = sum(novelties) / len(novelties)
        at_min = sum(1 for n in novelties if n <= self.min_novelty + 1e-9)
        return {
            "tracked_gens": len(counts),
            "total_completions": total,
            "avg_novelty": round(avg_novelty, 4),
            "min_novelty_reached": at_min,
        }

    def __repr__(self) -> str:
        return (
            f"HedonicAdapter("
            f"decay={self.decay}, "
            f"min_novelty={self.min_novelty}, "
            f"tracked={len(self._completion_counts)})"
        )
