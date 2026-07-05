"""
Тесты CharTransitionDriver.

Проверяем:
  - количество токенов (N_chars - 1 на непустой текст)
  - направление на границе слова (π/2) vs внутри слова (0.0)
  - общий первый переход к→о в «кот» и «кошка»
  - пустой ввод не даёт токенов
  - load_buffer / reset
  - FREQ_TABLE_RU: корректные значения яркости
"""
import math
import sys
import os

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drivers.char_transition_driver import (
    CharTransitionDriver,
    FREQ_TABLE_RU,
    FREQ_TABLE_EN,
    _brightness,
    _vowel_class,
    _char_code_normalized,
    _char_to_region,
)


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────────────

class TestFreqTable:
    def test_ru_most_frequent(self):
        assert FREQ_TABLE_RU["о"] == 1.0

    def test_ru_least_frequent(self):
        assert FREQ_TABLE_RU["ъ"] == pytest.approx(0.030, abs=0.001)

    def test_en_most_frequent(self):
        assert FREQ_TABLE_EN["e"] == 1.0

    def test_brightness_cyrillic(self):
        # «о» самая частая — яркость 1.0
        assert _brightness("о") == 1.0

    def test_brightness_latin(self):
        assert _brightness("e") == 1.0

    def test_brightness_unknown(self):
        # Цифра или знак → нейтральная яркость 0.5
        assert _brightness("5") == 0.5

    def test_brightness_case_insensitive(self):
        assert _brightness("О") == _brightness("о")


class TestVowelClass:
    def test_vowel_ru(self):
        assert _vowel_class("а") == 1.0
        assert _vowel_class("е") == 1.0
        assert _vowel_class("о") == 1.0

    def test_consonant_ru(self):
        assert _vowel_class("к") == pytest.approx(0.3)
        assert _vowel_class("с") == pytest.approx(0.3)

    def test_non_alpha(self):
        assert _vowel_class("5") == 0.0
        assert _vowel_class(" ") == 0.0

    def test_vowel_en(self):
        assert _vowel_class("a") == 1.0
        assert _vowel_class("i") == 1.0

    def test_consonant_en(self):
        assert _vowel_class("b") == pytest.approx(0.3)


class TestCharCodeNormalized:
    def test_cyrillic_а(self):
        # «а» = 1072, первая → ~0.0
        assert _char_code_normalized("а") == pytest.approx(0.0, abs=0.01)

    def test_cyrillic_я(self):
        # «я» = 1103, последняя → 1.0
        assert _char_code_normalized("я") == pytest.approx(1.0, abs=0.01)

    def test_latin_a(self):
        assert _char_code_normalized("a") == pytest.approx(0.0, abs=0.01)

    def test_latin_z(self):
        assert _char_code_normalized("z") == pytest.approx(1.0, abs=0.01)

    def test_in_range(self):
        for ch in "абвгдеёжзийклмнопрстуфхцчшщъыьэюя":
            v = _char_code_normalized(ch)
            assert 0.0 <= v <= 1.0, f"Out of range for {ch!r}: {v}"


class TestCharToRegion:
    """
    _char_to_region использует позиционно-инвариантное кодирование:
    size=0, color_sat=0, fractal_dim=1 — только идентичность символа.
    """

    def test_position_invariant_size(self):
        """size всегда 0 независимо от позиции."""
        r0 = _char_to_region("к", 0, 4, False, True)
        r3 = _char_to_region("т", 3, 4, True, False)
        assert r0.size == pytest.approx(0.0)
        assert r3.size == pytest.approx(0.0)

    def test_color_sat_always_zero(self):
        """color_sat всегда 0 — граница слова не кодируется в RegionChars."""
        assert _char_to_region("к", 0, 3, False, True).color_sat == pytest.approx(0.0)
        assert _char_to_region("т", 2, 3, True, False).color_sat == pytest.approx(0.0)
        assert _char_to_region("о", 1, 3, False, False).color_sat == pytest.approx(0.0)

    def test_fractal_dim_constant(self):
        """fractal_dim всегда 1.0 — длина слова не кодируется."""
        for wlen in [2, 5, 10, 20]:
            r = _char_to_region("а", 0, wlen, False, True)
            assert r.fractal_dim == pytest.approx(1.0)

    def test_brightness_is_char_property(self):
        """brightness — частотный ранг: одинаков для одного символа в любой позиции."""
        r0 = _char_to_region("а", 0, 4, False, True)
        r2 = _char_to_region("а", 2, 4, False, False)
        assert r0.brightness == pytest.approx(r2.brightness)

    def test_contrast_vowel_consonant(self):
        """contrast: гласная=1.0, согласная=0.3."""
        assert _char_to_region("а", 0, 3, False, True).contrast == pytest.approx(1.0)
        assert _char_to_region("к", 0, 3, False, True).contrast == pytest.approx(0.3)

    def test_color_hue_is_char_identity(self):
        """color_hue уникален для каждого символа и инвариантен к позиции."""
        r0 = _char_to_region("м", 0, 3, False, True)
        r2 = _char_to_region("м", 2, 3, True, False)
        assert r0.color_hue == pytest.approx(r2.color_hue)
        rk = _char_to_region("к", 0, 3, False, True)
        assert r0.color_hue != pytest.approx(rk.color_hue)


# ──────────────────────────────────────────────────────────────────────────────
# CharTransitionDriver
# ──────────────────────────────────────────────────────────────────────────────

