"""
Тесты ядра системы (Шаг 1).

Покрывают:
  - Feature: создание, совпадение, расстояние
  - Generalization: создание, значимость, уровень обобщения
  - GeneralizationBase: добавление, поиск, ранжирование, гетерархия
  - ContextBuffer: добавление, подтверждение, опровержение
  - AttractorEngine: главный цикл (CONFIRMED / REFUTED / COMPLETED / EXPLORING)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import math
import pytest
from core.feature import Feature, FeatureVector, RegionCharacteristics
from core.generalization import Generalization, GeneralizationBase, PeripheralToken
from core.context import ContextBuffer
from core.algorithm import AttractorEngine, StepOutcome
from drivers.sequence_driver import SequenceDriver


# ──────────────────────────────────────────────
# Feature

class TestFeature:
    def test_delta_same_region(self):
        r = RegionCharacteristics(size=0.5, brightness=0.5, contrast=0.5,
                                   color_hue=0.5, color_sat=0.5, fractal_dim=1.5)
        v = r.delta(r)
        assert v.delta_brightness == pytest.approx(0.0)
        assert v.delta_contrast == pytest.approx(0.0)

    def test_delta_different_regions(self):
        src = RegionCharacteristics(brightness=0.2, contrast=0.2,
                                     size=0.5, color_hue=0.0, color_sat=0.0,
                                     fractal_dim=1.0)
        tgt = RegionCharacteristics(brightness=0.6, contrast=0.6,
                                     size=0.5, color_hue=0.0, color_sat=0.0,
                                     fractal_dim=1.0)
        v = src.delta(tgt)
        assert v.delta_brightness > 0      # яркость выросла
        assert v.delta_contrast > 0        # контраст вырос

    def test_feature_matches_itself(self):
        f = Feature.from_regions(
            feature_id="f1", direction=0.0, distance=1.0,
            source=RegionCharacteristics(brightness=0.3),
            target=RegionCharacteristics(brightness=0.7),
        )
        assert f.matches(f, tolerance=0.01)

    def test_feature_no_match_distant(self):
        src = RegionCharacteristics(brightness=0.1, contrast=0.1)
        tgt1 = RegionCharacteristics(brightness=0.9, contrast=0.9)
        tgt2 = RegionCharacteristics(brightness=0.1, contrast=0.9)
        f1 = Feature.from_regions("f1", 0.0, 1.0, src, tgt1)
        f2 = Feature.from_regions("f2", 0.0, 1.0, src, tgt2)
        assert not f1.matches(f2, tolerance=0.1)

    def test_distance_symmetric(self):
        v1 = FeatureVector(delta_brightness=0.5)
        v2 = FeatureVector(delta_brightness=0.8)
        assert v1.distance_to(v2) == pytest.approx(v2.distance_to(v1))


# ──────────────────────────────────────────────
# Generalization

class TestGeneralization:
    def test_new_gen(self):
        g = Generalization.new(feature_chain=["f1", "f2"], label="test")
        assert g.gen_id
        assert g.feature_chain == ["f1", "f2"]
        assert g.generalization_level == 2
        assert g.significance == 0.0   # нет подтверждений

    def test_significance(self):
        g = Generalization.new()
        for _ in range(3):
            g.confirm()
        g.refute()
        assert g.significance == pytest.approx(0.75)

    def test_confirm_refute(self):
        g = Generalization.new()
        g.confirm()
        g.confirm()
        g.refute()
        assert g.success_count == 2
        assert g.stop_count == 1


# ──────────────────────────────────────────────
# GeneralizationBase

class TestGeneralizationBase:
    def test_add_get(self):
        base = GeneralizationBase()
        g = Generalization.new(feature_chain=["f1"])
        base.add(g)
        assert base.get(g.gen_id) is g
        assert base.size() == 1

    def test_rank(self):
        base = GeneralizationBase()
        g1 = Generalization.new(); g1.success_count = 10; g1.stop_count = 2
        g2 = Generalization.new(); g2.success_count = 5; g2.stop_count = 1
        base.add(g1); base.add(g2)
        ranked = base.rank()
        assert ranked[0].gen_id == g1.gen_id  # g1 более значим

    def test_search_by_chain(self):
        base = GeneralizationBase()
        g = Generalization.new(feature_chain=["a", "b"])
        base.add(g)
        found = base.search_by_chain(["a", "b"])
        assert len(found) == 1 and found[0].gen_id == g.gen_id
        assert base.search_by_chain(["a"]) == []

    def test_search_by_prefix(self):
        base = GeneralizationBase()
        g1 = Generalization.new(feature_chain=["a", "b", "c"])
        g2 = Generalization.new(feature_chain=["a", "b", "d"])
        g3 = Generalization.new(feature_chain=["x", "y"])
        base.add(g1); base.add(g2); base.add(g3)
        found = base.search_by_prefix(["a", "b"])
        assert len(found) == 2
        assert g3.gen_id not in [f.gen_id for f in found]

    def test_transition_stats(self):
        base = GeneralizationBase()
        base.record_transition("f1", "f2")
        base.record_transition("f1", "f2")
        base.record_transition("f1", "f3")
        assert base.most_likely_next("f1") == "f2"

    def test_heterarchy_link(self):
        base = GeneralizationBase()
        parent = Generalization.new(feature_chain=["a"])
        child = Generalization.new(feature_chain=["a", "b"])
        base.add(parent); base.add(child)
        base.link(parent.gen_id, child.gen_id)
        assert child.gen_id in parent.child_ids
        assert parent.gen_id in child.parent_ids


# ──────────────────────────────────────────────
# ContextBuffer

class TestContextBuffer:
    def _make_gen_and_base(self, chain):
        base = GeneralizationBase()
        g = Generalization.new(feature_chain=chain)
        base.add(g)
        return g, base

    def test_add_active(self):
        ctx = ContextBuffer()
        ctx.add_active("g1")
        assert "g1" in ctx.active_gen_ids()

    def test_expected_features(self):
        g, base = self._make_gen_and_base(["f1", "f2"])
        ctx = ContextBuffer()
        ctx.add_active(g.gen_id)
        exp = ctx.get_expected_features(base)
        assert exp[g.gen_id] == "f1"   # первый в цепочке

    def test_confirm_advances(self):
        g, base = self._make_gen_and_base(["f1", "f2"])
        ctx = ContextBuffer()
        ctx.add_active(g.gen_id)
        completed = ctx.confirm_feature("f1", base)
        assert completed == []
        exp = ctx.get_expected_features(base)
        assert exp[g.gen_id] == "f2"   # перешли к следующему

    def test_confirm_all_completes(self):
        g, base = self._make_gen_and_base(["f1"])
        ctx = ContextBuffer()
        ctx.add_active(g.gen_id)
        completed = ctx.confirm_feature("f1", base)
        assert g.gen_id in completed
        assert ctx.is_complete(base)

    def test_refute_removes_gen(self):
        g, base = self._make_gen_and_base(["f1", "f2"])
        ctx = ContextBuffer()
        ctx.add_active(g.gen_id)
        removed = ctx.refute_feature("f1", base)
        assert g.gen_id in removed
        assert ctx.is_empty()

    def test_history_cycle_detection(self):
        ctx = ContextBuffer()
        ctx.add_to_history("t1")
        assert ctx.seen("t1")
        assert not ctx.seen("t2")


# ──────────────────────────────────────────────
# AttractorEngine (интеграционные тесты)

class TestAttractorEngine:
    def _make_feature(self, fid: str, brightness_delta: float) -> Feature:
        src = RegionCharacteristics(brightness=0.3)
        tgt = RegionCharacteristics(brightness=0.3 + brightness_delta)
        return Feature.from_regions(fid, 0.0, 1.0, src, tgt)

    def test_exploring_on_empty_base(self):
        """
        На пустой базе движок создаёт Gen для входящего признака
        и сразу его завершает (COMPLETED), а не зависает в EXPLORING.
        EXPLORING возникает только если нет входящего признака.
        """
        base = GeneralizationBase()
        engine = AttractorEngine(base)

        # С признаком → создаём Gen и сразу COMPLETED
        f = self._make_feature("f1", 0.4)
        token = PeripheralToken.new("test", f)
        result = engine.step(token)
        assert result.outcome in (StepOutcome.COMPLETED, StepOutcome.CONFIRMED)

        # Без признака → EXPLORING
        engine2 = AttractorEngine(GeneralizationBase())
        token_no_feat = PeripheralToken.new("test", None)
        result2 = engine2.step(token_no_feat)
        assert result2.outcome == StepOutcome.EXPLORING

    def test_confirmed_on_known_pattern(self):
        base = GeneralizationBase()
        engine = AttractorEngine(base, feature_tolerance=0.5)

        # Создать обобщение с одним признаком
        f = self._make_feature("f1", 0.4)
        engine.register_feature(f)
        gen = Generalization.new(feature_chain=["f1"])
        base.add(gen)
        engine.context.add_active(gen.gen_id)

        # Подать похожий признак
        f_similar = self._make_feature("f2", 0.42)   # близко к f1
        token = PeripheralToken.new("test", f_similar)
        result = engine.step(token)
        assert result.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED)

    def test_refuted_on_different_pattern(self):
        base = GeneralizationBase()
        engine = AttractorEngine(base, feature_tolerance=0.1)  # строгий допуск

        f = self._make_feature("f1", 0.1)
        engine.register_feature(f)
        gen = Generalization.new(feature_chain=["f1"])
        base.add(gen)
        engine.context.add_active(gen.gen_id)

        # Подать сильно отличающийся признак
        f_different = self._make_feature("f2", 0.9)
        token = PeripheralToken.new("test", f_different)
        result = engine.step(token)
        assert result.outcome == StepOutcome.REFUTED
        assert result.new_gen_id is not None

    def test_cycle_avoided(self):
        base = GeneralizationBase()
        engine = AttractorEngine(base)
        token = PeripheralToken.new("test", None)
        engine.step(token)           # первый раз
        result = engine.step(token)  # повторный — цикл
        assert result.outcome == StepOutcome.CYCLE_AVOIDED

    def test_consolidation(self):
        base = GeneralizationBase()
        engine = AttractorEngine(base)

        # Два обобщения с общим префиксом
        g1 = Generalization.new(feature_chain=["f1", "f2"])
        g1.success_count = 10
        g2 = Generalization.new(feature_chain=["f1", "f3"])
        g2.success_count = 8
        base.add(g1); base.add(g2)

        new_gens = engine.consolidate(min_success=5)
        assert len(new_gens) >= 1
        assert new_gens[0].feature_chain == ["f1"]

    def test_sequence_driver_integration(self):
        """Полный цикл: SequenceDriver → AttractorEngine."""
        base = GeneralizationBase()
        engine = AttractorEngine(base, feature_tolerance=0.5)

        seq = [0.1, 0.3, 0.7, 0.5, 0.2, 0.8]
        driver = SequenceDriver("drv0", seq)

        outcomes = []
        for token in driver.produce():
            result = engine.step(token)
            outcomes.append(result.outcome)

        assert len(outcomes) == len(seq) - 1
        assert StepOutcome.CYCLE_AVOIDED not in outcomes
        print(f"\nOutcomes: {[o.name for o in outcomes]}")
        print(f"Base size after: {base.size()}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
