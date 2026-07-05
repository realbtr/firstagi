"""
Шаг 10: тесты инспектора, симулятора, контроллера драйверов,
CurriculumAgent и DebugSession.

Группы:
  1. GeneralizationInspector   (12 тестов)
  2. PredictiveSimulator        (8 тестов)
  3. DriverController          (12 тестов)
  4. StabilitySchedule          (6 тестов)
  5. CurriculumAgent           (15 тестов)
  6. DebugSession              (12 тестов)
"""

import pytest

from core.learning import LearningSystem
from core.app import CoreApplication
from core.inspector import GeneralizationInspector, PredictiveSimulator, SimulationResult
from core.driver_control import DriverController
from curriculum.agent import StabilitySchedule, CurriculumAgent, CurriculumStep
from curriculum.debug_session import DebugSession


# ══════════════════════════════════════════════════════════════════════
# Фикстуры
# ══════════════════════════════════════════════════════════════════════

CORPUS = [
    "кот сидит на окне",
    "кот спит на диване",
    "собака бежит по улице",
    "птица летит в небе",
    "рыба плывёт в воде",
    "кот ест рыбу",
    "собака ест кость",
]

SHORT_CORPUS = [
    "кот сидит на окне",
    "кот спит на диване",
]


def _trained_app(texts=None) -> CoreApplication:
    """Приложение с предварительным обучением."""
    app = CoreApplication(config={"mock_teacher": False})
    app.startup()
    for text in (texts or CORPUS):
        app.learn(text)
        app.learn(text)   # дважды для консолидации
    return app


def _empty_app() -> CoreApplication:
    app = CoreApplication(config={"mock_teacher": False})
    app.startup()
    return app


# ══════════════════════════════════════════════════════════════════════
# 1. GeneralizationInspector
# ══════════════════════════════════════════════════════════════════════

class TestGeneralizationInspector:

    def test_inspector_creates(self):
        app = _empty_app()
        inspector = GeneralizationInspector(app.system)
        assert inspector.system is app.system

    def test_snapshot_keys(self):
        app = _empty_app()
        inspector = GeneralizationInspector(app.system)
        snap = inspector.snapshot()
        for key in ("stats", "top_gens", "weak_gens", "proposals",
                    "active_gens", "readiness"):
            assert key in snap

    def test_top_gens_empty(self):
        app = _empty_app()
        inspector = GeneralizationInspector(app.system)
        assert inspector.top_gens() == []

    def test_top_gens_after_learning(self):
        app = _trained_app()
        inspector = GeneralizationInspector(app.system)
        top = inspector.top_gens(5)
        assert len(top) > 0
        assert all("significance" in g for g in top)

    def test_top_gens_sorted_descending(self):
        app = _trained_app()
        inspector = GeneralizationInspector(app.system)
        top = inspector.top_gens(10)
        sigs = [g["significance"] for g in top]
        assert sigs == sorted(sigs, reverse=True)

    def test_weak_gens_empty(self):
        app = _empty_app()
        inspector = GeneralizationInspector(app.system)
        assert inspector.weak_gens() == []

    def test_weak_gens_have_low_significance(self):
        app = _trained_app()
        inspector = GeneralizationInspector(app.system)
        weak = inspector.weak_gens(max_significance=0.4)
        for g in weak:
            assert g["significance"] <= 0.4

    def test_gen_dict_fields(self):
        app = _trained_app()
        inspector = GeneralizationInspector(app.system)
        top = inspector.top_gens(1)
        assert len(top) > 0
        g = top[0]
        for field in ("gen_id", "full_id", "label", "chain_len",
                      "success", "stop", "significance", "feature_chain"):
            assert field in g

    def test_readiness_zero_when_empty(self):
        app = _empty_app()
        inspector = GeneralizationInspector(app.system)
        assert inspector.readiness() == 0.0

    def test_readiness_positive_after_learning(self):
        app = _trained_app()
        inspector = GeneralizationInspector(app.system)
        assert inspector.readiness() > 0.0

    def test_gens_by_chain_len(self):
        app = _trained_app()
        inspector = GeneralizationInspector(app.system)
        gens = inspector.gens_by_chain_len(min_len=1, max_len=2)
        for g in gens:
            assert 1 <= g["chain_len"] <= 2

    def test_snapshot_does_not_mutate_state(self):
        app = _trained_app()
        inspector = GeneralizationInspector(app.system)
        size_before = app.system.base.size()
        inspector.snapshot()
        inspector.snapshot()
        assert app.system.base.size() == size_before


# ══════════════════════════════════════════════════════════════════════
# 2. PredictiveSimulator
# ══════════════════════════════════════════════════════════════════════

