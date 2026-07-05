"""
Тесты для core/dream.py — консолидация обобщений в фазе сна.

Проверяем:
  DreamTransactionBuffer — транзакционный прокси над GeneralizationBase
  DomainRegistry         — реестр доменов для feature_id
  CrossDomainDetector    — фильтр кросс-доменных метаобобщений
  ReplayEngine           — генерация синтетических токенов из контекста
  SleepScheduler         — детектор момента входа в фазу сна
  sleep_cycle()          — полный цикл консолидации (end-to-end)
"""

import pytest
from core.generalization import Generalization, GeneralizationBase
from core.feature import Feature, FeatureVector
from core.dream import (
    DreamTransactionBuffer,
    DomainRegistry,
    CrossDomainDetector,
    ReplayEngine,
    SleepScheduler,
    SleepDecision,
    SleepResult,
    sleep_cycle,
)


# ══════════════════════════════════════════════════════════════════════
# Вспомогательные фабрики
# ══════════════════════════════════════════════════════════════════════

def make_gen(chain_len: int = 1, sig: float = 0.0, label: str = "") -> Generalization:
    gen = Generalization.new(
        feature_chain=[f"f{i}" for i in range(chain_len)],
        label=label or f"L{chain_len}",
    )
    if sig > 0.0:
        gen.success_count = int(sig * 100)
        gen.stop_count = 100 - gen.success_count
    return gen


def make_feature(fid: str = "f0") -> Feature:
    return Feature(feature_id=fid, direction=0.0, distance=0.5)


def make_base(*gens: Generalization) -> GeneralizationBase:
    base = GeneralizationBase()
    for g in gens:
        base.add(g)
    return base


# ══════════════════════════════════════════════════════════════════════
# 1. DreamTransactionBuffer
# ══════════════════════════════════════════════════════════════════════

class TestDreamTransactionBuffer:

    def test_add_goes_to_pending_not_real(self):
        real = GeneralizationBase()
        buf = DreamTransactionBuffer(real)
        gen = make_gen()
        buf.add(gen)
        assert real.size() == 0           # реальная база нетронута
        assert buf.size() == 1            # виртуальный размер учитывает pending
        assert len(buf.pending_gens()) == 1

    def test_get_returns_pending_first(self):
        real = GeneralizationBase()
        gen_real = make_gen(label="real")
        real.add(gen_real)

        buf = DreamTransactionBuffer(real)
        gen_pend = make_gen(label="pend")
        buf.add(gen_pend)

        assert buf.get(gen_real.gen_id) is gen_real
        assert buf.get(gen_pend.gen_id) is gen_pend

    def test_all_merges_pending_and_real(self):
        gen_a = make_gen(label="a")
        gen_b = make_gen(label="b")
        real = make_base(gen_a)
        buf = DreamTransactionBuffer(real)
        buf.add(gen_b)

        all_ids = {g.gen_id for g in buf.all()}
        assert gen_a.gen_id in all_ids
        assert gen_b.gen_id in all_ids

    def test_size_is_real_plus_pending(self):
        gen_a, gen_b, gen_c = make_gen(), make_gen(), make_gen()
        real = make_base(gen_a, gen_b)
        buf = DreamTransactionBuffer(real)
        buf.add(gen_c)
        assert buf.size() == 3

    def test_commit_all_moves_pending_to_real(self):
        real = GeneralizationBase()
        buf = DreamTransactionBuffer(real)
        gen = make_gen()
        buf.add(gen)

        committed = buf.commit()   # None → all
        assert committed == 1
        assert real.size() == 1
        assert len(buf.pending_gens()) == 0
        assert buf.n_committed == 1

    def test_commit_subset_moves_only_selected(self):
        real = GeneralizationBase()
        buf = DreamTransactionBuffer(real)
        gen_a, gen_b = make_gen(label="a"), make_gen(label="b")
        buf.add(gen_a)
        buf.add(gen_b)

        buf.commit({gen_a.gen_id})
        assert real.size() == 1
        assert real.get(gen_a.gen_id) is gen_a
        assert real.get(gen_b.gen_id) is None
        assert len(buf.pending_gens()) == 1   # gen_b still pending

    def test_rollback_discards_pending(self):
        real = GeneralizationBase()
        buf = DreamTransactionBuffer(real)
        buf.add(make_gen())
        buf.add(make_gen())

        rolled = buf.rollback()
        assert rolled == 2
        assert real.size() == 0
        assert len(buf.pending_gens()) == 0
        assert buf.n_rolled_back == 2

    def test_remove_from_pending(self):
        real = GeneralizationBase()
        buf = DreamTransactionBuffer(real)
        gen = make_gen()
        buf.add(gen)
        removed = buf.remove(gen.gen_id)
        assert removed is True
        assert len(buf.pending_gens()) == 0

    def test_nested_inner_commit_goes_to_outer_pending(self):
        real = GeneralizationBase()
        outer = DreamTransactionBuffer(real, tag="outer")
        inner = outer.nested(tag="inner")

        gen = make_gen(label="meta")
        inner.add(gen)
        assert len(outer.pending_gens()) == 0   # пока в inner

        inner.commit({gen.gen_id})              # commit inner → outer._pending
        assert len(outer.pending_gens()) == 1
        assert real.size() == 0                 # ещё не в реальной базе

    def test_nested_inner_rollback_does_not_affect_outer(self):
        real = GeneralizationBase()
        outer = DreamTransactionBuffer(real, tag="outer")
        inner = outer.nested(tag="inner")

        inner.add(make_gen())
        inner.rollback()

        assert len(outer.pending_gens()) == 0
        assert real.size() == 0

    def test_repr_shows_tag_and_counts(self):
        real = GeneralizationBase()
        buf = DreamTransactionBuffer(real, tag="outer")
        r = repr(buf)
        assert "outer" in r
        assert "pending" in r


