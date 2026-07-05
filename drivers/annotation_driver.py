"""
drivers/annotation_driver.py — Драйвер эмоциональной разметки учителя.

«Костыль» для зеркальной нейронной сети:
  Учитель помечает: «это нравится» / «это не нравится» / «без внимания».
  Модель интерпретирует разметку как эмоциональный контекст.
  Со временем формируются обобщения, которые управляют поведением нативно.

Принцип:
  1. Учитель даёт разметку (word → +1 / -1 / 0)
  2. Разметка влияет на вычисление валентности в EmotionDriver
  3. Модель «учится» эмоциям через подражание
  4. Когда модель начинает сама предсказывать валентность →
     разметка учителя больше не нужна (модель усвоила)

Иерархия:
  Level 0: Учитель размечает (костыль)
  Level 1: Модель интерпретирует (подражание)
  Level 2: Модель предсказывает (интуиция)
  Level 3: Модель управляет нативно (внутренний голос)

Использование:
    ann = AnnotationDriver()
    ann.annotate("помогла", +1)
    ann.annotate("обидела", -1)
    ann.annotate("пошла", 0)
    valence = ann.get_valence("помогла")  # +1.0
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ══════════════════════════════════════════════════════════════════════
# Аннотация
# ══════════════════════════════════════════════════════════════════════

@dataclass
class Annotation:
    """Одна аннотация учителя."""
    word: str
    valence: float       # +1.0 (нравится) / -1.0 (не нравится) / 0.0 (нейтрально)
    confidence: float    # уверенность учителя (0-1)
    source: str          # «teacher» / «auto» / «inferred»
    count: int = 1       # сколько раз дана эта аннотация


# ══════════════════════════════════════════════════════════════════════
# AnnotationDriver
# ══════════════════════════════════════════════════════════════════════

class AnnotationDriver:
    """
    Драйвер эмоциональной разметки учителя.

    Хранит аннотации и предоставляет:
      - get_valence(word) → средняя валентность
      - get_annotation(word) → полная аннотация
      - infer_valence(word) → предсказанная валентность (на основе похожих слов)
      - annotate(word, valence, confidence) → добавить аннотацию
      - export_annotations() → все аннотации для анализа
    """

    def __init__(self) -> None:
        # word → Annotation (последняя аннотация)
        self._annotations: Dict[str, Annotation] = {}
        # word → [valence_values] (все аннотации для скользящего среднего)
        self._history: Dict[str, List[float]] = defaultdict(list)
        # inferred_valence: word → valence (предсказанная из контекста)
        self._inferred: Dict[str, float] = {}

    # ------------------------------------------------------------------
    # Аннотирование
    # ------------------------------------------------------------------

    def annotate(
        self,
        word: str,
        valence: float,
        confidence: float = 1.0,
        source: str = "teacher",
    ) -> Annotation:
        """
        Добавить аннотацию для слова.

        valence: +1.0 (нравится) / -1.0 (не нравится) / 0.0 (нейтрально)
        confidence: уверенность учителя (0-1)
        source: «teacher» (учитель) / «auto» (автоматически) / «inferred» (выведено)
        """
        word_lower = word.lower()
        valence = max(-1.0, min(1.0, valence))

        existing = self._annotations.get(word_lower)
        if existing:
            # Обновить: скользящее среднее
            n = existing.count
            new_val = existing.valence * n / (n + 1) + valence / (n + 1)
            existing.valence = round(new_val, 3)
            existing.count += 1
            existing.confidence = max(existing.confidence, confidence)
        else:
            self._annotations[word_lower] = Annotation(
                word=word_lower,
                valence=valence,
                confidence=confidence,
                source=source,
            )

        self._history[word_lower].append(valence)
        return self._annotations[word_lower]

    def batch_annotate(self, annotations: Dict[str, float]) -> int:
        """
        Пакетное аннотирование.

        annotations: {"помогла": +1, "обидела": -1, "пошла": 0}
        Возвращает количество аннотаций.
        """
        count = 0
        for word, valence in annotations.items():
            self.annotate(word, valence)
            count += 1
        return count

    # ------------------------------------------------------------------
    # Получение валентности
    # ------------------------------------------------------------------

    def get_valence(self, word: str) -> float:
        """Получить аннотированную валентность слова."""
        ann = self._annotations.get(word.lower())
        if ann:
            return ann.valence
        # Проверить inferred
        return self._inferred.get(word.lower(), 0.0)

    def get_annotation(self, word: str) -> Optional[Annotation]:
        """Получить полную аннотацию слова."""
        return self._annotations.get(word.lower())

    def has_annotation(self, word: str) -> bool:
        """Проверить, есть ли аннотация для слова."""
        return word.lower() in self._annotations

    # ------------------------------------------------------------------
    # Вывод валентности (inference)
    # ------------------------------------------------------------------

    def infer_valence(self, word: str) -> float:
        """
        Вывести валентность слова на основе похожих аннотированных слов.

        Простая эвристика: если слово похоже на аннотированное
        (общий корень, похожее начало) → унаследовать валентность.
        """
        word_lower = word.lower()

        # Точное совпадение
        if word_lower in self._inferred:
            return self._inferred[word_lower]

        # Поиск по префиксу (общий корень)
        matches = []
        for ann_word, ann in self._annotations.items():
            if ann_word.startswith(word_lower[:3]) or word_lower.startswith(ann_word[:3]):
                matches.append(ann.valence)

        if matches:
            avg = sum(matches) / len(matches)
            self._inferred[word_lower] = round(avg, 3)
            return self._inferred[word_lower]

        return 0.0

    # ------------------------------------------------------------------
    # Экспорт и статистика
    # ------------------------------------------------------------------

    def export_annotations(self) -> List[Dict]:
        """Экспорт всех аннотаций для анализа."""
        return [
            {
                "word": ann.word,
                "valence": ann.valence,
                "confidence": ann.confidence,
                "source": ann.source,
                "count": ann.count,
            }
            for ann in sorted(self._annotations.values(), key=lambda a: -abs(a.valence))
        ]

    def positive_words(self, min_valence: float = 0.3) -> List[str]:
        """Слова с позитивной аннотацией."""
        return [ann.word for ann in self._annotations.values()
                if ann.valence >= min_valence]

    def negative_words(self, max_valence: float = -0.3) -> List[str]:
        """Слова с негативной аннотацией."""
        return [ann.word for ann in self._annotations.values()
                if ann.valence <= max_valence]

    def stats(self) -> Dict:
        """Статистика аннотаций."""
        total = len(self._annotations)
        positive = sum(1 for a in self._annotations.values() if a.valence > 0.1)
        negative = sum(1 for a in self._annotations.values() if a.valence < -0.1)
        neutral = total - positive - negative

        return {
            "total": total,
            "positive": positive,
            "negative": negative,
            "neutral": neutral,
            "inferred": len(self._inferred),
        }

    def __repr__(self) -> str:
        s = self.stats()
        return (
            f"AnnotationDriver("
            f"total={s['total']}, "
            f"+{s['positive']}, "
            f"-{s['negative']})"
        )
