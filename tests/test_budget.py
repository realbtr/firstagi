"""
tests/test_budget.py — тесты для QuestionBudget и интеграции с ContextBroker.

Покрытие (30 тестов):
  TestQuestionBudget       (16) — init, can_ask, consume, remaining, reset,
                                   stats, repr, zero_limit, автосброс при смене даты
  TestBrokerWithBudget     (14) — handle_query tier3 с бюджетом, budget_blocked,
                                   stats budget_remaining, tick с бюджетом
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from core.budget import QuestionBudget
from drivers.context_broker import ContextBroker, SourceTextRegistry


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _mock_query(trigger: str = "слово") -> MagicMock:
    q = MagicMock()
    q.trigger_token = trigger
    q.missing_hint = "?"
    return q


def _mock_teaching_log() -> MagicMock:
    tl = MagicMock()
    tl.peek_queries.return_value = []
    tl.pending_query_count.return_value = 0
    return tl


# ══════════════════════════════════════════════════════════════════════════════
# TestQuestionBudget
# ══════════════════════════════════════════════════════════════════════════════

class TestQuestionBudget:
    def test_default_limit(self):
        b = QuestionBudget()
        assert b.daily_limit == 20

    def test_custom_limit(self):
        b = QuestionBudget(daily_limit=5)
        assert b.daily_limit == 5

    def test_negative_limit_raises(self):
        with pytest.raises(ValueError):
            QuestionBudget(daily_limit=-1)

    def test_can_ask_initially_true(self):
        b = QuestionBudget(daily_limit=3)
        assert b.can_ask() is True

    def test_consume_returns_true_when_available(self):
        b = QuestionBudget(daily_limit=3)
        assert b.consume() is True

    def test_consume_deducts_from_remaining(self):
        b = QuestionBudget(daily_limit=3)
        b.consume()
        assert b.remaining() == 2

    def test_consume_returns_false_when_exhausted(self):
        b = QuestionBudget(daily_limit=2)
        b.consume()
        b.consume()
        assert b.consume() is False

    def test_can_ask_false_when_exhausted(self):
        b = QuestionBudget(daily_limit=1)
        b.consume()
        assert b.can_ask() is False

    def test_remaining_tracks_correctly(self):
        b = QuestionBudget(daily_limit=5)
        for _ in range(3):
            b.consume()
        assert b.remaining() == 2

    def test_remaining_never_negative(self):
        b = QuestionBudget(daily_limit=1)
        b.consume()
        b.consume()  # сверх лимита
        assert b.remaining() == 0

    def test_reset_restores_budget(self):
        b = QuestionBudget(daily_limit=3)
        b.consume()
        b.consume()
        b.reset()
        assert b.remaining() == 3

    def test_stats_keys(self):
        b = QuestionBudget(daily_limit=10)
        b.consume()
        s = b.stats()
        assert s["daily_limit"] == 10
        assert s["used_today"] == 1
        assert s["remaining"] == 9
        assert "date" in s

    def test_stats_date_format(self):
        b = QuestionBudget()
        s = b.stats()
        assert s["date"] == date.today().isoformat()

    def test_repr(self):
        b = QuestionBudget(daily_limit=5)
        b.consume()
        r = repr(b)
        assert "QuestionBudget" in r
        assert "limit=5" in r
        assert "remaining=4" in r

    def test_zero_limit_always_blocks(self):
        b = QuestionBudget(daily_limit=0)
        assert b.can_ask() is False
        assert b.consume() is False

    def test_auto_reset_on_date_change(self):
        from datetime import date as _date, timedelta
        b = QuestionBudget(daily_limit=3)
        b.consume()
        assert b.remaining() == 2
        # Имитируем следующий день (относительно текущей даты)
        tomorrow = _date.today() + timedelta(days=1)
        with patch("core.budget.date") as mock_date:
            mock_date.today.return_value = tomorrow
            # Принудительно обновляем дату через _maybe_reset
            assert b.can_ask() is True   # должен сброситься
            assert b.remaining() == 3    # полный бюджет снова


# ══════════════════════════════════════════════════════════════════════════════
# TestBrokerWithBudget
# ══════════════════════════════════════════════════════════════════════════════

class TestBrokerWithBudget:
    def _broker(self, budget=None):
        tl = _mock_teaching_log()
        broker = ContextBroker(teaching_log=tl, budget=budget)
        return broker, tl

    def test_tier3_consumed_from_budget(self):
        budget = QuestionBudget(daily_limit=5)
        broker, tl = self._broker(budget=budget)
        broker.handle_query(_mock_query(), driver=None)
        assert budget.remaining() == 4
        tl.push_query.assert_called_once()

    def test_tier3_blocked_when_budget_exhausted(self):
        budget = QuestionBudget(daily_limit=0)
        broker, tl = self._broker(budget=budget)
        result = broker.handle_query(_mock_query(), driver=None)
        assert result is False
        tl.push_query.assert_not_called()

    def test_budget_blocked_counter(self):
        budget = QuestionBudget(daily_limit=0)
        broker, _ = self._broker(budget=budget)
        broker.handle_query(_mock_query())
        broker.handle_query(_mock_query())
        assert broker._budget_blocked == 2

    def test_stats_includes_budget_remaining(self):
        budget = QuestionBudget(daily_limit=10)
        broker, _ = self._broker(budget=budget)
        s = broker.stats()
        assert "budget_remaining" in s
        assert s["budget_remaining"] == 10

    def test_stats_no_budget_remaining_when_none(self):
        broker, _ = self._broker(budget=None)
        s = broker.stats()
        assert "budget_remaining" not in s

    def test_stats_budget_blocked_always_present(self):
        broker, _ = self._broker()
        assert "budget_blocked" in broker.stats()

    def test_tier1_hit_doesnt_consume_budget(self):
        budget = QuestionBudget(daily_limit=5)
        tl = _mock_teaching_log()
        reg = SourceTextRegistry()
        reg.register("медведь гуляет в лесу")
        broker = ContextBroker(teaching_log=tl, registry=reg, budget=budget)
        broker.handle_query(_mock_query("медведь"))
        assert budget.remaining() == 5  # бюджет не тронут

    def test_multiple_queries_respect_budget(self):
        budget = QuestionBudget(daily_limit=2)
        broker, tl = self._broker(budget=budget)
        for _ in range(4):
            broker.handle_query(_mock_query())
        assert tl.push_query.call_count == 2
        assert broker._budget_blocked == 2

    def test_tick_with_budget_limits_llm(self):
        budget = QuestionBudget(daily_limit=1)
        tl = _mock_teaching_log()
        tl.peek_queries.return_value = [_mock_query("а"), _mock_query("б")]
        broker = ContextBroker(teaching_log=tl, budget=budget)
        broker.tick()
        # Первый уходит к LLM (списывает бюджет), второй блокируется
        assert broker._budget_blocked == 1
        assert broker._remote_queries == 1

    def test_tick_with_zero_budget_blocks_all(self):
        budget = QuestionBudget(daily_limit=0)
        tl = _mock_teaching_log()
        tl.peek_queries.return_value = [_mock_query("а"), _mock_query("б")]
        broker = ContextBroker(teaching_log=tl, budget=budget)
        broker.tick()
        assert broker._budget_blocked == 2
        assert broker._remote_queries == 0

    def test_no_budget_all_go_to_llm(self):
        broker, tl = self._broker(budget=None)
        for _ in range(3):
            broker.handle_query(_mock_query())
        assert tl.push_query.call_count == 3

    def test_budget_reset_allows_new_queries(self):
        budget = QuestionBudget(daily_limit=1)
        broker, tl = self._broker(budget=budget)
        broker.handle_query(_mock_query())   # использует 1
        broker.handle_query(_mock_query())   # блокируется
        budget.reset()
        broker.handle_query(_mock_query())   # снова проходит
        assert tl.push_query.call_count == 2

    def test_budget_stats_after_use(self):
        budget = QuestionBudget(daily_limit=10)
        broker, _ = self._broker(budget=budget)
        broker.handle_query(_mock_query())
        broker.handle_query(_mock_query())
        s = broker.stats()
        assert s["budget_remaining"] == 8
        assert s["remote_queries"] == 2

    def test_handle_query_returns_false_on_budget_block(self):
        budget = QuestionBudget(daily_limit=0)
        broker, _ = self._broker(budget=budget)
        assert broker.handle_query(_mock_query()) is False
