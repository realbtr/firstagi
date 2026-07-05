"""
Тесты для core/question_trace.py

Запуск: py -m pytest tests/test_question_trace.py -v
"""
from __future__ import annotations

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import time
import pytest
from core.question_trace import QuestionTrace, VoiceMemory


# ══════════════════════════════════════════════════════════════════════
# QuestionTrace — создание и состояние
# ══════════════════════════════════════════════════════════════════════

class TestQuestionTraceCreation:

    def test_begin_fills_fields(self):
        t = QuestionTrace.begin(
            logical_form="что идёт после мёда?",
            narrative_form="— откуда мёд? — думал Медведь.",
            char_name="медведь",
            role="EXPLORER",
            gen_count_before=100,
        )
        assert t.logical_form   == "что идёт после мёда?"
        assert t.narrative_form == "— откуда мёд? — думал Медведь."
        assert t.char_name      == "медведь"
        assert t.role           == "EXPLORER"
        assert t.gen_count_before == 100

    def test_begin_not_yet_scored(self):
        t = QuestionTrace.begin("q?", "Q?", "char", "ROLE", 50)
        assert not t.is_scored
        assert t.gen_delta      == 0
        assert t.quality_score  == 0.0
        assert t.answer_tokens  == []

    def test_asked_at_is_recent(self):
        before = time.time()
        t = QuestionTrace.begin("q?", "Q?", "char", "ROLE", 50)
        after  = time.time()
        assert before <= t.asked_at <= after


# ══════════════════════════════════════════════════════════════════════
# QuestionTrace — finish() и метрики
# ══════════════════════════════════════════════════════════════════════

class TestQuestionTraceMetrics:

    def _trace(self, before=100, after=110, tokens=None):
        t = QuestionTrace.begin("q?", "нарратив вопрос?", "медведь", "EXPLORER", before)
        t.finish(gen_count_after=after, answer_tokens=tokens or ["мёд", "пчёлы"])
        return t

    def test_finish_marks_scored(self):
        t = self._trace()
        assert t.is_scored

    def test_finish_returns_self(self):
        t = QuestionTrace.begin("q?", "Q?", "ch", "R", 50)
        ret = t.finish(gen_count_after=55)
        assert ret is t

    def test_gen_delta_positive(self):
        t = self._trace(before=100, after=115)
        assert t.gen_delta == 15

    def test_gen_delta_zero_if_no_change(self):
        t = self._trace(before=100, after=100)
        assert t.gen_delta == 0

    def test_gen_delta_clamped_non_negative(self):
        # Если Gen-база уменьшилась (eviction) — delta не уходит в минус
        t = self._trace(before=100, after=95)
        assert t.gen_delta == 0

    def test_quality_score_zero_if_no_delta(self):
        t = self._trace(before=100, after=100)
        assert t.quality_score == 0.0

    def test_quality_score_nonzero_on_delta(self):
        t = self._trace(before=100, after=105)
        assert 0.0 < t.quality_score <= 1.0

    def test_quality_score_capped_at_one(self):
        t = self._trace(before=100, after=200)
        assert t.quality_score == 1.0

    def test_quality_score_delta10_is_one(self):
        t = self._trace(before=100, after=110)
        assert abs(t.quality_score - 1.0) < 1e-9

    def test_quality_score_delta5_is_half(self):
        t = self._trace(before=100, after=105)
        assert abs(t.quality_score - 0.5) < 1e-9

    def test_narrative_overlap_full_match(self):
        t = QuestionTrace.begin(
            "q?", "мёд пчёлы собирают", "char", "R", 100
        )
        t.finish(gen_count_after=105, answer_tokens=["мёд", "пчёлы", "собирают"])
        assert t.narrative_overlap > 0.5

    def test_narrative_overlap_zero_no_answer(self):
        t = self._trace(tokens=[])
        assert t.narrative_overlap == 0.0

    def test_summary_contains_role(self):
        t = self._trace()
        s = t.summary()
        assert "EXPLORER" in s

    def test_summary_pending_when_not_scored(self):
        t = QuestionTrace.begin("q?", "Q?", "ch", "R", 50)
        assert "pending" in t.summary()


# ══════════════════════════════════════════════════════════════════════
# VoiceMemory
# ══════════════════════════════════════════════════════════════════════

