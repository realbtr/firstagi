"""
SequenceDriver — драйвер для числовых последовательностей.

Преобразует список числовых значений в поток признаков (Feature):
  - каждая пара (x_i, x_{i+1}) образует один признак-переход
  - характеристики области: само значение как «яркость»,
    производная как «контраст», etc.

Используется для демонстрации и unit-тестов.
"""

from __future__ import annotations
import math
import uuid
from typing import Iterator, List, Sequence

from core.feature import Feature, FeatureVector, RegionCharacteristics
from core.generalization import PeripheralToken
from .base import PeripheralDriver


def _stats(value: float, prev: float, window_mean: float) -> RegionCharacteristics:
    """Преобразовать скалярное значение в RegionCharacteristics."""
    brightness = max(0.0, min(1.0, (value + 1.0) / 2.0))  # нормировка [-1, 1] → [0, 1]
    contrast = abs(value - window_mean) / (abs(window_mean) + 1e-9)
    contrast = min(1.0, contrast)
    delta = value - prev
    fractal_dim = 1.0 + min(1.0, abs(delta) * 2)          # грубая оценка
    return RegionCharacteristics(
        size=0.1,            # фиксированный размер окна
        brightness=brightness,
        contrast=contrast,
        color_hue=0.0,
        color_sat=0.0,
        fractal_dim=fractal_dim,
    )


class SequenceDriver(PeripheralDriver):
    """
    Драйвер числовой последовательности.

    Пример:
        driver = SequenceDriver("seq0", [0.1, 0.5, -0.3, 0.8, 0.1])
        for token in driver.produce():
            result = engine.step(token)
    """

    def __init__(
        self,
        driver_id: str,
        sequence: Sequence[float],
        direction: float = 0.0,   # направление движения внимания (рад)
        distance: float = 1.0,    # дистанция между шагами (нормированная)
    ) -> None:
        super().__init__(driver_id)
        self._sequence = list(sequence)
        self.direction = direction
        self.distance = distance
        self._pos: int = 0

    def produce(self) -> Iterator[PeripheralToken]:
        """Генерировать токены-признаки из последовательности."""
        seq = self._sequence
        if len(seq) < 2:
            return

        window_mean = sum(seq) / len(seq)

        for i in range(len(seq) - 1):
            src = _stats(seq[i], seq[i - 1] if i > 0 else seq[i], window_mean)
            tgt = _stats(seq[i + 1], seq[i], window_mean)

            feature = Feature.from_regions(
                feature_id=str(uuid.uuid4()),
                direction=self.direction,
                distance=self.distance,
                source=src,
                target=tgt,
            )
            token = PeripheralToken.new(driver_id=self.driver_id, data=feature,
                                        label=f"{seq[i + 1]:.3g}")
            self._pos = i + 1
            yield token

    def load_buffer(self, values_or_tokens, **kwargs) -> int:  # type: ignore[override]
        """
        Удобный метод: принимает List[float] или List[PeripheralToken].

        Если передан список чисел — создаёт SequenceDriver на лету,
        токенизирует и добавляет токены в буфер.
        Возвращает новый размер буфера.
        """
        from core.generalization import PeripheralToken as PT
        if values_or_tokens and not isinstance(values_or_tokens[0], PT):
            tmp = SequenceDriver(
                self.driver_id,
                list(values_or_tokens),
                direction=self.direction,
                distance=self.distance,
            )
            tokens = list(tmp.produce())
            return super().load_buffer(tokens)
        return super().load_buffer(values_or_tokens)

    def reset(self) -> None:
        self._pos = 0
        self.clear_buffer()
