"""
Тесты Шага 2: GreedyGeneralizer, LazyDisambiguator, NarrativeMinimizer, TextDriver.
"""

import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from core.feature import Feature, RegionCharacteristics
from core.generalization import Generalization, GeneralizationBase, PeripheralToken
from core.context import ContextBuffer
from core.algorithm import AttractorEngine, StepOutcome
from core.learning import (
    GreedyGeneralizer, LazyDisambiguator, NarrativeMinimizer, LearningSystem
)
from drivers.text_driver import TextDriver, _word_complexity, _build_vocab


# ──────────────────────────────────────────────
# Вспомогательные фабрики

def make_feature(fid: str, brightness_delta: float) -> Feature:
    src = RegionCharacteristics(brightness=0.3)
    tgt = RegionCharacteristics(brightness=0.3 + brightness_delta)
    return Feature.from_regions(fid, 0.0, 1.0, src, tgt)


def make_token(data) -> PeripheralToken:
    return PeripheralToken.new("test", data)


# ══════════════════════════════════════════════
# GreedyGeneralizer

class TestGreedyGeneralizer:

    def test_no_gen_after_single_occurrence(self):
        base = GeneralizationBase()
        g = GreedyGeneralizer(base, min_count=2)

        from core.algorithm import StepResult
        r = StepResult(
            outcome=StepOutcome.CONFIRMED,
            token=make_token(None),
            matched_feature_id="f1",
        )
        g.on_step_result(r)
        r2 = StepResult(
            outcome=StepOutcome.COMPLETED,
            token=make_token(None),
            matched_feature_id="f2",
        )
        result = g.on_step_result(r2)
        # Первый раз — ещё не создаём
        assert result is None
        assert g.created_count == 0

    def test_gen_created_after_min_count(self):
        """
        Паттерн fA→fB встречается 2 раза (две «сессии»).
        На второй сессии должен быть создан новый Gen.
        reset_chain() отмечает границу сессии.
        """
        base = GeneralizationBase()
        g = GreedyGeneralizer(base, min_count=2)

        from core.algorithm import StepResult
        result = None
        for _ in range(2):
            g.on_step_result(StepResult(
                outcome=StepOutcome.CONFIRMED,
                token=make_token(None),
                matched_feature_id="f1",
            ))
            g.on_step_result(StepResult(
                outcome=StepOutcome.COMPLETED,
                token=make_token(None),
                matched_feature_id="f2",
            ))
            result = g.reset_chain()   # граница сессии → финализация

        # Gen создаётся когда count достигает min_count (может быть в любой итерации)
        assert g.created_count == 1
        assert base.size() == 1
        created = base.search_by_chain(["f1", "f2"])
        assert created, "Gen с цепочкой ['f1','f2'] должен существовать"
        assert created[0].feature_chain == ["f1", "f2"]

    def test_no_duplicate_gen(self):
        """Повторный паттерн не создаёт дубликат — увеличивает счётчик."""
        base = GeneralizationBase()
        g = GreedyGeneralizer(base, min_count=2)

        from core.algorithm import StepResult
        for _ in range(4):
            g.on_step_result(StepResult(
                outcome=StepOutcome.CONFIRMED,
                token=make_token(None),
                matched_feature_id="fA",
            ))
            g.on_step_result(StepResult(
                outcome=StepOutcome.COMPLETED,
                token=make_token(None),
                matched_feature_id="fB",
            ))
            g.reset_chain()   # граница сессии

        assert g.created_count == 1
        assert base.size() == 1
        gen = base.all()[0]
        assert gen.success_count >= 2

    def test_refuted_finalizes_chain(self):
        """При REFUTED цепочка фиксируется как кандидат."""
        base = GeneralizationBase()
        g = GreedyGeneralizer(base, min_count=2)

        from core.algorithm import StepResult
        # Первый раз: CONFIRMED + REFUTED
        g.on_step_result(StepResult(
            outcome=StepOutcome.CONFIRMED,
            token=make_token(None),
            matched_feature_id="fX",
        ))
        g.on_step_result(StepResult(
            outcome=StepOutcome.REFUTED,
            token=make_token(None),
        ))
        assert ("fX",) in g.candidate_chains

    def test_chain_heterarchy_link(self):
        """Новый длинный Gen должен быть связан с более коротким."""
        base = GeneralizationBase()
        short = Generalization.new(feature_chain=["f1"])
        base.add(short)

        g = GreedyGeneralizer(base, min_count=2)
        from core.algorithm import StepResult

        for _ in range(2):
            g.on_step_result(StepResult(
                outcome=StepOutcome.CONFIRMED,
                token=make_token(None),
                matched_feature_id="f1",
            ))
            g.on_step_result(StepResult(
                outcome=StepOutcome.COMPLETED,
                token=make_token(None),
                matched_feature_id="f2",
            ))
            g.reset_chain()   # граница сессии

        long_gen = base.search_by_chain(["f1", "f2"])
        assert long_gen, "Длинный Gen должен быть создан"
        assert short.gen_id in long_gen[0].child_ids


