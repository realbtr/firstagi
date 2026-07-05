"""
Фаза сна — консолидация обобщений.

Биологическая аналогия:
  Медленный сон:  повтор оперативных траекторий → укрепление гетерархических связей
  REM:            галлюцинация из долгосрочного контекста →
                  поиск кросс-доменных зависимостей → метаобобщения
  Глубокий сон:   выброс неинтегрированных OPERATIONAL Gen (CapacityBudget)

Вложенные транзакции:
  Внешняя (весь sleep-цикл):
    COMMIT:   meta-Gen (кросс-доменные / глубокие обобщения)
    ROLLBACK: всё остальное — в конце цикла
  Внутренняя (один replay-цикл):
    Большинство → ROLLBACK (эпизодический шум)
    Кандидаты  → COMMIT во внешнюю транзакцию

Компоненты:
  DreamTransactionBuffer  — shadow-база с вложенными транзакциями
  ReplayEngine            — топ-даун генерация токенов из контекстных ожиданий
  SleepScheduler          — детектор момента входа в фазу сна (H15-плато + urgency)
  DomainRegistry          — метки доменов для feature_id
  CrossDomainDetector     — поиск метаобобщений по domain-дивергенции
  SleepResult             — итоги одного цикла сна
  sleep_cycle()           — оркестратор: replay → commit/rollback → eviction
  REFUTEDEvent            — событие опровержения («удивление дня»)
  ContextQueryLog         — лог REFUTED-событий для SleepDriver
  SleepDriver             — системный драйвер сна: воспроизводит непонятое
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, List, Optional, Set

from .generalization import Generalization, GeneralizationBase, PeripheralToken
from .context import ContextBuffer

if TYPE_CHECKING:
    from .vitality import VitalityEngine
    from .learning import LearningSystem
    from .capacity import CapacityBudget


# ══════════════════════════════════════════════════════════════════════
# DreamTransactionBuffer — shadow-база с вложенными транзакциями
# ══════════════════════════════════════════════════════════════════════

class DreamTransactionBuffer:
    """
    Прокси поверх GeneralizationBase с транзакционной семантикой.

    Все ЗАПИСИ попадают в _pending (не в реальную базу).
    Все ЧТЕНИЯ проксируются к реальной базе (+ pending).

    Вложенность:
        outer = DreamTransactionBuffer(real_base)
        inner = outer.nested()
        # inner.add() → inner._pending
        # inner.commit(ids) → outer._pending (через outer.add())
        # inner.rollback()  → очищает inner._pending

    Фиксация:
        outer.commit()    → перемещает outer._pending → real_base
        outer.rollback()  → очищает оставшийся outer._pending
    """

    def __init__(
        self,
        real_base: "GeneralizationBase | DreamTransactionBuffer",
        tag: str = "outer",
    ) -> None:
        self._real    = real_base
        self._pending: Dict[str, Generalization] = {}
        self.tag      = tag
        self._n_committed   = 0
        self._n_rolled_back = 0

    # ------------------------------------------------------------------
    # GeneralizationBase-совместимый интерфейс (CRUD)

    def add(self, gen: Generalization) -> Generalization:
        """Добавить Gen в pending (не в реальную базу)."""
        self._pending[gen.gen_id] = gen
        return gen

    def get(self, gen_id: str) -> Optional[Generalization]:
        return self._pending.get(gen_id) or self._real.get(gen_id)

    def all(self) -> List[Generalization]:
        seen = set(self._pending)
        result = list(self._pending.values())
        for g in self._real.all():
            if g.gen_id not in seen:
                result.append(g)
        return result

    def size(self) -> int:
        return self._real.size() + len(self._pending)

    def remove(self, gen_id: str) -> bool:
        if gen_id in self._pending:
            del self._pending[gen_id]
            return True
        return self._real.remove(gen_id)

    # ------------------------------------------------------------------
    # Поиск и ранжирование

    def rank(self, min_significance: float = 0.0) -> List[Generalization]:
        gens = [g for g in self.all() if g.significance >= min_significance]
        return sorted(gens, key=lambda g: g.significance, reverse=True)

    def search_by_chain(self, feature_chain: List[str]) -> List[Generalization]:
        pending_hits = [g for g in self._pending.values()
                        if g.feature_chain == feature_chain]
        real_hits = self._real.search_by_chain(feature_chain)
        seen = {g.gen_id for g in pending_hits}
        return pending_hits + [g for g in real_hits if g.gen_id not in seen]

    def search_by_prefix(self, prefix: List[str]) -> List[Generalization]:
        n = len(prefix)
        pending_hits = [g for g in self._pending.values()
                        if g.feature_chain[:n] == prefix]
        real_hits = self._real.search_by_prefix(prefix)
        seen = {g.gen_id for g in pending_hits}
        return pending_hits + [g for g in real_hits if g.gen_id not in seen]

    def low_level(self, max_chain_length: int = 2) -> List[Generalization]:
        result = [g for g in self.all()
                  if 0 < g.generalization_level <= max_chain_length]
        return sorted(result, key=lambda g: g.significance, reverse=True)

    # ------------------------------------------------------------------
    # Гетерархия и переходы (делегируем реальной базе)

    def link(self, parent_id: str, child_id: str) -> None:
        parent = self.get(parent_id)
        child  = self.get(child_id)
        if parent and child:
            if child_id not in parent.child_ids:
                parent.child_ids.append(child_id)
            if parent_id not in child.parent_ids:
                child.parent_ids.append(parent_id)

    def record_transition(self, from_id: str, to_id: str) -> None:
        self._real.record_transition(from_id, to_id)

    def get_transitions(self, from_id: str) -> Dict[str, int]:
        return self._real.get_transitions(from_id)

    def most_likely_next(self, from_id: str) -> Optional[str]:
        return self._real.most_likely_next(from_id)

    # ------------------------------------------------------------------
    # Транзакционные операции

    def commit(self, gen_ids: Optional[Set[str]] = None) -> int:
        """
        Перенести pending Gen в реальную базу (или во внешнюю транзакцию).

        Если gen_ids=None — перенести все pending.
        Возвращает количество перенесённых Gen.
        """
        ids_to_commit = gen_ids if gen_ids is not None else set(self._pending.keys())
        committed = 0
        for gid in list(ids_to_commit):
            if gid in self._pending:
                self._real.add(self._pending.pop(gid))
                committed += 1
        self._n_committed += committed
        return committed

    def rollback(self) -> int:
        """
        Отбросить все pending Gen (не попавшие в commit).
        Возвращает количество отброшенных.
        """
        n = len(self._pending)
        self._pending.clear()
        self._n_rolled_back += n
        return n

    def pending_gens(self) -> List[Generalization]:
        """Список Gen, ожидающих commit/rollback."""
        return list(self._pending.values())

    def nested(self, tag: str = "inner") -> "DreamTransactionBuffer":
        """Создать вложенную транзакцию, обёрнутую вокруг self."""
        return DreamTransactionBuffer(self, tag=tag)

    # ------------------------------------------------------------------

    @property
    def n_committed(self) -> int:
        return self._n_committed

    @property
    def n_rolled_back(self) -> int:
        return self._n_rolled_back

    def __repr__(self) -> str:
        return (
            f"DreamTransactionBuffer(tag={self.tag!r}, "
            f"pending={len(self._pending)}, "
            f"committed={self._n_committed}, "
            f"rolled_back={self._n_rolled_back})"
        )


# ══════════════════════════════════════════════════════════════════════
# DomainRegistry — регистр доменов для feature_id
# ══════════════════════════════════════════════════════════════════════

class DomainRegistry:
    """
    Связывает feature_id с именем домена (обучающего корпуса).

    Использование:
        registry = DomainRegistry()
        registry.register("feat-uuid-...", "narrative")
        domains = registry.domains_of(["feat-a", "feat-b"])  # {"narrative", "serial"}
    """

    def __init__(self) -> None:
        self._map: Dict[str, str] = {}   # feature_id → domain

    def register(self, feature_id: str, domain: str) -> None:
        """Зарегистрировать feature_id под именем домена."""
        self._map[feature_id] = domain

    def register_many(self, feature_ids: List[str], domain: str) -> None:
        for fid in feature_ids:
            self._map[fid] = domain

    def domain_of(self, feature_id: str) -> Optional[str]:
        return self._map.get(feature_id)

    def domains_of(self, feature_ids: List[str]) -> Set[str]:
        """Множество доменов, охватываемых данными feature_id."""
        result: Set[str] = set()
        for fid in feature_ids:
            d = self._map.get(fid)
            if d is not None:
                result.add(d)
        return result

    def known_domains(self) -> Set[str]:
        return set(self._map.values())

    def size(self) -> int:
        return len(self._map)

    def __repr__(self) -> str:
        return f"DomainRegistry(features={len(self._map)}, domains={self.known_domains()})"


# ══════════════════════════════════════════════════════════════════════
# CrossDomainDetector — поиск кросс-доменных метаобобщений
# ══════════════════════════════════════════════════════════════════════

class CrossDomainDetector:
    """
    Определяет, является ли Gen кросс-доменным метаобобщением.

    Два режима:
      1. С DomainRegistry: Gen кросс-доменный если его feature_chain
         охватывает ≥ min_domains доменов.
      2. Без реестра (fallback): Gen считается кандидатом если
         chain_length ≥ min_chain_fallback (эвристика).
    """

    def __init__(
        self,
        domain_registry: Optional[DomainRegistry] = None,
        min_domains: int = 2,
        min_chain_fallback: int = 3,
    ) -> None:
        self._registry        = domain_registry
        self.min_domains      = min_domains
        self.min_chain_fallback = min_chain_fallback

    def is_meta_candidate(self, gen: Generalization) -> bool:
        """True если Gen является кандидатом на метаобобщение."""
        if self._registry is not None:
            domains = self._registry.domains_of(gen.feature_chain)
            return len(domains) >= self.min_domains
        # Fallback: глубина цепочки как прокси
        return len(gen.feature_chain) >= self.min_chain_fallback

    def filter_meta(self, gens: List[Generalization]) -> List[Generalization]:
        """Вернуть только Gen-кандидаты на метаобобщение."""
        return [g for g in gens if self.is_meta_candidate(g)]

    def annotate(self, gen: Generalization) -> str:
        """Человекочитаемое объяснение почему Gen считается мета."""
        if self._registry is not None:
            domains = self._registry.domains_of(gen.feature_chain)
            return f"domains={sorted(domains)}"
        return f"chain_len={len(gen.feature_chain)}"


# ══════════════════════════════════════════════════════════════════════
# ReplayEngine — топ-даун генерация токенов из контекстных ожиданий
# ══════════════════════════════════════════════════════════════════════

class ReplayEngine:
    """
    Генерирует синтетические токены из ожиданий активного контекста.

    Механика («галлюцинация»):
      1. Берёт ожидаемые признаки из контекста (get_expected_features).
      2. Для каждого ожидаемого feature_id ищет Feature в реестре движка.
      3. Создаёт PeripheralToken с Feature.data — движок принимает его как
         реальный входной сигнал (engine._token_to_feature возвращает Feature).
      4. Поскольку токен точно совпадает с ожиданием → CONFIRMED/COMPLETED.
      5. После подтверждения контекст переходит к следующему ожиданию.

    Кросс-доменный эффект:
      Если в контексте одновременно активны Gen из разных доменов
      с частично совпадающими ожиданиями → GreedyGeneralizer создаёт
      новый Gen, объединяющий оба пути.
    """

    DREAM_DRIVER_ID = "dream"

    def __init__(self, feature_registry: Dict[str, "Feature"]) -> None:
        self._features = feature_registry   # engine._features (shared ref)

    def make_token(self, feature_id: str) -> Optional[PeripheralToken]:
        """Создать синтетический токен из feature_id."""
        from .feature import Feature
        feat = self._features.get(feature_id)
        if feat is None:
            return None
        return PeripheralToken.new(
            driver_id=self.DREAM_DRIVER_ID,
            data=feat,
            label=f"dream:{feature_id[:8]}",
        )

    def generate_sequence(
        self,
        context: ContextBuffer,
        base: "GeneralizationBase | DreamTransactionBuffer",
        max_tokens: int = 15,
    ) -> List[PeripheralToken]:
        """
        Сгенерировать последовательность синтетических токенов
        из текущих ожиданий контекста.

        Возвращает список токенов (может быть пустым если контекст пуст
        или ожидаемые feature не найдены в реестре).
        """
        expected = context.get_expected_features(base)  # {gen_id: feature_id}
        tokens: List[PeripheralToken] = []
        seen_feat_ids: Set[str] = set()

        for feat_id in expected.values():
            if feat_id in seen_feat_ids:
                continue
            tok = self.make_token(feat_id)
            if tok is not None:
                tokens.append(tok)
                seen_feat_ids.add(feat_id)
            if len(tokens) >= max_tokens:
                break

        return tokens

    def iterative_replay(
        self,
        engine: "AttractorEngine",
        buf: "DreamTransactionBuffer",
        max_steps: int = 20,
    ) -> List["StepResult"]:
        """
        Итеративный replay: каждый шаг берёт ожидание из обновлённого
        контекста, создаёт токен и отдаёт в engine.step().

        Останавливается при:
          - исчерпании ожиданий (EXPLORING)
          - достижении max_steps
        """
        from .algorithm import StepOutcome
        results = []
        for _ in range(max_steps):
            tokens = self.generate_sequence(engine.context, buf, max_tokens=1)
            if not tokens:
                break
            result = engine.step(tokens[0])
            results.append(result)
            if result.outcome in (StepOutcome.EXPLORING, StepOutcome.CYCLE_AVOIDED):
                break
        return results


# ══════════════════════════════════════════════════════════════════════
# SleepScheduler — детектор момента входа в фазу сна
# ══════════════════════════════════════════════════════════════════════

@dataclass
class SleepDecision:
    """Решение планировщика: спать или нет."""
    n_new:                 int
    is_plateau:            bool
    consecutive_plateaus:  int
    n_knock:               int
    knock_fraction:        float
    should_sleep:          bool

    def __repr__(self) -> str:
        verdict = "SLEEP" if self.should_sleep else "awake"
        return (
            f"SleepDecision({verdict}: "
            f"n_new={self.n_new}, "
            f"plateaus={self.consecutive_plateaus}, "
            f"knock={self.n_knock}/{self.knock_fraction:.2%})"
        )


class SleepScheduler:
    """
    Решает когда входить в фазу сна на основе двух сигналов:

      1. H15-плато:  n_new_gens < plateau_threshold  за последний pass
                     (подтверждён H15 — надёжный сигнал насыщения)
      2. Urgency:    доля knock_candidates ≥ min_knock_fraction
                     (много Gen «просят» о консолидации)

    Фаза сна активируется если:
      consecutive_plateaus ≥ plateaus_required  AND  urgency-сигнал ≥ порога.
    """

    def __init__(
        self,
        plateau_threshold:   int   = 3,     # n_new < N = плато
        plateaus_required:   int   = 2,     # сколько плато подряд до решения
        urgency_threshold:   float = 2.0,   # urgency > N → knock_candidate
        min_knock_fraction:  float = 0.03,  # ≥ 3% Gen просрочено
    ) -> None:
        self._plateau_threshold  = plateau_threshold
        self._plateaus_required  = plateaus_required
        self._urgency_threshold  = urgency_threshold
        self._min_knock_fraction = min_knock_fraction
        self._prev_base_size     = 0
        self._consecutive        = 0

    def tick(
        self,
        base:         "GeneralizationBase",
        vitality:     "VitalityEngine",
        current_step: int = 0,
    ) -> SleepDecision:
        """
        Вызывается после каждого обучающего pass.
        Возвращает SleepDecision с рекомендацией.
        """
        n_new = base.size() - self._prev_base_size
        self._prev_base_size = base.size()

        is_plateau = n_new < self._plateau_threshold
        self._consecutive = self._consecutive + 1 if is_plateau else 0

        gen_ids = [g.gen_id for g in base.all()]
        knock = vitality.knock_candidates(
            gen_ids, base, current_step, threshold=self._urgency_threshold
        )
        knock_fraction = len(knock) / max(base.size(), 1)

        should_sleep = (
            self._consecutive >= self._plateaus_required
            and knock_fraction >= self._min_knock_fraction
        )

        return SleepDecision(
            n_new=n_new,
            is_plateau=is_plateau,
            consecutive_plateaus=self._consecutive,
            n_knock=len(knock),
            knock_fraction=knock_fraction,
            should_sleep=should_sleep,
        )

    def reset(self) -> None:
        """Сбросить счётчик плато (после пробуждения)."""
        self._consecutive = 0
        self._prev_base_size = 0


# ══════════════════════════════════════════════════════════════════════
# SleepResult — итоги цикла сна
# ══════════════════════════════════════════════════════════════════════

@dataclass
class SleepResult:
    """Результат одного цикла сна."""
    n_replays:         int               # число replay-итераций
    meta_gen_count:    int               # коммитнутых meta-Gen
    meta_gen_ids:      List[str]         # их ID
    total_committed:   int               # Gen попавших в commit (все транзакции)
    total_rolled_back: int               # Gen отброшенных при rollback
    n_evicted:         int = 0           # вытеснено CapacityBudget после сна
    replay_outcomes:   List[str] = field(default_factory=list)  # OutcomeStats per replay

    @property
    def commit_rate(self) -> float:
        """Доля созданных Gen, которые были закоммичены (не выброшены)."""
        total = self.total_committed + self.total_rolled_back
        return self.total_committed / total if total > 0 else 0.0

    def summary(self) -> str:
        return (
            f"SleepResult: {self.n_replays} replays, "
            f"{self.meta_gen_count} meta-Gen committed, "
            f"commit_rate={self.commit_rate:.1%}, "
            f"evicted={self.n_evicted}"
        )


# ══════════════════════════════════════════════════════════════════════
# sleep_cycle() — оркестратор фазы сна
# ══════════════════════════════════════════════════════════════════════

def sleep_cycle(
    system:        "LearningSystem",
    replay_engine: ReplayEngine,
    detector:      CrossDomainDetector,
    budget:        Optional["CapacityBudget"] = None,
    n_replays:     int = 10,
    replay_steps:  int = 20,
    load_top_n:    int = 5,
) -> SleepResult:
    """
    Один полный цикл консолидирующего сна.

    Протокол:
      1. Создать outer_buf поверх system.base.
      2. Для каждого из n_replays (используем top-N LONG_TERM Gen по urgency):
         a. Создать inner_buf (вложенная транзакция).
         b. Переключить engine.base и generalizer.base → inner_buf.
         c. Загрузить Gen в контекст (один или несколько из разных доменов).
         d. Итеративный replay: ожидание → синт.токен → engine.step().
         e. Собрать inner_buf.pending_gens() → detector.filter_meta().
         f. COMMIT meta-кандидатов → outer_buf.
         g. ROLLBACK остальных inner_buf.
         h. Восстановить engine.base / generalizer.base → outer_buf.
      3. outer_buf.commit() → system.base (реальная база).
      4. outer_buf.rollback() → очистить остаток.
      5. Если budget задан → enforce() → выброс OPERATIONAL Gen.
      6. Восстановить контекст системы.
      7. Вернуть SleepResult.

    Параметры
    ----------
    n_replays : int
        Число replay-итераций (≈ число «сновидений» за цикл).
    replay_steps : int
        Максимальное число шагов движка за одну итерацию.
    load_top_n : int
        Сколько LONG_TERM Gen по значимости загружать в контекст
        перед каждой итерацией.
    """
    from .algorithm import StepOutcome

    # Сохранить контекст и оригинальные базы
    saved_context        = system.engine.context
    orig_engine_base     = system.engine.base
    orig_generalizer_base = system.generalizer.base

    # Внешняя транзакция
    outer_buf = DreamTransactionBuffer(system.base, tag="outer")

    total_committed   = 0
    total_rolled_back = 0
    meta_gen_ids: List[str] = []
    replay_outcomes: List[str] = []

    # Получить кандидатов для replay: top LONG_TERM Gen по значимости
    replay_gens = system.base.low_level(max_chain_length=2)[:load_top_n]
    if not replay_gens:
        # Fallback: просто top-ranked
        replay_gens = system.base.rank()[:load_top_n]

    for replay_i in range(n_replays):
        # Создать вложенную транзакцию
        inner_buf = outer_buf.nested(tag=f"inner_{replay_i}")

        # Переключить движок на inner_buf (записи идут в dream, чтения — сквозные)
        system.engine.base       = inner_buf
        system.generalizer.base  = inner_buf

        # Свежий контекст для этого replay
        system.engine.context = ContextBuffer()

        # Загрузить несколько Gen из разных «временных уровней»
        # Смешиваем: один LONG_TERM (якорь) + потенциально mid-tier Gen
        target_gen = replay_gens[replay_i % len(replay_gens)]
        system.engine.context.add_active(target_gen.gen_id)

        # Для кросс-доменного эффекта: добавляем второй Gen если доступен
        if len(replay_gens) > 1:
            other = replay_gens[(replay_i + 1) % len(replay_gens)]
            if other.gen_id != target_gen.gen_id:
                system.engine.context.add_active(other.gen_id)

        # Итеративный replay: галлюцинация из контекста
        step_results = replay_engine.iterative_replay(
            system.engine, inner_buf, max_steps=replay_steps
        )

        # Описание исходов для SleepResult
        outcome_counts: Dict[str, int] = {}
        for r in step_results:
            k = r.outcome.name
            outcome_counts[k] = outcome_counts.get(k, 0) + 1
        replay_outcomes.append(str(outcome_counts))

        # Запустить GreedyGeneralizer на накопленных step results
        for r in step_results:
            system.generalizer.on_step_result(r)
        system.generalizer.reset_chain()

        # Отфильтровать meta-кандидатов
        new_gens      = inner_buf.pending_gens()
        meta_gens     = detector.filter_meta(new_gens)
        meta_ids      = {g.gen_id for g in meta_gens}

        # COMMIT meta → outer_buf
        committed = inner_buf.commit(meta_ids)
        total_committed += committed
        meta_gen_ids.extend(meta_ids)

        # ROLLBACK всего остального inner_buf
        rolled = inner_buf.rollback()
        total_rolled_back += rolled

        # Восстановить базы на outer_buf (следующая итерация тоже пишет в outer)
        system.engine.base      = outer_buf
        system.generalizer.base = outer_buf

    # Восстановить оригинальные ссылки
    system.engine.base       = orig_engine_base
    system.generalizer.base  = orig_generalizer_base
    system.engine.context    = saved_context

    # COMMIT всех meta-Gen из outer_buf → реальная база
    outer_committed = outer_buf.commit()
    total_committed += outer_committed

    # Очистить оставшийся outer_buf (если что-то там осталось)
    outer_rolled = outer_buf.rollback()
    total_rolled_back += outer_rolled

    # Фаза «глубокого сна»: выброс OPERATIONAL Gen если задан budget
    n_evicted = 0
    if budget is not None:
        n_evicted = budget.enforce(system.base)

    return SleepResult(
        n_replays=n_replays,
        meta_gen_count=len(meta_gen_ids),
        meta_gen_ids=meta_gen_ids,
        total_committed=total_committed,
        total_rolled_back=total_rolled_back,
        n_evicted=n_evicted,
        replay_outcomes=replay_outcomes,
    )


# ══════════════════════════════════════════════════════════════════════
# REFUTEDEvent + ContextQueryLog — «лог удивлений дня»
# ══════════════════════════════════════════════════════════════════════

@dataclass
class REFUTEDEvent:
    """
    Событие опровержения — «удивление» во время бодрствования.

    Хранит контекст момента опровержения чтобы SleepDriver мог
    воспроизвести его в режиме сенсорной депривации.
    """
    feature_id:     str            # признак, который опроверг ожидание
    active_gen_ids: List[str]      # Gen-контекст в момент опровержения
    new_gen_id:     Optional[str]  # новый Gen созданный при опровержении
    chain_len:      int            # глубина контекста в момент удивления
                                   # (max chain_len активных Gen, не нового Gen)
    urgency:        float = 1.0    # важность (растёт если повторно не объяснено)
    token_label:    str   = ""     # человекочитаемый ярлык токена («слово»)

    @property
    def is_deep(self) -> bool:
        """Удивление в глубоком контексте (chain≥3 Gen был активен)."""
        return self.chain_len >= 3


class ContextQueryLog:
    """
    Лог «удивлений дня» — REFUTED события за сессию бодрствования.

    Заполняется через LearningSystem.process_token() при REFUTED исходах.
    Используется SleepDriver как источник событий для replay.

    Биологическая аналогия: след эпизодической памяти о неожиданностях,
    который мозг прокручивает во время сна в поисках объяснения.
    """

    def __init__(self) -> None:
        self._events: List[REFUTEDEvent] = []

    def record(
        self,
        feature_id:     str,
        active_gen_ids: List[str],
        new_gen_id:     Optional[str] = None,
        chain_len:      int = 0,
        token_label:    str = "",
    ) -> None:
        """Записать REFUTED событие."""
        self._events.append(REFUTEDEvent(
            feature_id=feature_id,
            active_gen_ids=list(active_gen_ids),
            new_gen_id=new_gen_id,
            chain_len=chain_len,
            token_label=token_label,
        ))

    def candidates(
        self,
        min_chain:   int = 3,
        min_urgency: float = 0.0,
        max_n:       Optional[int] = None,
    ) -> List[REFUTEDEvent]:
        """Вернуть события-кандидаты для replay, отсортированные по urgency."""
        result = [
            e for e in self._events
            if e.chain_len >= min_chain and e.urgency >= min_urgency
        ]
        result.sort(key=lambda e: e.urgency, reverse=True)
        return result[:max_n] if max_n is not None else result

    def is_rich_enough(self, threshold: int = 10) -> bool:
        """Стоит ли спать — был ли день насыщен глубокими удивлениями?"""
        return len(self.candidates(min_chain=3)) >= threshold

    def all_events(self) -> List[REFUTEDEvent]:
        return list(self._events)

    def retain_unresolved(self, urgency_threshold: float = 1.5) -> None:
        """
        Оставить только события с urgency > порога (повторно непонятые).
        Вызывается после sleep_cycle для очистки объяснённых событий.
        """
        self._events = [e for e in self._events if e.urgency > urgency_threshold]

    def clear(self) -> None:
        """Полная очистка лога."""
        self._events.clear()

    def __len__(self) -> int:
        return len(self._events)

    def __repr__(self) -> str:
        deep = sum(1 for e in self._events if e.is_deep)
        return f"ContextQueryLog(total={len(self._events)}, deep_chain3+={deep})"


# ══════════════════════════════════════════════════════════════════════
# SleepDriver — системный драйвер сна
# ══════════════════════════════════════════════════════════════════════

def _make_sleep_token(
    feature_id:       str,
    feature_registry: Dict,
) -> Optional[PeripheralToken]:
    """Создать синтетический токен из feature_id для replay во сне."""
    feat = feature_registry.get(feature_id)
    if feat is None:
        return None
    return PeripheralToken.new(
        driver_id="sleep",
        data=feat,
        label=f"sleep:{feature_id[:8]}",
    )


class SleepDriver:
    """
    Системный драйвер сна.

    Механика (сенсорная депривация):
      Для каждого REFUTED события из ContextQueryLog:
        1. Восстановить контекст момента опровержения (active_gen_ids).
        2. Подать опровергнутый токен (feature_id) заново в engine.step().
        3. Если теперь CONFIRMED/COMPLETED → система «поняла» во сне →
           кандидат на meta-Gen.
        4. Если снова REFUTED → urgency += 0.5 → останется на следующую ночь.
      Внешний внимания полностью захвачен (нет внешнего input).

    Отличие от ReplayEngine:
      ReplayEngine воспроизводит ОЖИДАЕМОЕ (→ всегда CONFIRMED, нечего интегрировать).
      SleepDriver воспроизводит НЕПОНЯТОЕ (→ иногда CONFIRMED = инсайт во сне).

    Биологическая аналогия:
      «Мозг переигрывает непонятые события дня, ища объяснение в накопленном
       опыте. Нашёл → интеграция. Не нашёл → urgency растёт, повторится завтра.»
    """

    DRIVER_ID = "sleep"

    def __init__(self, query_log: ContextQueryLog) -> None:
        self._log = query_log

    @property
    def query_log(self) -> ContextQueryLog:
        return self._log

    def run(
        self,
        system:    "LearningSystem",
        detector:  CrossDomainDetector,
        budget:    Optional["CapacityBudget"] = None,
        n_replays: int = 20,
        min_chain: int = 3,
    ) -> SleepResult:
        """
        Один цикл сна: воспроизвести непонятое в режиме сенсорной депривации.

        Параметры
        ----------
        n_replays : int
            Максимальное число событий для replay за один цикл.
        min_chain : int
            Минимальная глубина опровержения (по умолчанию 3 — глубокий контекст).
        """
        candidates = self._log.candidates(min_chain=min_chain, max_n=n_replays)
        if not candidates:
            return SleepResult(
                n_replays=0, meta_gen_count=0, meta_gen_ids=[],
                total_committed=0, total_rolled_back=0,
            )

        # Сохранить состояние системы (сенсорная депривация — без внешнего input)
        saved_context         = system.engine.context
        orig_engine_base      = system.engine.base
        orig_generalizer_base = system.generalizer.base

        outer_buf = DreamTransactionBuffer(system.base, tag="sleep_outer")

        total_committed   = 0
        total_rolled_back = 0
        meta_gen_ids: List[str] = []
        replay_outcomes: List[str] = []

        for event in candidates:
            inner_buf = outer_buf.nested(tag="sleep_inner")
            system.engine.base      = inner_buf
            system.generalizer.base = inner_buf

            # Восстановить контекст момента опровержения
            system.engine.context = ContextBuffer()
            for gid in event.active_gen_ids:
                if system.base.get(gid) is not None:
                    system.engine.context.add_active(gid)

            # Подать опровергнутый токен заново
            tok = _make_sleep_token(event.feature_id, system.engine._features)
            if tok is None:
                inner_buf.rollback()
                system.engine.base      = outer_buf
                system.generalizer.base = outer_buf
                continue

            result = system.engine.step(tok)
            system.generalizer.on_step_result(result)
            system.generalizer.reset_chain()

            replay_outcomes.append(result.outcome.name)

            # Если снова REFUTED — событие не объяснено, urgency растёт
            if result.outcome.name == "REFUTED":
                event.urgency += 0.5

            # Отфильтровать meta-кандидатов из того что создано в inner_buf
            new_gens  = inner_buf.pending_gens()
            meta_gens = detector.filter_meta(new_gens)
            meta_ids  = {g.gen_id for g in meta_gens}

            committed = inner_buf.commit(meta_ids)
            total_committed += committed
            meta_gen_ids.extend(meta_ids)

            rolled = inner_buf.rollback()
            total_rolled_back += rolled

            system.engine.base      = outer_buf
            system.generalizer.base = outer_buf

        # Восстановить систему из депривации
        system.engine.base       = orig_engine_base
        system.generalizer.base  = orig_generalizer_base
        system.engine.context    = saved_context

        # COMMIT meta-Gen во внешнюю базу
        outer_committed = outer_buf.commit()
        total_committed += outer_committed
        outer_rolled    = outer_buf.rollback()
        total_rolled_back += outer_rolled

        # Глубокий сон: eviction по CapacityBudget
        n_evicted = budget.enforce(system.base) if budget is not None else 0

        # Очистить объяснённые события; оставить повторно непонятые
        self._log.retain_unresolved(urgency_threshold=1.5)

        return SleepResult(
            n_replays=len(candidates),
            meta_gen_count=len(meta_gen_ids),
            meta_gen_ids=meta_gen_ids,
            total_committed=total_committed,
            total_rolled_back=total_rolled_back,
            n_evicted=n_evicted,
            replay_outcomes=replay_outcomes,
        )
