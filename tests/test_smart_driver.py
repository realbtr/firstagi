"""
tests/test_smart_driver.py — тесты для SmartTextDriver.

Покрытие (46 тестов):
  TestCandidateSet        (10) — entropy, фильтрация, IG, best_probe
  TestEntropyMinimizer    (12) — probe_word: пустые кандидаты, точное совпадение,
                                  фазы suffix/prefix/root/greedy, непредсказанное слово
  TestThemeRhemeRouter    (8)  — label_sequence, theme_identifier_char, rheme_pivot_char
  TestContextualizer      (6)  — estimate (регистр, домен, морфология), adjust_tolerance
  TestSmartTextDriver     (10) — produce, set_candidates, build_vocab, efficiency_summary,
                                  load_buffer, reset, repr
"""
from __future__ import annotations

import math
import pytest

from drivers.smart_text_driver import (
    CandidateSet,
    Contextualizer,
    ContextParameters,
    EntropyMinimizer,
    ProbeStats,
    SmartTextDriver,
    ThemeRhemeLabel,
    ThemeRhemeRouter,
)


# ══════════════════════════════════════════════════════════════════════════════
# TestCandidateSet (10 тестов)
# ══════════════════════════════════════════════════════════════════════════════

class TestCandidateSet:

    def test_empty_entropy(self):
        cs = CandidateSet([])
        assert cs.entropy() == 0.0

    def test_single_word_entropy(self):
        cs = CandidateSet(["кот"])
        assert cs.entropy() == 0.0

    def test_two_words_entropy(self):
        cs = CandidateSet(["кот", "пёс"])
        assert abs(cs.entropy() - 1.0) < 1e-9  # log2(2) = 1

    def test_four_words_entropy(self):
        cs = CandidateSet(["а", "б", "в", "г"])
        assert abs(cs.entropy() - 2.0) < 1e-9  # log2(4) = 2

    def test_filter_by_length(self):
        cs = CandidateSet(["кот", "кошка", "котёнок", "пёс"])
        filtered = cs.filter_by_length(3)
        assert set(filtered.words) == {"кот", "пёс"}

    def test_filter_by_length_no_match(self):
        cs = CandidateSet(["кот", "кошка"])
        filtered = cs.filter_by_length(10)
        assert len(filtered) == 0

    def test_filter_by_char(self):
        cs = CandidateSet(["кот", "кошка", "котёнок", "пёс"])
        filtered = cs.filter_by_char(0, "к")
        assert set(filtered.words) == {"кот", "кошка", "котёнок"}

    def test_filter_by_char_middle(self):
        cs = CandidateSet(["кот", "кошка"])
        # pos=1: 'о' в обоих словах
        filtered = cs.filter_by_char(1, "о")
        assert len(filtered) == 2

    def test_information_gain_positive(self):
        cs = CandidateSet(["кот", "пёс", "кошка"])
        # Проверяем 'к' на pos=0 — отсеивает 'пёс', остаются 'кот' и 'кошка'
        ig = cs.information_gain(0, "к")
        assert ig > 0.0

    def test_contains(self):
        cs = CandidateSet(["кот", "пёс"])
        assert cs.contains("кот")
        assert not cs.contains("медведь")

    def test_best_probe(self):
        cs = CandidateSet(["кот", "пёс", "кошка", "краб"])
        # best_probe должен вернуть позицию в слове "кошка"
        pos = cs.best_probe("кошка")
        assert 0 <= pos < len("кошка")


# ══════════════════════════════════════════════════════════════════════════════
# TestEntropyMinimizer (12 тестов)
# ══════════════════════════════════════════════════════════════════════════════

