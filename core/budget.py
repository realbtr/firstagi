"""
QuestionBudget — суточный бюджет LLM-запросов.

Ограничивает число tier-3 обращений к учителю (LLM) за сутки.
Бюджет автоматически обнуляется при смене даты.

Использование:
    budget = QuestionBudget(daily_limit=20)

    if budget.can_ask():
        budget.consume()
        teaching_log.push_query(query)

    print(budget.stats())
    # {'daily_limit': 20, 'used_today': 1, 'remaining': 19, 'date': '2026-03-23'}
"""
from __future__ import annotations

from datetime import date
from typing import Any, Dict


# ══════════════════════════════════════════════════════════════════════════════
# QuestionBudget
# ══════════════════════════════════════════════════════════════════════════════

class QuestionBudget:
    """
    Суточный счётчик LLM-запросов.

    Параметры
    ----------
    daily_limit : int — максимум запросов в сутки (по умолчанию 20)

    Автосброс: при вызове can_ask() или consume() проверяется текущая дата;
    если она отличается от даты последнего использования — счётчик обнуляется.
    """

    def __init__(self, daily_limit: int = 20) -> None:
        if daily_limit < 0:
            raise ValueError("daily_limit must be >= 0")
        self._daily_limit: int = daily_limit
        self._used: int = 0
        self._date: date = date.today()

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    @property
    def daily_limit(self) -> int:
        return self._daily_limit

    def can_ask(self) -> bool:
        """True если в бюджете ещё есть запросы на сегодня."""
        self._maybe_reset()
        return self._used < self._daily_limit

    def consume(self) -> bool:
        """
        Списать один запрос из бюджета.

        Возвращает True если запрос разрешён и списан,
        False если бюджет исчерпан (запрос НЕ списан).
        """
        self._maybe_reset()
        if self._used >= self._daily_limit:
            return False
        self._used += 1
        return True

    def remaining(self) -> int:
        """Число оставшихся запросов на сегодня."""
        self._maybe_reset()
        return max(0, self._daily_limit - self._used)

    def reset(self) -> None:
        """Принудительно сбросить счётчик (для тестов и отладки)."""
        self._used = 0
        self._date = date.today()

    def stats(self) -> Dict[str, Any]:
        self._maybe_reset()
        return {
            "daily_limit": self._daily_limit,
            "used_today":  self._used,
            "remaining":   self.remaining(),
            "date":        self._date.isoformat(),
        }

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _maybe_reset(self) -> None:
        today = date.today()
        if today != self._date:
            self._used = 0
            self._date = today

    def __repr__(self) -> str:
        return (
            f"QuestionBudget("
            f"limit={self._daily_limit}, "
            f"used={self._used}, "
            f"remaining={self.remaining()})"
        )
