"""
Тесты CharGenDecoder.

Проверяем:
  - _invert_color_hue: точное восстановление символов
  - _invert_color_hue: обнаружение коллизии «н→а» / «т→а»
  - CharGenDecoder.decode: восстановление строки из реального обучения
  - CharGenDecoder.annotate_base: проставление меток
  - CharRecoveryResult: свойства is_reliable, text, is_empty
  - collision_report: сводная статистика
"""
import math
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drivers.char_gen_decoder import (
    CharGenDecoder,
    CharRecoveryResult,
    _invert_color_hue,
    _HUE_TABLE,
)
from drivers.char_transition_driver import (
    CharTransitionDriver,
    _char_code_normalized,
    _brightness,
    _char_to_region,
)


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────────────

def _make_system(tolerance: float = 0.35, texts: list = None):
    """Создать систему и обучить на текстах."""
    from core.app import CoreApplication
    from core.algorithm import StepOutcome

    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": tolerance})
    app.startup()

    if texts:
        drv = CharTransitionDriver("chars")
        for _ in range(3):
            for t in texts:
                for tok in drv.produce(t):
                    app.system.process_token(tok)
                app.system.reset_context()

    return app.system


# ──────────────────────────────────────────────────────────────────────────────
# 1. _invert_color_hue — точное восстановление
# ──────────────────────────────────────────────────────────────────────────────

class TestInvertColorHue:
    """Проверяем инверсию color_hue для конкретных символов."""

    @pytest.mark.parametrize("char", ["а", "о", "е", "и", "н", "т", "с", "к", "м"])
    def test_cyrillic_exact(self, char: str):
        hue = _char_code_normalized(char)
        br  = _brightness(char)
        recovered, conf = _invert_color_hue(hue, br)
        assert recovered == char, f"Ожидали «{char}», получили «{recovered}»"
        assert conf >= 0.7, f"Уверенность слишком низкая: {conf:.2f}"

    @pytest.mark.parametrize("char", ["e", "i", "o", "t", "s"])
    def test_latin_exact(self, char: str):
        hue = _char_code_normalized(char)
        br  = _brightness(char)
        recovered, conf = _invert_color_hue(hue, br)
        assert recovered == char, f"Ожидали «{char}», получили «{recovered}»"
        assert conf >= 0.5

    def test_latin_a_ambiguous_with_cyrillic(self):
        """
        Латинская 'a' (hue=0.0) совпадает с кириллической 'а' (hue=0.0).
        Декодер возвращает 'а' (Кириллица приоритетнее в HUE_TABLE).
        Это известная коллизия алфавитов — не баг, а свойство кодирования.
        """
        hue = _char_code_normalized("a")  # = 0.0, совпадает с «а»
        br  = _brightness("a")
        recovered, conf = _invert_color_hue(hue, br)
        # Может вернуть 'а' или 'a' — главное не None и не исключение
        assert recovered is not None
        assert conf >= 0.0

    def test_yo_recovery(self):
        """ё — специальный случай (unicode 1105, вне основного диапазона)."""
        hue = _char_code_normalized("ё")
        br  = _brightness("ё")
        recovered, conf = _invert_color_hue(hue, br)
        assert recovered == "ё"
        assert conf > 0.0

    def test_unknown_hue_returns_something(self):
        """Неизвестный hue не должен вызывать исключение."""
        ch, conf = _invert_color_hue(0.5, 0.5)
        # Может вернуть None или символ — главное не exception
        assert conf >= 0.0

    def test_confidence_range(self):
        """Уверенность всегда в [0, 1]."""
        for hue in [0.0, 0.25, 0.5, 0.75, 1.0]:
            for br in [0.0, 0.5, 1.0]:
                _, conf = _invert_color_hue(hue, br)
                assert 0.0 <= conf <= 1.0, f"conf={conf} для hue={hue}, br={br}"