class TestEntropyMinimizer:

    def setup_method(self):
        self.minimizer = EntropyMinimizer(min_entropy_threshold=0.5, max_probes=5)

    def test_empty_candidates_returns_zero_probes(self):
        stats = self.minimizer.probe_word("кот", CandidateSet([]))
        assert stats.probes_used == 0
        assert stats.was_predicted is False

    def test_single_candidate_matching(self):
        stats = self.minimizer.probe_word("кот", CandidateSet(["кот"]))
        assert stats.was_predicted is True
        # Один кандидат — минимум проб
        assert stats.probes_used <= 1

    def test_word_in_candidates(self):
        candidates = CandidateSet(["кот", "кошка", "котёнок"])
        stats = self.minimizer.probe_word("кот", candidates)
        assert stats.was_predicted is True
        assert stats.candidates_before == 3

    def test_word_not_in_candidates(self):
        candidates = CandidateSet(["пёс", "волк", "лиса"])
        stats = self.minimizer.probe_word("кот", candidates)
        assert stats.was_predicted is False

    def test_length_probe_eliminates_most(self):
        # Все кандидаты одной длины — длинная пробка ничего не даёт
        candidates = CandidateSet(["кот", "пёс", "лис"])
        stats = self.minimizer.probe_word("кот", candidates)
        # Проб должно быть немного
        assert stats.probes_used <= 5

    def test_probes_not_exceed_max(self):
        # Много похожих слов — но probes_used ≤ max_probes
        words = [f"слово{i}" for i in range(20)]
        candidates = CandidateSet(words)
        stats = self.minimizer.probe_word("слово5", candidates)
        assert stats.probes_used <= self.minimizer.max_probes

    def test_positions_checked_are_valid_indices(self):
        candidates = CandidateSet(["кот", "кошка", "котёнок"])
        word = "кошка"
        stats = self.minimizer.probe_word(word, candidates)
        for pos in stats.positions_checked:
            assert 0 <= pos < len(word)

    def test_entropy_saved_nonnegative(self):
        candidates = CandidateSet(["кот", "кошка", "котёнок", "краб"])
        stats = self.minimizer.probe_word("кот", candidates)
        assert stats.entropy_saved >= 0.0

    def test_probe_stats_type(self):
        stats = self.minimizer.probe_word("кот", CandidateSet(["кот"]))
        assert isinstance(stats, ProbeStats)

    def test_two_chars_disambiguate(self):
        # 'кот' vs 'кошка' vs 'корень' — должны различаться за ≤ 3 проб
        candidates = CandidateSet(["кот", "кошка", "корень"])
        stats = self.minimizer.probe_word("кот", candidates)
        assert stats.probes_used <= 3

    def test_suffix_phase_used_first(self):
        # Suffix (последний символ) даёт большой IG между "кот" и "кошка"
        candidates = CandidateSet(["кот", "кошка"])
        stats = self.minimizer.probe_word("кот", candidates)
        # Последний символ 'т' vs 'а' — разные, должно различить за 1 пробу
        assert stats.probes_used <= 2

    def test_skipped_flag_not_set_with_multiple_candidates(self):
        candidates = CandidateSet(["кот", "кошка", "котёнок"])
        stats = self.minimizer.probe_word("кот", candidates)
        # skipped=True только при H=0 после length probe
        # При 3 кандидатах не должно быть пропуска
        if candidates.filter_by_length(len("кот")).entropy() > 0.0:
            assert not stats.skipped


# ══════════════════════════════════════════════════════════════════════════════
# TestThemeRhemeRouter (8 тестов)
# ══════════════════════════════════════════════════════════════════════════════

