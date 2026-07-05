"""
BackgroundRunner — демо-прогон.

Показывает непрерывный обучающий цикл со всеми компонентами:
  • GenerativeCorpus (4 домена)
  • ContextBroker с CurriculumIndex (FTS5) и QuestionBudget
  • SleepDriver (раз в sleep_every переходов, если лог насыщен)
  • on_log callback — вывод статистики на консоль

Запуск:
    py -X utf8 training/runner_demo.py                 # 50K переходов
    py -X utf8 training/runner_demo.py --transitions 20000
    py -X utf8 training/runner_demo.py --sleep-every 5000
    py -X utf8 training/runner_demo.py --dual-channel  # + B_модель (ModelVoice)
    py -X utf8 training/runner_demo.py --no-color
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict, List, Tuple

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.capacity import CapacityBudget
from core.dream import (
    ContextQueryLog, CrossDomainDetector, DomainRegistry, SleepDriver,
)
from core.learning import LearningSystem
from core.budget import QuestionBudget
from app.runner import BackgroundRunner, RunnerConfig, SleepStats, TextNarrative
from data.gen_base import GenBaseDB
from drivers.context_broker import ContextBroker, CurriculumIndex, SourceTextRegistry
from drivers.model_voice import ModelVoice
from drivers.speech_driver import SpeechDriver
from drivers.text_driver import TextDriver
from training.scale_experiment import GenerativeCorpus


# ─── ANSI цвета ───────────────────────────────────────────────────────────────
_COLOR = True


def _c(code: str, text: str) -> str:
    return f"{code}{text}\033[0m" if _COLOR else text


W  = "\033[0m";  BD = "\033[1m";  DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"; BL = "\033[94m"


# ══════════════════════════════════════════════════════════════════════════════
# Форматирование
# ══════════════════════════════════════════════════════════════════════════════

def _bar(value: float, width: int = 20, full: str = "█", empty: str = "░") -> str:
    filled = int(round(value * width))
    return full * filled + empty * (width - filled)


def _fmt_log(snap: Dict[str, Any], base_size_0: int) -> str:
    t   = snap["transitions"]
    tps = snap["transitions_per_s"]
    bs  = snap["base_size"]
    sc  = snap["sleep_cycles"]
    mg  = snap["meta_gen_total"]
    growth = bs - base_size_0

    lines = [
        f"{BD}── {t:>8,} переходов{W}  "
        f"{DM}{tps:>6,.0f} tok/s{W}  "
        f"base={_c(CY, str(bs))}  "
        f"(+{_c(GR, str(growth))} за сессию)  "
        f"сон={_c(MG, str(sc))}  "
        f"meta-Gen={_c(AM, str(mg))}"
    ]

    if "broker" in snap:
        b = snap["broker"]
        local     = b.get("local_hits", 0)
        curric    = b.get("curriculum_hits", 0)
        remote    = b.get("remote_queries", 0)
        blocked   = b.get("budget_blocked", 0)
        remaining = b.get("budget_remaining", "—")
        lines.append(
            f"  broker: "
            f"tier1={_c(GR, str(local))}  "
            f"tier2={_c(CY, str(curric))}  "
            f"tier3={_c(AM, str(remote))}  "
            f"blocked={_c(RD, str(blocked))}  "
            f"бюджет_осталось={_c(BD, str(remaining))}"
        )

    if "voice_records" in snap:
        mr  = snap["voice_match_rate"]
        div = snap["voice_avg_divergence"]
        mr_color  = GR if mr  >= 0.5 else AM
        div_color = GR if div <= 0.3 else (AM if div <= 0.6 else RD)
        lines.append(
            f"  B_модель: mr={_c(mr_color, f'{mr:.2f}')}  "
            f"avg_div={_c(div_color, f'{div:.2f}')}  "
            f"предсказаний={snap['voice_records']:,}"
        )

    return "\n".join(lines)


def _fmt_narrative(narr: TextNarrative) -> str:
    short_text = (narr.text[:55] + "…") if len(narr.text) > 55 else narr.text
    total = narr.n_confirmed + narr.n_completed + narr.n_refuted + narr.n_exploring
    lines = [
        f"  {BL}📖 [{narr.domain}]{W}  "
        f"mr={_c(GR if narr.mr >= 0.5 else AM, f'{narr.mr:.2f}')}  "
        f"✓{narr.n_confirmed}+★{narr.n_completed} / ✗{narr.n_refuted} / ~{narr.n_exploring}  "
        f"{DM}«{short_text}»{W}"
    ]
    if narr.surprises:
        surp_str = "  ".join(f"{RD}«{s}»{W}" for s in narr.surprises[:4])
        lines.append(f"    ✗ Сюрприз: {surp_str}")
    if narr.new_links:
        links_str = "  ".join(f"{AM}{lnk}{W}" for lnk in narr.new_links[:4])
        lines.append(f"    → Новые связи: {links_str}")
    if narr.context_gap is not None:
        gap = narr.context_gap
        lines.append(
            f"    {MG}⚡ Разрыв контекста:{W} "
            f"токен={_c(BD, gap.trigger_token)}  "
            f"{DM}{gap.query_text[:80]}{W}"
        )
    if narr.voice_stats and narr.voice_stats.get("total", 0) > 0:
        vs = narr.voice_stats
        mr  = vs["match_rate"]
        div = vs["avg_divergence"]
        mr_color  = GR if mr  >= 0.5 else AM
        div_color = GR if div <= 0.3 else (AM if div <= 0.6 else RD)
        lines.append(
            f"    {CY}B_модель:{W} "
            f"mr={_c(mr_color, f'{mr:.2f}')}  "
            f"avg_div={_c(div_color, f'{div:.2f}')}  "
            f"vocab={vs['feature_vocab']}ф+{vs['bigram_vocab']}б"
        )
    return "\n".join(lines)


def _fmt_sleep(ss: SleepStats) -> str:
    bar = _bar(ss.commit_rate)
    return (
        f"\n  {MG}🌙 Сон на переходе {ss.transition_at:,}{W}\n"
        f"     replays={ss.n_replays}  "
        f"meta-Gen={_c(AM, str(ss.meta_gen))}  "
        f"commit_rate={ss.commit_rate:.1%} [{bar}]"
    )


# ══════════════════════════════════════════════════════════════════════════════
# main
# ══════════════════════════════════════════════════════════════════════════════

def main() -> None:
    global _COLOR, W, BD, DM, GR, CY, AM, RD, MG, BL

    parser = argparse.ArgumentParser(description="BackgroundRunner demo")
    parser.add_argument("--transitions", type=int, default=50_000)
    parser.add_argument("--sleep-every", type=int, default=8_000)
    parser.add_argument("--sleep-replays", type=int, default=15)
    parser.add_argument("--sleep-min-chain", type=int, default=0,
                        help="Мин. chain_len для кандидатов сна (0=все REFUTED)")
    parser.add_argument("--sleep-threshold", type=int, default=5,
                        help="Мин. число кандидатов для запуска сна")
    parser.add_argument("--switch-every", type=int, default=5_000,
                        help="Смена домена каждые N переходов (0=не менять)")
    parser.add_argument("--capacity", type=int, default=4000)
    parser.add_argument("--budget", type=int, default=10,
                        help="Суточный лимит LLM-запросов (tier3)")
    parser.add_argument("--log-every", type=int, default=5000)
    parser.add_argument("--narrative-verbosity", type=int, default=0,
                        help="Нарратив: 0=только сюрпризы, 1=все шаги, 2=детально")
    parser.add_argument("--show-all-narratives", action="store_true",
                        help="Показывать нарратив для каждого текста, не только с сюрпризами")
    parser.add_argument("--dual-channel", action="store_true",
                        help="Включить ModelVoice (B_модель): предсказания + дивергенция")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args()

    if args.no_color:
        _COLOR = False
        W = BD = DM = GR = CY = AM = RD = MG = BL = ""

    print(f"{BD}═══ BackgroundRunner Demo ═══{W}")
    print(f"Переходов:  {args.transitions:,}")
    print(f"Сон каждые: {args.sleep_every:,}")
    print(f"Ёмкость:    {args.capacity}")
    print(f"Бюджет:     {args.budget} LLM-запросов/сутки")
    print(f"Смена дом.: каждые {args.switch_every:,}" if args.switch_every > 0
          else "Смена дом.: выключена")
    print(f"Нарратив:   verbosity={args.narrative_verbosity}"
          f"{'  (все тексты)' if args.show_all_narratives else '  (только сюрпризы)'}")
    if args.dual_channel:
        print(f"Двойной кан.: ModelVoice включён (B_модель vs B_интерпретатор)")
    print()

    # ── Компоненты ────────────────────────────────────────────────────
    query_log   = ContextQueryLog()
    capacity    = CapacityBudget(max_gens=args.capacity)
    system      = LearningSystem(capacity_budget=capacity, query_log=query_log)

    # Временная БД для CurriculumIndex (не засоряем prod-базу)
    tmp_db_file = tempfile.NamedTemporaryFile(suffix="_runner_demo.db", delete=False)
    tmp_db_file.close()
    db = GenBaseDB(path=Path(tmp_db_file.name))

    llm_budget  = QuestionBudget(daily_limit=args.budget)
    curriculum  = CurriculumIndex(db)
    registry    = SourceTextRegistry(db=db)
    broker      = ContextBroker(
        teaching_log = system.teaching_log,
        registry     = registry,
        curriculum   = curriculum,
        budget       = llm_budget,
    )

    domain_reg  = DomainRegistry()
    detector    = CrossDomainDetector(domain_registry=domain_reg, min_domains=2)
    sleep_drv   = SleepDriver(query_log)

    # ── Корпус — GenerativeCorpus, 4 домена ───────────────────────────
    corpus = GenerativeCorpus(seed=7)
    domain_texts = []
    for dom in GenerativeCorpus.DOMAINS:
        corpus._domain = dom
        batch = corpus.generate_batch(100)
        domain_texts.append((dom, batch))

    print(f"Корпус: {sum(len(t) for _, t in domain_texts)} текстов "
          f"из {len(domain_texts)} доменов")
    print(f"Домены: {', '.join(d for d, _ in domain_texts)}")
    print()

    # ── Callbacks ─────────────────────────────────────────────────────
    base_size_0 = [0]

    domain_switch_log: List[Tuple[int, str, str]] = []

    def on_log(snap: Dict[str, Any]) -> None:
        if base_size_0[0] == 0:
            base_size_0[0] = snap["base_size"]
        domain = snap.get("current_domain", "")
        print(_fmt_log(snap, base_size_0[0]) +
              (f"  [{_c(BL, domain)}]" if domain else ""))

    def on_domain_switch(old: str, new: str) -> None:
        # будет вызван из run() — сохраним для итога
        domain_switch_log.append((0, old, new))  # transition_at неизвестен здесь
        print(f"\n  {BL}↻ Домен: {old} → {new}{W}")

    def on_sleep(ss: SleepStats) -> None:
        print(_fmt_sleep(ss))

    # ── ModelVoice (опционально) ───────────────────────────────────────
    voice = ModelVoice() if args.dual_channel else None

    # ── SpeechDriver — живой нарратив ─────────────────────────────────
    speech_drv = SpeechDriver(verbosity=args.narrative_verbosity, lang="ru")
    narrative_count = [0]

    def on_narrative(narr: TextNarrative) -> None:
        narrative_count[0] += 1
        print(_fmt_narrative(narr))

    # ── Запуск BackgroundRunner ────────────────────────────────────────
    config = RunnerConfig(
        switch_domain_every       = args.switch_every,
        sleep_every               = args.sleep_every,
        sleep_replays             = args.sleep_replays,
        sleep_min_chain           = args.sleep_min_chain,
        sleep_threshold           = args.sleep_threshold,
        broker_tick_every         = 20,
        narrative_verbosity       = args.narrative_verbosity,
        narrative_only_surprises  = not args.show_all_narratives,
        log_every                 = args.log_every,
    )

    driver = TextDriver("runner")
    runner = BackgroundRunner(
        system            = system,
        domains           = domain_texts if args.switch_every > 0 else None,
        texts             = domain_texts[0][1] if args.switch_every == 0 else None,
        domain            = domain_texts[0][0] if args.switch_every == 0 else "mixed",
        driver            = driver,
        broker            = broker,
        sleep_driver      = sleep_drv,
        detector          = detector,
        domain_registry   = domain_reg,
        capacity          = capacity,
        config            = config,
        speech            = speech_drv,
        model_voice       = voice,
        on_sleep          = on_sleep,
        on_log            = on_log,
        on_domain_switch  = on_domain_switch,
        on_narrative      = on_narrative,
    )

    t0 = time.monotonic()
    stats = runner.run(max_transitions=args.transitions)
    elapsed = time.monotonic() - t0

    # ── Итог ──────────────────────────────────────────────────────────
    print()
    print(f"{BD}═══ Итог ═══{W}")
    print(f"Переходов обработано:  {stats.transitions:>10,}")
    print(f"Текстов обработано:    {stats.texts_processed:>10,}")
    print(f"Время:                 {elapsed:>10.1f} с")
    print(f"Скорость:              {stats.transitions_per_s:>10,.0f} ток/с")
    print(f"Gen в базе:            {len(system.base.all()):>10,}")
    print(f"Циклов сна:            {stats.sleep_cycles:>10,}")
    print(f"Meta-Gen за сны:       {stats.meta_gen_total:>10,}")
    print(f"broker тиков:          {stats.broker_ticks:>10,}")
    print(f"Нарративов выведено:   {narrative_count[0]:>10,}")

    print(f"Смен домена:           {stats.domain_switches:>10,}")

    if stats.sleep_history:
        print()
        print(f"{BD}История сна:{W}")
        for ss in stats.sleep_history:
            bar = _bar(ss.commit_rate, width=15)
            print(
                f"  t={ss.transition_at:>8,}  "
                f"домен={ss.domain:<8}  "
                f"replays={ss.n_replays}  "
                f"meta={ss.meta_gen}  "
                f"commit={ss.commit_rate:.1%} [{bar}]"
            )

    b = broker.stats()
    print()
    print(f"{BD}Брокер контекста:{W}")
    print(f"  Tier1 (реестр):      {b['local_hits']:>6,}")
    print(f"  Tier2 (FTS5):        {b['curriculum_hits']:>6,}")
    print(f"  Tier3 (LLM):         {b['remote_queries']:>6,}")
    print(f"  Заблокировано бюдж.: {b['budget_blocked']:>6,}")
    print(f"  Бюджет остаток:      {b.get('budget_remaining', '—'):>6}")

    print()
    qlog_deep = sum(1 for e in query_log.all_events() if e.is_deep)
    print(f"{BD}Лог удивлений:{W}  всего={len(query_log)}  глубоких(chain≥3)={qlog_deep}")

    if voice is not None:
        vs = voice.stats()
        print()
        print(f"{BD}B_модель (итог):{W}")
        mr  = vs["match_rate"]
        div = vs["avg_divergence"]
        mr_color  = GR if mr  >= 0.5 else AM
        div_color = GR if div <= 0.3 else (AM if div <= 0.6 else RD)
        print(f"  Предсказаний: {vs['total']:,}  "
              f"mr={_c(mr_color, f'{mr:.2f}')}  "
              f"avg_div={_c(div_color, f'{div:.2f}')}")
        print(f"  Словарь: {vs['feature_vocab']} признаков  "
              f"{vs['bigram_vocab']} биграмм")

    db.close()
    try:
        os.unlink(tmp_db_file.name)
    except OSError:
        pass


if __name__ == "__main__":
    main()
