"""
CharTransitionDriver — символьный переходный драйвер.

Кодирует текст как последовательность переходов между символами.
Каждый переход (char_i → char_{i+1}) — один PeripheralToken[Feature].

Преимущества перед TextDriver (пары слов):
  • «кот» и «кошка» разделяют признаки к→о, общие корни → общие Gen
  • Gen естественно формируют вероятностное три (тrie) — минимально различающие цепочки
  • Динамическая разрешающая способность: короткие цепочки = грубо, длинные = точно
  • Морфологическая осведомлённость: суффиксы, корни, префиксы → отдельные кластеры Gen

Кодирование RegionCharacteristics для символа (позиционно-инвариантное):
  brightness  = частотный ранг символа [0, 1]        (типичность)
  contrast    = класс: гласная=1.0 / согласная=0.3 / прочее=0.0  (фонетика)
  color_hue   = нормированный код символа [0, 1]     (точная идентичность)
  size, color_sat, fractal_dim = 0/0/1               (нейтральные — не кодируются)

Позиционно-инвариантность: «м→а» в любом слове и позиции → одинаковый
FeatureVector. Это фундаментальное свойство вероятностного три.
direction = π/2 при пересечении границы слова, 0.0 внутри слова.

Запуск демо:
    py -X utf8 drivers/char_transition_driver.py
"""
from __future__ import annotations

import math
import re
import uuid
from typing import Iterator, List, Optional

from core.feature import Feature, RegionCharacteristics
from core.generalization import PeripheralToken
from .base import PeripheralDriver


# ──────────────────────────────────────────────────────────────────────────────
# Частотные таблицы: brightness = 1.0 - (rank-1)/N  (чаще → ярче)
# ──────────────────────────────────────────────────────────────────────────────

# Русский алфавит: ранг по убыванию частоты (источник: Шайкевич и др.)
FREQ_TABLE_RU: dict[str, float] = {
    "о": 1.000, "е": 0.970, "а": 0.939, "и": 0.909, "н": 0.879,
    "т": 0.848, "с": 0.818, "р": 0.788, "в": 0.758, "л": 0.727,
    "к": 0.697, "м": 0.667, "д": 0.636, "п": 0.606, "у": 0.576,
    "я": 0.545, "ы": 0.515, "ь": 0.485, "г": 0.455, "з": 0.424,
    "б": 0.394, "ч": 0.364, "й": 0.333, "х": 0.303, "ж": 0.273,
    "ш": 0.242, "ё": 0.212, "ц": 0.182, "щ": 0.152, "э": 0.121,
    "ф": 0.091, "ю": 0.061, "ъ": 0.030,
}

# Английский алфавит: ранг по убыванию частоты (оценка по Etaoin Shrdlu)
FREQ_TABLE_EN: dict[str, float] = {
    "e": 1.000, "t": 0.960, "a": 0.920, "o": 0.880, "i": 0.840,
    "n": 0.800, "s": 0.760, "h": 0.720, "r": 0.680, "d": 0.640,
    "l": 0.600, "c": 0.560, "u": 0.520, "m": 0.480, "w": 0.440,
    "f": 0.400, "g": 0.360, "y": 0.320, "p": 0.280, "b": 0.240,
    "v": 0.200, "k": 0.160, "j": 0.120, "x": 0.080, "q": 0.040, "z": 0.000,
}

_VOWELS_RU = frozenset("аеёиоуыьъэюя")
_VOWELS_EN = frozenset("aeiou")


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────────────

def _brightness(char: str) -> float:
    """Частотный ранг символа из объединённой таблицы."""
    c = char.lower()
    if c in FREQ_TABLE_RU:
        return FREQ_TABLE_RU[c]
    if c in FREQ_TABLE_EN:
        return FREQ_TABLE_EN[c]
    return 0.5  # цифры, знаки — нейтральная яркость


def _vowel_class(char: str) -> float:
    """1.0 гласная, 0.3 согласная, 0.0 всё остальное."""
    c = char.lower()
    if c in _VOWELS_RU or c in _VOWELS_EN:
        return 1.0
    if c.isalpha():
        return 0.3
    return 0.0


def _char_code_normalized(char: str) -> float:
    """Нормированный unicode-код символа [0, 1]."""
    o = ord(char)
    # Кириллица: 1072 (а) – 1103 (я) + 1105 (ё) + 1066 (Ъ) mapped
    if 1072 <= o <= 1103:
        return (o - 1072) / 31.0
    if o == 1105:  # ё
        return 6.5 / 31.0
    # ASCII буквы: a-z → 0..1
    if 97 <= o <= 122:
        return (o - 97) / 25.0
    # Прочие: нормируем в [0, 1] по широкому диапазону
    return min(o / 65535.0, 1.0)


