r"""
core/query_builder.py — «Дырявые шаблоны»: перевод состояния Gen-системы в поисковые запросы.

Модель не знает regex. Она знает свои Gen-цепочки. QueryBuilder переводит внутреннее
состояние LearningSystem → LeakyTemplate → regex / FTS5 / смещение курсора.

Концепция
─────────
1. Активные/недавно подтверждённые Gen с высокой significance → «известные» слоты
2. Пробелы в цепочке (REFUTED, EXPLORING) → wildcards
3. Anchor = первое высоко-значимое слово в шаблоне → точка входа в поиск
4. Глубокие Gen (L2+) → жёсткие якоря; L1 с sig<0.5 → wildcards

Пример
──────
Gen-система видела: "маша" → "медведь" → "пирог" (sig=0.9) + "медведь" → "праздник" (sig=0.7)
Запрос: r"маша\s+(?:\w+\s+){0,2}медведь\s+(?:\w+\s+){0,3}(?:пирог|праздник)"
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ══════════════════════════════════════════════════════════════════════════════
# Структуры данных
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class TemplateSlot:
    """Один слот в шаблоне."""
    kind: str            # "anchor" | "required" | "alternative" | "wildcard"
    words: List[str]     # конкретные слова (пусто для wildcard)
    max_gap: int = 0     # max слов-wildcard ДО этого слота
    min_gap: int = 0     # min слов-wildcard ДО этого слота

    @property
    def is_known(self) -> bool:
        return bool(self.words)


@dataclass
class LeakyTemplate:
    """
    Дырявый шаблон — то что модель ищет в корпусе.
    Может содержать обязательные слова, альтернативы и дырки-wildcards.
    """
    slots: List[TemplateSlot]
    source: str = ""        # откуда взят шаблон (gen_id или "question")
    confidence: float = 0.0 # суммарная уверенность

    @property
    def anchor(self) -> Optional[str]:
        """Первое конкретное слово — точка входа для поиска."""
        for s in self.slots:
            if s.words:
                return s.words[0]
        return None

    def to_regex(self, flags: re.RegexFlag = re.IGNORECASE | re.UNICODE) -> re.Pattern:
        """Скомпилировать в regex-паттерн."""
        parts = []
        for i, slot in enumerate(self.slots):
            # Разрыв-wildcard встроен в сам слот (max_gap > 0)
            gap_pattern = ""
            if slot.max_gap > 0:
                if slot.min_gap == 0:
                    gap_pattern = rf"(?:\w+\s+){{0,{slot.max_gap}}}"
                else:
                    gap_pattern = rf"(?:\w+\s+){{{slot.min_gap},{slot.max_gap}}}"

            if slot.kind == "wildcard" or not slot.words:
                word_pattern = r"\w+"
            elif len(slot.words) == 1:
                word_pattern = re.escape(slot.words[0])
            else:
                alts = "|".join(re.escape(w) for w in slot.words)
                word_pattern = f"(?:{alts})"

            if i == 0:
                parts.append(word_pattern)
            else:
                # Всегда нужен хотя бы один пробел между словами,
                # gap_pattern добавляет ДОПОЛНИТЕЛЬНЫЕ слова (0..N)
                if gap_pattern:
                    sep = r"\s+" + gap_pattern
                else:
                    sep = r"\s+"
                parts.append(sep + word_pattern)

        pattern = "".join(parts)
        return re.compile(pattern, flags)

    def to_fts_query(self) -> str:
        """
        Упрощённый FTS5-запрос для предфильтрации по всем известным словам.
        Возвращает строку вида: '"маша" "медведь" "пирог"'
        """
        words = []
        for slot in self.slots:
            if slot.words:
                words.append(f'"{slot.words[0]}"')
        return " ".join(words)

    def __str__(self) -> str:
        parts = []
        for slot in self.slots:
            if slot.max_gap > 0:
                parts.append(f"[…{slot.max_gap}]")
            if not slot.words:
                parts.append("[?]")
            elif len(slot.words) == 1:
                parts.append(slot.words[0])
            else:
                parts.append(f"({'/'.join(slot.words[:3])})")
        return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# Строитель шаблонов
# ══════════════════════════════════════════════════════════════════════════════

class QueryBuilder:
    """
    Переводит состояние LearningSystem → List[LeakyTemplate].

    Стратегии
    ─────────
    build_from_active_gen   — из активных Gen в контексте
    build_from_pattern_q    — из вопроса-расширения («кто ещё X Y?»)
    build_from_gap_q        — из вопроса о пробеле («что дальше после X?»)
    build_from_cluster_q    — из вопроса об именовании («как называется X,Y,Z?»)
    """

    # Пороги значимости для включения в шаблон
    ANCHOR_SIG    = 0.70   # Gen с sig>=0.70 → anchor/required
    REQUIRED_SIG  = 0.40   # Gen с sig>=0.40 → required
    ALT_SIG       = 0.20   # Gen с sig>=0.20 → alternative

    def __init__(self, max_gap: int = 3, max_alternatives: int = 4) -> None:
        self._max_gap = max_gap
        self._max_alts = max_alternatives

    # ── Из активных Gen ───────────────────────────────────────────────────────

    def build_from_active_gen(self, system) -> List[LeakyTemplate]:
        """
        Построить шаблоны из активных Gen в контексте.
        Если контекст пуст — брать топ-5 Gen по significance из базы.
        """
        ctx  = system.engine.context
        base = system.base

        # Собрать активные Gen
        infos = []
        for gid in list(ctx._active.keys()):
            g = base.get(gid)
            if g and g.label and g.significance >= self.ALT_SIG:
                infos.append(g)

        # Если контекст пуст — взять самые знакомые Gen из базы
        # (даже с sig=0 — просто часто встречавшиеся, судим по success+stop)
        if not infos:
            all_gens = [
                base.get(gid) for gid in list(base._gens.keys())
                if base.get(gid) and base.get(gid).label
            ]
            all_gens.sort(key=lambda g: -(g.success_count + g.stop_count))
            infos = [g for g in all_gens[:6] if g]

        if not infos:
            return []

        infos.sort(key=lambda g: -g.significance)

        templates: List[LeakyTemplate] = []

        # Шаблон 1: все альтернативы одного токена (ближайший прогноз)
        labels_seen = {}
        for g in infos:
            labels_seen.setdefault(g.label.lower(), []).append(g)

        if labels_seen:
            # Один слот с альтернативными словами
            all_words = list(labels_seen.keys())[: self._max_alts]
            sig = max(g.significance for gs in labels_seen.values() for g in gs)
            templates.append(LeakyTemplate(
                slots=[TemplateSlot(
                    kind  = "anchor" if sig >= self.ANCHOR_SIG else "alternative",
                    words = all_words,
                )],
                source     = "active_gen",
                confidence = sig,
            ))

        # Шаблон 2: расширенный — anchor + ближайший высокий Gen в базе
        anchor_gen = infos[0]
        deep = self._find_deep_continuation(anchor_gen, base)
        if deep:
            slots = [
                TemplateSlot(kind="anchor", words=[anchor_gen.label.lower()]),
            ]
            for cont_label in deep[:2]:
                slots.append(TemplateSlot(
                    kind="required", words=[cont_label],
                    max_gap=self._max_gap, min_gap=0,
                ))
            templates.append(LeakyTemplate(
                slots      = slots,
                source     = f"deep:{anchor_gen.gen_id[:8]}",
                confidence = anchor_gen.significance,
            ))

        return templates

    # ── Из вопросов ───────────────────────────────────────────────────────────

    def build_from_pattern_q(self, question: str) -> Optional[LeakyTemplate]:
        """
        «Кто ещё принёс маше?» →
          [?] принёс [wildcard] маше
        """
        tokens = question.lower().replace("?", "").split()
        if not tokens:
            return None
        # Убрать вопросительные слова в начале
        skip = {"кто", "что", "где", "как", "ещё", "еще", "может"}
        content = [t for t in tokens if t not in skip]
        if len(content) < 2:
            return None

        slots: List[TemplateSlot] = [
            TemplateSlot(kind="wildcard", words=[], max_gap=self._max_gap),
        ]
        for i, word in enumerate(content):
            slots.append(TemplateSlot(
                kind    = "required",
                words   = [word],
                max_gap = self._max_gap if i > 0 else 0,
            ))
        return LeakyTemplate(slots=slots, source="pattern_q", confidence=0.5)

    def build_from_gap_q(self, question: str) -> Optional[LeakyTemplate]:
        """
        «Что дальше после принёс?» →
          принёс [wildcard]
        """
        tokens = question.lower().replace("?", "").split()
        skip = {"что", "дальше", "после", "следующее", "потом", "где"}
        content = [t for t in tokens if t not in skip]
        if not content:
            return None
        anchor = content[-1]
        return LeakyTemplate(
            slots=[
                TemplateSlot(kind="anchor", words=[anchor]),
                TemplateSlot(kind="wildcard", words=[], max_gap=self._max_gap),
            ],
            source="gap_q", confidence=0.3,
        )

    def build_from_cluster_q(self, question: str) -> Optional[LeakyTemplate]:
        """
        «Как называется группа: мёд, морковка, пирог?» →
          [?] (мёд|морковка|пирог)  (поиск общего контекста)
        """
        # Извлечь список слов после ":"
        if ":" in question:
            words_str = question.split(":", 1)[1]
        else:
            words_str = question
        words = [w.strip().strip("?.,") for w in words_str.split(",")]
        words = [w for w in words if len(w) > 1]
        if not words:
            return None

        alt_slot = TemplateSlot(
            kind="alternative",
            words=words[: self._max_alts],
        )
        return LeakyTemplate(
            slots=[alt_slot],
            source="cluster_q", confidence=0.4,
        )

    # ── Вспомогательные ───────────────────────────────────────────────────────

    def _find_deep_continuation(self, gen, base, max_depth: int = 2) -> List[str]:
        """
        Найти L2+ Gen в базе, начинающиеся с метки данного Gen.
        Вернуть список последующих слов (из метки) с sig >= REQUIRED_SIG.
        """
        if not gen.label:
            return []
        prefix = gen.label.lower()
        result = []
        for gid in list(base._gens.keys()):
            cand = base.get(gid)
            if cand is None or len(cand.feature_chain) < 2:
                continue
            if cand.significance < self.REQUIRED_SIG:
                continue
            clabel = (cand.label or "").lower()
            parts = clabel.split("·")
            if parts[0] == prefix and len(parts) >= 2:
                result.extend(parts[1: 1 + max_depth])
        # Дедуплицировать, сохраняя порядок
        seen = set()
        unique = []
        for w in result:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        return unique[: max_depth]
