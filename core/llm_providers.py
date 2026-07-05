"""
Шаг 9+: LLM-провайдеры — клиенты для разных языковых моделей.

Все классы реализуют протокол LLMClient: complete(prompt: str) -> str

Поддерживаемые провайдеры:
  Claude    — Anthropic          (pip install anthropic)
  OpenAI    — OpenAI GPT         (pip install openai)
  Grok      — xAI Grok           (pip install openai)
  DeepSeek  — DeepSeek           (pip install openai)
  Qwen      — Alibaba DashScope  (pip install openai)
  Gemini    — Google Gemini      (pip install openai)

Большинство провайдеров поддерживают OpenAI-совместимый API,
поэтому достаточно одного класса OpenAICompatibleClient.

Использование:
    from core.llm_providers import clients_from_env
    clients = clients_from_env()  # {'claude': ..., 'openai': ..., ...}
    # или напрямую:
    client = make_openai_client("sk-...")
    worker = LLMTeacherWorker(system, client)

Переменные окружения для автодетектора:
    ANTHROPIC_API_KEY, ANTHROPIC_MODEL
    OPENAI_API_KEY,    OPENAI_MODEL
    GROK_API_KEY,      GROK_MODEL
    DEEPSEEK_API_KEY,  DEEPSEEK_MODEL
    QWEN_API_KEY,      QWEN_MODEL
    GEMINI_API_KEY,    GEMINI_MODEL
"""
from __future__ import annotations

import os
from typing import Dict, Optional

from .llm_broker import LLMClient, AnthropicClient


# ══════════════════════════════════════════════════════════════════════
# Универсальный OpenAI-совместимый клиент
# ══════════════════════════════════════════════════════════════════════

class OpenAICompatibleClient(LLMClient):
    """
    Клиент для любого OpenAI-совместимого API.

    Работает для: OpenAI, xAI Grok, DeepSeek, Alibaba Qwen, Google Gemini.
    Требует: pip install openai
    """

    def __init__(
        self,
        api_key: str,
        model: str,
        base_url: Optional[str] = None,
        provider_name: str = "OpenAI-compatible",
        max_tokens: int = 400,
        temperature: float = 0.7,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.provider_name = provider_name
        self.max_tokens = max_tokens
        self.temperature = temperature
        self._client = None  # ленивая инициализация

    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
            except ImportError as exc:
                raise ImportError(
                    "Установите openai: pip install openai"
                ) from exc
            kwargs: dict = {"api_key": self.api_key}
            if self.base_url:
                kwargs["base_url"] = self.base_url
            self._client = OpenAI(**kwargs)
        return self._client

    def complete(self, prompt: str) -> str:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=self.max_tokens,
            temperature=self.temperature,
        )
        return response.choices[0].message.content or ""

    def __repr__(self) -> str:
        return f"{self.provider_name}({self.model})"


# ══════════════════════════════════════════════════════════════════════
# Фабрики для конкретных провайдеров
# ══════════════════════════════════════════════════════════════════════

def make_claude_client(
    api_key: str,
    model: str = "claude-haiku-4-5-20251001",
) -> AnthropicClient:
    """Anthropic Claude (собственный SDK, не OpenAI-совместимый)."""
    return AnthropicClient(api_key=api_key, model=model)


def make_openai_client(
    api_key: str,
    model: str = "gpt-4o-mini",
) -> OpenAICompatibleClient:
    """OpenAI GPT-4o, GPT-4o-mini, GPT-4-turbo и т.д."""
    return OpenAICompatibleClient(
        api_key=api_key,
        model=model,
        base_url=None,          # официальный endpoint
        provider_name="OpenAI",
    )


def make_grok_client(
    api_key: str,
    model: str = "grok-3-mini",
) -> OpenAICompatibleClient:
    """xAI Grok — OpenAI-совместимый API."""
    return OpenAICompatibleClient(
        api_key=api_key,
        model=model,
        base_url="https://api.x.ai/v1",
        provider_name="Grok",
    )


def make_deepseek_client(
    api_key: str,
    model: str = "deepseek-chat",
) -> OpenAICompatibleClient:
    """DeepSeek — OpenAI-совместимый API."""
    return OpenAICompatibleClient(
        api_key=api_key,
        model=model,
        base_url="https://api.deepseek.com",
        provider_name="DeepSeek",
    )


def make_qwen_client(
    api_key: str,
    model: str = "qwen-turbo",
) -> OpenAICompatibleClient:
    """Alibaba Qwen через DashScope (OpenAI-совместимый endpoint)."""
    return OpenAICompatibleClient(
        api_key=api_key,
        model=model,
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        provider_name="Qwen",
    )


def make_gemini_client(
    api_key: str,
    model: str = "gemini-2.0-flash",
) -> OpenAICompatibleClient:
    """Google Gemini через OpenAI-совместимый endpoint."""
    return OpenAICompatibleClient(
        api_key=api_key,
        model=model,
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        provider_name="Gemini",
    )


# ══════════════════════════════════════════════════════════════════════
# Автодетектор по переменным окружения
# ══════════════════════════════════════════════════════════════════════

# (env_var_key, provider_name, factory, default_model)
_PROVIDER_MAP = [
    ("ANTHROPIC_API_KEY", "claude",    make_claude_client,    "claude-haiku-4-5-20251001"),
    ("OPENAI_API_KEY",    "openai",    make_openai_client,    "gpt-4o-mini"),
    ("GROK_API_KEY",      "grok",      make_grok_client,      "grok-3-mini"),
    ("DEEPSEEK_API_KEY",  "deepseek",  make_deepseek_client,  "deepseek-chat"),
    ("QWEN_API_KEY",      "qwen",      make_qwen_client,      "qwen-turbo"),
    ("GEMINI_API_KEY",    "gemini",    make_gemini_client,    "gemini-2.0-flash"),
]


def clients_from_env() -> Dict[str, LLMClient]:
    """
    Автоматически создать LLM-клиентов из переменных окружения.

    Для каждого провайдера проверяется наличие его API-ключа:
        ANTHROPIC_API_KEY, OPENAI_API_KEY, GROK_API_KEY,
        DEEPSEEK_API_KEY, QWEN_API_KEY, GEMINI_API_KEY

    Модель можно переопределить через переменную вида <PROVIDER>_MODEL:
        OPENAI_MODEL=gpt-4o
        GEMINI_MODEL=gemini-1.5-pro

    Возвращает dict {name: client}. Пустой dict — если ни один ключ не задан.
    """
    result: Dict[str, LLMClient] = {}
    for env_key, name, factory, default_model in _PROVIDER_MAP:
        api_key = os.getenv(env_key, "").strip()
        if not api_key:
            continue
        model_env = env_key.replace("_API_KEY", "_MODEL")
        model = os.getenv(model_env, default_model).strip()
        result[name] = factory(api_key=api_key, model=model)
    return result


def active_provider_names() -> list[str]:
    """Вернуть список активных провайдеров (у которых есть API-ключ)."""
    return [
        name
        for env_key, name, _, _ in _PROVIDER_MAP
        if os.getenv(env_key, "").strip()
    ]
