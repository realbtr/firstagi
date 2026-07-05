"""
Признак (Feature) — атомарный элемент системы.

Признак = направленный переход между двумя областями внимания.
Кодируется как вектор относительных изменений характеристик области.
Инвариантен к масштабу, повороту, сдвигу, общей яркости/тональности.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional
import math


@dataclass
class RegionCharacteristics:
    """Интегральные характеристики области внимания."""
    size: float = 0.0           # нормированный размер области
    brightness: float = 0.0    # средняя яркость [0, 1]
    contrast: float = 0.0      # контрастность [0, 1]
    color_hue: float = 0.0     # оттенок [0, 1] (нормированный)
    color_sat: float = 0.0     # насыщенность [0, 1]
    fractal_dim: float = 1.0   # фрактальная размерность [1, 2]

    def delta(self, other: RegionCharacteristics) -> FeatureVector:
        """Вычислить относительные изменения (признак перехода)."""
        def rel(a: float, b: float) -> float:
            denom = (abs(a) + abs(b)) / 2
            return (b - a) / denom if denom > 1e-9 else 0.0

        return FeatureVector(
            delta_size=rel(self.size, other.size),
            delta_brightness=rel(self.brightness, other.brightness),
            delta_contrast=rel(self.contrast, other.contrast),
            delta_color_hue=rel(self.color_hue, other.color_hue),
            delta_color_sat=rel(self.color_sat, other.color_sat),
            delta_fractal_dim=rel(self.fractal_dim, other.fractal_dim),
        )


@dataclass
class FeatureVector:
    """
    Вектор относительных изменений характеристик при переходе.
    Это и есть математический «признак» в смысле статьи.
    """
    delta_size: float = 0.0
    delta_brightness: float = 0.0
    delta_contrast: float = 0.0
    delta_color_hue: float = 0.0
    delta_color_sat: float = 0.0
    delta_fractal_dim: float = 0.0

    def distance_to(self, other: FeatureVector) -> float:
        """Евклидово расстояние между двумя признаками в пространстве признаков."""
        return math.sqrt(
            (self.delta_size - other.delta_size) ** 2
            + (self.delta_brightness - other.delta_brightness) ** 2
            + (self.delta_contrast - other.delta_contrast) ** 2
            + (self.delta_color_hue - other.delta_color_hue) ** 2
            + (self.delta_color_sat - other.delta_color_sat) ** 2
            + (self.delta_fractal_dim - other.delta_fractal_dim) ** 2
        )

    def matches(self, other: FeatureVector, tolerance: float = 0.3) -> bool:
        """Совпадает ли признак с другим в пределах допуска (обобщение)."""
        return self.distance_to(other) <= tolerance


@dataclass
class Feature:
    """
    Признак — направленный переход между двумя областями внимания.

    Поля:
        feature_id    — уникальный идентификатор
        direction     — угол направления перехода [0, 2π)
        distance      — нормированное расстояние перехода [0, 1]
        vector        — вектор изменений характеристик
        source_chars  — характеристики исходной области (опционально)
        target_chars  — характеристики целевой области (опционально)
    """
    feature_id: str
    direction: float                                # угол в радианах
    distance: float                                 # нормированное расстояние
    vector: FeatureVector = field(default_factory=FeatureVector)
    source_chars: Optional[RegionCharacteristics] = None
    target_chars: Optional[RegionCharacteristics] = None

    @staticmethod
    def from_regions(
        feature_id: str,
        direction: float,
        distance: float,
        source: RegionCharacteristics,
        target: RegionCharacteristics,
    ) -> Feature:
        """Создать признак из двух областей."""
        return Feature(
            feature_id=feature_id,
            direction=direction,
            distance=distance,
            vector=source.delta(target),
            source_chars=source,
            target_chars=target,
        )

    def matches(self, other: Feature, tolerance: float = 0.3) -> bool:
        """
        Совпадение признаков — основа для обобщения.
        Сравниваем только вектор изменений (инвариантный к позиции).
        """
        return self.vector.matches(other.vector, tolerance)
