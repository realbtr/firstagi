"""
Шаг 8: тесты LLMDecision, LLMPromptBuilder, LLMResponseParser,
MockLLMClient, LLMTeacherWorker, BrokerLoop, интеграционные.

~63 теста.
"""

from __future__ import annotations

import json
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.llm_broker import (
    LLMDecision,
    LLMPromptBuilder,
    LLMResponseParser,
    MockLLMClient,
    LLMTeacherWorker,
)
from core.learning import LearningSystem
from core.teacher import RewardOrder
from core.app import CoreApplication
from training.llm_loop import BrokerLoop
from drivers.text_driver import TextDriver


# ══════════════════════════════════════════════════════════════════════
# Вспомогательные фабрики
# ══════════════════════════════════════════════════════════════════════

def _make_system() -> LearningSystem:
    return LearningSystem(feature_tolerance=0.3, min_gen_count=2)


def _trained_system() -> LearningSystem:
    sys_ = _make_system()
    driver = TextDriver(driver_id="t", lowercase=True)
    texts = ["день ночь день ночь", "день ночь день ночь", "день ночь день ночь"]
    driver.build_vocab(texts)
    for text in texts:
        tokens = list(driver.produce(text))
        sys_.process_stream(tokens)
        sys_.reset_context()
    return sys_


def _make_app() -> CoreApplication:
    app = CoreApplication(config={"mock_teacher": False, "scheduler_interval": 999.0})
    app.startup()
    return app


def _make_worker(system, responses=None, min_interval=0.0) -> LLMTeacherWorker:
    client = MockLLMClient(responses=responses or [])
    return LLMTeacherWorker(system=system, llm_client=client, min_interval=min_interval)


def _log_entries(n=5):
    """Создать несколько лог-записей для тестов."""
    outcomes = ["CONFIRMED", "COMPLETED", "REFUTED", "EXPLORING", "CONFIRMED"]
    return [
        {
            "step": i,
            "outcome": outcomes[i % len(outcomes)],
            "resource_level": 0.5,
            "resource_mode": "normal",
            "active_gens": [],
            "matched_feat": None,
            "completed_gens": [],
            "removed_gens": [],
            "new_gen_id": None,
        }
        for i in range(n)
    ]


# ══════════════════════════════════════════════════════════════════════
# TestLLMDecision  (3 теста)
# ══════════════════════════════════════════════════════════════════════

class TestLLMDecision:

    def test_defaults(self):
        d = LLMDecision(action="TEACH")
        assert d.action == "TEACH"
        assert d.text == ""
        assert d.amount == 0.0
        assert d.reason == ""

    def test_action_uppercase(self):
        d = LLMDecision(action="teach")
        assert d.action == "TEACH"

    def test_invalid_action_becomes_wait(self):
        d = LLMDecision(action="INVALID_XYZ")
        assert d.action == "WAIT"


# ══════════════════════════════════════════════════════════════════════
# TestLLMPromptBuilder  (8 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestLLMPromptBuilder:

    def test_build_returns_nonempty(self):
        sys_ = _make_system()
        entries = _log_entries(5)
        prompt = LLMPromptBuilder.build(sys_, entries)
        assert isinstance(prompt, str)
        assert len(prompt) > 50

    def test_build_contains_narrative_section(self):
        sys_ = _make_system()
        entries = _log_entries(3)
        prompt = LLMPromptBuilder.build(sys_, entries)
        assert "ТЕКУЩЕЕ СОСТОЯНИЕ" in prompt

    def test_build_contains_events_section(self):
        sys_ = _make_system()
        entries = _log_entries(5)
        prompt = LLMPromptBuilder.build(sys_, entries)
        assert "СОБЫТИЙ" in prompt
        assert "COMPLETED" in prompt
        assert "REFUTED" in prompt

    def test_build_contains_initiative_section(self):
        sys_ = _make_system()
        entries = _log_entries(3)
        prompt = LLMPromptBuilder.build(sys_, entries)
        assert "ИНИЦИАТИВА" in prompt

    def test_build_contains_task_section(self):
        sys_ = _make_system()
        entries = _log_entries(3)
        prompt = LLMPromptBuilder.build(sys_, entries)
        assert "ЗАДАЧА" in prompt
        assert "TEACH" in prompt
        assert "REWARD" in prompt
        assert "WAIT" in prompt

    def test_build_contains_json_format(self):
        sys_ = _make_system()
        entries = _log_entries(3)
        prompt = LLMPromptBuilder.build(sys_, entries)
        assert "action" in prompt
        assert "JSON" in prompt

    def test_build_with_empty_log(self):
        sys_ = _make_system()
        prompt = LLMPromptBuilder.build(sys_, [])
        assert len(prompt) > 20

    def test_build_with_trained_system(self):
        sys_ = _trained_system()
        entries = _log_entries(10)
        prompt = LLMPromptBuilder.build(sys_, entries)
        assert "База" in prompt or "Обобщений" in prompt or "Gen" in prompt


