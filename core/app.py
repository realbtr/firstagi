"""
Шаг 6: CoreApplication — центральный объект полноценного приложения.

Собирает все компоненты ядра в единый фасад:
  • LearningSystem (ядро)
  • PeripheralManager (драйверы)
  • NarrativeVoice (нарратив)
  • SessionManager (персистентность)
  • TeacherScheduler (асинхронные учителя)

CLI и HTTP API оборачивают именно CoreApplication.

Использование:
    app = CoreApplication()
    app.startup()

    app.add_text_driver("text")
    result = app.learn("кот сидит на окне")
    print(result["narrative"])

    app.save_session("cats")
    app.shutdown()
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional

from .learning import LearningSystem
from .peripheral import PeripheralManager
from .narrative import NarrativeVoice
from .session import SessionManager
from .scheduler import TeacherScheduler, MockTeacherWorker
from .timescale import TimescaleScheduler
from drivers.text_driver import TextDriver
from drivers.sequence_driver import SequenceDriver


# Конфигурация по умолчанию
_DEFAULT_CONFIG: Dict[str, Any] = {
    "feature_tolerance": 0.35,
    "min_gen_count":     2,
    "max_competing":     8,
    "initial_resource":  0.5,
    "sessions_dir":      "sessions",
    "scheduler_interval": 2.0,
    "mock_teacher":      True,
}


class CoreApplication:
    """
    Центральный объект приложения FirstAGI.

    Создаётся один раз; CLI и HTTP-сервер оборачивают его.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = dict(_DEFAULT_CONFIG)
        if config:
            cfg.update(config)
        self._cfg = cfg
        self._started = False

        # Ядро
        self.system = LearningSystem(
            feature_tolerance=cfg["feature_tolerance"],
            min_gen_count=cfg["min_gen_count"],
            max_competing=cfg["max_competing"],
            initial_resource=cfg["initial_resource"],
        )

        # Менеджеры
        self.peripherals = PeripheralManager(self.system)
        self.voice        = NarrativeVoice(self.system)
        self.sessions     = SessionManager(cfg["sessions_dir"])
        self.scheduler    = TeacherScheduler(
            self.system.teaching_log,
            self.system.teacher,
        )
        self.timescale    = TimescaleScheduler()

    # ------------------------------------------------------------------
    # Запуск / останов

    def startup(self, autoload: Optional[str] = None) -> None:
        """
        Инициализация: добавить дефолтный TextDriver,
        опционально загрузить сессию, запустить планировщик.
        """
        if self._started:
            return

        # Дефолтный текстовый драйвер
        if "text" not in self.peripherals.driver_ids():
            self.add_text_driver("text")

        # Mock-учитель (если нужен)
        if self._cfg.get("mock_teacher"):
            self.scheduler.add_worker(MockTeacherWorker(), name="mock")

        # Загрузить сессию
        if autoload and self.sessions.exists(autoload):
            self.load_session(autoload)

        # Запустить планировщик в фоне
        self.scheduler.start(interval=self._cfg["scheduler_interval"])
        self._started = True

    def shutdown(self) -> None:
        """Остановить фоновые потоки."""
        self.scheduler.stop()
        self._started = False

    # ------------------------------------------------------------------
    # Обучение

    def learn(
        self,
        text: str,
        driver_id: str = "text",
        reset_after: bool = True,
    ) -> Dict[str, Any]:
        """
        Обучить систему одной единицей текста.

        Если driver_id ещё не зарегистрирован — создаёт TextDriver.
        Возвращает словарь с результатами и нарративом.
        """
        if driver_id not in self.peripherals.driver_ids():
            self.add_text_driver(driver_id)

        driver = self.peripherals.get(driver_id)

        # TextDriver.produce() принимает text= как kwarg
        results = self.peripherals.process(driver_id, text=text)

        if reset_after:
            self.system.reset_context()

        outcomes = [r.outcome.name for r in results]
        confirmed = outcomes.count("CONFIRMED")
        completed = outcomes.count("COMPLETED")
        refuted   = outcomes.count("REFUTED")
        explored  = outcomes.count("EXPLORING")

        return {
            "text":      text,
            "driver_id": driver_id,
            "outcomes":  outcomes,
            "confirmed": confirmed,
            "completed": completed,
            "refuted":   refuted,
            "explored":  explored,
            "match_rate": (confirmed + completed) / max(len(outcomes), 1),
            "narrative": self.voice.summary(),
            "stats":     self.system.stats(),
        }

    # ------------------------------------------------------------------
    # Состояние

    def status(self) -> Dict[str, Any]:
        """Полный снапшот состояния системы."""
        stats = self.system.stats()
        rs = self.system.resource.state
        return {
            "system":     stats,
            "resource": {
                "level": rs.level,
                "mode":  rs.mode,
                "trend": rs.trend,
            },
            "drivers":    self.peripherals.driver_ids(),
            "scheduler": {
                "running":    self.scheduler.is_running,
                "tick_count": self.scheduler.tick_count,
                "workers":    self.scheduler.worker_names(),
            },
            "timescale":  self.timescale.tier_sizes(self.system.base),
            "sessions": {
                "dir":    self._cfg["sessions_dir"],
                "latest": self.sessions.latest(),
            },
            "narrative": self.voice.summary(),
        }

    # ------------------------------------------------------------------
    # Сессии

    def save_session(
        self,
        name: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Сохранить текущую сессию. Возвращает путь к файлу."""
        meta = {"saved_at": time.time()}
        if metadata:
            meta.update(metadata)
        return self.sessions.save(name, self.system, meta)

    def load_session(self, name: str) -> Dict[str, Any]:
        """
        Загрузить сессию и заменить текущую систему.
        Возвращает метаданные сессии.
        """
        system, meta = self.sessions.load(name)
        self.system = system
        # Переподключить менеджеры к новой системе
        self.peripherals = PeripheralManager(system)
        self.add_text_driver("text")
        self.voice = NarrativeVoice(system)
        self.scheduler = TeacherScheduler(
            system.teaching_log,
            system.teacher,
        )
        if self._cfg.get("mock_teacher"):
            self.scheduler.add_worker(MockTeacherWorker(), name="mock")
        if self._started:
            self.scheduler.start(interval=self._cfg["scheduler_interval"])
        return meta

    # ------------------------------------------------------------------
    # Управление драйверами

    def add_text_driver(self, driver_id: str = "text", **kwargs: Any) -> None:
        """Добавить/заменить TextDriver."""
        driver = TextDriver(driver_id, **kwargs)
        self.peripherals.register(driver, priority=10)

    def add_sequence_driver(
        self,
        driver_id: str,
        sequence: List[float],
        **kwargs: Any,
    ) -> None:
        """Добавить SequenceDriver."""
        driver = SequenceDriver(driver_id, sequence=sequence, **kwargs)
        self.peripherals.register(driver, priority=5)

    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"CoreApplication("
            f"base={self.system.base.size()} Gen, "
            f"steps={self.system.engine.step_count}, "
            f"drivers={self.peripherals.driver_ids()})"
        )
