"""
Обобщение (Generalization, Gen) — цепочка признаков.
Гетерархия обобщений (GeneralizationBase) — База обобщений.
Токен периферии (PeripheralToken) — атомарный ввод от драйвера.

Гетерархия (не иерархия): обобщения могут ссылаться друг на друга
на разных уровнях. Обобщение обобщения — тоже обобщение того же типа.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Any
import uuid
import time


@dataclass
class Generalization:
    """
    Обобщение — цепочка признаков.

    Структура из презентации:
        gen_id         — уникальный ID
        key_id         — ID «ключа» (входного контекста, triggering condition)
        goal_id        — ID «цели» (целевого состояния)
        oper_id        — ID «операции» (трансформации, перехода)
        feature_chain  — упорядоченный список feature_id (сами признаки)
        success_count  — сколько раз подтверждалось
        variation_count— сколько вариаций встречалось
        stop_count     — сколько раз было остановлено/опровергнуто
        parent_ids     — родители в гетерархии (более общие)
        child_ids      — дети в гетерархии (более конкретные)
        created_at     — время создания
        label          — человекочитаемая метка (опционально)
    """
    gen_id: str
    key_id: Optional[str] = None           # ссылка на другой Gen (ключ)
    goal_id: Optional[str] = None          # ссылка на другой Gen (цель)
    oper_id: Optional[str] = None          # ссылка на другой Gen (операция)
    feature_chain: List[str] = field(default_factory=list)  # список feature_id
    success_count: int = 0
    variation_count: int = 0
    stop_count: int = 0
    parent_ids: List[str] = field(default_factory=list)
    child_ids: List[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    label: Optional[str] = None

    @property
    def significance(self) -> float:
        """
        Значимость обобщения = ранг в опыте.
        Ранжируем по частоте подтверждений, штрафуем за остановы.
        """
        total = self.success_count + self.stop_count
        if total == 0:
            return 0.0
        return self.success_count / total

    @property
    def generalization_level(self) -> int:
        """Длина цепочки признаков = уровень обобщения."""
        return len(self.feature_chain)

    @staticmethod
    def new(
        feature_chain: List[str] = None,
        key_id: str = None,
        goal_id: str = None,
        oper_id: str = None,
        label: str = None,
    ) -> Generalization:
        """Создать новое обобщение с автогенерацией ID."""
        return Generalization(
            gen_id=str(uuid.uuid4()),
            key_id=key_id,
            goal_id=goal_id,
            oper_id=oper_id,
            feature_chain=feature_chain or [],
            label=label,
        )

    def confirm(self) -> None:
        """Признак подтверждён — увеличить счётчик успехов."""
        self.success_count += 1

    def refute(self) -> None:
        """Признак опровергнут — увеличить счётчик остановов."""
        self.stop_count += 1

    def add_variation(self) -> None:
        """Встречена вариация (похожий, но не точный признак)."""
        self.variation_count += 1


@dataclass
class PeripheralToken:
    """
    Токен периферии — атомарный ввод от периферийного драйвера.

    Структура из презентации:
        token_id  — уникальный ID токена
        gen_id    — ID обобщения, которому соответствует токен
        driver_id — ID драйвера, породившего токен
        data      — фактические данные (характеристики области, текст, etc.)
        timestamp — время создания
    """
    token_id: str
    driver_id: str
    data: Any                              # произвольные данные от драйвера
    label: Optional[str] = None           # человекочитаемая метка (слово, символ, ...)
    gen_id: Optional[str] = None          # заполняется при распознавании
    timestamp: float = field(default_factory=time.time)

    @staticmethod
    def new(driver_id: str, data: Any, label: Optional[str] = None) -> PeripheralToken:
        return PeripheralToken(
            token_id=str(uuid.uuid4()),
            driver_id=driver_id,
            data=data,
            label=label,
        )


class GeneralizationBase:
    """
    Гетерархия обобщений (База обобщений).

    Хранит:
        - все обобщения (Generalization)
        - статистику переходов между обобщениями (для алгоритма консолидации)
        - индексы для быстрого поиска

    Методы:
        add()         — добавить обобщение
        get()         — получить по ID
        rank()        — ранжировать по значимости
        search()      — найти совпадающие обобщения по цепочке признаков
        low_level()   — найти наименее обобщённые (короткие цепочки)
                        → они получают приоритет при пустом контексте
    """

    def __init__(
        self,
        evict_callback: Optional[Callable[["GeneralizationBase"], int]] = None,
    ) -> None:
        self._gens: Dict[str, Generalization] = {}
        # Статистика переходов: transition_stats[from_id][to_id] = count
        self._transition_stats: Dict[str, Dict[str, int]] = {}
        # Опциональный колбэк вытеснения — вызывается после каждого add().
        # Сигнатура: callback(base) -> int (число вытесненных Gen).
        self._evict_callback = evict_callback

    # ------------------------------------------------------------------
    # CRUD

    def add(self, gen: Generalization) -> Generalization:
        """Добавить обобщение в базу. Если задан evict_callback — вызывает его после вставки."""
        self._gens[gen.gen_id] = gen
        if self._evict_callback is not None:
            self._evict_callback(self)
        return gen

    def remove(self, gen_id: str) -> bool:
        """
        Удалить обобщение из базы.

        Также очищает:
          - ссылки parent_ids / child_ids у соседних Gen
          - записи в _transition_stats

        Возвращает True если Gen был найден и удалён.
        """
        gen = self._gens.pop(gen_id, None)
        if gen is None:
            return False
        # Убрать ссылки у родителей
        for pid in gen.parent_ids:
            parent = self._gens.get(pid)
            if parent and gen_id in parent.child_ids:
                parent.child_ids.remove(gen_id)
        # Убрать ссылки у детей
        for cid in gen.child_ids:
            child = self._gens.get(cid)
            if child and gen_id in child.parent_ids:
                child.parent_ids.remove(gen_id)
        # Очистить статистику переходов
        self._transition_stats.pop(gen_id, None)
        for stats in self._transition_stats.values():
            stats.pop(gen_id, None)
        return True

    def get(self, gen_id: str) -> Optional[Generalization]:
        """Получить обобщение по ID."""
        return self._gens.get(gen_id)

    def all(self) -> List[Generalization]:
        """Все обобщения."""
        return list(self._gens.values())

    def size(self) -> int:
        return len(self._gens)

    # ------------------------------------------------------------------
    # Поиск и ранжирование

    def rank(self, min_significance: float = 0.0) -> List[Generalization]:
        """
        Ранжировать обобщения по значимости (частоте подтверждений).
        Это и есть «опыт» системы.
        """
        gens = [g for g in self._gens.values() if g.significance >= min_significance]
        return sorted(gens, key=lambda g: g.significance, reverse=True)

    def search_by_chain(self, feature_chain: List[str]) -> List[Generalization]:
        """
        Найти обобщения с точным совпадением цепочки признаков.
        (Для нечёткого поиска нужен отдельный метод с толерантностью.)
        """
        result = []
        for gen in self._gens.values():
            if gen.feature_chain == feature_chain:
                result.append(gen)
        return sorted(result, key=lambda g: g.significance, reverse=True)

    def search_by_prefix(self, prefix: List[str]) -> List[Generalization]:
        """Найти обобщения, цепочка которых начинается с данного префикса."""
        result = []
        n = len(prefix)
        for gen in self._gens.values():
            if gen.feature_chain[:n] == prefix:
                result.append(gen)
        return sorted(result, key=lambda g: g.significance, reverse=True)

    def low_level(self, max_chain_length: int = 2) -> List[Generalization]:
        """
        Малообобщённые обобщения (короткие цепочки).
        При пустом/полном контексте внимание переключается именно на них.
        """
        result = [
            g for g in self._gens.values()
            if 0 < g.generalization_level <= max_chain_length
        ]
        return sorted(result, key=lambda g: g.significance, reverse=True)

    # ------------------------------------------------------------------
    # Статистика переходов (для алгоритма консолидации)

    def record_transition(self, from_id: str, to_id: str) -> None:
        """Зафиксировать переход from_id → to_id."""
        if from_id not in self._transition_stats:
            self._transition_stats[from_id] = {}
        stats = self._transition_stats[from_id]
        stats[to_id] = stats.get(to_id, 0) + 1

    def get_transitions(self, from_id: str) -> Dict[str, int]:
        """Статистика переходов из данного обобщения."""
        return self._transition_stats.get(from_id, {})

    def most_likely_next(self, from_id: str) -> Optional[str]:
        """Наиболее вероятное следующее обобщение после from_id."""
        transitions = self.get_transitions(from_id)
        if not transitions:
            return None
        return max(transitions, key=transitions.__getitem__)

    # ------------------------------------------------------------------
    # Гетерархия (связи родитель-потомок)

    def link(self, parent_id: str, child_id: str) -> None:
        """Установить связь родитель → потомок в гетерархии."""
        parent = self._gens.get(parent_id)
        child = self._gens.get(child_id)
        if parent and child:
            if child_id not in parent.child_ids:
                parent.child_ids.append(child_id)
            if parent_id not in child.parent_ids:
                child.parent_ids.append(parent_id)

    def __repr__(self) -> str:
        return f"GeneralizationBase(size={self.size()})"