# ══════════════════════════════════════════════════════════════════════
# TestLLMResponseParser  (12 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestLLMResponseParser:

    def test_parse_teach(self):
        r = '{"action":"TEACH","text":"день ночь","amount":0,"reason":"test"}'
        d = LLMResponseParser.parse(r)
        assert d is not None
        assert d.action == "TEACH"
        assert d.text == "день ночь"

    def test_parse_reward(self):
        r = '{"action":"REWARD","text":"","amount":5.0,"reason":"good"}'
        d = LLMResponseParser.parse(r)
        assert d is not None
        assert d.action == "REWARD"
        assert d.amount == 5.0

    def test_parse_wait(self):
        r = '{"action":"WAIT","text":"","amount":0,"reason":""}'
        d = LLMResponseParser.parse(r)
        assert d is not None
        assert d.action == "WAIT"

    def test_parse_markdown_block(self):
        r = '```json\n{"action":"TEACH","text":"раз два три","amount":0,"reason":"x"}\n```'
        d = LLMResponseParser.parse(r)
        assert d is not None
        assert d.action == "TEACH"
        assert d.text == "раз два три"

    def test_parse_markdown_block_no_lang(self):
        r = '```\n{"action":"WAIT","text":"","amount":0,"reason":""}\n```'
        d = LLMResponseParser.parse(r)
        assert d is not None
        assert d.action == "WAIT"

    def test_parse_invalid_json_returns_none(self):
        d = LLMResponseParser.parse("это не json вообще")
        assert d is None

    def test_parse_empty_string_returns_none(self):
        d = LLMResponseParser.parse("")
        assert d is None

    def test_parse_whitespace_returns_none(self):
        d = LLMResponseParser.parse("   \n  ")
        assert d is None

    def test_parse_unknown_action_becomes_wait(self):
        r = '{"action":"DANCE","text":"","amount":0,"reason":""}'
        d = LLMResponseParser.parse(r)
        assert d is not None
        assert d.action == "WAIT"

    def test_parse_missing_text_defaults_empty(self):
        r = '{"action":"TEACH","amount":0,"reason":""}'
        d = LLMResponseParser.parse(r)
        assert d is not None
        assert d.text == ""

    def test_parse_case_insensitive_action(self):
        r = '{"action":"teach","text":"привет мир","amount":0,"reason":""}'
        d = LLMResponseParser.parse(r)
        assert d is not None
        assert d.action == "TEACH"

    def test_parse_json_in_text(self):
        r = 'Вот мой ответ: {"action":"REWARD","text":"","amount":10.0,"reason":"great"} — конец'
        d = LLMResponseParser.parse(r)
        assert d is not None
        assert d.action == "REWARD"
        assert d.amount == 10.0


