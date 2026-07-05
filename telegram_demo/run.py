"""
Entry point: py -X utf8 -m telegram_demo.run

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Обязательные переменные окружения:
  TELEGRAM_BOT_TOKEN   — токен Telegram-бота (от @BotFather)
  TELEGRAM_CHANNEL_ID  — ID канала/группы (напр.: -100123456789)

LLM-провайдеры (задай хотя бы один, или включи mock):
  ANTHROPIC_API_KEY    — Claude  (pip install anthropic)
  OPENAI_API_KEY       — GPT-4o  (pip install openai)
  GROK_API_KEY         — Grok    (pip install openai)
  DEEPSEEK_API_KEY     — DeepSeek(pip install openai)
  QWEN_API_KEY         — Qwen    (pip install openai)
  GEMINI_API_KEY       — Gemini  (pip install openai)

  USE_MOCK_LLM=1       — использовать mock вместо реальных API (default: 1)

Переопределение модели (опционально):
  ANTHROPIC_MODEL, OPENAI_MODEL, GROK_MODEL,
  DEEPSEEK_MODEL, QWEN_MODEL, GEMINI_MODEL

Поведение:
  TRAIN_INTERVAL   — секунды между тиками обучения (default: 30)
  POST_INTERVAL    — секунды между статус-постами (default: 300)
  SESSION_NAME     — имя сессии для автосохранения (default: telegram_demo)
  LEARN_FROM_USERS — учиться из сообщений чата, 1/0 (default: 1)
  POST_ON_EVENTS   — мгновенно постить события, 1/0 (default: 1)

Зависимости:
  pip install python-telegram-bot>=21.0
  pip install openai          # для OpenAI/Grok/DeepSeek/Qwen/Gemini
  pip install anthropic       # для Claude
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
from __future__ import annotations

import asyncio
import logging
import sys
import os

# Корень проекта в sys.path
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)


async def main() -> None:
    from telegram_demo.config import DemoConfig
    from telegram_demo.formatter import MessageFormatter
    from telegram_demo.poster import ChannelPoster
    from telegram_demo.brain_loop import BrainLoop
    from telegram_demo.handlers import CommandRouter

    # ── Конфиг ──────────────────────────────────────────────────────────
    try:
        config = DemoConfig.from_env()
    except ValueError as exc:
        logger.error("Config error: %s", exc)
        sys.exit(1)

    errors = config.validate()
    if errors:
        for e in errors:
            logger.error("Validation: %s", e)
        sys.exit(1)

    # ── FirstAGI Core ────────────────────────────────────────────────────
    from core.app import CoreApplication

    # mock_teacher=False — учителей подключаем вручную ниже
    app = CoreApplication(config={"mock_teacher": False})
    app.startup()

    # Загрузить предыдущую сессию
    if app.sessions.exists(config.session_name):
        logger.info("Loading session: %s", config.session_name)
        app.load_session(config.session_name)
        app.scheduler.start(interval=2.0)

    # ── LLM-учителя ──────────────────────────────────────────────────────
    from core.llm_broker import LLMTeacherWorker, MockLLMClient
    from core.llm_providers import clients_from_env, active_provider_names

    llm_clients = {}

    if not config.use_mock_llm:
        llm_clients = clients_from_env()
        if not llm_clients:
            logger.error(
                "USE_MOCK_LLM=0 but no API keys found. "
                "Set at least one: ANTHROPIC_API_KEY, OPENAI_API_KEY, "
                "GROK_API_KEY, DEEPSEEK_API_KEY, QWEN_API_KEY, GEMINI_API_KEY"
            )
            sys.exit(1)

    # Fallback: mock-учитель
    if not llm_clients:
        logger.info("No LLM API keys → using mock teacher")
        llm_clients = {
            "mock": MockLLMClient([
                '{"action":"TEACH","text":"Аттракторы — устойчивые состояния динамической системы.","amount":1,"reason":"core concept"}',
                '{"action":"WAIT","text":"","amount":0,"reason":"observing"}',
                '{"action":"TEACH","text":"Признаки образуют цепочки обобщений через подтверждение гипотезы.","amount":1,"reason":"pattern"}',
                '{"action":"TEACH","text":"Контекст — множество активных, не опровергнутых обобщений.","amount":1,"reason":"context"}',
                '{"action":"REWARD","text":"","amount":3,"reason":"good generalization found"}',
                '{"action":"TEACH","text":"Бифуркация — точка расхождения контекста на несколько путей.","amount":1,"reason":"bifurcation"}',
                '{"action":"WAIT","text":"","amount":0,"reason":"consolidating"}',
            ])
        }

    logger.info("Active LLM teachers (%d): %s", len(llm_clients), list(llm_clients.keys()))

    # Регистрируем всех учителей в планировщике
    # Интервал вызовов = 60s × количество учителей → равномерная нагрузка
    min_interval = max(60.0, 30.0 * len(llm_clients))
    workers = []
    for name, client in llm_clients.items():
        worker = LLMTeacherWorker(app.system, client, min_interval=min_interval)
        app.scheduler.add_worker(worker, name=name)
        workers.append((name, worker))
        logger.info("  → Teacher '%s' registered (min_interval=%.0fs)", name, min_interval)

    from training.llm_loop import BrokerLoop
    # BrokerLoop управляет тиками; основной воркер — первый в списке (для статистики)
    broker = BrokerLoop(app, workers[0][1])

    # ── Telegram ─────────────────────────────────────────────────────────
    from telegram.ext import (
        Application, CommandHandler, MessageHandler, filters,
    )

    tg_app = Application.builder().token(config.bot_token).build()

    formatter = MessageFormatter()
    poster = ChannelPoster(tg_app.bot, config.channel_id, config.min_post_interval)
    brain = BrainLoop(app, broker, poster, formatter, config)
    router = CommandRouter(brain, formatter, poster, config)

    tg_app.add_handler(CommandHandler("start",  router.cmd_start))
    tg_app.add_handler(CommandHandler("help",   router.cmd_start))
    tg_app.add_handler(CommandHandler("status", router.cmd_status))
    tg_app.add_handler(CommandHandler("stats",  router.cmd_stats))
    tg_app.add_handler(CommandHandler("teach",  router.cmd_teach))
    tg_app.add_handler(CommandHandler("reset",  router.cmd_reset))
    tg_app.add_handler(
        MessageHandler(filters.TEXT & ~filters.COMMAND, router.handle_message)
    )

    # ── Запуск ───────────────────────────────────────────────────────────
    teacher_list = ", ".join(llm_clients.keys())
    logger.info(
        "Starting FirstAGI Telegram Demo | channel=%s | teachers=[%s]",
        config.channel_id, teacher_list
    )

    async with tg_app:
        await tg_app.start()

        # Приветственный пост с перечислением активных учителей
        welcome = formatter.format_welcome()
        teachers_line = f"\n\n<b>Активные учителя:</b> {teacher_list}"
        await poster.post(welcome + teachers_line)

        brain_task = asyncio.create_task(brain.run())
        await tg_app.updater.start_polling(drop_pending_updates=True)

        logger.info("Bot is running. Ctrl+C to stop.")
        try:
            await asyncio.Event().wait()
        except (KeyboardInterrupt, asyncio.CancelledError):
            pass
        finally:
            logger.info("Shutting down…")
            await brain.stop()
            brain_task.cancel()
            try:
                await brain_task
            except asyncio.CancelledError:
                pass

            # Сохранить сессию (накопленные петли аттрактора)
            try:
                path = app.save_session(config.session_name)
                logger.info("Session saved: %s", path)
            except Exception as exc:
                logger.warning("Could not save session: %s", exc)

            await tg_app.updater.stop()
            await tg_app.stop()

    app.shutdown()
    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
