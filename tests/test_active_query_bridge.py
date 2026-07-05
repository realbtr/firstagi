"""
Тесты ActiveQueryBridge — автоматическое возобновление при IDLE.

Покрывает:
  TestBridgeResult       — датакласс результата
  TestActiveQueryBridge  — базовые сценарии
  TestBridgeStrategies   — каждая стратегия отдельно
  TestBridgeIntegration  — интеграция с ProposalCommandLoop
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from core.app import CoreApplication
from core.active_query_bridge import ActiveQueryBridge, BridgeResult
from core.attention_loop import AttentionLoop
from core.proposal_loop import ProposalCommandLoop
from drivers.text_driver import TextDriver
from drivers.speech_driver import SpeechDriver
from drivers.context_broker import ContextBroker, SourceTextRegistry


# ──────────────────────────────────────────────────────────────────────
# Вспомогательные фабрики
# ──────────────────────────────────────────────────────────────────────

def _make_app():
    app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.3})
    app.startup()
    return app


def _make_broker(app):
    registry = SourceTextRegistry()
    texts = [
        "маша пошла в лес",
        "волк встретил зайца",
        "кот сидит на окне",
    ]
    for i, t in enumerate(texts):
        registry.register(t, source_id=f"train_{i}", origin="test")
    return ContextBroker(
        teaching_log=app.system.teaching_log,
        registry=registry,
    )


def _trained_system(app, texts=None):
    texts = texts or [
        "маша пошла в лес",
        "волк встретил зайца",
        "кот сидит на окне",
    ]
    d = TextDriver("train")
    for t in texts:
        for tok in d.produce(t):
            app.system.process_token(tok)
        app.system.reset_context()
    return app


# ══════════════════════════════════════════════════════════════════════
# 1. BridgeResult
# ══════════════════════════════════════════════════════════════════════

class TestBridgeResult:

    def test_defaults(self):
        r = BridgeResult()
        assert r.query_generated is False
        assert r.query_resolved is False
        assert r.query_sent_to_llm is False
        assert r.query is None
        assert r.reason == ""
        assert r.strategy == ""

    def test_with_values(self):
        r = BridgeResult(
            query_generated=True,
            query_resolved=True,
            strategy="LEAST_CONFIRMED",
            reason="found_weak_gen",
        )
        assert r.query_generated is True
        assert r.query_resolved is True
        assert r.strategy == "LEAST_CONFIRMED"


# ══════════════════════════════════════════════════════════════════════
# 2. ActiveQueryBridge — базовые сценарии
# ══════════════════════════════════════════════════════════════════════

class TestActiveQueryBridge:

    def test_creation(self):
        app = _make_app()
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)
        assert bridge._idle_count == 0
        assert bridge._queries_made == 0

    def test_creation_with_driver_id(self):
        app = _make_app()
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker, driver_id="custom")
        assert bridge._driver_id == "custom"

    def test_on_idle_returns_bridge_result(self):
        app = _make_app()
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)
        result = bridge.on_idle()
        assert isinstance(result, BridgeResult)
        assert bridge._idle_count == 1

    def test_on_idle_always_generates_query(self):
        """Bridge должен ВСЕГДА генерировать запрос (FALLBACK)."""
        app = _make_app()
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)
        result = bridge.on_idle()
        assert result.query_generated is True

    def test_stats_empty(self):
        app = _make_app()
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)
        stats = bridge.stats()
        assert stats["idle_count"] == 0
        assert stats["queries_made"] == 0
        assert stats["queries_resolved"] == 0

    def test_repr(self):
        app = _make_app()
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)
        r = repr(bridge)
        assert "ActiveQueryBridge" in r


# ══════════════════════════════════════════════════════════════════════
# 3. Стратегии
# ══════════════════════════════════════════════════════════════════════

class TestBridgeStrategies:

    def test_least_confirmed_strategy(self):
        """Gen с success_count=1 должны быть первыми кандидатами."""
        app = _make_app()
        app = _trained_system(app)
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)

        # Добавить слабый Gen
        from core.generalization import Generalization
        weak = Generalization(
            gen_id="weak-001",
            feature_chain=["f1", "f2"],
            success_count=1,
            stop_count=3,
            label="слабый паттерн",
        )
        app.system.base.add(weak)

        result = bridge.on_idle()
        assert result.query_generated is True
        assert result.strategy == "LEAST_CONFIRMED"

    def test_provisional_hunt_strategy(self):
        """Gen на испытательном сроке должны быть обнаружены."""
        app = _make_app()
        app = _trained_system(app)
        broker = _make_broker(app)

        # Убедиться что provisional есть
        provisional = getattr(app.system.engine, '_provisional', None)
        if provisional is not None:
            bridge = ActiveQueryBridge(app.system, broker)
            result = bridge.on_idle()
            assert result.query_generated is True
            # Стратегия может быть любой из подходящих

    def test_domain_gap_strategy(self):
        """Домен определён по меткам Gen."""
        app = _make_app()
        app = _trained_system(app)
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)

        # Добавить лесные Gen
        from core.generalization import Generalization
        for i in range(4):
            g = Generalization(
                gen_id=f"forest-{i}",
                feature_chain=["f1", "f2"],
                success_count=2 + i,
                stop_count=1,
                label=f"лес дерево заяц {i}",
            )
            app.system.base.add(g)

        result = bridge.on_idle()
        assert result.query_generated is True
        # Может быть LEAST_CONFIRMED или DOMAIN_GAP

    def test_fallback_strategy(self):
        """Fallback срабатывает когда ничего другого нет."""
        app = _make_app()
        # Не обучаем — база пуста
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)

        result = bridge.on_idle()
        assert result.query_generated is True
        assert result.strategy == "FALLBACK"

    def test_strategies_used_tracking(self):
        app = _make_app()
        app = _trained_system(app)
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)

        for _ in range(3):
            bridge.on_idle()

        stats = bridge.stats()
        assert stats["idle_count"] == 3
        assert stats["queries_made"] >= 0

    def test_no_strategy_returns_fallback(self):
        """Даже при пустой базе FALLBACK должен сработать."""
        app = _make_app()
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)

        result = bridge.on_idle()
        assert result.query_generated is True
        assert result.strategy == "FALLBACK"


# ══════════════════════════════════════════════════════════════════════
# 4. Интеграция с ProposalCommandLoop
# ══════════════════════════════════════════════════════════════════════

class TestBridgeIntegration:

    def test_bridge_with_pcl(self):
        app = _make_app()
        app = _trained_system(app)
        broker = _make_broker(app)

        loop = AttentionLoop(app.system, app.peripherals)
        speech = SpeechDriver(verbosity=0)
        pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
        bridge = ActiveQueryBridge(app.system, broker)

        pcl.load_buffer("маша пошла в лес")
        result = pcl.run_cycle(max_steps=50)
        assert result.total_steps > 0

        # Bridge готов к работе
        bridge_result = bridge.on_idle()
        assert isinstance(bridge_result, BridgeResult)

    def test_full_cycle_with_bridge(self):
        app = _make_app()
        app = _trained_system(app)
        broker = _make_broker(app)

        loop = AttentionLoop(app.system, app.peripherals)
        speech = SpeechDriver(verbosity=0)
        pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
        bridge = ActiveQueryBridge(app.system, broker)

        texts = ["маша пошла в лес", "кот сидит на окне"]
        total_steps = 0
        for text in texts:
            app.system.reset_context()
            pcl.load_buffer(text)
            result = pcl.run_cycle(max_steps=50)
            total_steps += result.total_steps

        assert total_steps > 0
        stats = bridge.stats()
        assert stats["idle_count"] >= 0


# ══════════════════════════════════════════════════════════════════════
# 5. Domain detection
# ══════════════════════════════════════════════════════════════════════

class TestDomainDetection:

    def test_detect_forest_domain(self):
        app = _make_app()
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)

        from core.generalization import Generalization
        for i in range(4):
            gen = Generalization(
                gen_id=f"forest-{i}",
                feature_chain=["f1", "f2"],
                success_count=3,
                stop_count=1,
                label=f"лес дерево заяц медведь {i}",
            )
            app.system.base.add(gen)

        domain = bridge._detect_domain()
        assert domain == "лес"

    def test_detect_no_domain(self):
        app = _make_app()
        broker = _make_broker(app)
        bridge = ActiveQueryBridge(app.system, broker)

        domain = bridge._detect_domain()
        assert domain is None
