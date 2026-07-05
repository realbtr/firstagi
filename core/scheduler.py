"""
Шаг 6: TeacherScheduler — планировщик учителей.

Координирует пул асинхронных LLM-учителей (воркеров), которые:
  1. Читают TeachingLog (состояние ядра)
  2. Принимают решение: поставить ордер на награду / подбросить контент
  3. Пишут результат обратно в TeachingLog

Воркеры реализуют протокол TeacherWorker.
MockTeacherWorker — простой эвристический воркер для тестов.

TeacherScheduler.tick() — один синхронный шаг.
TeacherScheduler.start() — запуск в фоновом Thread.

Использование:
    scheduler = TeacherScheduler(system.teaching_log, system.teacher)
    scheduler.add_worker(MockTeacherWorker(), name="mock")
    scheduler.tick()           # одноразово
    scheduler.start(interval=2.0)   # фоново каждые 2 сек
"""

from __future__ import annotations

import threading
import time
from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

from .teacher import RewardOrder, TeacherDriver, TeachingLog


# ══════════════════════════════════════════════════════════════════════
# Протокол воркера

@runtime_checkable
class TeacherWorker(Protocol):
    """
    Интерфейс для LLM-учителя или любого внешнего агента.

    observe() → если условия выполнены, вернуть RewardOrder, иначе None.
    suggest_content() → предложить учебный контент или None.
    """

    def observe(self, log_entries: List[Dict]) -> Optional[RewardOrder]:
        """Проанализировать лог и вернуть ордер (или None)."""
        ...

    def suggest_content(self, log_entries: List[Dict]) -> Optional[Any]:
        """Предложить следующий учебный токен/текст (или None)."""
        ...


# ══════════════════════════════════════════════════════════════════════
# Простой эвристический воркер (для тестов и демо)

class MockTeacherWorker:
    """
    Эвристический учитель:
      • Если в последних N записях REFUTED встречается >= threshold раз →
        ставит ордер «поощрить исследование».
      • Если ресурс падает ниже low_resource → подбрасывает контент 'rest'.

    Полностью детерминирован и не требует LLM.
    """

    def __init__(
        self,
        refuted_threshold: int = 3,
        look_back: int = 10,
        reward: float = 30.0,
        low_resource: float = 0.3,
    ) -> None:
        self._threshold = refuted_threshold
        self._look_back = look_back
        self._reward = reward
        self._low_resource = low_resource
        self.order_count: int = 0
        self.content_count: int = 0

    def observe(self, log_entries: List[Dict]) -> Optional[RewardOrder]:
        """Ставит ордер если слишком много опровержений подряд."""
        if not log_entries:
            return None
        recent = log_entries[-self._look_back:]
        refuted = sum(1 for e in recent if e.get("outcome") == "REFUTED")
        if refuted >= self._threshold:
            self.order_count += 1
            # Берём любые активные Gen из последней записи
            last = log_entries[-1]
            active = set(last.get("active_gens", [])[:3])
            return RewardOrder(
                required_gen_ids=active,
                reward=self._reward,
                label=f"mock_order_{self.order_count}",
                max_fires=1,
            )
        return None

    def suggest_content(self, log_entries: List[Dict]) -> Optional[Any]:
        """Предлагает 'rest' если ресурс низкий."""
        if not log_entries:
            return None
        last = log_entries[-1]
        if last.get("resource_level", 1.0) < self._low_resource:
            self.content_count += 1
            return "rest"
        return None


# ══════════════════════════════════════════════════════════════════════
# Планировщик

class TeacherScheduler:
    """
    Координирует пул воркеров.

    tick() выполняется синхронно: опрашивает всех воркеров, собирает
    ордера и контент, пушит их в TeachingLog.

    start(interval) запускает tick() в фоновом потоке с заданным интервалом.
    """

    def __init__(
        self,
        teaching_log: TeachingLog,
        teacher: TeacherDriver,
        look_back: int = 20,
    ) -> None:
        self._log = teaching_log
        self._teacher = teacher
        self._look_back = look_back
        self._workers: Dict[str, TeacherWorker] = {}
        self._tick_count: int = 0

        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    # ------------------------------------------------------------------
    # Управление воркерами

    def add_worker(self, worker: TeacherWorker, name: str = "") -> None:
        """Добавить воркера. Имя уникально; если пусто — авто."""
        if not name:
            name = f"worker_{len(self._workers)}"
        self._workers[name] = worker

    def remove_worker(self, name: str) -> None:
        """Удалить воркера по имени."""
        self._workers.pop(name, None)

    def worker_names(self) -> List[str]:
        return list(self._workers.keys())

    # ------------------------------------------------------------------
    # Синхронный шаг

    def tick(self) -> int:
        """
        Один цикл: читать лог → опросить воркеров → запушить.
        Возвращает число запушенных ордеров + контент-элементов.
        """
        self._tick_count += 1
        entries = self._log.get_recent(self._look_back)
        pushed = 0

        for worker in self._workers.values():
            # Ордер
            order = worker.observe(entries)
            if order is not None:
                self._log.push_reward_order(order)
                pushed += 1

            # Контент
            content = worker.suggest_content(entries)
            if content is not None:
                self._log.push_content(content)
                pushed += 1

        return pushed

    # ------------------------------------------------------------------
    # Фоновый поток

    def start(self, interval: float = 1.0) -> None:
        """Запустить фоновый Thread с интервалом interval секунд."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()

        def _loop() -> None:
            while not self._stop_event.is_set():
                try:
                    self.tick()
                except Exception:
                    pass
                self._stop_event.wait(timeout=interval)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Остановить фоновый Thread."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def tick_count(self) -> int:
        return self._tick_count

    def __repr__(self) -> str:
        return (
            f"TeacherScheduler("
            f"workers={len(self._workers)}, "
            f"ticks={self._tick_count}, "
            f"running={self.is_running})"
        )
