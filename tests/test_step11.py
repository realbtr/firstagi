"""
Тесты Шага 11: Proposal-Command Loop (активное внимание).

Группы:
  A. PeripheralDriver buffer API       (12 тестов)
  B. TextDriver buffer + query         (14 тестов)
  C. SequenceDriver buffer + query     (10 тестов)
  D. AttentionLoop                     (18 тестов)
  E. DebugSession active attention     (12 тестов)
  F. DriverController buffer API       (8 тестов)

Итого: 74 теста
"""

import pytest
from collections import deque
from typing import List

from core.app import CoreApplication
from core.attention_loop import AttentionLoop, AttentionStep
from core.driver_control import DriverController
from core.generalization import PeripheralToken
from core.feature import Feature, FeatureVector, RegionCharacteristics
from drivers.base import PeripheralDriver
from drivers.text_driver import TextDriver
from drivers.sequence_driver import SequenceDriver
from curriculum.debug_session import DebugSession


# ══════════════════════════════════════════════════════════════════════
# Fixtures
# ══════════════════════════════════════════════════════════════════════

def _make_app() -> CoreApplication:
    app = CoreApplication(config={"mock_teacher": False})
    app.startup()
    return app


def _make_token(driver_id: str = "test") -> PeripheralToken:
    """Создать синтетический токен с Feature."""
    rc = RegionCharacteristics(0.5, 0.5, 0.5, 0.0, 0.5, 1.5)
    feat = Feature.from_regions(
        feature_id="f_test",
        direction=0.0,
        distance=1.0,
        source=rc,
        target=RegionCharacteristics(0.6, 0.6, 0.6, 0.1, 0.5, 1.6),
    )
    return PeripheralToken.new(driver_id=driver_id, data=feat)


def _make_feature(brightness: float = 0.5) -> Feature:
    rc1 = RegionCharacteristics(0.3, brightness, 0.4, 0.0, 0.5, 1.4)
    rc2 = RegionCharacteristics(0.4, brightness + 0.1, 0.5, 0.1, 0.5, 1.5)
    return Feature.from_regions("fq", 0.0, 1.0, rc1, rc2)


# ══════════════════════════════════════════════════════════════════════
# A. PeripheralDriver buffer API
# ══════════════════════════════════════════════════════════════════════

class ConcreteDriver(PeripheralDriver):
    def produce(self):
        return iter([])
    def reset(self):
        self.clear_buffer()


class TestDriverBufferAPI:
    def test_initial_buffer_empty(self):
        d = ConcreteDriver("d1")
        assert d.buffer_size == 0

    def test_load_buffer_returns_new_size(self):
        d = ConcreteDriver("d1")
        tokens = [_make_token() for _ in range(3)]
        size = d.load_buffer(tokens)
        assert size == 3

    def test_buffer_size_after_load(self):
        d = ConcreteDriver("d1")
        d.load_buffer([_make_token() for _ in range(5)])
        assert d.buffer_size == 5

    def test_load_buffer_accumulates(self):
        d = ConcreteDriver("d1")
        d.load_buffer([_make_token(), _make_token()])
        d.load_buffer([_make_token()])
        assert d.buffer_size == 3

    def test_query_returns_none_when_empty(self):
        d = ConcreteDriver("d1")
        assert d.query() is None

    def test_query_no_feature_pops_fifo(self):
        d = ConcreteDriver("d1")
        t1, t2 = _make_token("a"), _make_token("b")
        d.load_buffer([t1, t2])
        result = d.query()
        assert result is t1
        assert d.buffer_size == 1

    def test_query_decrements_buffer(self):
        d = ConcreteDriver("d1")
        d.load_buffer([_make_token() for _ in range(4)])
        d.query()
        assert d.buffer_size == 3

    def test_query_until_empty(self):
        d = ConcreteDriver("d1")
        d.load_buffer([_make_token() for _ in range(3)])
        for _ in range(3):
            assert d.query() is not None
        assert d.query() is None

    def test_query_with_feature_returns_token(self):
        d = ConcreteDriver("d1")
        d.load_buffer([_make_token() for _ in range(3)])
        feat = _make_feature()
        result = d.query(feat)
        assert result is not None

    def test_query_with_feature_decrements_buffer(self):
        d = ConcreteDriver("d1")
        d.load_buffer([_make_token() for _ in range(5)])
        feat = _make_feature()
        d.query(feat)
        assert d.buffer_size == 4

    def test_clear_buffer(self):
        d = ConcreteDriver("d1")
        d.load_buffer([_make_token() for _ in range(5)])
        d.clear_buffer()
        assert d.buffer_size == 0

    def test_repr_shows_buf_size(self):
        d = ConcreteDriver("d42")
        d.load_buffer([_make_token()])
        assert "buf=1" in repr(d)


