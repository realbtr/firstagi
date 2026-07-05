"""ChannelPoster — отправка сообщений в Telegram-канал с троттлингом."""
from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .formatter import MessageFormatter

logger = logging.getLogger(__name__)


class ChannelPoster:
    """
    Отправляет HTML-сообщения в Telegram-канал.

    Встроенный троттлинг: min_interval секунд между любыми постами.
    """

    def __init__(
        self,
        bot,
        channel_id: str,
        min_interval: float = 2.0,
    ) -> None:
        self.bot = bot
        self.channel_id = channel_id
        self.min_interval = min_interval
        self._last_post_time: float = 0.0
        self._post_count: int = 0
        self._error_count: int = 0

    # ------------------------------------------------------------------

    async def post(self, text: str, parse_mode: str = "HTML") -> bool:
        """Отправить сообщение. Возвращает True при успехе."""
        # Троттлинг
        now = time.monotonic()
        wait = self.min_interval - (now - self._last_post_time)
        if wait > 0:
            await asyncio.sleep(wait)

        try:
            await self.bot.send_message(
                chat_id=self.channel_id,
                text=text,
                parse_mode=parse_mode,
            )
            self._last_post_time = time.monotonic()
            self._post_count += 1
            return True
        except Exception as exc:
            logger.error("Telegram post failed: %s", exc)
            self._error_count += 1
            return False

    async def post_status(self, status: dict, formatter: "MessageFormatter") -> bool:
        text = formatter.format_status(status)
        return await self.post(text)

    async def post_event(self, text: str) -> bool:
        return await self.post(text)

    # ------------------------------------------------------------------

    def stats(self) -> dict:
        return {
            "post_count": self._post_count,
            "error_count": self._error_count,
        }