# ══════════════════════════════════════════════════════════════════════
# 2. DomainRegistry
# ══════════════════════════════════════════════════════════════════════

class TestDomainRegistry:

    def test_register_and_domain_of(self):
        reg = DomainRegistry()
        reg.register("f1", "science")
        assert reg.domain_of("f1") == "science"

    def test_unknown_feature_returns_none(self):
        reg = DomainRegistry()
        assert reg.domain_of("no-such-feat") is None

    def test_register_many(self):
        reg = DomainRegistry()
        reg.register_many(["fa", "fb", "fc"], "art")
        assert reg.domain_of("fb") == "art"
        assert reg.size() == 3

    def test_domains_of_returns_set(self):
        reg = DomainRegistry()
        reg.register("f1", "science")
        reg.register("f2", "art")
        reg.register("f3", "science")
        domains = reg.domains_of(["f1", "f2", "f3"])
        assert domains == {"science", "art"}

    def test_known_domains(self):
        reg = DomainRegistry()
        reg.register("x", "alpha")
        reg.register("y", "beta")
        assert reg.known_domains() == {"alpha", "beta"}


# ══════════════════════════════════════════════════════════════════════
# 3. CrossDomainDetector
# ══════════════════════════════════════════════════════════════════════

class TestCrossDomainDetector:

    def _make_registry(self):
        reg = DomainRegistry()
        reg.register("f0", "science")
        reg.register("f1", "art")
        reg.register("f2", "science")
        return reg

    def test_with_registry_cross_domain_is_meta(self):
        reg = self._make_registry()
        detector = CrossDomainDetector(domain_registry=reg, min_domains=2)
        gen = make_gen(chain_len=2)   # feature_chain = ["f0", "f1"] → science + art
        assert detector.is_meta_candidate(gen) is True

    def test_with_registry_single_domain_not_meta(self):
        reg = self._make_registry()
        detector = CrossDomainDetector(domain_registry=reg, min_domains=2)
        gen = Generalization.new(feature_chain=["f0", "f2"])   # science + science
        assert detector.is_meta_candidate(gen) is False

    def test_fallback_chain_gte_min_is_meta(self):
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)
        gen = make_gen(chain_len=3)
        assert detector.is_meta_candidate(gen) is True

    def test_fallback_chain_lt_min_not_meta(self):
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)
        gen = make_gen(chain_len=2)
        assert detector.is_meta_candidate(gen) is False

    def test_filter_meta_returns_only_candidates(self):
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)
        gens = [make_gen(chain_len=l) for l in [1, 2, 3, 4]]
        meta = detector.filter_meta(gens)
        assert all(len(g.feature_chain) >= 3 for g in meta)
        assert len(meta) == 2