def _make_trace(role: str, delta: int, char: str = "char") -> QuestionTrace:
    t = QuestionTrace.begin("q?", f"нарративный {role}?", char, role, 100)
    t.finish(gen_count_after=100 + delta, answer_tokens=["слово"])
    return t


class TestVoiceMemory:

    def test_empty_stats(self):
        mem = VoiceMemory()
        s = mem.stats()
        assert s["total"]       == 0
        assert s["scored"]      == 0
        assert s["avg_quality"] == 0.0
        assert s["best_role"]   is None

    def test_record_increments_total(self):
        mem = VoiceMemory()
        mem.record(_make_trace("EXPLORER", 5))
        assert len(mem) == 1

    def test_stats_after_one_trace(self):
        mem = VoiceMemory()
        mem.record(_make_trace("EXPLORER", 10))
        s = mem.stats()
        assert s["scored"]      == 1
        assert s["avg_quality"] == 1.0
        assert s["best_role"]   == "EXPLORER"

    def test_stats_avg_quality(self):
        mem = VoiceMemory()
        mem.record(_make_trace("GIVER", 10))   # q=1.0
        mem.record(_make_trace("GIVER", 0))    # q=0.0
        s = mem.stats()
        assert abs(s["avg_quality"] - 0.5) < 1e-9

    def test_best_for_role_returns_top(self):
        mem = VoiceMemory()
        mem.record(_make_trace("EXPLORER", 3))
        mem.record(_make_trace("EXPLORER", 10))
        mem.record(_make_trace("GIVER",    8))
        best = mem.best_for_role("EXPLORER", top_n=1)
        assert len(best) == 1
        assert best[0].gen_delta == 10

    def test_best_for_role_min_quality_filter(self):
        mem = VoiceMemory()
        mem.record(_make_trace("EXPLORER", 0))   # quality=0.0
        mem.record(_make_trace("EXPLORER", 1))   # quality=0.1
        best = mem.best_for_role("EXPLORER", min_quality=0.2)
        assert len(best) == 0

    def test_best_for_char(self):
        mem = VoiceMemory()
        mem.record(_make_trace("EXPLORER", 5, "медведь"))
        mem.record(_make_trace("GIVER",    8, "пятачок"))
        best = mem.best_for_char("медведь")
        assert all(t.char_name == "медведь" for t in best)

    def test_all_scored_sorted_by_quality(self):
        mem = VoiceMemory()
        mem.record(_make_trace("R", 2))
        mem.record(_make_trace("R", 10))
        mem.record(_make_trace("R", 5))
        scored = mem.all_scored()
        qs = [t.quality_score for t in scored]
        assert qs == sorted(qs, reverse=True)

    def test_fifo_eviction_at_max(self):
        mem = VoiceMemory(max_traces=3)
        for i in range(5):
            t = _make_trace("R", i)
            mem.record(t)
        assert len(mem) == 3

    def test_recent_returns_last_n(self):
        mem = VoiceMemory()
        for i in range(10):
            mem.record(_make_trace("R", i))
        recent = mem.recent(3)
        assert len(recent) == 3
        assert recent[-1].gen_delta == 9  # последний добавленный

    def test_role_ranking_order(self):
        mem = VoiceMemory()
        mem.record(_make_trace("GIVER",    10))
        mem.record(_make_trace("EXPLORER", 2))
        ranking = mem.role_ranking()
        # GIVER должен быть выше EXPLORER
        roles = [r for r, _ in ranking]
        assert roles.index("GIVER") < roles.index("EXPLORER")

    def test_unscored_trace_not_in_stats(self):
        mem = VoiceMemory()
        t = QuestionTrace.begin("q?", "Q?", "ch", "R", 50)  # не finish()
        mem.record(t)
        s = mem.stats()
        assert s["scored"] == 0

    def test_repr_contains_stats(self):
        mem = VoiceMemory()
        mem.record(_make_trace("EXPLORER", 5))
        r = repr(mem)
        assert "total=1" in r
        assert "scored=1" in r

    def test_avg_gen_delta_in_stats(self):
        mem = VoiceMemory()
        mem.record(_make_trace("R", 4))
        mem.record(_make_trace("R", 6))
        s = mem.stats()
        assert abs(s["avg_gen_delta"] - 5.0) < 1e-9