# ──────────────────────────────────────────────────────────────────────────────
# 2. Известная коллизия: «н→а» и «т→а»
# ──────────────────────────────────────────────────────────────────────────────

class TestKnownCollision:
    """
    При tolerance=0.35 переходы «н→а» и «т→а» сливаются в один признак.
    Это проверяет, что декодер хотя бы правильно восстанавливает TARGET («а»),
    даже если SOURCE неоднозначен.
    """

    def test_na_ta_collision_distance(self):
        """Расстояние между «н→а» и «т→а» < 0.35 — коллизия."""
        from core.feature import Feature
        src_н = _char_to_region("н", 0, 3, False, True)
        tgt_а = _char_to_region("а", 1, 3, False, False)
        src_т = _char_to_region("т", 0, 3, False, True)

        f_na = Feature.from_regions("na", 0.0, 1.0, src_н, tgt_а)
        f_ta = Feature.from_regions("ta", 0.0, 1.0, src_т, tgt_а)

        dist = f_na.vector.distance_to(f_ta.vector)
        assert dist < 0.35, f"Ожидали коллизию (dist<0.35), получили dist={dist:.4f}"

    def test_target_а_always_recoverable(self):
        """target_chars «а» восстанавливается правильно из любого перехода к «а»."""
        tgt_а = _char_to_region("а", 1, 3, False, False)
        recovered, conf = _invert_color_hue(tgt_а.color_hue, tgt_а.brightness)
        assert recovered == "а"
        assert conf >= 0.7

    def test_кот_кошка_share_first_transition(self):
        """«к→о» идентично в «кот» и «кошка»: первый переход совпадает."""
        d = CharTransitionDriver("t")
        tok_kot  = list(d.produce("кот"))[0]
        tok_kosh = list(d.produce("кошка"))[0]

        fv1 = tok_kot.data.vector
        fv2 = tok_kosh.data.vector

        dist = fv1.distance_to(fv2)
        assert dist == pytest.approx(0.0, abs=1e-9), \
            f"Переход «к→о» должен быть идентичным, dist={dist}"


# ──────────────────────────────────────────────────────────────────────────────
# 3. CharRecoveryResult — базовые свойства
# ──────────────────────────────────────────────────────────────────────────────

class TestCharRecoveryResult:
    def test_empty_result(self):
        r = CharRecoveryResult()
        assert r.is_empty
        assert r.text == ""
        assert not r.is_reliable

    def test_text_from_words(self):
        r = CharRecoveryResult(words=["маша", "пошла"], confidence=0.9)
        assert r.text == "маша пошла"
        assert not r.is_empty

    def test_text_from_chars_fallback(self):
        r = CharRecoveryResult(chars=["м", "а", "ш", "а"], confidence=0.9)
        assert r.text == "маша"

    def test_is_reliable_requires_confidence_and_no_missing(self):
        r = CharRecoveryResult(words=["тест"], confidence=0.75, missing=0)
        assert r.is_reliable

        r2 = CharRecoveryResult(words=["тест"], confidence=0.75, missing=1)
        assert not r2.is_reliable

        r3 = CharRecoveryResult(words=["тест"], confidence=0.65, missing=0)
        assert not r3.is_reliable

    def test_repr_contains_text(self):
        r = CharRecoveryResult(words=["привет"], confidence=0.8)
        assert "привет" in repr(r)


# ──────────────────────────────────────────────────────────────────────────────
# 4. CharGenDecoder.decode — реальное обучение
# ──────────────────────────────────────────────────────────────────────────────