class TestPredictiveSimulator:

    def test_simulator_returns_result(self):
        app = _empty_app()
        sim = PredictiveSimulator(app.system)
        result = sim.simulate("кот сидит")
        assert isinstance(result, SimulationResult)

    def test_simulate_does_not_mutate_base(self):
        app = _trained_app()
        sim = PredictiveSimulator(app.system)
        size_before  = app.system.base.size()
        steps_before = app.system.engine.step_count
        sim.simulate("кот бежит по улице")
        assert app.system.base.size()        == size_before
        assert app.system.engine.step_count  == steps_before

    def test_simulate_does_not_mutate_context(self):
        app = _trained_app()
        sim = PredictiveSimulator(app.system)
        active_before = app.system.engine.context.active_gen_ids()
        sim.simulate("птица летит")
        active_after  = app.system.engine.context.active_gen_ids()
        assert active_before == active_after

    def test_simulate_result_fields(self):
        app = _empty_app()
        sim = PredictiveSimulator(app.system)
        r = sim.simulate("кот сидит на окне")
        assert hasattr(r, "outcomes")
        assert hasattr(r, "confirmed_features")
        assert hasattr(r, "refuted_count")
        assert hasattr(r, "match_rate")
        assert hasattr(r, "would_create_gens")

    def test_simulate_match_rate_range(self):
        app = _trained_app()
        sim = PredictiveSimulator(app.system)
        r = sim.simulate("кот сидит на окне")
        assert 0.0 <= r.match_rate <= 1.0

    def test_simulate_empty_text(self):
        app = _empty_app()
        sim = PredictiveSimulator(app.system)
        r = sim.simulate("")
        assert r.outcomes == []
        assert r.match_rate == 0.0

    def test_simulate_known_text_better_match(self):
        """После обучения знакомый текст даёт лучший match_rate чем незнакомый."""
        app = _trained_app(["кот сидит на окне"] * 5)
        sim = PredictiveSimulator(app.system)
        r_known   = sim.simulate("кот сидит на окне")
        r_unknown = sim.simulate("зебра прыгает через пропасть")
        assert r_known.match_rate >= r_unknown.match_rate

    def test_simulate_outcomes_are_valid(self):
        valid = {"CONFIRMED", "COMPLETED", "REFUTED", "EXPLORING", "CYCLE_AVOIDED"}
        app = _trained_app()
        sim = PredictiveSimulator(app.system)
        r = sim.simulate("кот спит на диване")
        for outcome in r.outcomes:
            assert outcome in valid


# ══════════════════════════════════════════════════════════════════════
# 3. DriverController
# ══════════════════════════════════════════════════════════════════════

class TestDriverController:

    def test_controller_creates(self):
        app = _empty_app()
        ctrl = DriverController(app)
        assert ctrl._app is app

    def test_get_priorities_returns_dict(self):
        app = _empty_app()
        ctrl = DriverController(app)
        priorities = ctrl.get_driver_priorities()
        assert isinstance(priorities, dict)

    def test_driver_ids_list(self):
        app = _empty_app()
        ctrl = DriverController(app)
        ids = ctrl.driver_ids()
        assert "text" in ids

    def test_set_driver_priority(self):
        app = _empty_app()
        ctrl = DriverController(app)
        ctrl.set_driver_priority("text", 99)
        assert ctrl.get_driver_priorities()["text"] == 99

    def test_set_priority_unknown_driver_raises(self):
        app = _empty_app()
        ctrl = DriverController(app)
        with pytest.raises(KeyError):
            ctrl.set_driver_priority("nonexistent", 10)

    def test_tolerance_override_none_by_default(self):
        app = _empty_app()
        ctrl = DriverController(app)
        assert ctrl.tolerance_override is None

    def test_set_tolerance_override(self):
        app = _empty_app()
        ctrl = DriverController(app)
        ctrl.set_tolerance_override(0.1)
        assert ctrl.tolerance_override == 0.1
        assert app.system.engine.feature_tolerance == pytest.approx(0.1)

    def test_reset_tolerance_override(self):
        app = _empty_app()
        ctrl = DriverController(app)
        ctrl.set_tolerance_override(0.1)
        ctrl.set_tolerance_override(None)
        assert ctrl.tolerance_override is None
        # tolerance восстанавливается к значению от ResourceDriver
        assert app.system.engine.feature_tolerance > 0.0

    def test_get_attention_map_empty(self):
        app = _empty_app()
        ctrl = DriverController(app)
        amap = ctrl.get_attention_map()
        assert isinstance(amap, dict)

    def test_get_attention_map_after_learning(self):
        app = _trained_app(["кот сидит"] * 3)
        ctrl = DriverController(app)
        # После reset_context (вызывается в learn) контекст пуст
        amap = ctrl.get_attention_map()
        assert isinstance(amap, dict)

    def test_known_features_empty(self):
        app = _empty_app()
        ctrl = DriverController(app)
        feats = ctrl.known_features()
        assert isinstance(feats, list)

    def test_inject_feature_unknown(self):
        app = _empty_app()
        ctrl = DriverController(app)
        result = ctrl.inject_feature("nonexistent_feature_id")
        assert result is None

    def test_inject_known_feature(self):
        """После обучения есть known features; инъекция возвращает StepResult."""
        app = _trained_app(["кот сидит"] * 3)
        ctrl = DriverController(app)
        feats = ctrl.known_features()
        if feats:
            result = ctrl.inject_feature(feats[0])
            assert result is not None
            assert hasattr(result, "outcome")

    def test_active_gen_count_int(self):
        app = _empty_app()
        ctrl = DriverController(app)
        assert isinstance(ctrl.active_gen_count(), int)