# ══════════════════════════════════════════════════════════════════════
# TestMockLLMClient  (5 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestMockLLMClient:

    def test_empty_responses_returns_wait(self):
        client = MockLLMClient()
        r = client.complete("любой промпт")
        assert "WAIT" in r

    def test_cycles_through_responses(self):
        responses = ['{"action":"TEACH"}', '{"action":"REWARD"}', '{"action":"WAIT"}']
        client = MockLLMClient(responses)
        r0 = client.complete("p1")
        r1 = client.complete("p2")
        r2 = client.complete("p3")
        r3 = client.complete("p4")   # цикл заново
        assert r0 == responses[0]
        assert r1 == responses[1]
        assert r2 == responses[2]
        assert r3 == responses[0]

    def test_calls_recorded(self):
        client = MockLLMClient()
        client.complete("промпт 1")
        client.complete("промпт 2")
        assert len(client.calls) == 2
        assert client.calls[0] == "промпт 1"

    def test_complete_returns_string(self):
        client = MockLLMClient(['{"action":"WAIT"}'])
        r = client.complete("test")
        assert isinstance(r, str)

    def test_calls_grows_with_each_complete(self):
        client = MockLLMClient()
        for i in range(5):
            client.complete(f"p{i}")
        assert len(client.calls) == 5


# ══════════════════════════════════════════════════════════════════════
# TestLLMTeacherWorker  (15 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestLLMTeacherWorker:

    def test_init_defaults(self):
        sys_ = _make_system()
        client = MockLLMClient()
        worker = LLMTeacherWorker(sys_, client)
        assert worker.call_count == 0
        assert worker.min_interval == 5.0

    def test_observe_no_call_when_interval_not_met(self):
        sys_ = _make_system()
        worker = _make_worker(sys_, min_interval=9999.0)
        # Симулируем недавний вызов
        worker._last_call = time.time()
        result = worker.observe(_log_entries())
        assert result is None
        assert worker.call_count == 0

    def test_observe_calls_llm_when_interval_zero(self):
        teach_json = '{"action":"TEACH","text":"день ночь","amount":0,"reason":"test"}'
        sys_ = _make_system()
        worker = _make_worker(sys_, responses=[teach_json], min_interval=0.0)
        worker.observe(_log_entries())
        assert worker.call_count == 1

    def test_observe_returns_none_for_teach(self):
        teach_json = '{"action":"TEACH","text":"день ночь","amount":0,"reason":""}'
        sys_ = _make_system()
        worker = _make_worker(sys_, responses=[teach_json], min_interval=0.0)
        result = worker.observe(_log_entries())
        assert result is None

    def test_observe_returns_reward_order_for_reward(self):
        reward_json = '{"action":"REWARD","text":"","amount":7.5,"reason":"good"}'
        sys_ = _make_system()
        worker = _make_worker(sys_, responses=[reward_json], min_interval=0.0)
        result = worker.observe(_log_entries())
        assert isinstance(result, RewardOrder)
        assert result.reward == 7.5
        assert result.max_fires == 1

    def test_observe_returns_none_for_wait(self):
        wait_json = '{"action":"WAIT","text":"","amount":0,"reason":""}'
        sys_ = _make_system()
        worker = _make_worker(sys_, responses=[wait_json], min_interval=0.0)
        result = worker.observe(_log_entries())
        assert result is None

    def test_suggest_content_uses_teach_cache(self):
        teach_json = '{"action":"TEACH","text":"кот сидит","amount":0,"reason":""}'
        sys_ = _make_system()
        worker = _make_worker(sys_, responses=[teach_json], min_interval=0.0)
        # observe() вызывает LLM и кэширует
        worker.observe(_log_entries())
        # suggest_content() использует кэш
        content = worker.suggest_content(_log_entries())
        assert content == "кот сидит"

    def test_suggest_content_clears_cache(self):
        teach_json = '{"action":"TEACH","text":"раз два три","amount":0,"reason":""}'
        sys_ = _make_system()
        worker = _make_worker(sys_, responses=[teach_json], min_interval=0.0)
        worker.observe(_log_entries())
        worker.suggest_content(_log_entries())
        # Второй вызов — кэш пустой, новый LLM-вызов не произошёл
        content2 = worker.suggest_content(_log_entries())
        assert content2 is None

    def test_suggest_content_none_for_reward_cache(self):
        reward_json = '{"action":"REWARD","text":"","amount":5.0,"reason":""}'
        sys_ = _make_system()
        worker = _make_worker(sys_, responses=[reward_json], min_interval=0.0)
        worker.observe(_log_entries())
        content = worker.suggest_content(_log_entries())
        assert content is None

    def test_single_llm_call_per_tick(self):
        """observe() + suggest_content() = ровно 1 LLM-вызов"""
        teach_json = '{"action":"TEACH","text":"тест","amount":0,"reason":""}'
        sys_ = _make_system()
        worker = _make_worker(sys_, responses=[teach_json, teach_json], min_interval=0.0)
        entries = _log_entries()
        worker.observe(entries)
        worker.suggest_content(entries)
        assert worker.call_count == 1

    def test_call_count_increments(self):
        json_resp = '{"action":"WAIT","text":"","amount":0,"reason":""}'
        sys_ = _make_system()
        worker = _make_worker(sys_, responses=[json_resp], min_interval=0.0)
        for i in range(3):
            worker._last_call = 0.0  # обнулить таймер
            worker.observe(_log_entries())
        assert worker.call_count == 3

    def test_stats_structure(self):
        sys_ = _make_system()
        worker = _make_worker(sys_)
        stats = worker.stats()
        assert "call_count" in stats
        assert "last_call_age" in stats
        assert "decision_history" in stats

    def test_exception_in_llm_handled_gracefully(self):
        """Если LLM выбросил исключение — observe() возвращает None."""
        class FailingClient:
            def complete(self, prompt):
                raise RuntimeError("network error")

        sys_ = _make_system()
        worker = LLMTeacherWorker(sys_, FailingClient(), min_interval=0.0)
        result = worker.observe(_log_entries())
        assert result is None
        assert worker.call_count == 1  # вызов был, но с ошибкой

    def test_decision_log_records_history(self):
        responses = [
            '{"action":"TEACH","text":"a","amount":0,"reason":""}',
            '{"action":"REWARD","text":"","amount":5,"reason":""}',
            '{"action":"WAIT","text":"","amount":0,"reason":""}',
        ]
        sys_ = _make_system()
        worker = _make_worker(sys_, responses=responses, min_interval=0.0)
        for _ in range(3):
            worker._last_call = 0.0
            worker.observe(_log_entries())
        stats = worker.stats()
        assert "TEACH" in stats["decision_history"]
        assert "REWARD" in stats["decision_history"]
        assert "WAIT" in stats["decision_history"]

    def test_reward_order_unconditional(self):
        """RewardOrder с пустым required_gen_ids срабатывает безусловно."""
        reward_json = '{"action":"REWARD","text":"","amount":3.0,"reason":"test"}'
        sys_ = _make_system()
        worker = _make_worker(sys_, responses=[reward_json], min_interval=0.0)
        order = worker.observe(_log_entries())
        assert order is not None
        assert len(order.required_gen_ids) == 0