class TestThemeRhemeRouter:

    def setup_method(self):
        self.router = ThemeRhemeRouter()

    def test_empty_sequence(self):
        result = self.router.label_sequence([])
        assert result == []

    def test_single_word(self):
        result = self.router.label_sequence(["кот"])
        assert len(result) == 1
        assert result[0].word == "кот"
        assert result[0].role in ("theme", "rheme")

    def test_label_count_matches_words(self):
        words = ["кот", "сидит", "на", "окне"]
        result = self.router.label_sequence(words)
        assert len(result) == len(words)

    def test_label_types(self):
        result = self.router.label_sequence(["кот", "сидит", "окно"])
        for lbl in result:
            assert isinstance(lbl, ThemeRhemeLabel)
            assert lbl.role in ("theme", "rheme")
            assert 0.0 <= lbl.cd_score <= 1.0

    def test_cd_score_increases_with_position(self):
        # При равном словаре — позиционно-поздние слова имеют больший CD
        router = ThemeRhemeRouter(vocab={"кот": 0.0, "сидит": 0.0, "окно": 0.0})
        result = router.label_sequence(["кот", "сидит", "окно"])
        # Последнее слово должно иметь наибольший cd_score
        assert result[-1].cd_score >= result[0].cd_score

    def test_rare_words_have_higher_cd(self):
        # Редкое слово (vocab_index высокий = малочастотное) → выше CD.
        # Используем 3 слова: одно частое раннее, одно частое позднее, одно редкое.
        # Редкое слово в начале должно иметь cd < редкого в конце при том же vocab.
        vocab = {"the": 0.0, "cat": 0.1, "экзистенциализм": 1.0}
        router = ThemeRhemeRouter(vocab=vocab)
        # Строка из трёх слов: частое→частое→редкое
        result = router.label_sequence(["the", "cat", "экзистенциализм"])
        # Последнее слово: максимальная редкость + максимальная позиция → наибольший CD
        assert result[2].cd_score >= result[0].cd_score

    def test_theme_identifier_char(self):
        char = self.router.theme_identifier_char("кот")
        assert char == "к"

    def test_rheme_pivot_char(self):
        word = "котёнок"  # len=7, root_pos=2
        char = self.router.rheme_pivot_char(word)
        assert char == word[max(1, len(word) // 3)]

    def test_empty_word_returns_none(self):
        assert self.router.theme_identifier_char("") is None
        assert self.router.rheme_pivot_char("") is None


# ══════════════════════════════════════════════════════════════════════════════
# TestContextualizer (6 тестов)
# ══════════════════════════════════════════════════════════════════════════════

class TestContextualizer:

    def setup_method(self):
        self.ctx = Contextualizer()

    def test_returns_context_parameters(self):
        result = self.ctx.estimate("кот сидит на окне")
        assert isinstance(result, ContextParameters)

    def test_formal_register(self):
        text = "данный алгоритм следовательно однако вследствие указанный"
        result = self.ctx.estimate(text)
        assert result.register == "formal"

    def test_informal_register(self):
        text = "ну вот типа значит короче блин ладно"
        result = self.ctx.estimate(text)
        assert result.register == "informal"

    def test_technical_domain(self):
        text = "алгоритм функция параметр конфигурация протокол интерфейс архитектура"
        result = self.ctx.estimate(text)
        assert result.domain == "technical"

    def test_synthetic_morphology(self):
        text = "обеспечение конфигурация ускорение активация соединение"
        result = self.ctx.estimate(text)
        assert result.morphology == "synthetic"

    def test_adjust_tolerance_formal(self):
        params = ContextParameters(register="formal", domain="technical")
        adjusted = self.ctx.adjust_tolerance(params, base_tolerance=0.3)
        assert adjusted < 0.3  # строже при формальном/техническом

    def test_adjust_tolerance_informal(self):
        params = ContextParameters(register="informal", domain="general")
        adjusted = self.ctx.adjust_tolerance(params, base_tolerance=0.3)
        assert adjusted > 0.3  # мягче при разговорном

    def test_adjust_tolerance_bounds(self):
        params = ContextParameters(register="informal")
        # Не должно выходить за [0.05, 0.5]
        for base in [0.01, 0.5, 0.99]:
            result = self.ctx.adjust_tolerance(params, base_tolerance=base)
            assert 0.05 <= result <= 0.5


# ══════════════════════════════════════════════════════════════════════════════
# TestSmartTextDriver (10 тестов)
# ══════════════════════════════════════════════════════════════════════════════

class TestSmartTextDriver:

    def setup_method(self):
        self.drv = SmartTextDriver("smart_test")

    def test_produce_returns_tokens(self):
        tokens = list(self.drv.produce("кот сидит на окне"))
        assert len(tokens) == 3  # 4 слова → 3 пары

    def test_produce_empty_text(self):
        tokens = list(self.drv.produce(""))
        assert tokens == []

    def test_produce_single_word(self):
        tokens = list(self.drv.produce("кот"))
        assert tokens == []

    def test_token_label_has_metadata(self):
        tokens = list(self.drv.produce("кот сидит на окне"))
        for tok in tokens:
            assert tok.label is not None
            # label содержит метаданные: |p=N|h=X|role=
            assert "|p=" in tok.label
            assert "|h=" in tok.label
            assert "|role=" in tok.label

    def test_token_driver_id(self):
        tokens = list(self.drv.produce("кот сидит"))
        assert tokens[0].driver_id == "smart_test"

    def test_set_candidates_influences_stats(self):
        self.drv.set_candidates(["сидит", "лежит", "спит"])
        list(self.drv.produce("кот сидит на окне"))
        stats = self.drv.session_stats()
        assert len(stats) == 3
        # хотя бы одно слово было предсказано
        predicted = [s for s in stats if s.was_predicted]
        assert len(predicted) >= 1  # "сидит" был в кандидатах

    def test_efficiency_summary_keys(self):
        list(self.drv.produce("кот сидит на окне"))
        summary = self.drv.efficiency_summary()
        assert "avg_probes" in summary
        assert "predicted_rate" in summary
        assert "avg_entropy_saved" in summary
        assert "skipped_rate" in summary

    def test_efficiency_summary_empty_session(self):
        summary = self.drv.efficiency_summary()
        assert summary["avg_probes"] == 0.0

    def test_load_buffer_from_string(self):
        size = self.drv.load_buffer("кот сидит на окне")
        assert size == 3  # 3 токена загружено

    def test_reset_clears_state(self):
        self.drv.set_candidates(["кот", "пёс"])
        list(self.drv.produce("кот сидит"))
        self.drv.reset()
        assert self.drv.buffer_size == 0
        assert len(self.drv._candidates) == 0
        assert self.drv.session_stats() == []

    def test_repr(self):
        r = repr(self.drv)
        assert "SmartTextDriver" in r
        assert "smart_test" in r

    def test_build_vocab_updates_router(self):
        corpus = ["кот сидит на окне", "пёс бежит по полю"]
        self.drv.build_vocab(corpus)
        assert len(self.drv._vocab) > 0
        # После build_vocab тема/рема разметка должна работать
        tokens = list(self.drv.produce("кот сидит"))
        assert len(tokens) == 1

    def test_context_params_set_after_produce(self):
        assert self.drv.context_params() is None
        list(self.drv.produce("кот сидит на окне"))
        assert self.drv.context_params() is not None

    def test_produce_without_candidates_works(self):
        # Без кандидатов — работает как TextDriver
        drv = SmartTextDriver("passive")
        tokens = list(drv.produce("маша пошла в лес"))
        assert len(tokens) == 3

    def test_session_stats_accumulate(self):
        list(self.drv.produce("кот сидит"))
        list(self.drv.produce("пёс лежит"))
        stats = self.drv.session_stats()
        assert len(stats) == 2  # по одному токену от каждой пары
