"""
Шаг 9: Тесты Telegram Demo Interface.

Покрытие:
  DemoConfig       — загрузка из env, валидация
  MessageFormatter — форматирование всех типов сообщений
  ChannelPoster    — троттлинг, отправка, обработка ошибок
  BrainLoop        — очередь, детекция событий, снапшоты
  CommandRouter    — все команды, handle_message

Зависимости: pytest-asyncio  (pip install pytest-asyncio)
"""
from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock

# ── Вспомогательные фабрики ──────────────────────────────────────────

def _make_status(gen=0, tokens=0, level=0.5, mode="normal",
                 n_attr=0, n_traj=0, n_bif=0,
                 narrative="test narrative"):
    return {
        "system": {
            "total_generalizations": gen,
            "total_tokens": tokens,
            "active_context_size": 0,
            "phase_space": {
                "n_attractors":   n_attr,
                "n_trajectories": n_traj,
                "n_bifurcations": n_bif,
            },
            "hedonic":    {"total_completions": 0},
            "initiative": {"hit_rate": 0.0},
        },
        "resource": {"level": level, "mode": mode, "trend": 0.0},
        "drivers":  ["text"],
        "scheduler": {"running": True, "tick_count": 0, "workers": ["llm"]},
        "sessions":  {"dir": "sessions", "latest": None},
        "narrative": narrative,
    }


def _make_mock_app(status=None):
    app = MagicMock()
    app.status.return_value = status or _make_status()
    app.learn.return_value = {
        "outcomes": [], "confirmed": 0, "completed": 0,
        "refuted": 0, "explored": 0, "match_rate": 0.0,
        "narrative": "learning...", "stats": {},
    }
    app.system = MagicMock()
    app.system.reset_context = MagicMock()
    app.sessions = MagicMock()
    return app


def _make_mock_broker(content_fed=None):
    broker = MagicMock()
    broker.step.return_value = {
        "step":         1,
        "content_fed":  content_fed,
        "learn_result": None,
        "orders_fired": 0,
        "resource":     0.5,
        "llm_calls":    0,
    }
    return broker


def _make_mock_poster():
    poster = MagicMock()
    poster.post       = AsyncMock(return_value=True)
    poster.post_status = AsyncMock(return_value=True)
    poster.post_event  = AsyncMock(return_value=True)
    return poster


def _make_update(text="hello world", username="alice", user_id=42):
    upd = MagicMock()
    upd.message = MagicMock()
    upd.message.text = text
    upd.message.reply_text = AsyncMock()
    upd.effective_user = MagicMock()
    upd.effective_user.username = username
    upd.effective_user.id = user_id
    return upd


def _make_context(args=None):
    ctx = MagicMock()
    ctx.args = args or []
    return ctx


# ════════════════════════════════════════════════════════════════════════
# DemoConfig
# ════════════════════════════════════════════════════════════════════════

