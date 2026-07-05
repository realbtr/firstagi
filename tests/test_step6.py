"""
Шаг 6: тесты PeripheralManager, NarrativeVoice, SessionManager,
TeacherScheduler, CoreApplication, HTTP API (FastAPI TestClient).
"""

from __future__ import annotations

import os
import sys
import tempfile
import time

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.learning import LearningSystem
from core.peripheral import PeripheralManager
from core.narrative import NarrativeVoice
from core.session import SessionManager
from core.scheduler import TeacherScheduler, MockTeacherWorker, TeacherWorker
from core.app import CoreApplication
from core.teacher import RewardOrder
from drivers.text_driver import TextDriver
from drivers.sequence_driver import SequenceDriver


# ══════════════════════════════════════════════════════════════════════
# Вспомогательные фабрики

def _make_system() -> LearningSystem:
    return LearningSystem(feature_tolerance=0.3, min_gen_count=2)


def _trained_system() -> LearningSystem:
    """Система с минимальным обучением (несколько Gen в базе)."""
    sys_ = _make_system()
    driver = TextDriver("t", lowercase=True)
    texts = ["кот сидит на окне", "кот сидит на окне", "кот сидит на диване"]
    driver.build_vocab(texts)
    for text in texts:
        tokens = list(driver.produce(text))
        sys_.process_stream(tokens)
        sys_.reset_context()
    return sys_


# ══════════════════════════════════════════════════════════════════════
# TestPeripheralManager

class TestPeripheralManager:
    def test_register_and_driver_ids(self):
        sys_ = _make_system()
        mgr = PeripheralManager(sys_)
        d1 = TextDriver("d1")
        d2 = TextDriver("d2")
        mgr.register(d1)
        mgr.register(d2)
        assert "d1" in mgr.driver_ids()
        assert "d2" in mgr.driver_ids()

    def test_register_priority_order(self):
        sys_ = _make_system()
        mgr = PeripheralManager(sys_)
        mgr.register(TextDriver("low"), priority=1)
        mgr.register(TextDriver("high"), priority=10)
        assert mgr.driver_ids()[0] == "high"

    def test_unregister(self):
        sys_ = _make_system()
        mgr = PeripheralManager(sys_)
        mgr.register(TextDriver("d1"))
        mgr.unregister("d1")
        assert "d1" not in mgr.driver_ids()

    def test_unregister_nonexistent_ok(self):
        sys_ = _make_system()
        mgr = PeripheralManager(sys_)
        mgr.unregister("nonexistent")   # не поднимает

    def test_get(self):
        sys_ = _make_system()
        mgr = PeripheralManager(sys_)
        d = TextDriver("d1")
        mgr.register(d)
        assert mgr.get("d1") is d
        assert mgr.get("nope") is None

    def test_len(self):
        sys_ = _make_system()
        mgr = PeripheralManager(sys_)
        mgr.register(TextDriver("d1"))
        mgr.register(TextDriver("d2"))
        assert len(mgr) == 2

    def test_process_returns_results(self):
        sys_ = _make_system()
        mgr = PeripheralManager(sys_)
        driver = TextDriver("t", lowercase=True)
        driver.build_vocab(["кот сидит на окне"])
        mgr.register(driver)
        results = mgr.process("t", text="кот сидит на окне")
        assert isinstance(results, list)
        assert len(results) > 0

    def test_process_unknown_driver_raises(self):
        sys_ = _make_system()
        mgr = PeripheralManager(sys_)
        with pytest.raises(KeyError):
            mgr.process("nope")

    def test_process_all_returns_dict(self):
        sys_ = _make_system()
        mgr = PeripheralManager(sys_)
        driver = TextDriver("t", lowercase=True)
        driver.build_vocab(["раз два три"])
        mgr.register(driver)
        results = mgr.process_all(text="раз два три")
        assert "t" in results
        assert isinstance(results["t"], list)

    def test_reset_all(self):
        sys_ = _make_system()
        mgr = PeripheralManager(sys_)
        driver = TextDriver("t", lowercase=True)
        driver.build_vocab(["раз два"])
        mgr.register(driver)
        mgr.process("t", text="раз два")
        mgr.reset_all()   # не поднимает

    def test_sequence_driver_registered(self):
        sys_ = _make_system()
        mgr = PeripheralManager(sys_)
        seq = SequenceDriver("seq", sequence=[1.0, 2.0, 3.0])
        mgr.register(seq)
        assert "seq" in mgr.driver_ids()
        results = mgr.process("seq")
        assert isinstance(results, list)


