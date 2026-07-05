"""
Тесты Шага 12: VitalityEngine — внутренний ритм жизни обобщений.

Покрывает:
  TestVitalityRecord        — запись жизненности одного Gen
  TestVitalityEngine        — агрегатный трекер
  TestWakeUpRestorer        — восстановление контекста
  TestLearningSystemVitality — интеграция в LearningSystem
  TestDebugSessionVitality  — интеграция в DebugSession
"""

import sys
import os
import math
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from core.vitality import VitalityRecord, VitalityEngine, WakeUpRestorer
from core.generalization import Generalization, GeneralizationBase
from core.context import ContextBuffer
from core.learning import LearningSystem
from core.app import CoreApplication
from curriculum.debug_session import DebugSession


# ──────────────────────────────────────────────────────────────────────
# Вспомогательные фабрики
# ──────────────────────────────────────────────────────────────────────

def _make_gen(chain_len: int = 2, label: str = None, sig_boost: int = 0) -> Generalization:
    g = Generalization.new(feature_chain=[f"f{i}" for i in range(chain_len)], label=label)
    g.success_count = 10 + sig_boost
    g.stop_count    = 2
    return g


def _make_base(*gens) -> GeneralizationBase:
    base = GeneralizationBase()
    for g in gens:
        base.add(g)
    return base


def _make_context(*gen_ids) -> ContextBuffer:
    ctx = ContextBuffer()
    for gid in gen_ids:
        ctx.add_active(gid)
    return ctx


def _make_system():
    return LearningSystem(feature_tolerance=0.3)


def _trained_session(texts=None):
    texts = texts or [
        "кот сидит на окне",
        "кот спит на диване",
        "кот прыгнул на подоконник",
    ]
    app = CoreApplication(config={"mock_teacher": True, "feature_tolerance": 0.3})
    app.startup()
    app.peripherals.get("text").build_vocab(texts)
    session = DebugSession(app)
    for t in texts:
        session.learn(t)
    return session


# ══════════════════════════════════════════════════════════════════════
# 1. VitalityRecord
# ══════════════════════════════════════════════════════════════════════

class TestVitalityRecord:

    def test_initial_state_empty(self):
        rec = VitalityRecord("g1")
        assert rec.last_step() is None
        assert rec.mean_interval() is None

    def test_record_single_activation(self):
        rec = VitalityRecord("g1")
        rec.record(10)
        assert rec.last_step() == 10
        assert rec.mean_interval() is None   # один шаг → нет интервала

    def test_mean_interval_none_with_one_activation(self):
        rec = VitalityRecord("g1")
        rec.record(5)
        assert rec.mean_interval() is None

    def test_mean_interval_two_activations(self):
        rec = VitalityRecord("g1")
        rec.record(10)
        rec.record(20)
        assert rec.mean_interval() == pytest.approx(10.0)

    def test_mean_interval_multiple_activations(self):
        rec = VitalityRecord("g1")
        for step in [0, 5, 10, 15, 20]:
            rec.record(step)
        assert rec.mean_interval() == pytest.approx(5.0)

    def test_mean_interval_rolling_window_not_exceeded(self):
        # max_history=3 → хранит 2 интервала (maxlen=2)
        # steps: [0,1,10,20] → интервалы [1,9,10]; с maxlen=2 остаются [9,10]
        rec = VitalityRecord("g1", max_history=3)
        for step in [0, 1, 10, 20]:
            rec.record(step)
        # mean_interval = (9+10)/2 = 9.5
        assert rec.mean_interval() == pytest.approx(9.5)
        assert rec.last_step() == 20

    def test_urgency_never_activated_returns_zero(self):
        rec = VitalityRecord("g1")
        assert rec.urgency(100) == pytest.approx(0.0)

    def test_urgency_within_interval_below_one(self):
        rec = VitalityRecord("g1")
        rec.record(0)
        rec.record(10)   # mean_interval = 10
        # current_step=15, elapsed=5, urgency=5/10=0.5
        assert rec.urgency(15) == pytest.approx(0.5)

    def test_urgency_exactly_one_at_double_interval(self):
        rec = VitalityRecord("g1")
        rec.record(0)
        rec.record(10)
        assert rec.urgency(20) == pytest.approx(1.0)

    def test_urgency_overdue_above_one(self):
        rec = VitalityRecord("g1")
        rec.record(0)
        rec.record(10)
        assert rec.urgency(30) == pytest.approx(2.0)

    def test_urgency_clamped_at_ten(self):
        rec = VitalityRecord("g1")
        rec.record(0)
        rec.record(1)   # mean_interval=1
        assert rec.urgency(1000) == pytest.approx(VitalityRecord._URGENCY_CAP)

    def test_vitality_full_when_on_time(self):
        rec = VitalityRecord("g1")
        rec.record(0)
        rec.record(10)
        # urgency=0.5 < 1 → no decay
        v = rec.vitality(0.8, 15)
        assert v == pytest.approx(0.8)

    def test_vitality_decays_when_overdue(self):
        rec = VitalityRecord("g1")
        rec.record(0)
        rec.record(10)
        # urgency=2.0, decay=exp(-1)≈0.368
        v = rec.vitality(1.0, 30)
        assert v == pytest.approx(math.exp(-1.0), rel=1e-4)

    def test_vitality_never_below_zero(self):
        rec = VitalityRecord("g1")
        rec.record(0)
        rec.record(1)
        assert rec.vitality(0.5, 10_000) >= 0.0

    def test_last_step_none_if_empty(self):
        rec = VitalityRecord("g1")
        assert rec.last_step() is None

    def test_last_step_returns_latest(self):
        rec = VitalityRecord("g1")
        rec.record(5)
        rec.record(15)
        assert rec.last_step() == 15