# ══════════════════════════════════════════════
# LazyDisambiguator

class TestLazyDisambiguator:

    def _setup(self):
        base = GeneralizationBase()
        # Три Gen с общим первым признаком "f1"
        g1 = Generalization.new(feature_chain=["f1", "f2"])
        g2 = Generalization.new(feature_chain=["f1", "f3"])
        g3 = Generalization.new(feature_chain=["f1", "f4"])
        for g in (g1, g2, g3):
            base.add(g)
        return base, g1, g2, g3

    def test_load_all_candidates(self):
        base, g1, g2, g3 = self._setup()
        ctx = ContextBuffer()
        d = LazyDisambiguator(base, max_competing=10)
        count = d.load_all_candidates(ctx, "f1")
        assert count == 3
        assert set(ctx.active_gen_ids()) == {g1.gen_id, g2.gen_id, g3.gen_id}

    def test_detect_bifurcation(self):
        base, g1, g2, g3 = self._setup()
        ctx = ContextBuffer()
        ctx.add_active(g1.gen_id)
        ctx.add_active(g2.gen_id)
        # Оба Gen начинают с "f1" (index=0) → нет бифуркации.
        # Подтверждаем "f1" — оба переходят к своим вторым признакам.
        ctx.confirm_feature("f1", base)
        # Теперь g1 ожидает "f2", g2 ожидает "f3" → бифуркация
        d = LazyDisambiguator(base)
        assert d.detect_bifurcation(ctx, base) is True

    def test_no_bifurcation_when_same_feature(self):
        base = GeneralizationBase()
        g1 = Generalization.new(feature_chain=["f1", "f2"])
        g2 = Generalization.new(feature_chain=["f1", "f2", "f3"])
        base.add(g1); base.add(g2)
        ctx = ContextBuffer()
        ctx.add_active(g1.gen_id)
        ctx.add_active(g2.gen_id)
        d = LazyDisambiguator(base)
        # Оба ожидают f1 → нет бифуркации
        assert d.detect_bifurcation(ctx, base) is False

    def test_disambiguate_by_confirmed_feature(self):
        base, g1, g2, g3 = self._setup()
        ctx = ContextBuffer()
        for g in (g1, g2, g3):
            ctx.add_active(g.gen_id)
        # Сначала подтверждаем общий первый признак "f1"
        ctx.confirm_feature("f1", base)
        # Теперь g1 ожидает "f2", g2 — "f3", g3 — "f4" → бифуркация
        d = LazyDisambiguator(base, max_competing=1)
        # Подтверждаем "f2" — должен остаться только g1
        kept, removed = d.disambiguate(ctx, base, confirmed_feature_id="f2")
        assert g1.gen_id in kept
        assert g2.gen_id in removed or g3.gen_id in removed

    def test_disambiguate_by_significance(self):
        base, g1, g2, g3 = self._setup()
        g1.success_count = 10; g1.stop_count = 1
        g2.success_count = 2;  g2.stop_count = 5
        g3.success_count = 0;  g3.stop_count = 0
        ctx = ContextBuffer()
        for g in (g1, g2, g3):
            ctx.add_active(g.gen_id)
        d = LazyDisambiguator(base, max_competing=1)
        kept, removed = d.disambiguate(ctx, base)
        assert g1.gen_id in kept    # наиболее значимый

    def test_find_distinguishing_feature(self):
        base = GeneralizationBase()
        g1 = Generalization.new(feature_chain=["f1", "f2", "f_unique_A"])
        g2 = Generalization.new(feature_chain=["f1", "f2", "f_unique_B"])
        base.add(g1); base.add(g2)
        d = LazyDisambiguator(base)
        feat = d.find_distinguishing_feature([g1.gen_id], [g2.gen_id], base)
        assert feat == "f_unique_A"


