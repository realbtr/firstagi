"""
Шаг 11: AttentionLoop — петля активного внимания.

Замыкает цикл:
    InitiativeEngine.propose() → next_feature_id
        → driver.query(feature)
        → token
        → system.process_token(token)
        → обновлённый контекст
        → новые proposals
        → (цикл)

Модель сама инициирует движение внимания, опрашивая периферийные
драйверы вместо того, чтобы пассивно ждать подачи данных учителем.
Данные никогда не загружаются принудительно — только через запрос.

Использование:
    loop = AttentionLoop(app.system, app.peripherals)
    loop.load_buffer("кот сидит на окне")
    steps = loop.run(20)
    for s in steps:
        print(s.outcome, s.buffer_sizes)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from .learning import LearningSystem
    from core.peripheral import PeripheralManager
    from drivers.memory_driver import MemoryDriver


# ══════════════════════════════════════════════════════════════════════
# Результат одного шага активного внимания
# ══════════════════════════════════════════════════════════════════════

@dataclass
class AttentionStep:
    """Результат одного шага AttentionLoop."""
    step_n:               int
    proposal_feature_id:  Optional[str]    # feature_id который ожидала система
    driver_queried:       Optional[str]    # id драйвера, который был запрошен
    outcome:              str              # CONFIRMED/REFUTED/EXPLORING/IDLE
    new_gens:             int              # новые Gen за этот шаг
    buffer_sizes:         Dict[str, int]   # размеры буферов после шага
    match_rate:           float            # скользящий match_rate (окно 10)
    candidates:           List[float] = field(default_factory=list)
    # расстояния топ-3 кандидатов из драйвера (0-й = выбранный)
    # пустой список если буфер был пуст (IDLE) или feature не задан


# ══════════════════════════════════════════════════════════════════════
# Петля активного внимания
# ══════════════════════════════════════════════════════════════════════

class AttentionLoop:
    """
    Петля активного внимания: модель опрашивает периферию сама.

    Алгоритм шага:
      1. Получить proposals от InitiativeEngine (last_proposals).
      2. Найти лучший драйвер с непустым буфером (по приоритету).
      3. Запросить driver.query(feature) — лучший совпадающий токен.
      4. Если токен получен → system.process_token(token).
      5. Если все буферы пусты → вернуть шаг с outcome=IDLE.

    Для загрузки контента используйте load_buffer():
        loop.load_buffer("текст")           # TextDriver по умолчанию
        loop.load_buffer([0.1, 0.5], "seq") # SequenceDriver
    """

    def __init__(
        self,
        system:      "LearningSystem",
        peripherals: "PeripheralManager",
        memory:      Optional["MemoryDriver"] = None,
    ) -> None:
        self._system      = system
        self._peripherals = peripherals
        self._step_n:  int = 0
        self._history: List[AttentionStep] = []
        self.memory: Optional["MemoryDriver"] = memory
        # Последний StepResult — используется ProposalCommandLoop (Шаг 13)
        self._last_step_result: Optional[Any] = None

    # ------------------------------------------------------------------
    # Загрузка контента

    def load_buffer(self, content: Any, driver_id: str = "text") -> int:
        """
        Загрузить контент в буфер указанного драйвера.

        content — строка (TextDriver), список float (SequenceDriver),
                  или List[PeripheralToken] для любого драйвера.
        Возвращает новый размер буфера драйвера.
        """
        driver = self._peripherals.get(driver_id)
        if driver is None:
            raise KeyError(f"Драйвер '{driver_id}' не зарегистрирован")
        return driver.load_buffer(content)

    def buffer_sizes(self) -> Dict[str, int]:
        """Текущие размеры буферов всех зарегистрированных драйверов."""
        result: Dict[str, int] = {}
        for did in self._peripherals.driver_ids():
            d = self._peripherals.get(did)
            if d is not None:
                result[did] = d.buffer_size
        return result

    def total_buffer_size(self) -> int:
        """Суммарное количество токенов во всех буферах."""
        return sum(self.buffer_sizes().values())

    # ------------------------------------------------------------------
    # Основной шаг

    def step(self) -> AttentionStep:
        """
        Один шаг активного внимания.

        Если все буферы пусты — возвращает шаг с outcome='IDLE'.
        """
        self._step_n += 1
        gens_before = self._system.base.size()

        # Получить текущие proposals от InitiativeEngine
        proposals = self._system.last_proposals()
        top_proposal = proposals[0] if proposals else None

        # Найти feature для запроса (из top proposal)
        query_feature = None
        if top_proposal:
            query_feature = self._system.engine._features.get(
                top_proposal.next_feature_id
            )

        # Найти драйвер с непустым буфером (по приоритету)
        token = None
        driver_queried: Optional[str] = None
        candidates: List[float] = []

        for did in self._peripherals.driver_ids():
            d = self._peripherals.get(did)
            if d is not None and d.buffer_size > 0:
                # Сначала посмотреть альтернативы (без извлечения)
                if query_feature is not None:
                    ranked = d.query_ranked(query_feature, n=3)
                    candidates = [round(dist, 4) for _, dist in ranked]
                token = d.query(query_feature)
                driver_queried = did
                break

        # Все буферы пусты → IDLE
        if token is None:
            step = AttentionStep(
                step_n=self._step_n,
                proposal_feature_id=(
                    top_proposal.next_feature_id if top_proposal else None
                ),
                driver_queried=None,
                outcome="IDLE",
                new_gens=0,
                buffer_sizes=self.buffer_sizes(),
                match_rate=self._rolling_match_rate(),
                candidates=[],
            )
            self._history.append(step)
            return step

        # Обработать токен
        result = self._system.process_token(token)
        self._last_step_result = result          # для ProposalCommandLoop (Шаг 13)
        outcome = result.outcome.name
        gens_after = self._system.base.size()

        # Записать в долговременную память
        if self.memory is not None:
            active_ids = tuple(self._system.engine.context.active_gen_ids())
            if outcome in ("CONFIRMED", "COMPLETED"):
                # Успешное подтверждение — sig текущих Gen
                self.memory.record(token, self._mean_sig(active_ids), active_ids)
            elif outcome == "REFUTED":
                # Неожиданность — новый Gen только создан, sig≈0, нужен replay.
                # Сохраняем new_gen_id чтобы focus_gen() мог его найти.
                new_gen_sig = 0.0 if result.new_gen_id else 0.2
                refuted_ids = active_ids
                if result.new_gen_id:
                    refuted_ids = (result.new_gen_id,) + active_ids
                self.memory.record(token, new_gen_sig, refuted_ids)

        step = AttentionStep(
            step_n=self._step_n,
            proposal_feature_id=(
                top_proposal.next_feature_id if top_proposal else None
            ),
            driver_queried=driver_queried,
            outcome=outcome,
            new_gens=gens_after - gens_before,
            buffer_sizes=self.buffer_sizes(),
            match_rate=self._rolling_match_rate(),
            candidates=candidates,
        )
        self._history.append(step)
        return step

    def run(self, n_steps: int) -> List[AttentionStep]:
        """
        Запустить n шагов подряд.

        Останавливается досрочно если все буферы пусты более idle_limit
        раз подряд (по умолчанию — не останавливается).
        """
        return [self.step() for _ in range(n_steps)]

    def run_until_empty(self, max_steps: int = 10_000) -> List[AttentionStep]:
        """
        Запускать шаги, пока буферы не опустеют.

        Ограничение max_steps защищает от бесконечного цикла.
        """
        steps: List[AttentionStep] = []
        for _ in range(max_steps):
            s = self.step()
            steps.append(s)
            if s.outcome == "IDLE":
                break
        return steps

    def run_sentences(
        self,
        texts: List[str],
        driver_id: str = "text",
        max_steps_per: int = 500,
    ) -> List[List[AttentionStep]]:
        """
        Обработать каждый текст как самостоятельное предложение.

        Сбрасывает контекст системы перед каждым текстом:
          система «переводит взгляд» — не тащит цепочки из предыдущего.

        Это ключевое отличие от run() / run_until_empty():
          там буфер — непрерывный поток; здесь — дискретные высказывания.

        Возвращает список списков шагов (один подсписок на текст).
        """
        results: List[List[AttentionStep]] = []
        for text in texts:
            self._system.reset_context()          # граница предложения
            self.load_buffer(text, driver_id)
            steps = self.run_until_empty(max_steps_per)
            results.append(steps)
        return results

    def run_consolidation(self, n_steps: int = 100) -> List[AttentionStep]:
        """
        Цикл консолидации: ядро реплицирует долговременную память.

        Активирует MemoryDriver на один цикл, затем запускает step() пока
        не исчерпается цикл (IDLE). TextDriver должен быть пуст — иначе
        внимание уйдёт к нему (приоритет выше).

        Во время консолидации tolerance обычно ниже (устанавливается снаружи
        через session.consolidate() — это повышает разрешение различения).
        """
        if self.memory is None:
            return []
        self.memory.activate(new_cycle=True)
        steps: List[AttentionStep] = []
        try:
            for _ in range(n_steps):
                s = self.step()
                steps.append(s)
                if s.outcome == "IDLE":
                    break
        finally:
            self.memory.deactivate()
        return steps

    # ------------------------------------------------------------------
    # Вспомогательные методы

    def _mean_sig(self, gen_ids: tuple) -> float:
        """Средняя значимость активных Gen (для записи в память)."""
        base = self._system.base
        sigs = [
            g.significance
            for gid in gen_ids
            if (g := base.get(gid)) is not None
        ]
        return round(sum(sigs) / len(sigs), 4) if sigs else 0.5

    # ------------------------------------------------------------------
    # Статистика

    def stats(self) -> Dict[str, Any]:
        """Сводная статистика петли."""
        if not self._history:
            return {
                "steps":          0,
                "buffer_sizes":   self.buffer_sizes(),
                "avg_match_rate": 0.0,
            }
        outcomes = [s.outcome for s in self._history]
        total = len(outcomes)
        return {
            "steps":          total,
            "confirmed":      outcomes.count("CONFIRMED"),
            "completed":      outcomes.count("COMPLETED"),
            "refuted":        outcomes.count("REFUTED"),
            "exploring":      outcomes.count("EXPLORING"),
            "idle":           outcomes.count("IDLE"),
            "avg_match_rate": round(
                (outcomes.count("CONFIRMED") + outcomes.count("COMPLETED")) / total, 4
            ),
            "total_new_gens": sum(s.new_gens for s in self._history),
            "buffer_sizes":   self.buffer_sizes(),
        }

    @property
    def history(self) -> List[AttentionStep]:
        return list(self._history)

    def _rolling_match_rate(self, window: int = 10) -> float:
        recent = [
            s for s in self._history[-window:] if s.outcome != "IDLE"
        ]
        if not recent:
            return 0.0
        hits = sum(
            1 for s in recent
            if s.outcome in ("CONFIRMED", "COMPLETED")
        )
        return round(hits / len(recent), 4)

    def __repr__(self) -> str:
        return (
            f"AttentionLoop("
            f"steps={self._step_n}, "
            f"buf={self.total_buffer_size()}, "
            f"match={self._rolling_match_rate():.2f})"
        )