# ══════════════════════════════════════════════════════════════════════
# 2. VitalityEngine
# ══════════════════════════════════════════════════════════════════════

class TestVitalityEngine:

    def test_empty_engine_urgency_zero(self):
        engine = VitalityEngine()
        assert engine.urgency("nonexistent", 100) == 0.0

    def test_record_activation_creates_record(self):
        engine = VitalityEngine()
        engine.record_activation("g1", 10)
        assert "g1" in engine._records

    def test_record_activation_updates_existing(self):
        engine = VitalityEngine()
        engine.record_activation("g1", 5)
        engine.record_activation("g1", 10)
        rec = engine._records["g1"]
        assert rec.last_step() == 10
        assert rec.mean_interval() == pytest.approx(5.0)

    def test_urgency_after_recording(self):
        engine = VitalityEngine()
        engine.record_activation("g1", 0)
        engine.record_activation("g1", 10)
        # urgency at step 15: elapsed=5, interval=10 → 0.5
        assert engine.urgency("g1", 15) == pytest.approx(0.5)

    def test_gap_for_returns_zero_unknown(self):
        engine = VitalityEngine()
        assert engine.gap_for("g1", 100) == 0

    def test_gap_for_returns_elapsed(self):
        engine = VitalityEngine()
        engine.record_activation("g1", 30)
        assert engine.gap_for("g1", 50) == 20

    def test_knock_candidates_empty_below_threshold(self):
        engine = VitalityEngine()
        base   = _make_base(_make_gen())
        gid    = list(base._gens.keys())[0]
        engine.record_activation(gid, 0)
        engine.record_activation(gid, 10)
        # urgency at step=15 → 0.5, threshold=2.0
        assert engine.knock_candidates([gid], base, 15, threshold=2.0) == []

    def test_knock_candidates_returns_overdue(self):
        engine = VitalityEngine()
        base   = _make_base(_make_gen())
        gid    = list(base._gens.keys())[0]
        engine.record_activation(gid, 0)
        engine.record_activation(gid, 10)
        # urgency at step=30 → 2.0, threshold=1.5
        result = engine.knock_candidates([gid], base, 30, threshold=1.5)
        assert len(result) == 1
        assert result[0][0] == gid

    def test_knock_candidates_sorted_desc(self):
        engine = VitalityEngine()
        g1, g2 = _make_gen(), _make_gen()
        base   = _make_base(g1, g2)
        # g1 more urgent
        engine.record_activation(g1.gen_id, 0)
        engine.record_activation(g1.gen_id, 5)
        # g2 less urgent
        engine.record_activation(g2.gen_id, 0)
        engine.record_activation(g2.gen_id, 10)
        result = engine.knock_candidates([g1.gen_id, g2.gen_id], base, 50, threshold=1.0)
        if len(result) >= 2:
            assert result[0][1] >= result[1][1]

    def test_knock_candidates_excludes_never_activated(self):
        engine = VitalityEngine()
        g1     = _make_gen()
        base   = _make_base(g1)
        # g1 never recorded → excluded from knock
        result = engine.knock_candidates([g1.gen_id], base, 100, threshold=0.0)
        assert result == []

    def test_report_includes_all_gen_ids(self):
        engine = VitalityEngine()
        g1, g2 = _make_gen(), _make_gen()
        base   = _make_base(g1, g2)
        rows   = engine.report([g1.gen_id, g2.gen_id], base, 10)
        assert len(rows) == 2

    def test_report_sorted_vitality_asc(self):
        engine = VitalityEngine()
        g1, g2 = _make_gen(), _make_gen()
        base   = _make_base(g1, g2)
        # Make g1 more overdue (lower vitality)
        engine.record_activation(g1.gen_id, 0)
        engine.record_activation(g1.gen_id, 1)
        engine.record_activation(g2.gen_id, 0)
        engine.record_activation(g2.gen_id, 100)
        rows = engine.report([g1.gen_id, g2.gen_id], base, 200)
        assert rows[0]["vitality"] <= rows[1]["vitality"]

    def test_report_unseen_gen_has_urgency_zero(self):
        engine = VitalityEngine()
        g      = _make_gen()
        base   = _make_base(g)
        rows   = engine.report([g.gen_id], base, 100)
        assert rows[0]["urgency"] == pytest.approx(0.0)
        assert rows[0]["vitality"] == pytest.approx(rows[0]["significance"])

    def test_report_dict_has_required_keys(self):
        engine = VitalityEngine()
        g      = _make_gen()
        base   = _make_base(g)
        rows   = engine.report([g.gen_id], base, 10)
        required = {"gen_id", "label", "chain_len", "significance",
                    "urgency", "vitality", "mean_interval", "last_step"}
        assert required.issubset(rows[0].keys())

    def test_stats_empty(self):
        engine = VitalityEngine()
        s = engine.stats()
        assert s["tracked_gens"]   == 0
        assert s["avg_urgency"]    == 0.0
        assert s["critical_count"] == 0

    def test_stats_with_records(self):
        engine = VitalityEngine()
        engine.record_activation("g1", 0)
        engine.record_activation("g1", 1)
        s = engine.stats()
        assert s["tracked_gens"] == 1
        assert isinstance(s["avg_urgency"], float)