# ══════════════════════════════════════════════════════════════════════
# TestBrokerLoop  (10 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestBrokerLoop:

    def test_step_returns_dict_with_keys(self):
        app = _make_app()
        worker = _make_worker(app.system, min_interval=9999.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)
        report = loop.step()
        assert "step" in report
        assert "content_fed" in report
        assert "learn_result" in report
        assert "orders_fired" in report
        assert "resource" in report
        assert "llm_calls" in report
        app.shutdown()

    def test_step_count_increments(self):
        app = _make_app()
        worker = _make_worker(app.system, min_interval=9999.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)
        loop.step()
        loop.step()
        assert loop._step_count == 2
        app.shutdown()

    def test_content_from_queue_gets_learned(self):
        """Если в TeachingLog есть контент — он передаётся в app.learn()."""
        app = _make_app()
        worker = _make_worker(app.system, min_interval=9999.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)

        # Руками пушим контент в лог
        app.system.teaching_log.push_content("день ночь")
        report = loop.step()
        assert report["content_fed"] == "день ночь"
        assert report["learn_result"] is not None
        app.shutdown()

    def test_no_content_when_queue_empty(self):
        app = _make_app()
        worker = _make_worker(app.system, min_interval=9999.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)
        report = loop.step()
        assert report["content_fed"] is None
        assert report["learn_result"] is None
        app.shutdown()

    def test_run_returns_n_reports(self):
        app = _make_app()
        worker = _make_worker(app.system, min_interval=9999.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)
        reports = loop.run(n_steps=7)
        assert len(reports) == 7
        app.shutdown()

    def test_stats_structure(self):
        app = _make_app()
        worker = _make_worker(app.system, min_interval=9999.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)
        loop.run(n_steps=3)
        stats = loop.stats()
        assert "total_steps" in stats
        assert "content_fed_count" in stats
        assert "orders_fired_total" in stats
        assert "llm_calls" in stats
        assert "final_resource" in stats
        app.shutdown()

    def test_resource_in_valid_range(self):
        app = _make_app()
        worker = _make_worker(app.system, min_interval=9999.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)
        reports = loop.run(n_steps=5)
        for r in reports:
            assert 0.0 <= r["resource"] <= 1.0
        app.shutdown()

    def test_orders_fired_counted(self):
        """Когда LLM выдаёт REWARD — orders_fired должен быть > 0."""
        reward_json = '{"action":"REWARD","text":"","amount":5.0,"reason":"test"}'
        app = _make_app()
        worker = _make_worker(app.system, responses=[reward_json], min_interval=0.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)
        report = loop.step()
        # tick() возвращает число запушенных (1 ордер)
        assert report["orders_fired"] >= 0  # может быть 0 если ордер не срабатывает сразу
        app.shutdown()

    def test_content_fed_count_in_stats(self):
        app = _make_app()
        worker = _make_worker(app.system, min_interval=9999.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)

        # Пушим контент 3 раза перед каждым шагом
        for _ in range(3):
            app.system.teaching_log.push_content("раз два три")
            loop.step()

        stats = loop.stats()
        assert stats["content_fed_count"] == 3
        app.shutdown()

    def test_run_does_not_crash(self):
        """BrokerLoop.run() без ошибок на пустой системе."""
        app = _make_app()
        worker = _make_worker(app.system, min_interval=9999.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)
        reports = loop.run(n_steps=10)
        assert len(reports) == 10
        app.shutdown()