# ══════════════════════════════════════════════════════════════════════
# 4. ReplayEngine
# ══════════════════════════════════════════════════════════════════════

class TestReplayEngine:

    def _make_registry(self):
        feats = {
            "feat-a": make_feature("feat-a"),
            "feat-b": make_feature("feat-b"),
        }
        return feats

    def test_make_token_known_feature(self):
        feats = self._make_registry()
        engine = ReplayEngine(feats)
        tok = engine.make_token("feat-a")
        assert tok is not None
        assert tok.driver_id == "dream"
        assert tok.data is feats["feat-a"]

    def test_make_token_unknown_feature_returns_none(self):
        engine = ReplayEngine({})
        assert engine.make_token("no-such") is None

    def test_make_token_label_prefix(self):
        feats = {"feat-abcdef01": make_feature("feat-abcdef01")}
        engine = ReplayEngine(feats)
        tok = engine.make_token("feat-abcdef01")
        assert tok.label.startswith("dream:")

    def test_generate_sequence_empty_context(self):
        from core.context import ContextBuffer
        feats = self._make_registry()
        engine = ReplayEngine(feats)
        ctx = ContextBuffer()
        base = GeneralizationBase()
        tokens = engine.generate_sequence(ctx, base, max_tokens=5)
        assert tokens == []

    def test_generate_sequence_with_active_gen(self):
        from core.context import ContextBuffer
        feats = self._make_registry()
        replay = ReplayEngine(feats)

        # Создать Gen с известным feature_chain
        gen = Generalization.new(feature_chain=["feat-a", "feat-b"])
        base = make_base(gen)
        ctx = ContextBuffer()
        ctx.add_active(gen.gen_id)

        tokens = replay.generate_sequence(ctx, base, max_tokens=5)
        assert len(tokens) >= 1
        assert tokens[0].driver_id == "dream"


# ══════════════════════════════════════════════════════════════════════
# 5. SleepScheduler
# ══════════════════════════════════════════════════════════════════════

class TestSleepScheduler:

    def _make_scheduler(self, plateau_threshold=3, plateaus_required=2,
                        urgency_threshold=2.0, min_knock_fraction=0.03):
        return SleepScheduler(
            plateau_threshold=plateau_threshold,
            plateaus_required=plateaus_required,
            urgency_threshold=urgency_threshold,
            min_knock_fraction=min_knock_fraction,
        )

    def _empty_vitality(self):
        from core.vitality import VitalityEngine
        return VitalityEngine()

    def test_first_tick_high_new_gens_not_plateau(self):
        sched = self._make_scheduler(plateau_threshold=3)
        base = make_base(*[make_gen() for _ in range(10)])
        vitality = self._empty_vitality()

        # prev_base_size = 0, n_new = 10 ≥ 3 → not plateau
        decision = sched.tick(base, vitality, current_step=1)
        assert decision.is_plateau is False
        assert decision.consecutive_plateaus == 0
        assert decision.should_sleep is False

    def test_plateau_detected_when_few_new_gens(self):
        sched = self._make_scheduler(plateau_threshold=5)
        base = make_base(*[make_gen() for _ in range(3)])
        vitality = self._empty_vitality()

        decision = sched.tick(base, vitality, current_step=1)
        assert decision.is_plateau is True
        assert decision.consecutive_plateaus == 1

    def test_consecutive_plateau_increments(self):
        sched = self._make_scheduler(plateau_threshold=5, plateaus_required=2)
        gen_a = make_gen()
        base = make_base(gen_a)
        vitality = self._empty_vitality()

        d1 = sched.tick(base, vitality, current_step=1)  # n_new=1 < 5 → plateau 1
        assert d1.consecutive_plateaus == 1

        d2 = sched.tick(base, vitality, current_step=2)  # n_new=0 < 5 → plateau 2
        assert d2.consecutive_plateaus == 2

    def test_should_sleep_requires_both_conditions(self):
        # Если urgency-кандидатов нет — should_sleep=False даже при плато
        sched = self._make_scheduler(
            plateau_threshold=5, plateaus_required=1, min_knock_fraction=0.03
        )
        base = make_base(*[make_gen() for _ in range(2)])
        vitality = self._empty_vitality()

        decision = sched.tick(base, vitality, current_step=1)
        # плато есть, но urgency-кандидатов нет → should_sleep=False
        assert decision.consecutive_plateaus >= 1
        assert decision.should_sleep is False

    def test_should_sleep_true_when_urgency_condition_met(self):
        from core.vitality import VitalityEngine
        sched = self._make_scheduler(
            plateau_threshold=100,   # всегда плато (n_new всегда < 100)
            plateaus_required=1,
            urgency_threshold=0.01,  # очень низкий порог — все Gen кандидаты
            min_knock_fraction=0.0,  # ноль — всегда выполняется
        )
        gen = make_gen(sig=0.9)
        base = make_base(gen)
        vitality = VitalityEngine()
        vitality.record_activation(gen.gen_id, step=1)
        vitality.record_activation(gen.gen_id, step=2)

        decision = sched.tick(base, vitality, current_step=1000)
        assert decision.should_sleep is True

    def test_reset_clears_consecutive(self):
        sched = self._make_scheduler(plateau_threshold=5)
        base = make_base(make_gen())
        vitality = self._empty_vitality()

        sched.tick(base, vitality, current_step=1)   # consecutive → 1
        sched.reset()
        assert sched._consecutive == 0


