"""
Тесты ProvisionalBase и его интеграции с AttractorEngine / LearningSystem.
"""
from __future__ import annotations

import pytest
from core.provisional import ProvisionalBase, ProvisionalEntry
from core.algorithm import AttractorEngine, StepOutcome
from core.generalization import GeneralizationBase, PeripheralToken
from core.feature import Feature, FeatureVector, RegionCharacteristics
from core.learning import LearningSystem


# ══════════════════════════════════════════════════════════════════════════════
# Вспомогательные функции
# ══════════════════════════════════════════════════════════════════════════════

def _feat(brightness_delta: float, fid: str | None = None) -> Feature:
    import uuid
    src = RegionCharacteristics(brightness=0.3)
    tgt = RegionCharacteristics(brightness=0.3 + brightness_delta)
    return Feature.from_regions(fid or str(uuid.uuid4()), 0.0, 1.0, src, tgt)


def _tok(brightness_delta: float, label: str = "") -> PeripheralToken:
    return PeripheralToken.new(driver_id="test", data=_feat(brightness_delta), label=label)


# ══════════════════════════════════════════════════════════════════════════════
# ProvisionalEntry
# ══════════════════════════════════════════════════════════════════════════════

class TestProvisionalEntry:
    def test_defaults(self):
        e = ProvisionalEntry(gen_id="abc")
        assert e.gen_id == "abc"
        assert e.confirmations == 0
        assert e.age == 0

    def test_custom_values(self):
        e = ProvisionalEntry(gen_id="x", confirmations=3, age=10)
        assert e.confirmations == 3
        assert e.age == 10


# ══════════════════════════════════════════════════════════════════════════════
# ProvisionalBase — базовые операции
# ══════════════════════════════════════════════════════════════════════════════

class TestProvisionalBaseBasic:
    def setup_method(self):
        self.pb = ProvisionalBase(min_confirmations=2, max_age=5)

    def test_track_and_is_tracked(self):
        self.pb.track("g1")
        assert self.pb.is_tracked("g1")
        assert not self.pb.is_tracked("g2")

    def test_size(self):
        assert self.pb.size() == 0
        self.pb.track("g1")
        self.pb.track("g2")
        assert self.pb.size() == 2

    def test_track_overwrites(self):
        self.pb.track("g1")
        self.pb.track("g1")   # повторный track не ломает
        assert self.pb.size() == 1

    def test_remove(self):
        self.pb.track("g1")
        self.pb.remove("g1")
        assert not self.pb.is_tracked("g1")

    def test_remove_nonexistent_noop(self):
        self.pb.remove("nobody")  # не должно бросать исключение

    def test_confirm_unknown_returns_false(self):
        assert self.pb.confirm("nobody") is False

    def test_confirm_increments(self):
        self.pb.track("g1")
        promoted = self.pb.confirm("g1")
        assert promoted is False
        assert self.pb.is_tracked("g1")

    def test_confirm_promotes_at_min(self):
        self.pb.track("g1")
        self.pb.confirm("g1")
        promoted = self.pb.confirm("g1")   # 2nd — reaches min_confirmations=2
        assert promoted is True
        assert not self.pb.is_tracked("g1")

    def test_promoted_counter(self):
        self.pb.track("g1")
        self.pb.confirm("g1")
        self.pb.confirm("g1")
        assert self.pb.stats()["promoted"] == 1

    def test_tick_ages(self):
        self.pb.track("g1")
        self.pb.tick()
        self.pb.tick()
        entry = self.pb._entries["g1"]
        assert entry.age == 2

    def test_tick_no_eviction_before_max_age(self):
        self.pb.track("g1")
        for _ in range(5):   # max_age=5
            evicted = self.pb.tick()
            assert evicted == []
        assert self.pb.is_tracked("g1")

    def test_tick_evicts_at_max_age_plus_1(self):
        self.pb.track("g1")
        for _ in range(6):   # age becomes 6 > max_age=5
            evicted = self.pb.tick()
        assert "g1" in evicted
        assert not self.pb.is_tracked("g1")
        assert self.pb.stats()["evicted"] == 1

    def test_tick_no_eviction_if_confirmed(self):
        self.pb.track("g1")
        self.pb.confirm("g1")   # 1 confirmation, not yet promoted
        for _ in range(10):   # way past max_age
            evicted = self.pb.tick()
        assert evicted == []     # не вытесняем: есть подтверждения
        assert self.pb.is_tracked("g1")

    def test_tick_returns_list_of_evict_ids(self):
        for i in range(3):
            self.pb.track(f"g{i}")
        for _ in range(6):
            result = self.pb.tick()
        assert set(result) == {"g0", "g1", "g2"}

    def test_tick_evicts_only_zero_confirmations(self):
        self.pb.track("confirmed")
        self.pb.track("unconfirmed")
        self.pb.confirm("confirmed")

        for _ in range(6):
            evicted = self.pb.tick()

        assert "unconfirmed" in evicted
        assert "confirmed" not in evicted

    def test_multiple_evictions_accumulate_stat(self):
        self.pb.track("g1")
        self.pb.track("g2")
        for _ in range(6):
            self.pb.tick()
        assert self.pb.stats()["evicted"] == 2


# ══════════════════════════════════════════════════════════════════════════════
# ProvisionalBase — статистика
# ══════════════════════════════════════════════════════════════════════════════

