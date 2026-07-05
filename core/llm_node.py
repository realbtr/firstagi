"""
core/llm_node.py — ModelNode с Claude API в качестве бэкенда.

LLMTeachNode
────────────
Специальный ModelNode, у которого «Gen-база» — это Claude (через AnthropicClient
из core/llm_broker.py). Когда модель-новичок задаёт вопрос:
  1. Формируется структурированный промпт с контекстом
  2. Claude возвращает ответ на вопрос
  3. Ответ парсится в List[str] токенов
  4. Токены скармливаются в learn_from_response → новые Gen

Промпт минималистичен: задача, вопрос, контекст → только токены ответа.
Формат ответа Claude: строка слов через пробел (без JSON), просто
педагогический ответ из 5-15 слов.

Использование:
  from core.llm_node import LLMTeachNode, MockLLMTeachNode
  from core.llm_broker import AnthropicClient

  llm_node = LLMTeachNode.from_api_key(
      api_key="sk-ant-...",
      domains={"children", "astronomy"},
      experience=5,
  )
  router.register(llm_node)
  novice_node.add_mentor(llm_node)
"""
from __future__ import annotations

import os
from typing import Callable, List, Optional, Set

from core.heterarchy import ModelNode, TeachRequest, TeachResponse
from core.llm_broker import AnthropicClient, LLMClient, MockLLMClient


# ══════════════════════════════════════════════════════════════════════════════
# Промпт-строитель
# ══════════════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT = """\
Ты — учитель генеративной модели, которая учится языку.
Модель задала тебе вопрос о продолжении текста.
Ответь кратко: дай 5–15 слов, которые естественно следуют за вопросом.
Только слова через пробел, без пунктуации и объяснений."""


def _build_prompt(req: TeachRequest) -> str:
    parts = []
    if req.domain_hint:
        parts.append(f"Область знаний: {req.domain_hint}")
    if req.context_tokens:
        ctx = " ".join(req.context_tokens[-8:])
        parts.append(f"Последний контекст: «{ctx}»")
    parts.append(f"Вопрос: {req.question}")
    parts.append("Ответ (только слова через пробел):")
    return "\n".join(parts)


def _parse_response(text: str, max_tokens: int = 15) -> List[str]:
    """
    Превратить сырой текст ответа Claude в список токенов.
    Фильтруем пунктуацию, берём не более max_tokens слов.
    """
    import re
    words = re.findall(r"[а-яёa-zA-Z0-9]+", text.lower())
    return words[:max_tokens]


# ══════════════════════════════════════════════════════════════════════════════
# LLMTeachNode
# ══════════════════════════════════════════════════════════════════════════════

class LLMTeachNode(ModelNode):
    """
    ModelNode, бэкендом которого является LLM (Claude API).

    Отличия от обычного ModelNode:
    - Не имеет собственной Gen-базы (system=DummySystem)
    - teach_fn → вызывает LLM через llm_client.complete()
    - Всегда отвечает (нет «не знаю»), но confidence зависит от длины ответа
    - Ведёт лог всех запросов (call_count, token_count)
    """

    def __init__(
        self,
        node_id: str,
        llm_client: LLMClient,
        domains: Optional[Set[str]] = None,
        experience: int = 5,
        verbose: bool = False,
    ) -> None:
        # Создаём пустую обёртку вместо полноценного LearningSystem
        system = _DummySystem()
        super().__init__(
            node_id    = node_id,
            system     = system,
            domains    = domains,
            experience = experience,
            teach_fn   = self._llm_teach,
        )
        self._llm_client = llm_client
        self._verbose    = verbose
        self._call_count = 0
        self._token_count = 0

    def _llm_teach(self, req: TeachRequest) -> Optional[TeachResponse]:
        """Обработать запрос через LLM."""
        prompt = _build_prompt(req)
        try:
            raw = self._llm_client.complete(prompt)
        except Exception as e:
            if self._verbose:
                print(f"  [LLMTeachNode:{self.node_id}] ERROR: {e}")
            return None

        tokens = _parse_response(raw)
        self._call_count  += 1
        self._token_count += len(tokens)

        if self._verbose:
            print(f"  [LLMTeachNode:{self.node_id}] Q: «{req.question}» → {tokens}")

        if not tokens:
            return None

        # Уверенность: больше токенов → более полный ответ
        confidence = min(1.0, len(tokens) / 10.0)

        resp = TeachResponse(
            tokens     = tokens,
            domain     = req.domain_hint,
            source_id  = self.node_id,
            confidence = confidence,
        )
        self._teach_log.append({
            "to":     req.origin_id,
            "q":      req.question,
            "tokens": tokens,
        })
        return resp

    # ── Статистика ────────────────────────────────────────────────────────────

    @property
    def stats(self):
        base_stats = super().stats
        base_stats["llm_calls"]   = self._call_count
        base_stats["llm_tokens"]  = self._token_count
        return base_stats

    # ── Фабрики ───────────────────────────────────────────────────────────────

    @classmethod
    def from_api_key(
        cls,
        api_key: str = "",
        node_id: str = "llm_master",
        model: str = "claude-haiku-4-5-20251001",
        domains: Optional[Set[str]] = None,
        experience: int = 5,
        verbose: bool = False,
    ) -> "LLMTeachNode":
        """
        Создать LLMTeachNode с реальным Claude API.
        api_key: если пуст — берётся из ANTHROPIC_API_KEY.
        """
        key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError(
                "API key required. Pass api_key= or set ANTHROPIC_API_KEY env var."
            )
        client = AnthropicClient(
            api_key       = key,
            model         = model,
            max_tokens    = 64,
            system_prompt = _SYSTEM_PROMPT,
        )
        return cls(
            node_id    = node_id,
            llm_client = client,
            domains    = domains or set(),
            experience = experience,
            verbose    = verbose,
        )

    @classmethod
    def mock(
        cls,
        responses: Optional[List[str]] = None,
        node_id: str = "llm_mock",
        domains: Optional[Set[str]] = None,
        experience: int = 5,
    ) -> "LLMTeachNode":
        """
        Создать LLMTeachNode с MockLLMClient для тестов/демо.
        """
        client = MockLLMClient(responses or [
            "медведь принёс пирог с грибами маше",
            "заяц нашёл морковку в огороде мамы",
            "звезда видна в телескоп ночью",
            "кот мяукает когда голоден",
        ])
        return cls(
            node_id    = node_id,
            llm_client = client,
            domains    = domains or set(),
            experience = experience,
        )


# ══════════════════════════════════════════════════════════════════════════════
# Заглушка LearningSystem (для LLMTeachNode)
# ══════════════════════════════════════════════════════════════════════════════

class _DummyBase:
    """Имитирует GeneralizationBase для статистики."""
    def size(self) -> int:
        return 0


class _DummySystem:
    """
    Минимальная заглушка LearningSystem.
    LLMTeachNode не обучается сам — только отвечает на вопросы.
    """
    def __init__(self) -> None:
        self.base = _DummyBase()

    def process_token(self, tok) -> None:
        pass
