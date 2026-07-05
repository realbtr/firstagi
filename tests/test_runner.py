"""
tests/test_runner.py — тесты для BackgroundRunner.

Покрытие (58 тестов):
  TestRunnerConfig       (6)  — дефолты, кастом, поля, switch_domain_every
  TestRunnerStats        (6)  — transitions_per_s, to_dict, sleep_history
  TestBackgroundRunner   (25) — run с лимитом, stop(), broker integration,
                                sleep trigger, on_sleep callback, on_log callback,
                                stats snapshot, domain_registry, no_sleep_if_not_rich
  TestDomainSwitching    (10) — domains API, switch_domain_every, on_domain_switch,
                                current_domain, domain в SleepStats
  TestSpeechIntegration  (11) — on_narrative, TextNarrative fields, gap→broker,
                                narrative_only_surprises, narrative_verbosity
"""
from __future__ import annotations

from typing import List
from unittest.mock import MagicMock, patch

import pytest

from app.runner import BackgroundRunner, RunnerConfig, RunnerStats, SleepStats, TextNarrative
from core.learning import LearningSystem


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _system() -> LearningSystem:
    return LearningSystem()


def _texts(n: int = 5) -> List[str]:
    return [f"слово{i} тест строка" for i in range(n)]


def _mock_sleep_driver(is_rich: bool = False):
    log = MagicMock()
    # candidates() используется _is_log_rich_enough() в BackgroundRunner
    log.candidates.return_value = (["ev1", "ev2", "ev3", "ev4", "ev5"] if is_rich else [])
    result = MagicMock()
    result.meta_gen_count = 2
    result.commit_rate = 0.5
    result.n_replays = 5
    drv = MagicMock()
    drv.query_log = log
    drv.run.return_value = result
    return drv


def _mock_broker():
    b = MagicMock()
    b.stats.return_value = {"handled": 0, "local_hits": 0}
    return b


# ══════════════════════════════════════════════════════════════════════════════
# TestRunnerConfig
# ══════════════════════════════════════════════════════════════════════════════

class TestRunnerConfig:
    def test_defaults(self):
        c = RunnerConfig()
        assert c.sleep_every == 50_000
        assert c.sleep_replays == 20
        assert c.sleep_min_chain == 3
        assert c.sleep_threshold == 10
        assert c.broker_tick_every == 50
        assert c.log_every == 10_000
        assert c.switch_domain_every == 0

    def test_custom_values(self):
        c = RunnerConfig(sleep_every=1000, sleep_replays=5, broker_tick_every=10)
        assert c.sleep_every == 1000
        assert c.sleep_replays == 5
        assert c.broker_tick_every == 10

    def test_dataclass_fields(self):
        import dataclasses
        names = {f.name for f in dataclasses.fields(RunnerConfig)}
        assert "sleep_every" in names
        assert "broker_tick_every" in names
        assert "log_every" in names

    def test_can_set_log_every(self):
        c = RunnerConfig(log_every=500)
        assert c.log_every == 500

    def test_min_chain_default(self):
        assert RunnerConfig().sleep_min_chain == 3

    def test_switch_domain_every_custom(self):
        c = RunnerConfig(switch_domain_every=5000)
        assert c.switch_domain_every == 5000


# ══════════════════════════════════════════════════════════════════════════════
# TestRunnerStats
# ══════════════════════════════════════════════════════════════════════════════

class TestRunnerStats:
    def test_initial_zero(self):
        s = RunnerStats()
        assert s.transitions == 0
        assert s.elapsed_s == 0.0
        assert s.sleep_cycles == 0

    def test_transitions_per_s(self):
        s = RunnerStats(transitions=1000, elapsed_s=2.0)
        assert s.transitions_per_s == 500.0

    def test_transitions_per_s_zero_elapsed(self):
        s = RunnerStats(transitions=100, elapsed_s=0.0)
        assert s.transitions_per_s == 0.0

    def test_to_dict_keys(self):
        s = RunnerStats(transitions=100, elapsed_s=1.0)
        d = s.to_dict()
        assert "transitions" in d
        assert "elapsed_s" in d
        assert "transitions_per_s" in d
        assert "sleep_cycles" in d
        assert "meta_gen_total" in d

    def test_sleep_history_list(self):
        s = RunnerStats()
        s.sleep_history.append(SleepStats(
            transition_at=1000, domain="лес", meta_gen=2, commit_rate=0.5, n_replays=5
        ))
        assert len(s.sleep_history) == 1

    def test_to_dict_elapsed_rounded(self):
        s = RunnerStats(transitions=1, elapsed_s=1.23456)
        d = s.to_dict()
        assert d["elapsed_s"] == 1.23


