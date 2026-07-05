"""
core/active_query_bridge.py — Автоматическое возобновление при IDLE.

Когда буферы драйверов пусты и система не может обработать ни одного токена,
ActiveQueryBridge формирует запрос на основе:

  1. Gen с наименьшим числом подтверждений (least confirmed)
  2. Gen на испытательном сроке (ProvisionalBase)
  3. Домен из меток Gen (label-based domain detection)
  4. Контекстная подсказка (ожидания активных Gen)
  5. Fallback: запросить любой текст из реестра

Алгоритм:
  1. AttentionLoop.step() → IDLE
  2. ActiveQueryBridge.on_idle() → ContextQuery
  3. ContextBroker.handle_query(query, driver) → True/False
  4. Если True → буфер пополнен → AttentionLoop.step() продолжает
  5. Если False → TeachingLog → LLM → resume_after_llm()
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .learning import LearningSystem
    from .generalization import GeneralizationBase
    from drivers.context_broker import ContextBroker
    from drivers.speech_driver import ContextQuery


# ══════════════════════════════════════════════════════════════════════
# Результат попытки возобновления
# ══════════════════════════════════════════════════════════════════════

@dataclass
class BridgeResult:
    """Результат работы ActiveQueryBridge.on_idle()."""
    query_generated: bool = False
    query_resolved: bool = False
    query_sent_to_llm: bool = False
    query: Optional["ContextQuery"] = None
    reason: str = ""
    strategy: str = ""


# ══════════════════════════════════════════════════════════════════════
# Ключевые слова доменов
# ══════════════════════════════════════════════════════════════════════

_DOMAIN_KEYWORDS = {
    "лес": ["лес", "дерево", "заяц", "медведь", "гриб", "ягод", "птиц",
            "рек", "опушк", "дуб", "ёжик", "белк", "олен", "кукушк",
            "волк", "лис", "сова", "маша"],
    "город": ["улиц", "дом", "магазин", "парк", "скамейк", "машин",
              "человек", "окн", "квартир", "кот", "пёс", "собак",
              "попугай", "хомяк", "черепах", "мышк", "кролик", "рыбк"],
    "море": ["мор", "волн", "рыб", "пляж", "берег", "корабл", "ракушк",
             "дн", "прилив", "чайк", "краб", "дельфин", "морж",
             "осьминог", "медуз", "конёк", "лев"],
    "горы": ["гор", "вершин", "скал", "перевал", "троп", "снег",
             "камн", "солнц", "поднож", "хребет", "ущель"],
}


# ══════════════════════════════════════════════════════════════════════
# ActiveQueryBridge
# ══════════════════════════════════════════════════════════════════════

class ActiveQueryBridge:
    """
    Автоматическое возобновление при IDLE.

    Стратегии (по приоритету):

      1. LEAST_CONFIRMED — Gen с наименьшим success_count
         «Система знает о X, но мало подтвердила — нужно больше данных»
      2. PROVISIONAL_HUNT — Gen на испытательном сроке
         «Система пыталась понять X при REFUTED — нужно помочь»
      3. DOMAIN_GAP — Домен определён по меткам, но мало Gen
         «Система мало знает о домене D»
      4. CONTEXT_HINT — Активные Gen в контексте
         «Система ждёт продолжения паттерна X»
      5. FALLBACK — Запросить любой текст из реестра
         «Системе нужны данные, любые данные»
    """

    def __init__(
        self,
        system:   "LearningSystem",
        broker:   "ContextBroker",
        driver_id: str = "text",
    ) -> None:
        self._system = system
        self._broker = broker
        self._driver_id = driver_id
        self._idle_count: int = 0
        self._queries_made: int = 0
        self._queries_resolved: int = 0
        self._strategies_used: dict = {}

    # ------------------------------------------------------------------
    # Основной метод
    # ------------------------------------------------------------------

    def on_idle(self) -> BridgeResult:
        """Обработать IDLE: сформировать запрос и разрешить через broker."""
        self._idle_count += 1

        strategies = [
            ("LEAST_CONFIRMED", self._try_least_confirmed),
            ("PROVISIONAL_HUNT", self._try_provisional_hunt),
            ("DOMAIN_GAP", self._try_domain_gap),
            ("CONTEXT_HINT", self._try_context_hint),
            ("FALLBACK", self._try_fallback),
        ]

        for name, fn in strategies:
            query = fn()
            if query is not None:
                return self._resolve(query, name)

        return BridgeResult(
            query_generated=False,
            reason="no_strategy_applicable",
        )

    # ------------------------------------------------------------------
    # Стратегия 1: Gen с наименьшим числом подтверждений
    # ------------------------------------------------------------------

    def _try_least_confirmed(self) -> Optional["ContextQuery"]:
        """
        Gen с наименьшим success_count — система начала обобщать,
        но не получила достаточно данных для подтверждения.
        """
        from drivers.speech_driver import ContextQuery

        base = self._system.base
        gens = base.all()
        if not gens:
            return None

        # Сортируем по success_count (восходяще) — слабые первыми
        weak = sorted(gens, key=lambda g: g.success_count)[:5]
        if not weak:
            return None

        # Берём тот, у которого chain ≥ 2 (не атомарный)
        target = None
        for g in weak:
            if len(g.feature_chain) >= 2:
                target = g
                break
        if target is None:
            target = weak[0]

        label = target.label or target.gen_id[:8]
        return ContextQuery(
            trigger_token=f"[weak:{label}]",
            trigger_outcome="IDLE",
            missing_hint=label,
            query_text=(
                f"Система начала обобщать паттерн «{label}» "
                f"(success={target.success_count}, stop={target.stop_count}, "
                f"chain={len(target.feature_chain)}). "
                f"Нужны дополнительные примеры для подтверждения."
            ),
            confidence_gap=1.0 - target.significance,
        )

    # ------------------------------------------------------------------
    # Стратегия 2: Gen на испытательном сроке
    # ------------------------------------------------------------------

    def _try_provisional_hunt(self) -> Optional["ContextQuery"]:
        """
        Gen, созданные при REFUTED, ещё не подтверждены.
        Система «пыталась понять» — нужно помочь.
        """
        from drivers.speech_driver import ContextQuery

        provisional = getattr(self._system.engine, '_provisional', None)
        if provisional is None:
            return None

        entries = getattr(provisional, '_entries', {})
        if not entries:
            return None

        # Взять первого кандидата
        gen_id = next(iter(entries))
        gen = self._system.base.get(gen_id)
        if gen is None:
            return None

        label = gen.label or gen_id[:8]
        return ContextQuery(
            trigger_token=f"[provisional:{label}]",
            trigger_outcome="IDLE",
            missing_hint=label,
            query_text=(
                f"Система создала обобщение «{label}» при опровержении "
                f"(success={gen.success_count}, stop={gen.stop_count}), "
                f"но оно ещё не подтверждено. "
                f"Нужны данные для подтверждения или опровержения."
            ),
            confidence_gap=0.8,
        )

    # ------------------------------------------------------------------
    # Стратегия 3: Доменный пробел
    # ------------------------------------------------------------------

    def _try_domain_gap(self) -> Optional["ContextQuery"]:
        """
        Если метки Gen указывают на домен, но в базе мало Gen этого домена.
        """
        from drivers.speech_driver import ContextQuery

        domain = self._detect_domain()
        if domain is None:
            return None

        # Подсчитать Gen, относящиеся к домену
        keywords = _DOMAIN_KEYWORDS.get(domain, [])
        domain_gens = [
            g for g in self._system.base.all()
            if g.label and any(kw in g.label.lower() for kw in keywords)
        ]

        if len(domain_gens) > 3:
            return None  # Домен достаточно покрыт

        return ContextQuery(
            trigger_token=f"[domain:{domain}]",
            trigger_outcome="IDLE",
            missing_hint=domain,
            query_text=(
                f"Система работает в домене «{domain}», "
                f"но в базе только {len(domain_gens)} обобщений. "
                f"Нужны тексты из этого домена для расширения опыта."
            ),
            confidence_gap=0.6,
        )

    # ------------------------------------------------------------------
    # Стратегия 4: Контекстная подсказка
    # ------------------------------------------------------------------

    def _try_context_hint(self) -> Optional["ContextQuery"]:
        """
        Активные Gen в контексте указывают на ожидаемый паттерн.
        """
        from drivers.speech_driver import ContextQuery

        context = self._system.engine.context
        active_ids = list(context.active_gen_ids())
        if not active_ids:
            return None

        # Gen с наибольшей цепочкой (самый конкретный)
        best = None
        best_chain = 0
        for gid in active_ids:
            gen = self._system.base.get(gid)
            if gen and len(gen.feature_chain) > best_chain:
                best = gen
                best_chain = len(gen.feature_chain)

        if best is None:
            return None

        label = best.label or best.gen_id[:8]
        return ContextQuery(
            trigger_token=f"[context:{label}]",
            trigger_outcome="IDLE",
            missing_hint=label,
            query_text=(
                f"Система ожидает продолжения паттерна «{label}» "
                f"(chain={best_chain}, sig={best.significance:.2f}). "
                f"Нужны данные для проверки этого ожидания."
            ),
            confidence_gap=1.0 - best.significance,
        )

    # ------------------------------------------------------------------
    # Стратегия 5: Fallback — любой текст
    # ------------------------------------------------------------------

    def _try_fallback(self) -> Optional["ContextQuery"]:
        """
        Если ничего не подошло — запросить любой текст из реестра.
        Это «голодная» стратегия: система готова учиться, данных нет.
        """
        from drivers.speech_driver import ContextQuery

        # Проверить, есть ли что в реестре
        registry = self._broker.registry
        if registry.size() == 0:
            return None

        # Взять метку из последних Gen (если есть)
        gens = self._system.base.all()
        hint = ""
        if gens:
            latest = max(gens, key=lambda g: g.success_count + g.stop_count)
            hint = latest.label or latest.gen_id[:8]

        return ContextQuery(
            trigger_token="[fallback:request_any]",
            trigger_outcome="IDLE",
            missing_hint=hint or "текст",
            query_text=(
                f"Система готова к обучению, но буферы пусты. "
                f"Запрос: предоставить любой текст для продолжения. "
                f"Доминирующий контекст: «{hint}»" if hint
                else "Система готова к обучению. Предоставьте текст."
            ),
            confidence_gap=0.5,
        )

    # ------------------------------------------------------------------
    # Определение домена
    # ------------------------------------------------------------------

    def _detect_domain(self) -> Optional[str]:
        """Определить домен из меток Gen в базе."""
        gens = self._system.base.all()
        if not gens:
            return None

        # Собрать все метки
        all_labels = " ".join(
            g.label.lower() for g in gens if g.label
        )

        if not all_labels:
            return None

        # Найти домен с наибольшим числом совпадений
        best_domain = None
        best_score = 0
        for domain, keywords in _DOMAIN_KEYWORDS.items():
            score = sum(1 for kw in keywords if kw in all_labels)
            if score > best_score:
                best_score = score
                best_domain = domain

        return best_domain if best_score >= 3 else None

    # ------------------------------------------------------------------
    # Разрешение запроса
    # ------------------------------------------------------------------

    def _resolve(self, query: "ContextQuery", strategy: str) -> BridgeResult:
        """Попытаться разрешить запрос через ContextBroker."""
        self._queries_made += 1
        self._strategies_used[strategy] = self._strategies_used.get(strategy, 0) + 1

        resolved = self._broker.handle_query(query, driver=None)

        if resolved:
            self._queries_resolved += 1
            return BridgeResult(
                query_generated=True,
                query_resolved=True,
                query=query,
                reason=f"resolved_locally via {strategy}",
                strategy=strategy,
            )
        else:
            return BridgeResult(
                query_generated=True,
                query_resolved=False,
                query_sent_to_llm=True,
                query=query,
                reason=f"sent_to_llm via {strategy}",
                strategy=strategy,
            )

    # ------------------------------------------------------------------
    # Статистика
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        return {
            "idle_count": self._idle_count,
            "queries_made": self._queries_made,
            "queries_resolved": self._queries_resolved,
            "strategies_used": dict(self._strategies_used),
            "resolution_rate": (
                self._queries_resolved / self._queries_made
                if self._queries_made > 0 else 0.0
            ),
        }

    def __repr__(self) -> str:
        return (
            f"ActiveQueryBridge("
            f"queries={self._queries_made}, "
            f"resolved={self._queries_resolved}, "
            f"strategies={self._strategies_used})"
        )
