"""
Тесты TimescaleScheduler (core/timescale.py).
"""

from __future__ import annotations

import pytest
from core.timescale import Tier, TierStats, TickResult, TimescaleScheduler
from core.generalization import Generalization, GeneralizationBase


# ══════════════════════════════════════════════════════════════════════
# Вспомогательные функции
# ══════════════════════════════════════════════════════════════════════

import uuid

def _make_gen(chain_len: int, success: int = 3, stop: int = 1) -> Generalization:
    """Создать Gen с заданной длиной цепочки и значимостью success/(success+stop)."""
    chain = [str(uuid.uuid4()) for _ in range(chain_len)]
    g = Generalization.new()
    object.__setattr__(g, "feature_chain", chain)
    object.__setattr__(g, "success_count", success)
    object.__setattr__(g, "stop_count",    stop)
    return g


def _make_base(*gens: Generalization) -> GeneralizationBase:
    base = GeneralizationBase()
    for g in gens:
        base.add(g)
    return base


# ══════════════════════════════════════════════════════════════════════
# TestTierClassification
# ══════════════════════════════════════════════════════════════════════

class TestTierClassification:
    def test_chain_0_is_long_term(self):
        sched = TimescaleScheduler()
        g = _make_gen(0)
        assert sched.classify(g) == Tier.LONG_TERM

    def test_chain_1_is_long_term(self):
        sched = TimescaleScheduler()
        assert sched.classify(_make_gen(1)) == Tier.LONG_TERM

    def test_chain_2_is_long_term(self):
        sched = TimescaleScheduler()
        assert sched.classify(_make_gen(2)) == Tier.LONG_TERM

    def test_chain_3_is_medium(self):
        sched = TimescaleScheduler()
        assert sched.classify(_make_gen(3)) == Tier.MEDIUM

    def test_chain_4_is_medium(self):
        sched = TimescaleScheduler()
        assert sched.classify(_make_gen(4)) == Tier.MEDIUM

    def test_chain_5_is_operational(self):
        sched = TimescaleScheduler()
        assert sched.classify(_make_gen(5)) == Tier.OPERATIONAL

    def test_chain_10_is_operational(self):
        sched = TimescaleScheduler()
        assert sched.classify(_make_gen(10)) == Tier.OPERATIONAL

    def test_custom_boundaries(self):
        sched = TimescaleScheduler(long_term_max_chain=1, medium_max_chain=3)
        assert sched.classify(_make_gen(1)) == Tier.LONG_TERM
        assert sched.classify(_make_gen(2)) == Tier.MEDIUM
        assert sched.classify(_make_gen(3)) == Tier.MEDIUM
        assert sched.classify(_make_gen(4)) == Tier.OPERATIONAL

    def test_retention_weight_long_term(self):
        sched = TimescaleScheduler()
        assert sched.retention_weight(_make_gen(1)) == 1.0

    def test_retention_weight_medium(self):
        sched = TimescaleScheduler()
        assert sched.retention_weight(_make_gen(3)) == 0.5

    def test_retention_weight_operational(self):
        sched = TimescaleScheduler()
        assert sched.retention_weight(_make_gen(5)) == 0.0


# ══════════════════════════════════════════════════════════════════════
# TestDepthProfile
# ══════════════════════════════════════════════════════════════════════

class TestDepthProfile:
    def test_empty_base(self):
        sched = TimescaleScheduler()
        base  = GeneralizationBase()
        p = sched.depth_profile(base)
        assert p[Tier.LONG_TERM].count == 0
        assert p[Tier.MEDIUM].count    == 0
        assert p[Tier.OPERATIONAL].count == 0

    def test_counts_per_tier(self):
        sched = TimescaleScheduler()
        base  = _make_base(
            _make_gen(1), _make_gen(2),          # LONG_TERM × 2
            _make_gen(3), _make_gen(4),          # MEDIUM × 2
            _make_gen(5), _make_gen(6), _make_gen(7),  # OPERATIONAL × 3
        )
        p = sched.depth_profile(base)
        assert p[Tier.LONG_TERM].count   == 2
        assert p[Tier.MEDIUM].count      == 2
        assert p[Tier.OPERATIONAL].count == 3

    def test_avg_sig_correct(self):
        sched = TimescaleScheduler()
        # success=3, stop=1 → sig=0.75
        g1 = _make_gen(1, success=3, stop=1)
        g2 = _make_gen(2, success=1, stop=1)  # sig=0.5
        base = _make_base(g1, g2)
        p = sched.depth_profile(base)
        assert abs(p[Tier.LONG_TERM].avg_sig - 0.625) < 0.001

    def test_profile_returns_all_tiers(self):
        sched = TimescaleScheduler()
        base  = _make_base(_make_gen(1))
        p = sched.depth_profile(base)
        assert set(p.keys()) == {Tier.LONG_TERM, Tier.MEDIUM, Tier.OPERATIONAL}

    def test_tier_cache_populated(self):
        sched = TimescaleScheduler()
        g = _make_gen(3)
        base = _make_base(g)
        sched.depth_profile(base)
        assert sched.tier_of(g.gen_id) == Tier.MEDIUM


# ══════════════════════════════════════════════════════════════════════
# TestTick
# ══════════════════════════════════════════════════════════════════════