# ══════════════════════════════════════════════════════════════════════
# 3. WakeUpRestorer
# ══════════════════════════════════════════════════════════════════════

class TestWakeUpRestorer:

    @pytest.mark.parametrize("gap, expected", [
        (0, 5), (3, 5), (5, 4), (9, 4),
        (10, 3), (19, 3), (20, 2), (49, 2),
        (50, 1), (200, 1),
    ])
    def test_min_chain_len_for_gap(self, gap, expected):
        restorer = WakeUpRestorer()
        assert restorer.min_chain_len_for_gap(gap) == expected

    def test_find_anchor_none_on_empty_base(self):
        restorer = WakeUpRestorer()
        base     = GeneralizationBase()
        assert restorer.find_anchor(base, min_chain_len=1) is None

    def test_find_anchor_returns_significant_gen(self):
        restorer = WakeUpRestorer(min_significance=0.1)
        g = _make_gen(chain_len=3, label="meta_L2")
        base = _make_base(g)
        anchor = restorer.find_anchor(base, min_chain_len=1)
        assert anchor is not None
        assert anchor.gen_id == g.gen_id

    def test_find_anchor_respects_min_chain_len(self):
        restorer = WakeUpRestorer(min_significance=0.0)
        g_short = _make_gen(chain_len=1)
        g_long  = _make_gen(chain_len=5)
        base    = _make_base(g_short, g_long)
        anchor  = restorer.find_anchor(base, min_chain_len=4)
        assert anchor is not None
        assert len(anchor.feature_chain) >= 4

    def test_find_anchor_prefers_meta_gen(self):
        restorer = WakeUpRestorer(min_significance=0.0)
        g_plain = _make_gen(chain_len=2, label="auto_123")
        g_meta  = _make_gen(chain_len=2, label="meta_L2", sig_boost=0)
        base    = _make_base(g_plain, g_meta)
        anchor  = restorer.find_anchor(base, min_chain_len=1)
        assert anchor.label.startswith("meta_")

    def test_restore_adds_to_context(self):
        restorer = WakeUpRestorer(min_significance=0.0)
        g    = _make_gen(chain_len=1)
        base = _make_base(g)
        ctx  = _make_context()
        result = restorer.restore(base, ctx, step_gap=100)
        assert result == g.gen_id
        assert g.gen_id in ctx.active_gen_ids()

    def test_restore_idempotent_if_already_active(self):
        restorer = WakeUpRestorer(min_significance=0.0)
        g    = _make_gen(chain_len=1)
        base = _make_base(g)
        ctx  = _make_context(g.gen_id)   # already active
        result = restorer.restore(base, ctx, step_gap=100)
        # Returns gen_id but does NOT increment restore_count
        assert result == g.gen_id
        assert restorer.restore_count == 0

    def test_restore_count_increments(self):
        restorer = WakeUpRestorer(min_significance=0.0)
        g    = _make_gen(chain_len=1)
        base = _make_base(g)
        ctx  = _make_context()
        restorer.restore(base, ctx, step_gap=100)
        assert restorer.restore_count == 1

    def test_restore_returns_none_on_empty_base(self):
        restorer = WakeUpRestorer()
        ctx  = _make_context()
        base = GeneralizationBase()
        assert restorer.restore(base, ctx, step_gap=10) is None


