"""
«Почемучка» — обучение с любопытством.

Схема: 4 фазы × (10K обучение → 10K сон).
Порядок доменов намеренно создаёт семантические «мосты»:
  serial/угощение + winnie/мёд  → мост «ест»/«угостил»
  serial/опасность + winnie/беда → мост «испугался»/«помог»
  moomin + winnie/зима           → мост «нашёл»/«ушёл»

После каждого сна отображаются три типа вопросов:
  1. pattern_questions()  — «почемучка»: кто ещё ест морковку?
  2. unnamed_clusters()   — «как называется»: мёд, пирог, ягоды, морковка?
  3. knowledge_gaps()     — «что дальше»: что происходит с гармошкой?

Запуск:
    py -X utf8 training/curiosity_run.py
    py -X utf8 training/curiosity_run.py --transitions 5000   # быстрый тест
    py -X utf8 training/curiosity_run.py --db data/gen_base.db --resume
    py -X utf8 training/curiosity_run.py --no-llm
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.capacity import CapacityBudget
from core.generalization import GeneralizationBase
from core.dream import (
    ContextQueryLog, CrossDomainDetector, DomainRegistry, SleepDriver,
)
from core.learning import LearningSystem
from core.provisional import ProvisionalBase
from core.budget import QuestionBudget
from app.runner import BackgroundRunner, RunnerConfig, RunnerStats
from data.gen_base import GenBaseDB
from drivers.context_broker import ContextBroker, CurriculumIndex, SourceTextRegistry
from drivers.narrator_driver import NarratorDriver, CreativityLevel, UnnamedClusterDetector
from drivers.text_driver import TextDriver
from training.corpus import TextCorpus, _CORPUS
from training.serial_corpus import SITUATION_FAMILIES, EPISODE_ARCS
from training.winnie_corpus import ALL_DOMAINS as WINNIE_DOMAINS
from training.moomin_corpus import MOOMIN_CORPUS

# ── ANSI ──────────────────────────────────────────────────────────────────────
W  = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; YL = "\033[33m"


def hr(title: str = "", w: int = 68) -> None:
    if title:
        pad = (w - len(title) - 2) // 2
        print(f"\n{BD}{'═'*pad} {title} {'═'*pad}{W}")
    else:
        print(f"{DM}{'─'*w}{W}")


# ══════════════════════════════════════════════════════════════════════════════
# Лог любопытства
# ══════════════════════════════════════════════════════════════════════════════

class CuriosityLogger:
    """Собирает события обучения и вопросы модели в структурированный JSON-лог."""

    def __init__(self) -> None:
        self._events: List[Dict[str, Any]] = []
        self._t0 = time.time()
        self._last_domain: Optional[str] = None
        self._phase: int = 0

    # ── запись событий ─────────────────────────────────────────────────────

    def set_phase(self, phase: int, kind: str, domains: List[str]) -> None:
        self._phase = phase
        self._last_domain = None
        self._add("phase_start", kind=kind, phase=phase, domains=domains)

    def on_log_snap(self, snap: Dict[str, Any]) -> None:
        dom = snap.get("current_domain")
        if dom and dom != self._last_domain:
            self._add("domain_switch",
                      domain=dom,
                      transitions=snap.get("transitions", 0),
                      base_size=snap.get("base_size", 0),
                      match_rate=round(snap.get("match_rate", 0.0), 4))
            self._last_domain = dom

    def on_sleep(self, meta_gen: int, transitions: int, base_size: int) -> None:
        self._add("sleep",
                  meta_gen_created=meta_gen,
                  transitions=transitions,
                  base_size=base_size)

    def on_questions(self, phase: int,
                     pattern_qs: List[str],
                     cluster_qs: List[str],
                     gap_qs: List[str],
                     bridges: List[Tuple[str, int]]) -> None:
        self._add("curiosity_questions",
                  phase=phase,
                  pattern_questions=pattern_qs,
                  cluster_questions=cluster_qs,
                  gap_questions=gap_qs,
                  semantic_bridges=[{"word": w, "degree": d} for w, d in bridges])

    def on_checkpoint(self, gen_count: int) -> None:
        self._add("checkpoint", gen_count=gen_count)

    # ── вспомогательные ────────────────────────────────────────────────────

    def _add(self, event: str, **kw) -> None:
        self._events.append({"event": event,
                              "phase": self._phase,
                              "elapsed_s": round(time.time() - self._t0, 1),
                              **kw})

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"events": self._events,
                       "total_events": len(self._events)}, f,
                      ensure_ascii=False, indent=2)
        print(f"  {GR}Лог сохранён: {path}  ({len(self._events)} событий){W}")


# ══════════════════════════════════════════════════════════════════════════════
# Построение доменов для каждой фазы
# (порядок создаёт максимум семантических мостов)
# ══════════════════════════════════════════════════════════════════════════════

def _make_domains() -> Dict[str, List[Tuple[str, List[str]]]]:
    """
    Возвращает словарь: имя_фазы → список доменов [(name, texts)].

    Принцип «почемучки»: одно и то же семантическое поле (еда, помощь, поиск)
    намеренно появляется в РАЗНЫХ корпусах подряд → CrossDomainDetector
    обнаруживает мосты во сне → GapQ генерирует вопросы-расширения.
    """
    corpus = TextCorpus()

    # ── Фаза 1: Фундамент (ритмы → нарративы) ────────────────────────────────
    phase1_domains = [
        ("corpus_l1",     corpus.get_level(1)),   # бинарные циклы
        ("corpus_l2",     corpus.get_level(2)),   # ритмичные паттерны
        ("corpus_l3",     corpus.get_level(3)),   # нарративы
        ("corpus_l4",     corpus.get_level(4)),   # развилки
    ]

    # ── Фаза 2: Персонажи + кооперация ────────────────────────────────────────
    # «Мост угощение»: заяц ест морковку (serial) → Пух ест мёд (winnie)
    # «Мост помощь»: медведь помог маше (serial) → Пятачок помог Пуху (winnie)
    phase2_domains = [
        ("serial_встреча",  SITUATION_FAMILIES["встреча"]),
        ("serial_угощение", SITUATION_FAMILIES["угощение"]),  # ← «ест», «угостил»
        ("serial_помощь",   SITUATION_FAMILIES["помощь"]),    # ← «помог», «поблагодарил»
        ("winnie_friends",  WINNIE_DOMAINS[1][1]),             # встречи друзей
        ("winnie_honey",    WINNIE_DOMAINS[0][1]),             # ← «ест», «мёд»
        ("winnie_rabbit",   WINNIE_DOMAINS[2][1]),             # ← «угостил», «морковь»
    ]

    # ── Фаза 3: Конфликт, поиск, кросс-корпусные мосты ───────────────────────
    # «Мост испугался»: заяц испугался волка (serial) → Пятачок испугался Тигры (winnie)
    # «Мост нашёл»: маша нашла корзину (serial) → Муми нашёл пещеру (moomin)
    moomin_domains = [
        ("moomin_all", MOOMIN_CORPUS),
    ]
    phase3_domains = [
        ("serial_опасность",   SITUATION_FAMILIES["опасность"]),   # ← «испугался», «спасся»
        ("serial_поиск",       SITUATION_FAMILIES["поиск"]),        # ← «нашёл», «потерял»
        ("serial_спор",        SITUATION_FAMILIES["спор"]),         # ← «поспорили», «помирились»
        ("winnie_winter",      WINNIE_DOMAINS[3][1]),               # холод, голод
        ("winnie_character",   WINNIE_DOMAINS[4][1]),               # характеры
        ("moomin_all",         MOOMIN_CORPUS),                      # ← «нашёл», «ушёл» (мост)
    ]

    # ── Фаза 4: Обогащение — всё вперемежку ──────────────────────────────────
    # Микросериальные дуги: нарратив через 3 текста → длинные Gen
    arc_texts = [t for arc in EPISODE_ARCS for t in arc]
    phase4_domains = [
        ("serial_праздник",    SITUATION_FAMILIES["праздник"]),
        ("serial_потеря",      SITUATION_FAMILIES["потеря"]),
        ("serial_возвращение", SITUATION_FAMILIES["возвращение"]),
        ("arcs_micro_serial",  arc_texts),       # эпизодические дуги
        ("winnie_all",         [t for _, ts in WINNIE_DOMAINS for t in ts]),
        ("moomin_repeat",      MOOMIN_CORPUS),
        ("corpus_l3_repeat",   corpus.get_level(3)),  # нарративы повторно
    ]

    return {
        "phase1": phase1_domains,
        "phase2": phase2_domains,
        "phase3": phase3_domains,
        "phase4": phase4_domains,
    }


# ══════════════════════════════════════════════════════════════════════════════
# Система
# ══════════════════════════════════════════════════════════════════════════════

def _build_system(
    args: argparse.Namespace,
    db: GenBaseDB,
    all_texts: List[str],
    resume: bool = False,
) -> Tuple[LearningSystem, ContextBroker, SleepDriver, DomainRegistry, CrossDomainDetector, CapacityBudget]:
    query_log   = ContextQueryLog()
    capacity    = CapacityBudget(max_gens=args.capacity)
    provisional = ProvisionalBase(min_confirmations=2, max_age=200)
    system      = LearningSystem(
        capacity_budget = capacity,
        query_log       = query_log,
        provisional_base= provisional,
    )
    if resume:
        n = db.load(system.base)
        print(f"  {GR}Загружено из БД: {n} Gen{W}")

    registry = SourceTextRegistry(db=db)
    for t in all_texts:
        registry.register(t, source_id="curiosity_corpus", origin="corpus")

    curriculum = CurriculumIndex(db)
    budget     = QuestionBudget(daily_limit=args.llm_budget)

    llm_teacher = None
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key and not args.no_llm:
        try:
            from core.llm_broker import AnthropicClient, LLMTeacherWorker
            client = AnthropicClient(
                api_key=api_key,
                model="claude-haiku-4-5-20251001",
                max_tokens=128,
                system_prompt=_SYSTEM_PROMPT,
            )
            llm_teacher = LLMTeacherWorker(system=system, llm_client=client)
            print(f"  LLM-учитель: {GR}claude-haiku{W} (бюджет: {args.llm_budget}/день)")
        except Exception as e:
            print(f"  {AM}LLM недоступен: {e}{W}")
    else:
        reason = "--no-llm" if args.no_llm else "нет ANTHROPIC_API_KEY"
        print(f"  LLM: {DM}отключён ({reason}){W}")

    broker     = ContextBroker(
        teaching_log = system.teaching_log,
        registry     = registry,
        curriculum   = curriculum,
        budget       = budget,
    )
    domain_reg = DomainRegistry()
    cross_det  = CrossDomainDetector(domain_registry=domain_reg, min_domains=2)
    sleep_drv  = SleepDriver(query_log)

    return system, broker, sleep_drv, domain_reg, cross_det, capacity


_SYSTEM_PROMPT = """\
Ты — рассказчик историй для обучения языковой модели.
Когда тебя просят (TEACH), генерируй КОРОТКУЮ историю (6-14 слов) на русском языке.
Используй персонажей и ситуации из контекста.
Делай истории простыми, конкретными, с чёткими субъект-действие-объект отношениями.
Никогда не выходи за рамки детских сказок о животных и людях в лесу.
Пиши только по-русски.
"""


# ══════════════════════════════════════════════════════════════════════════════
# Одна фаза обучения
# ══════════════════════════════════════════════════════════════════════════════

def _run_one_phase(
    phase_name: str,
    domains: List[Tuple[str, List[str]]],
    system: LearningSystem,
    broker: ContextBroker,
    sleep_drv: SleepDriver,
    domain_reg: DomainRegistry,
    cross_det: CrossDomainDetector,
    capacity: CapacityBudget,
    transitions: int,
    sleep_every: int,
    is_sleep_phase: bool = False,
    logger: Optional[CuriosityLogger] = None,
) -> RunnerStats:
    """Запустить одну фазу (обучение или сон) через BackgroundRunner."""
    t0 = time.time()

    config = RunnerConfig(
        switch_domain_every = max(200, transitions // (len(domains) * 3)),
        sleep_every         = sleep_every,
        sleep_threshold     = 1 if is_sleep_phase else 5,
        broker_tick_every   = 100,
        log_every           = max(1000, transitions // 5),
    )

    stats_snap: List[Dict[str, Any]] = []
    _last_sleep_transitions = [0]

    def on_log(snap: Dict[str, Any]) -> None:
        t  = snap["transitions"]
        bs = snap["base_size"]
        sc = snap["sleep_cycles"]
        mr = snap.get("match_rate", 0.0)
        dom = snap.get("current_domain", "—")
        elapsed = time.time() - t0
        print(f"  {DM}{t:>7,} tok{W}  base={CY}{bs}{W}  "
              f"sleep={AM}{sc}{W}  MR={GR}{mr:.3f}{W}  "
              f"dom={dom}  {int(elapsed)}s")
        stats_snap.append(snap)
        if logger:
            logger.on_log_snap(snap)

    def on_sleep(stats: Any) -> None:
        mg = getattr(stats, "meta_gen_created", 0)
        bs = system.base.size()
        tr = _last_sleep_transitions[0]
        print(f"  {MG}[SLP]{W} meta_gen={mg}", end="  ", flush=True)
        if logger:
            logger.on_sleep(mg, tr, bs)
        _last_sleep_transitions[0] = tr + sleep_every

    runner = BackgroundRunner(
        system           = system,
        domains          = domains,
        broker           = broker,
        sleep_driver     = sleep_drv,
        domain_registry  = domain_reg,
        detector         = cross_det,
        capacity         = capacity,
        config           = config,
        on_log           = on_log,
        on_sleep         = on_sleep,
    )

    try:
        result = runner.run(max_transitions=transitions)
    except KeyboardInterrupt:
        runner.stop()
        result = runner.stats()
        print(f"\n  {AM}Прервано{W}")

    elapsed = time.time() - t0
    print(f"\n  {phase_name}: {result.transitions:,} tok  "
          f"sleep={result.sleep_cycles}  MR={result.match_rate:.3f}  "
          f"{int(elapsed)}s")
    return result


# ══════════════════════════════════════════════════════════════════════════════
# Вопросы «почемучки» после сна
# ══════════════════════════════════════════════════════════════════════════════

def _show_curiosity_questions(
    base: GeneralizationBase,
    phase: int,
    logger: Optional[CuriosityLogger] = None,
) -> None:
    """Показать все три типа вопросов после фазы сна."""
    if base.size() < 10:
        return

    narrator = NarratorDriver(base, seed=42)

    # 1. Вопросы-расширения паттернов («почемучка»)
    pq = narrator.pattern_questions(max_questions=8)
    if pq:
        print(f"\n  {YL}❓ Вопросы-расширения (кто ещё? что ещё?):{W}")
        for q in pq:
            print(f"     • {q}")

    # 2. Вопросы о безымянных категориях
    uq = narrator.unnamed_clusters(min_children=3, max_questions=5)
    if uq:
        print(f"\n  {MG}❓ Безымянные категории (как называется?):{W}")
        for q in uq:
            print(f"     • {q}")

    # 3. Классические вопросы о пробелах
    kq = narrator.knowledge_gaps(max_questions=6)
    if kq:
        print(f"\n  {CY}❓ Пробелы знания (что дальше?):{W}")
        for q in kq:
            print(f"     • {q}")

    # Топ мостовых слов (семантическое ядро)
    graph = narrator._graph
    bridges = sorted(
        [(w, graph.in_degree(w) + graph.degree(w)) for w in graph.all_words()
         if graph.in_degree(w) >= 2 and graph.degree(w) >= 2],
        key=lambda x: -x[1]
    )
    if bridges:
        top_b = [f"{w}({d})" for w, d in bridges[:6]]
        print(f"\n  {GR}Семантические мосты: {', '.join(top_b)}{W}")

    if logger:
        logger.on_questions(phase, pq, uq, kq, bridges[:10])


# ══════════════════════════════════════════════════════════════════════════════
# Watch mode: интерактивный вывод в реальном времени
# ══════════════════════════════════════════════════════════════════════════════

def _show_watch(
    base: GeneralizationBase,
    phase: int,
) -> None:
    """Показать полный анализ модели в watch mode."""
    from core.curiosity import CharacterCuriosityEngine

    if base.size() < 5:
        return

    engine = CharacterCuriosityEngine(base)
    anchors = engine.find_anchors()
    unfamiliar = engine.find_unfamiliar(anchors)
    queries = engine.generate_queries(anchors, unfamiliar, max_queries=8)

    hr(f"WATCH — Фаза {phase}")

    # Опоры
    print(f"\n  {BD}Анкоры модели:{W}")
    for a in anchors[:8]:
        flag = f" {AM}[unfamiliar]{W}" if a.is_unfamiliar else ""
        bar = "█" * int(a.significance * 20)
        print(f"    {GR}{a.word:<15}{W} sig={AM}{a.significance:.3f}{W} "
              f"gen={a.gen_count:>3}  {DM}{bar}{W}{flag}")

    # Unfamiliar
    if unfamiliar:
        print(f"\n  {AM}Хочет узнать больше:{W}")
        for a in unfamiliar[:5]:
            print(f"    • «{a.word}» — {a.gen_count} Gen, sig={a.significance:.3f}")
            if a.contexts:
                print(f"      контекст: {a.contexts[0]}")

    # Запросы
    if queries:
        print(f"\n  {CY}Запросы к учителю:{W}")
        for q in queries[:6]:
            prio = {1: f"{RD}!!{W}", 2: f"{AM}!{W}", 3: f"{DM}.{W}"}.get(q["priority"], "")
            print(f"    {prio} {q['question']}")
            print(f"      {DM}{q['context'][:80]}...{W}")

    # Навигация по гетерархии (пример для первого анкора)
    if anchors:
        top_word = anchors[0].word
        path = engine.hierarchy_path(top_word)
        if path:
            print(f"\n  {BD}Гетерархия «{top_word}»:{W}")
            for p in path[:6]:
                indent = "  " * min(p["chain_len"], 5)
                print(f"    {indent}L{p['chain_len']:<2} sig={p['sig']:.2f} "
                      f"→[{p['children']}↑{p['parents']}]  {DM}{p['label'][:40]}{W}")

    # Семантические мосты
    narrator = NarratorDriver(base, seed=42)
    graph = narrator._graph
    bridges = sorted(
        [(w, graph.in_degree(w) + graph.degree(w)) for w in graph.all_words()
         if graph.in_degree(w) >= 2 and graph.degree(w) >= 2],
        key=lambda x: -x[1]
    )
    if bridges:
        top_b = [f"{w}({d})" for w, d in bridges[:6]]
        print(f"\n  {GR}Мосты: {', '.join(top_b)}{W}")


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(description="Обучение «Почемучка»")
    parser.add_argument("--transitions", type=int, default=10_000,
                        help="Переходов на каждую фазу (default: 10 000)")
    parser.add_argument("--capacity", type=int, default=8_000,
                        help="Макс. Gen (default: 8 000)")
    parser.add_argument("--llm-budget", type=int, default=50,
                        help="Макс. LLM-запросов в сутки (default: 50)")
    parser.add_argument("--db", type=str, default="data/gen_base.db",
                        help="Путь к GenBaseDB (default: data/gen_base.db)")
    parser.add_argument("--resume", action="store_true",
                        help="Загрузить существующую БД (cold start)")
    parser.add_argument("--no-llm", action="store_true",
                        help="Не использовать LLM")
    parser.add_argument("--phase", type=int, default=0,
                        help="Запустить только одну фазу 1-4 (0 = все)")
    parser.add_argument("--log-json", type=str, default="",
                        help="Путь для JSON-лога любопытства (пусто = не сохранять)")
    parser.add_argument("--watch", action="store_true",
                        help="Watch mode: показывать вопросы модели в реальном времени")
    args = parser.parse_args()

    hr("ОБУЧЕНИЕ «ПОЧЕМУЧКА»")
    T  = args.transitions       # переходов на фазу обучения
    TS = T                      # переходов на фазу сна (столько же)

    # ── БД ────────────────────────────────────────────────────────────────────
    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = GenBaseDB(db_path)
    print(f"\n  {'Резюме из' if args.resume else 'Новая база'} · DB: {db_path}")

    # ── Сборка всех доменов ───────────────────────────────────────────────────
    phase_domains = _make_domains()
    all_texts = list({
        t
        for domains in phase_domains.values()
        for _, texts in domains
        for t in texts
    })

    system, broker, sleep_drv, domain_reg, cross_det, capacity = \
        _build_system(args, db, all_texts, resume=args.resume)

    print(f"\n  Переходов на фазу: {T:,}  ·  capacity: {args.capacity:,}")
    print(f"  Текстов в пуле: {len(all_texts)}  ·  DB: {db_path}\n")

    phases_to_run = [1, 2, 3, 4] if args.phase == 0 else [args.phase]
    t_total = time.time()

    logger = CuriosityLogger()

    for phase_num in phases_to_run:
        pname  = f"phase{phase_num}"
        domains = phase_domains[pname]
        domain_names_list = [n for n, _ in domains]

        # ── Фаза обучения ─────────────────────────────────────────────────────
        hr(f"ФАЗА {phase_num}: ОБУЧЕНИЕ ({T:,} переходов)")
        domain_names = ", ".join(domain_names_list)
        print(f"  Домены: {domain_names}\n")

        logger.set_phase(phase_num, "train", domain_names_list)
        _run_one_phase(
            phase_name = f"Фаза {phase_num}",
            domains    = domains,
            system     = system,
            broker     = broker,
            sleep_drv  = sleep_drv,
            domain_reg = domain_reg,
            cross_det  = cross_det,
            capacity   = capacity,
            transitions = T,
            sleep_every = max(500, T // 20),
            logger      = logger,
        )

        # Checkpoint после обучения
        saved = db.checkpoint(system.base)
        print(f"  {GR}✓ Checkpoint: {saved} Gen сохранено{W}")
        logger.on_checkpoint(saved)

        # ── Фаза сна ──────────────────────────────────────────────────────────
        hr(f"ФАЗА {phase_num}: СОН ({TS:,} переходов, sleep_every=100)")

        logger.set_phase(phase_num, "sleep", domain_names_list)
        _run_one_phase(
            phase_name   = f"Сон {phase_num}",
            domains      = domains,    # те же тексты — модель «переваривает»
            system       = system,
            broker       = broker,
            sleep_drv    = sleep_drv,
            domain_reg   = domain_reg,
            cross_det    = cross_det,
            capacity     = capacity,
            transitions  = TS,
            sleep_every  = 100,        # ← частый сон = глубокая консолидация
            is_sleep_phase = True,
            logger        = logger,
        )

        # Checkpoint после сна
        saved = db.checkpoint(system.base)
        print(f"  {GR}✓ Checkpoint: {saved} Gen (после сна){W}")
        logger.on_checkpoint(saved)

        # Вопросы «почемучки»
        _show_curiosity_questions(system.base, phase_num, logger=logger)

        # Watch mode: показать что модель «думает»
        if args.watch:
            _show_watch(system.base, phase_num)
        print()

    # ── Итоги ─────────────────────────────────────────────────────────────────
    elapsed = time.time() - t_total
    hr("ИТОГ")
    print(f"  База Gen:    {system.base.size():>8,}")
    print(f"  Время:       {int(elapsed//60)}м {int(elapsed%60)}с")
    print(f"  DB:          {db_path}")

    # Сохранить JSON-лог
    log_path_str = args.log_json or "training/curiosity_log.json"
    logger.save(Path(log_path_str))

    # Финальный нарратив
    if system.base.size() >= 10:
        hr("НАРРАТОР — финальные примеры")
        narrator = NarratorDriver(system.base, seed=0)
        for level in [CreativityLevel.RECALL, CreativityLevel.COMPOSE, CreativityLevel.DREAM]:
            r = narrator.generate(level, max_words=14)
            if r.text:
                print(f"  {CY}[{level.name:<7}]{W} «{r.text}»")

    print()


if __name__ == "__main__":
    main()
