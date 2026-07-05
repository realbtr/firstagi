"""
TextDriver — периферийный драйвер для текстового ввода.

Преобразует текст в поток PeripheralToken.

Признак текстового перехода:
  Переход (word_i → word_{i+1}) кодируется как Feature:
    • delta_size         = изменение длины слова (нормированное)
    • delta_brightness   = изменение позиции слова в словаре (лексический сдвиг)
    • delta_contrast     = изменение «информационной плотности» (уникальные символы / длина)
    • delta_fractal_dim  = изменение сложности слова
    • direction          = позиция в предложении (нормированная) как угол

Инвариантность к:
  • регистру (всё в lower)
  • порядку слов в словаре (используем относительные дельты)
  • абсолютной позиции в тексте (используем дельты позиций)
"""

from __future__ import annotations
import uuid
import math
from typing import Iterator, List, Optional

from core.feature import Feature, RegionCharacteristics
from core.generalization import PeripheralToken
from .base import PeripheralDriver


# ──────────────────────────────────────────────────────────────────────
# Вспомогательные функции

def _word_complexity(word: str) -> float:
    """
    Информационная плотность слова = доля уникальных символов.
    Аналог фрактальной размерности для текста.
    """
    if not word:
        return 0.0
    return len(set(word)) / len(word)


def _build_vocab(words: List[str]) -> dict[str, float]:
    """
    Построить словарь: слово → нормированный индекс [0, 1].
    Учитываем частоту: более частые слова получают меньший индекс.
    """
    freq: dict[str, int] = {}
    for w in words:
        freq[w] = freq.get(w, 0) + 1

    # Сортируем по частоте убывания (частые → маленький индекс)
    sorted_words = sorted(freq, key=lambda w: -freq[w])
    n = max(len(sorted_words) - 1, 1)
    return {w: i / n for i, w in enumerate(sorted_words)}


def _word_to_region(
    word: str,
    vocab_index: float,
) -> RegionCharacteristics:
    """
    Закодировать слово как RegionCharacteristics.

    Позиционная информация намеренно исключена: признак перехода (w_i → w_{i+1})
    должен быть инвариантен к тому, где в предложении находятся эти слова.
    Только лексические свойства слов участвуют в кодировании.
    """
    length = min(len(word) / 20.0, 1.0)        # нормированная длина [0, 1]
    complexity = _word_complexity(word)         # уникальных букв / длина
    return RegionCharacteristics(
        size=length,
        brightness=vocab_index,
        contrast=complexity,
        color_hue=vocab_index,                  # лексический ранг (не позиция)
        color_sat=complexity,
        fractal_dim=1.0 + complexity,
    )


# ──────────────────────────────────────────────────────────────────────

class TextDriver(PeripheralDriver):
    """
    Текстовый драйвер: текст → поток PeripheralToken[Feature].

    Режимы:
      "words"  — токенизация по словам (по умолчанию)
      "chars"  — токенизация по символам (для детального анализа)
      "bigram" — биграммы слов (пары слов как единый токен)

    Пример:
        driver = TextDriver("txt0", "кот сидит на окне")
        for token in driver.produce():
            result = engine.step(token)
    """

    def __init__(
        self,
        driver_id: str,
        text: str = "",
        mode: str = "words",
        lowercase: bool = True,
    ) -> None:
        super().__init__(driver_id)
        self._text = text
        self.mode = mode
        self.lowercase = lowercase
        self._vocab: dict[str, float] = {}

    def set_text(self, text: str) -> None:
        """Установить новый текст."""
        self._text = text

    def _tokenize(self, text: str) -> List[str]:
        if self.lowercase:
            text = text.lower()
        if self.mode == "words":
            # Простая токенизация: разбить по пробелам и знакам препинания
            import re
            return [w for w in re.split(r"[\s,.\-!?;:\"'()]+", text) if w]
        elif self.mode == "chars":
            return [c for c in text if c.strip()]
        elif self.mode == "bigram":
            words = [w for w in text.split() if w]
            return [f"{words[i]}_{words[i+1]}" for i in range(len(words) - 1)]
        return text.split()

    def build_vocab(self, texts: List[str]) -> None:
        """
        Построить/обновить словарь по корпусу текстов.
        Полезно вызвать перед серией produce() для консистентного кодирования.
        """
        all_words: List[str] = []
        for t in texts:
            all_words.extend(self._tokenize(t))
        self._vocab = _build_vocab(all_words)

    def produce(self, text: Optional[str] = None) -> Iterator[PeripheralToken]:
        """
        Генерировать токены-признаки из текста.

        Каждая пара последовательных слов (w_i, w_{i+1}) образует один
        Feature-токен (признак перехода).
        """
        source_text = text if text is not None else self._text
        words = self._tokenize(source_text)

        if len(words) < 2:
            return

        # Если словарь не построен — строим на лету из текущего текста
        if not self._vocab:
            self._vocab = _build_vocab(words)

        n = len(words)
        for i in range(n - 1):
            w1, w2 = words[i], words[i + 1]

            vi1 = self._vocab.get(w1, 0.5)
            vi2 = self._vocab.get(w2, 0.5)

            src = _word_to_region(w1, vi1)
            tgt = _word_to_region(w2, vi2)

            # Направление = изменение лексического ранга между словами.
            # Фиксированное distance=1.0 даёт инвариантность к длине предложения.
            direction = (vi2 - vi1) * math.pi   # знаковый угол: вверх/вниз по словарю

            feature = Feature.from_regions(
                feature_id=str(uuid.uuid4()),
                direction=direction,
                distance=1.0,
                source=src,
                target=tgt,
            )

            token = PeripheralToken.new(
                driver_id=self.driver_id,
                data=feature,
                label=w2,   # метка = слово, к которому переходим
            )
            yield token

    def load_buffer(self, text_or_tokens, **kwargs) -> int:  # type: ignore[override]
        """
        Удобный метод: принимает строку или List[PeripheralToken].

        Если передана строка — токенизирует её и добавляет токены в буфер.
        Если передан список токенов — делегирует базовому методу.
        Возвращает новый размер буфера.
        """
        if isinstance(text_or_tokens, str):
            tokens = list(self.produce(text=text_or_tokens))
            return super().load_buffer(tokens)
        return super().load_buffer(text_or_tokens)

    def reset(self) -> None:
        self.clear_buffer()

    def __repr__(self) -> str:
        return f"TextDriver(id={self.driver_id!r}, mode={self.mode!r}, buf={self.buffer_size})"