# ══════════════════════════════════════════════════════════════════════
# TestNarrativeVoice

class TestNarrativeVoice:
    def test_resource_report_is_str(self):
        sys_ = _trained_system()
        v = NarrativeVoice(sys_)
        r = v.resource_report()
        assert isinstance(r, str)
        assert "Ресурс" in r

    def test_resource_report_contains_level(self):
        sys_ = _make_system()
        v = NarrativeVoice(sys_)
        r = v.resource_report()
        assert "уровень=" in r

    def test_event_report_confirmed(self):
        from core.algorithm import StepOutcome, StepResult
        from core.generalization import PeripheralToken
        sys_ = _trained_system()
        v = NarrativeVoice(sys_)
        token = PeripheralToken.new("t", data=None)
        result = StepResult(outcome=StepOutcome.CONFIRMED, token=token)
        r = v.event_report(result)
        assert "подтверждён" in r

    def test_event_report_refuted_shows_new_gen(self):
        from core.algorithm import StepOutcome, StepResult
        from core.generalization import PeripheralToken
        sys_ = _trained_system()
        v = NarrativeVoice(sys_)
        token = PeripheralToken.new("t", data=None)
        result = StepResult(
            outcome=StepOutcome.REFUTED,
            token=token,
            new_gen_id="abc12345-test",
        )
        r = v.event_report(result)
        assert "abc12345" in r

    def test_attractor_report_empty(self):
        sys_ = _make_system()
        v = NarrativeVoice(sys_)
        r = v.attractor_report()
        assert "пуст" in r or "нет" in r

    def test_attractor_report_with_data(self):
        sys_ = _trained_system()
        v = NarrativeVoice(sys_)
        r = v.attractor_report()
        assert isinstance(r, str)
        assert len(r) > 0

    def test_state_report_contains_sections(self):
        sys_ = _trained_system()
        v = NarrativeVoice(sys_)
        r = v.state_report()
        assert "Обобщений" in r
        assert "Ресурс" in r

    def test_summary_default_lines(self):
        sys_ = _trained_system()
        v = NarrativeVoice(sys_)
        s = v.summary()
        assert isinstance(s, str)
        lines = s.strip().split("\n")
        assert len(lines) <= 10

    def test_summary_max_lines_respected(self):
        sys_ = _trained_system()
        v = NarrativeVoice(sys_)
        s = v.summary(max_lines=2)
        lines = s.strip().split("\n")
        assert len(lines) <= 2

    def test_summary_contains_base_size(self):
        sys_ = _trained_system()
        v = NarrativeVoice(sys_)
        s = v.summary()
        assert "База:" in s


# ══════════════════════════════════════════════════════════════════════
# TestSessionManager

class TestSessionManager:
    @pytest.fixture
    def tmpdir(self, tmp_path):
        return str(tmp_path)

    def test_save_creates_file(self, tmpdir):
        mgr = SessionManager(tmpdir)
        sys_ = _trained_system()
        path = mgr.save("test_session", sys_)
        assert os.path.exists(path)

    def test_load_roundtrip(self, tmpdir):
        mgr = SessionManager(tmpdir)
        sys_ = _trained_system()
        original_size = sys_.base.size()
        mgr.save("roundtrip", sys_)
        loaded, meta = mgr.load("roundtrip")
        assert loaded.base.size() == original_size

    def test_metadata_preserved(self, tmpdir):
        mgr = SessionManager(tmpdir)
        sys_ = _make_system()
        mgr.save("meta_test", sys_, metadata={"notes": "тест"})
        _, meta = mgr.load("meta_test")
        assert meta.get("notes") == "тест"

    def test_metadata_has_stats(self, tmpdir):
        mgr = SessionManager(tmpdir)
        sys_ = _trained_system()
        mgr.save("stats_test", sys_)
        _, meta = mgr.load("stats_test")
        assert "base_size" in meta
        assert "steps" in meta

    def test_exists_true(self, tmpdir):
        mgr = SessionManager(tmpdir)
        sys_ = _make_system()
        mgr.save("exists_ok", sys_)
        assert mgr.exists("exists_ok") is True

    def test_exists_false(self, tmpdir):
        mgr = SessionManager(tmpdir)
        assert mgr.exists("no_such") is False

    def test_list_sessions(self, tmpdir):
        mgr = SessionManager(tmpdir)
        sys_ = _make_system()
        mgr.save("s1", sys_)
        mgr.save("s2", sys_)
        sessions = mgr.list_sessions()
        names = [s["name"] for s in sessions]
        assert "s1" in names and "s2" in names

    def test_list_sorted_newest_first(self, tmpdir):
        mgr = SessionManager(tmpdir)
        sys_ = _make_system()
        mgr.save("first", sys_)
        time.sleep(0.01)
        mgr.save("second", sys_)
        sessions = mgr.list_sessions()
        assert sessions[0]["name"] == "second"

    def test_delete(self, tmpdir):
        mgr = SessionManager(tmpdir)
        sys_ = _make_system()
        mgr.save("to_delete", sys_)
        mgr.delete("to_delete")
        assert not mgr.exists("to_delete")

    def test_delete_nonexistent_raises(self, tmpdir):
        mgr = SessionManager(tmpdir)
        with pytest.raises(FileNotFoundError):
            mgr.delete("nope")

    def test_latest(self, tmpdir):
        mgr = SessionManager(tmpdir)
        sys_ = _make_system()
        mgr.save("a", sys_)
        time.sleep(0.01)
        mgr.save("b", sys_)
        assert mgr.latest() == "b"

    def test_latest_empty(self, tmpdir):
        mgr = SessionManager(tmpdir)
        assert mgr.latest() is None

    def test_invalid_name_raises(self, tmpdir):
        mgr = SessionManager(tmpdir)
        sys_ = _make_system()
        with pytest.raises(ValueError):
            mgr.save("", sys_)

    def test_load_missing_raises(self, tmpdir):
        mgr = SessionManager(tmpdir)
        with pytest.raises(FileNotFoundError):
            mgr.load("ghost")


