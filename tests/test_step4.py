"""
Тесты Шага 4: Ресурсный драйвер и система обучения.

Покрывают:
  - ResourceState: mode, modulate_tolerance, modulate_context_size,
                   resolution_hint, is_depleted, is_abundant
  - ResourceDriver: set_level, add_reward, consume, recover, step,
                    history, state
  - RewardOrder: matches, is_exhausted, max_fires
  - TeacherDriver: add_order, remove_order, clear_orders,
                   check_and_fire (срабатывание / несрабатывание),
                   max_fires соблюдается
  - TeachingLog: log_state, get_recent, push/pop orders, push/pop content
  - Интеграция с LearningSystem: наличие полей, модуляция tolerance,
                                  ресурс меняется при шагах,
                                  ордер срабатывает в реальном цикле
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from core.generalization import Generalization, GeneralizationBase, PeripheralToken
from core.context import ContextBuffer
from core.algorithm import StepResult, StepOutcome
from core.resource import ResourceState, ResourceDriver
from core.teacher import RewardOrder, TeacherDriver, TeachingLog
from core.attractor import Resolution


# ── вспомогательные функции ────────────────────────────────────────────────

def _make_gen(chain, success=0, stop=0):
    g = Generalization.new(feature_chain=chain)
    g.success_count = success
    g.stop_count = stop
    return g


def _step_result(outcome, feat_id=None):
    token = PeripheralToken.new("test", None)
    return StepResult(outcome=outcome, token=token, matched_feature_id=feat_id)


# ══════════════════════════════════════════════════════════════════════
# ResourceState
# ══════════════════════════════════════════════════════════════════════

class TestResourceState:
    def test_mode_rest(self):
        assert ResourceState(level=0.0).mode == "rest"
        assert ResourceState(level=0.19).mode == "rest"

    def test_mode_conserve(self):
        assert ResourceState(level=0.2).mode == "conserve"
        assert ResourceState(level=0.39).mode == "conserve"

    def test_mode_normal(self):
        assert ResourceState(level=0.4).mode == "normal"
        assert ResourceState(level=0.5).mode == "normal"
        assert ResourceState(level=0.69).mode == "normal"

    def test_mode_explore(self):
        assert ResourceState(level=0.7).mode == "explore"
        assert ResourceState(level=0.89).mode == "explore"

    def test_mode_abundant(self):
        assert ResourceState(level=0.9).mode == "abundant"
        assert ResourceState(level=1.0).mode == "abundant"

    def test_is_depleted(self):
        assert ResourceState(level=0.1).is_depleted()
        assert not ResourceState(level=0.5).is_depleted()

    def test_is_abundant(self):
        assert ResourceState(level=0.95).is_abundant()
        assert not ResourceState(level=0.5).is_abundant()

    def test_modulate_tolerance_increases_with_level(self):
        base = 0.3
        low  = ResourceState(level=0.1).modulate_tolerance(base)
        mid  = ResourceState(level=0.5).modulate_tolerance(base)
        high = ResourceState(level=0.9).modulate_tolerance(base)
        assert low < mid < high

    def test_modulate_tolerance_normal_equals_base(self):
        base = 0.3
        # level=0.5 → factor=1.0 → result=base*1.0
        result = ResourceState(level=0.5).modulate_tolerance(base)
        assert result == pytest.approx(base * 1.0)

    def test_modulate_context_size_increases_with_level(self):
        low  = ResourceState(level=0.1).modulate_context_size(4)
        high = ResourceState(level=0.9).modulate_context_size(4)
        assert low < high

    def test_modulate_context_size_min_one(self):
        assert ResourceState(level=0.0).modulate_context_size(1) >= 1

    def test_resolution_hint_rest(self):
        assert ResourceState(level=0.1).resolution_hint() == Resolution.COARSE

    def test_resolution_hint_normal(self):
        assert ResourceState(level=0.5).resolution_hint() == Resolution.MEDIUM

    def test_resolution_hint_explore(self):
        assert ResourceState(level=0.75).resolution_hint() == Resolution.FINE

    def test_resolution_hint_abundant(self):
        assert ResourceState(level=0.95).resolution_hint() == Resolution.EXACT


# ══════════════════════════════════════════════════════════════════════
# ResourceDriver
# ══════════════════════════════════════════════════════════════════════

class TestResourceDriver:
    def test_initial_level(self):
        d = ResourceDriver(initial_level=0.7)
        assert d.level == pytest.approx(0.7)

    def test_set_level_clamps(self):
        d = ResourceDriver()
        d.set_level(1.5)
        assert d.level == pytest.approx(1.0)
        d.set_level(-0.3)
        assert d.level == pytest.approx(0.0)

    def test_consume_reduces(self):
        d = ResourceDriver(initial_level=0.5)
        d.consume(0.1)
        assert d.level == pytest.approx(0.4)

    def test_recover_increases(self):
        d = ResourceDriver(initial_level=0.3)
        d.recover(0.2)
        assert d.level == pytest.approx(0.5)

    def test_add_reward_increases(self):
        d = ResourceDriver(initial_level=0.5, reward_scale=0.1)
        d.add_reward(10.0)
        assert d.level > 0.5

    def test_history_tracks(self):
        d = ResourceDriver(initial_level=0.5)
        d.set_level(0.6)
        d.set_level(0.7)
        assert len(d.history) >= 3   # initial + 2 updates

    def test_state_trend_positive(self):
        d = ResourceDriver(initial_level=0.3)
        d.set_level(0.5)
        assert d.state.trend > 0

    def test_state_trend_negative(self):
        d = ResourceDriver(initial_level=0.7)
        d.set_level(0.5)
        assert d.state.trend < 0

    def test_step_completed_recovers(self):
        d = ResourceDriver(initial_level=0.5)
        before = d.level
        d.step(_step_result(StepOutcome.COMPLETED))
        assert d.level > before

    def test_step_refuted_consumes(self):
        d = ResourceDriver(initial_level=0.5)
        before = d.level
        d.step(_step_result(StepOutcome.REFUTED))
        assert d.level < before

    def test_step_exploring_light_consume(self):
        d = ResourceDriver(initial_level=0.5)
        before = d.level
        d.step(_step_result(StepOutcome.EXPLORING))
        assert d.level < before

    def test_step_confirmed_slight_consume(self):
        d = ResourceDriver(initial_level=0.5)
        before = d.level
        d.step(_step_result(StepOutcome.CONFIRMED))
        assert d.level < before

    def test_mode_changes_with_level(self):
        d = ResourceDriver(initial_level=0.1)
        assert d.state.mode == "rest"
        d.set_level(0.5)
        assert d.state.mode == "normal"
        d.set_level(0.95)
        assert d.state.mode == "abundant"


# ══════════════════════════════════════════════════════════════════════
# RewardOrder
# ══════════════════════════════════════════════════════════════════════

class TestRewardOrder:
    def test_matches_when_subset(self):
        order = RewardOrder(required_gen_ids={"g1", "g2"}, reward=10.0)
        assert order.matches({"g1", "g2", "g3"})

    def test_no_match_partial(self):
        order = RewardOrder(required_gen_ids={"g1", "g2"}, reward=10.0)
        assert not order.matches({"g1"})

    def test_no_match_empty_active(self):
        order = RewardOrder(required_gen_ids={"g1"}, reward=10.0)
        assert not order.matches(set())

    def test_exhausted_after_max_fires(self):
        order = RewardOrder(required_gen_ids={"g1"}, reward=10.0, max_fires=2)
        assert not order.is_exhausted()
        order.fired_count = 2
        assert order.is_exhausted()

    def test_no_limit_never_exhausted(self):
        order = RewardOrder(required_gen_ids={"g1"}, reward=10.0, max_fires=-1)
        order.fired_count = 9999
        assert not order.is_exhausted()

    def test_exhausted_does_not_match(self):
        order = RewardOrder(required_gen_ids={"g1"}, reward=10.0, max_fires=1)
        order.fired_count = 1
        assert not order.matches({"g1"})


# ══════════════════════════════════════════════════════════════════════
# TeacherDriver
# ══════════════════════════════════════════════════════════════════════

class TestTeacherDriver:
    def _make_ctx_base_with_gen(self, gen_id=None):
        base = GeneralizationBase()
        g = _make_gen(["f1"], success=2, stop=1)
        base.add(g)
        ctx = ContextBuffer()
        ctx.add_active(g.gen_id)
        return ctx, base, g

    def test_add_order(self):
        res = ResourceDriver()
        t = TeacherDriver(res)
        order = t.add_order({"g1"}, reward=50.0, label="test")
        assert len(t._orders) == 1
        assert order.label == "test"

    def test_remove_order(self):
        res = ResourceDriver()
        t = TeacherDriver(res)
        order = t.add_order({"g1"}, reward=50.0)
        t.remove_order(order)
        assert len(t._orders) == 0

    def test_clear_orders(self):
        res = ResourceDriver()
        t = TeacherDriver(res)
        t.add_order({"g1"}, reward=10.0)
        t.add_order({"g2"}, reward=20.0)
        t.clear_orders()
        assert len(t._orders) == 0

    def test_check_and_fire_triggers(self):
        ctx, base, g = self._make_ctx_base_with_gen()
        res = ResourceDriver(initial_level=0.5)
        t = TeacherDriver(res)
        t.add_order({g.gen_id}, reward=50.0)
        before = res.level
        fired = t.check_and_fire(ctx, base)
        assert fired > 0
        assert res.level > before

    def test_check_and_fire_no_trigger_when_mismatch(self):
        ctx, base, g = self._make_ctx_base_with_gen()
        res = ResourceDriver(initial_level=0.5)
        t = TeacherDriver(res)
        t.add_order({"nonexistent_gen_id"}, reward=100.0)
        before = res.level
        fired = t.check_and_fire(ctx, base)
        assert fired == 0.0
        assert res.level == pytest.approx(before)

    def test_check_and_fire_strengthens_gen(self):
        ctx, base, g = self._make_ctx_base_with_gen()
        res = ResourceDriver()
        t = TeacherDriver(res)
        success_before = g.success_count
        t.add_order({g.gen_id}, reward=100.0)
        t.check_and_fire(ctx, base)
        assert g.success_count > success_before

    def test_max_fires_respected(self):
        ctx, base, g = self._make_ctx_base_with_gen()
        res = ResourceDriver(initial_level=0.5)
        t = TeacherDriver(res)
        t.add_order({g.gen_id}, reward=10.0, max_fires=2)
        t.check_and_fire(ctx, base)  # fire 1
        t.check_and_fire(ctx, base)  # fire 2
        level_after_2 = res.level
        t.check_and_fire(ctx, base)  # должен НЕ сработать
        assert res.level == pytest.approx(level_after_2)

    def test_order_fired_count_increments(self):
        ctx, base, g = self._make_ctx_base_with_gen()
        res = ResourceDriver()
        t = TeacherDriver(res)
        order = t.add_order({g.gen_id}, reward=10.0)
        t.check_and_fire(ctx, base)
        t.check_and_fire(ctx, base)
        assert order.fired_count == 2

    def test_clear_exhausted(self):
        res = ResourceDriver()
        t = TeacherDriver(res)
        order = t.add_order({"g1"}, reward=10.0, max_fires=1)
        order.fired_count = 1
        removed = t.clear_exhausted()
        assert removed == 1
        assert len(t._orders) == 0

    def test_active_order_count(self):
        res = ResourceDriver()
        t = TeacherDriver(res)
        order = t.add_order({"g1"}, reward=10.0, max_fires=1)
        assert t.active_order_count == 1
        order.fired_count = 1
        assert t.active_order_count == 0

    def test_total_fired_reward(self):
        ctx, base, g = self._make_ctx_base_with_gen()
        res = ResourceDriver()
        t = TeacherDriver(res)
        t.add_order({g.gen_id}, reward=50.0)
        t.check_and_fire(ctx, base)
        t.check_and_fire(ctx, base)
        assert t.total_fired_reward == pytest.approx(100.0)

    def test_fired_log_entries(self):
        ctx, base, g = self._make_ctx_base_with_gen()
        res = ResourceDriver()
        t = TeacherDriver(res)
        t.add_order({g.gen_id}, reward=30.0, label="test_label")
        t.check_and_fire(ctx, base)
        log = t.fired_log()
        assert len(log) == 1
        assert log[0]["label"] == "test_label"
        assert log[0]["reward"] == 30.0

    def test_multiple_orders_one_step(self):
        ctx, base, g = self._make_ctx_base_with_gen()
        res = ResourceDriver(initial_level=0.5)
        t = TeacherDriver(res)
        t.add_order({g.gen_id}, reward=10.0, label="order1")
        t.add_order({g.gen_id}, reward=20.0, label="order2")
        fired = t.check_and_fire(ctx, base)
        assert fired == pytest.approx(30.0)


# ══════════════════════════════════════════════════════════════════════
# TeachingLog
# ══════════════════════════════════════════════════════════════════════

class TestTeachingLog:
    def test_log_state_appends(self):
        log = TeachingLog()
        result = _step_result(StepOutcome.CONFIRMED, "f1")
        rs = ResourceState(level=0.5)
        log.log_state(result, rs, ["g1", "g2"])
        assert log.size() == 1

    def test_get_recent(self):
        log = TeachingLog()
        rs = ResourceState(level=0.5)
        for i in range(5):
            log.log_state(_step_result(StepOutcome.CONFIRMED), rs, [f"g{i}"])
        recent = log.get_recent(3)
        assert len(recent) == 3
        # последние 3 записи
        assert recent[-1]["active_gens"] == ["g4"]

    def test_log_entry_fields(self):
        log = TeachingLog()
        result = _step_result(StepOutcome.COMPLETED, "f_abc")
        rs = ResourceState(level=0.7)
        log.log_state(result, rs, ["g1"])
        entry = log.get_recent(1)[0]
        assert entry["outcome"] == "COMPLETED"
        assert entry["matched_feat"] == "f_abc"
        assert entry["resource_level"] == pytest.approx(0.7)
        assert entry["resource_mode"] == "explore"

    def test_push_pop_reward_order(self):
        log = TeachingLog()
        order = RewardOrder(required_gen_ids={"g1"}, reward=50.0, label="llm_order")
        log.push_reward_order(order)
        orders = log.pop_pending_orders()
        assert len(orders) == 1
        assert orders[0].label == "llm_order"
        # После pop — пусто
        assert log.pop_pending_orders() == []

    def test_push_pop_content(self):
        log = TeachingLog()
        log.push_content("учебный текст 1")
        log.push_content("учебный текст 2")
        assert log.pending_content_count() == 2
        c1 = log.pop_content()
        c2 = log.pop_content()
        assert c1 == "учебный текст 1"
        assert c2 == "учебный текст 2"
        assert log.pop_content() is None

    def test_max_entries_truncates(self):
        log = TeachingLog(max_entries=5)
        rs = ResourceState(level=0.5)
        for i in range(10):
            log.log_state(_step_result(StepOutcome.CONFIRMED), rs, [])
        assert log.size() == 5

    def test_multiple_orders_in_queue(self):
        log = TeachingLog()
        for i in range(3):
            log.push_reward_order(RewardOrder({"g1"}, reward=float(i * 10)))
        orders = log.pop_pending_orders()
        assert len(orders) == 3
        assert [o.reward for o in orders] == [0.0, 10.0, 20.0]


# ══════════════════════════════════════════════════════════════════════
# Интеграция с LearningSystem (Шаг 4)
# ══════════════════════════════════════════════════════════════════════

class TestLearningSystemStep4:
    def test_has_resource(self):
        from core.learning import LearningSystem
        ls = LearningSystem()
        assert hasattr(ls, "resource")
        assert isinstance(ls.resource, ResourceDriver)

    def test_has_teacher(self):
        from core.learning import LearningSystem
        ls = LearningSystem()
        assert hasattr(ls, "teacher")
        assert isinstance(ls.teacher, TeacherDriver)

    def test_has_teaching_log(self):
        from core.learning import LearningSystem
        ls = LearningSystem()
        assert hasattr(ls, "teaching_log")
        assert isinstance(ls.teaching_log, TeachingLog)

    def test_stats_include_resource(self):
        from core.learning import LearningSystem
        ls = LearningSystem()
        s = ls.stats()
        assert "resource" in s
        assert "level" in s["resource"]
        assert "mode" in s["resource"]

    def test_stats_include_teacher(self):
        from core.learning import LearningSystem
        ls = LearningSystem()
        s = ls.stats()
        assert "teacher" in s
        assert "active_orders" in s["teacher"]

    def test_resource_updates_during_processing(self):
        from core.learning import LearningSystem
        from core.feature import Feature, RegionCharacteristics
        ls = LearningSystem(feature_tolerance=0.5, initial_resource=0.5)
        initial_level = ls.resource.level
        src = RegionCharacteristics(brightness=0.3)
        tgt = RegionCharacteristics(brightness=0.7)
        f = Feature.from_regions("f1", 0.0, 1.0, src, tgt)
        token = PeripheralToken.new("drv", f)
        # Обрабатываем несколько токенов
        for _ in range(5):
            ls.process_token(PeripheralToken.new("drv", f))
        # Ресурс должен был измениться
        assert ls.resource.level != initial_level

    def test_tolerance_modulated_by_resource(self):
        from core.learning import LearningSystem
        ls = LearningSystem(feature_tolerance=0.3, initial_resource=0.5)
        base_tol = ls._base_tolerance
        # При низком ресурсе tolerance должен быть меньше base
        ls.resource.set_level(0.0)
        from core.generalization import PeripheralToken
        # Обрабатываем пустой токен чтобы спровоцировать модуляцию
        token = PeripheralToken.new("drv", None)
        ls.process_token(token)
        assert ls.engine.feature_tolerance < base_tol

    def test_reward_order_fires_in_real_cycle(self):
        """Ордер срабатывает, когда нужный Gen активен в контексте."""
        from core.learning import LearningSystem
        from core.feature import Feature, RegionCharacteristics
        ls = LearningSystem(feature_tolerance=0.5)

        # Обучим одному токену — создастся Gen
        src = RegionCharacteristics(brightness=0.2)
        tgt = RegionCharacteristics(brightness=0.8)
        f = Feature.from_regions("f_teach", 0.0, 1.0, src, tgt)
        token = PeripheralToken.new("drv", f)
        result = ls.process_token(token)

        # Получить id активных Gen после шага
        active_ids = ls.engine.context.active_gen_ids()
        if not active_ids:
            return  # ничего активного — тест не применим

        # Поставить ордер на один из активных Gen
        target_gen_id = active_ids[0]
        initial_resource = ls.resource.level
        ls.teacher.add_order({target_gen_id}, reward=100.0, label="integration_test")

        # Следующий шаг с тем же токеном — ордер должен сработать
        ls.reset_context()
        ls.engine.context.add_active(target_gen_id)   # вручную активировать
        ls.teacher.check_and_fire(ls.engine.context, ls.base)

        assert ls.resource.level > initial_resource

    def test_teaching_log_receives_external_order(self):
        """Ордер от LLM-учителя через TeachingLog попадает в TeacherDriver."""
        from core.learning import LearningSystem
        from core.generalization import PeripheralToken
        ls = LearningSystem()
        # LLM-учитель ставит ордер
        order = RewardOrder(required_gen_ids={"g_ext"}, reward=30.0, label="llm")
        ls.teaching_log.push_reward_order(order)
        # Обрабатываем токен — pending ордера должны быть применены
        token = PeripheralToken.new("drv", None)
        ls.process_token(token)
        # Ордер должен оказаться в TeacherDriver
        all_labels = [o.label for o in ls.teacher._orders]
        assert "llm" in all_labels

    def test_reset_context_recovers_resource(self):
        """reset_context восстанавливает ресурс (пауза = отдых)."""
        from core.learning import LearningSystem
        ls = LearningSystem(initial_resource=0.3)
        ls.resource.set_level(0.3)
        ls.reset_context()
        assert ls.resource.level > 0.3

    def test_initial_resource_parameter(self):
        from core.learning import LearningSystem
        ls = LearningSystem(initial_resource=0.8)
        assert ls.resource.level == pytest.approx(0.8)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