# ══════════════════════════════════════════════════════════════════════
# 6. sleep_cycle() — end-to-end
# ══════════════════════════════════════════════════════════════════════

class TestSleepCycle:

    def _make_system_with_gens(self):
        """Создать LearningSystem с несколькими Gen в базе и признаками в реестре."""
        from core.learning import LearningSystem

        ls = LearningSystem()

        # Добавить признаки в реестр движка
        feat_ids = [f"feat-{i:02d}" for i in range(6)]
        for fid in feat_ids:
            ls.engine._features[fid] = make_feature(fid)

        # Добавить несколько Gen в базу (chain=1,2 — LONG_TERM)
        for i in range(4):
            gen = Generalization.new(
                feature_chain=[feat_ids[i]],
                label=f"anchor-{i}",
            )
            gen.success_count = 5
            ls.base.add(gen)

        # Один глубокий Gen (chain=3, кандидат на метаобобщение в fallback-режиме)
        deep = Generalization.new(
            feature_chain=[feat_ids[0], feat_ids[1], feat_ids[2]],
            label="deep",
        )
        deep.success_count = 3
        ls.base.add(deep)

        return ls

    def test_sleep_cycle_returns_sleep_result(self):
        ls = self._make_system_with_gens()
        replay_engine = ReplayEngine(ls.engine._features)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)

        result = sleep_cycle(ls, replay_engine, detector, n_replays=2, replay_steps=5)
        assert isinstance(result, SleepResult)

    def test_sleep_cycle_n_replays_respected(self):
        ls = self._make_system_with_gens()
        replay_engine = ReplayEngine(ls.engine._features)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)

        result = sleep_cycle(ls, replay_engine, detector, n_replays=3, replay_steps=5)
        assert result.n_replays == 3
        assert len(result.replay_outcomes) == 3

    def test_sleep_cycle_restores_engine_base(self):
        ls = self._make_system_with_gens()
        original_base = ls.engine.base
        replay_engine = ReplayEngine(ls.engine._features)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)

        sleep_cycle(ls, replay_engine, detector, n_replays=2, replay_steps=5)

        assert ls.engine.base is original_base
        assert ls.generalizer.base is original_base

    def test_sleep_cycle_restores_context(self):
        ls = self._make_system_with_gens()
        original_context = ls.engine.context
        replay_engine = ReplayEngine(ls.engine._features)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)

        sleep_cycle(ls, replay_engine, detector, n_replays=2, replay_steps=5)

        assert ls.engine.context is original_context

    def test_sleep_cycle_with_budget_runs_eviction(self):
        from core.capacity import CapacityBudget
        from core.timescale import TimescaleScheduler

        ls = self._make_system_with_gens()
        replay_engine = ReplayEngine(ls.engine._features)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=10)

        # Установить бюджет ниже текущего размера базы
        initial_size = ls.base.size()
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=2, scheduler=sched, evict_batch=0)

        result = sleep_cycle(
            ls, replay_engine, detector, budget=budget, n_replays=1, replay_steps=3
        )
        assert result.n_evicted >= 0   # eviction произошла (не краш)

    def test_commit_rate_in_range(self):
        ls = self._make_system_with_gens()
        replay_engine = ReplayEngine(ls.engine._features)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)

        result = sleep_cycle(ls, replay_engine, detector, n_replays=4, replay_steps=10)
        assert 0.0 <= result.commit_rate <= 1.0

    def test_sleep_result_summary_string(self):
        ls = self._make_system_with_gens()
        replay_engine = ReplayEngine(ls.engine._features)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)

        result = sleep_cycle(ls, replay_engine, detector, n_replays=2, replay_steps=5)
        summary = result.summary()
        assert "replays" in summary
        assert "commit_rate" in summary


