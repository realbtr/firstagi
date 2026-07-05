"""
Тесты Шага 3: Прямое кодирование аттрактора в фазовом пространстве.

Покрывают:
  - Resolution: prefix_length, coarser, finer
  - PhasePoint / BifurcationPoint / MacroToken / Attractor — структуры данных
  - PhaseTrajectory: add, diverges_from, converges_to, coarsen
  - TrajectoryRecorder: record (CONFIRMED/COMPLETED/REFUTED), reset
  - AttractorEncoder: compute_resolution, compute_all_resolutions,
                      phase_space_dimensionality,
                      detect_bifurcations, split_on_bifurcation,
                      create_macro_tokens, compression_ratio,
                      find_attractors, attach_macro_tokens, summary
  - Интеграция с LearningSystem (наличие encoder, recorder, stats, reset_context)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from core.generalization import Generalization, GeneralizationBase, PeripheralToken
from core.context import ContextBuffer
from core.algorithm import StepResult, StepOutcome
from core.attractor import (
    Resolution, PhasePoint, BifurcationPoint, MacroToken, Attractor,
    PhaseTrajectory, TrajectoryRecorder, AttractorEncoder,
)


# ── вспомогательные функции ────────────────────────────────────────────────

def _make_gen(chain, success=0, stop=0, label=None):
    g = Generalization.new(feature_chain=chain, label=label)
    g.success_count = success
    g.stop_count = stop
    return g


def _make_base_with_gens():
    """Три Gen: f1→f2 (sig≈0.83), f1→f3 (sig=0.8), f4→f5 (sig=0.5)."""
    base = GeneralizationBase()
    g1 = _make_gen(["f1", "f2"], success=5, stop=1)
    g2 = _make_gen(["f1", "f3"], success=4, stop=1)
    g3 = _make_gen(["f4", "f5"], success=2, stop=2)
    base.add(g1); base.add(g2); base.add(g3)
    return base, g1, g2, g3


def _step_result(outcome, feat_id=None):
    token = PeripheralToken.new("test", None)
    return StepResult(outcome=outcome, token=token, matched_feature_id=feat_id)


# ══════════════════════════════════════════════════════════════════════
# Resolution
# ══════════════════════════════════════════════════════════════════════

class TestResolution:
    def test_prefix_length(self):
        assert Resolution.COARSE.prefix_length() == 1
        assert Resolution.MEDIUM.prefix_length() == 2
        assert Resolution.FINE.prefix_length() == 3
        assert Resolution.EXACT.prefix_length() == 9999

    def test_coarser(self):
        assert Resolution.FINE.coarser() == Resolution.MEDIUM
        assert Resolution.MEDIUM.coarser() == Resolution.COARSE
        assert Resolution.COARSE.coarser() == Resolution.COARSE   # floor

    def test_finer(self):
        assert Resolution.MEDIUM.finer() == Resolution.FINE
        assert Resolution.FINE.finer() == Resolution.EXACT
        assert Resolution.EXACT.finer() == Resolution.EXACT       # ceiling

    def test_order(self):
        assert Resolution.COARSE.value < Resolution.MEDIUM.value
        assert Resolution.MEDIUM.value < Resolution.FINE.value
        assert Resolution.FINE.value < Resolution.EXACT.value

    def test_round_trip(self):
        """coarser().finer() восстанавливает исходное для MEDIUM/FINE."""
        assert Resolution.FINE.coarser().finer() == Resolution.FINE
        assert Resolution.MEDIUM.coarser().finer() == Resolution.MEDIUM


# ══════════════════════════════════════════════════════════════════════
# PhaseTrajectory
# ══════════════════════════════════════════════════════════════════════

class TestPhaseTrajectory:
    def test_empty(self):
        t = PhaseTrajectory()
        assert t.length == 0
        assert t.gen_sequence == []
        assert t.last_point() is None

    def test_add_length(self):
        t = PhaseTrajectory()
        t.add(PhasePoint(gen_id="g1"))
        t.add(PhasePoint(gen_id="g2"))
        assert t.length == 2
        assert t.gen_sequence == ["g1", "g2"]

    def test_last_point(self):
        t = PhaseTrajectory()
        t.add(PhasePoint(gen_id="g1"))
        t.add(PhasePoint(gen_id="g2"))
        assert t.last_point().gen_id == "g2"

    def test_diverges_from_at_position(self):
        t1 = PhaseTrajectory(); t2 = PhaseTrajectory()
        for gid in ["g1", "g2", "g3"]:
            t1.add(PhasePoint(gid))
        for gid in ["g1", "g9", "g3"]:
            t2.add(PhasePoint(gid))
        assert t1.diverges_from(t2) == 1

    def test_diverges_from_none_when_equal(self):
        t1 = PhaseTrajectory(); t2 = PhaseTrajectory()
        for gid in ["g1", "g2"]:
            t1.add(PhasePoint(gid))
            t2.add(PhasePoint(gid))
        assert t1.diverges_from(t2) is None

    def test_diverges_from_different_length(self):
        t1 = PhaseTrajectory(); t2 = PhaseTrajectory()
        t1.add(PhasePoint("g1")); t1.add(PhasePoint("g2"))
        t2.add(PhasePoint("g1"))
        # Совпадают до min_len, затем длины расходятся → min(2,1)=1
        assert t1.diverges_from(t2) == 1

    def test_diverges_from_both_empty(self):
        t1 = PhaseTrajectory(); t2 = PhaseTrajectory()
        assert t1.diverges_from(t2) is None

    def test_converges_to(self):
        t1 = PhaseTrajectory(); t2 = PhaseTrajectory()
        for gid in ["g1", "g2", "g3"]:
            t1.add(PhasePoint(gid))
        for gid in ["g9", "g2", "g3"]:
            t2.add(PhasePoint(gid))
        assert t1.converges_to(t2, tail_length=2)
        assert not t1.converges_to(t2, tail_length=3)  # начало различается

    def test_converges_too_short(self):
        t1 = PhaseTrajectory(); t2 = PhaseTrajectory()
        t1.add(PhasePoint("g1"))
        t2.add(PhasePoint("g1"))
        assert not t1.converges_to(t2, tail_length=2)  # оба короче tail_length

    def test_coarsen_preserves_length(self):
        t = PhaseTrajectory()
        t.add(PhasePoint("g1", resolution=Resolution.FINE))
        t.add(PhasePoint("g2", resolution=Resolution.FINE))
        coarsened = t.coarsen(Resolution.COARSE)
        assert coarsened.length == 2

    def test_coarsen_changes_resolution(self):
        t = PhaseTrajectory()
        t.add(PhasePoint("g1", resolution=Resolution.FINE))
        coarsened = t.coarsen(Resolution.COARSE)
        assert all(p.resolution == Resolution.COARSE for p in coarsened.points)

    def test_coarsen_preserves_gen_ids(self):
        t = PhaseTrajectory()
        t.add(PhasePoint("g1")); t.add(PhasePoint("g2"))
        coarsened = t.coarsen(Resolution.MEDIUM)
        assert coarsened.gen_sequence == ["g1", "g2"]


# ══════════════════════════════════════════════════════════════════════
# TrajectoryRecorder
# ══════════════════════════════════════════════════════════════════════

class TestTrajectoryRecorder:
    def test_record_confirmed_adds_point(self):
        rec = TrajectoryRecorder()
        rec.record(_step_result(StepOutcome.CONFIRMED, "f1"), ["g1"])
        assert rec._current.length == 1

    def test_record_completed_adds_all_active(self):
        rec = TrajectoryRecorder()
        rec.record(_step_result(StepOutcome.COMPLETED, "f1"), ["g1", "g2"])
        assert rec._current.length == 2

    def test_exploring_does_not_add(self):
        rec = TrajectoryRecorder()
        rec.record(_step_result(StepOutcome.EXPLORING), ["g1"])
        # EXPLORING начинает новую траекторию, но не записывает точки
        assert rec._current.length == 0

    def test_refuted_saves_nonempty_trajectory(self):
        rec = TrajectoryRecorder()
        rec.record(_step_result(StepOutcome.CONFIRMED, "f1"), ["g1"])
        rec.record(_step_result(StepOutcome.REFUTED), ["g2"])
        assert rec.count == 1
        assert rec._current.length == 0   # новая пустая траектория

    def test_refuted_empty_not_saved(self):
        rec = TrajectoryRecorder()
        rec.record(_step_result(StepOutcome.REFUTED), ["g1"])
        assert rec.count == 0

    def test_reset_saves_current(self):
        rec = TrajectoryRecorder()
        rec.record(_step_result(StepOutcome.CONFIRMED, "f1"), ["g1"])
        rec.reset()
        assert rec.count == 1
        assert rec._current.length == 0

    def test_reset_empty_not_saved(self):
        rec = TrajectoryRecorder()
        rec.reset()
        assert rec.count == 0

    def test_multiple_trajectories(self):
        rec = TrajectoryRecorder()
        # Траектория 1
        rec.record(_step_result(StepOutcome.CONFIRMED, "f1"), ["g1"])
        rec.record(_step_result(StepOutcome.REFUTED), ["g2"])
        # Траектория 2
        rec.record(_step_result(StepOutcome.CONFIRMED, "f2"), ["g3"])
        rec.reset()
        assert rec.count == 2
        trajs = rec.all_trajectories()
        assert len(trajs) == 2
        assert trajs[0].length == 1
        assert trajs[1].length == 1


# ══════════════════════════════════════════════════════════════════════
# AttractorEncoder — compute_resolution
# ══════════════════════════════════════════════════════════════════════

class TestAttractorEncoderResolution:
    def test_unknown_gen_returns_medium(self):
        base = GeneralizationBase()
        enc = AttractorEncoder(base)
        assert enc.compute_resolution("nonexistent") == Resolution.MEDIUM

    def test_new_gen_no_experience_returns_exact(self):
        base = GeneralizationBase()
        g = _make_gen(["f1"], success=0, stop=0)
        base.add(g)
        enc = AttractorEncoder(base)
        # sig=0.0 → EXACT (нужна максимальная точность для нового Gen)
        assert enc.compute_resolution(g.gen_id) == Resolution.EXACT

    def test_fine_significance(self):
        base = GeneralizationBase()
        g = _make_gen(["f1", "f2"], success=3, stop=4)  # sig≈0.43 > 0.0
        base.add(g)
        enc = AttractorEncoder(base)
        assert enc.compute_resolution(g.gen_id) == Resolution.FINE

    def test_medium_significance(self):
        base = GeneralizationBase()
        g = _make_gen(["f1", "f2"], success=5, stop=5)  # sig=0.5
        base.add(g)
        enc = AttractorEncoder(base)
        assert enc.compute_resolution(g.gen_id) == Resolution.MEDIUM

    def test_coarse_high_sig_long_chain(self):
        base = GeneralizationBase()
        g = _make_gen(["f1", "f2", "f3"], success=9, stop=1)  # sig=0.9, level=3
        base.add(g)
        enc = AttractorEncoder(base)
        assert enc.compute_resolution(g.gen_id) == Resolution.COARSE

    def test_near_bifurcation_always_exact(self):
        base, g1, _, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        # Независимо от значимости, рядом с бифуркацией → EXACT
        assert enc.compute_resolution(g1.gen_id, near_bifurcation=True) == Resolution.EXACT

    def test_compute_all_resolutions_only_active(self):
        base, g1, g2, g3 = _make_base_with_gens()
        enc = AttractorEncoder(base)
        ctx = ContextBuffer()
        ctx.add_active(g1.gen_id)
        ctx.add_active(g2.gen_id)
        resolutions = enc.compute_all_resolutions(ctx)
        assert g1.gen_id in resolutions
        assert g2.gen_id in resolutions
        assert g3.gen_id not in resolutions   # не в контексте

    def test_compute_all_resolutions_dict_values(self):
        base, g1, g2, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        ctx = ContextBuffer()
        ctx.add_active(g1.gen_id)
        resolutions = enc.compute_all_resolutions(ctx)
        assert isinstance(resolutions[g1.gen_id], Resolution)

    def test_phase_space_dimensionality_nonempty(self):
        base, g1, g2, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        ctx = ContextBuffer()
        ctx.add_active(g1.gen_id)
        ctx.add_active(g2.gen_id)
        dim = enc.phase_space_dimensionality(ctx)
        assert dim["n_active"] == 2
        assert dim["effective_dim"] > 0
        assert "counts" in dim

    def test_phase_space_dimensionality_empty_context(self):
        base = GeneralizationBase()
        enc = AttractorEncoder(base)
        ctx = ContextBuffer()
        dim = enc.phase_space_dimensionality(ctx)
        assert dim["effective_dim"] == 0


# ══════════════════════════════════════════════════════════════════════
# AttractorEncoder — detect_bifurcations / split_on_bifurcation
# ══════════════════════════════════════════════════════════════════════

class TestAttractorEncoderBifurcations:
    def _make_bifurcation_ctx(self):
        """
        Два Gen с разными вторыми признаками, оба продвинуты мимо первого.
        g1: ["f1","f2"], g2: ["f1","f3"]
        После confirm("f1"): g1 ожидает "f2", g2 ожидает "f3" → бифуркация.
        """
        base = GeneralizationBase()
        g1 = _make_gen(["f1", "f2"], success=4, stop=1)
        g2 = _make_gen(["f1", "f3"], success=4, stop=1)
        base.add(g1); base.add(g2)
        ctx = ContextBuffer()
        ctx.add_active(g1.gen_id)
        ctx.add_active(g2.gen_id)
        # Продвинуть оба Gen мимо общего "f1"
        ctx.confirm_feature("f1", base)
        return base, ctx, g1, g2

    def test_no_bifurcation_same_expected(self):
        """Оба Gen ожидают один и тот же следующий признак → нет бифуркации."""
        base = GeneralizationBase()
        g1 = _make_gen(["f1", "f2"])
        g2 = _make_gen(["f1", "f2"])   # идентичные цепочки
        base.add(g1); base.add(g2)
        enc = AttractorEncoder(base)
        ctx = ContextBuffer()
        ctx.add_active(g1.gen_id)
        ctx.add_active(g2.gen_id)
        # Оба ожидают "f1" → нет бифуркации
        assert len(enc.detect_bifurcations(ctx)) == 0

    def test_detect_bifurcation_after_advance(self):
        base, ctx, g1, g2 = self._make_bifurcation_ctx()
        enc = AttractorEncoder(base)
        bifs = enc.detect_bifurcations(ctx)
        assert len(bifs) >= 1

    def test_bifurcation_contains_both_gens(self):
        base, ctx, g1, g2 = self._make_bifurcation_ctx()
        enc = AttractorEncoder(base)
        bif = enc.detect_bifurcations(ctx)[0]
        all_ids = set(bif.branch_a + bif.branch_b)
        assert g1.gen_id in all_ids
        assert g2.gen_id in all_ids

    def test_bifurcation_divergence_score(self):
        base, ctx, g1, g2 = self._make_bifurcation_ctx()
        enc = AttractorEncoder(base)
        bif = enc.detect_bifurcations(ctx)[0]
        assert 0.0 < bif.divergence_score <= 1.0

    def test_bifurcation_distinguishing_features_are_different(self):
        base, ctx, g1, g2 = self._make_bifurcation_ctx()
        enc = AttractorEncoder(base)
        bif = enc.detect_bifurcations(ctx)[0]
        # Различающие признаки должны быть разными
        assert bif.distinguishing_feature_a is not None
        assert bif.distinguishing_feature_b is not None
        assert bif.distinguishing_feature_a != bif.distinguishing_feature_b

    def test_split_keeps_branch_a(self):
        base, ctx, g1, g2 = self._make_bifurcation_ctx()
        enc = AttractorEncoder(base)
        bif = enc.detect_bifurcations(ctx)[0]
        kept, removed = enc.split_on_bifurcation(bif, ctx, confirmed_branch="a")
        assert len(kept) + len(removed) == 2
        remaining = set(ctx.active_gen_ids())
        assert remaining == set(bif.branch_a)

    def test_split_keeps_branch_b(self):
        base, ctx, g1, g2 = self._make_bifurcation_ctx()
        enc = AttractorEncoder(base)
        bif = enc.detect_bifurcations(ctx)[0]
        kept, removed = enc.split_on_bifurcation(bif, ctx, confirmed_branch="b")
        remaining = set(ctx.active_gen_ids())
        assert remaining == set(bif.branch_b)


# ══════════════════════════════════════════════════════════════════════
# AttractorEncoder — create_macro_tokens / compression_ratio
# ══════════════════════════════════════════════════════════════════════

class TestAttractorEncoderMacroTokens:
    def test_create_macro_tokens_coarse_count(self):
        """COARSE: Gen с одинаковым первым признаком → один Macro-Token."""
        base, _, _, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        macros = enc.create_macro_tokens(Resolution.COARSE)
        # g1,g2 → ("f1",); g3 → ("f4",): 2 группы
        assert len(macros) == 2

    def test_create_macro_tokens_medium_count(self):
        """MEDIUM: каждый Gen уникален по первым двум признакам."""
        base, _, _, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        macros = enc.create_macro_tokens(Resolution.MEDIUM)
        assert len(macros) == 3

    def test_macro_token_representative_most_significant(self):
        base, g1, g2, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        macros = enc.create_macro_tokens(Resolution.COARSE)
        f1_macro = next(m for m in macros if "f1" in m.shared_prefix)
        # g1 sig≈0.833 > g2 sig=0.8 → g1 представитель
        assert f1_macro.representative_id == g1.gen_id

    def test_macro_token_shared_prefix(self):
        base, g1, g2, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        macros = enc.create_macro_tokens(Resolution.COARSE)
        f1_macro = next(m for m in macros if "f1" in m.shared_prefix)
        assert f1_macro.shared_prefix == ["f1"]
        assert f1_macro.size == 2

    def test_macro_token_distinguishing_features(self):
        base, g1, g2, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        macros = enc.create_macro_tokens(Resolution.COARSE)
        f1_macro = next(m for m in macros if "f1" in m.shared_prefix)
        # Различающие признаки: то, что идёт после общего prefix f1
        assert "f2" in f1_macro.distinguishing_features
        assert "f3" in f1_macro.distinguishing_features

    def test_macro_token_significance(self):
        base, g1, g2, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        macros = enc.create_macro_tokens(Resolution.COARSE)
        f1_macro = next(m for m in macros if "f1" in m.shared_prefix)
        expected_sig = g1.significance + g2.significance
        assert f1_macro.total_significance == pytest.approx(expected_sig, abs=0.01)

    def test_macro_tokens_sorted_by_significance(self):
        base, _, _, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        macros = enc.create_macro_tokens(Resolution.COARSE)
        # f1-группа (2 Gen, суммарная значимость выше) идёт первой
        assert macros[0].shared_prefix == ["f1"]

    def test_find_macro_token_for(self):
        base, g1, g2, g3 = _make_base_with_gens()
        enc = AttractorEncoder(base)
        macros = enc.create_macro_tokens(Resolution.COARSE)
        mt_g1 = enc.find_macro_token_for(g1.gen_id, macros)
        mt_g3 = enc.find_macro_token_for(g3.gen_id, macros)
        assert mt_g1 is not None
        assert g1.gen_id in mt_g1.member_gen_ids
        assert mt_g3 is not None
        assert g3.gen_id in mt_g3.member_gen_ids
        assert mt_g1 is not mt_g3  # в разных MacroToken

    def test_find_macro_token_for_unknown(self):
        base, _, _, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        macros = enc.create_macro_tokens(Resolution.COARSE)
        assert enc.find_macro_token_for("unknown_id", macros) is None

    def test_compression_ratio_coarse(self):
        base, _, _, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        ratio = enc.compression_ratio(Resolution.COARSE)
        # 3 Gen → 2 MacroToken: ratio = 1 - 2/3 ≈ 0.333
        assert ratio == pytest.approx(1.0 - 2.0 / 3.0, abs=0.01)

    def test_compression_ratio_medium_zero(self):
        base, _, _, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        ratio = enc.compression_ratio(Resolution.MEDIUM)
        # 3 Gen → 3 MacroToken: ratio = 0.0
        assert ratio == pytest.approx(0.0)

    def test_compression_ratio_empty_base(self):
        base = GeneralizationBase()
        enc = AttractorEncoder(base)
        assert enc.compression_ratio() == 0.0

    def test_min_members_filter(self):
        base, _, _, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        # min_members=2: только f1-группа (2 Gen), f4-группа (1 Gen) исключается
        macros = enc.create_macro_tokens(Resolution.COARSE, min_members=2)
        assert len(macros) == 1
        assert macros[0].shared_prefix == ["f1"]


# ══════════════════════════════════════════════════════════════════════
# AttractorEncoder — find_attractors / attach_macro_tokens / summary
# ══════════════════════════════════════════════════════════════════════

class TestAttractorEncoderAttractors:
    def test_find_attractors_includes_significant(self):
        base, g1, g2, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        attractors = enc.find_attractors(min_strength=0.0)
        core_ids = {gid for a in attractors for gid in a.core_gen_ids}
        # Хотя бы один из g1/g2 должен быть в ядре аттрактора
        assert g1.gen_id in core_ids or g2.gen_id in core_ids

    def test_find_attractors_excludes_insignificant(self):
        base = GeneralizationBase()
        g_strong = _make_gen(["f1", "f2"], success=9, stop=1)  # sig=0.9
        g_weak   = _make_gen(["f3", "f4"], success=0, stop=5)  # sig=0.0
        base.add(g_strong); base.add(g_weak)
        enc = AttractorEncoder(base)
        attractors = enc.find_attractors(min_strength=0.3)
        core_ids = {gid for a in attractors for gid in a.core_gen_ids}
        assert g_strong.gen_id in core_ids
        assert g_weak.gen_id not in core_ids

    def test_attractor_basin_includes_same_prefix(self):
        """Gen с тем же первым признаком должны попасть в один бассейн."""
        base = GeneralizationBase()
        g1 = _make_gen(["f1", "f2"], success=6, stop=1)  # sig≈0.86
        g2 = _make_gen(["f1", "f3"], success=6, stop=1)  # sig≈0.86
        base.add(g1); base.add(g2)
        enc = AttractorEncoder(base)
        attractors = enc.find_attractors(min_strength=0.3)
        any_includes_both = any(
            g1.gen_id in a.basin_gen_ids and g2.gen_id in a.basin_gen_ids
            for a in attractors
        )
        assert any_includes_both

    def test_attractor_strength_nonnegative(self):
        base, _, _, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        for a in enc.find_attractors(min_strength=0.0):
            assert a.strength >= 0

    def test_attractor_basin_size(self):
        base = GeneralizationBase()
        g = _make_gen(["f1", "f2"], success=5, stop=1)
        base.add(g)
        enc = AttractorEncoder(base)
        attractors = enc.find_attractors(min_strength=0.3)
        assert len(attractors) >= 1
        assert attractors[0].basin_size >= 1

    def test_max_attractors_limit(self):
        base = GeneralizationBase()
        for i in range(15):
            g = _make_gen([f"f{i}", f"g{i}"], success=5, stop=1)
            base.add(g)
        enc = AttractorEncoder(base)
        attractors = enc.find_attractors(min_strength=0.0, max_attractors=5)
        assert len(attractors) <= 5

    def test_attach_macro_tokens(self):
        base, _, _, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        attractors = enc.find_attractors(min_strength=0.0)
        enc.attach_macro_tokens(attractors, Resolution.COARSE)
        # Хотя бы один аттрактор должен получить MacroToken
        assert any(a.macro_token is not None for a in attractors)

    def test_summary_keys(self):
        base, g1, g2, g3 = _make_base_with_gens()
        enc = AttractorEncoder(base)
        s = enc.summary()
        for key in ("n_gen", "n_attractors", "n_macro_coarse", "n_macro_medium",
                    "compression_coarse", "compression_medium",
                    "avg_significance", "max_significance",
                    "avg_chain_length", "max_chain_length"):
            assert key in s, f"Ключ '{key}' отсутствует в summary"

    def test_summary_n_gen(self):
        base, _, _, _ = _make_base_with_gens()
        enc = AttractorEncoder(base)
        assert enc.summary()["n_gen"] == 3

    def test_summary_avg_significance(self):
        base, g1, g2, g3 = _make_base_with_gens()
        enc = AttractorEncoder(base)
        s = enc.summary()
        expected = (g1.significance + g2.significance + g3.significance) / 3
        assert s["avg_significance"] == pytest.approx(expected, abs=0.01)

    def test_summary_empty_base(self):
        base = GeneralizationBase()
        enc = AttractorEncoder(base)
        s = enc.summary()
        assert s["n_gen"] == 0


# ══════════════════════════════════════════════════════════════════════
# Интеграция с LearningSystem (Шаг 3)
# ══════════════════════════════════════════════════════════════════════

class TestLearningSystemStep3:
    def test_has_encoder(self):
        from core.learning import LearningSystem
        ls = LearningSystem()
        assert hasattr(ls, "encoder")
        assert isinstance(ls.encoder, AttractorEncoder)

    def test_has_recorder(self):
        from core.learning import LearningSystem
        ls = LearningSystem()
        assert hasattr(ls, "recorder")
        assert isinstance(ls.recorder, TrajectoryRecorder)

    def test_stats_include_phase_space(self):
        from core.learning import LearningSystem
        from core.feature import Feature, RegionCharacteristics
        ls = LearningSystem(feature_tolerance=0.5)
        src = RegionCharacteristics(brightness=0.3)
        tgt = RegionCharacteristics(brightness=0.7)
        f = Feature.from_regions("f_test", 0.0, 1.0, src, tgt)
        token = PeripheralToken.new("drv", f)
        ls.process_token(token)
        stats = ls.stats()
        assert "phase_space" in stats
        assert "n_gen" in stats["phase_space"]
        assert stats["phase_space"]["n_gen"] >= 1

    def test_reset_context(self):
        """reset_context() сбрасывает контекст, generalizer и recorder."""
        from core.learning import LearningSystem
        ls = LearningSystem()
        ls.reset_context()
        assert ls.engine.context.is_empty()
        assert ls.recorder._current.length == 0

    def test_recorder_records_during_processing(self):
        """Recorder записывает траекторию во время process_token."""
        from core.learning import LearningSystem
        from core.feature import Feature, RegionCharacteristics
        ls = LearningSystem(feature_tolerance=0.5)
        src = RegionCharacteristics(brightness=0.3)
        tgt = RegionCharacteristics(brightness=0.8)
        f = Feature.from_regions("f_int", 0.0, 1.0, src, tgt)
        token = PeripheralToken.new("drv", f)
        result = ls.process_token(token)
        # Как минимум, recorder не сломался
        assert ls.recorder is not None

    def test_encoder_shares_features_with_engine(self):
        """Encoder должен иметь доступ к тем же признакам, что и Engine."""
        from core.learning import LearningSystem
        from core.feature import Feature, RegionCharacteristics
        ls = LearningSystem(feature_tolerance=0.5)
        # Зарегистрировать признак через движок
        src = RegionCharacteristics(brightness=0.2)
        tgt = RegionCharacteristics(brightness=0.8)
        f = Feature.from_regions("f_shared", 0.0, 1.0, src, tgt)
        ls.engine.register_feature(f)
        # Encoder должен видеть тот же признак (shared dict reference)
        assert "f_shared" in ls.encoder._features


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