# ══════════════════════════════════════════════════════════════════════
# TestTeacherScheduler

class TestTeacherScheduler:
    def _make_scheduler(self, refuted_threshold=1):
        sys_ = _make_system()
        return (
            sys_,
            TeacherScheduler(sys_.teaching_log, sys_.teacher),
        )

    def test_add_worker(self):
        _, sched = self._make_scheduler()
        sched.add_worker(MockTeacherWorker(), name="m1")
        assert "m1" in sched.worker_names()

    def test_remove_worker(self):
        _, sched = self._make_scheduler()
        sched.add_worker(MockTeacherWorker(), name="m1")
        sched.remove_worker("m1")
        assert "m1" not in sched.worker_names()

    def test_tick_empty_log_returns_zero(self):
        _, sched = self._make_scheduler()
        sched.add_worker(MockTeacherWorker(), name="m")
        assert sched.tick() == 0

    def test_tick_increments_count(self):
        _, sched = self._make_scheduler()
        sched.tick()
        sched.tick()
        assert sched.tick_count == 2

    def test_mock_worker_observe_fires_on_refuted(self):
        """MockTeacherWorker ставит ордер при достаточном количестве REFUTED."""
        sys_ = _make_system()
        # Наполним лог записями с REFUTED
        from core.algorithm import StepOutcome, StepResult
        from core.generalization import PeripheralToken
        from core.resource import ResourceState
        dummy_token = PeripheralToken.new("t", None)
        dummy_result = StepResult(outcome=StepOutcome.REFUTED, token=dummy_token)
        dummy_rs = ResourceState(level=0.5)
        for _ in range(5):
            sys_.teaching_log.log_state(dummy_result, dummy_rs, [])

        sched = TeacherScheduler(sys_.teaching_log, sys_.teacher)
        worker = MockTeacherWorker(refuted_threshold=3)
        sched.add_worker(worker, name="mock")
        pushed = sched.tick()
        assert pushed >= 1
        assert worker.order_count >= 1

    def test_mock_worker_suggest_content_on_low_resource(self):
        """MockTeacherWorker предлагает контент при низком ресурсе."""
        sys_ = _make_system()
        from core.algorithm import StepOutcome, StepResult
        from core.generalization import PeripheralToken
        from core.resource import ResourceState
        dummy_token = PeripheralToken.new("t", None)
        dummy_result = StepResult(outcome=StepOutcome.EXPLORING, token=dummy_token)
        low_rs = ResourceState(level=0.1)
        sys_.teaching_log.log_state(dummy_result, low_rs, [])

        sched = TeacherScheduler(sys_.teaching_log, sys_.teacher)
        worker = MockTeacherWorker(low_resource=0.3)
        sched.add_worker(worker, name="mock")
        pushed = sched.tick()
        assert pushed >= 1
        assert worker.content_count >= 1

    def test_start_stop(self):
        _, sched = self._make_scheduler()
        sched.start(interval=0.05)
        assert sched.is_running
        time.sleep(0.15)
        sched.stop()
        assert not sched.is_running

    def test_double_start_safe(self):
        _, sched = self._make_scheduler()
        sched.start(interval=0.1)
        sched.start(interval=0.1)   # второй вызов безопасен
        assert sched.is_running
        sched.stop()

    def test_mock_worker_protocol(self):
        """MockTeacherWorker реализует протокол TeacherWorker."""
        w = MockTeacherWorker()
        assert isinstance(w, TeacherWorker)