# ══════════════════════════════════════════════════════════════════════
# 4. StabilitySchedule
# ══════════════════════════════════════════════════════════════════════

class TestStabilitySchedule:

    def test_schedule_defaults(self):
        s = StabilitySchedule()
        assert s.initial   == 1.0
        assert s.final     == 0.1
        assert s.decay     == 0.95
        assert s.threshold == 0.5

    def test_apply_decreases_when_ready(self):
        s = StabilitySchedule(threshold=0.5, decay=0.9)
        new_val = s.apply(1.0, readiness=0.6)
        assert new_val == pytest.approx(0.9)

    def test_apply_no_decrease_when_not_ready(self):
        s = StabilitySchedule(threshold=0.5)
        new_val = s.apply(0.8, readiness=0.3)
        assert new_val == pytest.approx(0.8)

    def test_apply_bounded_by_final(self):
        s = StabilitySchedule(final=0.1, decay=0.5)
        # Многократно применяем: должны остановиться на final
        val = 1.0
        for _ in range(30):
            val = s.apply(val, readiness=1.0)
        assert val >= s.final

    def test_apply_exactly_at_threshold(self):
        s = StabilitySchedule(threshold=0.5, decay=0.8)
        new_val = s.apply(1.0, readiness=0.5)
        assert new_val == pytest.approx(0.8)

    def test_custom_schedule(self):
        s = StabilitySchedule(initial=0.7, final=0.2, decay=0.5, threshold=0.3)
        new_val = s.apply(0.7, readiness=0.4)
        assert new_val == pytest.approx(0.35)


# ══════════════════════════════════════════════════════════════════════
# 5. CurriculumAgent
# ══════════════════════════════════════════════════════════════════════

class TestCurriculumAgent:

    def _make_agent(self, corpus=None, schedule=None, seed=42) -> CurriculumAgent:
        app = _empty_app()
        inspector  = GeneralizationInspector(app.system)
        controller = DriverController(app)
        return CurriculumAgent(
            inspector  = inspector,
            controller = controller,
            app        = app,
            corpus     = corpus or CORPUS,
            schedule   = schedule,
            seed       = seed,
        )

    def test_agent_creates(self):
        agent = self._make_agent()
        assert agent.stability == 1.0
        assert len(agent.corpus) == len(CORPUS)

    def test_assess_readiness_empty(self):
        agent = self._make_agent()
        r = agent.assess_readiness()
        assert 0.0 <= r <= 1.0

    def test_select_texts_returns_list(self):
        agent = self._make_agent()
        texts = agent.select_texts(stability=0.8, n=3)
        assert isinstance(texts, list)
        assert len(texts) <= 3

    def test_select_texts_high_stability(self):
        agent = self._make_agent()
        texts = agent.select_texts(stability=0.9, n=3)
        assert all(t in CORPUS for t in texts)

    def test_select_texts_low_stability(self):
        agent = self._make_agent()
        texts = agent.select_texts(stability=0.1, n=3)
        assert all(t in CORPUS for t in texts)

    def test_select_texts_empty_corpus(self):
        app = _empty_app()
        inspector  = GeneralizationInspector(app.system)
        controller = DriverController(app)
        agent = CurriculumAgent(
            inspector=inspector, controller=controller, app=app, corpus=[],
        )
        assert agent.select_texts(0.5) == []

    def test_step_returns_curriculum_step(self):
        agent = self._make_agent()
        step = agent.step()
        assert isinstance(step, CurriculumStep)

    def test_step_adds_to_history(self):
        agent = self._make_agent()
        agent.step()
        agent.step()
        assert len(agent.history) == 2

    def test_step_step_n_increments(self):
        agent = self._make_agent()
        s0 = agent.step()
        s1 = agent.step()
        assert s0.step_n == 0
        assert s1.step_n == 1

    def test_step_stability_bounded_below(self):
        """Стабильность не опускается ниже schedule.final."""
        schedule = StabilitySchedule(final=0.1, decay=0.5, threshold=0.0)
        agent = self._make_agent(schedule=schedule)
        for _ in range(30):
            agent.step()
        assert agent.stability >= 0.1

    def test_step_stability_non_negative(self):
        agent = self._make_agent()
        for _ in range(10):
            agent.step()
        assert agent.stability >= 0.0

    def test_run_multiple_steps(self):
        agent = self._make_agent()
        steps = agent.run(5)
        assert len(steps) == 5
        assert all(isinstance(s, CurriculumStep) for s in steps)

    def test_stats_before_any_step(self):
        agent = self._make_agent()
        stats = agent.stats()
        assert stats["steps"] == 0
        assert stats["corpus_size"] == len(CORPUS)

    def test_stats_after_steps(self):
        agent = self._make_agent()
        agent.run(3)
        stats = agent.stats()
        assert stats["steps"] == 3

    def test_reset_clears_history(self):
        agent = self._make_agent()
        agent.run(5)
        agent.reset()
        assert len(agent.history) == 0
        assert agent.stability == agent.schedule.initial


