"""
Тесты ModelVoice — канал B_модель (Phase 2 двухканального обучения).
"""
from __future__ import annotations

import pytest
from collections import Counter
from unittest.mock import MagicMock, patch

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drivers.model_voice import (
    ChannelDivergence,
    ModelVoice,
    VoicePrediction,
)


# ══════════════════════════════════════════════════════════════════════════════
# Вспомогательные фабрики
# ══════════════════════════════════════════════════════════════════════════════

def _make_pred(words=None, confidence=0.5, source_gen="g1") -> VoicePrediction:
    return VoicePrediction(
        words=words or [],
        confidence=confidence,
        source_gen=source_gen,
    )


def _make_div(predicted=None, actual="маша", match=True,
              divergence=0.0, confidence=0.5, source_gen="g1") -> ChannelDivergence:
    return ChannelDivergence(
        predicted_words=predicted or [],
        actual_word=actual,
        match=match,
        divergence=divergence,
        confidence=confidence,
        source_gen=source_gen,
    )


def _make_system(expected_features=None, gen_significance=None):
    """Создать мок LearningSystem для тестов."""
    system  = MagicMock()
    context = MagicMock()
    base    = MagicMock()
    engine  = MagicMock()

    engine.context = context
    system.engine  = engine
    system.base    = base

    # get_expected_features(base) → {gen_id: feature_id}
    expected = expected_features or {}
    context.get_expected_features.return_value = expected
    context._active = {}

    # base.get(gen_id) → gen (с significance)
    def get_gen(gid):
        if gen_significance and gid in gen_significance:
            gen = MagicMock()
            gen.significance = gen_significance[gid]
            gen.label = ""
            gen.feature_chain = []
            return gen
        return None
    base.get.side_effect = get_gen

    return system


# ══════════════════════════════════════════════════════════════════════════════
# TestVoicePrediction
# ══════════════════════════════════════════════════════════════════════════════

class TestVoicePrediction:
    def test_has_prediction_false_when_empty(self):
        pred = _make_pred(words=[])
        assert pred.has_prediction is False

    def test_has_prediction_true_when_words(self):
        pred = _make_pred(words=["маша"])
        assert pred.has_prediction is True

    def test_top_word_none_when_empty(self):
        pred = _make_pred(words=[])
        assert pred.top_word is None

    def test_top_word_first_when_not_empty(self):
        pred = _make_pred(words=["маша", "лес"])
        assert pred.top_word == "маша"

    def test_as_text_no_prediction(self):
        pred = _make_pred(words=[])
        assert pred.as_text() == "~"

    def test_as_text_single_word(self):
        pred = _make_pred(words=["маша"], confidence=0.75)
        txt = pred.as_text()
        assert "маша" in txt
        assert "0.75" in txt

    def test_as_text_multiple_words_shows_alternatives(self):
        pred = _make_pred(words=["маша", "лес", "волк"], confidence=0.60)
        txt = pred.as_text()
        assert "маша" in txt
        assert "лес" in txt
        assert "или" in txt

    def test_as_text_en_lang(self):
        pred = _make_pred(words=["masha"], confidence=0.70)
        txt = pred.as_text(lang="en")
        assert "'masha'" in txt


# ══════════════════════════════════════════════════════════════════════════════
# TestChannelDivergence
# ══════════════════════════════════════════════════════════════════════════════

class TestChannelDivergence:
    def test_as_text_match(self):
        cd = _make_div(predicted=["маша"], actual="маша", match=True)
        txt = cd.as_text()
        assert "✓" in txt
        assert "маша" in txt

    def test_as_text_mismatch(self):
        cd = _make_div(predicted=["пошла"], actual="побежала", match=False,
                       divergence=0.77)
        txt = cd.as_text()
        assert "↔" in txt
        assert "пошла" in txt
        assert "побежала" in txt
        assert "0.77" in txt

    def test_as_text_no_prediction(self):
        cd = _make_div(predicted=[], actual="медведь", match=False)
        txt = cd.as_text()
        assert "~" in txt
        assert "медведь" in txt

    def test_as_text_en(self):
        cd = _make_div(predicted=["forest"], actual="field", match=False,
                       divergence=0.70)
        txt = cd.as_text(lang="en")
        assert "Expected" in txt
        assert "forest" in txt


# ══════════════════════════════════════════════════════════════════════════════
# TestModelVoiceRecordFeature
# ══════════════════════════════════════════════════════════════════════════════

