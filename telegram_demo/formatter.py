"""
Форматирование состояния FirstAGI в HTML-сообщения для Telegram.

Все методы чистые — без сети и без состояния.
Используется HTML parse_mode (надёжнее MarkdownV2).
"""
from __future__ import annotations

from typing import Optional


class MessageFormatter:
    """Форматирует данные FirstAGI в готовые HTML-строки для Telegram."""

    MAX_LEN: int = 4000

    # ------------------------------------------------------------------
    # Утилиты

    def truncate(self, text: str, max_len: Optional[int] = None) -> str:
        limit = max_len or self.MAX_LEN
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    @staticmethod
    def _esc(text: str) -> str:
        """Экранировать HTML-символы."""
        return (
            text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
        )

    # ------------------------------------------------------------------
    # Основные сообщения

    def format_welcome(self) -> str:
        return (
            "<b>🤖 FirstAGI — живой демо-стенд</b>\n\n"
            "Здесь AGI-ядро <b>непрерывно обучается</b> в диалоге с LLM-учителем.\n"
            "Каждый день — новые петли аттрактора.\n\n"
            "<b>Команды:</b>\n"
            "  /status — текущее состояние\n"
            "  /stats  — детальная статистика\n"
            "  /teach &lt;текст&gt; — научить FirstAGI вашему тексту\n"
            "  /reset  — сбросить контекст (только для администратора)\n\n"
            "Просто пишите в чат — FirstAGI будет учиться на ваших словах!"
        )

    def format_status(self, status: dict) -> str:
        """
        Краткое состояние.

        status — полный словарь из CoreApplication.status().
        """
        system = status.get("system", {})
        resource = status.get("resource", {})
        narrative = status.get("narrative", "")
        phase = system.get("phase_space", {})

        gen_count = system.get("total_generalizations", 0)
        token_count = system.get("total_tokens", 0)
        res_level = resource.get("level", 0.0)
        res_mode = resource.get("mode", "normal")
        n_attractors = phase.get("n_attractors", 0)

        lines = [
            "<b>📊 Состояние FirstAGI</b>",
            "",
            f"├ Обобщений: <b>{gen_count}</b>",
            f"├ Токенов обработано: <b>{token_count}</b>",
            f"├ Аттракторов: <b>{n_attractors}</b>",
            f"└ Ресурс: <b>{res_level:.2f}</b> ({self._esc(res_mode)})",
        ]
        if narrative:
            short = self.truncate(self._esc(narrative), 200)
            lines.extend(["", f"<i>{short}</i>"])

        return "\n".join(lines)

    def format_teacher_dialogue(
        self,
        teacher_text: str,
        agi_narrative: str,
        n_learned: int = 0,
    ) -> str:
        teacher_short = self.truncate(self._esc(teacher_text), 300)
        agi_short = (
            self.truncate(self._esc(agi_narrative), 300) if agi_narrative else "..."
        )
        lines = [
            "<b>📚 Диалог: Учитель → FirstAGI</b>",
            "",
            f"<b>Учитель:</b> {teacher_short}",
            "",
            f"<b>FirstAGI:</b> {agi_short}",
        ]
        if n_learned > 0:
            lines.append(f"\n<i>Усвоено токенов: {n_learned}</i>")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Событийные сообщения

    def format_new_generalization(self, gen_id: str, delta: int) -> str:
        return (
            f"🧩 <b>Новые обобщения</b>\n"
            f"Прирост: +{delta}\n"
            f"Последний: <code>{self._esc(gen_id[:12])}</code>"
        )

    def format_attractor_found(self, attractor_id: str, n_new: int) -> str:
        return (
            f"🌀 <b>Новый аттрактор!</b>\n"
            f"ID: <code>{self._esc(attractor_id[:12])}</code>\n"
            f"Всего новых: {n_new}"
        )

    def format_bifurcation(self, feature_id: str, n_new: int) -> str:
        return (
            f"⚡ <b>Бифуркация</b>\n"
            f"Признак: <code>{self._esc(feature_id[:12])}</code>\n"
            f"Новых: {n_new}"
        )

    # ------------------------------------------------------------------
    # Пользовательское взаимодействие

    def format_user_teach(
        self, username: str, text: str, n_learned: int
    ) -> str:
        short = self.truncate(self._esc(text), 200)
        status = (
            f"усвоено ≈{n_learned} токен(ов)" if n_learned > 0 else "поставлено в очередь"
        )
        return (
            f"👤 <b>@{self._esc(username)}</b> учит FirstAGI\n"
            f"<i>{short}</i>\n"
            f"→ {status}"
        )

    # ------------------------------------------------------------------
    # Статистика

    def format_stats_detail(self, status: dict) -> str:
        """Детальная статистика из CoreApplication.status()."""
        system = status.get("system", {})
        resource = status.get("resource", {})
        phase = system.get("phase_space", {})
        hedonic = system.get("hedonic", {})
        initiative = system.get("initiative", {})
        scheduler = status.get("scheduler", {})

        lines = ["<b>📈 Детальная статистика FirstAGI</b>", ""]

        # Ядро
        lines.append("<b>Ядро:</b>")
        lines.append(
            f"  обобщений: {system.get('total_generalizations', '—')}"
        )
        lines.append(f"  токенов: {system.get('total_tokens', '—')}")
        lines.append(
            f"  активный контекст: {system.get('active_context_size', '—')}"
        )

        # Ресурс
        if resource:
            lines.extend(["", "<b>Ресурс:</b>"])
            lines.append(
                f"  level={resource.get('level', 0):.3f}  "
                f"mode={resource.get('mode', '?')}  "
                f"trend={resource.get('trend', 0):+.3f}"
            )

        # Фазовое пространство
        if phase:
            lines.extend(["", "<b>Фазовое пространство:</b>"])
            lines.append(f"  аттракторов: {phase.get('n_attractors', 0)}")
            lines.append(f"  траекторий: {phase.get('n_trajectories', 0)}")
            lines.append(f"  бифуркаций: {phase.get('n_bifurcations', 0)}")

        # Гедоника + инициатива
        if hedonic or initiative:
            lines.extend(["", "<b>Мотивация:</b>"])
        if hedonic:
            lines.append(
                f"  завершений: {hedonic.get('total_completions', 0)}"
            )
        if initiative:
            hr = initiative.get("hit_rate", 0)
            lines.append(f"  предсказание: {hr:.1%}")

        # Планировщик
        if scheduler:
            lines.extend(["", "<b>Планировщик:</b>"])
            lines.append(
                f"  тиков: {scheduler.get('tick_count', 0)}  "
                f"workers: {scheduler.get('workers', [])}"
            )

        return "\n".join(lines)

    def format_daily_summary(self, status: dict, uptime_h: float) -> str:
        system = status.get("system", {})
        phase = system.get("phase_space", {})
        return (
            f"🌙 <b>Итог дня</b>\n\n"
            f"Время работы: {uptime_h:.1f}ч\n"
            f"Обобщений накоплено: {system.get('total_generalizations', 0)}\n"
            f"Токенов обработано: {system.get('total_tokens', 0)}\n"
            f"Аттракторов: {phase.get('n_attractors', 0)}\n\n"
            f"<i>Петли аттрактора продолжают накручиваться...</i>"
        )

    def format_error(self, error: str) -> str:
        short = self.truncate(self._esc(error), 500)
        return f"⚠️ <b>Ошибка</b>\n<code>{short}</code>"