# ══════════════════════════════════════════════════════════════════════
# 6. DebugSession
# ══════════════════════════════════════════════════════════════════════

class TestDebugSession:

    def _make_session(self, corpus=None, trained=False) -> DebugSession:
        if trained:
            app = _trained_app()
        else:
            app = _empty_app()
        return DebugSession(app, corpus=corpus or CORPUS)

    def test_session_creates(self):
        session = self._make_session()
        assert session.inspector  is not None
        assert session.simulator  is not None
        assert session.controller is not None
        assert session.curriculum is not None

    def test_inspect_returns_dict(self):
        session = self._make_session()
        snap = session.inspect()
        assert isinstance(snap, dict)
        assert "stats" in snap
        assert "attention" in snap

    def test_predict_does_not_mutate(self):
        session = self._make_session(trained=True)
        size_before = session.app.system.base.size()
        session.predict("кот бежит по крыше")
        assert session.app.system.base.size() == size_before

    def test_predict_returns_dict(self):
        session = self._make_session()
        result = session.predict("кот сидит")
        assert "outcomes" in result
        assert "match_rate" in result
        assert "would_create" in result

    def test_learn_returns_dict(self):
        session = self._make_session()
        result = session.learn("кот сидит на окне")
        assert "confirmed" in result
        assert "match_rate" in result

    def test_weak_returns_list(self):
        session = self._make_session(trained=True)
        weak = session.weak()
        assert isinstance(weak, list)

    def test_top_returns_sorted(self):
        session = self._make_session(trained=True)
        top = session.top(5)
        sigs = [g["significance"] for g in top]
        assert sigs == sorted(sigs, reverse=True)

    def test_set_stability(self):
        session = self._make_session()
        session.set_stability(0.3)
        assert session.curriculum.stability == pytest.approx(0.3)

    def test_set_stability_clamped(self):
        session = self._make_session()
        session.set_stability(999)
        assert session.curriculum.stability == 1.0
        session.set_stability(-5)
        assert session.curriculum.stability == 0.0

    def test_step_curriculum_returns_dict(self):
        session = self._make_session()
        step = session.step_curriculum()
        assert "stability" in step
        assert "match_rates" in step
        assert "new_stability" in step

    def test_run_curriculum_n_steps(self):
        session = self._make_session()
        steps = session.run_curriculum(3)
        assert len(steps) == 3

    def test_log_grows_with_actions(self):
        session = self._make_session()
        assert len(session.log) == 0
        session.learn("кот")
        assert len(session.log) == 1
        session.step_curriculum()
        assert len(session.log) == 2

    def test_log_summary(self):
        session = self._make_session()
        session.learn("кот сидит")
        session.step_curriculum()
        summary = session.log_summary()
        assert summary["learn_calls"]      == 1
        assert summary["curriculum_steps"] == 1

    def test_add_to_corpus(self):
        app = _empty_app()
        session = DebugSession(app, corpus=[])
        assert len(session.curriculum.corpus) == 0
        session.add_to_corpus(["тест один", "тест два"])
        assert len(session.curriculum.corpus) == 2

    def test_readiness_float(self):
        session = self._make_session(trained=True)
        r = session.readiness()
        assert isinstance(r, float)
        assert 0.0 <= r <= 1.0