# ══════════════════════════════════════════════
# NarrativeMinimizer

class TestNarrativeMinimizer:

    def test_replace_children_with_parent(self):
        base = GeneralizationBase()
        parent = Generalization.new(feature_chain=["f1"])
        child1 = Generalization.new(feature_chain=["f1", "f2"])
        child2 = Generalization.new(feature_chain=["f1", "f3"])
        for g in (parent, child1, child2):
            base.add(g)
        base.link(parent.gen_id, child1.gen_id)
        base.link(parent.gen_id, child2.gen_id)

        nm = NarrativeMinimizer(base)
        minimized = nm.minimize([child1.gen_id, child2.gen_id])
        assert parent.gen_id in minimized
        assert child1.gen_id not in minimized
        assert child2.gen_id not in minimized

    def test_prune_insignificant(self):
        base = GeneralizationBase()
        g_good = Generalization.new(feature_chain=["f1"]); g_good.success_count = 5
        g_bad  = Generalization.new(feature_chain=["f2"]); g_bad.stop_count = 3
        base.add(g_good); base.add(g_bad)

        nm = NarrativeMinimizer(base)
        minimized = nm.minimize([g_good.gen_id, g_bad.gen_id])
        assert g_good.gen_id in minimized
        assert g_bad.gen_id not in minimized

    def test_remove_absorbed(self):
        """Короткий Gen поглощается длинным с тем же префиксом."""
        base = GeneralizationBase()
        short = Generalization.new(feature_chain=["f1"])
        short.success_count = 3
        long  = Generalization.new(feature_chain=["f1", "f2"])
        long.success_count = 3
        base.add(short); base.add(long)

        nm = NarrativeMinimizer(base)
        minimized = nm.minimize([short.gen_id, long.gen_id])
        assert long.gen_id in minimized
        assert short.gen_id not in minimized

    def test_description_length(self):
        import math
        base = GeneralizationBase()
        g1 = Generalization.new(feature_chain=["f1"])
        g2 = Generalization.new(feature_chain=["f1", "f2", "f3"])
        base.add(g1); base.add(g2)
        nm = NarrativeMinimizer(base)
        assert nm.description_length([g1.gen_id]) < nm.description_length([g2.gen_id])

    def test_compare(self):
        base = GeneralizationBase()
        g1 = Generalization.new(feature_chain=["f1"])
        g2 = Generalization.new(feature_chain=["f1", "f2"])
        base.add(g1); base.add(g2)
        nm = NarrativeMinimizer(base)
        assert nm.compare([g1.gen_id], [g2.gen_id]) == -1   # g1 короче
        assert nm.compare([g2.gen_id], [g1.gen_id]) == 1    # g2 длиннее

    def test_already_minimal(self):
        base = GeneralizationBase()
        g = Generalization.new(feature_chain=["f1"]); g.success_count = 1
        base.add(g)
        nm = NarrativeMinimizer(base)
        assert nm.is_minimal([g.gen_id])


# ══════════════════════════════════════════════
# TextDriver