class TestTick:
    def test_tick_returns_tick_result(self):
        sched = TimescaleScheduler()
        base  = _make_base(_make_gen(1))
        r = sched.tick(base, current_step=10)
        assert isinstance(r, TickResult)

    def test_tick_step_stored(self):
        sched = TimescaleScheduler()
        base  = _make_base(_make_gen(1))
        r = sched.tick(base, current_step=42)
        assert r.step == 42

    def test_tick_total_gens(self):
        sched = TimescaleScheduler()
        base  = _make_base(_make_gen(1), _make_gen(3), _make_gen(5))
        r = sched.tick(base)
        assert r.total_gens == 3

    def test_tick_new_gens_first_is_count(self):
        sched = TimescaleScheduler()
        base  = _make_base(_make_gen(1), _make_gen(1))
        r = sched.tick(base)
        # первый tick: prev_counts все нули → total_new = count
        assert r.profile[Tier.LONG_TERM].total_new == 2

    def test_tick_new_gens_incremental(self):
        sched = TimescaleScheduler()
        g1    = _make_gen(1)
        base  = _make_base(g1)
        sched.tick(base)
        # добавляем ещё один Gen
        g2 = _make_gen(1)
        base.add(g2)
        r2 = sched.tick(base)
        assert r2.profile[Tier.LONG_TERM].total_new == 1

    def test_tick_history_grows(self):
        sched = TimescaleScheduler()
        base  = _make_base(_make_gen(1))
        sched.tick(base)
        sched.tick(base)
        assert len(sched.history) == 2

    def test_last_tick_none_before_first(self):
        sched = TimescaleScheduler()
        assert sched.last_tick() is None

    def test_last_tick_after_tick(self):
        sched = TimescaleScheduler()
        base  = _make_base(_make_gen(2))
        sched.tick(base, current_step=5)
        assert sched.last_tick().step == 5

    def test_repr_after_tick(self):
        sched = TimescaleScheduler()
        base  = _make_base(_make_gen(1), _make_gen(3), _make_gen(6))
        sched.tick(base, current_step=100)
        r = repr(sched)
        assert "LT=1" in r
        assert "M=1"  in r
        assert "OP=1" in r

    def test_repr_before_tick(self):
        sched = TimescaleScheduler()
        assert "no ticks" in repr(sched)


# ══════════════════════════════════════════════════════════════════════
# TestEvictionCandidates
# ══════════════════════════════════════════════════════════════════════

class TestEvictionCandidates:
    def test_returns_list(self):
        sched = TimescaleScheduler()
        base  = _make_base(_make_gen(5))
        cands = sched.eviction_candidates(base, n=10)
        assert isinstance(cands, list)

    def test_long_term_not_in_candidates(self):
        """LONG_TERM Gen (retention=1.0) имеют score=0 — не попадают в топ."""
        sched  = TimescaleScheduler()
        lt_gen = _make_gen(1, success=0, stop=5)  # sig=0, но retention=1.0
        op_gen = _make_gen(5, success=1, stop=3)  # sig=0.25
        base   = _make_base(lt_gen, op_gen)
        cands  = sched.eviction_candidates(base, n=2)
        gen_ids = [g.gen_id for g in cands]
        assert op_gen.gen_id in gen_ids
        assert lt_gen.gen_id not in gen_ids

    def test_low_sig_operational_first(self):
        """OPERATIONAL Gen с низкой значимостью — первый кандидат."""
        sched   = TimescaleScheduler()
        op_low  = _make_gen(5, success=0, stop=5)   # sig=0
        op_high = _make_gen(6, success=9, stop=1)   # sig=0.9
        base    = _make_base(op_low, op_high)
        cands   = sched.eviction_candidates(base, n=1)
        assert cands[0].gen_id == op_low.gen_id

    def test_n_limits_results(self):
        sched = TimescaleScheduler()
        gens  = [_make_gen(5) for _ in range(20)]
        base  = _make_base(*gens)
        cands = sched.eviction_candidates(base, n=5)
        assert len(cands) <= 5

    def test_medium_before_long_term(self):
        """При одинаковой значимости MEDIUM раньше LONG_TERM."""
        sched  = TimescaleScheduler()
        med    = _make_gen(3, success=1, stop=1)  # sig=0.5, retention=0.5
        lt     = _make_gen(1, success=1, stop=1)  # sig=0.5, retention=1.0
        base   = _make_base(med, lt)
        cands  = sched.eviction_candidates(base, n=1)
        assert cands[0].gen_id == med.gen_id

    def test_empty_base(self):
        sched = TimescaleScheduler()
        base  = GeneralizationBase()
        assert sched.eviction_candidates(base, n=10) == []

    def test_tier_sizes(self):
        sched = TimescaleScheduler()
        base  = _make_base(
            _make_gen(1), _make_gen(2),
            _make_gen(3),
            _make_gen(5), _make_gen(8),
        )
        sizes = sched.tier_sizes(base)
        assert sizes["LONG_TERM"]   == 2
        assert sizes["MEDIUM"]      == 1
        assert sizes["OPERATIONAL"] == 2


# ══════════════════════════════════════════════════════════════════════
# TestTickResultHelpers
# ══════════════════════════════════════════════════════════════════════

class TestTickResultHelpers:
    def _result(self) -> TickResult:
        sched = TimescaleScheduler()
        base  = _make_base(
            _make_gen(1), _make_gen(2),
            _make_gen(3),
            _make_gen(5),
        )
        return sched.tick(base, current_step=50)

    def test_long_term_count(self):
        assert self._result().long_term_count == 2

    def test_medium_count(self):
        assert self._result().medium_count == 1

    def test_operational_count(self):
        assert self._result().operational_count == 1

    def test_summary_contains_tier_names(self):
        r = self._result()
        s = r.summary()
        assert "LONG_TERM"   in s
        assert "MEDIUM"      in s
        assert "OPERATIONAL" in s