# ══════════════════════════════════════════════════════════════════════
# TestCoreApplication

class TestCoreApplication:
    @pytest.fixture
    def app(self, tmp_path):
        a = CoreApplication(config={
            "sessions_dir": str(tmp_path),
            "mock_teacher": False,
        })
        a.startup()
        yield a
        a.shutdown()

    def test_has_system(self, app):
        assert app.system is not None

    def test_has_peripherals(self, app):
        assert app.peripherals is not None
        assert "text" in app.peripherals.driver_ids()

    def test_has_voice(self, app):
        assert app.voice is not None

    def test_has_sessions(self, app):
        assert app.sessions is not None

    def test_has_scheduler(self, app):
        assert app.scheduler is not None

    def test_learn_returns_dict(self, app):
        result = app.learn("кот сидит на окне")
        assert isinstance(result, dict)
        assert "outcomes" in result
        assert "match_rate" in result
        assert "narrative" in result

    def test_learn_outcomes_not_empty(self, app):
        result = app.learn("раз два три")
        assert len(result["outcomes"]) > 0

    def test_status_returns_dict(self, app):
        status = app.status()
        assert "system" in status
        assert "resource" in status
        assert "drivers" in status

    def test_save_and_load_session(self, app):
        app.learn("кот сидит на окне")
        app.learn("кот сидит на окне")
        original_size = app.system.base.size()
        app.save_session("test_save")
        app.load_session("test_save")
        assert app.system.base.size() == original_size

    def test_add_text_driver(self, app):
        app.add_text_driver("extra")
        assert "extra" in app.peripherals.driver_ids()

    def test_add_sequence_driver(self, app):
        app.add_sequence_driver("seq", sequence=[1.0, 2.0, 3.0])
        assert "seq" in app.peripherals.driver_ids()

    def test_startup_is_idempotent(self, app):
        app.startup()   # второй вызов безопасен

    def test_shutdown_stops_scheduler(self, app):
        app.startup()   # убедиться что запущен
        app.shutdown()
        assert not app.scheduler.is_running


# ══════════════════════════════════════════════════════════════════════
# TestServerRoutes  (FastAPI TestClient)

try:
    from fastapi.testclient import TestClient
    _FASTAPI_AVAILABLE = True
except ImportError:
    _FASTAPI_AVAILABLE = False


@pytest.mark.skipif(not _FASTAPI_AVAILABLE, reason="fastapi not installed")
class TestServerRoutes:
    @pytest.fixture
    def client(self, tmp_path):
        import app.server as srv
        srv._app_instance = CoreApplication(config={
            "sessions_dir": str(tmp_path),
            "mock_teacher": False,
        })
        srv._app_instance.startup()
        with TestClient(srv.api) as c:
            yield c
        srv._app_instance.shutdown()
        srv._app_instance = None

    def test_get_status(self, client):
        resp = client.get("/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "system" in data
        assert "resource" in data

    def test_post_learn(self, client):
        resp = client.post("/learn", json={"text": "кот сидит на окне"})
        assert resp.status_code == 200
        data = resp.json()
        assert "outcomes" in data
        assert "match_rate" in data

    def test_get_narrative(self, client):
        resp = client.get("/narrative")
        assert resp.status_code == 200
        assert "report" in resp.json()

    def test_get_attractors(self, client):
        resp = client.get("/attractors")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert "attractors" in data

    def test_get_base(self, client):
        resp = client.get("/base")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "generalizations" in data

    def test_post_reset(self, client):
        resp = client.post("/reset")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_sessions_list(self, client):
        resp = client.get("/sessions")
        assert resp.status_code == 200
        assert "sessions" in resp.json()

    def test_sessions_save_and_load(self, client):
        # Обучить
        client.post("/learn", json={"text": "кот сидит на окне"})
        # Сохранить
        resp = client.post("/sessions/save", json={"name": "api_test"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        # Загрузить
        resp2 = client.post("/sessions/load", json={"name": "api_test"})
        assert resp2.status_code == 200
        assert resp2.json()["ok"] is True

    def test_sessions_load_missing_returns_404(self, client):
        resp = client.post("/sessions/load", json={"name": "ghost"})
        assert resp.status_code == 404


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