class TestTextDriver:

    def test_word_complexity(self):
        assert _word_complexity("aaa") == pytest.approx(1/3)
        assert _word_complexity("abc") == pytest.approx(1.0)
        assert _word_complexity("") == 0.0

    def test_build_vocab(self):
        words = ["кот", "кот", "собака", "птица"]
        vocab = _build_vocab(words)
        assert "кот" in vocab
        assert "собака" in vocab
        # кот самый частый → должен иметь наименьший индекс
        assert vocab["кот"] < vocab["собака"]

    def test_produces_tokens(self):
        driver = TextDriver("t0", "кот сидит на окне")
        tokens = list(driver.produce())
        assert len(tokens) == 3           # 4 слова → 3 перехода

    def test_token_is_feature(self):
        from core.feature import Feature
        driver = TextDriver("t0", "кот сидит")
        tokens = list(driver.produce())
        assert len(tokens) == 1
        assert isinstance(tokens[0].data, Feature)

    def test_short_text_no_tokens(self):
        driver = TextDriver("t0", "один")
        assert list(driver.produce()) == []

    def test_empty_text_no_tokens(self):
        driver = TextDriver("t0", "")
        assert list(driver.produce()) == []

    def test_lowercase(self):
        d1 = TextDriver("t0", "Кот Сидит", lowercase=True)
        d2 = TextDriver("t1", "кот сидит", lowercase=True)
        t1 = list(d1.produce())
        t2 = list(d2.produce())
        # Оба текста дают одинаковые признаки при lowercase=True
        assert len(t1) == len(t2)
        f1 = t1[0].data
        f2 = t2[0].data
        assert f1.vector.distance_to(f2.vector) < 0.01

    def test_char_mode(self):
        driver = TextDriver("t0", "abc", mode="chars")
        tokens = list(driver.produce())
        assert len(tokens) == 2       # 3 символа → 2 перехода

    def test_build_vocab_external(self):
        driver = TextDriver("t0", mode="words")
        driver.build_vocab(["кот сидит на окне", "кот бежит по полю"])
        assert "кот" in driver._vocab
        assert "бежит" in driver._vocab

    def test_features_differ_for_different_words(self):
        d1 = TextDriver("t0", "кот сидит")
        d2 = TextDriver("t1", "кот бежит")
        t1 = list(d1.produce())[0].data
        t2 = list(d2.produce())[0].data
        # «сидит» и «бежит» разные слова → разные признаки
        assert t1.vector.distance_to(t2.vector) > 0.0


# ══════════════════════════════════════════════
# LearningSystem (интеграционные тесты)

class TestLearningSystem:

    def test_learns_repeated_pattern(self):
        """Повторяющийся паттерн порождает новое обобщение."""
        sys = LearningSystem(feature_tolerance=0.4, min_gen_count=2)
        driver = TextDriver("t0", mode="words")

        texts = [
            "кот сидит на окне",
            "кот сидит на окне",   # повтор → жадное обобщение
        ]
        for text in texts:
            tokens = list(driver.produce(text))
            sys.process_stream(tokens)
            sys.engine.context.reset()
            sys.generalizer.reset_chain()

        stats = sys.stats()
        assert stats["base_size"] >= 1
        assert stats["features"] >= 1
        print(f"\nStats after learning: {stats}")

    def test_different_texts_different_features(self):
        """Разные тексты создают разные признаки."""
        sys = LearningSystem(feature_tolerance=0.1)
        d1 = TextDriver("t0", "кот бежит быстро")
        d2 = TextDriver("t1", "собака прыгает высоко")
        t1 = list(d1.produce())
        t2 = list(d2.produce())
        sys.process_stream(t1)
        n1 = sys.stats()["features"]
        sys.process_stream(t2)
        n2 = sys.stats()["features"]
        assert n2 > n1    # новые признаки добавились

    def test_minimal_narrative(self):
        """Минимизация нарратива не ломает систему."""
        sys = LearningSystem()
        g = Generalization.new(feature_chain=["f1"]); g.success_count = 3
        sys.base.add(g)
        sys.engine.context.add_active(g.gen_id)
        narrative = sys.get_minimal_narrative()
        assert isinstance(narrative, list)

    def test_consolidation_after_learning(self):
        """После обучения консолидация находит общие опоры."""
        sys = LearningSystem(feature_tolerance=0.5, min_gen_count=2)

        # Два обобщения с общим началом
        g1 = Generalization.new(feature_chain=["fA", "fB"])
        g1.success_count = 6
        g2 = Generalization.new(feature_chain=["fA", "fC"])
        g2.success_count = 5
        sys.base.add(g1); sys.base.add(g2)

        new_gens = sys.engine.consolidate(min_success=5)
        assert len(new_gens) >= 1
        assert new_gens[0].feature_chain == ["fA"]

    def test_sequence_driver_with_learning(self):
        """SequenceDriver + LearningSystem полный цикл."""
        from drivers.sequence_driver import SequenceDriver
        sys = LearningSystem(feature_tolerance=0.4, min_gen_count=2)
        pattern = [0.1, 0.5, 0.9, 0.5, 0.1]

        # Обучение на повторяющемся паттерне
        for _ in range(3):
            driver = SequenceDriver("s0", pattern)
            sys.process_stream(driver.produce())
            sys.engine.context.reset()
            sys.generalizer.reset_chain()

        stats = sys.stats()
        print(f"\nSequence learning stats: {stats}")
        assert stats["steps"] > 0
        assert stats["base_size"] >= 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
