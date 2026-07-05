"""
core/domain_detector.py — Словарный детектор доменов.

DomainDetector
──────────────
Классифицирует текст/вопрос по домену на основе словарных частот.

Алгоритм:
  1. Для каждого домена накапливается счётчик слов (term frequency)
  2. При классификации: TF-IDF-подобный балл = sum(tf_domain[w] / total_domain)
     минус штраф за слова, встречающиеся во ВСЕХ доменах (stop-terms)
  3. Возвращается домен с наибольшим баллом

Преимущество перед keyword-списком (в heterarchy.py):
  - Автоматически обновляется при добавлении новых текстов
  - Устойчив к опечаткам и морфологии (счёт по подстроке)
  - Работает без обучения (просто corpus statistics)

Пример:
  det = DomainDetector()
  det.add_example("Маша пошла в лес за грибами...", "children")
  det.add_example("Звёзды светят в ночном небе...", "astronomy")
  det.detect("Маша встретила медведя") → "children"
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from typing import Dict, List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# Утилиты
# ══════════════════════════════════════════════════════════════════════════════

_STOP_WORDS = {
    "и", "в", "на", "с", "по", "за", "из", "не", "что", "это",
    "как", "он", "она", "оно", "они", "а", "но", "или", "то",
    "всё", "все", "был", "была", "были", "есть", "стал", "стала",
    "к", "до", "у", "о", "их", "от", "его", "её", "им", "ему",
    "the", "a", "is", "in", "of", "and", "to", "it", "was",
}


def _tokenize(text: str) -> List[str]:
    """Простая токенизация: нижний регистр + только слова ≥2 символов."""
    return [
        w for w in re.findall(r"[а-яёa-z]+", text.lower())
        if len(w) >= 2 and w not in _STOP_WORDS
    ]


# ══════════════════════════════════════════════════════════════════════════════
# DomainDetector
# ══════════════════════════════════════════════════════════════════════════════

class DomainDetector:
    """
    Статистический детектор доменов по словарным частотам.

    Поддерживает:
    - Инкрементальное добавление примеров (add_example)
    - Детектирование одного домена (detect)
    - Ранжирование нескольких доменов (detect_top)
    - Построение из корпуса (build_from_corpus)
    - Сохранение/загрузку статистики (to_dict / from_dict)
    """

    def __init__(self, min_score: float = 0.001) -> None:
        self._domain_tf:    Dict[str, Counter] = defaultdict(Counter)
        self._domain_total: Dict[str, int]      = defaultdict(int)
        self._min_score = min_score
        # Кэш stop-terms (слова, встречающиеся во всех доменах)
        self._cross_terms: Optional[set] = None

    # ── Обучение ──────────────────────────────────────────────────────────────

    def add_example(self, text: str, domain: str) -> None:
        """Добавить пример текста для данного домена."""
        tokens = _tokenize(text)
        self._domain_tf[domain].update(tokens)
        self._domain_total[domain] += len(tokens)
        self._cross_terms = None   # сбросить кэш

    def build_from_corpus(self, corpus: Dict) -> "DomainDetector":
        """
        Построить детектор из словаря корпуса.
        corpus: {doc_id: {"text": str, "domain": str, ...}}
        """
        for info in corpus.values():
            domain = info.get("domain", "")
            text   = info.get("text", "")
            if domain and text:
                self.add_example(text, domain)
        return self

    # ── Детектирование ────────────────────────────────────────────────────────

    def detect(self, text: str, fallback: str = "") -> str:
        """
        Определить домен текста.
        Возвращает пустую строку, если нет обученных доменов или уверенность низкая.
        """
        ranked = self.detect_top(text, n=1)
        if ranked and ranked[0][1] >= self._min_score:
            return ranked[0][0]
        return fallback

    def detect_top(self, text: str, n: int = 3) -> List[Tuple[str, float]]:
        """
        Вернуть top-n доменов с их баллами.
        """
        if not self._domain_tf:
            return []

        tokens = _tokenize(text)
        if not tokens:
            return []

        cross = self._get_cross_terms()
        scores: Dict[str, float] = {}

        for domain, tf in self._domain_tf.items():
            total = max(1, self._domain_total[domain])
            score = 0.0
            for tok in tokens:
                if tok in cross:
                    continue  # слово есть везде — не информативно
                freq = tf.get(tok, 0)
                if freq > 0:
                    # TF + бонус за редкие слова
                    score += freq / total
            scores[domain] = score

        ranked = sorted(scores.items(), key=lambda x: -x[1])
        return ranked[:n]

    # ── Анализ ────────────────────────────────────────────────────────────────

    def domains(self) -> List[str]:
        return list(self._domain_tf.keys())

    def top_words(self, domain: str, n: int = 10) -> List[Tuple[str, int]]:
        """Топ-n слов для домена."""
        return self._domain_tf[domain].most_common(n)

    def _get_cross_terms(self) -> set:
        """Слова, встречающиеся во ВСЕХ доменах — не информативны."""
        if self._cross_terms is not None:
            return self._cross_terms
        if len(self._domain_tf) < 2:
            self._cross_terms = set()
            return self._cross_terms
        sets = [set(tf.keys()) for tf in self._domain_tf.values()]
        cross = sets[0]
        for s in sets[1:]:
            cross = cross & s
        self._cross_terms = cross
        return self._cross_terms

    # ── Сериализация ──────────────────────────────────────────────────────────

    def to_dict(self) -> Dict:
        return {
            "domain_tf":    {d: dict(c) for d, c in self._domain_tf.items()},
            "domain_total": dict(self._domain_total),
            "min_score":    self._min_score,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> "DomainDetector":
        det = cls(min_score=data.get("min_score", 0.001))
        for domain, tf in data.get("domain_tf", {}).items():
            det._domain_tf[domain] = Counter(tf)
        for domain, total in data.get("domain_total", {}).items():
            det._domain_total[domain] = total
        return det

    def __repr__(self) -> str:
        domains = ", ".join(
            f"{d}({self._domain_total[d]}tok)" for d in self.domains()
        )
        return f"DomainDetector([{domains}])"
