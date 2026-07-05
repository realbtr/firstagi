"""
ProvisionalBase — испытательный срок для новых обобщений.

Проблема: на REFUTED система немедленно добавляет новый Gen в базу.
Результат: 14K Gen из «Дома который построил Джек» — большинство шумовые.

Решение: Gen добавляется в GeneralizationBase как обычно (контекст работает
нормально), НО параллельно отслеживается ProvisionalBase.

Жизненный цикл provisional Gen:
  1. REFUTED → Gen добавлен в base → provisional.track(gen_id)
  2. CONFIRMED для tracked gen → provisional.confirm(gen_id)
       • confirmations < min_confirmations → остаётся на испытании
       • confirmations >= min_confirmations → promoted (снят с испытания, в базе навсегда)
  3. Каждый step() → provisional.tick():
       • age <= max_age → просто стареет
       • age > max_age AND confirmations == 0 → EVICT:
         caller должен вызвать base.remove(gen_id) + context.remove_active(gen_id)

Благодаря тому, что Gen находится в GeneralizationBase:
  • context.get_expected_features() видит его нормально
  • confirm_feature() / refute_feature() работают без изменений
  • GreedyGeneralizer работает (base.get() возвращает ген)

Но GreedyGeneralizer НЕ строит цепочки из provisional Gen — он проверяет
base.search_by_chain(), и provisional ген не отличается от обычного. Это
нормально: цепочки строятся из ЛЮБЫХ confirmed Gen, но provisional Gen
слишком молоды чтобы набрать много CONFIRMED, поэтому редко участвуют в цепях.

Параметры по умолчанию:
  min_confirmations = 2   — 2 подтверждения = реальный паттерн
  max_age           = 30  — 30 шагов без подтверждений = шум → удалить
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


# ══════════════════════════════════════════════════════════════════════════════
# ProvisionalEntry
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ProvisionalEntry:
    """Запись об одном Gen на испытательном сроке."""
    gen_id:        str
    confirmations: int = 0   # сколько раз подтверждён с момента создания
    age:           int = 0   # шагов с момента попадания на испытание


# ══════════════════════════════════════════════════════════════════════════════
# ProvisionalBase
# ══════════════════════════════════════════════════════════════════════════════

class ProvisionalBase:
    """
    Трекер новых Gen на испытательном сроке.

    Не хранит сами Gen — только отслеживает gen_id в GeneralizationBase.
    Контролирует когда Gen «промотировать» (снять испытание) или «вытеснить»
    (удалить из базы как шум).

    Параметры
    ---------
    min_confirmations : int
        Подтверждений для снятия испытательного срока.
    max_age : int
        Максимальный возраст (шагов) без подтверждений; затем — вытеснение.
    """

    def __init__(
        self,
        min_confirmations: int = 2,
        max_age: int = 30,
    ) -> None:
        self.min_confirmations = min_confirmations
        self.max_age = max_age

        self._entries: Dict[str, ProvisionalEntry] = {}

        # Накопленная статистика
        self._promoted: int = 0
        self._evicted:  int = 0

    # ------------------------------------------------------------------
    # Добавление / запрос

    def track(self, gen_id: str) -> None:
        """
        Поставить Gen на испытательный срок.

        Вызывать после добавления нового Gen в GeneralizationBase.
        """
        self._entries[gen_id] = ProvisionalEntry(gen_id=gen_id)

    def is_tracked(self, gen_id: str) -> bool:
        """Находится ли Gen на испытательном сроке."""
        return gen_id in self._entries

    def size(self) -> int:
        """Число Gen на испытательном сроке прямо сейчас."""
        return len(self._entries)

    # ------------------------------------------------------------------
    # Жизненный цикл

    def confirm(self, gen_id: str) -> bool:
        """
        Зафиксировать подтверждение для Gen.

        Возвращает True если Gen «промотирован» (снят с испытания, остаётся
        в базе навсегда). Возвращает False если нужно ещё подтверждений.
        Если gen_id не отслеживается — ничего не делает, возвращает False.
        """
        entry = self._entries.get(gen_id)
        if entry is None:
            return False
        entry.confirmations += 1
        if entry.confirmations >= self.min_confirmations:
            del self._entries[gen_id]
            self._promoted += 1
            return True
        return False

    def tick(self) -> List[str]:
        """
        Постарить все отслеживаемые Gen на один шаг.

        Возвращает список gen_id, которые нужно ВЫТЕСНИТЬ:
        вызывающий код должен удалить их из GeneralizationBase и контекста.

        Критерий вытеснения: age > max_age И confirmations == 0.
        """
        evict_ids: List[str] = []
        for gen_id, entry in list(self._entries.items()):
            entry.age += 1
            if entry.age > self.max_age and entry.confirmations == 0:
                evict_ids.append(gen_id)
                del self._entries[gen_id]
                self._evicted += 1
        return evict_ids

    def remove(self, gen_id: str) -> None:
        """
        Снять Gen с испытания без промоции и без вытеснения.

        Используется когда Gen удалён по другой причине (CapacityBudget и т.п.)
        """
        self._entries.pop(gen_id, None)

    # ------------------------------------------------------------------
    # Статистика

    def stats(self) -> dict:
        """Сводная статистика."""
        entries = list(self._entries.values())
        avg_age  = sum(e.age for e in entries) / len(entries) if entries else 0.0
        avg_conf = sum(e.confirmations for e in entries) / len(entries) if entries else 0.0
        return {
            "pending":   self.size(),
            "promoted":  self._promoted,
            "evicted":   self._evicted,
            "avg_age":   round(avg_age, 1),
            "avg_conf":  round(avg_conf, 2),
        }

    def __repr__(self) -> str:
        s = self.stats()
        return (
            f"ProvisionalBase("
            f"pending={s['pending']}, "
            f"promoted={s['promoted']}, "
            f"evicted={s['evicted']})"
        )
