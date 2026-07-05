"""
Шаг 6: NarrativeVoice — нарративный язык системы.

Генерирует текстовые описания внутреннего состояния ядра
без использования внешних LLM — на основе шаблонов и структурных данных.

Назначение:
  • Читаемый вывод состояния для оператора/пользователя
  • Входные данные для реальных LLM-учителей (через TeachingLog)
  • Самоотчёт ядра о текущей ситуации

Использование:
    voice = NarrativeVoice(system)
    print(voice.state_report())
    print(voice.event_report(step_result))
"""

from __future__ import annotations
from typing import Optional

from .learning import LearningSystem
from .algorithm import StepResult, StepOutcome


_OUTCOME_PHRASES = {
    StepOutcome.CONFIRMED:     "подтверждён признак",
    StepOutcome.REFUTED:       "опровержение — новое обобщение",
    StepOutcome.COMPLETED:     "цепочка завершена",
    StepOutcome.EXPLORING:     "исследование нового",
    StepOutcome.CYCLE_AVOIDED: "цикл избегнут",
}

_MODE_PHRASES = {
    "rest":      "Ресурс истощён. Ядро в режиме покоя.",
    "conserve":  "Ресурс низкий. Ядро экономит внимание.",
    "normal":    "Ресурс в норме. Обычный режим работы.",
    "explore":   "Ресурс высокий. Ядро активно исследует.",
    "abundant":  "Ресурс избыточный. Максимальная открытость.",
}


class NarrativeVoice:
    """
    Нарративный голос ядра.

    Переводит числовое состояние LearningSystem в человекочитаемый текст.
    Используется как для вывода оператору, так и для подачи
    контекста LLM-учителям.
    """

    def __init__(self, system: LearningSystem) -> None:
        self._s = system

    # ------------------------------------------------------------------
    # Отдельные отчёты

    def resource_report(self) -> str:
        """Одна строка о текущем ресурсе."""
        rs = self._s.resource.state
        phrase = _MODE_PHRASES.get(rs.mode, rs.mode)
        return (
            f"[Ресурс] уровень={rs.level:.2f}  тренд={rs.trend:+.3f}  "
            f"режим={rs.mode}  // {phrase}"
        )

    def event_report(self, result: StepResult) -> str:
        """Одна строка о последнем шаге."""
        phrase = _OUTCOME_PHRASES.get(result.outcome, result.outcome.name)
        parts = [f"[Шаг] {phrase}"]
        if result.matched_feature_id:
            parts.append(f"признак={result.matched_feature_id[:8]}")
        if result.new_gen_id:
            parts.append(f"создан Gen {result.new_gen_id[:8]}")
        if result.completed_gen_ids:
            parts.append(f"завершено Gen: {len(result.completed_gen_ids)}")
        if result.removed_gen_ids:
            parts.append(f"удалено Gen: {len(result.removed_gen_ids)}")
        return "  ".join(parts)

    def attractor_report(self) -> str:
        """Краткая карта аттракторов из фазового пространства."""
        enc = self._s.encoder
        attractors = enc.find_attractors(min_strength=0.0)
        if not attractors:
            return "[Аттракторы] база пуста — аттракторов нет"

        lines = [f"[Аттракторы] {len(attractors)} найдено:"]
        for i, attr in enumerate(attractors[:5], 1):
            core_gens = [
                self._s.base.get(gid)
                for gid in list(attr.core_gen_ids)[:2]
            ]
            labels = [
                (g.label or g.gen_id[:8]) for g in core_gens if g
            ]
            lines.append(
                f"  #{i}  сила={attr.strength:.0f}  "
                f"ядро={len(attr.core_gen_ids)}  "
                f"бассейн={attr.basin_size}  "
                f"ключ=[{', '.join(labels)}]"
            )
        if len(attractors) > 5:
            lines.append(f"  ... и ещё {len(attractors) - 5}")
        return "\n".join(lines)

    def state_report(self) -> str:
        """Полный снапшот состояния системы."""
        stats = self._s.stats()
        rs = self._s.resource.state
        active = self._s.engine.context.active_gen_ids()
        top_gens = self._s.base.rank()[:5]

        lines = [
            "╔══ Состояние ядра ══",
            f"║  Обобщений в базе : {stats['base_size']}",
            f"║  Уникальных признаков : {stats['features']}",
            f"║  Шагов обработано : {stats['steps']}",
            f"║  Создано Gen жадно: {stats['greedy_created']}",
            f"║  Бифуркаций : {stats['bifurcations']}",
            f"║  Активных в контексте: {len(active)}",
            "║",
            f"║  {self.resource_report()}",
            "║",
        ]

        if top_gens:
            lines.append("║  Топ-обобщения (по значимости):")
            for g in top_gens:
                lines.append(
                    f"║    {(g.label or g.gen_id[:8]):20s}  "
                    f"sig={g.significance:.2f}  "
                    f"len={g.generalization_level}  "
                    f"✓{g.success_count} ✗{g.stop_count}"
                )

        teacher_info = stats.get("teacher", {})
        if teacher_info.get("active_orders", 0) > 0:
            lines.append("║")
            lines.append(
                f"║  Учитель: {teacher_info['active_orders']} активных ордеров  "
                f"выдано наград={teacher_info['total_reward']:.1f}"
            )

        lines.append("╚" + "═" * 30)
        return "\n".join(lines)

    def summary(self, max_lines: int = 10) -> str:
        """
        Компактное описание — для передачи LLM-учителю или вывода в CLI.
        """
        stats = self._s.stats()
        rs = self._s.resource.state
        active = self._s.engine.context.active_gen_ids()
        enc_summary = stats.get("phase_space", {})

        lines = [
            f"База: {stats['base_size']} Gen  "
            f"признаков: {stats['features']}  "
            f"шагов: {stats['steps']}",
            f"Ресурс: {rs.level:.2f} ({rs.mode})  "
            f"аттракторов: {enc_summary.get('n_attractors', 0)}  "
            f"контекст: {len(active)} Gen",
        ]

        top = self._s.base.rank()[:3]
        if top:
            labels = [g.label or g.gen_id[:8] for g in top]
            lines.append(f"Топ Gen: {', '.join(labels)}")

        return "\n".join(lines[:max_lines])

    def __repr__(self) -> str:
        return f"NarrativeVoice(system_steps={self._s.engine.step_count})"
