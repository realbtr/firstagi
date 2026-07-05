"""
core/question_trace.py — Двойная запись вопроса и рефлексия формулировок.

QuestionTrace  : логическая форма + нарративная форма + результат.
QuestionReflection: оценка качества одного trace после получения ответа.
VoiceMemory    : растущая память об удачных формулировках.

Цикл:
  1. Системный вопрос (logical_form)  →  нарративный voice (narrative_form)
  2. Задать вопрос → получить ответ → скормить модели
  3. Замерить gen_delta = gen_count_after − gen_count_before
  4. Сохранить QuestionTrace в VoiceMemory
  5. Хорошие паттерны поднимаются в рейтинге → влияют на будущие формулировки

Использование:
    from core.question_trace import QuestionTrace, VoiceMemory

    memory = VoiceMemory()

    # до вопроса
    trace = QuestionTrace.begin(
        logical_form="что идёт после «мёд»?",
        narrative_form="— а мёд откуда? — думал Медведь.",
        char_name="медведь",
        role="EXPLORER",
        gen_count_before=127,
    )

    # после ответа
    trace.finish(gen_count_after=134, answer_tokens=["мёд", "собирают", "пчёлы"])
    memory.record(trace)

    print(memory.stats())
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ══════════════════════════════════════════════════════════════════════
# QuestionTrace
# ══════════════════════════════════════════════════════════════════════

@dataclass
class QuestionTrace:
    """
    Двойная запись одного обращения к внешнему агенту.

    Атрибуты
    --------
    logical_form    : сухой, технический вопрос (от системного драйвера)
    narrative_form  : тот же вопрос в голосе персонажа / живом регистре
    char_name       : имя персонажа, чьим голосом озвучен вопрос
    role            : архетип роли (_VoiceRole.name: EXPLORER / GIVER / …)
    gen_count_before: размер Gen-базы до вопроса
    asked_at        : UNIX-время момента вопроса
    answer_tokens   : токены ответа (заполняются после finish())
    gen_count_after : размер Gen-базы после скармливания ответа
    scored_at       : UNIX-время момента оценки
    """

    logical_form:     str
    narrative_form:   str
    char_name:        str
    role:             str                          # _VoiceRole.name
    gen_count_before: int
    asked_at:         float = field(default_factory=time.time)

    # заполняются после finish()
    answer_tokens:   List[str] = field(default_factory=list)
    gen_count_after: int       = 0
    scored_at:       float     = 0.0

    # ── Фабрика ───────────────────────────────────────────────────────

    @classmethod
    def begin(
        cls,
        logical_form:     str,
        narrative_form:   str,
        char_name:        str,
        role:             str,
        gen_count_before: int,
    ) -> "QuestionTrace":
        """Создать trace в момент постановки вопроса."""
        return cls(
            logical_form=logical_form,
            narrative_form=narrative_form,
            char_name=char_name,
            role=role,
            gen_count_before=gen_count_before,
        )

    # ── Заполнение результата ─────────────────────────────────────────

    def finish(
        self,
        gen_count_after: int,
        answer_tokens:   Optional[List[str]] = None,
    ) -> "QuestionTrace":
        """
        Зафиксировать результат после получения и скармливания ответа.

        Возвращает self для удобства цепочки вызовов.
        """
        self.gen_count_after = gen_count_after
        self.answer_tokens   = list(answer_tokens or [])
        self.scored_at       = time.time()
        return self

    # ── Метрики ───────────────────────────────────────────────────────

    @property
    def is_scored(self) -> bool:
        """True если finish() уже вызван."""
        return self.scored_at > 0.0

    @property
    def gen_delta(self) -> int:
        """Прирост Gen-базы после ответа (может быть 0 если не оценён)."""
        return max(0, self.gen_count_after - self.gen_count_before)

    @property
    def quality_score(self) -> float:
        """
        Качество формулировки: [0, 1].

        Основана на gen_delta — чем больше новых Gen закрепилось,
        тем лучше вопрос «попал в точку».

        Шкала:
          delta = 0    → 0.0  (ответ ничего не добавил)
          delta = 1–2  → 0.1–0.2  (слабый сигнал)
          delta = 5    → 0.5
          delta ≥ 10   → 1.0
        """
        if not self.is_scored:
            return 0.0
        delta = self.gen_delta
        if delta <= 0:
            return 0.0
        return min(1.0, delta / 10.0)

    @property
    def narrative_overlap(self) -> float:
        """
        Доля слов нарративной формы, встреченных в ответе.

        Показывает, насколько живой голос «попал» в язык ответа.
        """
        if not self.answer_tokens:
            return 0.0
        narrative_words = set(
            w.lower().strip(".,!?—»«") for w in self.narrative_form.split()
            if len(w) >= 3
        )
        answer_words = set(t.lower() for t in self.answer_tokens)
        if not narrative_words:
            return 0.0
        return len(narrative_words & answer_words) / len(narrative_words)

    def summary(self) -> str:
        """Однострочное описание для лога."""
        if not self.is_scored:
            return (f"[pending] {self.char_name}/{self.role}: "
                    f"«{self.narrative_form[:50]}»")
        return (
            f"[{self.role}/{self.char_name}] "
            f"Δgen={self.gen_delta:+d}  q={self.quality_score:.2f}  "
            f"overlap={self.narrative_overlap:.2f}  "
            f"«{self.narrative_form[:40]}»"
        )


# ══════════════════════════════════════════════════════════════════════
# VoiceMemory
# ══════════════════════════════════════════════════════════════════════

class VoiceMemory:
    """
    Растущая память об удачных формулировках вопросов.

    Хранит последние N QuestionTrace и предоставляет статистику:
    - какие роли приносят наибольший gen_delta;
    - какие нарративные паттерны работали лучше всего;
    - общее качество голосовых формулировок.

    Пример использования::

        memory = VoiceMemory(max_traces=100)
        memory.record(trace)
        print(memory.stats())
        best = memory.best_for_role("EXPLORER")
    """

    def __init__(self, max_traces: int = 200) -> None:
        self._traces: List[QuestionTrace] = []
        self._max = max_traces

    # ── Запись ────────────────────────────────────────────────────────

    def record(self, trace: QuestionTrace) -> None:
        """Добавить trace в память (FIFO при превышении лимита)."""
        self._traces.append(trace)
        if len(self._traces) > self._max:
            self._traces.pop(0)

    # ── Выборки ───────────────────────────────────────────────────────

    def all_scored(self) -> List[QuestionTrace]:
        """Все оценённые (finish() вызван) traces, от лучшего к худшему."""
        scored = [t for t in self._traces if t.is_scored]
        scored.sort(key=lambda t: -t.quality_score)
        return scored

    def best_for_role(
        self,
        role: str,
        top_n: int = 3,
        min_quality: float = 0.1,
    ) -> List[QuestionTrace]:
        """
        Лучшие traces для данной роли.

        Parameters
        ----------
        role        : имя роли (_VoiceRole.name), напр. "EXPLORER"
        top_n       : сколько вернуть
        min_quality : минимальный порог quality_score
        """
        candidates = [
            t for t in self._traces
            if t.role == role and t.quality_score >= min_quality
        ]
        candidates.sort(key=lambda t: -t.quality_score)
        return candidates[:top_n]

    def best_for_char(
        self,
        char_name: str,
        top_n: int = 3,
    ) -> List[QuestionTrace]:
        """Лучшие traces для конкретного персонажа."""
        candidates = [
            t for t in self._traces
            if t.char_name.lower() == char_name.lower() and t.is_scored
        ]
        candidates.sort(key=lambda t: -t.quality_score)
        return candidates[:top_n]

    def recent(self, n: int = 10) -> List[QuestionTrace]:
        """Последние N traces (включая неоценённые)."""
        return self._traces[-n:]

    # ── Статистика ────────────────────────────────────────────────────

    def stats(self) -> Dict:
        """
        Сводка по всей памяти.

        Возвращает dict с ключами:
          total, scored, avg_quality, best_role, avg_gen_delta,
          avg_overlap, role_scores {role: avg_quality}
        """
        total  = len(self._traces)
        scored = [t for t in self._traces if t.is_scored]
        if not scored:
            return {
                "total":       total,
                "scored":      0,
                "avg_quality": 0.0,
                "best_role":   None,
                "avg_gen_delta": 0.0,
                "avg_overlap": 0.0,
                "role_scores": {},
            }

        avg_q     = sum(t.quality_score for t in scored) / len(scored)
        avg_delta = sum(t.gen_delta      for t in scored) / len(scored)
        avg_ov    = sum(t.narrative_overlap for t in scored) / len(scored)

        # По ролям
        roles: Dict[str, List[float]] = {}
        for t in scored:
            roles.setdefault(t.role, []).append(t.quality_score)
        role_scores = {r: round(sum(qs) / len(qs), 3) for r, qs in roles.items()}
        best_role   = max(role_scores, key=role_scores.get) if role_scores else None

        return {
            "total":         total,
            "scored":        len(scored),
            "avg_quality":   round(avg_q, 3),
            "best_role":     best_role,
            "avg_gen_delta": round(avg_delta, 2),
            "avg_overlap":   round(avg_ov, 3),
            "role_scores":   role_scores,
        }

    def role_ranking(self) -> List[tuple]:
        """
        Отсортированный список (role, avg_quality) от лучшего к худшему.
        Удобно для отображения в TUI.
        """
        role_scores = self.stats().get("role_scores", {})
        return sorted(role_scores.items(), key=lambda x: -x[1])

    def __len__(self) -> int:
        return len(self._traces)

    def __repr__(self) -> str:
        s = self.stats()
        return (
            f"VoiceMemory(total={s['total']}, scored={s['scored']}, "
            f"avg_q={s['avg_quality']}, best_role={s['best_role']})"
        )
