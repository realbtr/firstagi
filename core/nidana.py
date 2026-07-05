"""Нидана-трасса (SPEC §1.7, v2 §C.12, задача И1-Т4 / З-0028).

Инфраструктура-логгер: такт горячего цикла проходит строго упорядоченные
стадии — они маркируются именами 12 нидан в телеметрии, чтобы чек-лист
пратитья-самутпады был исполняемым (ассерты в CI), а не визуальным.

Отображение C.12 на пайплайн LearningSystem.process_token():
  АВИДЬЯ       — зарегистрирована неопределённость (REFUTED/EXPLORING)
  САНСКАРА     — инициатива сформировала предложения ДО токена (шаг 0)
  ВИДЖНЯНА     — сырой токен получен от драйвера (вход шага 2)
  НАМАРУПА     — различию присвоен feature_id (вход шага 2)
  АЯТАНА       — активный контекст загружен, готов к сопоставлению
  СПАРША       — контакт: engine.step() сопоставил токен с ожиданиями
  ВЕДАНА       — resource_state обновлён по исходу (шаг 5 — буквально C.12;
                 до появления узлового RS6 эмитится по затронутым узлам такта)
  ТАНХА        — гедоника/инициатива отреагировали (шаги 6б/6в)
  УПАДАНА      — витальность зафиксировала удержание позиции (шаг 6г)
  БХАВА        — бифуркация: суперпозиция конкурентов не схлопнулась (шаг 9)
  ДЖАТИ        — Gen рождён / контекст зафиксирован разрешением конкуренции
  ДЖАРА-МАРАНА — Gen покинул контекст / контекст распался (REFUTED-снятие,
                 reset_context; вытеснение — при интеграции CapacityBudget)

Порядок эмиссии в реальном пайплайне даёт канонику без принуждения:
Ведана(шаг 5) < Танха(6б/6в) < Упадана(6г). CI-ассерты из v2 C.12:
  (1) для каждого узла Упадана не случается раньше его Веданы;
  (2) Джати→Джара-марана в пределах MAX_LIFETIME тактов (нет вечных циклов).
Трассер не несёт семантики — только метки, такты и ссылки.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, Dict, List, Optional

from .core_types import Nidana

MAX_LIFETIME_TICKS = 10_000   # дефолт ассерта «нет вечных циклов»


@dataclass
class NidanaEvent:
    tick: int
    node: str                        # gen_id / feature_id / "" (событие такта)
    stage: Nidana
    payload: dict = field(default_factory=dict)


class NidanaTracer:
    """Логгер NidanaEvent. enabled=False — трасса не пишется (горячий путь чист)."""

    def __init__(self, enabled: bool = True, max_events: int = 200_000) -> None:
        self.enabled = enabled
        self.events: Deque[NidanaEvent] = deque(maxlen=max_events)

    def emit(self, stage: Nidana, node: str = "", tick: int = 0, **payload) -> None:
        if not self.enabled:
            return
        self.events.append(
            NidanaEvent(tick=tick, node=node, stage=stage, payload=payload)
        )

    # ── выборки ──────────────────────────────────────────────────────
    def stages(self) -> List[Nidana]:
        return [e.stage for e in self.events]

    def events_for(self, node: str) -> List[NidanaEvent]:
        return [e for e in self.events if e.node == node]

    def count(self, stage: Nidana) -> int:
        return sum(1 for e in self.events if e.stage is stage)

    # ── CI-ассерты C.12 ──────────────────────────────────────────────
    def violations_vedana_before_upadana(self) -> List[str]:
        """(1) Упадана узла не раньше его первой Веданы (по порядку эмиссии)."""
        first_vedana: Dict[str, int] = {}
        bad: List[str] = []
        for i, e in enumerate(self.events):
            if e.stage is Nidana.VEDANA and e.node not in first_vedana:
                first_vedana[e.node] = i
            elif e.stage is Nidana.UPADANA and e.node not in first_vedana:
                bad.append(
                    f"{e.node}: Упадана (событие №{i}, такт {e.tick}) "
                    f"без предшествующей Веданы"
                )
        return bad

    def violations_jati_lifetime(
        self,
        max_lifetime: int = MAX_LIFETIME_TICKS,
        now_tick: Optional[int] = None,
    ) -> List[str]:
        """(2) Каждое Джати встречает Джара-марану узла в пределах max_lifetime."""
        births: Dict[str, int] = {}
        bad: List[str] = []
        last_tick = 0
        for e in self.events:
            last_tick = max(last_tick, e.tick)
            if e.stage is Nidana.JATI and e.node:
                births.setdefault(e.node, e.tick)
            elif e.stage is Nidana.JARA_MARANA and e.node in births:
                life = e.tick - births.pop(e.node)
                if life > max_lifetime:
                    bad.append(f"{e.node}: жизнь {life} тактов > {max_lifetime}")
        horizon = now_tick if now_tick is not None else last_tick
        for node, born in births.items():
            if horizon - born > max_lifetime:
                bad.append(
                    f"{node}: жив {horizon - born} тактов без Джара-мараны "
                    f"(> {max_lifetime})"
                )
        return bad