class TestDemoConfig:

    def test_direct_construction(self):
        from telegram_demo.config import DemoConfig
        cfg = DemoConfig(bot_token="abc", channel_id="@ch")
        assert cfg.bot_token == "abc"
        assert cfg.channel_id == "@ch"

    def test_defaults(self):
        from telegram_demo.config import DemoConfig
        cfg = DemoConfig(bot_token="x", channel_id="@y")
        assert cfg.use_mock_llm is True
        assert cfg.train_interval == 30.0
        assert cfg.post_interval == 300.0
        assert cfg.min_post_interval == 2.0
        assert cfg.learn_from_users is True
        assert cfg.post_on_events is True
        assert cfg.session_name == "telegram_demo"

    def test_from_env_ok(self, monkeypatch):
        from telegram_demo.config import DemoConfig
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok123")
        monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@chan")
        monkeypatch.setenv("USE_MOCK_LLM", "0")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-x")
        monkeypatch.setenv("TRAIN_INTERVAL", "15")
        monkeypatch.setenv("POST_INTERVAL", "120")
        cfg = DemoConfig.from_env()
        assert cfg.bot_token == "tok123"
        assert cfg.channel_id == "@chan"
        assert cfg.use_mock_llm is False
        assert cfg.anthropic_api_key == "sk-x"
        assert cfg.train_interval == 15.0
        assert cfg.post_interval == 120.0

    def test_from_env_missing_token(self, monkeypatch):
        from telegram_demo.config import DemoConfig
        monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
        with pytest.raises(ValueError, match="TELEGRAM_BOT_TOKEN"):
            DemoConfig.from_env()

    def test_from_env_missing_channel(self, monkeypatch):
        from telegram_demo.config import DemoConfig
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.delenv("TELEGRAM_CHANNEL_ID", raising=False)
        with pytest.raises(ValueError, match="TELEGRAM_CHANNEL_ID"):
            DemoConfig.from_env()

    def test_validate_ok(self):
        from telegram_demo.config import DemoConfig
        cfg = DemoConfig(bot_token="t", channel_id="@c")
        assert cfg.validate() == []

    def test_validate_empty_token(self):
        from telegram_demo.config import DemoConfig
        cfg = DemoConfig(bot_token="", channel_id="@c")
        assert any("bot_token" in e for e in cfg.validate())

    def test_validate_empty_channel(self):
        from telegram_demo.config import DemoConfig
        cfg = DemoConfig(bot_token="t", channel_id="")
        assert any("channel_id" in e for e in cfg.validate())

    def test_validate_negative_train_interval(self):
        from telegram_demo.config import DemoConfig
        cfg = DemoConfig(bot_token="t", channel_id="@c", train_interval=-1.0)
        assert any("train_interval" in e for e in cfg.validate())

    def test_validate_negative_post_interval(self):
        from telegram_demo.config import DemoConfig
        cfg = DemoConfig(bot_token="t", channel_id="@c", post_interval=0.0)
        assert any("post_interval" in e for e in cfg.validate())

    def test_validate_live_no_api_key(self):
        from telegram_demo.config import DemoConfig
        cfg = DemoConfig(bot_token="t", channel_id="@c",
                         use_mock_llm=False, anthropic_api_key="")
        assert any("anthropic_api_key" in e for e in cfg.validate())

    def test_validate_live_with_key_ok(self):
        from telegram_demo.config import DemoConfig
        cfg = DemoConfig(bot_token="t", channel_id="@c",
                         use_mock_llm=False, anthropic_api_key="sk-x")
        assert cfg.validate() == []

    def test_from_env_learn_from_users_false(self, monkeypatch):
        from telegram_demo.config import DemoConfig
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "tok")
        monkeypatch.setenv("TELEGRAM_CHANNEL_ID", "@c")
        monkeypatch.setenv("LEARN_FROM_USERS", "0")
        cfg = DemoConfig.from_env()
        assert cfg.learn_from_users is False


# ════════════════════════════════════════════════════════════════════════
# MessageFormatter
# ════════════════════════════════════════════════════════════════════════