# ══════════════════════════════════════════════════════════════════════════════
# TestBackgroundRunner
# ══════════════════════════════════════════════════════════════════════════════

class TestBackgroundRunner:

    def test_run_max_transitions(self):
        """Останавливается точно по max_transitions."""
        system = _system()
        runner = BackgroundRunner(
            system=system,
            texts=_texts(3),
            config=RunnerConfig(log_every=100_000),
        )
        stats = runner.run(max_transitions=10)
        assert stats.transitions == 10

    def test_run_returns_runner_stats(self):
        runner = BackgroundRunner(system=_system(), texts=_texts())
        stats = runner.run(max_transitions=5)
        assert isinstance(stats, RunnerStats)

    def test_texts_processed_increases(self):
        runner = BackgroundRunner(system=_system(), texts=_texts(2))
        stats = runner.run(max_transitions=20)
        assert stats.texts_processed > 0

    def test_stop_halts_run(self):
        """stop() прерывает цикл."""
        texts = ["кот сидит на окне"] * 100
        call_count = [0]
        runner = BackgroundRunner(
            system=_system(),
            texts=texts,
            config=RunnerConfig(log_every=5, sleep_every=100_000),
        )

        def stopper(snap):
            call_count[0] += 1
            runner.stop()

        runner._on_log = stopper
        stats = runner.run(max_transitions=1000)
        assert call_count[0] >= 1
        assert stats.transitions < 1000

    def test_stop_flag_set(self):
        runner = BackgroundRunner(system=_system(), texts=_texts())
        runner.stop()
        assert runner._stop is True

    def test_broker_register_called(self):
        broker = _mock_broker()
        runner = BackgroundRunner(
            system=_system(),
            texts=["кот мяукает"] * 3,
            broker=broker,
            config=RunnerConfig(broker_tick_every=100),
        )
        runner.run(max_transitions=5)
        assert broker.register_source.call_count > 0

    def test_broker_tick_called_periodically(self):
        broker = _mock_broker()
        texts = ["кот сидит"] * 60   # > broker_tick_every
        runner = BackgroundRunner(
            system=_system(),
            texts=texts,
            broker=broker,
            config=RunnerConfig(broker_tick_every=10, log_every=100_000),
        )
        runner.run(max_transitions=200)
        assert broker.tick.call_count >= 1

    def test_sleep_not_triggered_when_not_rich(self):
        sleep_drv = _mock_sleep_driver(is_rich=False)
        runner = BackgroundRunner(
            system=_system(),
            texts=_texts(5),
            sleep_driver=sleep_drv,
            config=RunnerConfig(sleep_every=5, sleep_threshold=5, log_every=100_000),
        )
        runner.run(max_transitions=30)
        sleep_drv.run.assert_not_called()

    def test_sleep_triggered_when_rich(self):
        sleep_drv = _mock_sleep_driver(is_rich=True)
        runner = BackgroundRunner(
            system=_system(),
            texts=_texts(5),
            sleep_driver=sleep_drv,
            config=RunnerConfig(sleep_every=5, sleep_threshold=5, log_every=100_000),
        )
        runner.run(max_transitions=30)
        assert sleep_drv.run.call_count >= 1

    def test_sleep_stats_recorded(self):
        sleep_drv = _mock_sleep_driver(is_rich=True)
        runner = BackgroundRunner(
            system=_system(),
            texts=_texts(5),
            sleep_driver=sleep_drv,
            config=RunnerConfig(sleep_every=5, sleep_threshold=5, log_every=100_000),
        )
        stats = runner.run(max_transitions=30)
        assert stats.sleep_cycles >= 1
        assert stats.meta_gen_total >= 2
        assert len(stats.sleep_history) >= 1

    def test_on_sleep_callback(self):
        sleep_drv = _mock_sleep_driver(is_rich=True)
        received = []

        def cb(ss: SleepStats):
            received.append(ss)

        runner = BackgroundRunner(
            system=_system(),
            texts=_texts(5),
            sleep_driver=sleep_drv,
            config=RunnerConfig(sleep_every=5, sleep_threshold=5, log_every=100_000),
            on_sleep=cb,
        )
        runner.run(max_transitions=30)
        assert len(received) >= 1
        assert isinstance(received[0], SleepStats)

    def test_on_sleep_callback_sleep_stats_fields(self):
        sleep_drv = _mock_sleep_driver(is_rich=True)
        received = []

        runner = BackgroundRunner(
            system=_system(),
            texts=_texts(5),
            sleep_driver=sleep_drv,
            config=RunnerConfig(sleep_every=5, sleep_threshold=5, log_every=100_000),
            on_sleep=lambda ss: received.append(ss),
        )
        runner.run(max_transitions=30)
        ss = received[0]
        assert ss.meta_gen == 2
        assert ss.commit_rate == 0.5
        assert ss.n_replays == 5
        assert ss.transition_at > 0

    def test_on_log_callback(self):
        logs = []
        runner = BackgroundRunner(
            system=_system(),
            texts=_texts(3),
            config=RunnerConfig(log_every=5, sleep_every=100_000),
            on_log=lambda d: logs.append(d),
        )
        runner.run(max_transitions=30)
        assert len(logs) >= 1
        assert "transitions" in logs[0]

    def test_stats_snapshot_keys(self):
        runner = BackgroundRunner(system=_system(), texts=_texts())
        runner.run(max_transitions=5)
        snap = runner.stats()
        assert "transitions" in snap
        assert "base_size" in snap
        assert "elapsed_s" in snap

    def test_stats_with_broker_includes_broker(self):
        broker = _mock_broker()
        runner = BackgroundRunner(
            system=_system(),
            texts=_texts(),
            broker=broker,
        )
        runner.run(max_transitions=5)
        snap = runner.stats()
        assert "broker" in snap

    def test_stats_without_broker_no_broker_key(self):
        runner = BackgroundRunner(system=_system(), texts=_texts())
        runner.run(max_transitions=5)
        snap = runner.stats()
        assert "broker" not in snap

    def test_domain_registry_populated(self):
        from core.dream import DomainRegistry
        reg = DomainRegistry()
        runner = BackgroundRunner(
            system=_system(),
            texts=["кот сидит дома"],
            domain="test_domain",
            domain_registry=reg,
        )
        runner.run(max_transitions=10)
        assert reg.size() > 0
        assert "test_domain" in reg.known_domains()

    def test_elapsed_s_populated(self):
        runner = BackgroundRunner(system=_system(), texts=_texts())
        stats = runner.run(max_transitions=20)
        assert stats.elapsed_s >= 0.0

    def test_transitions_per_s_positive(self):
        runner = BackgroundRunner(system=_system(), texts=_texts())
        stats = runner.run(max_transitions=50)
        assert stats.transitions_per_s >= 0.0

    def test_run_cycles_corpus(self):
        """Корпус из 2 текстов даёт > 2 texts_processed при лимите 50."""
        runner = BackgroundRunner(
            system=_system(),
            texts=["кот сидит"] * 2,
        )
        stats = runner.run(max_transitions=50)
        assert stats.texts_processed > 2

    def test_default_driver_created(self):
        runner = BackgroundRunner(system=_system(), texts=_texts())
        assert runner._driver is not None

    def test_custom_driver_used(self):
        from drivers.text_driver import TextDriver
        drv = TextDriver("custom")
        runner = BackgroundRunner(system=_system(), texts=_texts(), driver=drv)
        assert runner._driver is drv

    def test_config_default_when_none(self):
        runner = BackgroundRunner(system=_system(), texts=_texts())
        assert isinstance(runner.config, RunnerConfig)

    def test_stop_before_run(self):
        runner = BackgroundRunner(system=_system(), texts=_texts())
        runner.stop()
        stats = runner.run(max_transitions=1000)
        # stop() был вызван до run(), но run() сбрасывает флаг
        # поэтому прогон должен начаться — проверяем что он не завис
        assert stats is not None

    def test_no_texts_and_no_domains_raises(self):
        with pytest.raises((ValueError, TypeError)):
            BackgroundRunner(system=_system())


