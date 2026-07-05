"""
Шаг 8: Демо-скрипт LLM-брокера.

Использование:
    py -X utf8 training/llm_run.py --steps 50 --mock
    py -X utf8 training/llm_run.py --steps 50 --live      # требует ANTHROPIC_API_KEY
    py -X utf8 training/llm_run.py --interactive --mock    # до Ctrl+C
"""

from __future__ import annotations

import argparse
import os
import sys

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from core.app import CoreApplication
from core.llm_broker import (
    AnthropicClient,
    LLMTeacherWorker,
    MockLLMClient,
)
from training.llm_loop import BrokerLoop


# ══════════════════════════════════════════════════════════════════════
# Умный MockLLMClient для демонстрации
# ══════════════════════════════════════════════════════════════════════

_MOCK_TEACH_RESPONSES = [
    '{"action":"TEACH","text":"день ночь день ночь день ночь","amount":0,"reason":"простой бинарный паттерн"}',
    '{"action":"WAIT","text":"","amount":0,"reason":"даю время усвоить"}',
    '{"action":"TEACH","text":"утро вечер утро вечер утро вечер","amount":0,"reason":"ритм суток"}',
    '{"action":"REWARD","text":"","amount":5.0,"reason":"хорошие петли"}',
    '{"action":"TEACH","text":"кот сидит на окне кот встаёт кот сидит","amount":0,"reason":"нарративный паттерн"}',
    '{"action":"WAIT","text":"","amount":0,"reason":"наблюдаю"}',
    '{"action":"TEACH","text":"раз два три раз два три раз два три","amount":0,"reason":"счётный ритм"}',
    '{"action":"REWARD","text":"","amount":8.0,"reason":"хороший hit rate"}',
    '{"action":"TEACH","text":"Маша пришла Маша ушла Маша пришла","amount":0,"reason":"социальный паттерн"}',
    '{"action":"WAIT","text":"","amount":0,"reason":"модель обрабатывает"}',
]


def build_mock_client() -> MockLLMClient:
    """Создать MockLLMClient с разнообразными учебными ответами."""
    return MockLLMClient(responses=_MOCK_TEACH_RESPONSES)


def build_live_client() -> AnthropicClient:
    """Создать реальный клиент Claude API."""
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not api_key:
        print(
            "[Ошибка] Установите переменную окружения ANTHROPIC_API_KEY.",
            file=sys.stderr,
        )
        sys.exit(1)
    return AnthropicClient(api_key=api_key)


# ══════════════════════════════════════════════════════════════════════
# Основной скрипт
# ══════════════════════════════════════════════════════════════════════

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Шаг 8 — LLM-брокер FirstAGI"
    )
    parser.add_argument(
        "--steps", type=int, default=50,
        help="Число шагов брокер-цикла (по умолчанию 50)"
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--mock", action="store_true", default=True,
        help="Использовать MockLLMClient (по умолчанию)"
    )
    mode_group.add_argument(
        "--live", action="store_true",
        help="Использовать реальный Claude API (требует ANTHROPIC_API_KEY)"
    )
    parser.add_argument(
        "--interactive", action="store_true",
        help="Интерактивный режим до Ctrl+C"
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Подробный вывод каждого шага"
    )
    parser.add_argument(
        "--interval", type=float, default=0.0,
        help="Минимальный интервал между LLM-вызовами в секундах (0 = каждый tick)"
    )
    args = parser.parse_args()

    # Режим
    use_live = args.live
    mode_name = "live (Claude API)" if use_live else "mock"

    print()
    print("=" * 60)
    print(f"[Шаг 8 — LLM-брокер FirstAGI | mode={mode_name}]")
    if not args.interactive:
        print(f"  Шагов: {args.steps}")
    print("=" * 60)

    # Создать приложение
    app = CoreApplication(config={"mock_teacher": False})
    app.startup()
    app.add_text_driver("text")

    # Создать LLM-клиент
    llm_client = build_live_client() if use_live else build_mock_client()

    # Создать воркер и зарегистрировать в планировщике
    worker = LLMTeacherWorker(
        system=app.system,
        llm_client=llm_client,
        min_interval=args.interval,
    )
    app.scheduler.add_worker(worker, name="llm")

    # Создать цикл
    loop = BrokerLoop(app, worker)

    if args.interactive:
        loop.run_interactive(verbose=True)
    else:
        verbose = args.verbose or True  # всегда показывать для демо
        reports = loop.run(n_steps=args.steps, verbose=verbose)
        _print_final(loop, reports)

    app.shutdown()


def _print_final(loop: BrokerLoop, reports: list) -> None:
    stats = loop.stats()
    print()
    print("=" * 60)
    print("[Итог сеанса]")
    print("=" * 60)
    print(f"  Шагов брокера:         {stats['total_steps']}")
    print(f"  Контента подано:       {stats['content_fed_count']}")
    print(f"  Наград выдано (ордера): {stats['orders_fired_total']}")
    print(f"  LLM-вызовов:           {stats['llm_calls']}")
    print(f"  Финальный ресурс:      {stats['final_resource']:.3f}")

    sys_stats = stats.get("system_stats", {})
    init_stats = sys_stats.get("initiative", {})
    print(f"  Hit rate (инициатива): {init_stats.get('hit_rate', 0):.1%}")
    print(f"  Размер базы Gen:       {sys_stats.get('base_size', 0)}")
    print(f"  Шагов движка:          {sys_stats.get('steps', 0)}")

    worker_stats = stats.get("worker_stats", {})
    history = worker_stats.get("decision_history", [])
    if history:
        print(f"  История решений LLM:   {' → '.join(history)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
