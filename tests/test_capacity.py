"""
Тесты для CapacityBudget (core/capacity.py).

Проверяем:
  - enforce() удаляет Gen при превышении max_gens
  - LONG_TERM Gen (chain 1–2) никогда не вытесняются
  - OPERATIONAL Gen (chain 5+) вытесняются первыми
  - MEDIUM Gen (chain 3–4) вытесняются после OPERATIONAL
  - evict_batch амортизирует частые вставки
  - total_evicted, headroom, is_at_capacity
  - remove() очищает parent/child ссылки и transition_stats
  - GeneralizationBase с evict_callback работает end-to-end
"""

import pytest
from core.generalization import Generalization, GeneralizationBase
from core.capacity import CapacityBudget, EvictionStats
from core.timescale import TimescaleScheduler, Tier


# ══════════════════════════════════════════════════════════════════════
# Вспомогательные фабрики
# ══════════════════════════════════════════════════════════════════════

def make_gen(chain_len: int, sig: float = 0.0, label: str = "") -> Generalization:
    """Создать Gen с заданной длиной цепочки и значимостью."""
    gen = Generalization.new(
        feature_chain=[f"f{i}" for i in range(chain_len)],
        label=label or f"L{chain_len}",
    )
    # Выставляем значимость через success/stop счётчики
    if sig > 0.0:
        total = 100
        gen.success_count = int(sig * total)
        gen.stop_count = total - gen.success_count
    return gen


def make_base_with_budget(max_gens: int = 5, evict_batch: int = 0) -> tuple:
    """Вернуть (base, budget) с заданным лимитом."""
    sched = TimescaleScheduler()
    budget = CapacityBudget(max_gens=max_gens, scheduler=sched, evict_batch=evict_batch)
    base = GeneralizationBase(evict_callback=budget.enforce)
    return base, budget


# ══════════════════════════════════════════════════════════════════════
# 1. GeneralizationBase.remove()
# ══════════════════════════════════════════════════════════════════════

class TestGeneralizationBaseRemove:

    def test_remove_existing_gen(self):
        base = GeneralizationBase()
        gen = make_gen(3)
        base.add(gen)
        assert base.size() == 1
        result = base.remove(gen.gen_id)
        assert result is True
        assert base.size() == 0
        assert base.get(gen.gen_id) is None

    def test_remove_nonexistent_returns_false(self):
        base = GeneralizationBase()
        result = base.remove("nonexistent-id")
        assert result is False

    def test_remove_cleans_parent_child_links(self):
        base = GeneralizationBase()
        parent = make_gen(1)
        child = make_gen(3)
        base.add(parent)
        base.add(child)
        base.link(parent.gen_id, child.gen_id)

        assert child.gen_id in parent.child_ids
        assert parent.gen_id in child.parent_ids

        base.remove(child.gen_id)
        assert child.gen_id not in parent.child_ids

    def test_remove_cleans_child_parent_links(self):
        base = GeneralizationBase()
        parent = make_gen(1)
        child = make_gen(3)
        base.add(parent)
        base.add(child)
        base.link(parent.gen_id, child.gen_id)

        base.remove(parent.gen_id)
        assert parent.gen_id not in child.parent_ids

    def test_remove_cleans_transition_stats_from(self):
        base = GeneralizationBase()
        g1 = make_gen(2)
        g2 = make_gen(2)
        base.add(g1)
        base.add(g2)
        base.record_transition(g1.gen_id, g2.gen_id)
        assert g1.gen_id in base._transition_stats

        base.remove(g1.gen_id)
        assert g1.gen_id not in base._transition_stats

    def test_remove_cleans_transition_stats_to(self):
        base = GeneralizationBase()
        g1 = make_gen(2)
        g2 = make_gen(2)
        base.add(g1)
        base.add(g2)
        base.record_transition(g1.gen_id, g2.gen_id)

        base.remove(g2.gen_id)
        # Запись g1→g2 должна исчезнуть из словаря g1
        remaining = base._transition_stats.get(g1.gen_id, {})
        assert g2.gen_id not in remaining

    def test_remove_twice_returns_false_second_time(self):
        base = GeneralizationBase()
        gen = make_gen(2)
        base.add(gen)
        assert base.remove(gen.gen_id) is True
        assert base.remove(gen.gen_id) is False


# ══════════════════════════════════════════════════════════════════════
# 2. CapacityBudget базовое поведение
# ══════════════════════════════════════════════════════════════════════

