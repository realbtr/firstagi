"""
Шаг 6: PeripheralManager — менеджер периферии.

Ядро «видит сквозь» драйверы ощупываемый мир.
PeripheralManager прозрачен: он только доставляет токены от нескольких
PeripheralDriver в единый LearningSystem, не изменяя когнитивный взгляд ядра.

Использование:
    mgr = PeripheralManager(system)
    mgr.register(TextDriver("text"), priority=10)
    mgr.register(SequenceDriver("seq", sequence=[1,2,3]), priority=5)

    results = mgr.process("text", text="кот сидит на окне")
    all_results = mgr.process_all()
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional

from .learning import LearningSystem
from drivers.base import PeripheralDriver


class PeripheralManager:
    """
    Менеджер периферии.

    Регистрирует несколько PeripheralDriver, маршрутизирует их токены
    в один LearningSystem. Ядро не знает об источнике токенов —
    оно обрабатывает поток признаков (Feature), приходящих от любого
    зарегистрированного драйвера.
    """

    def __init__(self, system: LearningSystem) -> None:
        self._system = system
        self._drivers: Dict[str, PeripheralDriver] = {}
        self._priorities: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Регистрация драйверов

    def register(self, driver: PeripheralDriver, priority: int = 0) -> None:
        """Зарегистрировать драйвер. Большее priority → обрабатывается первым."""
        self._drivers[driver.driver_id] = driver
        self._priorities[driver.driver_id] = priority

    def unregister(self, driver_id: str) -> None:
        """Снять драйвер с регистрации."""
        self._drivers.pop(driver_id, None)
        self._priorities.pop(driver_id, None)

    def get(self, driver_id: str) -> Optional[PeripheralDriver]:
        """Вернуть драйвер по id."""
        return self._drivers.get(driver_id)

    def driver_ids(self) -> List[str]:
        """Список id зарегистрированных драйверов (по убыванию priority)."""
        return sorted(
            self._drivers.keys(),
            key=lambda did: -self._priorities.get(did, 0),
        )

    def __len__(self) -> int:
        return len(self._drivers)

    # ------------------------------------------------------------------
    # Обработка

    def process(self, driver_id: str, **produce_kwargs: Any) -> list:
        """
        Обработать поток токенов от одного драйвера.
        produce_kwargs передаются в driver.produce().

        Возвращает список StepResult.
        """
        driver = self._drivers.get(driver_id)
        if driver is None:
            raise KeyError(f"Драйвер '{driver_id}' не зарегистрирован")
        tokens = list(driver.produce(**produce_kwargs))
        return self._system.process_stream(tokens)

    def process_all(self, **produce_kwargs: Any) -> Dict[str, list]:
        """
        Обработать токены от всех драйверов в порядке приоритета.
        Возвращает {driver_id: [StepResult, ...]}.
        """
        results: Dict[str, list] = {}
        for did in self.driver_ids():
            driver = self._drivers[did]
            tokens = list(driver.produce(**produce_kwargs))
            results[did] = self._system.process_stream(tokens)
        return results

    def reset_all(self) -> None:
        """Сбросить все драйверы и контекст системы."""
        for driver in self._drivers.values():
            driver.reset()
        self._system.reset_context()

    # ------------------------------------------------------------------
    # Отладка

    def __repr__(self) -> str:
        ids = ", ".join(self.driver_ids())
        return f"PeripheralManager(drivers=[{ids}])"