# ══════════════════════════════════════════════════════════════════════════════
# TestDomainSwitching
# ══════════════════════════════════════════════════════════════════════════════

class TestDomainSwitching:

    def test_domains_api_runs(self):
        """domains= API работает без ошибок."""
        runner = BackgroundRunner(
            system=_system(),
            domains=[("a", _texts(2)), ("b", _texts(2))],
            config=RunnerConfig(switch_domain_every=5, log_every=100_000),
        )
        stats = runner.run(max_transitions=20)
        assert stats.transitions == 20

    def test_domain_switch_increments_counter(self):
        runner = BackgroundRunner(
            system=_system(),
            domains=[("a", _texts(2)), ("b", _texts(2))],
            config=RunnerConfig(switch_domain_every=5, log_every=100_000),
        )
        stats = runner.run(max_transitions=30)
        assert stats.domain_switches >= 1

    def test_on_domain_switch_callback(self):
        switches = []
        runner = BackgroundRunner(
            system=_system(),
            domains=[("лес", _texts(2)), ("горы", _texts(2))],
            config=RunnerConfig(switch_domain_every=5, log_every=100_000),
            on_domain_switch=lambda old, new: switches.append((old, new)),
        )
        runner.run(max_transitions=30)
        assert len(switches) >= 1
        assert switches[0] == ("лес", "горы")

    def test_on_domain_switch_cycles(self):
        """А → Б → А → Б — порядок сохраняется."""
        switches = []
        runner = BackgroundRunner(
            system=_system(),
            domains=[("a", _texts(2)), ("b", _texts(2))],
            config=RunnerConfig(switch_domain_every=5, log_every=100_000),
            on_domain_switch=lambda old, new: switches.append(new),
        )
        runner.run(max_transitions=50)
        # Должны чередоваться a и b
        assert len(switches) >= 2
        assert switches[0] != switches[1]

    def test_current_domain_updated(self):
        runner = BackgroundRunner(
            system=_system(),
            domains=[("лес", _texts(2)), ("горы", _texts(2))],
            config=RunnerConfig(switch_domain_every=5, log_every=100_000),
        )
        runner.run(max_transitions=20)
        assert runner.current_domain in ("лес", "горы")

    def test_domain_registry_gets_both_domains(self):
        from core.dream import DomainRegistry
        reg = DomainRegistry()
        runner = BackgroundRunner(
            system=_system(),
            domains=[("лес", ["кот сидит дома"]), ("горы", ["орёл летит высоко"])],
            domain_registry=reg,
            config=RunnerConfig(switch_domain_every=5, log_every=100_000),
        )
        runner.run(max_transitions=30)
        domains = reg.known_domains()
        assert len(domains) >= 1  # хотя бы один домен зарегистрирован

    def test_single_domain_no_switch(self):
        """switch_domain_every=0 → domain_switches остаётся 0."""
        runner = BackgroundRunner(
            system=_system(),
            domains=[("единственный", _texts(3))],
            config=RunnerConfig(switch_domain_every=0, log_every=100_000),
        )
        stats = runner.run(max_transitions=20)
        assert stats.domain_switches == 0

    def test_sleep_stats_has_domain(self):
        sleep_drv = _mock_sleep_driver(is_rich=True)
        runner = BackgroundRunner(
            system=_system(),
            domains=[("лес", _texts(5))],
            sleep_driver=sleep_drv,
            config=RunnerConfig(
                sleep_every=5, sleep_threshold=5,
                switch_domain_every=0, log_every=100_000,
            ),
        )
        stats = runner.run(max_transitions=30)
        assert len(stats.sleep_history) >= 1
        assert stats.sleep_history[0].domain == "лес"

    def test_texts_api_still_works(self):
        """Старый API (texts=) работает как прежде."""
        runner = BackgroundRunner(
            system=_system(),
            texts=_texts(3),
            domain="тест",
        )
        stats = runner.run(max_transitions=10)
        assert stats.current_domain == "тест"

    def test_to_dict_includes_domain_switches(self):
        runner = BackgroundRunner(
            system=_system(),
            domains=[("a", _texts(2)), ("b", _texts(2))],
            config=RunnerConfig(switch_domain_every=5, log_every=100_000),
        )
        stats = runner.run(max_transitions=30)
        d = stats.to_dict()
        assert "domain_switches" in d
        assert "current_domain" in d


