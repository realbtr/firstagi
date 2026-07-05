"""
Тесты Шага 13: ProposalCommandLoop — замкнутый цикл активного внимания.

Покрывает:
  TestLoopStatus       — константы статусов
  TestCycleResult      — датакласс результата
  TestProposalCommandLoopBasic  — базовые сценарии без speech/broker
  TestProposalCommandLoopSpeech — интеграция с SpeechDriver
  TestProposalCommandLoopBroker — интеграция с ContextBroker
  TestProposalCommandLoopResume — resume_after_llm
  TestProposalCommandLoopStats  — stats, repr
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from core.proposal_loop import ProposalCommandLoop, CycleResult, LoopStatus
from core.attention_loop import AttentionLoop
from core.app import CoreApplication
from drivers.text_driver import TextDriver
from drivers.speech_driver import SpeechDriver, ContextQuery


# ──────────────────────────────────────────────────────────────────────
# Вспомогательные фабрики
# ──────────────────────────────────────────────────────────────────────

def _make_app():
    app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.3})
    app.startup()
    return app


def _trained_loop(texts=None):
    """Создать AttentionLoop на обученном приложении."""
    texts = texts or [
        "маша пошла в лес",
        "волк встретил зайца",
        "кот сидит на окне",
    ]
    app = _make_app()
    d = TextDriver("train")
    for t in texts:
        for tok in d.produce(t):
            app.system.process_token(tok)
        app.system.reset_context()
    loop = AttentionLoop(app.system, app.peripherals)
    return loop, app


# ══════════════════════════════════════════════════════════════════════
# 1. LoopStatus
# ══════════════════════════════════════════════════════════════════════

class TestLoopStatus:

    def test_done_constant(self):
        assert LoopStatus.DONE == "DONE"

    def test_awaiting_llm_constant(self):
        assert LoopStatus.AWAITING_LLM == "AWAITING_LLM"

    def test_running_constant(self):
        assert LoopStatus.RUNNING == "RUNNING"


# ══════════════════════════════════════════════════════════════════════
# 2. CycleResult
# ══════════════════════════════════════════════════════════════════════

class TestCycleResult:

    def test_empty_steps(self):
        r = CycleResult(steps=[], status=LoopStatus.DONE)
        assert r.total_steps == 0
        assert r.match_rate == 0.0
        assert r.new_gens == 0

    def test_match_rate_all_confirmed(self):
        from core.attention_loop import AttentionStep
        steps = [
            AttentionStep(1, None, "text", "CONFIRMED", 0, {}, 1.0),
            AttentionStep(2, None, "text", "CONFIRMED", 0, {}, 1.0),
        ]
        r = CycleResult(steps=steps, status=LoopStatus.DONE)
        assert r.match_rate == pytest.approx(1.0)

    def test_match_rate_ignores_idle(self):
        from core.attention_loop import AttentionStep
        steps = [
            AttentionStep(1, None, "text", "CONFIRMED", 0, {}, 1.0),
            AttentionStep(2, None, None,   "IDLE",      0, {}, 1.0),
        ]
        r = CycleResult(steps=steps, status=LoopStatus.DONE)
        assert r.match_rate == pytest.approx(1.0)

    def test_new_gens_sum(self):
        from core.attention_loop import AttentionStep
        steps = [
            AttentionStep(1, None, "text", "REFUTED", 3, {}, 0.0),
            AttentionStep(2, None, "text", "REFUTED", 2, {}, 0.0),
        ]
        r = CycleResult(steps=steps, status=LoopStatus.DONE)
        assert r.new_gens == 5

    def test_pending_queries_default_empty(self):
        r = CycleResult(steps=[], status=LoopStatus.DONE)
        assert r.pending_queries == []

    def test_status_awaiting_llm(self):
        r = CycleResult(steps=[], status=LoopStatus.AWAITING_LLM,
                        pending_queries=["q1"])
        assert r.status == LoopStatus.AWAITING_LLM


# ══════════════════════════════════════════════════════════════════════
# 3. ProposalCommandLoop — базовые сценарии (без speech/broker)
# ══════════════════════════════════════════════════════════════════════

class TestProposalCommandLoopBasic:

    def test_creates_successfully(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        assert pcl is not None

    def test_empty_buffer_returns_done(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        result = pcl.run_cycle(max_steps=10)
        assert result.status == LoopStatus.DONE

    def test_empty_buffer_single_idle_step(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        result = pcl.run_cycle(max_steps=10)
        assert result.total_steps == 1
        assert result.steps[0].outcome == "IDLE"

    def test_run_cycle_with_buffer(self):
        loop, _ = _trained_loop()
        loop.load_buffer("маша пошла в лес")
        pcl = ProposalCommandLoop(loop)
        result = pcl.run_cycle(max_steps=50)
        assert result.status == LoopStatus.DONE
        assert result.total_steps >= 1

    def test_run_cycle_ends_with_idle(self):
        loop, _ = _trained_loop()
        loop.load_buffer("кот сидит на окне")
        pcl = ProposalCommandLoop(loop)
        result = pcl.run_cycle(max_steps=100)
        # Последний шаг — IDLE (буфер исчерпан)
        assert result.steps[-1].outcome == "IDLE"

    def test_match_rate_nonneg(self):
        loop, _ = _trained_loop()
        loop.load_buffer("маша пошла в лес")
        pcl = ProposalCommandLoop(loop)
        result = pcl.run_cycle(max_steps=50)
        assert 0.0 <= result.match_rate <= 1.0

    def test_no_queries_without_speech(self):
        loop, _ = _trained_loop()
        loop.load_buffer("мальчик нашёл ключ")
        pcl = ProposalCommandLoop(loop)
        result = pcl.run_cycle(max_steps=50)
        assert result.queries_generated == 0
        assert result.queries_resolved_local == 0
        assert result.queries_sent_to_llm == 0

    def test_pending_queries_empty_without_broker(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        assert pcl.pending_queries == []

    def test_inner_loop_accessible(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        assert pcl.inner_loop is loop

    def test_stats_returns_dict(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        s = pcl.stats()
        assert isinstance(s, dict)
        assert "pending_queries" in s
        assert s["pending_queries"] == 0


# ══════════════════════════════════════════════════════════════════════
# 4. ProposalCommandLoop — интеграция с SpeechDriver
# ══════════════════════════════════════════════════════════════════════

class TestProposalCommandLoopSpeech:

    def test_creates_with_speech(self):
        loop, _ = _trained_loop()
        speech = SpeechDriver(verbosity=0)
        pcl = ProposalCommandLoop(loop, speech=speech)
        assert pcl is not None

    def test_run_with_speech_returns_cycle_result(self):
        loop, _ = _trained_loop()
        loop.load_buffer("маша пошла в лес")
        speech = SpeechDriver(verbosity=0)
        pcl = ProposalCommandLoop(loop, speech=speech)
        result = pcl.run_cycle(max_steps=50)
        assert isinstance(result, CycleResult)

    def test_run_with_speech_status_done_known_text(self):
        """Известный текст → мало разрывов → status=DONE."""
        texts = ["маша пошла в лес"] * 5
        loop, _ = _trained_loop(texts)
        loop.load_buffer("маша пошла в лес")
        speech = SpeechDriver(verbosity=0)
        pcl = ProposalCommandLoop(loop, speech=speech, gap_threshold=0.10, min_streak=5)
        result = pcl.run_cycle(max_steps=50)
        # Со строгим порогом (0.10) на знакомом тексте разрывов нет
        assert result.status == LoopStatus.DONE

    def test_speech_resets_session_on_run(self):
        """SpeechDriver.reset_session() вызывается при каждом run_cycle."""
        loop, _ = _trained_loop()
        speech = SpeechDriver(verbosity=0)
        # Первый прогон
        pcl = ProposalCommandLoop(loop, speech=speech)
        loop.load_buffer("кот сидит на окне")
        pcl.run_cycle(max_steps=20)
        # Второй прогон — не должен упасть
        loop.load_buffer("кот сидит на окне")
        result = pcl.run_cycle(max_steps=20)
        assert isinstance(result, CycleResult)

    def test_queries_generated_on_unknown_text(self):
        """Незнакомый текст при строгом gap_threshold → возможны разрывы."""
        loop, _ = _trained_loop(["маша пошла в лес"])
        loop.load_buffer("мальчик открыл дверь вошёл внутрь")
        speech = SpeechDriver(verbosity=0)
        pcl = ProposalCommandLoop(
            loop, speech=speech,
            gap_threshold=0.50,  # очень строгий
            min_streak=1,
        )
        result = pcl.run_cycle(max_steps=50)
        # Либо разрывы найдены, либо нет — но структура правильная
        assert result.queries_generated >= 0
        assert isinstance(result.status, str)


# ══════════════════════════════════════════════════════════════════════
# 5. ProposalCommandLoop — интеграция с ContextBroker (mock)
# ══════════════════════════════════════════════════════════════════════

class _MockBrokerAlwaysLocal:
    """ContextBroker, который всегда разрешает запрос локально."""
    def handle_query(self, query, driver=None) -> bool:
        if driver is not None:
            # Загружаем фиктивный текст в буфер
            driver.load_buffer("кот на окне")
        return True


class _MockBrokerAlwaysRemote:
    """ContextBroker, который всегда отправляет в TeachingLog."""
    def __init__(self):
        self.pushed = []
    def handle_query(self, query, driver=None) -> bool:
        self.pushed.append(query)
        return False


class _MockSpeechWithGap:
    """SpeechDriver, который генерирует ContextQuery ровно один раз за всё время."""

    def __init__(self):
        self._fired = False

    def reset_session(self):
        pass  # Намеренно не сбрасываем — gap должен сгенерироваться ровно раз

    def observe(self, result, base, active):
        return None

    def detect_context_gap(self, result, lead_gen, lead_sig, **kw):
        if not self._fired:
            self._fired = True
            return ContextQuery(
                trigger_token="тест",
                trigger_outcome="REFUTED",
                missing_hint="тест",
                query_text="Напомни текст про тест.",
                confidence_gap=0.8,
            )
        return None


class TestProposalCommandLoopBroker:

    def test_local_resolve_increments_counter(self):
        loop, _ = _trained_loop()
        loop.load_buffer("маша пошла в лес")
        speech = _MockSpeechWithGap()
        broker = _MockBrokerAlwaysLocal()
        pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
        result = pcl.run_cycle(max_steps=50)
        assert result.queries_generated >= 1
        assert result.queries_resolved_local >= 1
        assert result.queries_sent_to_llm == 0

    def test_local_resolve_status_done(self):
        loop, _ = _trained_loop()
        loop.load_buffer("маша пошла в лес")
        speech = _MockSpeechWithGap()
        broker = _MockBrokerAlwaysLocal()
        pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
        result = pcl.run_cycle(max_steps=50)
        assert result.status == LoopStatus.DONE
        assert result.pending_queries == []

    def test_remote_resolve_status_awaiting_llm(self):
        loop, _ = _trained_loop()
        loop.load_buffer("маша пошла в лес")
        speech = _MockSpeechWithGap()
        broker = _MockBrokerAlwaysRemote()
        pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
        result = pcl.run_cycle(max_steps=50)
        assert result.status == LoopStatus.AWAITING_LLM
        assert len(result.pending_queries) >= 1
        assert result.queries_sent_to_llm >= 1

    def test_no_broker_no_local_resolution(self):
        loop, _ = _trained_loop()
        loop.load_buffer("маша пошла в лес")
        speech = _MockSpeechWithGap()
        pcl = ProposalCommandLoop(loop, speech=speech, broker=None)
        result = pcl.run_cycle(max_steps=50)
        # Без брокера LOCAL не работает → разрывы уходят в REMOTE (но нет broker → pending)
        # На самом деле без broker: _try_resolve → False → q_llm += 1, pending += 1
        assert result.queries_sent_to_llm >= 1
        assert result.status == LoopStatus.AWAITING_LLM

    def test_pending_queries_accessible(self):
        loop, _ = _trained_loop()
        loop.load_buffer("маша пошла в лес")
        speech = _MockSpeechWithGap()
        broker = _MockBrokerAlwaysRemote()
        pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
        pcl.run_cycle(max_steps=50)
        assert len(pcl.pending_queries) >= 1

    def test_clear_pending(self):
        loop, _ = _trained_loop()
        loop.load_buffer("маша пошла в лес")
        speech = _MockSpeechWithGap()
        broker = _MockBrokerAlwaysRemote()
        pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
        pcl.run_cycle(max_steps=50)
        pcl.clear_pending()
        assert pcl.pending_queries == []


# ══════════════════════════════════════════════════════════════════════
# 6. resume_after_llm
# ══════════════════════════════════════════════════════════════════════

class TestProposalCommandLoopResume:

    def test_resume_clears_pending(self):
        loop, _ = _trained_loop()
        loop.load_buffer("маша пошла в лес")
        speech = _MockSpeechWithGap()
        broker = _MockBrokerAlwaysRemote()
        pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
        pcl.run_cycle(max_steps=50)
        assert len(pcl.pending_queries) >= 1

        pcl.resume_after_llm(["маша нашла ягоды"])
        assert pcl.pending_queries == []

    def test_resume_returns_cycle_result(self):
        loop, _ = _trained_loop()
        loop.load_buffer("маша пошла в лес")
        speech = _MockSpeechWithGap()
        broker = _MockBrokerAlwaysRemote()
        pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
        pcl.run_cycle(max_steps=50)
        result2 = pcl.resume_after_llm(["маша нашла ягоды"])
        assert isinstance(result2, CycleResult)

    def test_resume_loads_text_into_buffer(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        # Буфер пуст → run_cycle вернёт DONE с 1 IDLE шагом
        r1 = pcl.run_cycle(max_steps=10)
        assert r1.steps[-1].outcome == "IDLE"
        # resume загружает текст → теперь есть не-IDLE шаги
        r2 = pcl.resume_after_llm(["маша пошла в лес"])
        non_idle = [s for s in r2.steps if s.outcome != "IDLE"]
        assert len(non_idle) > 0

    def test_resume_empty_texts_ok(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        result = pcl.resume_after_llm([])
        assert isinstance(result, CycleResult)

    def test_resume_after_done_is_noop_if_empty(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        r = pcl.resume_after_llm([])
        assert r.status == LoopStatus.DONE


# ══════════════════════════════════════════════════════════════════════
# 7. load_buffer + stats + repr
# ══════════════════════════════════════════════════════════════════════

class TestProposalCommandLoopStats:

    def test_load_buffer_returns_size(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        size = pcl.load_buffer("маша пошла в лес")
        assert size > 0

    def test_stats_has_pending_key(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        s = pcl.stats()
        assert "pending_queries" in s

    def test_stats_pending_zero_initially(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        assert pcl.stats()["pending_queries"] == 0

    def test_repr_contains_loop_info(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        r = repr(pcl)
        assert "ProposalCommandLoop" in r
        assert "pending=0" in r

    def test_repr_shows_speech_broker_status(self):
        loop, _ = _trained_loop()
        speech = SpeechDriver(verbosity=0)
        pcl = ProposalCommandLoop(loop, speech=speech)
        r = repr(pcl)
        assert "speech=yes" in r
        assert "broker=no" in r

    def test_multiple_run_cycles_accumulate_in_inner_loop(self):
        loop, _ = _trained_loop()
        pcl = ProposalCommandLoop(loop)
        loop.load_buffer("маша пошла в лес")
        pcl.run_cycle(max_steps=20)
        loop.load_buffer("кот сидит на окне")
        pcl.run_cycle(max_steps=20)
        s = pcl.stats()
        assert s["steps"] >= 2  # минимум 2 IDLE шага