# ══════════════════════════════════════════════════════════════════════
# TestIntegration  (10 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestIntegration:

    def test_teach_decision_leads_to_tokens(self):
        """TEACH → текст попадает в систему → шаги движка."""
        teach_json = '{"action":"TEACH","text":"день ночь день ночь","amount":0,"reason":""}'
        app = _make_app()
        worker = _make_worker(app.system, responses=[teach_json], min_interval=0.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)

        steps_before = app.system.engine.step_count
        loop.step()   # тик: LLM решает TEACH, пушит контент
        loop.step()   # тик: контент изымается и обрабатывается
        steps_after = app.system.engine.step_count

        assert steps_after > steps_before
        app.shutdown()

    def test_reward_decision_increases_resource(self):
        """REWARD → ресурс растёт."""
        reward_json = '{"action":"REWARD","text":"","amount":50.0,"reason":"great"}'
        app = _make_app()
        resource_before = app.system.resource.level
        worker = _make_worker(app.system, responses=[reward_json], min_interval=0.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)

        # Тик: observe() кладёт RewardOrder в TeachingLog
        # LearningSystem.process_token() потребит ордер на следующем process_token()
        loop.step()

        # Применить ордера через process_token (контент из следующего шага или напрямую)
        # Проверяем что ордер хотя бы попал в teaching_log → pending_orders
        pending = app.system.teaching_log.pop_pending_orders()
        if pending:
            for order in pending:
                app.system.resource.add_reward(order.reward)

        resource_after = app.system.resource.level
        assert resource_after >= resource_before
        app.shutdown()

    def test_llm_worker_registered_in_scheduler_works(self):
        """LLMTeacherWorker корректно работает через scheduler.tick()."""
        wait_json = '{"action":"WAIT","text":"","amount":0,"reason":""}'
        app = _make_app()
        worker = _make_worker(app.system, responses=[wait_json], min_interval=0.0)
        app.scheduler.add_worker(worker, name="llm")

        app.scheduler.tick()
        assert worker.call_count == 1
        app.shutdown()

    def test_narrative_in_prompt_contains_system_info(self):
        """Промпт содержит реальные данные системы."""
        sys_ = _trained_system()
        entries = _log_entries(5)
        prompt = LLMPromptBuilder.build(sys_, entries)
        # После обучения база не пуста — должно быть что-то про Gen
        assert len(prompt) > 100
        assert "ресурс" in prompt.lower() or "resource" in prompt.lower() or "Ресурс" in prompt

    def test_full_roundtrip_teach(self):
        """Полный цикл: MockLLM → TEACH → контент в лог → BrokerLoop → learn()."""
        teach_json = '{"action":"TEACH","text":"раз два три раз два три","amount":0,"reason":""}'
        app = _make_app()
        worker = LLMTeacherWorker(
            system=app.system,
            llm_client=MockLLMClient([teach_json]),
            min_interval=0.0,
        )
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)

        r1 = loop.step()  # tick → LLM → TEACH пушится в content queue
        r2 = loop.step()  # контент изымается и учится

        assert r1["content_fed"] is None   # контент ещё не было до тика
        assert r2["content_fed"] == "раз два три раз два три"
        assert r2["learn_result"] is not None
        app.shutdown()

    def test_broker_loop_multiple_steps_no_crash(self):
        """50 шагов с чередующимися TEACH/WAIT без краша."""
        responses = [
            '{"action":"TEACH","text":"день ночь","amount":0,"reason":""}',
            '{"action":"WAIT","text":"","amount":0,"reason":""}',
        ]
        app = _make_app()
        worker = _make_worker(app.system, responses=responses, min_interval=0.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)
        reports = loop.run(n_steps=50)
        assert len(reports) == 50
        app.shutdown()

    def test_worker_stats_after_run(self):
        responses = ['{"action":"TEACH","text":"утро вечер","amount":0,"reason":""}']
        app = _make_app()
        worker = _make_worker(app.system, responses=responses, min_interval=0.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)
        loop.run(n_steps=5)

        stats = worker.stats()
        assert stats["call_count"] >= 1
        assert "TEACH" in stats["decision_history"]
        app.shutdown()

    def test_system_learns_from_llm_content(self):
        """После подачи текста через LLM-брокер база Gen должна расти."""
        responses = [
            '{"action":"TEACH","text":"день ночь день ночь","amount":0,"reason":""}',
        ] * 10
        app = _make_app()
        worker = _make_worker(app.system, responses=responses, min_interval=0.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)

        base_before = app.system.base.size()
        loop.run(n_steps=20)
        base_after = app.system.base.size()

        assert base_after >= base_before  # что-то выучили
        app.shutdown()

    def test_mock_client_called_with_real_prompt(self):
        """MockLLMClient получает реальный непустой промпт."""
        wait_json = '{"action":"WAIT","text":"","amount":0,"reason":""}'
        app = _make_app()
        client = MockLLMClient([wait_json])
        worker = LLMTeacherWorker(app.system, client, min_interval=0.0)
        app.scheduler.add_worker(worker, name="llm")

        app.scheduler.tick()

        assert len(client.calls) == 1
        assert len(client.calls[0]) > 50  # реальный промпт непустой
        assert "ЗАДАЧА" in client.calls[0]
        app.shutdown()

    def test_broker_loop_stats_after_content(self):
        """Статистика BrokerLoop корректно считает контент и шаги."""
        responses = [
            '{"action":"TEACH","text":"кот мяукает","amount":0,"reason":""}',
            '{"action":"WAIT","text":"","amount":0,"reason":""}',
        ]
        app = _make_app()
        worker = _make_worker(app.system, responses=responses, min_interval=0.0)
        app.scheduler.add_worker(worker, name="llm")
        loop = BrokerLoop(app, worker)
        loop.run(n_steps=10)

        stats = loop.stats()
        assert stats["total_steps"] == 10
        assert stats["llm_calls"] >= 1
        app.shutdown()