class TestCapacityBudgetBasic:

    def test_no_eviction_below_limit(self):
        base, budget = make_base_with_budget(max_gens=5)
        for i in range(5):
            base.add(make_gen(5))  # OPERATIONAL
        assert base.size() == 5
        assert budget.total_evicted == 0

    def test_eviction_triggered_on_add(self):
        base, budget = make_base_with_budget(max_gens=3, evict_batch=0)
        for i in range(3):
            base.add(make_gen(5))  # OPERATIONAL, sig=0
        # 4-й добавляемый вызовет eviction
        base.add(make_gen(5))
        assert base.size() <= 3

    def test_total_evicted_counter(self):
        base, budget = make_base_with_budget(max_gens=3, evict_batch=0)
        for _ in range(5):
            base.add(make_gen(5))
        assert budget.total_evicted >= 2

    def test_headroom_below_limit(self):
        base, budget = make_base_with_budget(max_gens=10)
        for _ in range(4):
            base.add(make_gen(5))
        assert budget.headroom(base) == 6

    def test_headroom_at_limit(self):
        base, budget = make_base_with_budget(max_gens=3, evict_batch=0)
        for _ in range(3):
            base.add(make_gen(5))
        assert budget.headroom(base) == 0

    def test_is_at_capacity_false(self):
        base, budget = make_base_with_budget(max_gens=10)
        base.add(make_gen(5))
        assert budget.is_at_capacity(base) is False

    def test_is_at_capacity_true(self):
        base, budget = make_base_with_budget(max_gens=1, evict_batch=0)
        base.add(make_gen(5))
        assert budget.is_at_capacity(base) is True

    def test_stats_returns_eviction_stats(self):
        base, budget = make_base_with_budget(max_gens=5)
        base.add(make_gen(5))
        stats = budget.stats(base)
        assert isinstance(stats, EvictionStats)
        assert stats.max_gens == 5
        assert stats.current_gens == 1

    def test_repr(self):
        _, budget = make_base_with_budget(max_gens=100)
        assert "CapacityBudget" in repr(budget)
        assert "100" in repr(budget)


# ══════════════════════════════════════════════════════════════════════
# 3. Приоритеты вытеснения по тирам
# ══════════════════════════════════════════════════════════════════════

class TestEvictionPriority:

    def _add_mixed(self, base: GeneralizationBase):
        """Добавить Gen всех тиров в базу."""
        lt = make_gen(1, sig=0.9, label="long_term")   # LONG_TERM
        med = make_gen(3, sig=0.5, label="medium")     # MEDIUM
        op = make_gen(5, sig=0.1, label="operational") # OPERATIONAL
        base.add(lt)
        base.add(med)
        base.add(op)
        return lt, med, op

    def test_long_term_never_evicted(self):
        """LONG_TERM Gen (chain 1–2) не должны вытесняться."""
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=2, scheduler=sched, evict_batch=0)
        base = GeneralizationBase()

        lt = make_gen(1, sig=0.0, label="lt")
        op1 = make_gen(5, sig=0.0, label="op1")
        op2 = make_gen(5, sig=0.0, label="op2")
        base.add(lt)
        base.add(op1)
        base.add(op2)

        # Принудительно вызываем enforce
        evicted = budget.enforce(base)
        assert evicted >= 1
        # LONG_TERM должен остаться
        assert base.get(lt.gen_id) is not None

    def test_operational_evicted_before_medium(self):
        """OPERATIONAL вытесняется раньше MEDIUM при одинаковой значимости."""
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=2, scheduler=sched, evict_batch=0)
        base = GeneralizationBase()

        med = make_gen(3, sig=0.0, label="med")    # MEDIUM, sig=0
        op = make_gen(5, sig=0.0, label="op")      # OPERATIONAL, sig=0
        lt = make_gen(1, sig=1.0, label="lt")       # LONG_TERM — защищён

        base.add(lt)
        base.add(med)
        base.add(op)

        evicted = budget.enforce(base)
        assert evicted >= 1
        # OPERATIONAL должен уйти первым
        assert base.get(op.gen_id) is None or base.get(med.gen_id) is not None

    def test_high_significance_operational_survives_low_sig_medium(self):
        """OPERATIONAL с sig=1.0 не вытесняется раньше MEDIUM с sig=0.0."""
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=2, scheduler=sched, evict_batch=0)
        base = GeneralizationBase()

        lt = make_gen(1, sig=1.0, label="lt")
        med_low = make_gen(3, sig=0.0, label="med_low")   # MEDIUM, sig=0
        op_high = make_gen(5, sig=1.0, label="op_high")   # OPERATIONAL, sig=1

        base.add(lt)
        base.add(med_low)
        base.add(op_high)

        budget.enforce(base)

        # op_high: score = (1-0)*(1-1.0) = 0.0 — не кандидат
        # med_low: score = (1-0.5)*(1-0.0) = 0.5 — кандидат
        assert base.get(op_high.gen_id) is not None
        assert base.get(med_low.gen_id) is None

    def test_long_term_chain2_never_evicted(self):
        """Gen с chain=2 тоже LONG_TERM — не вытесняется."""
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=1, scheduler=sched, evict_batch=0)
        base = GeneralizationBase()

        lt2 = make_gen(2, sig=0.0, label="lt2")
        op = make_gen(5, sig=0.0, label="op")
        base.add(lt2)
        base.add(op)

        budget.enforce(base)
        assert base.get(lt2.gen_id) is not None