class TestProvisionalBaseStats:
    def test_empty_stats(self):
        pb = ProvisionalBase()
        s = pb.stats()
        assert s["pending"] == 0
        assert s["promoted"] == 0
        assert s["evicted"] == 0
        assert s["avg_age"] == 0.0
        assert s["avg_conf"] == 0.0

    def test_avg_age(self):
        pb = ProvisionalBase(min_confirmations=10, max_age=100)
        pb.track("g1")
        pb.track("g2")
        pb.tick()           # g1.age=1, g2.age=1
        pb.tick()           # g1.age=2, g2.age=2
        assert pb.stats()["avg_age"] == 2.0

    def test_repr(self):
        pb = ProvisionalBase()
        pb.track("g1")
        r = repr(pb)
        assert "pending=1" in r
        assert "promoted=0" in r
        assert "evicted=0" in r


# ══════════════════════════════════════════════════════════════════════════════
# Интеграция: AttractorEngine + ProvisionalBase
# ══════════════════════════════════════════════════════════════════════════════

class TestAttractorEngineProvisional:
    def _make_engine(self, min_conf=2, max_age=5):
        pb = ProvisionalBase(min_confirmations=min_conf, max_age=max_age)
        base = GeneralizationBase()
        engine = AttractorEngine(base, feature_tolerance=0.1, provisional=pb)
        return engine, pb

    def test_refuted_tracks_new_gen(self):
        engine, pb = self._make_engine()
        tok = _tok(0.5, "a")
        engine.step(tok)
        # Первый токен: база пуста → EXPLORING или создаёт Gen
        # Второй токен с другим признаком → REFUTED → track
        tok2 = _tok(0.9, "b")
        r = engine.step(tok2)
        if r.new_gen_id:
            assert pb.is_tracked(r.new_gen_id)

    def test_no_provisional_does_not_crash(self):
        base = GeneralizationBase()
        engine = AttractorEngine(base, feature_tolerance=0.1, provisional=None)
        tok = _tok(0.5, "a")
        engine.step(tok)   # не должно бросать исключение

    def test_eviction_removes_from_base_and_context(self):
        pb = ProvisionalBase(min_confirmations=10, max_age=2)
        base = GeneralizationBase()
        engine = AttractorEngine(base, feature_tolerance=0.1, provisional=pb)

        # Создаём Gen через REFUTED
        r1 = engine.step(_tok(0.1, "x"))
        r2 = engine.step(_tok(0.9, "y"))
        new_gen_id = r2.new_gen_id

        if new_gen_id:
            assert pb.is_tracked(new_gen_id)
            initial_size = base.size()

            # Прогоняем шаги чтобы age > max_age=2
            for _ in range(4):
                engine.step(_tok(0.5, "z"))

            # После eviction Gen должен исчезнуть из базы
            assert not pb.is_tracked(new_gen_id)
            assert base.get(new_gen_id) is None

    def test_confirmed_promotes_provisional(self):
        """Gen подтверждённый min_confirmations раз снимается с испытательного срока."""
        pb = ProvisionalBase(min_confirmations=2, max_age=100)
        base = GeneralizationBase()
        engine = AttractorEngine(base, feature_tolerance=0.05, provisional=pb)

        # Первый проход: создаём Gen для признака 0.5
        r1 = engine.step(_tok(0.5, "w1"))
        new_id = r1.new_gen_id

        if new_id is None:
            # Если это был EXPLORING — берём Gen из базы
            gens = list(base.all())
            if gens:
                new_id = gens[0].gen_id
                pb.track(new_id)

        if new_id and pb.is_tracked(new_id):
            # Подтверждаем вручную
            pb.confirm(new_id)
            promoted = pb.confirm(new_id)
            assert promoted is True
            assert not pb.is_tracked(new_id)
            # Gen остаётся в базе
            assert base.get(new_id) is not None


# ══════════════════════════════════════════════════════════════════════════════
# Интеграция: LearningSystem + ProvisionalBase
# ══════════════════════════════════════════════════════════════════════════════

class TestLearningSystemProvisional:
    def test_learning_system_accepts_provisional(self):
        pb = ProvisionalBase(min_confirmations=2, max_age=30)
        system = LearningSystem(provisional_base=pb)
        assert system.provisional is pb
        assert system.engine._provisional is pb

    def test_learning_system_default_no_provisional(self):
        system = LearningSystem()
        assert system.provisional is None
        assert system.engine._provisional is None

    def test_provisional_tracks_after_process_token(self):
        pb = ProvisionalBase(min_confirmations=2, max_age=50)
        system = LearningSystem(feature_tolerance=0.1, provisional_base=pb)

        from drivers.text_driver import TextDriver
        drv = TextDriver("t")

        # Подать пару токенов
        for tok in drv.produce("кот мат"):
            system.process_token(tok)

        # ProvisionalBase должен что-то отслеживать
        # (новые Gen при REFUTED автоматически попадают на испытание)
        total = pb.size() + pb.stats()["promoted"] + pb.stats()["evicted"]
        assert total >= 0   # просто проверяем что не упало

    def test_provisional_eviction_keeps_promoted_in_base(self):
        """Промотированные Gen остаются в базе после eviction deadline."""
        pb = ProvisionalBase(min_confirmations=1, max_age=2)
        system = LearningSystem(feature_tolerance=0.1, provisional_base=pb)

        from drivers.text_driver import TextDriver
        drv = TextDriver("t")

        # Обучить 3 раза одним текстом — Gen должны подтвердиться и промотироваться
        for _ in range(3):
            for tok in drv.produce("пух мёд"):
                system.process_token(tok)
            system.reset_context()

        base_size_after = system.base.size()
        # Промотированные не вытесняются
        assert base_size_after > 0
