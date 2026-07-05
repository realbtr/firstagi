"""
Шаг 4: Система обучения — Внутренний Учитель и Брокер состояний.

TeacherDriver (Тактический уровень):
  Синхронный наблюдатель. Вызывается после каждого step() Ядра.
  Хранит «Ордера на награду»: если активен нужный набор Gen →
  мгновенный вброс ресурса + усиление целевых обобщений.

TeachingLog (Стратегический уровень):
  Брокер состояний между Ядром и асинхронными LLM-учителями.
  Ядро пишет лог → LLM читает → ставит новые ордера / контент.

Программное API (первый этап):
  teacher.add_order(required_gen_ids={g1, g2}, reward=50.0, label="...", max_fires=3)
  log.push_reward_order(order)
  log.push_content(token)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .generalization import Generalization, GeneralizationBase
from .context import ContextBuffer
from .algorithm import StepResult
from .resource import ResourceDriver, ResourceState


# ══════════════════════════════════════════════════════════════════════
# Ордер на награду
# ══════════════════════════════════════════════════════════════════════

@dataclass
class RewardOrder:
    """
    Условие → Награда.

    Когда все gen_id из required_gen_ids одновременно активны
    в контексте, TeacherDriver срабатывает:
      1. Вбрасывает reward единиц ресурса.
      2. Увеличивает success_count целевых Gen.

    max_fires = -1  → без ограничений.
    max_fires =  1  → сработать один раз и замолчать.
    """
    required_gen_ids: Set[str]
    reward: float
    label: str = ""
    max_fires: int = -1
    fired_count: int = field(default=0, init=False)

    def is_exhausted(self) -> bool:
        return self.max_fires >= 0 and self.fired_count >= self.max_fires

    def matches(self, active_gen_ids: Set[str]) -> bool:
        return not self.is_exhausted() and self.required_gen_ids.issubset(active_gen_ids)


# ══════════════════════════════════════════════════════════════════════
# Внутренний Учитель (тактический уровень)
# ══════════════════════════════════════════════════════════════════════

class TeacherDriver:
    """
    Синхронный внутренний учитель.

    Встроен в цикл LearningSystem.process_token().
    Проверяет ордера ПОСЛЕ engine.step() — пока контекст ещё «горячий».
    Срабатывает за миллисекунды.

    Пример использования:
        teacher.add_order(
            required_gen_ids={"gen-abc", "gen-xyz"},
            reward=100.0,
            label="форма + цвет одновременно",
            max_fires=3,
        )
    """

    def __init__(self, resource: ResourceDriver) -> None:
        self.resource = resource
        self._orders: List[RewardOrder] = []
        self._fired_log: List[Dict] = []   # история срабатываний
        self._step_count: int = 0

    # ------------------------------------------------------------------
    # Управление ордерами (программное API)

    def add_order(
        self,
        required_gen_ids: Set[str],
        reward: float,
        label: str = "",
        max_fires: int = -1,
    ) -> RewardOrder:
        """Зарегистрировать ордер на награду."""
        order = RewardOrder(
            required_gen_ids=set(required_gen_ids),
            reward=reward,
            label=label,
            max_fires=max_fires,
        )
        self._orders.append(order)
        return order

    def remove_order(self, order: RewardOrder) -> None:
        """Отозвать ордер."""
        self._orders = [o for o in self._orders if o is not order]

    def clear_orders(self) -> None:
        """Удалить все ордера."""
        self._orders.clear()

    def clear_exhausted(self) -> int:
        """Удалить истощённые ордера. Возвращает число удалённых."""
        before = len(self._orders)
        self._orders = [o for o in self._orders if not o.is_exhausted()]
        return before - len(self._orders)

    # ------------------------------------------------------------------
    # Срабатывание

    def check_and_fire(
        self,
        context: ContextBuffer,
        base: GeneralizationBase,
    ) -> float:
        """
        Проверить ордера, выдать награду при совпадении.
        Вызывается синхронно после каждого engine.step().
        Возвращает суммарную выданную награду (0.0 если ничего не сработало).
        """
        self._step_count += 1
        active = set(context.active_gen_ids())
        total = 0.0

        for order in self._orders:
            if not order.matches(active):
                continue

            # Мгновенный вброс ресурса
            self.resource.add_reward(order.reward)

            # Усилить целевые Gen в базе
            bonus = max(1, int(order.reward / 10))
            for gid in order.required_gen_ids:
                gen = base.get(gid)
                if gen:
                    gen.success_count += bonus

            order.fired_count += 1
            total += order.reward

            self._fired_log.append({
                "step": self._step_count,
                "label": order.label,
                "reward": order.reward,
                "active_sample": list(active)[:5],
            })

        return total

    # ------------------------------------------------------------------
    # Состояние

    @property
    def active_order_count(self) -> int:
        return sum(1 for o in self._orders if not o.is_exhausted())

    @property
    def total_fired_reward(self) -> float:
        return sum(e["reward"] for e in self._fired_log)

    def fired_log(self, last_n: int = 20) -> List[Dict]:
        return self._fired_log[-last_n:]

    def __repr__(self) -> str:
        return (f"TeacherDriver("
                f"orders={len(self._orders)}, "
                f"fired={len(self._fired_log)}, "
                f"resource={self.resource.level:.3f})")


# ══════════════════════════════════════════════════════════════════════
# Брокер состояний (стратегический уровень)
# ══════════════════════════════════════════════════════════════════════

class TeachingLog:
    """
    Асинхронный брокер: Ядро → LLM-учителя → обратно в Ядро.

    Ядро пишет состояния в лог.
    LLM-учителя (внешние процессы) читают лог и:
      а) ставят новые ордера через push_reward_order()
      б) подбрасывают учебный контент через push_content()
    Ядро забирает их через pop_pending_orders() / pop_content().

    На первом этапе — in-memory очередь.
    Позже заменяется на Redis/Kafka/etc. без изменения интерфейса.
    """

    def __init__(self, max_entries: int = 1000) -> None:
        self._log: List[Dict] = []
        self._max_entries = max_entries
        self._pending_orders: List[RewardOrder] = []
        self._pending_content: List[Any] = []
        self._pending_queries: List[Any] = []  # ContextQuery objects

    # ------------------------------------------------------------------
    # Запись состояния (Ядро → Лог)

    def log_state(
        self,
        step_result: StepResult,
        resource: ResourceState,
        active_gen_ids: List[str],
    ) -> None:
        """Записать мгновенное состояние Ядра. Вызывается из process_token."""
        entry = {
            "step":           len(self._log),
            "outcome":        step_result.outcome.name,
            "matched_feat":   step_result.matched_feature_id,
            "resource_level": round(resource.level, 4),
            "resource_mode":  resource.mode,
            "active_gens":    active_gen_ids[:10],
            "new_gen_id":     step_result.new_gen_id,
            "completed_gens": step_result.completed_gen_ids,
            "removed_gens":   step_result.removed_gen_ids,
        }
        self._log.append(entry)
        if len(self._log) > self._max_entries:
            self._log = self._log[-self._max_entries:]

    def get_recent(self, n: int = 20) -> List[Dict]:
        """Последние n записей лога — для чтения LLM-учителем."""
        return self._log[-n:]

    def size(self) -> int:
        return len(self._log)

    # ------------------------------------------------------------------
    # Очередь ордеров (LLM → Ядро)

    def push_reward_order(self, order: RewardOrder) -> None:
        """LLM-учитель ставит новый ордер на награду."""
        self._pending_orders.append(order)

    def pop_pending_orders(self) -> List[RewardOrder]:
        """Ядро забирает накопившиеся ордера от LLM-учителей."""
        orders = list(self._pending_orders)
        self._pending_orders.clear()
        return orders

    # ------------------------------------------------------------------
    # Очередь учебного контента (LLM → Ядро)

    def push_content(self, content: Any) -> None:
        """LLM-учитель подбрасывает учебный токен/текст."""
        self._pending_content.append(content)

    def pop_content(self) -> Optional[Any]:
        """Ядро забирает следующий учебный элемент."""
        return self._pending_content.pop(0) if self._pending_content else None

    def pending_content_count(self) -> int:
        return len(self._pending_content)

    # ------------------------------------------------------------------
    # Очередь контекстных запросов (SpeechDriver/ContextBroker → LLM)

    def push_query(self, query: Any) -> None:
        """Поставить запрос на восстановление контекста за горизонтом восприятия."""
        self._pending_queries.append(query)

    def peek_queries(self, n: int = 10) -> List[Any]:
        """Прочитать накопившиеся запросы без изъятия (для LLMPromptBuilder)."""
        return list(self._pending_queries[-n:])

    def clear_queries(self) -> None:
        """Сбросить очередь запросов (вызывается после обработки LLM-ответа)."""
        self._pending_queries.clear()

    def pending_query_count(self) -> int:
        return len(self._pending_queries)

    def __repr__(self) -> str:
        return (f"TeachingLog("
                f"entries={len(self._log)}, "
                f"pending_orders={len(self._pending_orders)}, "
                f"pending_content={len(self._pending_content)})")