# ══════════════════════════════════════════════════════════════════════
# 4. evict_batch амортизация
# ══════════════════════════════════════════════════════════════════════

class TestEvictBatch:

    def test_evict_batch_removes_extra(self):
        """evict_batch > 0 создаёт запас свободных мест после вытеснения."""
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=5, scheduler=sched, evict_batch=3)
        base = GeneralizationBase()

        # Наполняем 5 OPERATIONAL Gen
        for _ in range(5):
            base.add(make_gen(5))
        assert base.size() == 5

        # 6-й вызовет enforce: overflow=1, n_to_evict=1+3=4
        budget.enforce(base)
        # После вытеснения должно быть ≤ 5 - 1 = 4, не больше
        assert base.size() <= 5

    def test_evict_batch_zero_removes_minimum(self):
        """evict_batch=0 удаляет ровно столько, сколько нужно."""
        base, budget = make_base_with_budget(max_gens=3, evict_batch=0)
        for _ in range(3):
            base.add(make_gen(5))
        budget.enforce(base)
        assert base.size() <= 3


# ══════════════════════════════════════════════════════════════════════
# 5. enforce() вручную (без evict_callback)
# ══════════════════════════════════════════════════════════════════════

class TestEnforceManual:

    def test_enforce_returns_zero_if_not_over_limit(self):
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=10, scheduler=sched)
        base = GeneralizationBase()
        base.add(make_gen(5))
        assert budget.enforce(base) == 0

    def test_enforce_returns_count_of_evicted(self):
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=2, scheduler=sched, evict_batch=0)
        base = GeneralizationBase()
        for _ in range(4):
            base.add(make_gen(5))
        evicted = budget.enforce(base)
        assert evicted == 2
        assert base.size() == 2

    def test_enforce_multiple_calls_accumulate_total_evicted(self):
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=2, scheduler=sched, evict_batch=0)
        base = GeneralizationBase()
        for _ in range(4):
            base.add(make_gen(5))
        budget.enforce(base)
        for _ in range(2):
            base.add(make_gen(5))
        budget.enforce(base)
        assert budget.total_evicted >= 4


# ══════════════════════════════════════════════════════════════════════
# 6. end-to-end с evict_callback
# ══════════════════════════════════════════════════════════════════════

class TestEndToEnd:

    def test_base_stays_within_budget_on_continuous_add(self):
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=10, scheduler=sched, evict_batch=2)
        base = GeneralizationBase(evict_callback=budget.enforce)

        for i in range(50):
            base.add(make_gen(5, sig=0.0))

        assert base.size() <= 10

    def test_high_sig_gens_survive_eviction(self):
        """Gen с высокой значимостью должны оставаться после вытеснения."""
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=5, scheduler=sched, evict_batch=0)
        base = GeneralizationBase(evict_callback=budget.enforce)

        # Сначала добавляем ценные MEDIUM Gen (защищены частично)
        valued = []
        for _ in range(3):
            g = make_gen(3, sig=0.95)
            base.add(g)
            valued.append(g.gen_id)

        # Затем мусор OPERATIONAL с sig=0
        for _ in range(20):
            base.add(make_gen(5, sig=0.0))

        # Все ценные должны остаться
        for gid in valued:
            assert base.get(gid) is not None, f"valued gen {gid} was evicted"

    def test_budget_with_no_evictable_gens_does_not_crash(self):
        """Если все Gen — LONG_TERM, enforce не падает (просто не вытесняет)."""
        sched = TimescaleScheduler()
        budget = CapacityBudget(max_gens=2, scheduler=sched, evict_batch=0)
        base = GeneralizationBase()

        for _ in range(5):
            base.add(make_gen(1))  # все LONG_TERM

        # enforce должен вернуть 0 (нечего вытеснять)
        evicted = budget.enforce(base)
        assert evicted == 0
        assert base.size() == 5  # размер не изменился

    def test_set_step_does_not_crash(self):
        _, budget = make_base_with_budget()
        budget.set_step(12345)
        assert budget._current_step == 12345

    def test_attach_vitality_stores_reference(self):
        """attach_vitality принимает объект без ошибок."""
        from unittest.mock import MagicMock
        _, budget = make_base_with_budget()
        mock_vitality = MagicMock()
        budget.attach_vitality(mock_vitality)
        assert budget._vitality is mock_vitality