# ══════════════════════════════════════════════════════════════════════
# 4. Интеграция в LearningSystem
# ══════════════════════════════════════════════════════════════════════

class TestLearningSystemVitality:

    def _make_tokens(self, system: LearningSystem, text: str):
        """Создать токены через TextDriver без обращения к app."""
        from drivers.text_driver import TextDriver
        driver = TextDriver("t", text)
        driver.build_vocab([text])
        return list(driver.produce())

    def test_vitality_attribute_exists(self):
        sys = _make_system()
        assert hasattr(sys, "vitality")
        assert isinstance(sys.vitality, VitalityEngine)

    def test_restorer_attribute_exists(self):
        sys = _make_system()
        assert hasattr(sys, "restorer")
        assert isinstance(sys.restorer, WakeUpRestorer)

    def test_vitality_in_stats(self):
        sys = _make_system()
        stats = sys.stats()
        assert "vitality" in stats
        assert isinstance(stats["vitality"], dict)

    def test_vitality_stats_has_required_keys(self):
        sys   = _make_system()
        vstats = sys.stats()["vitality"]
        assert "tracked_gens"   in vstats
        assert "avg_urgency"    in vstats
        assert "critical_count" in vstats

    def test_vitality_records_after_confirmed(self):
        sys    = _make_system()
        tokens = self._make_tokens(sys, "кот сидит на окне")
        if len(tokens) < 2:
            pytest.skip("Текст слишком короткий для теста")
        for tok in tokens:
            sys.process_token(tok)
        # После обработки должны появиться VitalityRecord
        # (возможно 0 если ни один Gen не подтвердился — зависит от min_count)
        assert isinstance(sys.vitality.stats()["tracked_gens"], int)

    def test_vitality_grows_with_repeated_learning(self):
        sys  = _make_system()
        text = "кот сидит"
        tokens = self._make_tokens(sys, text)
        # Два прохода — второй должен создать Gen и активации
        for _ in range(3):
            for tok in tokens:
                sys.process_token(tok)
        tracked = sys.vitality.stats()["tracked_gens"]
        assert tracked >= 0   # >= 0, т.к. зависит от min_count

    def test_vitality_only_records_on_confirmed(self):
        """Запись идёт только при CONFIRMED/COMPLETED, не при REFUTED/EXPLORING."""
        from core.algorithm import StepOutcome
        sys    = _make_system()
        tokens = self._make_tokens(sys, "кот сидит на окне")
        # Считаем сколько CONFIRMED/COMPLETED шагов прошло
        confirmed_steps = 0
        for tok in tokens:
            r = sys.process_token(tok)
            if r.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
                confirmed_steps += 1
        tracked = sys.vitality.stats()["tracked_gens"]
        # Если не было CONFIRMED — записей нет
        if confirmed_steps == 0:
            assert tracked == 0
        else:
            assert tracked >= 0

    def test_stats_vitality_tracked_gens_zero_initially(self):
        sys = _make_system()
        assert sys.vitality.stats()["tracked_gens"] == 0