class TestMessageFormatter:

    @pytest.fixture
    def fmt(self):
        from telegram_demo.formatter import MessageFormatter
        return MessageFormatter()

    def test_welcome_not_empty(self, fmt):
        text = fmt.format_welcome()
        assert len(text) > 50

    def test_welcome_contains_firstagi(self, fmt):
        assert "FirstAGI" in fmt.format_welcome()

    def test_welcome_has_commands(self, fmt):
        text = fmt.format_welcome()
        assert "/status" in text
        assert "/teach" in text

    def test_format_status_gen_count(self, fmt):
        st = _make_status(gen=42)
        assert "42" in fmt.format_status(st)

    def test_format_status_tokens(self, fmt):
        st = _make_status(tokens=1337)
        assert "1337" in fmt.format_status(st)

    def test_format_status_resource(self, fmt):
        st = _make_status(level=0.73, mode="explore")
        text = fmt.format_status(st)
        assert "0.73" in text
        assert "explore" in text

    def test_format_status_attractors(self, fmt):
        st = _make_status(n_attr=5)
        assert "5" in fmt.format_status(st)

    def test_format_status_includes_narrative(self, fmt):
        st = _make_status(narrative="thinking hard")
        assert "thinking hard" in fmt.format_status(st)

    def test_format_status_empty(self, fmt):
        text = fmt.format_status({})
        assert len(text) > 0

    def test_format_teacher_dialogue_content(self, fmt):
        text = fmt.format_teacher_dialogue("учи меня", "я учусь", 7)
        assert "учи меня" in text
        assert "я учусь" in text
        assert "7" in text

    def test_format_teacher_dialogue_zero_learned(self, fmt):
        text = fmt.format_teacher_dialogue("test", "reply", 0)
        assert "test" in text
        assert "reply" in text

    def test_format_teacher_dialogue_no_narrative(self, fmt):
        text = fmt.format_teacher_dialogue("msg", "", 0)
        assert "msg" in text

    def test_format_new_generalization(self, fmt):
        text = fmt.format_new_generalization("gen_abc123XYZ", 8)
        assert "8" in text
        assert "gen_abc" in text

    def test_format_attractor_found(self, fmt):
        text = fmt.format_attractor_found("attr_zz999", 2)
        assert "attr_zz" in text
        assert "2" in text

    def test_format_bifurcation(self, fmt):
        text = fmt.format_bifurcation("feat_aaa", 3)
        assert "3" in text

    def test_format_user_teach_with_learned(self, fmt):
        text = fmt.format_user_teach("bob", "Привет мир", 5)
        assert "bob" in text
        assert "Привет мир" in text
        assert "5" in text

    def test_format_user_teach_zero_learned(self, fmt):
        text = fmt.format_user_teach("alice", "test", 0)
        assert "alice" in text

    def test_format_stats_detail(self, fmt):
        st = _make_status(gen=10, tokens=50, level=0.5,
                          n_attr=2, n_traj=8, n_bif=1)
        st["system"]["hedonic"]    = {"total_completions": 20}
        st["system"]["initiative"] = {"hit_rate": 0.45}
        text = fmt.format_stats_detail(st)
        assert "10" in text
        assert "50" in text
        assert "45" in text  # hit_rate 0.45 → "45.0%" or "45%"

    def test_format_error(self, fmt):
        text = fmt.format_error("something failed")
        assert "something failed" in text
        assert "Ошибка" in text or "⚠" in text

    def test_truncate_short(self, fmt):
        assert fmt.truncate("hello", 100) == "hello"

    def test_truncate_long(self, fmt):
        result = fmt.truncate("x" * 500, 100)
        assert len(result) == 100
        assert result.endswith("...")

    def test_truncate_exact(self, fmt):
        s = "y" * 50
        assert fmt.truncate(s, 50) == s

    def test_format_daily_summary(self, fmt):
        st = _make_status(gen=55, tokens=200, n_attr=7)
        text = fmt.format_daily_summary(st, 8.5)
        assert "8.5" in text
        assert "55" in text
        assert "7" in text

    def test_esc_html(self, fmt):
        result = fmt._esc("<b>test</b> & more")
        assert "<" not in result
        assert ">" not in result
        assert "&amp;" in result


# ════════════════════════════════════════════════════════════════════════
# ChannelPoster
# ════════════════════════════════════════════════════════════════════════

class TestChannelPoster:

    @pytest.fixture
    def bot(self):
        b = MagicMock()
        b.send_message = AsyncMock(return_value=MagicMock())
        return b

    @pytest.fixture
    def poster(self, bot):
        from telegram_demo.poster import ChannelPoster
        return ChannelPoster(bot, "@testchan", min_interval=0.0)

    @pytest.mark.anyio
    async def test_post_success(self, poster, bot):
        result = await poster.post("hello")
        assert result is True
        bot.send_message.assert_called_once()

    @pytest.mark.anyio
    async def test_post_uses_channel_id(self, poster, bot):
        await poster.post("test")
        kw = bot.send_message.call_args.kwargs
        assert kw.get("chat_id") == "@testchan"

    @pytest.mark.anyio
    async def test_post_html_parse_mode(self, poster, bot):
        await poster.post("<b>test</b>")
        kw = bot.send_message.call_args.kwargs
        assert kw.get("parse_mode") == "HTML"

    @pytest.mark.anyio
    async def test_post_increments_counter(self, poster):
        await poster.post("a")
        await poster.post("b")
        assert poster.stats()["post_count"] == 2

    @pytest.mark.anyio
    async def test_post_error_returns_false(self, poster, bot):
        bot.send_message.side_effect = Exception("Network error")
        result = await poster.post("test")
        assert result is False
        assert poster.stats()["error_count"] == 1

    @pytest.mark.anyio
    async def test_post_status(self, poster):
        from telegram_demo.formatter import MessageFormatter
        fmt = MessageFormatter()
        result = await poster.post_status(_make_status(), fmt)
        assert result is True

    @pytest.mark.anyio
    async def test_post_event(self, poster):
        result = await poster.post_event("🌀 Аттрактор найден!")
        assert result is True

    def test_initial_stats(self, poster):
        s = poster.stats()
        assert s["post_count"] == 0
        assert s["error_count"] == 0

    @pytest.mark.anyio
    async def test_throttle_respects_interval(self):
        """min_interval=0.0 — всё должно проходить немедленно."""
        bot = MagicMock()
        bot.send_message = AsyncMock()
        from telegram_demo.poster import ChannelPoster
        p = ChannelPoster(bot, "@c", min_interval=0.0)
        for _ in range(3):
            await p.post("x")
        assert p.stats()["post_count"] == 3