def _char_to_region(
    char: str,
    pos_in_word: int,
    word_len: int,
    is_last_in_word: bool,
    is_first_in_word: bool,
) -> RegionCharacteristics:
    """Закодировать один символ как RegionCharacteristics.

    Только позиционно-инвариантные измерения:
      brightness  — частотный ранг (идентичность относительно общей нормы)
      contrast    — класс: гласная / согласная (фонетика)
      color_hue   — нормированный код символа (точная идентичность)

    Позиционно-зависимые поля (size, color_sat, fractal_dim) намеренно
    зафиксированы в нейтральных значениях, чтобы один и тот же переход
    (например «м→а») в любом слове и позиции порождал идентичный
    FeatureVector — это ключевое свойство для вероятностного три.
    """
    brightness  = _brightness(char)
    contrast    = _vowel_class(char)
    color_hue   = _char_code_normalized(char)

    return RegionCharacteristics(
        size=0.0,           # позиция не кодируется — инвариантность позиции
        brightness=brightness,
        contrast=contrast,
        color_hue=color_hue,
        color_sat=0.0,      # граница слова не кодируется (см. direction=π/2)
        fractal_dim=1.0,    # длина слова не кодируется
    )


# ──────────────────────────────────────────────────────────────────────────────
# CharTransitionDriver
# ──────────────────────────────────────────────────────────────────────────────

class CharTransitionDriver(PeripheralDriver):
    """
    Символьный переходный драйвер: текст → поток PeripheralToken[Feature].

    Каждый токен = признак перехода (char_i → char_{i+1}).
    На границах слов direction = π/2, внутри слова direction = 0.0.

    Gen над этими токенами формируют вероятностное три:
      «к» → «о» → «т» — Gen для корня "кот"
      «к» → «о» → «ш» → «к» — Gen для "кошк-"
    Общий префикс «к» → «о» будет одним общим Gen-родителем.

    Параметры
    ----------
    driver_id : str
    lowercase : bool  (по умолчанию True)

    Использование:
        d = CharTransitionDriver("chars")
        for tok in d.produce("маша пошла в лес"):
            result = system.process_token(tok)
    """

    def __init__(self, driver_id: str, lowercase: bool = True) -> None:
        super().__init__(driver_id)
        self.lowercase = lowercase

    def produce(self, text: Optional[str] = None) -> Iterator[PeripheralToken]:  # type: ignore[override]
        """
        Генерировать токены из текста.

        text : str  — текст для обработки (если None — буфер пуст, ничего не генерируется)

        Каждая пара соседних символов порождает один PeripheralToken[Feature].
        Граница слова (last_char → first_char_of_next_word) отмечается direction=π/2.
        """
        if text is None:
            return

        source = text.lower() if self.lowercase else text

        # Разбиваем на слова, сохраняем все непустые
        words = [w for w in re.split(r"[\s,.\-!?;:\"'()]+", source) if w]
        if not words:
            return

        # Строим плоский список (char, pos_in_word, word_len, is_last, is_first, word)
        all_chars: List[tuple] = []
        for word in words:
            wlen = len(word)
            for i, ch in enumerate(word):
                all_chars.append((ch, i, wlen, i == wlen - 1, i == 0, word))

        # Генерируем переходы
        for i in range(len(all_chars) - 1):
            ch1, pos1, wlen1, is_last1, is_first1, word1 = all_chars[i]
            ch2, pos2, wlen2, is_last2, is_first2, word2 = all_chars[i + 1]

            is_boundary = is_last1 and is_first2  # переход через границу слова
            direction = math.pi / 2 if is_boundary else 0.0

            src = _char_to_region(ch1, pos1, wlen1, is_last1, is_first1)
            tgt = _char_to_region(ch2, pos2, wlen2, is_last2, is_first2)

            feature = Feature.from_regions(
                feature_id=str(uuid.uuid4()),
                direction=direction,
                distance=1.0,
                source=src,
                target=tgt,
            )
            # На границе слов: label = целевое слово (аналог TextDriver где label=w2).
            # Внутри слова: label = целевой символ.
            label = word2 if is_boundary else ch2
            yield PeripheralToken.new(
                driver_id=self.driver_id,
                data=feature,
                label=label,
            )

    def load_buffer(self, text_or_tokens, **kwargs) -> int:  # type: ignore[override]
        """Принимает строку или List[PeripheralToken]."""
        if isinstance(text_or_tokens, str):
            tokens = list(self.produce(text=text_or_tokens))
            return super().load_buffer(tokens)
        return super().load_buffer(text_or_tokens)

    def reset(self) -> None:
        self.clear_buffer()

    def __repr__(self) -> str:
        return f"CharTransitionDriver(id={self.driver_id!r}, buf={self.buffer_size})"