class TestCharTransitionDriverTokenCount:
    def test_one_word_n_minus_1(self):
        d = CharTransitionDriver("t")
        # «кот» = 3 символа → 2 перехода
        toks = list(d.produce("кот"))
        assert len(toks) == 2

    def test_two_words(self):
        d = CharTransitionDriver("t")
        # «кот мяч» = к-о-т, м-я-ч = 6 символов, 5 переходов
        toks = list(d.produce("кот мяч"))
        assert len(toks) == 5

    def test_four_words(self):
        d = CharTransitionDriver("t")
        # «маша пошла в лес» = 4+5+1+3 = 13 символов → 12 переходов
        toks = list(d.produce("маша пошла в лес"))
        assert len(toks) == 12

    def test_empty_string(self):
        d = CharTransitionDriver("t")
        toks = list(d.produce(""))
        assert len(toks) == 0

    def test_none_produces_nothing(self):
        d = CharTransitionDriver("t")
        toks = list(d.produce(None))
        assert len(toks) == 0

    def test_single_char_word_no_tokens(self):
        d = CharTransitionDriver("t")
        toks = list(d.produce("а"))
        assert len(toks) == 0


class TestCharTransitionDriverDirection:
    def _get_dirs(self, text: str):
        d = CharTransitionDriver("t")
        return [tok.data.direction for tok in d.produce(text)]

    def test_within_word_direction_zero(self):
        # «кот» — все переходы внутри слова
        dirs = self._get_dirs("кот")
        assert all(d == pytest.approx(0.0) for d in dirs)

    def test_boundary_direction_pi_half(self):
        # «кот мяч» — третий переход (т→м) = граница
        dirs = self._get_dirs("кот мяч")
        assert dirs[2] == pytest.approx(math.pi / 2, abs=1e-9)

    def test_inner_not_boundary(self):
        dirs = self._get_dirs("кот мяч")
        # переходы 0,1 (к→о, о→т) = внутри слова
        assert dirs[0] == pytest.approx(0.0)
        assert dirs[1] == pytest.approx(0.0)
        # переход 3,4 (м→я, я→ч) = внутри второго слова
        assert dirs[3] == pytest.approx(0.0)
        assert dirs[4] == pytest.approx(0.0)

    def test_multiple_boundaries(self):
        # «а б в» = 3 однобуквенных слова → 2 перехода-границы
        dirs = self._get_dirs("а б в")
        assert dirs[0] == pytest.approx(math.pi / 2)
        assert dirs[1] == pytest.approx(math.pi / 2)


class TestCharTransitionDriverSharedPrefix:
    """Ключевой тест: «кот» и «кошка» разделяют признак к→о."""

    def test_first_transition_identical(self):
        d = CharTransitionDriver("t")
        toks_kot  = list(d.produce("кот"))
        toks_kosh = list(d.produce("кошка"))

        fv1 = toks_kot[0].data.vector
        fv2 = toks_kosh[0].data.vector

        assert fv1.delta_size       == pytest.approx(fv2.delta_size,       abs=1e-6)
        assert fv1.delta_brightness == pytest.approx(fv2.delta_brightness, abs=1e-6)
        assert fv1.delta_contrast   == pytest.approx(fv2.delta_contrast,   abs=1e-6)
        assert fv1.delta_color_hue  == pytest.approx(fv2.delta_color_hue,  abs=1e-6)

    def test_second_transition_differs(self):
        # о→т (кот) ≠ о→ш (кошка) — второй переход должен различаться
        d = CharTransitionDriver("t")
        toks_kot  = list(d.produce("кот"))
        toks_kosh = list(d.produce("кошка"))

        fv1 = toks_kot[1].data.vector   # о→т
        fv2 = toks_kosh[1].data.vector  # о→ш

        # delta_color_hue должно отличаться (разные символы)
        assert fv1.delta_color_hue != pytest.approx(fv2.delta_color_hue, abs=0.01)


class TestCharTransitionDriverBuffer:
    def test_load_buffer_string(self):
        d = CharTransitionDriver("t")
        n = d.load_buffer("кот сидит")
        assert n == d.buffer_size
        assert n > 0

    def test_query_from_buffer(self):
        d = CharTransitionDriver("t")
        d.load_buffer("кот")
        tok = d.query()
        assert tok is not None

    def test_reset_clears_buffer(self):
        d = CharTransitionDriver("t")
        d.load_buffer("кот сидит")
        d.reset()
        assert d.buffer_size == 0

    def test_produce_twice_independent(self):
        d = CharTransitionDriver("t")
        t1 = list(d.produce("кот"))
        t2 = list(d.produce("кот"))
        assert len(t1) == len(t2)


class TestCharTransitionDriverLowercase:
    def test_lowercase_on(self):
        d = CharTransitionDriver("t", lowercase=True)
        toks_lower = list(d.produce("Кот"))
        toks_upper = list(d.produce("кот"))
        fv1 = toks_lower[0].data.vector
        fv2 = toks_upper[0].data.vector
        assert fv1.delta_brightness == pytest.approx(fv2.delta_brightness, abs=1e-6)

    def test_lowercase_off(self):
        d = CharTransitionDriver("t", lowercase=False)
        toks = list(d.produce("Кот"))
        assert len(toks) == 2  # Должны быть токены даже без lowercase


class TestCharTransitionDriverIntegration:
    """Интеграционный тест: обучение на нескольких текстах."""

    def test_learning_increases_base(self):
        import sys, os
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from core.app import CoreApplication

        app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
        app.startup()

        d = CharTransitionDriver("char")
        texts = [
            "маша пошла в лес",
            "маша встретила медведя",
            "медведь обрадовался",
        ]

        initial_size = len(app.system.base.all())
        for t in texts:
            for tok in d.produce(t):
                app.system.process_token(tok)
            app.system.reset_context()

        final_size = len(app.system.base.all())
        assert final_size > initial_size

    def test_token_has_feature(self):
        from core.feature import Feature
        d = CharTransitionDriver("t")
        tok = next(iter(d.produce("кот")))
        assert isinstance(tok.data, Feature)
