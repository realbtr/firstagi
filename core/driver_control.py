"""
Шаг 10: DriverController — программный контроль потока внимания.

Позволяет отладчику или CurriculumAgent:
  • менять приоритеты зарегистрированных драйверов
  • инжектировать синтетические признаки напрямую в движок
  • временно переопределять нейромодуляцию tolerance
  • читать карту внимания (активные Gen + их ожидания)

Не добавляет новых когнитивных механизмов — только экспонирует
то, что уже есть в CoreApplication, для внешнего управления.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, TYPE_CHECKING  # noqa: F401

if TYPE_CHECKING:
    from .app import CoreApplication
    from .algorithm import StepResult


class DriverController:
    """
    Программный контроль потока внимания.

    Привязывается к CoreApplication и предоставляет низкоуровневый
    доступ к движку для автоматизации и отладки.
    """

    def __init__(self, app: "CoreApplication") -> None:
        self._app = app
        self._tolerance_override: Optional[float] = None

    # ------------------------------------------------------------------
    # Приоритеты драйверов

    def set_driver_priority(self, driver_id: str, priority: int) -> None:
        """Изменить приоритет зарегистрированного драйвера."""
        if driver_id not in self._app.peripherals._drivers:
            raise KeyError(f"Драйвер '{driver_id}' не зарегистрирован")
        self._app.peripherals._priorities[driver_id] = priority

    def get_driver_priorities(self) -> Dict[str, int]:
        """Текущие приоритеты всех зарегистрированных драйверов."""
        return dict(self._app.peripherals._priorities)

    def driver_ids(self) -> List[str]:
        """Список id зарегистрированных драйверов (по убыванию приоритета)."""
        return self._app.peripherals.driver_ids()

    # ------------------------------------------------------------------
    # Инъекция синтетических признаков

    def inject_feature(self, feature_id: str) -> Optional["StepResult"]:
        """
        Инжектировать синтетический токен с известным признаком.

        Позволяет «скормить» движку feature_id напрямую,
        минуя текстовый парсинг. Полезно для точечного подкрепления
        конкретных ветвей внимания.

        Возвращает StepResult или None если feature_id неизвестен.
        """
        from .generalization import PeripheralToken

        feature = self._app.system.engine._features.get(feature_id)
        if feature is None:
            return None
        token = PeripheralToken.new(driver_id="_injected_", data=feature)
        return self._app.system.process_token(token)

    def known_features(self) -> List[str]:
        """Список известных feature_id в реестре движка."""
        return list(self._app.system.engine._features.keys())

    # ------------------------------------------------------------------
    # Переопределение tolerance

    def set_tolerance_override(self, value: Optional[float]) -> None:
        """
        Временно переопределить нейромодуляцию tolerance.

        value=None → вернуть управление ResourceDriver.
        Малое значение (<0.1) = строгое совпадение признаков.
        Большое значение (>0.5) = нечёткое, обобщённое совпадение.
        """
        self._tolerance_override = value
        if value is not None:
            self._app.system.engine.feature_tolerance = float(value)
        else:
            rs = self._app.system.resource.state
            self._app.system.engine.feature_tolerance = rs.modulate_tolerance(
                self._app.system._base_tolerance
            )

    @property
    def tolerance_override(self) -> Optional[float]:
        """Текущее переопределение tolerance (None если не переопределено)."""
        return self._tolerance_override

    # ------------------------------------------------------------------
    # Карта внимания

    def get_attention_map(self) -> Dict[str, Any]:
        """
        Текущая карта внимания: активные Gen и их ожидаемые следующие признаки.

        Ключевой инструмент для понимания, «куда смотрит» система
        в данный момент. Используется при генерации curriculum.
        """
        context = self._app.system.engine.context
        base    = self._app.system.base
        expected = context.get_expected_features(base)

        result: Dict[str, Any] = {}
        for gen_id, feat_id in expected.items():
            gen = base.get(gen_id)
            if gen:
                result[gen_id[:8]] = {
                    "full_id":          gen_id,
                    "expected_feature": feat_id,
                    "significance":     round(gen.significance, 4),
                    "chain_len":        gen.generalization_level,
                    "label":            gen.label or "",
                }
        return result

    def active_gen_count(self) -> int:
        """Количество активных Gen в текущем контексте."""
        return len(self._app.system.engine.context.active_gen_ids())

    # ------------------------------------------------------------------
    # Шаг 11: буферы и активное внимание

    def load_buffer(self, content: Any, driver_id: str = "text") -> int:
        """
        Загрузить контент в буфер указанного драйвера.

        Делегирует в driver.load_buffer(content).
        Возвращает новый размер буфера.
        """
        driver = self._app.peripherals.get(driver_id)
        if driver is None:
            raise KeyError(f"Драйвер '{driver_id}' не зарегистрирован")
        return driver.load_buffer(content)

    def buffer_sizes(self) -> Dict[str, int]:
        """Текущие размеры буферов всех зарегистрированных драйверов."""
        result: Dict[str, int] = {}
        for did in self._app.peripherals.driver_ids():
            d = self._app.peripherals.get(did)
            if d is not None:
                result[did] = d.buffer_size
        return result

    def clear_buffer(self, driver_id: Optional[str] = None) -> None:
        """
        Очистить буфер. driver_id=None → очистить все буферы.
        """
        if driver_id is not None:
            d = self._app.peripherals.get(driver_id)
            if d:
                d.clear_buffer()
        else:
            for did in self._app.peripherals.driver_ids():
                d = self._app.peripherals.get(did)
                if d:
                    d.clear_buffer()