# ════════════════════════════════════════════════════════════════════════
# BrainLoop
# ════════════════════════════════════════════════════════════════════════

def _make_brain(gen=0, tokens=0, n_attr=0, n_bif=0,
                content_fed=None, post_on_events=True):
    from telegram_demo.config import DemoConfig
    from telegram_demo.formatter import MessageFormatter
    from telegram_demo.brain_loop import BrainLoop

    cfg = DemoConfig(
        bot_token="t", channel_id="@c",
        train_interval=0.01, post_interval=1000.0,
        post_on_events=post_on_events, learn_from_users=True,
    )
    status = _make_status(gen=gen, tokens=tokens, n_attr=n_attr, n_bif=n_bif)
    app = _make_mock_app(status)
    broker = _make_mock_broker(content_fed=content_fed)
    poster = _make_mock_poster()
    return BrainLoop(app, broker, poster, MessageFormatter(), cfg)


class TestBrainLoop:

    def test_initial_not_running(self):
        brain = _make_brain()
        assert brain._running is False

    def test_initial_step_count_zero(self):
        assert _make_brain()._step_count == 0

    def test_feed_user_text_queues(self):
        brain = _make_brain()
        brain.feed_user_text("hello", "alice")
        assert brain._user_queue.qsize() == 1

    def test_feed_multiple_texts(self):
        brain = _make_brain()
        brain.feed_user_text("t1", "u1")
        brain.feed_user_text("t2", "u2")
        assert brain._user_queue.qsize() == 2

    def test_sync_train_tick_calls_broker(self):
        brain = _make_brain()
        result = brain._sync_train_tick()
        brain.broker.step.assert_called_once()

    def test_sync_train_tick_returns_dict(self):
        brain = _make_brain()
        result = brain._sync_train_tick()
        assert "n_learned" in result
        assert "events" in result
        assert "teacher_text" in result

    def test_sync_train_tick_with_content(self):
        brain = _make_brain(content_fed="кот сидит на окне")
        result = brain._sync_train_tick()
        assert result["n_learned"] == 1
        assert result["teacher_text"] == "кот сидит на окне"

    def test_sync_train_tick_no_content(self):
        brain = _make_brain(content_fed=None)
        result = brain._sync_train_tick()
        assert result["n_learned"] == 0
        assert result["teacher_text"] == ""

    def test_detect_events_no_change(self):
        brain = _make_brain()
        before = {"gen_count": 10, "attractor_count": 2, "bifurcation_count": 0}
        after  = {"gen_count": 10, "attractor_count": 2, "bifurcation_count": 0}
        assert brain._detect_events(before, after) == []

    def test_detect_events_new_attractor(self):
        brain = _make_brain()
        before = {"gen_count": 10, "attractor_count": 0, "bifurcation_count": 0}
        after  = {"gen_count": 10, "attractor_count": 1, "bifurcation_count": 0}
        events = brain._detect_events(before, after)
        assert len(events) == 1
        assert "аттрактор" in events[0].lower()

    def test_detect_events_bifurcation(self):
        brain = _make_brain()
        before = {"gen_count": 5, "attractor_count": 0, "bifurcation_count": 0}
        after  = {"gen_count": 5, "attractor_count": 0, "bifurcation_count": 2}
        events = brain._detect_events(before, after)
        assert len(events) == 1
        assert "Бифуркация" in events[0]

    def test_detect_events_many_gens(self):
        brain = _make_brain()
        before = {"gen_count": 0,  "attractor_count": 0, "bifurcation_count": 0}
        after  = {"gen_count": 10, "attractor_count": 0, "bifurcation_count": 0}
        events = brain._detect_events(before, after)
        assert len(events) == 1
        assert "обобщен" in events[0].lower()

    def test_detect_events_small_gen_delta_no_event(self):
        brain = _make_brain()
        before = {"gen_count": 10, "attractor_count": 0, "bifurcation_count": 0}
        after  = {"gen_count": 13, "attractor_count": 0, "bifurcation_count": 0}
        events = brain._detect_events(before, after)
        assert events == []

    def test_detect_events_empty_dicts(self):
        brain = _make_brain()
        assert brain._detect_events({}, {}) == []

    def test_detect_events_multiple(self):
        brain = _make_brain()
        before = {"gen_count": 0, "attractor_count": 0, "bifurcation_count": 0}
        after  = {"gen_count": 10, "attractor_count": 1, "bifurcation_count": 1}
        events = brain._detect_events(before, after)
        assert len(events) == 3

    def test_snapshot_stats_structure(self):
        brain = _make_brain(gen=5, n_attr=2, n_bif=1)
        snap = brain._snapshot_stats()
        assert snap["gen_count"] == 5
        assert snap["attractor_count"] == 2
        assert snap["bifurcation_count"] == 1

    def test_get_narrative(self):
        brain = _make_brain()
        brain.app.status.return_value = _make_status(narrative="hello narrative")
        assert brain._get_narrative() == "hello narrative"

    def test_get_narrative_exception(self):
        brain = _make_brain()
        brain.app.status.side_effect = RuntimeError("fail")
        assert brain._get_narrative() == ""

    def test_uptime_before_start(self):
        assert _make_brain().uptime_hours() == 0.0

    def test_stats_structure(self):
        brain = _make_brain()
        s = brain.stats()
        assert "running" in s
        assert "step_count" in s
        assert "event_count" in s
        assert "uptime_hours" in s
        assert "user_queue_size" in s

    @pytest.mark.anyio
    async def test_run_sets_running(self):
        brain = _make_brain()
        task = asyncio.create_task(brain.run())
        await asyncio.sleep(0.05)
        assert brain._running is True
        await brain.stop()
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @pytest.mark.anyio
    async def test_train_loop_increments_step_count(self):
        brain = _make_brain()
        brain._running = True
        task = asyncio.create_task(brain._train_loop())
        await asyncio.sleep(0.08)
        brain._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert brain._step_count >= 1

    @pytest.mark.anyio
    async def test_user_loop_processes_text(self):
        brain = _make_brain()
        brain._running = True
        brain.feed_user_text("Кот на окне", "alice")
        task = asyncio.create_task(brain._user_loop())
        await asyncio.sleep(0.15)
        brain._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        brain.app.learn.assert_called()

    @pytest.mark.anyio
    async def test_event_posted_on_attractor(self):
        brain = _make_brain(post_on_events=True)
        brain._running = True

        # Mock: first call returns gen=0,attr=0; second gen=0,attr=1
        call_count = [0]
        def status_side_effect():
            call_count[0] += 1
            if call_count[0] <= 1:
                return _make_status(n_attr=0)
            return _make_status(n_attr=1)

        brain.app.status.side_effect = status_side_effect
        task = asyncio.create_task(brain._train_loop())
        await asyncio.sleep(0.08)
        brain._running = False
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        brain.poster.post_event.assert_called()


