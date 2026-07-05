"""
CommandRouter — обработчик команд и сообщений Telegram.

Регистрируется в Application как handlers; делегирует логику в BrainLoop.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Set

if TYPE_CHECKING:
    from .brain_loop import BrainLoop
    from .config import DemoConfig
    from .formatter import MessageFormatter
    from .poster import ChannelPoster

logger = logging.getLogger(__name__)


class CommandRouter:
    """
    Маршрутизатор команд и текстовых сообщений.

    Команды:
        /start, /help  — приветствие
        /status        — краткое состояние
        /stats         — детальная статистика
        /teach <текст> — обучить FirstAGI
        /reset         — сбросить контекст (только admin)
    """

    def __init__(
        self,
        brain: "BrainLoop",
        formatter: "MessageFormatter",
        poster: "ChannelPoster",
        config: "DemoConfig",
    ) -> None:
        self.brain = brain
        self.formatter = formatter
        self.poster = poster
        self.config = config
        self._admin_ids: Set[int] = set()

    def set_admin_ids(self, ids) -> None:
        self._admin_ids = set(ids)

    # ------------------------------------------------------------------
    # Команды

    async def cmd_start(self, update, context) -> None:
        text = self.formatter.format_welcome()
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_status(self, update, context) -> None:
        try:
            status = self.brain.app.status()
            text = self.formatter.format_status(status)
        except Exception as exc:
            text = self.formatter.format_error(str(exc))
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_stats(self, update, context) -> None:
        try:
            status = self.brain.app.status()
            text = self.formatter.format_stats_detail(status)
        except Exception as exc:
            text = self.formatter.format_error(str(exc))
        await update.message.reply_text(text, parse_mode="HTML")

    async def cmd_teach(self, update, context) -> None:
        args = getattr(context, "args", None) or []
        if not args:
            await update.message.reply_text(
                "Использование: /teach &lt;текст&gt;",
                parse_mode="HTML",
            )
            return

        text = " ".join(args)
        user = update.effective_user
        username = (user.username or str(user.id)) if user else "unknown"
        self.brain.feed_user_text(text, username)

        snippet = self.formatter.truncate(
            self.formatter._esc(text), 120
        )
        await update.message.reply_text(
            f"✅ Поставлено в очередь обучения:\n<i>{snippet}</i>",
            parse_mode="HTML",
        )

    async def cmd_reset(self, update, context) -> None:
        user = update.effective_user
        user_id = user.id if user else None

        if self._admin_ids and user_id not in self._admin_ids:
            await update.message.reply_text(
                "⛔ Команда доступна только администраторам."
            )
            return

        try:
            self.brain.app.system.reset_context()
            await update.message.reply_text("♻️ Контекст сброшен.")
        except Exception as exc:
            await update.message.reply_text(
                self.formatter.format_error(str(exc)), parse_mode="HTML"
            )

    # ------------------------------------------------------------------
    # Произвольные сообщения

    async def handle_message(self, update, context) -> None:
        """Обработать обычный текст — опционально добавить в обучение."""
        if not self.config.learn_from_users:
            return
        if not update.message or not update.message.text:
            return

        text = update.message.text.strip()
        if len(text) < self.config.min_text_length:
            return

        user = update.effective_user
        username = (user.username or str(user.id)) if user else "anon"
        self.brain.feed_user_text(text, username)
