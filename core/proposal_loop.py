"""
Шаг 13: ProposalCommandLoop — замкнутый цикл активного внимания.

Закрывает петлю:
    propose → driver.query(feature) → token → step → observe → propose → ...
                                                          ↓
                                               (при разрыве контекста)
                                                          ↓
                                             broker.handle_query(query)
                                           ┌─────────────────────────┐
                                           │ LOCAL  → refill buffer  │
                                           │ REMOTE → TeachingLog    │
                                           │          → LLM          │
                                           └─────────────────────────┘

Три уровня восстановления контекста (из архитектуры ActiveAttention):
  1. driver.query(feature_id)        [AttentionLoop.step()]
  2. broker.handle_query() LOCAL     [SourceTextRegistry]
  3. broker.handle_query() REMOTE    [TeachingLog → LLM]

Использование:
    loop   = AttentionLoop(app.system, app.peripherals)
    speech = SpeechDriver(verbosity=1)
    broker = ContextBroker(app.system.teaching_log, registry)

    pcl = ProposalCommandLoop(loop, speech=speech, broker=broker)
    loop.load_buffer("мальчик нашёл ключ открыл дверь")
    result = pcl.run_cycle()

    if result.status == LoopStatus.AWAITING_LLM:
        # ... получить ответ от LLM ...
        result2 = pcl.resume_after_llm(["он открыл дверь и вошёл"])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .attention_loop import AttentionLoop, AttentionStep
    from drivers.speech_driver import SpeechDriver, ContextQuery
    from drivers.context_broker import ContextBroker


# ══════════════════════════════════════════════════════════════════════
# Статус цикла
# ══════════════════════════════════════════════════════════════════════

class LoopStatus:
    """Статус завершения цикла."""
    RUNNING      = "RUNNING"       # (не возвращается из run_cycle, только внутренний)
    DONE         = "DONE"          # буфер исчерпан, нет незакрытых запросов
    AWAITING_LLM = "AWAITING_LLM"  # есть pending_queries → ждём ответа LLM


# ══════════════════════════════════════════════════════════════════════
# Результат одного цикла
# ══════════════════════════════════════════════════════════════════════

@dataclass
class CycleResult:
    """
    Результат одного прогона ProposalCommandLoop.run_cycle().

    steps                — список AttentionStep (один на process_token)
    status               — LoopStatus.DONE или LoopStatus.AWAITING_LLM
    queries_generated    — количество обнаруженных ContextQuery
    queries_resolved_local  — разрешено из SourceTextRegistry (LOCAL)
    queries_sent_to_llm  — отправлено в TeachingLog (REMOTE)
    pending_queries      — запросы, ожидающие ответа LLM (REMOTE, не разрешены)
    all_queries          — ВСЕ обнаруженные ContextQuery (LOCAL + REMOTE)
    """
    steps:                  List["AttentionStep"]
    status:                 str                   # LoopStatus.*
    queries_generated:      int = 0
    queries_resolved_local: int = 0
    queries_sent_to_llm:    int = 0
    pending_queries:        List[Any] = field(default_factory=list)
    all_queries:            List[Any] = field(default_factory=list)

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    @property
    def match_rate(self) -> float:
        """Доля шагов CONFIRMED+COMPLETED среди не-IDLE."""
        non_idle = [s for s in self.steps if s.outcome != "IDLE"]
        if not non_idle:
            return 0.0
        hits = sum(1 for s in non_idle if s.outcome in ("CONFIRMED", "COMPLETED"))
        return round(hits / len(non_idle), 4)

    @property
    def new_gens(self) -> int:
        return sum(s.new_gens for s in self.steps)


# ══════════════════════════════════════════════════════════════════════
# ProposalCommandLoop
# ══════════════════════════════════════════════════════════════════════

class ProposalCommandLoop:
    """
    Замкнутый цикл активного внимания (Шаг 13).

    Оборачивает AttentionLoop и добавляет:
      - Наблюдение SpeechDriver за каждым шагом (Канал B)
      - Детектирование контекстных разрывов (gap_threshold, min_streak)
      - Автоматическое обращение к ContextBroker при разрыве
        · LOCAL  → буфер пополнен мгновенно, цикл продолжается
        · REMOTE → запрос в TeachingLog, status→AWAITING_LLM
      - resume_after_llm() возобновляет цикл после ответа LLM

    Параметры
    ---------
    loop              : AttentionLoop   — основной цикл (уже создан)
    speech            : SpeechDriver    — Канал B (опционально)
    broker            : ContextBroker   — брокер контекста (опционально)
    default_driver_id : str             — id драйвера для refill («text»)
    gap_threshold     : float           — порог уверенности для разрыва
    min_streak        : int             — мин. серия REFUTED для разрыва
    """

    def __init__(
        self,
        loop:               "AttentionLoop",
        speech:             Optional["SpeechDriver"]  = None,
        broker:             Optional["ContextBroker"] = None,
        default_driver_id:  str   = "text",
        gap_threshold:      float = 0.30,
        min_streak:         int   = 2,
    ) -> None:
        self._loop              = loop
        self._speech            = speech
        self._broker            = broker
        self._default_driver_id = default_driver_id
        self._gap_threshold     = gap_threshold
        self._min_streak        = min_streak
        self._pending_queries:  List[Any] = []

    # ------------------------------------------------------------------
    # Основной цикл

    def run_cycle(
        self,
        max_steps: int = 500,
        verbose:   bool = False,
        clear_pending: bool = True,
    ) -> CycleResult:
        """
        Запустить цикл до DONE или AWAITING_LLM.

        Алгоритм каждого шага:
          1. loop.step() → AttentionStep
          2. speech.observe() → Observation (Канал B, если speech задан)
          3. speech.detect_context_gap() → ContextQuery?
             Да  → broker.handle_query()
                   LOCAL  → continue (буфер пополнен)
                   REMOTE → pending_queries += query
          4. outcome == IDLE → выход из цикла

        clear_pending=True (умолчание) — очищает накопленные pending_queries
            перед стартом нового цикла. False — накапливает между прогонами.
        verbose=True выводит наблюдения канала B и GAP-алерты в stdout.
        """
        if clear_pending:
            self._pending_queries.clear()

        steps:       List["AttentionStep"] = []
        q_generated  = 0
        q_local      = 0
        q_llm        = 0
        all_q:       List[Any] = []

        if self._speech:
            self._speech.reset_session()

        for _ in range(max_steps):
            s = self._loop.step()
            steps.append(s)

            # ── Канал B: наблюдение + детекция разрыва ───────────────
            if self._speech and self._loop._last_step_result is not None:
                result = self._loop._last_step_result
                system = self._loop._system
                active = list(system.engine.context.active_gen_ids())

                obs = self._speech.observe(result, system.base, active)
                if verbose and obs:
                    print(f"  [{obs.outcome_tag[:4]}] {obs.text}")

                # Ведущий Gen по значимости
                lead_gen, lead_sig = None, 0.0
                for gid in active:
                    g = system.base.get(gid)
                    if g and g.significance > lead_sig:
                        lead_gen, lead_sig = g, g.significance

                query = self._speech.detect_context_gap(
                    result, lead_gen, lead_sig,
                    gap_threshold=self._gap_threshold,
                    min_streak=self._min_streak,
                )
                if query:
                    q_generated += 1
                    all_q.append(query)
                    if verbose:
                        print(f"  [GAP ] {query.query_text}")
                    if self._try_resolve(query):
                        q_local += 1
                        # Буфер пополнен локально — продолжаем без прерывания
                    else:
                        q_llm += 1
                        self._pending_queries.append(query)
                        # Запрос в TeachingLog, продолжаем оставшийся буфер

            # ── IDLE: буфер исчерпан ──────────────────────────────────
            if s.outcome == "IDLE":
                break

        status = (
            LoopStatus.AWAITING_LLM
            if self._pending_queries
            else LoopStatus.DONE
        )
        return CycleResult(
            steps=steps,
            status=status,
            queries_generated=q_generated,
            queries_resolved_local=q_local,
            queries_sent_to_llm=q_llm,
            pending_queries=list(self._pending_queries),
            all_queries=all_q,
        )

    # ------------------------------------------------------------------
    # Возобновление после LLM-ответа

    def resume_after_llm(
        self,
        received_texts: List[str],
        max_steps: int = 200,
        verbose:   bool = False,
    ) -> CycleResult:
        """
        Возобновить цикл после получения ответа от LLM-учителя.

        Загружает полученные тексты в буфер драйвера,
        очищает очередь ожидающих запросов и запускает новый цикл.
        """
        driver = self._loop._peripherals.get(self._default_driver_id)
        if driver is not None:
            for text in received_texts:
                driver.load_buffer(text)
        self._pending_queries.clear()
        return self.run_cycle(max_steps=max_steps, verbose=verbose)

    # ------------------------------------------------------------------
    # Прямой доступ к буферам

    def load_buffer(self, content: Any, driver_id: Optional[str] = None) -> int:
        """Загрузить контент в буфер указанного (или default) драйвера."""
        return self._loop.load_buffer(
            content,
            driver_id=driver_id or self._default_driver_id,
        )

    # ------------------------------------------------------------------
    # Статистика / утилиты

    @property
    def pending_queries(self) -> List[Any]:
        """Запросы, ожидающие ответа LLM."""
        return list(self._pending_queries)

    def clear_pending(self) -> None:
        """Очистить очередь ожидающих запросов (например, после TIMEOUT)."""
        self._pending_queries.clear()

    @property
    def inner_loop(self) -> "AttentionLoop":
        """Доступ к внутреннему AttentionLoop (для stats, history)."""
        return self._loop

    def stats(self) -> Dict[str, Any]:
        """Сводная статистика цикла (делегирует в AttentionLoop)."""
        s = self._loop.stats()
        s["pending_queries"] = len(self._pending_queries)
        return s

    # ------------------------------------------------------------------

    def _try_resolve(self, query: Any) -> bool:
        """
        Попытаться разрешить ContextQuery локально через ContextBroker.

        LOCAL  → True  (буфер пополнен, продолжаем)
        REMOTE → False (запрос уже добавлен в TeachingLog брокером)
        Нет broker → False
        """
        if self._broker is None:
            return False
        driver = self._loop._peripherals.get(self._default_driver_id)
        return self._broker.handle_query(query, driver)

    def __repr__(self) -> str:
        return (
            f"ProposalCommandLoop("
            f"loop={self._loop!r}, "
            f"speech={'yes' if self._speech else 'no'}, "
            f"broker={'yes' if self._broker else 'no'}, "
            f"pending={len(self._pending_queries)})"
        )