# ══════════════════════════════════════════════════════════════════════
# B. TextDriver buffer + query
# ══════════════════════════════════════════════════════════════════════

class TestTextDriverBuffer:
    def test_load_buffer_text_returns_size(self):
        drv = TextDriver("t1")
        size = drv.load_buffer("кот сидит на окне")
        assert size > 0

    def test_load_buffer_text_fills_buffer(self):
        drv = TextDriver("t1")
        drv.load_buffer("кот сидит на окне")
        assert drv.buffer_size > 0

    def test_load_buffer_short_text_no_tokens(self):
        drv = TextDriver("t1")
        size = drv.load_buffer("привет")   # одно слово → 0 переходов
        assert size == 0

    def test_load_buffer_two_words_one_token(self):
        drv = TextDriver("t1")
        drv.load_buffer("кот сидит")
        assert drv.buffer_size == 1

    def test_load_buffer_accumulates(self):
        drv = TextDriver("t1")
        drv.load_buffer("кот сидит")
        drv.load_buffer("кот бежит")
        assert drv.buffer_size == 2

    def test_query_returns_peripheral_token(self):
        drv = TextDriver("t1")
        drv.load_buffer("кот сидит на окне")
        tok = drv.query()
        assert isinstance(tok, PeripheralToken)

    def test_query_fifo_order(self):
        drv = TextDriver("t1")
        drv.load_buffer("кот сидит")
        tok = drv.query()
        assert tok is not None
        assert drv.buffer_size == 0

    def test_query_with_feature_returns_token(self):
        drv = TextDriver("t1")
        drv.load_buffer("кот сидит на окне")
        feat = _make_feature(0.3)
        tok = drv.query(feat)
        assert tok is not None

    def test_query_empty_returns_none(self):
        drv = TextDriver("t1")
        assert drv.query() is None

    def test_reset_clears_buffer(self):
        drv = TextDriver("t1")
        drv.load_buffer("кот сидит на окне")
        drv.reset()
        assert drv.buffer_size == 0

    def test_load_buffer_tokens_list(self):
        drv = TextDriver("t1")
        tokens = [_make_token("t1") for _ in range(3)]
        size = drv.load_buffer(tokens)
        assert size == 3

    def test_load_buffer_preserves_vocab(self):
        drv = TextDriver("t1")
        drv.build_vocab(["кот сидит", "кот бежит"])
        drv.load_buffer("кот сидит")
        tok = drv.query()
        assert tok is not None
        assert isinstance(tok.data, Feature)

    def test_multiple_texts_different_features(self):
        drv = TextDriver("t1")
        drv.load_buffer("кот сидит на окне собака бежит")
        sizes_before = drv.buffer_size
        while drv.buffer_size > 0:
            drv.query()
        assert drv.buffer_size == 0
        assert sizes_before > 0

    def test_repr_after_load(self):
        drv = TextDriver("t1")
        drv.load_buffer("кот сидит")
        assert "buf=1" in repr(drv)


# ══════════════════════════════════════════════════════════════════════
# C. SequenceDriver buffer + query
# ══════════════════════════════════════════════════════════════════════

class TestSequenceDriverBuffer:
    def test_load_buffer_values(self):
        drv = SequenceDriver("s1", [])
        size = drv.load_buffer([0.1, 0.5, 0.9, 0.3])
        assert size == 3  # n-1 transitions

    def test_load_buffer_fills_buffer(self):
        drv = SequenceDriver("s1", [])
        drv.load_buffer([0.1, 0.5, 0.9])
        assert drv.buffer_size == 2

    def test_query_from_sequence_buffer(self):
        drv = SequenceDriver("s1", [])
        drv.load_buffer([0.1, 0.5, 0.9])
        tok = drv.query()
        assert tok is not None

    def test_query_decrements_sequence_buffer(self):
        drv = SequenceDriver("s1", [])
        drv.load_buffer([0.1, 0.5, 0.9, 0.3])
        drv.query()
        assert drv.buffer_size == 2

    def test_query_empty_returns_none(self):
        drv = SequenceDriver("s1", [])
        assert drv.query() is None

    def test_load_tokens_directly(self):
        drv = SequenceDriver("s1", [0.1, 0.5, 0.9])
        tokens = list(drv.produce())
        drv2 = SequenceDriver("s1", [])
        drv2.load_buffer(tokens)
        assert drv2.buffer_size == 2

    def test_clear_buffer(self):
        drv = SequenceDriver("s1", [])
        drv.load_buffer([0.1, 0.5, 0.9])
        drv.clear_buffer()
        assert drv.buffer_size == 0

    def test_reset_clears_buffer(self):
        drv = SequenceDriver("s1", [])
        drv.load_buffer([0.1, 0.5, 0.9])
        drv.reset()
        assert drv.buffer_size == 0

    def test_load_buffer_accumulates(self):
        drv = SequenceDriver("s1", [])
        drv.load_buffer([0.1, 0.5, 0.9])
        drv.load_buffer([0.2, 0.8])
        assert drv.buffer_size == 3

    def test_query_with_feature(self):
        drv = SequenceDriver("s1", [])
        drv.load_buffer([0.1, 0.5, 0.9, 0.3])
        feat = _make_feature(0.6)
        tok = drv.query(feat)
        assert tok is not None


