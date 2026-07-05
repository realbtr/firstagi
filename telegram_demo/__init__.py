"""
Шаг 9: Telegram Demo — живой демо-стенд FirstAGI в Telegram.

Канал/группа, в которой FirstAGI непрерывно обучается в диалоге
с LLM-учителем. Пользователи могут подавать тексты, наблюдать
обучение и задавать вопросы.

Компоненты:
  config.py     — DemoConfig (env-based)
  formatter.py  — MessageFormatter (HTML-сообщения для Telegram)
  poster.py     — ChannelPoster (отправка с троттлингом)
  brain_loop.py — BrainLoop (asyncio-цикл: тренировка + публикация)
  handlers.py   — CommandRouter (команды и сообщения пользователей)
  run.py        — Entry point: py -X utf8 -m telegram_demo.run

Переменные окружения:
  TELEGRAM_BOT_TOKEN   — токен бота (обязателен)
  TELEGRAM_CHANNEL_ID  — ID канала/группы, например @firstagi_demo
  ANTHROPIC_API_KEY    — ключ для live-режима (иначе mock LLM)
  USE_MOCK_LLM         — '1' mock, '0' live (default: '1')
  TRAIN_INTERVAL       — секунды между тиками обучения (default: 30)
  POST_INTERVAL        — секунды между статус-постами (default: 300)
  SESSION_NAME         — имя сессии для автосохранения (default: telegram_demo)
  LEARN_FROM_USERS     — '1' учиться из чата (default: '1')
  POST_ON_EVENTS       — '1' постить при событиях (default: '1')
"""
