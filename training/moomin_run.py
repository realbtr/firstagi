"""
Долгий обучающий цикл «Муми-тролль» — 1М+ переходов.

Система слушает сказки про Муми-троллей и их друзей.
LLM-учитель (если есть ANTHROPIC_API_KEY) настроен на генерацию продолжений
в стиле Туве Янссон — короткие истории про обитателей Муми-дола.

Запуск:
    py -X utf8 training/moomin_run.py                  # 1M переходов
    py -X utf8 training/moomin_run.py --transitions 500000
    py -X utf8 training/moomin_run.py --no-llm         # только корпус
    py -X utf8 training/moomin_run.py --dual-channel   # + B_модель

Нажми Ctrl+C для остановки — статистика выводится в финале.
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Dict

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.capacity import CapacityBudget
from core.dream import (
    ContextQueryLog, CrossDomainDetector, DomainRegistry, SleepDriver,
)
from core.learning import LearningSystem
from core.provisional import ProvisionalBase
from core.budget import QuestionBudget
from app.runner import BackgroundRunner, RunnerConfig, RunnerStats
from data.gen_base import GenBaseDB
from drivers.context_broker import ContextBroker, CurriculumIndex, SourceTextRegistry
from drivers.model_voice import ModelVoice
from drivers.speech_driver import SpeechDriver
from drivers.text_driver import TextDriver
from training.moomin_corpus import ALL_DOMAINS, MOOMIN_CORPUS


# ── Системный промпт для LLM-учителя ─────────────────────────────────────────

MOOMIN_SYSTEM_PROMPT = """\
Ты — рассказчик сериала про Муми-троллей по мотивам книг Туве Янссон.
Когда тебя просят подать текст (TEACH), генерируй КОРОТКУЮ историю (6-14 слов) \
про обитателей Муми-дола: Муми-тролль, Муми-мама, Муми-папа, Снусмумрик, \
Малышка Мю, Снорочка, Снорк, Хемуль, Морра, Хатифнатты, Филифьонка.
Истории должны быть простыми, повторяющимися по структуре, \
содержать конкретные действия персонажей в Муми-доле или у моря.
Никогда не выходи за рамки вселенной Муми-троллей.
Пиши только по-русски. Никаких английских слов.
"""

# ── ANSI цвета ────────────────────────────────────────────────────────────────

W  = "\033[0m"; BD = "\033[1m"; DM = "\033[90m"
GR = "\033[92m"; CY = "\033[96m"; AM = "\033[93m"
RD = "\033[91m"; MG = "\033[95m"


def _bar(v: float, w: int = 18) -> str:
    f = int(round(v * w))
    return "█" * f + "░" * (w - f)


def _fmt(snap: Dict[str, Any], t0: int) -> str:
    t   = snap["transitions"]
    tps = snap["transitions_per_s"]
    bs  = snap["base_size"]
    sc  = snap["sleep_cycles"]
    mg  = snap["meta_gen_total"]
    mr  = snap.get("match_rate", 0.0)
    dom = snap.get("current_domain", "—")
    elapsed = time.time() - t0
    eta_s = int((1_000_000 - t) / max(tps, 1))

    return (
        f"\n{BD}── {t:>9,} tok{W}  "
        f"{DM}{tps:>6,.0f}/s{W}  "
        f"base={CY}{bs}{W}  "
        f"meta={MG}{mg}{W}  "
        f"sleep={AM}{sc}{W}\n"
        f"   MR={GR}{mr:.2f}{W}  "
        f"dom={CY}{dom}{W}  "
        f"elapsed={int(elapsed//60)}m  "
        f"ETA={eta_s//60}m\n"
        f"   {_bar(mr)} MR"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Moomin training run")
    parser.add_argument("--transitions", type=int, default=1_000_000,
                        help="Число переходов (default: 1 000 000)")
    parser.add_argument("--switch-every", type=int, default=5_000,
                        help="Смена домена каждые N переходов (default: 5 000)")
    parser.add_argument("--sleep-every", type=int, default=20_000,
                        help="Сон каждые N переходов (default: 20 000)")
    parser.add_argument("--log-every", type=int, default=10_000,
                        help="Лог каждые N переходов (default: 10 000)")
    parser.add_argument("--capacity", type=int, default=8_000,
                        help="Макс. Gen в базе (default: 8 000)")
    parser.add_argument("--llm-budget", type=int, default=50,
                        help="Макс. LLM-запросов в сутки (default: 50)")
    parser.add_argument("--no-llm", action="store_true",
                        help="Не использовать LLM даже при наличии API key")
    parser.add_argument("--dual-channel", action="store_true",
                        help="Включить ModelVoice (B_модель)")
    parser.add_argument("--db", type=str, default="",
                        help="Путь к GenBaseDB (default: tmp)")
    args = parser.parse_args()

    print(f"\n{BD}{CY}{'═'*64}{W}")
    print(f"{BD}{CY}  Сказки Муми-тролля · FirstAGI · {args.transitions:,} переходов{W}")
    print(f"{BD}{CY}{'═'*64}{W}\n")

    # ── GenBaseDB ─────────────────────────────────────────────────────────────
    if args.db:
        db_path = Path(args.db)
    else:
        db_path = Path(tempfile.mkdtemp()) / "moomin.db"
    db = GenBaseDB(db_path)
    print(f"  DB: {db_path}")

    # ── LearningSystem ────────────────────────────────────────────────────────
    query_log   = ContextQueryLog()
    capacity    = CapacityBudget(max_gens=args.capacity)
    provisional = ProvisionalBase(min_confirmations=2, max_age=200)
    system      = LearningSystem(
        capacity_budget=capacity,
        query_log=query_log,
        provisional_base=provisional,
    )

    # ── SourceTextRegistry + CurriculumIndex ─────────────────────────────────
    registry = SourceTextRegistry(db=db)
    for name, texts in ALL_DOMAINS:
        for t in texts:
            registry.register(t, source_id=name, origin="corpus")

    curriculum = CurriculumIndex(db)

    budget = QuestionBudget(daily_limit=args.llm_budget)

    # LLM-учитель (опционально)
    llm_teacher = None
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if api_key and not args.no_llm:
        try:
            from core.llm_broker import AnthropicClient, LLMTeacherWorker
            llm_client = AnthropicClient(
                api_key=api_key,
                model="claude-haiku-4-5-20251001",
                max_tokens=128,
                system_prompt=MOOMIN_SYSTEM_PROMPT,
            )
            llm_teacher = LLMTeacherWorker(
                system=system,
                llm_client=llm_client,
            )
            print(f"  LLM-учитель: {GR}claude-haiku{W} (бюджет: {args.llm_budget}/день)")
        except Exception as e:
            print(f"  {AM}LLM недоступен: {e}{W}")
    else:
        reason = "--no-llm" if args.no_llm else "нет ANTHROPIC_API_KEY"
        print(f"  LLM: {DM}отключён ({reason}) — только корпус{W}")

    broker = ContextBroker(
        teaching_log = system.teaching_log,
        registry     = registry,
        curriculum   = curriculum,
        budget       = budget,
    )

    # ── Dream ─────────────────────────────────────────────────────────────────
    domain_reg = DomainRegistry()
    cross_det  = CrossDomainDetector(domain_registry=domain_reg, min_domains=2)
    sleep_drv  = SleepDriver(query_log)

    # ── SpeechDriver ──────────────────────────────────────────────────────────
    speech = SpeechDriver(verbosity=0)

    # ── ModelVoice ─────────────────────────────────────────────────────────────
    voice = ModelVoice() if args.dual_channel else None
    if voice:
        print(f"  B_модель: {GR}включена{W}")

    # ── BackgroundRunner ───────────────────────────────────────────────────────
    config = RunnerConfig(
        switch_domain_every = args.switch_every,
        sleep_every         = args.sleep_every,
        sleep_threshold     = 5,
        broker_tick_every   = 200,
        log_every           = args.log_every,
        correction_every    = 5_000 if voice else 0,
    )

    t0 = time.time()

    def on_log(snap: Dict[str, Any]) -> None:
        print(_fmt(snap, t0))

    def on_sleep(stats) -> None:
        dom = getattr(stats, "domain", "?")
        mg  = getattr(stats, "meta_gen_created", 0)
        print(f"\n  {MG}[SLEEP]{W} домен={dom}  meta_gen={mg}")

    def on_domain(old: str, new: str) -> None:
        print(f"  {CY}→ {old} → {new}{W}", end="", flush=True)

    runner = BackgroundRunner(
        system           = system,
        domains          = ALL_DOMAINS,
        broker           = broker,
        sleep_driver     = sleep_drv,
        domain_registry  = domain_reg,
        detector         = cross_det,
        capacity         = capacity,
        config           = config,
        speech           = speech,
        model_voice      = voice,
        on_log           = on_log,
        on_sleep         = on_sleep,
        on_domain_switch = on_domain,
    )

    print(f"\n  Корпус: {len(MOOMIN_CORPUS)} текстов · {len(ALL_DOMAINS)} доменов")
    print(f"  Capacity: {args.capacity:,} Gen  ·  switch_every={args.switch_every:,}")
    print(f"  Старт...\n")

    try:
        stats: RunnerStats = runner.run(max_transitions=args.transitions)
    except KeyboardInterrupt:
        runner.stop()
        stats = runner.stats()
        print(f"\n\n  {AM}Прервано пользователем{W}")

    # ── Итоги ─────────────────────────────────────────────────────────────────
    elapsed = time.time() - t0
    print(f"\n{BD}{CY}{'═'*64}{W}")
    print(f"{BD}  ИТОГ{W}")
    print(f"{BD}{CY}{'═'*64}{W}")
    print(f"  переходов:    {stats.transitions:>10,}")
    print(f"  время:        {int(elapsed//60)}м {int(elapsed%60)}с")
    print(f"  ср. скорость: {stats.transitions/max(elapsed,1):>10,.0f} tok/s")
    print(f"  sleep_cycles: {stats.sleep_cycles:>10,}")
    print(f"  meta_gen:     {stats.meta_gen_total:>10,}")
    print(f"  domain_sw:    {stats.domain_switches:>10,}")
    if voice:
        mr = stats.voice_match_rate
        dv = stats.voice_avg_divergence
        rc = stats.voice_records
        print(f"  B_модель:     MR={mr:.3f}  avg_div={dv:.3f}  записей={rc:,}")
    print()


if __name__ == "__main__":
    main()
