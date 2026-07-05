"""
core/exploration.py — Стратегия исследования корпуса и цепочки зондирования.

ExplorationPolicy
─────────────────
Управляет тем, КАКОЙ из найденных фрагментов выбрать.
Приоритизирует новизну (мало посещённые абзацы) + информационную ценность
(энтропия токенов фрагмента ≈ логарифм числа редких слов).

Критерий выбора: score = novelty * entropy_bonus
  novelty        = 1 / (1 + visit_count[doc_id][para_idx])
  entropy_bonus  = 1 + log(1 + редких слов в фрагменте) / 3

ProbeChain
──────────
Модель НЕ сразу читает весь фрагмент — сначала проверяет гипотезу:
  1. anchor_probe     — убедиться, что первое слово шаблона — нужное
  2. required_probes  — проверить N ключевых слов с минимальным сдвигом
  3. При первом критическом промахе → abort (не тратить токены на чтение)
  4. При успехе всех проб → read_fragment → feed

Это аналог предварительного просмотра: «открыть страницу, найти глаза,
убедиться что тема та» — только тогда читать.
"""
from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from core.query_builder import LeakyTemplate


# ══════════════════════════════════════════════════════════════════════════════
# ExplorationPolicy
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class VisitRecord:
    count:      int   = 0
    last_score: float = 0.0


class ExplorationPolicy:
    """
    Политика исследования корпуса.

    Ключевые идеи:
    - Новые/редко посещённые абзацы предпочтительнее
    - Фрагменты с редкими словами несут больше информации
    - Глобальный словарный счётчик накапливается между визитами
    """

    def __init__(self, revisit_penalty: float = 0.5) -> None:
        self._visits: Dict[Tuple[str, int], VisitRecord] = defaultdict(VisitRecord)
        self._word_freq: Dict[str, int] = defaultdict(int)
        self._total_tokens: int = 0
        self._revisit_penalty = revisit_penalty  # коэффициент штрафа при повторе

    # ── Обновление статистики ─────────────────────────────────────────────────

    def record_visit(self, doc_id: str, para_idx: int, tokens: List[str]) -> None:
        """Записать визит и обновить частоты слов."""
        key = (doc_id, para_idx)
        self._visits[key].count += 1
        for tok in tokens:
            self._word_freq[tok.lower()] += 1
        self._total_tokens += len(tokens)

    # ── Оценка и выбор ────────────────────────────────────────────────────────

    def score_match(self, doc_id: str, para_idx: int, fragment_tokens: List[str]) -> float:
        """
        Оценить привлекательность данного фрагмента.
        Высокий балл → стоит посетить.
        """
        key = (doc_id, para_idx)
        visit_count = self._visits[key].count

        # Новизна: уменьшается с каждым повтором
        novelty = 1.0 / (1.0 + visit_count * self._revisit_penalty)

        # Энтропийный бонус: доля редких слов в фрагменте
        if not fragment_tokens or self._total_tokens == 0:
            entropy_bonus = 1.0
        else:
            rare_count = sum(
                1 for t in fragment_tokens
                if self._word_freq.get(t.lower(), 0) <= 1
            )
            ratio = rare_count / len(fragment_tokens)
            entropy_bonus = 1.0 + math.log(1.0 + ratio * len(fragment_tokens)) / 3.0

        score = novelty * entropy_bonus
        self._visits[key].last_score = score
        return score

    def select(
        self,
        matches: List,  # List[SearchMatch]
        corpus: Dict,   # doc_id → CorpusEntry
        top_k: int = 1,
    ) -> List:
        """
        Выбрать top_k наиболее привлекательных совпадений.
        Если corpus передан — используем токены абзаца для энтропийного бонуса.
        """
        if not matches:
            return []

        scored = []
        for m in matches:
            doc = corpus.get(m.doc_id)
            tokens: List[str] = []
            if doc:
                paras = [p for p in doc.paragraphs if p.idx == m.para_idx]
                if paras:
                    tokens = paras[0].tokens
            sc = self.score_match(m.doc_id, m.para_idx, tokens)
            scored.append((sc, m))

        scored.sort(key=lambda x: -x[0])
        return [m for _, m in scored[:top_k]]

    # ── Статистика ────────────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict:
        total_visits = sum(v.count for v in self._visits.values())
        # Считаем только реально посещённые (count > 0), не Score-created записи
        unique_paras = sum(1 for v in self._visits.values() if v.count > 0)
        return {
            "total_visits":  total_visits,
            "unique_paras":  unique_paras,
            "vocab_size":    len(self._word_freq),
            "total_tokens":  self._total_tokens,
            "revisit_rate":  (total_visits - unique_paras) / max(1, total_visits),
        }

    def visit_map(self) -> Dict[Tuple[str, int], int]:
        """Карта посещений: (doc_id, para_idx) → count (только реально посещённые)."""
        return {k: v.count for k, v in self._visits.items() if v.count > 0}