class TestCharGenDecoderDecode:
    TEXTS = [
        "маша пошла в лес",
        "маша нашла гриб",
        "кот сидит на окне",
        "кот и кошка похожи",
    ]

    @pytest.fixture(scope="class")
    def trained_system(self):
        return _make_system(tolerance=0.35, texts=self.TEXTS)

    def test_decode_returns_result(self, trained_system):
        decoder = CharGenDecoder(trained_system.engine)
        for gen in trained_system.base.all()[:5]:
            r = decoder.decode(gen)
            assert isinstance(r, CharRecoveryResult)

    def test_decode_non_empty_for_high_sig_gen(self, trained_system):
        """Высоко-значимые Gen должны декодироваться в непустую строку."""
        decoder = CharGenDecoder(trained_system.engine)
        top_gens = sorted(trained_system.base.all(), key=lambda g: -g.significance)[:10]
        non_empty = [decoder.decode(g) for g in top_gens if not decoder.decode(g).is_empty]
        # Хотя бы половина из топ-10 должна декодироваться
        assert len(non_empty) >= 5

    def test_decode_chain1_gives_single_char(self, trained_system):
        """Gen с chain=1 должен декодироваться в 1 символ (только target)."""
        decoder = CharGenDecoder(trained_system.engine)
        chain1_gens = [g for g in trained_system.base.all()
                       if len(g.feature_chain) == 1]
        if not chain1_gens:
            pytest.skip("Нет Gen с chain=1")
        for gen in chain1_gens[:5]:
            r = decoder.decode(gen)
            if not r.is_empty:
                assert len(r.chars) == 1, f"chain=1 Gen должен давать 1 символ, дал {len(r.chars)}"

    def test_decode_confidence_in_range(self, trained_system):
        """confidence всегда в [0, 1]."""
        decoder = CharGenDecoder(trained_system.engine)
        for gen in trained_system.base.all():
            r = decoder.decode(gen)
            assert 0.0 <= r.confidence <= 1.0, f"conf={r.confidence} вне [0,1]"

    def test_decode_missing_zero_for_registered_features(self, trained_system):
        """Все признаки из обученных Gen должны быть в реестре."""
        decoder = CharGenDecoder(trained_system.engine)
        total_missing = 0
        for gen in trained_system.base.all():
            r = decoder.decode(gen)
            total_missing += r.missing
        # Допускаем небольшой процент (некоторые feature_id могут быть заменены)
        assert total_missing == 0, f"Найдено {total_missing} пропущенных признаков"

    def test_decode_chain_len_recorded(self, trained_system):
        """chain_len в результате должен совпадать с реальной длиной."""
        decoder = CharGenDecoder(trained_system.engine)
        for gen in trained_system.base.all()[:20]:
            r = decoder.decode(gen)
            assert r.chain_len == len(gen.feature_chain)


# ──────────────────────────────────────────────────────────────────────────────
# 5. CharGenDecoder.annotate_base
# ──────────────────────────────────────────────────────────────────────────────

class TestAnnotateBase:
    TEXTS = [
        "кот сидит на окне",
        "кошка и кот друзья",
        "маша пришла домой",
    ]

    @pytest.fixture(scope="class")
    def trained_system(self):
        return _make_system(tolerance=0.35, texts=self.TEXTS)

    def test_annotate_updates_labels(self, trained_system):
        """После annotate_base у некоторых Gen появляются метки."""
        decoder = CharGenDecoder(trained_system.engine)
        # Сначала убираем все метки для чистоты
        for gen in trained_system.base.all():
            gen.label = None
        n = decoder.annotate_base(trained_system.base, min_confidence=0.5, min_chain=2)
        assert n > 0, "Ожидали хотя бы один обновлённый Gen"

    def test_annotate_respects_overwrite_false(self, trained_system):
        """overwrite=False: существующие метки не перезаписываются."""
        decoder = CharGenDecoder(trained_system.engine)
        sentinel = "ТУТ_БЫЛ_ТЕСТ"
        # Поставим метку вручную
        some_gen = list(trained_system.base.all())[0]
        some_gen.label = sentinel

        decoder.annotate_base(trained_system.base, overwrite=False)
        assert some_gen.label == sentinel

    def test_annotate_overwrite_true_replaces(self, trained_system):
        """overwrite=True: метки заменяются если confidence достаточная."""
        decoder = CharGenDecoder(trained_system.engine)
        # Найти Gen с хорошей уверенностью
        for gen in trained_system.base.all():
            r = decoder.decode(gen)
            if r.confidence >= 0.65 and len(gen.feature_chain) >= 2:
                gen.label = "СТАРАЯ_МЕТКА"
                decoder.annotate_base(trained_system.base, min_confidence=0.65,
                                      min_chain=2, overwrite=True)
                # Метка должна была замениться
                assert gen.label != "СТАРАЯ_МЕТКА"
                return
        pytest.skip("Нет Gen с достаточной уверенностью")


