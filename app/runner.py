"""
BackgroundRunner — непрерывный обучающий цикл.

Запускает систему в бесконечном цикле обучения:
  1. Берёт текст из текущего домена (циклически)
  2. Подаёт токены в LearningSystem через TextDriver
  3. Периодически регистрирует тексты в ContextBroker и вызывает tick()
  4. Через каждые `switch_domain_every` переходов — меняет домен обучения
  5. Через каждые `sleep_every` переходов — запускает SleepDriver
  6. Ведёт статистику: transitions/s, domain_switches, sleep_cycles, meta_gen

Аналогия с виртуальной памятью:
  Рабочий набор     = активный контекст (chain=1-2 Gen)
  Страничный отказ  = ContextQuery (разрыв за горизонтом восприятия)
  Обработчик отказа = ContextBroker (tier1 → tier2 FTS5 → tier3 LLM)
  Файл подкачки     = CurriculumIndex (весь накопленный корпус в SQLite)

Использование (один домен):
    runner = BackgroundRunner(system=system, texts=my_texts)
    runner.run(max_transitions=1_000_000)

Использование (несколько доменов):
    runner = BackgroundRunner(
        system=system,
        domains=[
            ("лес",  forest_texts),
            ("горы", mountain_texts),
            ("море", sea_texts),
        ],
        config=RunnerConfig(switch_domain_every=15_000, sleep_every=10_000),
        on_domain_switch=lambda old, new: print(f"Смена домена: {old} → {new}"),
    )
    runner.run(max_transitions=1_000_000)
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from core.learning import LearningSystem
    from core.dream import (
        ContextQueryLog, CrossDomainDetector, DomainRegistry, SleepDriver, SleepResult,
    )
    from core.capacity import CapacityBudget
    from drivers.context_broker import ContextBroker
    from drivers.text_driver import TextDriver
    from drivers.speech_driver import ContextQuery, Observation, SpeechDriver
    from drivers.model_voice import ModelVoice, VoicePrediction, ChannelDivergence


# ══════════════════════════════════════════════════════════════════════════════
# RunnerConfig
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class RunnerConfig:
    """Параметры BackgroundRunner."""

    # Домены
    switch_domain_every: int = 0        # 0 = без смены; >0 = переключать каждые N переходов

    # Сон
    sleep_every:         int = 50_000   # запускать SleepDriver каждые N переходов
    sleep_replays:       int = 20       # SleepDriver.run(n_replays=...)
    sleep_min_chain:     int = 3        # минимальный chain_len события для replay
    sleep_threshold:     int = 10       # мин. число кандидатов для запуска сна

    # Брокер
    broker_tick_every:   int = 50       # broker.tick() каждые N текстов

    # Нарратив (SpeechDriver)
    narrative_verbosity:       int  = 0     # 0=сюрпризы/завершения, 1=всё, 2=детально
    narrative_only_surprises:  bool = True  # on_narrative только при наличии сюрпризов
    gap_min_streak:            int  = 3     # мин. подряд REFUTED для ContextQuery

    # Фаза 3: коррекция значимостей через дивергенцию (требует model_voice)
    correction_every:    int = 0        # 0 = отключено; >0 = каждые N переходов

    # Прогресс
    log_every:           int = 10_000   # callback on_log каждые N переходов


# ══════════════════════════════════════════════════════════════════════════════
# SleepStats / RunnerStats
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class SleepStats:
    transition_at: int    # на каком переходе произошёл сон
    domain:        str    # текущий домен во время сна
    meta_gen:      int    # коммитнуто meta-Gen
    commit_rate:   float  # доля объяснённых событий
    n_replays:     int


@dataclass
class TextNarrative:
    """
    Нарратив пути внимания системы по одному тексту.

    Генерируется SpeechDriver после каждого обработанного текста.
    Используется для:
      • живого лога в терминале (on_narrative callback)
      • анализа учителем-человеком и LLM-учителем
      • будущего драйвера саморефлексии
    """
    text:          str                     # исходный текст
    domain:        str                     # домен обучения
    transition_at: int                     # номер перехода в конце текста
    mr:            float                   # match rate (подтв+завер) / всего
    n_confirmed:   int
    n_completed:   int
    n_refuted:     int
    n_exploring:   int
    surprises:     List[str]               # токены-сюрпризы (REFUTED)
    new_links:     List[str]               # новые Gen-связи из сюрпризов
    summary:       str                     # человекочитаемый итог
    observations:  "List[Observation]"     # все наблюдения (канал B)
    context_gap:   "Optional[ContextQuery]" = None  # запрос брокеру (если разрыв)
    voice_stats:   "Optional[dict]"        = None  # stats() ModelVoice за этот текст

    @property
    def has_surprise(self) -> bool:
        return len(self.surprises) > 0

    @property
    def has_gap(self) -> bool:
        return self.context_gap is not None


@dataclass
class RunnerStats:
    transitions:         int   = 0
    texts_processed:     int   = 0
    elapsed_s:           float = 0.0
    sleep_cycles:        int   = 0
    meta_gen_total:      int   = 0
    broker_ticks:        int   = 0
    domain_switches:     int   = 0
    current_domain:      str   = ""
    sleep_history:       List[SleepStats] = field(default_factory=list)
    voice_records:       int   = 0        # число предсказаний B_модель
    voice_match_rate:    float = 0.0      # доля угаданных (скользящее)
    voice_avg_divergence: float = 0.0    # средняя дивергенция (скользящее)
    # Суммарная статистика переходов (все тексты)
    _total_confirmed:    int   = field(default=0, repr=False)
    _total_completed:    int   = field(default=0, repr=False)
    _total_transitions:  int   = field(default=0, repr=False)

    @property
    def match_rate(self) -> float:
        """Доля CONFIRMED+COMPLETED среди всех переходов."""
        if self._total_transitions == 0:
            return 0.0
        return (self._total_confirmed + self._total_completed) / self._total_transitions

    @property
    def transitions_per_s(self) -> float:
        return self.transitions / self.elapsed_s if self.elapsed_s > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        d = {
            "transitions":        self.transitions,
            "texts_processed":    self.texts_processed,
            "elapsed_s":          round(self.elapsed_s, 2),
            "transitions_per_s":  round(self.transitions_per_s, 1),
            "sleep_cycles":       self.sleep_cycles,
            "meta_gen_total":     self.meta_gen_total,
            "broker_ticks":       self.broker_ticks,
            "domain_switches":    self.domain_switches,
            "current_domain":     self.current_domain,
            "match_rate":         round(self.match_rate, 3),
        }
        if self.voice_records > 0:
            d["voice_records"]       = self.voice_records
            d["voice_match_rate"]    = round(self.voice_match_rate, 3)
            d["voice_avg_divergence"] = round(self.voice_avg_divergence, 3)
        return d


# ══════════════════════════════════════════════════════════════════════════════
# BackgroundRunner
# ══════════════════════════════════════════════════════════════════════════════

class BackgroundRunner:
    """
    Непрерывный обучающий цикл FirstAGI с поддержкой доменного переключения.

    Параметры
    ----------
    system          : LearningSystem            — ядро обучения (обязательно)
    texts           : Iterable[str]             — тексты одного домена (если domains=None)
    domains         : List[(name, Iterable)]    — список доменов для цикличной ротации
    driver          : TextDriver                — токенизатор (создаётся по умолчанию)
    broker          : ContextBroker             — 3-tier брокер контекста (опционально)
    sleep_driver    : SleepDriver               — драйвер сна (опционально)
    detector        : CrossDomainDetector       — для sleep_driver.run() (опционально)
    domain          : str                       — имя домена при использовании texts=
    domain_registry : DomainRegistry            — регистр доменов (опционально)
    capacity        : CapacityBudget            — бюджет ёмкости Gen-базы (опционально)
    config          : RunnerConfig              — параметры цикла
    speech          : SpeechDriver              — нарратив пути внимания (опционально)
    on_sleep        : Callable[SleepStats]      — callback после цикла сна
    on_log          : Callable[dict]            — callback для периодических логов
    on_domain_switch: Callable[str, str]        — callback(old, new) при смене домена
    on_narrative    : Callable[TextNarrative]   — callback после каждого текста с SpeechDriver
    """

    def __init__(
        self,
        system:           "LearningSystem",
        texts:            Optional[Iterable[str]] = None,
        domains:          Optional[List[Tuple[str, Iterable[str]]]] = None,
        driver:           Optional["TextDriver"] = None,
        broker:           Optional["ContextBroker"] = None,
        sleep_driver:     Optional["SleepDriver"] = None,
        detector:         Optional["CrossDomainDetector"] = None,
        domain:           str = "default",
        domain_registry:  Optional["DomainRegistry"] = None,
        capacity:         Optional["CapacityBudget"] = None,
        config:           Optional[RunnerConfig] = None,
        speech:           Optional["SpeechDriver"] = None,
        model_voice:      Optional["ModelVoice"] = None,
        emotion_driver:   Optional["EmotionDriver"] = None,
        annotation_driver: Optional["AnnotationDriver"] = None,
        curiosity_engine: Optional["CharacterCuriosityEngine"] = None,
        llm_worker:       Optional["LLMTeacherWorker"] = None,
        on_sleep:         Optional[Callable[["SleepStats"], None]] = None,
        on_log:           Optional[Callable[[Dict[str, Any]], None]] = None,
        on_domain_switch: Optional[Callable[[str, str], None]] = None,
        on_narrative:     Optional[Callable[["TextNarrative"], None]] = None,
        on_curiosity:     Optional[Callable[[List[Dict]], None]] = None,
        on_llm_teach:     Optional[Callable[[str], None]] = None,
    ) -> None:
        self.system           = system
        self._broker          = broker
        self._sleep_driver    = sleep_driver
        self._detector        = detector
        self._domain_registry = domain_registry
        self._capacity        = capacity
        self.config           = config or RunnerConfig()
        self._speech          = speech
        self._model_voice     = model_voice
        self._emotion         = emotion_driver
        self._annotation      = annotation_driver
        self._curiosity       = curiosity_engine
        self._llm_worker      = llm_worker
        self._on_sleep        = on_sleep
        self._on_log          = on_log
        self._on_domain_switch = on_domain_switch
        self._on_narrative    = on_narrative
        self._on_curiosity    = on_curiosity
        self._on_llm_teach    = on_llm_teach
        self._stop            = False
        self._llm_calls_total = 0
        self._llm_texts_fed   = 0

        # Строим список доменов
        if domains is not None:
            # Materialise iterables so we can cycle them repeatedly
            self._domains: List[Tuple[str, List[str]]] = [
                (name, list(txts)) for name, txts in domains
            ]
        elif texts is not None:
            self._domains = [(domain, list(texts))]
        else:
            raise ValueError("Укажите texts= или domains=")

        # TextDriver
        if driver is None:
            from drivers.text_driver import TextDriver as _TD
            self._driver = _TD("runner")
        else:
            self._driver = driver

        self._stats = RunnerStats(current_domain=self._domains[0][0])

    # ------------------------------------------------------------------
    # Публичный API
    # ------------------------------------------------------------------

    def run(self, max_transitions: Optional[int] = None) -> RunnerStats:
        """
        Запустить непрерывный обучающий цикл.

        Если задан switch_domain_every > 0, последовательно циклирует по доменам:
          домен A → (switch_domain_every переходов) → домен B → ... → домен A → …

        Блокирует до stop() или max_transitions.
        """
        self._stop = False
        self._stats = RunnerStats(current_domain=self._domains[0][0])

        t_start       = time.monotonic()
        last_log_at        = 0
        last_sleep_at      = 0
        last_correction_at = 0
        texts_since_tick = 0

        for domain_name, domain_texts in itertools.cycle(self._domains):
            if self._stop:
                break
            if max_transitions is not None and self._stats.transitions >= max_transitions:
                break

            # Смена домена
            if self._stats.domain_switches > 0 or domain_name != self._stats.current_domain:
                old = self._stats.current_domain
                self._stats.current_domain = domain_name
                if old != domain_name:
                    self._stats.domain_switches += 1
                    if self._on_domain_switch is not None:
                        self._on_domain_switch(old, domain_name)

            # Сброс контекста на границе домена
            self.system.reset_context()

            last_switch_at = self._stats.transitions

            for text in itertools.cycle(domain_texts):
                if self._stop:
                    break
                if max_transitions is not None and self._stats.transitions >= max_transitions:
                    break

                # Проверка смены домена
                if (self.config.switch_domain_every > 0
                        and (self._stats.transitions - last_switch_at)
                            >= self.config.switch_domain_every):
                    break  # выйти из внутреннего цикла → следующий домен

                # ── Регистрируем текст в брокере ─────────────────────
                if self._broker is not None:
                    self._broker.register_source(text, origin=domain_name)

                # ── Сброс нарратива для этого текста ─────────────────
                if self._speech is not None:
                    self._speech.reset_session()
                text_observations: "List[Observation]" = []
                text_gap: "Optional[ContextQuery]" = None
                prev_voice_label: str = ""

                # ── Токены ───────────────────────────────────────────
                for tok in self._driver.produce(text):
                    if self._stop:
                        break
                    if max_transitions is not None and self._stats.transitions >= max_transitions:
                        break

                    # ── B_модель: предсказание ДО токена ─────────────
                    voice_pred: "Optional[VoicePrediction]" = None
                    if self._model_voice is not None:
                        voice_pred = self._model_voice.predict(self.system)

                    result = self.system.process_token(tok)
                    self._stats.transitions += 1
                    self._stats._total_transitions += 1
                    if result.outcome.name == "CONFIRMED":
                        self._stats._total_confirmed += 1
                    elif result.outcome.name == "COMPLETED":
                        self._stats._total_completed += 1

                    # ── EmotionDriver: запись эмоционального контекста ──
                    if self._emotion is not None:
                        active_ids = tuple(self.system.engine.context.active_gen_ids())
                        tok_label = getattr(result.token, "label", "") or ""
                        self._emotion.record(active_ids, result.outcome.name, tok_label)

                    if (self._domain_registry is not None
                            and hasattr(tok.data, "feature_id")):
                        self._domain_registry.register(tok.data.feature_id, domain_name)

                    # ── B_модель: запись и дивергенция ПОСЛЕ токена ───
                    voice_div: "Optional[ChannelDivergence]" = None
                    if self._model_voice is not None and voice_pred is not None:
                        tok_label_mv = getattr(result.token, "label", None) or "?"
                        self._model_voice.record_feature(
                            result.matched_feature_id, tok_label_mv
                        )
                        if prev_voice_label:
                            self._model_voice.record_transition(prev_voice_label, tok_label_mv)
                        prev_voice_label = tok_label_mv
                        voice_div = self._model_voice.diverge(voice_pred, tok_label_mv)
                        self._stats.voice_records += 1

                    # ── SpeechDriver: observe + gap detection ─────────
                    if self._speech is not None:
                        active = self.system.engine.context.active_gen_ids()

                        # Найти ведущий Gen
                        lead_gen, lead_sig = None, 0.0
                        for gid in active:
                            g = self.system.base.get(gid)
                            if g and g.significance > lead_sig:
                                lead_gen, lead_sig = g, g.significance

                        # Прокидываем данные B_модель в наблюдение
                        vp_str = voice_pred.top_word if voice_pred and voice_pred.has_prediction else None
                        vd_val = voice_div.divergence if voice_div is not None else None

                        obs = self._speech.observe(
                            result, self.system.base, active,
                            voice_prediction=vp_str,
                            voice_divergence=vd_val,
                        )
                        if obs:
                            text_observations.append(obs)

                        # Gap detection → broker (если разрыв ещё не найден)
                        if text_gap is None and self._broker is not None:
                            gap = self._speech.detect_context_gap(
                                result, lead_gen, lead_sig,
                                min_streak=self.config.gap_min_streak,
                            )
                            if gap is not None:
                                self._broker.handle_query(gap)
                                text_gap = gap

                self._stats.texts_processed += 1
                texts_since_tick += 1

                # ── on_narrative: итог по тексту ─────────────────────
                if (self._speech is not None
                        and self._on_narrative is not None):
                    narr = self._build_narrative(
                        text, domain_name, text_observations, text_gap
                    )
                    if (not self.config.narrative_only_surprises
                            or narr.has_surprise or narr.has_gap):
                        self._on_narrative(narr)

                # ── CuriosityEngine: вопросы после текста ────────────
                if (self._curiosity is not None
                        and self._on_curiosity is not None
                        and self.system.base.size() >= 10):
                    anchors = self._curiosity.find_anchors()
                    unfamiliar = self._curiosity.find_unfamiliar(anchors)
                    queries = self._curiosity.generate_queries(
                        anchors, unfamiliar, max_queries=5
                    )
                    if queries:
                        self._on_curiosity({
                            "text_preview": text[:50],
                            "anchors": [a.word for a in anchors[:5]],
                            "unfamiliar": [a.word for a in unfamiliar[:3]],
                            "queries": queries,
                            "base_size": self.system.base.size(),
                        })

                # ── LLM-цикл: вопросы → LLM → TEACH → обучение ─────
                if (self._llm_worker is not None
                        and self._curiosity is not None
                        and self.system.base.size() >= 10):
                    # Собрать контекст для LLM
                    log_entries = self.system.teaching_log.get_recent(20)
                    # Сначала observe (вызывает LLM, кэширует решение)
                    self._llm_worker.observe(log_entries)
                    # Затем suggest_content (берёт текст из кэша)
                    content = self._llm_worker.suggest_content(log_entries)
                    if content:
                        self._llm_texts_fed += 1
                        self._llm_calls_total += 1
                        # Загрузить ответ LLM в буфер драйвера
                        for tok in self._driver.produce(content):
                            result_llm = self.system.process_token(tok)
                            self._stats.transitions += 1
                            self._stats._total_transitions += 1
                            if result_llm.outcome.name == "CONFIRMED":
                                self._stats._total_confirmed += 1
                            elif result_llm.outcome.name == "COMPLETED":
                                self._stats._total_completed += 1
                            # Записать в эмоциональный драйвер
                            if self._emotion is not None:
                                active_llm = tuple(
                                    self.system.engine.context.active_gen_ids()
                                )
                                tok_llm = getattr(result_llm.token, "label", "") or ""
                                self._emotion.record(
                                    active_llm, result_llm.outcome.name, tok_llm
                                )
                        self.system.reset_context()
                        if self._on_llm_teach is not None:
                            self._on_llm_teach(content)

                # ── broker.tick() ─────────────────────────────────────
                if (self._broker is not None
                        and texts_since_tick >= self.config.broker_tick_every):
                    self._broker.tick()
                    self._stats.broker_ticks += 1
                    texts_since_tick = 0

                # ── Сон ───────────────────────────────────────────────
                since_sleep = self._stats.transitions - last_sleep_at
                if (self._sleep_driver is not None
                        and since_sleep >= self.config.sleep_every
                        and self._is_log_rich_enough()):
                    self._run_sleep(domain_name)
                    last_sleep_at = self._stats.transitions
                    if self._on_sleep is not None:
                        self._on_sleep(self._stats.sleep_history[-1])

                # ── Фаза 3: коррекция дивергенции ─────────────────────
                if (self.config.correction_every > 0
                        and self._model_voice is not None
                        and (self._stats.transitions - last_correction_at)
                            >= self.config.correction_every):
                    corrections = self._model_voice.get_divergence_corrections()
                    if corrections:
                        self.system.apply_divergence_corrections(corrections)
                    self._model_voice.reset_history()
                    last_correction_at = self._stats.transitions

                # ── Лог ───────────────────────────────────────────────
                since_log = self._stats.transitions - last_log_at
                if since_log >= self.config.log_every:
                    self._stats.elapsed_s = time.monotonic() - t_start
                    if self._on_log is not None:
                        self._on_log(self._snapshot())
                    last_log_at = self._stats.transitions

            # Если switch_domain_every=0 — один домен, не выходим
            if self.config.switch_domain_every == 0:
                break  # выйдем из внешнего цикла после первого прохода домена
                       # (тексты уже зациклены внутренним itertools.cycle)

        self._stats.elapsed_s = time.monotonic() - t_start
        return self._stats

    def stop(self) -> None:
        """Остановить цикл после текущего текста."""
        self._stop = True

    @property
    def current_domain(self) -> str:
        return self._stats.current_domain

    def stats(self) -> Dict[str, Any]:
        return self._snapshot()

    # ------------------------------------------------------------------
    # Внутренние методы
    # ------------------------------------------------------------------

    def _build_narrative(
        self,
        text: str,
        domain: str,
        observations: "List[Observation]",
        gap: "Optional[ContextQuery]",
    ) -> "TextNarrative":
        """Собрать TextNarrative из наблюдений текущего текста."""
        total = max(len(list(self._driver.produce(text))), 1)

        n_conf  = sum(1 for o in observations if o.outcome_tag == "CONFIRMED")
        n_comp  = sum(1 for o in observations if o.outcome_tag == "COMPLETED")
        n_ref   = sum(1 for o in observations if o.outcome_tag == "REFUTED")
        n_expl  = sum(1 for o in observations if o.outcome_tag == "EXPLORING")
        mr = (n_conf + n_comp) / total

        surprises = [o.token_label for o in observations if o.is_surprise]
        new_links = [o.new_gen_hint for o in observations
                     if o.is_surprise and o.new_gen_hint]

        summary = self._speech.summarize(text, observations, total)

        voice_stats = self._model_voice.stats() if self._model_voice is not None else None

        return TextNarrative(
            text          = text,
            domain        = domain,
            transition_at = self._stats.transitions,
            mr            = round(mr, 3),
            n_confirmed   = n_conf,
            n_completed   = n_comp,
            n_refuted     = n_ref,
            n_exploring   = n_expl,
            surprises     = surprises,
            new_links     = new_links,
            summary       = summary,
            observations  = observations,
            context_gap   = gap,
            voice_stats   = voice_stats,
        )

    def _is_log_rich_enough(self) -> bool:
        log = self._sleep_driver.query_log
        n = len(log.candidates(min_chain=self.config.sleep_min_chain))
        return n >= self.config.sleep_threshold

    def _run_sleep(self, domain: str) -> "SleepResult":
        from core.dream import CrossDomainDetector as _CDD
        detector = self._detector or _CDD()
        result = self._sleep_driver.run(
            system    = self.system,
            detector  = detector,
            budget    = self._capacity,
            n_replays = self.config.sleep_replays,
            min_chain = self.config.sleep_min_chain,
        )
        self._stats.sleep_cycles   += 1
        self._stats.meta_gen_total += result.meta_gen_count
        self._stats.sleep_history.append(SleepStats(
            transition_at = self._stats.transitions,
            domain        = domain,
            meta_gen      = result.meta_gen_count,
            commit_rate   = result.commit_rate,
            n_replays     = result.n_replays,
        ))
        return result

    def _snapshot(self) -> Dict[str, Any]:
        # Обновляем voice stats из ModelVoice (скользящие значения)
        if self._model_voice is not None:
            vs = self._model_voice.stats()
            self._stats.voice_match_rate    = vs["match_rate"]
            self._stats.voice_avg_divergence = vs["avg_divergence"]

        d = self._stats.to_dict()
        d["base_size"] = len(self.system.base.all())
        d["stop_flag"] = self._stop
        if self._broker is not None:
            d["broker"] = self._broker.stats()
        return d
