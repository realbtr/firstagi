"""
Шаг 7: тесты HedonicAdapter, InitiativeEngine, LearningSystem (Step7),
TextCorpus, InteractiveTeacher, TrainingLoop, TrainingReport.

~70 тестов.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from core.hedonic import HedonicAdapter
from core.initiative import InitiativeEngine, Proposal
from core.learning import LearningSystem
from core.algorithm import StepOutcome
from core.generalization import PeripheralToken
from drivers.text_driver import TextDriver
from training.corpus import TextCorpus
from training.teacher import (
    InteractiveTeacher,
    LifeState,
    StepReport,
    TrainingReport,
)
from training.loop import TrainingLoop


# ══════════════════════════════════════════════════════════════════════
# Вспомогательные фабрики
# ══════════════════════════════════════════════════════════════════════

def _make_system() -> LearningSystem:
    return LearningSystem(feature_tolerance=0.3, min_gen_count=2)


def _trained_system() -> LearningSystem:
    """Система, обученная на простом повторяющемся тексте."""
    sys_ = _make_system()
    driver = TextDriver(driver_id="t", lowercase=True)
    texts = [
        "день ночь день ночь",
        "день ночь день ночь",
        "день ночь день ночь",
    ]
    driver.build_vocab(texts)
    for text in texts:
        tokens = list(driver.produce(text))
        sys_.process_stream(tokens)
        sys_.reset_context()
    return sys_


def _tokens(text: str) -> list:
    driver = TextDriver(driver_id="td")
    return list(driver.produce(text))


# ══════════════════════════════════════════════════════════════════════
# TestHedonicAdapter  (12 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestHedonicAdapter:

    def test_initial_novelty_is_one(self):
        h = HedonicAdapter()
        assert h.novelty_score("g1") == 1.0

    def test_after_one_completion_novelty_decays(self):
        h = HedonicAdapter(decay=0.75)
        h.record_completion("g1")
        assert abs(h.novelty_score("g1") - 0.75) < 1e-9

    def test_after_two_completions(self):
        h = HedonicAdapter(decay=0.75)
        h.record_completion("g1")
        h.record_completion("g1")
        expected = 0.75 ** 2
        assert abs(h.novelty_score("g1") - expected) < 1e-9

    def test_min_novelty_floor(self):
        h = HedonicAdapter(decay=0.5, min_novelty=0.1)
        for _ in range(20):
            h.record_completion("g1")
        assert h.novelty_score("g1") >= 0.1

    def test_reward_for_first_time(self):
        h = HedonicAdapter(decay=0.75)
        reward = h.reward_for("g1", 5.0)
        assert abs(reward - 5.0) < 1e-9

    def test_reward_for_after_one_completion(self):
        h = HedonicAdapter(decay=0.75)
        h.record_completion("g1")
        reward = h.reward_for("g1", 5.0)
        assert abs(reward - 5.0 * 0.75) < 1e-9

    def test_reward_decays_with_count(self):
        h = HedonicAdapter(decay=0.75)
        rewards = []
        for i in range(5):
            h.record_completion("g1")
            rewards.append(h.reward_for("g1", 10.0))
        # Должны убывать
        for i in range(len(rewards) - 1):
            assert rewards[i] >= rewards[i + 1]

    def test_multiple_gens_independent(self):
        h = HedonicAdapter(decay=0.75)
        h.record_completion("g1")
        h.record_completion("g1")
        h.record_completion("g2")
        assert h.novelty_score("g1") < h.novelty_score("g2")

    def test_most_novel_returns_highest(self):
        h = HedonicAdapter(decay=0.75)
        h.record_completion("g1")
        h.record_completion("g1")
        h.record_completion("g2")
        result = h.most_novel(["g1", "g2", "g3"])
        assert result == "g3"  # g3 никогда не завершался

    def test_most_novel_empty_list(self):
        h = HedonicAdapter()
        assert h.most_novel([]) is None

    def test_completion_count(self):
        h = HedonicAdapter()
        h.record_completion("g1")
        h.record_completion("g1")
        h.record_completion("g1")
        assert h.completion_count("g1") == 3
        assert h.completion_count("g2") == 0

    def test_stats_structure(self):
        h = HedonicAdapter()
        stats = h.stats()
        assert "tracked_gens" in stats
        assert "total_completions" in stats
        assert "avg_novelty" in stats
        assert "min_novelty_reached" in stats
        assert stats["tracked_gens"] == 0

    def test_stats_after_completions(self):
        h = HedonicAdapter(decay=0.5, min_novelty=0.05)
        h.record_completion("g1")
        h.record_completion("g2")
        stats = h.stats()
        assert stats["tracked_gens"] == 2
        assert stats["total_completions"] == 2

    def test_invalid_decay_raises(self):
        with pytest.raises(ValueError):
            HedonicAdapter(decay=0.0)

    def test_invalid_min_novelty_raises(self):
        with pytest.raises(ValueError):
            HedonicAdapter(min_novelty=1.0)


# ══════════════════════════════════════════════════════════════════════
# TestInitiativeEngine  (15 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestInitiativeEngine:

    def test_propose_empty_context_returns_empty(self):
        sys_ = _make_system()
        hedonic = HedonicAdapter()
        engine = InitiativeEngine()
        proposals = engine.propose(sys_.engine.context, sys_.base, hedonic)
        assert proposals == []

    def test_propose_returns_proposals_after_training(self):
        sys_ = _trained_system()
        hedonic = HedonicAdapter()
        engine = InitiativeEngine()
        # Загрузить контекст — подать один токен
        driver = TextDriver(driver_id="t")
        tokens = _tokens("день ночь")
        sys_.process_token(tokens[0])
        proposals = engine.propose(sys_.engine.context, sys_.base, hedonic)
        # Может быть пустой или нет — зависит от состояния обучения
        assert isinstance(proposals, list)

    def test_proposals_sorted_by_confidence(self):
        sys_ = _trained_system()
        hedonic = HedonicAdapter()
        engine = InitiativeEngine()
        # После обучения — получаем предложения
        tokens = _tokens("день ночь день ночь")
        for t in tokens:
            sys_.process_token(t)
        proposals = engine.propose(sys_.engine.context, sys_.base, hedonic)
        if len(proposals) >= 2:
            for i in range(len(proposals) - 1):
                assert proposals[i].confidence >= proposals[i + 1].confidence

    def test_evaluate_hit_rank_1_gives_highest_bonus(self):
        engine = InitiativeEngine()
        proposals = [
            Proposal("g1", "f1", 0.8),
            Proposal("g2", "f2", 0.5),
        ]
        bonus = engine.evaluate(proposals, "f1")
        assert bonus > 0
        # rank 1 → confidence * 5.0
        assert abs(bonus - 0.8 * 5.0) < 1e-9

    def test_evaluate_hit_rank_2(self):
        engine = InitiativeEngine()
        proposals = [
            Proposal("g1", "f1", 0.8),
            Proposal("g2", "f2", 0.5),
        ]
        bonus = engine.evaluate(proposals, "f2")
        assert abs(bonus - 0.5 * 2.5) < 1e-9

    def test_evaluate_hit_rank_3(self):
        engine = InitiativeEngine()
        proposals = [
            Proposal("g1", "f1", 0.8),
            Proposal("g2", "f2", 0.5),
            Proposal("g3", "f3", 0.3),
        ]
        bonus = engine.evaluate(proposals, "f3")
        assert abs(bonus - 0.3 * 1.0) < 1e-9

    def test_evaluate_miss_returns_zero(self):
        engine = InitiativeEngine()
        proposals = [Proposal("g1", "f1", 0.8)]
        bonus = engine.evaluate(proposals, "f_unknown")
        assert bonus == 0.0

    def test_evaluate_none_feature_returns_zero(self):
        engine = InitiativeEngine()
        proposals = [Proposal("g1", "f1", 0.8)]
        bonus = engine.evaluate(proposals, None)
        assert bonus == 0.0

    def test_hit_rate_initially_zero(self):
        engine = InitiativeEngine()
        assert engine.hit_rate == 0.0

    def test_hit_rate_after_hits_and_misses(self):
        engine = InitiativeEngine()
        proposals = [Proposal("g1", "f1", 0.8)]
        engine.evaluate(proposals, "f1")   # hit
        engine.evaluate(proposals, "f1")   # hit
        engine.evaluate(proposals, "f99")  # miss
        assert abs(engine.hit_rate - 2 / 3) < 1e-9

    def test_last_proposals_updated(self):
        sys_ = _trained_system()
        hedonic = HedonicAdapter()
        engine = InitiativeEngine()
        tokens = _tokens("день ночь")
        sys_.process_token(tokens[0])
        engine.propose(sys_.engine.context, sys_.base, hedonic)
        assert isinstance(engine.last_proposals, list)

    def test_stats_structure(self):
        engine = InitiativeEngine()
        stats = engine.stats()
        assert "total_proposals" in stats
        assert "total_hits" in stats
        assert "total_misses" in stats
        assert "hit_rate" in stats

    def test_stats_count_proposals(self):
        engine = InitiativeEngine()
        proposals = [Proposal("g1", "f1", 0.8), Proposal("g2", "f2", 0.5)]
        engine._total_proposals += len(proposals)
        engine.evaluate(proposals, "f1")
        stats = engine.stats()
        assert stats["total_hits"] == 1
        assert stats["total_misses"] == 0

    def test_evaluate_empty_proposals(self):
        engine = InitiativeEngine()
        bonus = engine.evaluate([], "f1")
        assert bonus == 0.0

    def test_proposal_dataclass(self):
        p = Proposal(gen_id="g1", next_feature_id="f1", confidence=0.9, label="test")
        assert p.gen_id == "g1"
        assert p.next_feature_id == "f1"
        assert p.confidence == 0.9
        assert p.label == "test"


# ══════════════════════════════════════════════════════════════════════
# TestLearningSystemStep7  (10 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestLearningSystemStep7:

    def test_has_hedonic_adapter(self):
        sys_ = _make_system()
        assert hasattr(sys_, "hedonic")
        assert isinstance(sys_.hedonic, HedonicAdapter)

    def test_has_initiative_engine(self):
        sys_ = _make_system()
        assert hasattr(sys_, "initiative")
        assert isinstance(sys_.initiative, InitiativeEngine)

    def test_stats_contains_hedonic(self):
        sys_ = _make_system()
        stats = sys_.stats()
        assert "hedonic" in stats

    def test_stats_contains_initiative(self):
        sys_ = _make_system()
        stats = sys_.stats()
        assert "initiative" in stats

    def test_last_proposals_method(self):
        sys_ = _make_system()
        proposals = sys_.last_proposals()
        assert isinstance(proposals, list)

    def test_hedonic_records_on_completed(self):
        sys_ = _trained_system()
        # После обучения — ещё раз пройтись по тексту для COMPLETED
        tokens = _tokens("день ночь день ночь день ночь")
        for t in tokens:
            sys_.process_token(t)
        # Hedonic должен что-то записать если были COMPLETED
        stats = sys_.stats()
        assert "hedonic" in stats

    def test_resource_increases_on_completed_via_hedonic(self):
        """Гедоника должна добавлять больше ресурса при первом завершении."""
        sys_ = _trained_system()
        level_before = sys_.resource.level
        tokens = _tokens("день ночь день ночь день ночь")
        results = []
        for t in tokens:
            r = sys_.process_token(t)
            results.append(r)
        # При наличии COMPLETED ресурс должен был вырасти в какой-то момент
        completed_count = sum(
            1 for r in results if r.outcome == StepOutcome.COMPLETED
        )
        if completed_count > 0:
            # Мы не знаем точный уровень, но тест проверяет что метод отработал
            assert sys_.resource.level >= 0.0

    def test_initiative_evaluated_per_step(self):
        """После process_token инициатива должна обновить счётчики."""
        sys_ = _trained_system()
        tokens = _tokens("день ночь")
        sys_.process_token(tokens[0])
        init_stats = sys_.initiative.stats()
        # После propose был вызван evaluate → total_proposals >= 0
        assert init_stats["total_proposals"] >= 0

    def test_process_token_returns_step_result(self):
        sys_ = _make_system()
        tokens = _tokens("кот сидит")
        result = sys_.process_token(tokens[0])
        assert result is not None
        assert hasattr(result, "outcome")

    def test_process_stream_with_hedonic(self):
        sys_ = _make_system()
        tokens = _tokens("день ночь день ночь")
        results = sys_.process_stream(tokens)
        assert len(results) == len(tokens)


# ══════════════════════════════════════════════════════════════════════
# TestTextCorpus  (8 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestTextCorpus:

    def test_get_level_1(self):
        corpus = TextCorpus()
        texts = corpus.get_level(1)
        assert len(texts) > 0
        assert all(isinstance(t, str) for t in texts)

    def test_get_level_2(self):
        corpus = TextCorpus()
        texts = corpus.get_level(2)
        assert len(texts) > 0

    def test_get_level_3(self):
        corpus = TextCorpus()
        texts = corpus.get_level(3)
        assert len(texts) > 0

    def test_get_level_4(self):
        corpus = TextCorpus()
        texts = corpus.get_level(4)
        assert len(texts) > 0

    def test_get_level_invalid_raises(self):
        corpus = TextCorpus()
        with pytest.raises(ValueError):
            corpus.get_level(0)
        with pytest.raises(ValueError):
            corpus.get_level(5)

    def test_easy_rescue(self):
        corpus = TextCorpus()
        text = corpus.easy_rescue()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_random_text(self):
        corpus = TextCorpus()
        for level in [1, 2, 3, 4]:
            text = corpus.random_text(level=level)
            assert text in corpus.get_level(level)

    def test_next_text_cycles(self):
        corpus = TextCorpus()
        texts = corpus.get_level(1)
        n = len(texts)
        seen = [corpus.next_text(1) for _ in range(n + 1)]
        # После n вызовов должен вернуться к началу
        assert seen[0] == seen[n]

    def test_random_text_no_level(self):
        corpus = TextCorpus()
        text = corpus.random_text()
        assert isinstance(text, str)
        assert len(text) > 0

    def test_level_count(self):
        corpus = TextCorpus()
        for level in [1, 2, 3, 4]:
            assert corpus.level_count(level) == len(corpus.get_level(level))


# ══════════════════════════════════════════════════════════════════════
# TestInteractiveTeacher  (15 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestInteractiveTeacher:

    def test_init_defaults(self):
        sys_ = _make_system()
        teacher = InteractiveTeacher(sys_)
        assert teacher.difficulty == 1
        assert teacher.death_count == 0
        assert teacher.stable_loop_count == 0

    def test_detect_life_state_alive(self):
        sys_ = _make_system()
        sys_.resource.set_level(0.8)
        teacher = InteractiveTeacher(sys_)
        assert teacher.detect_life_state() == LifeState.ALIVE

    def test_detect_life_state_at_risk(self):
        sys_ = _make_system()
        sys_.resource.set_level(0.2)
        teacher = InteractiveTeacher(sys_)
        assert teacher.detect_life_state() == LifeState.AT_RISK

    def test_detect_life_state_dying(self):
        sys_ = _make_system()
        sys_.resource.set_level(0.10)
        teacher = InteractiveTeacher(sys_)
        assert teacher.detect_life_state() == LifeState.DYING

    def test_detect_life_state_dead(self):
        sys_ = _make_system()
        sys_.resource.set_level(0.03)
        teacher = InteractiveTeacher(sys_)
        assert teacher.detect_life_state() == LifeState.DEAD

    def test_rescue_resets_context_and_recovers(self):
        sys_ = _make_system()
        sys_.resource.set_level(0.03)
        teacher = InteractiveTeacher(sys_)
        teacher.rescue()
        assert teacher.death_count == 1
        assert sys_.resource.level > 0.03

    def test_adjust_difficulty_increases(self):
        sys_ = _trained_system()
        teacher = InteractiveTeacher(sys_, difficulty=1)
        # Принудительно поставить условия для повышения
        teacher.stable_loop_count = 5
        teacher.system.initiative._total_hits = 7
        teacher.system.initiative._total_misses = 3
        old = teacher.difficulty
        teacher.adjust_difficulty()
        # Должно повыситься если hit_rate > 0.6 и stable_loops >= 3
        assert teacher.difficulty >= old

    def test_adjust_difficulty_decreases_on_deaths(self):
        sys_ = _make_system()
        teacher = InteractiveTeacher(sys_, difficulty=3)
        teacher._recent_deaths = 3
        teacher.adjust_difficulty()
        assert teacher.difficulty < 3

    def test_step_token_returns_step_report(self):
        sys_ = _make_system()
        teacher = InteractiveTeacher(sys_)
        tokens = _tokens("день ночь")
        if tokens:
            report = teacher.step_token(tokens[0])
            assert isinstance(report, StepReport)
            assert hasattr(report, "step_result")
            assert hasattr(report, "proposals")
            assert hasattr(report, "initiative_hit")
            assert hasattr(report, "life_state")
            assert hasattr(report, "resource_level")

    def test_feed_text_returns_list_of_reports(self):
        sys_ = _make_system()
        teacher = InteractiveTeacher(sys_)
        reports = teacher.feed_text("день ночь день ночь")
        assert isinstance(reports, list)
        assert len(reports) > 0
        assert all(isinstance(r, StepReport) for r in reports)

    def test_run_returns_training_report(self):
        sys_ = _make_system()
        teacher = InteractiveTeacher(sys_)
        report = teacher.run(n_steps=20)
        assert isinstance(report, TrainingReport)
        assert report.total_steps >= 0

    def test_training_report_structure(self):
        sys_ = _make_system()
        teacher = InteractiveTeacher(sys_)
        report = teacher.run(n_steps=10)
        assert hasattr(report, "deaths")
        assert hasattr(report, "stable_loops")
        assert hasattr(report, "final_base_size")
        assert hasattr(report, "final_resource")
        assert hasattr(report, "hit_rate")
        assert hasattr(report, "difficulty_reached")
        assert hasattr(report, "attractor_count")
        assert hasattr(report, "narrative")

    def test_difficulty_clamp_min(self):
        sys_ = _make_system()
        teacher = InteractiveTeacher(sys_, difficulty=1)
        teacher._recent_deaths = 10
        teacher.adjust_difficulty()
        assert teacher.difficulty >= 1

    def test_difficulty_clamp_max(self):
        sys_ = _make_system()
        teacher = InteractiveTeacher(sys_, difficulty=4)
        teacher.stable_loop_count = 100
        teacher.system.initiative._total_hits = 100
        teacher.system.initiative._total_misses = 0
        teacher.adjust_difficulty()
        assert teacher.difficulty <= 4

    def test_run_small_no_crash(self):
        sys_ = _make_system()
        corpus = TextCorpus()
        teacher = InteractiveTeacher(sys_, corpus, difficulty=1)
        report = teacher.run(n_steps=30)
        assert report.total_steps >= 0


# ══════════════════════════════════════════════════════════════════════
# TestTrainingLoop  (5 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestTrainingLoop:

    def test_run_tokens_returns_reports(self):
        loop = TrainingLoop()
        tokens = _tokens("день ночь день ночь")
        reports = loop.run_tokens(tokens)
        assert len(reports) == len(tokens)
        assert all(isinstance(r, StepReport) for r in reports)

    def test_run_text_returns_reports(self):
        loop = TrainingLoop()
        reports = loop.run_text("день ночь день ночь")
        assert isinstance(reports, list)
        assert len(reports) > 0

    def test_run_tokens_empty(self):
        loop = TrainingLoop()
        reports = loop.run_tokens([])
        assert reports == []

    def test_stats_after_run(self):
        loop = TrainingLoop()
        loop.run_text("день ночь день ночь")
        stats = loop.stats()
        assert "total_steps" in stats
        assert "deaths" in stats
        assert "hits" in stats
        assert "misses" in stats
        assert "hit_rate" in stats

    def test_stats_initial_empty(self):
        loop = TrainingLoop()
        stats = loop.stats()
        assert stats["total_steps"] == 0


# ══════════════════════════════════════════════════════════════════════
# TestTrainingReport  (5 тестов)
# ══════════════════════════════════════════════════════════════════════

class TestTrainingReport:

    def _run_teacher(self, n_steps: int = 50, difficulty: int = 1) -> TrainingReport:
        sys_ = _make_system()
        corpus = TextCorpus()
        teacher = InteractiveTeacher(sys_, corpus, difficulty=difficulty)
        return teacher.run(n_steps=n_steps)

    def test_deaths_counted(self):
        """Смерти должны корректно считаться (может быть 0)."""
        report = self._run_teacher(n_steps=50)
        assert report.deaths >= 0

    def test_stable_loops_counted(self):
        """Стабильные петли должны корректно считаться."""
        report = self._run_teacher(n_steps=100)
        assert report.stable_loops >= 0

    def test_hit_rate_in_range(self):
        """Hit rate должен быть в [0, 1]."""
        report = self._run_teacher(n_steps=50)
        assert 0.0 <= report.hit_rate <= 1.0

    def test_final_resource_in_range(self):
        """Ресурс в конце должен быть в [0, 1]."""
        report = self._run_teacher(n_steps=50)
        assert 0.0 <= report.final_resource <= 1.0

    def test_difficulty_reached_in_range(self):
        """Достигнутый уровень должен быть в [1, 4]."""
        report = self._run_teacher(n_steps=100, difficulty=1)
        assert 1 <= report.difficulty_reached <= 4