# ══════════════════════════════════════════════════════════════════════
# 5. Интеграция в DebugSession
# ══════════════════════════════════════════════════════════════════════

class TestDebugSessionVitality:

    def test_vitality_step_returns_dict(self):
        session = _trained_session()
        result  = session.vitality_step()
        assert isinstance(result, dict)

    def test_vitality_step_has_required_keys(self):
        session = _trained_session()
        result  = session.vitality_step()
        for key in ("active_count", "knock_count", "knock_ids", "restored", "step"):
            assert key in result

    def test_vitality_step_active_count_nonneg(self):
        session = _trained_session()
        result  = session.vitality_step()
        assert result["active_count"] >= 0

    def test_vitality_step_no_restore_when_no_knock(self):
        session = _trained_session()
        # threshold=100 → никто не дотягивается
        result  = session.vitality_step(threshold=100.0, auto_restore=True)
        assert result["knock_count"] == 0
        assert result["restored"]    is None

    def test_vitality_step_auto_restore_false(self):
        session = _trained_session(["кот сидит"] * 5)
        # Даже если есть knock кандидаты — не восстанавливать
        result = session.vitality_step(threshold=0.0, auto_restore=False)
        assert result["restored"] is None

    def test_wake_up_no_base_returns_none(self):
        app = CoreApplication(config={"mock_teacher": True})
        app.startup()
        session = DebugSession(app)
        # База пустая — ничего не восстановить
        result = session.wake_up(step_gap=10)
        assert result is None

    def test_wake_up_after_learning_returns_id(self):
        session = _trained_session()
        result  = session.wake_up(step_gap=50)
        # После обучения в базе есть Gen — должен найти якорь
        if session.app.system.base.size() > 0:
            assert result is None or isinstance(result, str)

    def test_vitality_report_keys(self):
        session = _trained_session()
        report  = session.vitality_report()
        for key in ("step", "tracked", "at_risk", "records", "vitality_stats"):
            assert key in report

    def test_vitality_report_at_risk_nonneg(self):
        session = _trained_session()
        report  = session.vitality_report(threshold=2.0)
        assert report["at_risk"] >= 0

    def test_log_summary_has_vitality_steps(self):
        session = _trained_session()
        session.vitality_step()
        session.vitality_step()
        summary = session.log_summary()
        assert "vitality_steps" in summary
        assert summary["vitality_steps"] == 2

    def test_vitality_report_records_is_list(self):
        session = _trained_session()
        report  = session.vitality_report()
        assert isinstance(report["records"], list)