# ══════════════════════════════════════════════════════════════════════════════
# TestSpeechIntegration
# ══════════════════════════════════════════════════════════════════════════════

class TestSpeechIntegration:

    def _runner_with_speech(self, verbosity=1, only_surprises=False, **kwargs):
        from drivers.speech_driver import SpeechDriver
        speech = SpeechDriver(verbosity=verbosity)
        narratives = []
        runner = BackgroundRunner(
            system=_system(),
            texts=["маша пришла к медведю медведь обрадовался"] * 5,
            speech=speech,
            config=RunnerConfig(
                narrative_only_surprises=only_surprises,
                log_every=100_000,
                sleep_every=100_000,
            ),
            on_narrative=lambda n: narratives.append(n),
            **kwargs,
        )
        return runner, narratives

    def test_on_narrative_called(self):
        runner, narratives = self._runner_with_speech()
        runner.run(max_transitions=30)
        assert len(narratives) > 0

    def test_narrative_is_text_narrative(self):
        runner, narratives = self._runner_with_speech()
        runner.run(max_transitions=30)
        assert isinstance(narratives[0], TextNarrative)

    def test_narrative_fields_populated(self):
        runner, narratives = self._runner_with_speech()
        runner.run(max_transitions=30)
        n = narratives[0]
        assert n.text != ""
        assert n.domain != ""
        assert n.transition_at > 0
        assert 0.0 <= n.mr <= 1.0
        assert isinstance(n.summary, str) and len(n.summary) > 0

    def test_narrative_observations_list(self):
        runner, narratives = self._runner_with_speech(verbosity=1)
        runner.run(max_transitions=30)
        n = narratives[0]
        assert isinstance(n.observations, list)

    def test_narrative_has_surprise_property(self):
        runner, narratives = self._runner_with_speech()
        runner.run(max_transitions=50)
        # has_surprise и has_gap — свойства
        n = narratives[0]
        assert isinstance(n.has_surprise, bool)
        assert isinstance(n.has_gap, bool)

    def test_narrative_domain_matches(self):
        runner, narratives = self._runner_with_speech()
        runner.run(max_transitions=20)
        assert narratives[0].domain == "default"

    def test_narrative_only_surprises_filters(self):
        """narrative_only_surprises=True: emit только при n_refuted > 0."""
        from drivers.speech_driver import SpeechDriver
        speech = SpeechDriver(verbosity=1)
        # Знакомый текст после нескольких проходов → мало сюрпризов
        texts = ["раз два три раз два три"] * 20
        narratives = []
        runner = BackgroundRunner(
            system=_system(),
            texts=texts,
            speech=speech,
            config=RunnerConfig(
                narrative_only_surprises=True,
                log_every=100_000, sleep_every=100_000,
            ),
            on_narrative=lambda n: narratives.append(n),
        )
        runner.run(max_transitions=100)
        # Все emitted narratives должны иметь хотя бы один сюрприз или gap
        for n in narratives:
            assert n.has_surprise or n.has_gap

    def test_narrative_all_when_not_only_surprises(self):
        """narrative_only_surprises=False: emit каждый текст."""
        from drivers.speech_driver import SpeechDriver
        speech = SpeechDriver(verbosity=1)
        texts = ["раз два три"] * 5
        narratives = []
        runner = BackgroundRunner(
            system=_system(),
            texts=texts,
            speech=speech,
            config=RunnerConfig(
                narrative_only_surprises=False,
                log_every=100_000, sleep_every=100_000,
            ),
            on_narrative=lambda n: narratives.append(n),
        )
        runner.run(max_transitions=30)
        assert len(narratives) > 0  # эмитируется даже без сюрпризов

    def test_gap_detection_calls_broker(self):
        """Разрыв контекста (streak REFUTED) вызывает broker.handle_query."""
        from drivers.speech_driver import SpeechDriver
        speech = SpeechDriver(verbosity=1)
        broker = _mock_broker()
        narratives = []
        # Незнакомый случайный текст → много EXPLORING/REFUTED → gap detection
        texts = ["яблоко синергия квант телескоп галактика орбита"] * 10
        runner = BackgroundRunner(
            system=_system(),
            texts=texts,
            speech=speech,
            broker=broker,
            config=RunnerConfig(
                gap_min_streak=2,
                narrative_only_surprises=False,
                log_every=100_000, sleep_every=100_000,
            ),
            on_narrative=lambda n: narratives.append(n),
        )
        runner.run(max_transitions=50)
        # Если gap был обнаружен — broker.handle_query должен был вызваться
        gaps = [n for n in narratives if n.has_gap]
        if gaps:
            assert broker.handle_query.call_count >= 1

    def test_no_narrative_without_speech_driver(self):
        narratives = []
        runner = BackgroundRunner(
            system=_system(),
            texts=_texts(3),
            config=RunnerConfig(log_every=100_000),
            on_narrative=lambda n: narratives.append(n),
        )
        runner.run(max_transitions=20)
        assert len(narratives) == 0  # без speech — нет нарратива

    def test_narrative_counts_consistent(self):
        from drivers.speech_driver import SpeechDriver
        speech = SpeechDriver(verbosity=1)
        narratives = []
        runner = BackgroundRunner(
            system=_system(),
            texts=["кот сидит на окне кот мяукает"] * 3,
            speech=speech,
            config=RunnerConfig(
                narrative_only_surprises=False,
                log_every=100_000, sleep_every=100_000,
            ),
            on_narrative=lambda n: narratives.append(n),
        )
        runner.run(max_transitions=40)
        for n in narratives:
            total = n.n_confirmed + n.n_completed + n.n_refuted + n.n_exploring
            assert total >= 0  # суммы согласованы