# ══════════════════════════════════════════════════════════════════════════════
# ProbeChain
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProbeStep:
    """Один шаг в цепочке зондирования."""
    expected:  str
    delta:     int       # смещение относительно начала фрагмента (anchor)
    critical:  bool = True  # при промахе → abort вся цепочка?


@dataclass
class ProbeChainResult:
    """Итог цепочки зондирования."""
    passed:        bool           # все критические пробы прошли?
    steps_run:     int            # сколько шагов выполнено
    steps_passed:  int            # сколько шагов дали hit
    abort_reason:  str = ""       # имя шага, который вызвал abort
    confidence:    float = 0.0    # среднее от успешных шагов


class ProbeChain:
    """
    Цепочка целевых зондирований для проверки гипотезы о фрагменте.

    Вместо того, чтобы читать весь фрагмент, модель сначала:
    1. Находит anchor (первое конкретное слово шаблона)
    2. Проверяет ряд ожидаемых токенов в их предполагаемых позициях
    3. Только при успехе — запрашивает полный fragment

    Это экономит Gen-бюджет: не тратим обучение на нерелевантный текст.
    """

    def __init__(self, steps: Optional[List[ProbeStep]] = None) -> None:
        self._steps: List[ProbeStep] = steps or []

    @classmethod
    def from_template(cls, template: LeakyTemplate, max_steps: int = 4) -> "ProbeChain":
        """
        Автоматически построить цепочку зондирования из LeakyTemplate.
        Anchor-слот → первый шаг (delta=0), required-слоты → последующие.
        """
        steps: List[ProbeStep] = []
        delta = 0
        for i, slot in enumerate(template.slots):
            if not slot.words:
                # wildcard — пропустить max_gap позиций
                delta += max(1, slot.max_gap)
                continue
            word = slot.words[0]
            is_anchor = (slot.kind == "anchor" or i == 0)
            steps.append(ProbeStep(
                expected = word,
                delta    = delta,
                critical = is_anchor,   # только anchor критичен
            ))
            delta += 1 + slot.max_gap   # следующий шаг с учётом возможного разрыва
            if len(steps) >= max_steps:
                break
        return cls(steps)

    def add_step(self, expected: str, delta: int, critical: bool = True) -> "ProbeChain":
        self._steps.append(ProbeStep(expected=expected, delta=delta, critical=critical))
        return self

    def run(self, server, anchor_delta: int = 0) -> ProbeChainResult:
        """
        Запустить цепочку зондирования против текущей позиции сервера.
        server — ActiveTextServer с методом probe(expected, delta).

        anchor_delta: начальное смещение от cursor к предполагаемой позиции anchor.
        """
        if not self._steps:
            return ProbeChainResult(passed=True, steps_run=0, steps_passed=0, confidence=1.0)

        hits = 0
        for i, step in enumerate(self._steps):
            effective_delta = anchor_delta + step.delta
            result = server.probe(step.expected, delta=effective_delta)
            if result.hit:
                hits += 1
            elif step.critical:
                return ProbeChainResult(
                    passed       = False,
                    steps_run    = i + 1,
                    steps_passed = hits,
                    abort_reason = f"step[{i}]={step.expected}@δ{effective_delta}",
                    confidence   = hits / (i + 1) if i > 0 else 0.0,
                )

        confidence = hits / len(self._steps)
        return ProbeChainResult(
            passed       = True,
            steps_run    = len(self._steps),
            steps_passed = hits,
            confidence   = confidence,
        )

    def __len__(self) -> int:
        return len(self._steps)

    def __repr__(self) -> str:
        s = ", ".join(f"{st.expected}@δ{st.delta}{'!' if st.critical else ''}" for st in self._steps)
        return f"ProbeChain([{s}])"