class TestModelVoiceRecordFeature:
    def test_record_increases_vocab(self):
        mv = ModelVoice()
        assert mv.vocab_size == 0
        mv.record_feature("f1", "маша")
        assert mv.vocab_size == 1

    def test_record_same_feature_different_words(self):
        mv = ModelVoice()
        mv.record_feature("f1", "маша")
        mv.record_feature("f1", "волк")
        assert mv.vocab_size == 1
        assert mv._feature_words["f1"]["маша"] == 1
        assert mv._feature_words["f1"]["волк"] == 1

    def test_record_same_feature_same_word_increments(self):
        mv = ModelVoice()
        mv.record_feature("f1", "маша")
        mv.record_feature("f1", "маша")
        assert mv._feature_words["f1"]["маша"] == 2

    def test_record_lowercases(self):
        mv = ModelVoice()
        mv.record_feature("f1", "Маша")
        assert "маша" in mv._feature_words["f1"]

    def test_record_ignores_none_feature(self):
        mv = ModelVoice()
        mv.record_feature(None, "маша")
        assert mv.vocab_size == 0

    def test_record_ignores_empty_word(self):
        mv = ModelVoice()
        mv.record_feature("f1", "")
        assert mv.vocab_size == 0

    def test_record_ignores_question_mark(self):
        mv = ModelVoice()
        mv.record_feature("f1", "?")
        assert mv.vocab_size == 0


# ══════════════════════════════════════════════════════════════════════════════
# TestModelVoicePredict
# ══════════════════════════════════════════════════════════════════════════════

class TestModelVoicePredict:
    def test_predict_empty_context_returns_empty(self):
        mv     = ModelVoice()
        system = _make_system(expected_features={})
        pred   = mv.predict(system)
        assert not pred.has_prediction
        assert pred.confidence == 0.0
        assert pred.source_gen is None

    def test_predict_unknown_feature_returns_empty(self):
        mv     = ModelVoice()
        system = _make_system(
            expected_features={"g1": "f_unknown"},
            gen_significance={"g1": 0.8},
        )
        pred = mv.predict(system)
        assert not pred.has_prediction
        assert pred.source_gen == "g1"   # gen всё равно найден

    def test_predict_with_known_feature_returns_words(self):
        mv = ModelVoice()
        mv.record_feature("f1", "маша")
        mv.record_feature("f1", "маша")
        mv.record_feature("f1", "волк")

        system = _make_system(
            expected_features={"g1": "f1"},
            gen_significance={"g1": 0.9},
        )
        pred = mv.predict(system)
        assert pred.has_prediction
        assert pred.top_word == "маша"   # маша встречалась чаще
        assert 0.0 < pred.confidence <= 1.0

    def test_predict_weighted_by_significance(self):
        mv = ModelVoice()
        mv.record_feature("f1", "маша")   # используется gen с sig=0.9
        mv.record_feature("f2", "волк")   # используется gen с sig=0.1

        system = _make_system(
            expected_features={"g1": "f1", "g2": "f2"},
            gen_significance={"g1": 0.9, "g2": 0.1},
        )
        pred = mv.predict(system)
        # «маша» должна быть выше благодаря большей значимости
        assert pred.top_word == "маша"

    def test_predict_top_n_limits_results(self):
        mv = ModelVoice()
        for w in ["маша", "волк", "лиса", "заяц", "медведь"]:
            mv.record_feature("f1", w)

        system = _make_system(
            expected_features={"g1": "f1"},
            gen_significance={"g1": 0.5},
        )
        pred = mv.predict(system, top_n=2)
        assert len(pred.words) <= 2

    def test_predict_source_gen_is_highest_significance(self):
        mv = ModelVoice()
        mv.record_feature("f2", "слово")

        system = _make_system(
            expected_features={"g_low": "f1", "g_high": "f2"},
            gen_significance={"g_low": 0.1, "g_high": 0.8},
        )
        pred = mv.predict(system)
        assert pred.source_gen == "g_high"

    def test_predict_confidence_between_0_and_1(self):
        mv = ModelVoice()
        mv.record_feature("f1", "маша")
        system = _make_system(
            expected_features={"g1": "f1"},
            gen_significance={"g1": 0.5},
        )
        pred = mv.predict(system)
        assert 0.0 <= pred.confidence <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# TestModelVoiceDiverge
# ══════════════════════════════════════════════════════════════════════════════

class TestModelVoiceDiverge:
    def test_diverge_exact_match_zero(self):
        mv   = ModelVoice()
        pred = _make_pred(words=["маша"], confidence=0.8)
        cd   = mv.diverge(pred, "маша")
        assert cd.match is True
        assert cd.divergence == 0.0

    def test_diverge_match_case_insensitive(self):
        mv   = ModelVoice()
        pred = _make_pred(words=["Маша"], confidence=0.8)
        cd   = mv.diverge(pred, "маша")
        assert cd.match is True
        assert cd.divergence == 0.0

    def test_diverge_mismatch_nonzero(self):
        mv   = ModelVoice()
        pred = _make_pred(words=["пошла"], confidence=0.7)
        cd   = mv.diverge(pred, "побежала")
        assert cd.match is False
        assert cd.divergence > 0.0

    def test_diverge_higher_confidence_higher_divergence_on_miss(self):
        mv    = ModelVoice()
        pred_hi = _make_pred(words=["пошла"], confidence=0.9)
        pred_lo = _make_pred(words=["пошла"], confidence=0.1)
        cd_hi = mv.diverge(pred_hi, "побежала")
        cd_lo = mv.diverge(pred_lo, "побежала")
        assert cd_hi.divergence >= cd_lo.divergence

    def test_diverge_no_prediction_max_divergence(self):
        mv   = ModelVoice()
        pred = _make_pred(words=[], confidence=0.0)
        cd   = mv.diverge(pred, "медведь")
        assert cd.divergence == 1.0

    def test_diverge_appends_to_history(self):
        mv   = ModelVoice()
        pred = _make_pred(words=["маша"], confidence=0.6)
        mv.diverge(pred, "маша")
        mv.diverge(pred, "волк")
        assert len(mv.history) == 2

    def test_diverge_returns_correct_actual_word(self):
        mv   = ModelVoice()
        pred = _make_pred(words=["маша"], confidence=0.5)
        cd   = mv.diverge(pred, "лес")
        assert cd.actual_word == "лес"

    def test_diverge_divergence_capped_at_one(self):
        mv   = ModelVoice()
        pred = _make_pred(words=["маша"], confidence=1.0)
        cd   = mv.diverge(pred, "другое_слово")
        assert cd.divergence <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# TestModelVoiceStats