# ──────────────────────────────────────────────────────────────────────────────
# Демо
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from core.app import CoreApplication
    from training.serial_corpus import ALL_SERIAL_TEXTS

    W  = "\033[0m"; CY = "\033[96m"; GR = "\033[92m"; BD = "\033[1m"; DM = "\033[90m"

    def hdr(t: str) -> None:
        print(f"\n{BD}{CY}{'═'*68}{W}")
        print(f"{BD}{CY}  {t}{W}")
        print(f"{BD}{CY}{'═'*68}{W}\n")

    hdr("CharTransitionDriver — символьные переходы vs слова")

    # ── 1. Показать токены на примере ──────────────────────────────────────────
    hdr("Пример: «кот сидит на окне»")
    cd = CharTransitionDriver("chars")
    text = "кот сидит на окне"
    tokens = list(cd.produce(text))
    print(f"  Слов: 4, символов перехода: {len(tokens)}")
    for tok in tokens:
        fv = tok.data.vector
        print(f"  δ=({fv[0]:+.2f},{fv[1]:+.2f},{fv[2]:+.2f},{fv[3]:+.2f},{fv[4]:+.2f},{fv[5]:+.2f})"
              f"  dir={tok.data.direction:.2f}")

    # ── 2. Сравнение длин: TextDriver vs CharTransitionDriver ──────────────────
    hdr("Длина потока токенов: TextDriver vs CharTransitionDriver")
    from drivers.text_driver import TextDriver
    td = TextDriver("words")
    sample = ALL_SERIAL_TEXTS[:5]
    for t in sample:
        n_word = len(list(td.produce(t)))
        n_char = len(list(cd.produce(t)))
        print(f"  [{n_word:3d} слов / {n_char:4d} симв]  {t[:50]}")

    # ── 3. Обучение: CharTransitionDriver ─────────────────────────────────────
    hdr("Обучение: 3 прохода по 10 текстам")
    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.35})
    app.startup()

    cd2 = CharTransitionDriver("chars2")
    for _ in range(3):
        for t in ALL_SERIAL_TEXTS[:10]:
            for tok in cd2.produce(t):
                app.system.process_token(tok)
            app.system.reset_context()

    base = app.system.base.all()
    print(f"  Gen в базе: {len(base)}")

    # Топ-10 по значимости
    top = sorted(base, key=lambda g: g.significance, reverse=True)[:10]
    print(f"\n  Топ-10 Gen (значимость / длина цепочки):")
    for g in top:
        print(f"    sig={g.significance:.3f}  chain_len={len(g.feature_chain)}  {g.gen_id[:12]}")

    # ── 4. Сравнение с TextDriver: размер базы и mr ────────────────────────────
    hdr("Сравнение: CharDriver vs TextDriver (3 прохода, 10 текстов)")
    app2 = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.35})
    app2.startup()

    td2 = TextDriver("words2")
    for _ in range(3):
        for t in ALL_SERIAL_TEXTS[:10]:
            for tok in td2.produce(t):
                app2.system.process_token(tok)
            app2.system.reset_context()

    # mr на последнем проходе
    def calc_mr(system, driver, texts):
        total, confirmed = 0, 0
        for t in texts:
            from core.algorithm import StepOutcome
            for tok in driver.produce(t):
                r = system.process_token(tok)
                total += 1
                if r.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
                    confirmed += 1
            system.reset_context()
        return confirmed / total if total else 0.0

    mr_char = calc_mr(app.system, CharTransitionDriver("c_test"), ALL_SERIAL_TEXTS[:10])
    mr_text = calc_mr(app2.system, TextDriver("t_test"), ALL_SERIAL_TEXTS[:10])

    print(f"  {'Драйвер':<22} {'Base':<8} {'MR':<8}")
    print(f"  {'CharTransitionDriver':<22} {len(app.system.base.all()):<8} {mr_char:.3f}")
    print(f"  {'TextDriver':<22} {len(app2.system.base.all()):<8} {mr_text:.3f}")
    print()
    print(f"  CharTransitionDriver: больше Gen (символы ≈ {len(list(CharTransitionDriver('x').produce(ALL_SERIAL_TEXTS[0])))} токенов на 1 текст)")
    print(f"  TextDriver:           меньше Gen (слова ≈ {len(list(TextDriver('x').produce(ALL_SERIAL_TEXTS[0])))} токенов на 1 текст)")
    print()
    print("  Gen в CharDriver = узлы вероятностного три.")
    print("  Короткие цепочки (chain=1,2) = высокочастотные переходы букв.")
    print("  Длинные цепочки (chain=5+)  = конкретные морфемы/слова.")