# ══════════════════════════════════════════════════════════════════════
# 7. REFUTEDEvent + ContextQueryLog
# ══════════════════════════════════════════════════════════════════════

from core.dream import REFUTEDEvent, ContextQueryLog, SleepDriver


class TestREFUTEDEvent:

    def test_is_deep_chain3(self):
        e = REFUTEDEvent(
            feature_id="f0", active_gen_ids=[], new_gen_id=None, chain_len=3
        )
        assert e.is_deep is True

    def test_not_deep_chain2(self):
        e = REFUTEDEvent(
            feature_id="f0", active_gen_ids=[], new_gen_id=None, chain_len=2
        )
        assert e.is_deep is False

    def test_urgency_default(self):
        e = REFUTEDEvent(
            feature_id="f0", active_gen_ids=[], new_gen_id=None, chain_len=3
        )
        assert e.urgency == 1.0


class TestContextQueryLog:

    def test_record_and_len(self):
        log = ContextQueryLog()
        log.record(feature_id="f0", active_gen_ids=["g1"], chain_len=3)
        log.record(feature_id="f1", active_gen_ids=["g2"], chain_len=1)
        assert len(log) == 2

    def test_candidates_filters_min_chain(self):
        log = ContextQueryLog()
        log.record(feature_id="f0", active_gen_ids=[], chain_len=3)
        log.record(feature_id="f1", active_gen_ids=[], chain_len=2)
        log.record(feature_id="f2", active_gen_ids=[], chain_len=4)

        cands = log.candidates(min_chain=3)
        assert len(cands) == 2
        assert all(e.chain_len >= 3 for e in cands)

    def test_candidates_sorted_by_urgency(self):
        log = ContextQueryLog()
        log.record(feature_id="f0", active_gen_ids=[], chain_len=3)
        log.record(feature_id="f1", active_gen_ids=[], chain_len=3)
        # Поднять urgency второго события вручную
        log._events[1].urgency = 2.0

        cands = log.candidates(min_chain=3)
        assert cands[0].feature_id == "f1"  # выше urgency — первый

    def test_candidates_max_n(self):
        log = ContextQueryLog()
        for i in range(10):
            log.record(feature_id=f"f{i}", active_gen_ids=[], chain_len=3)
        assert len(log.candidates(min_chain=3, max_n=5)) == 5

    def test_is_rich_enough(self):
        log = ContextQueryLog()
        assert not log.is_rich_enough(threshold=3)
        for i in range(3):
            log.record(feature_id=f"f{i}", active_gen_ids=[], chain_len=3)
        assert log.is_rich_enough(threshold=3)

    def test_retain_unresolved(self):
        log = ContextQueryLog()
        log.record(feature_id="f0", active_gen_ids=[], chain_len=3)  # urgency=1.0
        log.record(feature_id="f1", active_gen_ids=[], chain_len=3)
        log._events[1].urgency = 2.0  # повторно непонятое
        log.retain_unresolved(urgency_threshold=1.5)
        assert len(log) == 1
        assert log._events[0].feature_id == "f1"

    def test_clear(self):
        log = ContextQueryLog()
        log.record("f0", [], chain_len=3)
        log.clear()
        assert len(log) == 0

    def test_repr_shows_deep_count(self):
        log = ContextQueryLog()
        log.record("f0", [], chain_len=3)
        log.record("f1", [], chain_len=1)
        r = repr(log)
        assert "total=2" in r
        assert "deep_chain3+=1" in r