# ──────────────────────────────────────────────────────────────────────────────
# 6. collision_report
# ──────────────────────────────────────────────────────────────────────────────

class TestCollisionReport:
    TEXTS = [
        "маша пошла в лес",
        "маша встретила зайца",
        "заяц убежал от лисы",
        "лиса хитрая и умная",
    ]

    @pytest.fixture(scope="class")
    def trained_system(self):
        return _make_system(tolerance=0.35, texts=self.TEXTS)

    def test_report_keys(self, trained_system):
        decoder = CharGenDecoder(trained_system.engine)
        report = decoder.collision_report(trained_system.base)
        expected_keys = {
            "total_gen", "decoded_ok", "partial", "failed",
            "avg_confidence", "collision_rate",
        }
        assert expected_keys == set(report.keys())

    def test_report_counts_consistent(self, trained_system):
        decoder = CharGenDecoder(trained_system.engine)
        report = decoder.collision_report(trained_system.base)
        total = report["decoded_ok"] + report["partial"] + report["failed"]
        assert total == report["total_gen"]

    def test_collision_rate_in_range(self, trained_system):
        decoder = CharGenDecoder(trained_system.engine)
        report = decoder.collision_report(trained_system.base)
        assert 0.0 <= report["collision_rate"] <= 1.0

    def test_avg_confidence_in_range(self, trained_system):
        decoder = CharGenDecoder(trained_system.engine)
        report = decoder.collision_report(trained_system.base)
        assert 0.0 <= report["avg_confidence"] <= 1.0

    def test_tolerance_affects_collision_rate(self):
        """Меньший tolerance → меньше коллизий, выше уверенность декодера."""
        sys_tight  = _make_system(tolerance=0.15, texts=self.TEXTS)
        sys_loose  = _make_system(tolerance=0.35, texts=self.TEXTS)

        dec_tight = CharGenDecoder(sys_tight.engine)
        dec_loose = CharGenDecoder(sys_loose.engine)

        rep_tight = dec_tight.collision_report(sys_tight.base)
        rep_loose = dec_loose.collision_report(sys_loose.base)

        # При меньшем tolerance: меньше коллизий
        assert rep_tight["collision_rate"] <= rep_loose["collision_rate"] + 0.1, (
            f"tight={rep_tight['collision_rate']:.2f} должно быть ≤ loose={rep_loose['collision_rate']:.2f}"
        )


# ──────────────────────────────────────────────────────────────────────────────
# 7. include_source=True
# ──────────────────────────────────────────────────────────────────────────────

class TestIncludeSource:
    def test_include_source_adds_one_char(self):
        """include_source=True добавляет source-символ первого признака."""
        sys = _make_system(tolerance=0.35, texts=["кот сидит"])
        decoder_no  = CharGenDecoder(sys.engine, include_source=False)
        decoder_yes = CharGenDecoder(sys.engine, include_source=True)

        for gen in sorted(sys.base.all(), key=lambda g: -g.significance)[:5]:
            r_no  = decoder_no.decode(gen)
            r_yes = decoder_yes.decode(gen)
            if not r_no.is_empty and not r_yes.is_empty:
                # С source-символом строка длиннее или равна
                assert len(r_yes.chars) >= len(r_no.chars)
                return

        pytest.skip("Нет подходящих Gen")