# ══════════════════════════════════════════════════════════════════════
# D. AttentionLoop
# ══════════════════════════════════════════════════════════════════════

class TestAttentionLoop:
    def test_create(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        assert loop.total_buffer_size() == 0

    def test_buffer_sizes_empty(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        sizes = loop.buffer_sizes()
        assert all(v == 0 for v in sizes.values())

    def test_load_buffer_text(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        size = loop.load_buffer("кот сидит на окне")
        assert size > 0

    def test_total_buffer_size(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        loop.load_buffer("кот сидит на окне")
        assert loop.total_buffer_size() > 0

    def test_step_idle_when_empty(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        step = loop.step()
        assert step.outcome == "IDLE"
        assert step.driver_queried is None

    def test_step_idle_returns_attention_step(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        step = loop.step()
        assert isinstance(step, AttentionStep)

    def test_step_after_load_not_idle(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        loop.load_buffer("кот сидит на окне")
        step = loop.step()
        assert step.outcome != "IDLE"

    def test_step_after_load_has_driver(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        loop.load_buffer("кот сидит на окне")
        step = loop.step()
        assert step.driver_queried == "text"

    def test_step_decrements_buffer(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        loop.load_buffer("кот сидит на окне")
        before = loop.total_buffer_size()
        loop.step()
        assert loop.total_buffer_size() == before - 1

    def test_run_returns_list(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        loop.load_buffer("кот сидит на окне")
        steps = loop.run(2)
        assert len(steps) == 2
        assert all(isinstance(s, AttentionStep) for s in steps)

    def test_run_until_empty_exhausts_buffer(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        loop.load_buffer("кот сидит на окне")
        steps = loop.run_until_empty()
        assert loop.total_buffer_size() == 0
        assert steps[-1].outcome == "IDLE"

    def test_stats_empty(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        s = loop.stats()
        assert s["steps"] == 0

    def test_stats_after_run(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        loop.load_buffer("кот сидит на окне")
        loop.run_until_empty()
        s = loop.stats()
        assert s["steps"] > 0

    def test_history_populated(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        loop.load_buffer("кот сидит")
        loop.run_until_empty()
        assert len(loop.history) > 0

    def test_match_rate_between_zero_and_one(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        loop.load_buffer("кот сидит на окне")
        loop.run_until_empty()
        s = loop.stats()
        assert 0.0 <= s["avg_match_rate"] <= 1.0

    def test_load_buffer_unknown_driver_raises(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        with pytest.raises(KeyError):
            loop.load_buffer("текст", driver_id="nonexistent")

    def test_second_run_after_reload(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        # Первый прогон
        loop.load_buffer("кот сидит")
        loop.run_until_empty()
        gens_after_first = app.system.base.size()
        # Второй прогон — должен работать без ошибок
        loop.load_buffer("кот сидит")
        steps = loop.run_until_empty()
        assert app.system.base.size() >= gens_after_first

    def test_repr(self):
        app = _make_app()
        loop = AttentionLoop(app.system, app.peripherals)
        assert "AttentionLoop" in repr(loop)


# ══════════════════════════════════════════════════════════════════════
# E. DebugSession active attention
# ══════════════════════════════════════════════════════════════════════

class TestDebugSessionActiveAttention:
    def _session(self):
        app = _make_app()
        return DebugSession(app, corpus=["кот сидит", "кот бежит"])

    def test_load_buffer_returns_size(self):
        s = self._session()
        size = s.load_buffer("кот сидит на окне")
        assert size > 0

    def test_buffer_sizes_dict(self):
        s = self._session()
        s.load_buffer("кот сидит")
        sizes = s.buffer_sizes()
        assert "text" in sizes
        assert sizes["text"] > 0

    def test_step_attention_idle_when_empty(self):
        s = self._session()
        result = s.step_attention()
        assert result["outcome"] == "IDLE"

    def test_step_attention_returns_dict(self):
        s = self._session()
        s.load_buffer("кот сидит")
        result = s.step_attention()
        assert isinstance(result, dict)
        assert "outcome" in result
        assert "match_rate" in result

    def test_step_attention_after_load_not_idle(self):
        s = self._session()
        s.load_buffer("кот сидит на окне")
        result = s.step_attention()
        assert result["outcome"] != "IDLE"

    def test_run_attention_returns_list(self):
        s = self._session()
        s.load_buffer("кот сидит на окне")
        results = s.run_attention(2)
        assert len(results) == 2

    def test_run_attention_until_empty(self):
        s = self._session()
        s.load_buffer("кот сидит")
        results = s.run_attention_until_empty()
        assert results[-1]["outcome"] == "IDLE"
        assert s.buffer_sizes().get("text", 0) == 0

    def test_attention_stats_after_run(self):
        s = self._session()
        s.load_buffer("кот сидит на окне")
        s.run_attention_until_empty()
        stats = s.attention_stats()
        assert stats["steps"] > 0

    def test_attention_logged(self):
        s = self._session()
        s.load_buffer("кот сидит")
        s.step_attention()
        log = s.log
        assert any(e["action"] == "attention_step" for e in log)

    def test_attention_and_curriculum_coexist(self):
        s = self._session()
        s.load_buffer("кот сидит на окне")
        s.run_attention_until_empty()
        step = s.step_curriculum()
        assert "step_n" in step

    def test_attention_after_learn(self):
        s = self._session()
        s.learn("кот сидит на окне")
        s.load_buffer("кот сидит на окне")
        results = s.run_attention_until_empty()
        # После обучения должно быть хоть одно подтверждение
        outcomes = [r["outcome"] for r in results if r["outcome"] != "IDLE"]
        assert any(o in ("CONFIRMED", "COMPLETED") for o in outcomes)

    def test_reload_and_rerun(self):
        s = self._session()
        s.load_buffer("кот сидит")
        s.run_attention_until_empty()
        s.load_buffer("кот сидит")  # загружаем повторно
        result = s.step_attention()
        assert result["outcome"] != "IDLE"


# ══════════════════════════════════════════════════════════════════════
# F. DriverController buffer API
# ══════════════════════════════════════════════════════════════════════

class TestDriverControllerBuffer:
    def _ctrl(self):
        app = _make_app()
        return DriverController(app), app

    def test_buffer_sizes_empty(self):
        ctrl, _ = self._ctrl()
        sizes = ctrl.buffer_sizes()
        assert isinstance(sizes, dict)
        assert all(v == 0 for v in sizes.values())

    def test_load_buffer_text(self):
        ctrl, _ = self._ctrl()
        size = ctrl.load_buffer("кот сидит на окне")
        assert size > 0

    def test_buffer_sizes_after_load(self):
        ctrl, _ = self._ctrl()
        ctrl.load_buffer("кот сидит")
        sizes = ctrl.buffer_sizes()
        assert sizes.get("text", 0) > 0

    def test_load_buffer_unknown_driver_raises(self):
        ctrl, _ = self._ctrl()
        with pytest.raises(KeyError):
            ctrl.load_buffer("текст", driver_id="no_such")

    def test_clear_buffer_specific(self):
        ctrl, _ = self._ctrl()
        ctrl.load_buffer("кот сидит на окне")
        ctrl.clear_buffer("text")
        assert ctrl.buffer_sizes().get("text", 0) == 0

    def test_clear_buffer_all(self):
        ctrl, _ = self._ctrl()
        ctrl.load_buffer("кот сидит на окне")
        ctrl.clear_buffer()
        assert all(v == 0 for v in ctrl.buffer_sizes().values())

    def test_clear_buffer_none_driver(self):
        ctrl, _ = self._ctrl()
        ctrl.load_buffer("кот сидит")
        ctrl.clear_buffer(driver_id=None)
        assert ctrl.buffer_sizes().get("text", 0) == 0

    def test_load_buffer_accumulates_via_controller(self):
        ctrl, _ = self._ctrl()
        ctrl.load_buffer("кот сидит")
        ctrl.load_buffer("кот бежит")
        assert ctrl.buffer_sizes().get("text", 0) == 2
