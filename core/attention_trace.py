"""Трасса элементарного цикла внимания (SPEC §1.7, v2 §C.12, И1-Т4 / З-0028, З-0029).

Инфраструктура-логгер: такт горячего цикла проходит строго упорядоченные
стадии AttentionStage — инженерные события с инженерными именами.

Отображение на пайплайн LearningSystem.process_token():
  UNCERTAINTY      — исход REFUTED/EXPLORING: неопределённость зарегистрирована
  PROBE_IMPULSE    — инициатива сформировала предложения ДО токена (шаг 0)
  SIGNAL_IN        — сырой токен получен от драйвера (вход шага 2)
  DISTINCTION      — различию присвоен feature_id (вход шага 2)
  CONTEXT_READY    — активный контекст загружен, готов к сопоставлению
  CONTACT          — engine.step() сопоставил токен с ожиданиями
  EVALUATION       — resource_state обновлён по исходу (шаг 5); до появления
                     узлового RS6 эмитится по затронутым узлам такта
  DRIVE            — гедоника/инициатива отреагировали (шаги 6б/6в)
  RETENTION        — витальность зафиксировала удержание позиции (шаг 6г)
  SUPERPOSITION    — бифуркация: конкуренты не схлопнулись (шаг 9)
  CONTEXT_FIXATION — узел вошёл в актуальный контекст (дельта вокруг шага 2)
  CONTEXT_DECAY    — узел покинул актуальный контекст (снятие при REFUTED,
                     разрешение конкуренции, reset_context, вытеснение)

CI-ассерты порядка (v2 C.12):
  (1) EVALUATION узла прежде его RETENTION;
  (2) CONTEXT_FIXATION → CONTEXT_DECAY в пределах MAX_LIFETIME тактов
      (вечный актуальный контекст = красная сборка).
Порядок EVALUATION < DRIVE < RETENTION дан реальным порядком шагов 5→6б→6г.

КОНТРОЛЬНЫЙ СЛОЙ (правило З-0029): соответствие 12 ниданам пратитья-самутпады
вынесено в NIDANA_CORRESPONDENCE. Слой проверочный — он испытывает архитектуру
философией; термины Учения не используются как имена кода и телеметрии.
Расхождение слоя с инженерией = сигнал пересмотра (или честной фиксации
расхождения записью в журнал), а не повод переименовать сущность.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from .core_types import AttentionStage

MAX_LIFETIME_TICKS = 10_000   # дефолт ассерта «нет вечных контекстов»

# ── Контрольный слой: соответствие стадий цикла 12 ниданам (v2 C.12) ────
# Ключи обязаны покрывать ВЕСЬ enum (проверяется тестом): 12 ↔ 12.
NIDANA_CORRESPONDENCE: Dict[AttentionStage, str] = {
    AttentionStage.UNCERTAINTY:      "авидья (неведение)",
    AttentionStage.PROBE_IMPULSE:    "санскара (формирующий импульс)",
    AttentionStage.SIGNAL_IN:        "виджняна (сознавание сигнала)",
    AttentionStage.DISTINCTION:      "намарупа (имя-форма)",
    AttentionStage.CONTEXT_READY:    "аятана (опоры восприятия)",
    AttentionStage.CONTACT:          "спарша (контакт)",
    AttentionStage.EVALUATION:       "ведана (оценка-тон)",
    AttentionStage.DRIVE:            "танха (жажда)",
    AttentionStage.RETENTION:        "упадана (цепляние)",
    AttentionStage.SUPERPOSITION:    "бхава (становление)",
    AttentionStage.CONTEXT_FIXATION: "джати (рождение)",
    AttentionStage.CONTEXT_DECAY:    "джара-марана (старение-смерть)",
}


@dataclass
class AttentionEvent:
    tick: int
    node: str                        # gen_id / feature_id / "" (событие такта)
    stage: AttentionStage
    payload: dict = field(default_factory=dict)


class AttentionTracer:
    """Логгер AttentionEvent. enabled=False — трасса не пишется (горячий путь чист)."""

    def __init__(self, enabled: bool = True, max_events: int = 200_000) -> None:
        self.enabled = enabled
        self.events: Deque[AttentionEvent] = deque(maxlen=max_events)

    def emit(self, stage: AttentionStage, node: str = "", tick: int = 0,
             **payload) -> None:
        if not self.enabled:
            return
        self.events.append(
            AttentionEvent(tick=tick, node=node, stage=stage, payload=payload)
        )

    # ── выборки ──────────────────────────────────────────────────────
    def stages(self) -> List[AttentionStage]:
        return [e.stage for e in self.events]

    def events_for(self, node: str) -> List[AttentionEvent]:
        return [e for e in self.events if e.node == node]

    def count(self, stage: AttentionStage) -> int:
        return sum(1 for e in self.events if e.stage is stage)

    # ── CI-ассерты порядка (v2 C.12) ─────────────────────────────────
    def violations_evaluation_before_retention(self) -> List[str]:
        """(1) RETENTION узла не раньше его первой EVALUATION (по эмиссии)."""
        first_eval: Dict[str, int] = {}
        bad: List[str] = []
        for i, e in enumerate(self.events):
            if e.stage is AttentionStage.EVALUATION and e.node not in first_eval:
                first_eval[e.node] = i
            elif (e.stage is AttentionStage.RETENTION
                  and e.node not in first_eval):
                bad.append(
                    f"{e.node}: RETENTION (событие №{i}, такт {e.tick}) "
                    f"без предшествующей EVALUATION"
                )
        return bad

    def violations_fixation_lifetime(
        self,
        max_lifetime: int = MAX_LIFETIME_TICKS,
        now_tick: Optional[int] = None,
    ) -> List[str]:
        """(2) CONTEXT_FIXATION встречает CONTEXT_DECAY узла в пределах max_lifetime."""
        births: Dict[str, int] = {}
        bad: List[str] = []
        last_tick = 0
        for e in self.events:
            last_tick = max(last_tick, e.tick)
            if e.stage is AttentionStage.CONTEXT_FIXATION and e.node:
                births.setdefault(e.node, e.tick)
            elif e.stage is AttentionStage.CONTEXT_DECAY and e.node in births:
                life = e.tick - births.pop(e.node)
                if life > max_lifetime:
                    bad.append(f"{e.node}: в контексте {life} тактов > {max_lifetime}")
        horizon = now_tick if now_tick is not None else last_tick
        for node, born in births.items():
            if horizon - born > max_lifetime:
                bad.append(
                    f"{node}: в контексте {horizon - born} тактов без "
                    f"CONTEXT_DECAY (> {max_lifetime})"
                )
        return bad