# ════════════════════════════════════════════════════════════════════════
# CommandRouter
# ════════════════════════════════════════════════════════════════════════

def _make_router(learn_from_users=True, min_text_length=3):
    from telegram_demo.config import DemoConfig
    from telegram_demo.formatter import MessageFormatter
    from telegram_demo.handlers import CommandRouter

    cfg = DemoConfig(
        bot_token="t", channel_id="@c",
        learn_from_users=learn_from_users,
        min_text_length=min_text_length,
    )
    brain = _make_brain()
    brain._running = True
    fmt = MessageFormatter()
    poster = _make_mock_poster()
    return CommandRouter(brain, fmt, poster, cfg), brain


class TestCommandRouter:

    @pytest.mark.anyio
    async def test_cmd_start_replies(self):
        router, _ = _make_router()
        upd = _make_update()
        await router.cmd_start(upd, _make_context())
        upd.message.reply_text.assert_called_once()
        text = upd.message.reply_text.call_args.args[0]
        assert "FirstAGI" in text

    @pytest.mark.anyio
    async def test_cmd_status_replies(self):
        router, _ = _make_router()
        upd = _make_update()
        await router.cmd_status(upd, _make_context())
        upd.message.reply_text.assert_called_once()

    @pytest.mark.anyio
    async def test_cmd_status_on_error(self):
        router, brain = _make_router()
        brain.app.status.side_effect = RuntimeError("boom")
        upd = _make_update()
        await router.cmd_status(upd, _make_context())
        text = upd.message.reply_text.call_args.args[0]
        assert "boom" in text or "Ошибка" in text

    @pytest.mark.anyio
    async def test_cmd_stats_replies(self):
        router, _ = _make_router()
        upd = _make_update()
        await router.cmd_stats(upd, _make_context())
        upd.message.reply_text.assert_called_once()

    @pytest.mark.anyio
    async def test_cmd_teach_no_args(self):
        router, _ = _make_router()
        upd = _make_update()
        await router.cmd_teach(upd, _make_context(args=[]))
        text = upd.message.reply_text.call_args.args[0]
        assert "/teach" in text

    @pytest.mark.anyio
    async def test_cmd_teach_queues_text(self):
        router, brain = _make_router()
        upd = _make_update(username="bob")
        await router.cmd_teach(upd, _make_context(args=["hello", "world"]))
        assert brain._user_queue.qsize() == 1
        text, uname = await brain._user_queue.get()
        assert text == "hello world"
        assert uname == "bob"

    @pytest.mark.anyio
    async def test_cmd_teach_replies_ok(self):
        router, _ = _make_router()
        upd = _make_update()
        await router.cmd_teach(upd, _make_context(args=["some text"]))
        reply = upd.message.reply_text.call_args.args[0]
        assert "✅" in reply or "очередь" in reply

    @pytest.mark.anyio
    async def test_cmd_reset_admin_ok(self):
        router, brain = _make_router()
        router.set_admin_ids([42])
        upd = _make_update(user_id=42)
        await router.cmd_reset(upd, _make_context())
        brain.app.system.reset_context.assert_called_once()

    @pytest.mark.anyio
    async def test_cmd_reset_non_admin_blocked(self):
        router, brain = _make_router()
        router.set_admin_ids([999])
        upd = _make_update(user_id=42)
        await router.cmd_reset(upd, _make_context())
        brain.app.system.reset_context.assert_not_called()
        text = upd.message.reply_text.call_args.args[0]
        assert "⛔" in text or "администр" in text.lower()

    @pytest.mark.anyio
    async def test_cmd_reset_no_admin_list_allows_all(self):
        """Пустой список admin_ids — сброс разрешён всем."""
        router, brain = _make_router()
        router.set_admin_ids([])
        upd = _make_update(user_id=42)
        await router.cmd_reset(upd, _make_context())
        brain.app.system.reset_context.assert_called_once()

    @pytest.mark.anyio
    async def test_handle_message_feeds_brain(self):
        router, brain = _make_router(learn_from_users=True)
        upd = _make_update(text="This is a nice long message")
        await router.handle_message(upd, _make_context())
        assert brain._user_queue.qsize() == 1

    @pytest.mark.anyio
    async def test_handle_message_disabled(self):
        router, brain = _make_router(learn_from_users=False)
        upd = _make_update(text="This is a nice long message")
        await router.handle_message(upd, _make_context())
        assert brain._user_queue.qsize() == 0

    @pytest.mark.anyio
    async def test_handle_message_too_short(self):
        router, brain = _make_router(min_text_length=5)
        upd = _make_update(text="hi")
        await router.handle_message(upd, _make_context())
        assert brain._user_queue.qsize() == 0

    @pytest.mark.anyio
    async def test_handle_message_no_text(self):
        router, brain = _make_router()
        upd = _make_update(text=None)
        upd.message.text = None
        await router.handle_message(upd, _make_context())
        assert brain._user_queue.qsize() == 0

    def test_set_admin_ids(self):
        router, _ = _make_router()
        router.set_admin_ids([1, 2, 3])
        assert 1 in router._admin_ids
        assert 4 not in router._admin_ids

    @pytest.mark.anyio
    async def test_handle_message_exactly_min_length(self):
        router, brain = _make_router(min_text_length=3)
        upd = _make_update(text="abc")  # exactly 3
        await router.handle_message(upd, _make_context())
        assert brain._user_queue.qsize() == 1

    @pytest.mark.anyio
    async def test_cmd_teach_uses_username(self):
        router, brain = _make_router()
        upd = _make_update(username="charlie")
        await router.cmd_teach(upd, _make_context(args=["test"]))
        _, uname = await brain._user_queue.get()
        assert uname == "charlie"