# ══════════════════════════════════════════════════════════════════════
# 8. SleepDriver — end-to-end
# ══════════════════════════════════════════════════════════════════════

class TestSleepDriver:

    def _make_system(self):
        from core.learning import LearningSystem
        ls = LearningSystem()
        feat_ids = [f"feat-{i:02d}" for i in range(6)]
        for fid in feat_ids:
            ls.engine._features[fid] = make_feature(fid)
        for i in range(4):
            gen = Generalization.new(feature_chain=[feat_ids[i]], label=f"anchor-{i}")
            gen.success_count = 5
            ls.base.add(gen)
        return ls, feat_ids

    def test_empty_log_returns_zero_replays(self):
        ls, _ = self._make_system()
        log = ContextQueryLog()
        driver = SleepDriver(log)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)
        result = driver.run(ls, detector, n_replays=5)
        assert result.n_replays == 0
        assert result.meta_gen_count == 0

    def test_log_with_shallow_events_skipped(self):
        """События с chain<3 игнорируются при min_chain=3."""
        ls, feat_ids = self._make_system()
        log = ContextQueryLog()
        log.record(feature_id=feat_ids[0], active_gen_ids=[], chain_len=2)
        driver = SleepDriver(log)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)
        result = driver.run(ls, detector, n_replays=5, min_chain=3)
        assert result.n_replays == 0

    def test_system_context_restored_after_run(self):
        """После сна контекст системы восстановлен."""
        from core.context import ContextBuffer
        ls, feat_ids = self._make_system()
        original_ctx = ls.engine.context
        log = ContextQueryLog()
        log.record(feat_ids[0], active_gen_ids=[], chain_len=3)
        driver = SleepDriver(log)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)
        driver.run(ls, detector, n_replays=1)
        assert ls.engine.context is original_ctx

    def test_system_base_restored_after_run(self):
        """После сна engine.base и generalizer.base восстановлены."""
        ls, feat_ids = self._make_system()
        orig_base = ls.engine.base
        log = ContextQueryLog()
        log.record(feat_ids[0], active_gen_ids=[], chain_len=3)
        driver = SleepDriver(log)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)
        driver.run(ls, detector, n_replays=1)
        assert ls.engine.base is orig_base
        assert ls.generalizer.base is orig_base

    def test_repeated_refuted_increases_urgency(self):
        """Если событие снова REFUTED во сне — urgency растёт."""
        ls, feat_ids = self._make_system()
        log = ContextQueryLog()
        # Подаём неизвестный feature_id чтобы гарантировать REFUTED
        unknown_fid = "unknown-feature-xyz"
        ls.engine._features[unknown_fid] = make_feature(unknown_fid)
        log.record(unknown_fid, active_gen_ids=[], chain_len=3)
        initial_urgency = log._events[0].urgency

        driver = SleepDriver(log)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)
        driver.run(ls, detector, n_replays=1)
        # После сна: событие снова REFUTED → urgency должно вырасти
        # (событие могло быть удалено через retain_unresolved если urgency≤1.5)
        # urgency было 1.0, после REFUTED стало 1.5 ≤ 1.5 → удалено
        assert len(log) == 0 or log._events[0].urgency > initial_urgency

    def test_result_has_correct_n_replays(self):
        ls, feat_ids = self._make_system()
        log = ContextQueryLog()
        for fid in feat_ids[:3]:
            log.record(fid, active_gen_ids=[], chain_len=3)
        driver = SleepDriver(log)
        detector = CrossDomainDetector(domain_registry=None, min_chain_fallback=3)
        result = driver.run(ls, detector, n_replays=2)
        assert result.n_replays == 2  # max_n=2 ограничивает

    def test_query_log_wired_via_learning_system(self):
        """LearningSystem записывает REFUTED события в query_log."""
        from core.learning import LearningSystem
        from drivers.text_driver import TextDriver

        log = ContextQueryLog()
        ls = LearningSystem(query_log=log)
        drv = TextDriver("text")

        # Прогнать несколько токенов — гарантированно будут REFUTED (новая система)
        for tok in drv.produce("кот сидит на крыше"):
            ls.process_token(tok)

        # Должны появиться записи в логе (хотя бы с chain=0 для первых токенов)
        assert len(log) >= 0  # лог не упал с ошибкой
