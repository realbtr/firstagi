"""
Шаг 8: LLM-брокер — непрерывное обучение через Language Model.

Архитектура:
  LLMDecision         — решение LLM (TEACH / REWARD / WAIT)
  LLMClient           — Protocol: complete(prompt) → str
  AnthropicClient     — реальный Claude API (ленивый импорт)
  MockLLMClient       — детерминированный mock для тестов
  LLMPromptBuilder    — формирует нарративный промпт из состояния системы
  LLMResponseParser   — разбирает JSON-ответ LLM
  LLMTeacherWorker    — реализует TeacherWorker Protocol

Принцип работы:
  Каждый tick() планировщика:
    1. observe()       → вызывает LLM (rate-limited), кэширует LLMDecision
                         → возвращает RewardOrder при action=REWARD
    2. suggest_content() → использует кэш из observe()
                         → возвращает text при action=TEACH, кэш очищается

  Один LLM-вызов на tick — не два.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .learning import LearningSystem

from .teacher import RewardOrder


# ══════════════════════════════════════════════════════════════════════
# Решение LLM
# ══════════════════════════════════════════════════════════════════════

@dataclass
class LLMDecision:
    """Структурированное решение LLM: что делать с моделью."""
    action: str        # "TEACH" | "REWARD" | "WAIT"
    text: str = ""     # текст для подачи (при TEACH)
    amount: float = 0.0  # размер награды (при REWARD)
    reason: str = ""   # объяснение решения

    _VALID_ACTIONS = {"TEACH", "REWARD", "WAIT"}

    def __post_init__(self) -> None:
        self.action = self.action.upper()
        if self.action not in self._VALID_ACTIONS:
            self.action = "WAIT"


# ══════════════════════════════════════════════════════════════════════
# LLM-клиенты
# ══════════════════════════════════════════════════════════════════════

class LLMClient:
    """Protocol-подобный базовый класс для LLM-клиентов."""
    def complete(self, prompt: str) -> str:
        raise NotImplementedError


class AnthropicClient(LLMClient):
    """
    Клиент Claude API от Anthropic.

    Ленивый импорт библиотеки anthropic — тесты работают без неё.
    Модель по умолчанию: claude-haiku-4-5-20251001 (быстрая и дешёвая).
    """

    def __init__(
        self,
        api_key: str,
        model: str = "claude-haiku-4-5-20251001",
        max_tokens: int = 256,
        system_prompt: Optional[str] = None,
    ) -> None:
        try:
            import anthropic as _anthropic
            self._client = _anthropic.Anthropic(api_key=api_key)
        except ImportError as e:
            raise ImportError(
                "Установите anthropic: pip install anthropic"
            ) from e
        self.model = model
        self.max_tokens = max_tokens
        self.system_prompt = system_prompt

    def complete(self, prompt: str) -> str:
        kwargs: Dict[str, Any] = dict(
            model=self.model,
            max_tokens=self.max_tokens,
            messages=[{"role": "user", "content": prompt}],
        )
        if self.system_prompt:
            kwargs["system"] = self.system_prompt
        msg = self._client.messages.create(**kwargs)
        return msg.content[0].text


class MockLLMClient(LLMClient):
    """
    Детерминированный mock для тестов.

    Циклически отдаёт ответы из списка `responses`.
    При пустом списке — всегда возвращает WAIT.

    Атрибуты:
        calls — история поданных промптов.
    """

    _DEFAULT_WAIT = '{"action":"WAIT","text":"","amount":0.0,"reason":"default"}'

    def __init__(self, responses: Optional[List[str]] = None) -> None:
        self.responses: List[str] = responses or []
        self._index: int = 0
        self.calls: List[str] = []

    def complete(self, prompt: str) -> str:
        self.calls.append(prompt)
        if not self.responses:
            return self._DEFAULT_WAIT
        response = self.responses[self._index % len(self.responses)]
        self._index += 1
        return response


# ══════════════════════════════════════════════════════════════════════
# Построитель промптов
# ══════════════════════════════════════════════════════════════════════

class LLMPromptBuilder:
    """
    Формирует нарративный промпт из текущего состояния системы.

    Использует NarrativeVoice.summary() как основной контекст.
    Добавляет сводку последних событий и текущие предложения инициативы.
    """

    @staticmethod
    def build(
        system: "LearningSystem",
        log_entries: List[Dict],
        queries: Optional[List[Any]] = None,
    ) -> str:
        """
        Построить промпт для LLM.

        Параметры:
            system      — LearningSystem для нарратива и proposals
            log_entries — последние N записей из TeachingLog
        """
        from .narrative import NarrativeVoice

        narrative = NarrativeVoice(system).summary()

        # Статистика последних событий
        outcomes = [e.get("outcome", "") for e in log_entries]
        completed  = outcomes.count("COMPLETED")
        refuted    = outcomes.count("REFUTED")
        confirmed  = outcomes.count("CONFIRMED")
        exploring  = outcomes.count("EXPLORING")
        n = len(outcomes)

        # Тренд ресурса
        if log_entries:
            first_r = log_entries[0].get("resource_level", 0.5)
            last_r  = log_entries[-1].get("resource_level", 0.5)
            trend = last_r - first_r
            trend_str = f"{trend:+.3f}"
            resource_mode = log_entries[-1].get("resource_mode", "normal")
        else:
            trend_str = "+0.000"
            resource_mode = "normal"

        # Предложения инициативы
        proposals = system.initiative.last_proposals
        hit_rate  = system.initiative.hit_rate
        if proposals:
            prop_lines = []
            for i, p in enumerate(proposals[:3], 1):
                prop_lines.append(
                    f"  {i}. '{p.label}' → feature_{p.next_feature_id[:6]}… "
                    f"(уверенность={p.confidence:.2f})"
                )
            proposals_str = "\n".join(prop_lines)
        else:
            proposals_str = "  (нет активных предсказаний)"

        # Запросы на восстановление контекста (от SpeechDriver/ContextBroker)
        if queries:
            query_lines = []
            for i, q in enumerate(queries[:5], 1):
                qt = getattr(q, "query_text", str(q))
                tt = getattr(q, "trigger_token", "?")
                gap = getattr(q, "confidence_gap", 0.0)
                query_lines.append(
                    f"  {i}. [{getattr(q, 'trigger_outcome', '?')}] «{tt}»  "
                    f"gap={gap:.2f}\n     → {qt}"
                )
            queries_section = (
                "\n═══ ЗАПРОСЫ НА КОНТЕКСТ ═══\n"
                "Модель вышла за горизонт восприятия. Помоги найти нужный текст:\n"
                + "\n".join(query_lines)
                + "\n"
            )
        else:
            queries_section = ""

        task_action = (
            "  TEACH  — подай текст для обучения (русский, 6-12 слов, повторяющийся паттерн жизни)"
            if not queries else
            "  TEACH  — верни текст, который поможет ответить на запросы выше "
            "(релевантный контекст, 6-20 слов)"
        )

        prompt = f"""Ты — учитель когнитивной модели FirstAGI. Модель учится находить паттерны в потоке токенов.

