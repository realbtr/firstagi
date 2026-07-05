"""
Шаг 13б: MemoryDriver — драйвер долговременной памяти.

Хранит историю подтверждённых паттернов и реплицирует их по приоритету.
Является PeripheralDriver: зарегистрирован в PeripheralManager при
низком приоритете — ядро обращается к нему автоматически, когда
все внешние буферы пусты.

Принцип работы:
  ПАССИВНЫЙ режим (active=False):
    • record() накапливает опыт при каждом CONFIRMED/COMPLETED
    • buffer_size = 0 → AttentionLoop не видит и не запрашивает
  АКТИВНЫЙ режим (active=True):
    • buffer_size = реальное количество записей (с учётом лимита цикла)
    • query() возвращает приоритетный токен для replay
    • AttentionLoop обращается к памяти когда TextDriver пуст

Приоритет воспроизведения:
  Высокий → слабые Gen (sig ≈ 0), мало воспроизводились, недавние
  Низкий  → сильные Gen (sig ≈ 1), много воспроизводились, давние

Это гарантирует, что «тёмные пятна» — обобщения, которые редко
подтверждались и плохо различают ситуации — получают больше внимания.
Морфология и семантические различия возникают естественно через накопление
replay, а не через хардкодинг.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from core.generalization import PeripheralToken
from .base import PeripheralDriver

if TYPE_CHECKING:
    from core.feature import Feature


# ══════════════════════════════════════════════════════════════════════
# Запись в памяти
# ══════════════════════════════════════════════════════════════════════

@dataclass
class MemoryEntry:
    """Одна запись в долговременной памяти ядра."""
    token:        PeripheralToken        # токен, который был подтверждён
    sig:          float                  # значимость Gen в момент записи
    gen_ids:      Tuple[str, ...]        # активные Gen в момент записи
    step_n:       int                    # порядковый номер записи
    replay_count: int = field(default=0) # сколько раз воспроизводился


# ══════════════════════════════════════════════════════════════════════
# MemoryDriver
# ══════════════════════════════════════════════════════════════════════

class MemoryDriver(PeripheralDriver):
    """
    Драйвер долговременной памяти ядра.

    Зарегистрировать в PeripheralManager с низким приоритетом:
        app.peripherals.register(memory_driver, priority=1)

    Управление режимом:
        memory.activate()    — включить replay (consolidation)
        memory.deactivate()  — выключить (только запись)
        memory.new_cycle()   — сбросить счётчик шагов цикла

    Запись опыта происходит автоматически через AttentionLoop.
    Явный вызов: memory.record(token, sig, gen_ids)

    Пример использования:
        session.consolidate(n_steps=50)   # в DebugSession
    """

    DRIVER_ID = "memory"

    def __init__(
        self,
        driver_id:        str = "memory",
        max_entries:      int = 2000,
        replay_per_cycle: int = 100,
    ) -> None:
        super().__init__(driver_id)
        self._entries:         List[MemoryEntry] = []
        self._max_entries      = max_entries
        self._replay_per_cycle = replay_per_cycle
        self._cycle_replays:   int  = 0
        self._total_recorded:  int  = 0
        self._total_replays:   int  = 0
        self._active:          bool = False   # пассивен по умолчанию

    # ------------------------------------------------------------------
    # Режим

    def activate(self, new_cycle: bool = True) -> None:
        """Включить режим replay. Теперь buffer_size > 0 и AttentionLoop видит память."""
        self._active = True
        if new_cycle:
            self.new_cycle()

    def deactivate(self) -> None:
        """Выключить режим replay. buffer_size → 0, AttentionLoop игнорирует."""
        self._active = False

    def new_cycle(self) -> None:
        """Начать новый цикл replay (сбросить счётчик шагов цикла)."""
        self._cycle_replays = 0

    @property
    def is_active(self) -> bool:
        return self._active

    # ------------------------------------------------------------------
    # Запись опыта

    def record(
        self,
        token:   PeripheralToken,
        sig:     float,
        gen_ids: Tuple[str, ...] = (),
    ) -> None:
        """
        Записать подтверждённый токен в долговременную память.

        sig — значимость Gen на момент записи [0..1].
        Записи с низкой sig получают приоритет при воспроизведении.
        """
        self._total_recorded += 1
        entry = MemoryEntry(
            token   = token,
            sig     = max(0.0, min(1.0, sig)),
            gen_ids = gen_ids,
            step_n  = self._total_recorded,
        )
        self._entries.append(entry)

        # Ограничение размера: удаляем наиболее воспроизведённые записи
        # (они уже закреплены — им меньше всего нужна память)
        if len(self._entries) > self._max_entries:
            self._entries.sort(key=lambda e: -e.replay_count)
            self._entries.pop(0)

    # ------------------------------------------------------------------
    # Воспроизведение

    def query(self, feature: Optional["Feature"] = None) -> Optional[PeripheralToken]:
        """
        Вернуть приоритетный токен из памяти для replay.

        feature — если задан, предпочитаем записи близкие к этому вектору
                  (ядро запрашивает что-то конкретное, мы ищем похожее в памяти).

        Возвращает None если:
          • память пуста
          • лимит cycle_replays исчерпан (→ IDLE, конец цикла)
          • режим deactivated
        """
        if not self._active or not self._entries:
            return None
        if self._cycle_replays >= self._replay_per_cycle:
            return None

        if feature is not None and hasattr(feature, "vector"):
            # Найти топ-10 близких по вектору, затем выбрать по приоритету
            scored: List[Tuple[MemoryEntry, float]] = []
            for e in self._entries:
                if hasattr(e.token.data, "vector"):
                    d = feature.vector.distance_to(e.token.data.vector)
                    scored.append((e, d))
            scored.sort(key=lambda x: x[1])
            candidates = [e for e, _ in scored[:10]] if scored else self._entries
        else:
            candidates = self._entries

        best = max(candidates, key=self._priority)
        best.replay_count     += 1
        self._cycle_replays   += 1
        self._total_replays   += 1

        # Создать свежий токен (новый token_id) — иначе цикл-детектор его отклонит
        fresh = PeripheralToken.new(driver_id=self.driver_id, data=best.token.data,
                                    label=best.token.label)
        return fresh

    # ------------------------------------------------------------------
    # buffer_size — переопределяем для управления видимостью

    @property
    def buffer_size(self) -> int:
        """
        Эффективный «размер буфера».

        0   — если не активен или цикл исчерпан (AttentionLoop не видит).
        N   — оставшийся лимит шагов в текущем цикле (привлекает внимание).
        """
        if not self._active or not self._entries:
            return 0
        remaining = self._replay_per_cycle - self._cycle_replays
        return max(0, min(remaining, len(self._entries)))

    # ------------------------------------------------------------------
    # Диагностика

    def stats(self) -> Dict[str, Any]:
        """Сводная статистика памяти."""
        n = len(self._entries)
        sigs = [e.sig for e in self._entries]
        return {
            "entries":        n,
            "total_recorded": self._total_recorded,
            "total_replays":  self._total_replays,
            "cycle_replays":  self._cycle_replays,
            "cycle_limit":    self._replay_per_cycle,
            "active":         self._active,
            "weak_entries":   sum(1 for s in sigs if s < 0.5),
            "avg_sig":        round(sum(sigs) / n, 4) if n else 0.0,
            "min_sig":        round(min(sigs), 4) if n else 0.0,
        }

    def weak_entries(self, max_sig: float = 0.5) -> List[MemoryEntry]:
        """Записи, соответствующие слабым Gen (sig < max_sig)."""
        return sorted(
            [e for e in self._entries if e.sig < max_sig],
            key=lambda e: e.sig,
        )

    def focus_gen(self, gen_id: str) -> int:
        """
        Поднять приоритет всех записей связанных с gen_id.

        Устанавливает replay_count=0 для этих записей —
        они станут наиболее приоритетными при следующем цикле.
        Возвращает количество затронутых записей.
        """
        count = 0
        for e in self._entries:
            if gen_id in e.gen_ids:
                e.replay_count = 0
                count += 1
        return count

    # ------------------------------------------------------------------
    # PeripheralDriver protocol (required by ABC)

    def produce(self):
        """MemoryDriver не производит потоки — только отвечает на запросы."""
        return iter([])

    def reset(self) -> None:
        """Сбросить состояние цикла (не очищает память)."""
        self.deactivate()
        self.new_cycle()

    def clear(self) -> None:
        """Полностью очистить память."""
        self._entries.clear()
        self._total_recorded = 0
        self._total_replays = 0
        self._cycle_replays = 0

    # ------------------------------------------------------------------

    def _priority(self, entry: MemoryEntry) -> float:
        """
        Приоритет воспроизведения записи.

        Высокий → слабые Gen (sig≈0), мало воспроизводились, недавние.
        Низкий  → сильные Gen (sig≈1), много воспроизводились, давние.
        """
        sig_score     = 1.0 - entry.sig
        replay_penalty = min(entry.replay_count * 0.15, 0.6)
        recency_bonus = (entry.step_n / max(self._total_recorded, 1)) * 0.1
        return sig_score - replay_penalty + recency_bonus

    def __repr__(self) -> str:
        return (
            f"MemoryDriver("
            f"entries={len(self._entries)}, "
            f"active={self._active}, "
            f"cycle={self._cycle_replays}/{self._replay_per_cycle})"
        )