# ══════════════════════════════════════════════════════════════════════════════

class TestModelVoiceStats:
    def test_stats_empty(self):
        mv = ModelVoice()
        s  = mv.stats()
        assert s["total"] == 0
        assert s["match_rate"] == 0.0
        assert s["avg_divergence"] == 0.0
        assert s["feature_vocab"] == 0

    def test_stats_after_matches(self):
        mv   = ModelVoice()
        pred = _make_pred(words=["маша"], confidence=0.7)
        mv.diverge(pred, "маша")   # match
        mv.diverge(pred, "маша")   # match
        s = mv.stats()
        assert s["total"] == 2
        assert s["matches"] == 2
        assert s["match_rate"] == 1.0
        assert s["avg_divergence"] == 0.0

    def test_stats_mixed(self):
        mv   = ModelVoice()
        pred = _make_pred(words=["маша"], confidence=0.6)
        mv.diverge(pred, "маша")    # match
        mv.diverge(pred, "волк")    # mismatch
        s = mv.stats()
        assert s["total"] == 2
        assert s["matches"] == 1
        assert s["match_rate"] == 0.5
        assert s["avg_divergence"] > 0.0

    def test_reset_history_clears_stats(self):
        mv   = ModelVoice()
        pred = _make_pred(words=["маша"], confidence=0.5)
        mv.diverge(pred, "маша")
        mv.reset_history()
        s = mv.stats()
        assert s["total"] == 0

    def test_reset_history_keeps_vocab(self):
        mv = ModelVoice()
        mv.record_feature("f1", "маша")
        mv.reset_history()
        assert mv.vocab_size == 1   # словарь сохранён

    def test_repr_contains_key_info(self):
        mv = ModelVoice()
        mv.record_feature("f1", "маша")
        pred = _make_pred(words=["маша"], confidence=0.7)
        mv.diverge(pred, "маша")
        r = repr(mv)
        assert "ModelVoice" in r
        assert "vocab=1" in r


# ══════════════════════════════════════════════════════════════════════════════
# TestModelVoiceLearningCycle — сквозной тест без реального LearningSystem
# ══════════════════════════════════════════════════════════════════════════════

class TestModelVoiceLearningCycle:
    def test_predict_improves_after_many_records(self):
        """После N записей feature→word, predict() должен выдать правильное слово."""
        mv = ModelVoice()
        # Обучаем: feature f1 → «маша» (5 раз), «волк» (1 раз)
        for _ in range(5):
            mv.record_feature("f1", "маша")
        mv.record_feature("f1", "волк")

        system = _make_system(
            expected_features={"g1": "f1"},
            gen_significance={"g1": 0.9},
        )
        pred = mv.predict(system)
        assert pred.top_word == "маша"   # доминирует после частых записей

    def test_divergence_decreases_on_known_sequence(self):
        """Повторные совпадения → match_rate растёт."""
        mv = ModelVoice()
        mv.record_feature("f1", "маша")

        system = _make_system(
            expected_features={"g1": "f1"},
            gen_significance={"g1": 0.8},
        )

        divergences = []
        for _ in range(5):
            pred = mv.predict(system)
            cd   = mv.diverge(pred, "маша")
            mv.record_feature("f1", "маша")
            divergences.append(cd.divergence)

        # Первый шаг: уже есть 1 запись, должен угадать
        assert divergences[0] == 0.0

    def test_full_cycle_record_predict_diverge(self):
        mv = ModelVoice()
        # Цикл: запись → предсказание → дивергенция
        for i in range(3):
            mv.record_feature("f1", "маша")

        system = _make_system(
            expected_features={"g1": "f1"},
            gen_significance={"g1": 0.6},
        )
        pred = mv.predict(system)
        cd   = mv.diverge(pred, "маша")

        assert pred.top_word == "маша"
        assert cd.match is True
        assert mv.stats()["total"] == 1