═══ ТЕКУЩЕЕ СОСТОЯНИЕ ═══
{narrative}

═══ ПОСЛЕДНИЕ {n} СОБЫТИЙ ═══
COMPLETED: {completed}  REFUTED: {refuted}  CONFIRMED: {confirmed}  EXPLORING: {exploring}
Тренд ресурса: {trend_str}  Режим: {resource_mode}

═══ ИНИЦИАТИВА МОДЕЛИ ═══
{proposals_str}
Hit rate: {hit_rate:.0%}
{queries_section}
═══ ТВОЯ ЗАДАЧА ═══
Выбери ОДНО действие:
{task_action}
  REWARD — выдай награду (если много COMPLETED и hit_rate растёт)
  WAIT   — ничего не делать (если модель справляется сама)

Строго ответь JSON:
{{"action":"TEACH"|"REWARD"|"WAIT","text":"...","amount":5.0,"reason":"..."}}"""

        return prompt


# ══════════════════════════════════════════════════════════════════════
# Парсер ответов
# ══════════════════════════════════════════════════════════════════════

class LLMResponseParser:
    """
    Разбирает JSON-ответ LLM в LLMDecision.

    Поддерживает:
      • Чистый JSON: {"action":"TEACH",...}
      • JSON в markdown-блоке: ```json\n{...}\n```
      • Невалидный ответ → None
    """

    # Паттерн для извлечения JSON из markdown-блока
    _MD_PATTERN = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
    # Паттерн для извлечения JSON из произвольного текста
    _JSON_PATTERN = re.compile(r"\{[^{}]*\}", re.DOTALL)

    @classmethod
    def parse(cls, response: str) -> Optional[LLMDecision]:
        """
        Разобрать ответ LLM. Возвращает LLMDecision или None при ошибке.
        """
        if not response or not response.strip():
            return None

        json_str = cls._extract_json(response)
        if json_str is None:
            return None

        try:
            data = json.loads(json_str)
        except (json.JSONDecodeError, ValueError):
            return None

        if not isinstance(data, dict):
            return None

        action = str(data.get("action", "WAIT")).upper()
        if action not in LLMDecision._VALID_ACTIONS:
            action = "WAIT"

        return LLMDecision(
            action=action,
            text=str(data.get("text", "")),
            amount=float(data.get("amount", 0.0)),
            reason=str(data.get("reason", "")),
        )

    @classmethod
    def _extract_json(cls, text: str) -> Optional[str]:
        """Извлечь JSON-строку из текста."""
        # Попробовать markdown-блок
        md_match = cls._MD_PATTERN.search(text)
        if md_match:
            return md_match.group(1)

        # Попробовать чистый JSON
        stripped = text.strip()
        if stripped.startswith("{"):
            return stripped

        # Попробовать найти JSON в тексте
        json_match = cls._JSON_PATTERN.search(text)
        if json_match:
            return json_match.group(0)

        return None


# ══════════════════════════════════════════════════════════════════════
# LLM-воркер
# ══════════════════════════════════════════════════════════════════════

class LLMTeacherWorker:
    """
    Реализует TeacherWorker Protocol через LLM.

    Интегрируется в TeacherScheduler:
        scheduler.add_worker(worker, name="llm")
        scheduler.tick()  # вызывает observe() + suggest_content()

    Принцип одного вызова:
        observe()         → вызывает LLM (rate-limited), кэширует решение
        suggest_content() → использует кэш, затем очищает его

    Параметры:
        system       — LearningSystem (для нарратива и proposals)
        llm_client   — LLMClient (AnthropicClient или MockLLMClient)
        min_interval — минимум секунд между LLM-вызовами (0 = без ограничений)
    """

    def __init__(
        self,
        system: "LearningSystem",
        llm_client: LLMClient,
        min_interval: float = 5.0,
    ) -> None:
        self.system = system
        self.llm = llm_client
        self.min_interval = min_interval

        self._last_call: float = 0.0
        self._cached_decision: Optional[LLMDecision] = None
        self._decision_log: List[LLMDecision] = []
        self.call_count: int = 0
        self._pending_queries: List[Any] = []

    # ------------------------------------------------------------------
    # TeacherWorker Protocol

    def observe(self, log_entries: List[Dict]) -> Optional[RewardOrder]:
        """
        Проанализировать состояние системы через LLM.

        Вызывает LLM если прошёл min_interval.
        Кэширует решение для suggest_content().
        Возвращает RewardOrder при action=REWARD, иначе None.
        """
        decision = self._call_llm_if_ready(log_entries)
        if decision is None:
            return None

        if decision.action == "REWARD" and decision.amount > 0:
            return RewardOrder(
                required_gen_ids=set(),   # безусловная награда
                reward=decision.amount,
                label=decision.reason or "llm_reward",
                max_fires=1,
            )
        return None

    def suggest_content(self, log_entries: List[Dict]) -> Optional[str]:
        """
        Предложить учебный контент на основе кэшированного решения.

        Берёт решение из кэша (оставленного observe()), после чего очищает его.
        Возвращает текст при action=TEACH, иначе None.
        """
        decision = self._cached_decision
        self._cached_decision = None  # потребляем кэш

        if decision is None:
            return None
        if decision.action == "TEACH" and decision.text:
            return decision.text
        return None

    # ------------------------------------------------------------------
    # Внутренняя логика

    def _should_call_llm(self) -> bool:
        """Проверить, прошло ли достаточно времени с последнего вызова."""
        if self.min_interval <= 0:
            return True
        return time.time() - self._last_call >= self.min_interval

    def _call_llm_if_ready(
        self, log_entries: List[Dict]
    ) -> Optional[LLMDecision]:
        """
        Вызвать LLM если готово, кэшировать и вернуть решение.
        Если не готово — вернуть None (не кешировать ничего нового).
        """
        if not self._should_call_llm():
            return None

        try:
            queries = self.system.teaching_log.peek_queries()
            prompt = LLMPromptBuilder.build(self.system, log_entries, queries=queries)
            response = self.llm.complete(prompt)
            decision = LLMResponseParser.parse(response)
        except Exception:
            decision = None
            queries = []

        self._last_call = time.time()
        self.call_count += 1

        if decision is None:
            decision = LLMDecision(action="WAIT", reason="parse_error")

        # Очистить обработанные запросы если LLM ответил TEACH
        if decision.action == "TEACH" and queries:
            self.system.teaching_log.clear_queries()

        self._cached_decision = decision
        self._decision_log.append(decision)

        return decision

    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Статистика воркера."""
        last_call_age = time.time() - self._last_call if self._last_call > 0 else -1
        return {
            "call_count":       self.call_count,
            "last_call_age":    round(last_call_age, 1),
            "decision_history": [d.action for d in self._decision_log[-10:]],
        }

    def __repr__(self) -> str:
        return (
            f"LLMTeacherWorker("
            f"calls={self.call_count}, "
            f"min_interval={self.min_interval}s)"
        )
