"""Конфигурация Telegram-демо, загружаемая из переменных окружения."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class DemoConfig:
    """
    Конфигурация демо-стенда.

    Создавать напрямую для тестов; использовать from_env() для продакшена.
    """

    bot_token: str
    channel_id: str

    anthropic_api_key: str = ""
    use_mock_llm: bool = True

    # Интервалы
    train_interval: float = 30.0    # секунды между тиками обучения
    post_interval: float = 300.0    # секунды между статус-постами
    min_post_interval: float = 2.0  # антифлуд между любыми постами

    # Поведение
    session_name: str = "telegram_demo"
    learn_from_users: bool = True   # учиться из сообщений участников чата
    post_on_events: bool = True     # мгновенно постить при интересных событиях
    min_text_length: int = 3        # минимальная длина текста для обучения

    # Лимиты Telegram
    max_message_length: int = 4000

    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "DemoConfig":
        """Загрузить конфигурацию из переменных окружения."""
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        channel = os.environ.get("TELEGRAM_CHANNEL_ID", "")

        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN not set")
        if not channel:
            raise ValueError("TELEGRAM_CHANNEL_ID not set")

        return cls(
            bot_token=token,
            channel_id=channel,
            anthropic_api_key=os.getenv("ANTHROPIC_API_KEY", ""),
            use_mock_llm=os.getenv("USE_MOCK_LLM", "1") == "1",
            train_interval=float(os.getenv("TRAIN_INTERVAL", "30")),
            post_interval=float(os.getenv("POST_INTERVAL", "300")),
            min_post_interval=float(os.getenv("MIN_POST_INTERVAL", "2")),
            session_name=os.getenv("SESSION_NAME", "telegram_demo"),
            learn_from_users=os.getenv("LEARN_FROM_USERS", "1") == "1",
            post_on_events=os.getenv("POST_ON_EVENTS", "1") == "1",
        )

    def validate(self) -> List[str]:
        """Вернуть список ошибок валидации (пустой = ОК)."""
        errors: List[str] = []
        if not self.bot_token:
            errors.append("bot_token is required")
        if not self.channel_id:
            errors.append("channel_id is required")
        if self.train_interval <= 0:
            errors.append("train_interval must be positive")
        if self.post_interval <= 0:
            errors.append("post_interval must be positive")
        if not self.use_mock_llm and not self.anthropic_api_key:
            errors.append("anthropic_api_key required when use_mock_llm=False")
        return errors
