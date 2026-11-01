"""
Актуальный контекст (ContextBuffer) — рабочая память системы.

Хранит:
  - Активные обобщения (опоры)      — подтверждены, не опровергнуты
  - Конкурирующие обобщения         — для различения (разрешения неопределённости)
  - История токенов                 — для предотвращения циклов

Предоставляет:
  - Текущий ожидаемый признак (ожидаемый_признак)
  - Методы подтверждения / опровержения признаков
  - Проверку состояния (пуст / завершён)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set
from .generalization import Generalization, GeneralizationBase


@dataclass
class ActiveGen:
    """
    Активное обобщение в контексте.
    Отслеживает, на каком признаке цепочки мы сейчас находимся.
    """
    gen_id: str
    current_feature_index: int = 0   # текущая позиция в feature_chain

    def current_feature_id(self, gen: Generalization) -> Optional[str]:
        """ID текущего ожидаемого признака."""
        if self.current_feature_index < len(gen.feature_chain):
            return gen.feature_chain[self.current_feature_index]
        return None

    def is_complete(self, gen: Generalization) -> bool:
        """Цепочка полностью пройдена (подтверждена)."""
        return self.current_feature_index >= len(gen.feature_chain)

    def advance(self) -> None:
        """Перейти к следующему признаку."""
        self.current_feature_index += 1


class ContextBuffer:
    """
    Буфер актуального контекста.

    Цикл работы:
        1. get_expected_features()  → набор ожидаемых признаков из активных Gen
        2. confirm_feature(id)      → продвинуть вперёд Gen, ожидавший этот признак
        3. refute_feature(id)       → удалить Gen, ожидавший этот признак
        4. is_empty()               → контекст пуст → переключить внимание
        5. is_complete()            → все Gen завершены → успешное распознавание
    """

    def __init__(self, base=None) -> None:
        self._base = base
        # Активные обобщения (опоры): gen_id → ActiveGen
        self._active: Dict[str, ActiveGen] = {}
        # Конкурирующие обобщения (для различения)
        self._competing: Dict[str, ActiveGen] = {}
        # История токенов во избежание циклов
        self._token_history: List[str] = []
        self._token_history_set: Set[str] = set()

    # ------------------------------------------------------------------
    # Управление активными обобщениями

    def _applicable(self, gen_id):
        base = getattr(self, "_base", None)
        return base is None or base.is_applicable(gen_id, stage="load")

    def prune_inapplicable(self, base):
        for gid in set(self._active) | set(self._competing):
            if not base.is_applicable(gid, stage="context"):
                self.remove_active(gid)

    def add_active(self, gen_id: str, current_feature_index=None) -> None:
        """Добавить обобщение как активную опору."""
        if current_feature_index is not None and (type(current_feature_index) is not int or current_feature_index < 0):
            raise ValueError("Invalid continuation position")
        if not self._applicable(gen_id):
            return
        if gen_id not in self._active:
            self._active[gen_id] = ActiveGen(gen_id=gen_id)
        if current_feature_index is not None:
            self._active[gen_id].current_feature_index = current_feature_index

    def add_competing(self, gen_id: str) -> None:
        """Добавить обобщение как конкурирующее (для различения)."""
        if not self._applicable(gen_id):
            return
        if gen_id not in self._competing:
            self._competing[gen_id] = ActiveGen(gen_id=gen_id)

    def remove_active(self, gen_id: str) -> None:
        """Удалить активное обобщение (опровергнуто)."""
        self._active.pop(gen_id, None)
        self._competing.pop(gen_id, None)

    def active_gen_ids(self) -> List[str]:
        return list(self._active.keys())

    def active_positions(self):
        return tuple(sorted((gid, active.current_feature_index) for gid, active in self._active.items()))

    def competing_gen_ids(self) -> List[str]:
        return list(self._competing.keys())

    # ------------------------------------------------------------------
    # Ожидаемые признаки

    def get_expected_features(self, base: GeneralizationBase) -> Dict[str, str]:
        """
        Получить ожидаемые признаки из всех активных обобщений.
        Возвращает: {gen_id: feature_id} — какой признак ожидает каждый Gen.
        """
        expected: Dict[str, str] = {}
        for gen_id, active in list(self._active.items()):
            gen = base.get(gen_id)
            if gen is None:
                continue
            feat_id = active.current_feature_id(gen)
            if feat_id is not None:
                expected[gen_id] = feat_id
        return expected

    # ------------------------------------------------------------------
    # Подтверждение / опровержение

    def confirm_feature(
        self,
        feature_id: str,
        base: GeneralizationBase,
    ) -> List[str]:
        """
        Признак подтверждён.

        Продвигает вперёд все Gen, ожидавшие этот признак.
        Возвращает список gen_id, для которых вся цепочка теперь завершена.
        """
        completed: List[str] = []
        for gen_id, active in list(self._active.items()):
            gen = base.get(gen_id)
            if gen is None:
                continue
            if active.current_feature_id(gen) == feature_id:
                gen.confirm()
                active.advance()
                if active.is_complete(gen):
                    completed.append(gen_id)
        return completed

    def refute_feature(
        self,
        feature_id: str,
        base: GeneralizationBase,
    ) -> List[str]:
        """
        Признак опровергнут.

        Удаляет из контекста все Gen, ожидавшие этот признак.
        Возвращает список удалённых gen_id.
        """
        removed: List[str] = []
        for gen_id, active in list(self._active.items()):
            gen = base.get(gen_id)
            if gen is None:
                self.remove_active(gen_id)
                removed.append(gen_id)
                continue
            if active.current_feature_id(gen) == feature_id:
                gen.refute()
                self.remove_active(gen_id)
                removed.append(gen_id)
        return removed

    # ------------------------------------------------------------------
    # Состояние

    def is_empty(self) -> bool:
        """Контекст пуст — нет активных обобщений."""
        return len(self._active) == 0

    def is_complete(self, base: GeneralizationBase) -> bool:
        """
        Все активные обобщения завершены (все цепочки пройдены).
        → Успешное распознавание.
        """
        if self.is_empty():
            return False
        for gen_id, active in self._active.items():
            gen = base.get(gen_id)
            if gen and not active.is_complete(gen):
                return False
        return True

    # ------------------------------------------------------------------
    # История токенов (защита от циклов)

    def add_to_history(self, token_id: str) -> None:
        self._token_history.append(token_id)
        self._token_history_set.add(token_id)

    def seen(self, token_id: str) -> bool:
        return token_id in self._token_history_set

    def token_history(self) -> List[str]:
        return list(self._token_history)

    # ------------------------------------------------------------------
    # Сброс

    def reset(self) -> None:
        """Полный сброс контекста (новый сеанс внимания)."""
        self._active.clear()
        self._competing.clear()
        self._token_history.clear()
        self._token_history_set.clear()

    def clear_completed(self, base: GeneralizationBase) -> List[str]:
        """Удалить из контекста завершённые обобщения, вернуть их ID."""
        completed = [
            gen_id for gen_id, active in self._active.items()
            if (gen := base.get(gen_id)) and active.is_complete(gen)
        ]
        for gen_id in completed:
            del self._active[gen_id]
        return completed

    def __repr__(self) -> str:
        return (
            f"ContextBuffer("
            f"active={len(self._active)}, "
            f"competing={len(self._competing)}, "
            f"history={len(self._token_history)})"
        )
