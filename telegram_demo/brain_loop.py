"""
BrainLoop — asyncio-цикл непрерывного обучения FirstAGI.

Три параллельных задачи:
  _train_loop  — тики BrokerLoop (обучение через LLM-учителя)
  _post_loop   — периодические статус-посты в канал
  _user_loop   — обработка текстов, пришедших от участников чата
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .config import DemoConfig
    from .formatter import MessageFormatter
    from .poster import ChannelPoster

logger = logging.getLogger(__name__)

# Порог прироста обобщений для публикации события
_GEN_EVENT_THRESHOLD = 5


class BrainLoop:
    """
    Непрерывный цикл обучения + публикации в Telegram.

    Использование:
        brain = BrainLoop(app, broker, poster, formatter, config)
        asyncio.create_task(brain.run())

        # из обработчика Telegram:
        brain.feed_user_text("кот сидит на окне", "alice")
    """

    def __init__(
        self,
        app,                        # CoreApplication
        broker,                     # BrokerLoop (training.llm_loop)
        poster: "ChannelPoster",
        formatter: "MessageFormatter",
        config: "DemoConfig",
    ) -> None:
        self.app = app
        self.broker = broker
        self.poster = poster
        self.formatter = formatter
        self.config = config

        self._running: bool = False
        self._user_queue: asyncio.Queue = asyncio.Queue(maxsize=50)
        self._start_time: float = 0.0
        self._step_count: int = 0
        self._event_count: int = 0

    # ------------------------------------------------------------------
    # Публичный API

    async def run(self) -> None:
        """Запустить все три задачи. Работает до вызова stop()."""
        self._running = True
        self._start_time = time.monotonic()
        tasks = [
            asyncio.create_task(self._train_loop(), name="brain-train"),
            asyncio.create_task(self._post_loop(),  name="brain-post"),
            asyncio.create_task(self._user_loop(),  name="brain-user"),
        ]
        try:
            await asyncio.gather(*tasks)
        except asyncio.CancelledError:
            pass
        finally:
            self._running = False
            for t in tasks:
                t.cancel()

    async def stop(self) -> None:
        """Сигнал остановки."""
        self._running = False

    def feed_user_text(self, text: str, username: str) -> None:
        """
        Поставить пользовательский текст в очередь обучения.
        Потокобезопасен — можно вызывать из любого контекста.
        """
        try:
            self._user_queue.put_nowait((text, username))
        except asyncio.QueueFull:
            logger.warning("User queue full, dropping message from @%s", username)

    # ------------------------------------------------------------------
    # Внутренние асинхронные петли

    async def _train_loop(self) -> None:
        """Тики обучения через BrokerLoop."""
        while self._running:
            try:
                tick_result = await asyncio.to_thread(self._sync_train_tick)
                self._step_count += 1

                # Публикуем интересные события
                if self.config.post_on_events:
                    for event_text in tick_result.get("events", []):
                        await self.poster.post_event(event_text)
                        self._event_count += 1

                # Публикуем диалог учитель → AGI, если что-то выучено
                teacher_text = tick_result.get("teacher_text", "")
                if teacher_text:
                    narrative = await asyncio.to_thread(self._get_narrative)
                    n_learned = tick_result.get("n_learned", 0)
                    msg = self.formatter.format_teacher_dialogue(
                        teacher_text, narrative, n_learned
                    )
                    await self.poster.post(msg)

            except Exception as exc:
                logger.error("Train loop error: %s", exc)

            await asyncio.sleep(self.config.train_interval)

    async def _post_loop(self) -> None:
        """Периодические статус-посты."""
        # Начальная задержка — дать боту время запустить приветствие
        await asyncio.sleep(15.0)
        while self._running:
            try:
                status = await asyncio.to_thread(self.app.status)
                await self.poster.post_status(status, self.formatter)
            except Exception as exc:
                logger.error("Post loop error: %s", exc)
            await asyncio.sleep(self.config.post_interval)

    async def _user_loop(self) -> None:
        """Обработка пользовательских текстов."""
        while self._running:
            try:
                text, username = await asyncio.wait_for(
                    self._user_queue.get(), timeout=1.0
                )
                try:
                    n_learned = await asyncio.to_thread(self._learn_text, text)
                    msg = self.formatter.format_user_teach(username, text, n_learned)
                    await self.poster.post(msg)
                except Exception as exc:
                    logger.error("User learn error for @%s: %s", username, exc)
            except asyncio.TimeoutError:
                continue

    # ------------------------------------------------------------------
    # Синхронные хелперы (запускаются через asyncio.to_thread)

    def _sync_train_tick(self) -> Dict:
        """Один тик брокер-цикла. Блокирующий."""
        before = self._snapshot_stats()
        report = self.broker.step()
        after = self._snapshot_stats()

        teacher_text = report.get("content_fed") or ""
        n_learned = 1 if teacher_text else 0
        events = self._detect_events(before, after)

        return {
            "n_learned":    n_learned,
            "teacher_text": teacher_text,
            "events":       events,
            "broker_report": report,
        }

    def _learn_text(self, text: str) -> int:
        """Обучить AGI тексту. Возвращает приблизительное число токенов."""
        try:
            before = self.app.status().get("system", {}).get("total_tokens", 0)
            self.app.learn(text)
            after = self.app.status().get("system", {}).get("total_tokens", 0)
            return max(0, after - before)
        except Exception:
            return 0

    def _get_narrative(self) -> str:
        try:
            return self.app.status().get("narrative", "")
        except Exception:
            return ""

    def _snapshot_stats(self) -> Dict:
        """Снапшот ключевых счётчиков для детекции событий."""
        try:
            status = self.app.status()
            system = status.get("system", {})
            phase = system.get("phase_space", {})
            return {
                "gen_count":        system.get("total_generalizations", 0),
                "attractor_count":  phase.get("n_attractors", 0),
                "bifurcation_count": phase.get("n_bifurcations", 0),
            }
        except Exception:
            return {}

    def _detect_events(self, before: Dict, after: Dict) -> List[str]:
        """Обнаружить интересные события между двумя снапшотами."""
        if not before or not after:
            return []

        events: List[str] = []

        # Прирост обобщений
        gen_delta = after.get("gen_count", 0) - before.get("gen_count", 0)
        if gen_delta >= _GEN_EVENT_THRESHOLD:
            events.append(
                self.formatter.format_new_generalization(
                    f"gen_{after['gen_count']}", gen_delta
                )
            )

        # Новые аттракторы
        attr_delta = after.get("attractor_count", 0) - before.get("attractor_count", 0)
        if attr_delta > 0:
            events.append(
                self.formatter.format_attractor_found(
                    f"attr_{after['attractor_count']}", attr_delta
                )
            )

        # Новые бифуркации
        bif_delta = after.get("bifurcation_count", 0) - before.get("bifurcation_count", 0)
        if bif_delta > 0:
            events.append(
                self.formatter.format_bifurcation(
                    f"feat_{after.get('gen_count', 0)}", bif_delta
                )
            )

        return events

    # ------------------------------------------------------------------

    def uptime_hours(self) -> float:
        if self._start_time == 0.0:
            return 0.0
        return (time.monotonic() - self._start_time) / 3600.0

    def stats(self) -> Dict:
        return {
            "running":        self._running,
            "step_count":     self._step_count,
            "event_count":    self._event_count,
            "uptime_hours":   self.uptime_hours(),
            "user_queue_size": self._user_queue.qsize(),
        }
