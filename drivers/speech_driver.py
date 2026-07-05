"""
SpeechDriver — системный речевой драйвер.

Переводит путь внимания ядра в человекочитаемый нарратив.

Два канала:
  A (молчаливый): внутренний поток внимания — Gen, outcomes, context
  B (речевой):    интерпретация канала A — вопросы, наблюдения, открытия

Канал B НЕ влияет на канал A. Это чистая интерпретация без обратной связи.

Применение:
  1. Учитель читает нарратив канала B → понимает что система замечала
  2. Можно сравнивать с будущей «речью» самой модели (двухканальное обучение)
  3. Отладка: видеть путь внимания без чисел

Запуск демо:
    py -X utf8 drivers/speech_driver.py
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.algorithm import StepResult
    from core.generalization import Generalization, GeneralizationBase


# ──────────────────────────────────────────────────────────────────────────────
# Одно наблюдение
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class Observation:
    """Одно наблюдение канала B — результат интерпретации одного шага."""
    token_label:  str
    outcome_tag:  str            # CONFIRMED / REFUTED / COMPLETED / EXPLORING
    text:         str            # человекочитаемое наблюдение
    confidence:   float = 0.0    # значимость ведущего Gen (0 если нет)
    is_surprise:  bool  = False  # REFUTED с созданием нового Gen
    new_gen_hint: Optional[str] = None  # описание нового Gen при surprise
    # Phase 2: dual-channel (B_model voice)
    voice_prediction: Optional[str]   = None   # предсказанное слово (из ModelVoice)
    voice_divergence: Optional[float] = None   # дивергенция [0, 1]


@dataclass
class ContextQuery:
    """
    Запрос на восстановление контекста за горизонтом восприятия.

    Генерируется SpeechDriver когда система встречает незнакомый токен
    (EXPLORING) или серию опровержений (REFUTED) и нуждается в
    дополнительном контексте из источника, который уже не в буфере драйвера.

    Аналог: «не вижу что за спиной — нужно повернуться».
    """
    trigger_token:   str          # токен, вызвавший запрос
    trigger_outcome: str          # "EXPLORING" | "REFUTED"
    missing_hint:    str          # что именно неизвестно (gen_hint или «?»)
    query_text:      str          # сформулированный запрос на естественном языке
    confidence_gap:  float = 0.0  # уровень неопределённости [0, 1]


# ──────────────────────────────────────────────────────────────────────────────
# SpeechDriver
# ──────────────────────────────────────────────────────────────────────────────

class SpeechDriver:
    """
    Системный речевой драйвер.

    Принимает результат каждого шага (StepResult) вместе с контекстом
    и базой обобщений, и порождает наблюдение на человеческом языке.

    Параметры
    ----------
    verbosity : int
        0 — только сюрпризы и завершения (компактно)
        1 — все шаги (default)
        2 — все шаги + технические детали Gen
    lang : str
        "ru" — русский (default), "en" — english
    """

    def __init__(self, verbosity: int = 1, lang: str = "ru") -> None:
        self.verbosity = verbosity
        self.lang = lang
        self._step_count: int = 0
        self._confirmed_run: int = 0   # подряд идущие CONFIRMED
        self._text_log: List[Observation] = []

    # ------------------------------------------------------------------
    # Основной метод: интерпретировать один шаг
    # ------------------------------------------------------------------

    def observe(
        self,
        result: "StepResult",
        base: "GeneralizationBase",
        active_gen_ids: List[str],
        voice_prediction: Optional[str] = None,
        voice_divergence: Optional[float] = None,
    ) -> Optional[Observation]:
        """
        Интерпретировать результат одного шага process_token().

        Возвращает Observation или None (если verbosity=0 и шаг неинтересен).
        """
        from core.algorithm import StepOutcome

        self._step_count += 1
        tok_label = getattr(result.token, "label", "?") or "?"

        # Найти ведущий Gen (первый активный с наивысшей значимостью)
        lead_gen: Optional["Generalization"] = None
        lead_sig: float = 0.0
        for gid in active_gen_ids:
            g = base.get(gid)
            if g and g.significance > lead_sig:
                lead_gen = g
                lead_sig = g.significance

        outcome = result.outcome

        if outcome == StepOutcome.CONFIRMED:
            self._confirmed_run += 1
            if self.verbosity == 0:
                return None

            if self._confirmed_run == 1:
                msg = self._fmt(
                    "Подтверждает: «{tok}»",
                    "Confirms: '{tok}'",
                    tok=tok_label,
                ) + (f" ← {self._gen_hint(lead_gen)}" if lead_gen else "")
            else:
                msg = self._fmt(
                    "✓ «{tok}»  (подряд: {n})",
                    "✓ '{tok}'  (streak: {n})",
                    tok=tok_label, n=self._confirmed_run,
                ) + (f"  sig={lead_sig:.2f}" if self.verbosity >= 2 else "")

            return self._make(tok_label, "CONFIRMED", msg, lead_sig,
                              voice_prediction=voice_prediction,
                              voice_divergence=voice_divergence)

        elif outcome == StepOutcome.COMPLETED:
            self._confirmed_run = 0
            completed_labels = []
            for gid in result.completed_gen_ids:
                g = base.get(gid)
                if g:
                    completed_labels.append(g.label or gid[:8])

            names = "«" + "», «".join(completed_labels) + "»" if completed_labels else ""
            msg = self._fmt(
                "★ Паттерн завершён: {names}. Что дальше?",
                "★ Pattern complete: {names}. What next?",
                names=names,
            )
            if self.verbosity >= 2 and completed_labels:
                msg += f"  [{', '.join(str(round(base.get(gid).significance, 2)) for gid in result.completed_gen_ids if base.get(gid))}]"
            return self._make(tok_label, "COMPLETED", msg, lead_sig,
                              voice_prediction=voice_prediction,
                              voice_divergence=voice_divergence)

        elif outcome == StepOutcome.REFUTED:
            self._confirmed_run = 0
            new_hint: Optional[str] = None
            if result.new_gen_id:
                new_gen = base.get(result.new_gen_id)
                if new_gen:
                    new_hint = new_gen.label or result.new_gen_id[:8]

            expected_hint = self._gen_hint(lead_gen) if lead_gen else "?"
            msg = self._fmt(
                "✗ Удивилась: «{tok}». Ожидала: {exp}.",
                "✗ Surprised by '{tok}'. Expected: {exp}.",
                tok=tok_label, exp=expected_hint,
            )
            if new_hint:
                msg += self._fmt(
                    f" → Новая связь: «{new_hint}»",
                    f" → New link: '{new_hint}'",
                )

            return self._make(tok_label, "REFUTED", msg, lead_sig,
                              is_surprise=True, new_gen_hint=new_hint,
                              voice_prediction=voice_prediction,
                              voice_divergence=voice_divergence)

        elif outcome == StepOutcome.EXPLORING:
            self._confirmed_run = 0
            if self.verbosity == 0:
                return None
            msg = self._fmt(
                "~ Исследует: «{tok}» — гипотеза не определена",
                "~ Exploring: '{tok}' — no hypothesis yet",
                tok=tok_label,
            )
            return self._make(tok_label, "EXPLORING", msg, 0.0,
                              voice_prediction=voice_prediction,
                              voice_divergence=voice_divergence)

        return None

    # ------------------------------------------------------------------
    # Итоговый нарратив после обработки всего текста
    # ------------------------------------------------------------------

    def summarize(
        self,
        text: str,
        observations: List[Observation],
        total_tokens: int,
    ) -> str:
        """
        Краткий нарратив о пути внимания по тексту.

        Формат:
          Текст: «...»
          ✓ 5/7  сюрприз: медведь вместо зайца  новое: маша→медведь
          Итог: 0.71  Паттерны: встреча, лес
        """
        n_confirmed  = sum(1 for o in observations if o.outcome_tag == "CONFIRMED")
        n_completed  = sum(1 for o in observations if o.outcome_tag == "COMPLETED")
        n_refuted    = sum(1 for o in observations if o.outcome_tag == "REFUTED")
        n_exploring  = sum(1 for o in observations if o.outcome_tag == "EXPLORING")
        mr = (n_confirmed + n_completed) / total_tokens if total_tokens else 0.0

        surprises = [o for o in observations if o.is_surprise]
        new_links = [o.new_gen_hint for o in surprises if o.new_gen_hint]

        lines = []
        short_text = (text[:60] + "…") if len(text) > 60 else text
        lines.append(self._fmt(
            f"Текст: «{short_text}»",
            f"Text: '{short_text}'",
        ))

        stat_line = self._fmt(
            f"✓ {n_confirmed+n_completed}/{total_tokens}",
            f"✓ {n_confirmed+n_completed}/{total_tokens}",
        )
        if surprises:
            surprise_toks = ", ".join(f"«{o.token_label}»" for o in surprises[:3])
            stat_line += self._fmt(
                f"  сюрприз: {surprise_toks}",
                f"  surprise: {surprise_toks}",
            )
        if new_links:
            stat_line += self._fmt(
                f"  новое: {', '.join(new_links[:3])}",
                f"  new: {', '.join(new_links[:3])}",
            )
        lines.append(stat_line)

        lines.append(self._fmt(
            f"Итог: mr={mr:.2f}  подтв={n_confirmed}  завер={n_completed}  "
            f"сюрп={n_refuted}  иссл={n_exploring}",
            f"Result: mr={mr:.2f}  conf={n_confirmed}  compl={n_completed}  "
            f"surp={n_refuted}  expl={n_exploring}",
        ))

        # Dual-channel stats (если есть данные B_модель)
        voice_obs = [o for o in observations if o.voice_divergence is not None]
        if voice_obs:
            n_match = sum(1 for o in voice_obs if (o.voice_divergence or 1.0) == 0.0)
            avg_div = sum(o.voice_divergence for o in voice_obs) / len(voice_obs)
            lines.append(self._fmt(
                f"B_модель: угадала={n_match}/{len(voice_obs)}  "
                f"avg_div={avg_div:.2f}",
                f"B_model: matched={n_match}/{len(voice_obs)}  "
                f"avg_div={avg_div:.2f}",
            ))

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Логирование сессии
    # ------------------------------------------------------------------

    def log_observation(self, obs: Observation) -> None:
        """Добавить наблюдение в лог текущей сессии."""
        self._text_log.append(obs)

    def session_narrative(self, max_lines: int = 20) -> str:
        """Выдать нарратив всей сессии (последние max_lines наблюдений)."""
        logs = self._text_log[-max_lines:]
        return "\n".join(f"  [{o.outcome_tag[:4]}] {o.text}" for o in logs)

    def reset_session(self) -> None:
        """Сброс лога сессии (при смене текста)."""
        self._text_log.clear()
        self._confirmed_run = 0

    # ------------------------------------------------------------------
    # Вспомогательные
    # ------------------------------------------------------------------

    def _fmt(self, ru: str, en: str = "", **kwargs) -> str:
        template = ru if self.lang == "ru" else (en or ru)
        return template.format(**kwargs) if kwargs else template

    def _gen_hint(self, gen: Optional["Generalization"]) -> str:
        if gen is None:
            return "?"
        if gen.label:
            return gen.label
        chain = gen.feature_chain
        if chain:
            return "→".join(str(f)[:6] for f in chain[:3])
        return gen.gen_id[:8]

    def _make(
        self,
        tok: str,
        tag: str,
        text: str,
        conf: float,
        is_surprise: bool = False,
        new_gen_hint: Optional[str] = None,
        voice_prediction: Optional[str] = None,
        voice_divergence: Optional[float] = None,
    ) -> Observation:
        obs = Observation(
            token_label      = tok,
            outcome_tag      = tag,
            text             = text,
            confidence       = conf,
            is_surprise      = is_surprise,
            new_gen_hint     = new_gen_hint,
            voice_prediction = voice_prediction,
            voice_divergence = voice_divergence,
        )
        self._text_log.append(obs)
        return obs

    # ------------------------------------------------------------------
    # Обнаружение разрыва контекста и формулирование запроса
    # ------------------------------------------------------------------

    def detect_context_gap(
        self,
        result: "StepResult",
        lead_gen: Optional["Generalization"],
        lead_sig: float,
        gap_threshold: float = 0.25,
        min_streak: int = 3,
    ) -> Optional["ContextQuery"]:
        """
        Обнаружить разрыв контекста: момент, когда система видит токен,
        выходящий за пределы актуального горизонта восприятия.

        Возвращает ContextQuery если:
          • EXPLORING И lead_sig < gap_threshold — система совсем не знает что делать
          • REFUTED подряд min_streak раз — поток опровержений превышает порог

        Логика аналогична «не вижу что за спиной — нужна команда повернуться».
        """
        from core.algorithm import StepOutcome

        outcome = result.outcome
        tok = getattr(result.token, "label", "?") or "?"

        if outcome == StepOutcome.EXPLORING and lead_sig < gap_threshold:
            hint = self._gen_hint(lead_gen) if lead_gen else "?"
            query_text = self.formulate_query(tok, hint, "EXPLORING")
            return ContextQuery(
                trigger_token=tok,
                trigger_outcome="EXPLORING",
                missing_hint=hint,
                query_text=query_text,
                confidence_gap=1.0 - lead_sig,
            )

        if outcome == StepOutcome.REFUTED:
            # Считаем подряд идущие REFUTED из хвоста лога
            streak = 0
            for obs in reversed(self._text_log):
                if obs.outcome_tag == "REFUTED":
                    streak += 1
                else:
                    break
            if streak >= min_streak:
                hint = self._gen_hint(lead_gen) if lead_gen else "?"
                query_text = self.formulate_query(tok, hint, "REFUTED")
                return ContextQuery(
                    trigger_token=tok,
                    trigger_outcome="REFUTED",
                    missing_hint=hint,
                    query_text=query_text,
                    confidence_gap=1.0 - lead_sig,
                )

        return None

    def formulate_query(
        self,
        trigger_token: str,
        missing_hint: str,
        outcome_tag: str,
    ) -> str:
        """
        Сформулировать запрос к учителю на естественном языке.

        Использует хвост лога наблюдений как контекст запроса.
        Это — голос интерпретатора за систему, пока она не говорит сама.
        """
        # Собрать «контекст» из последних интересных наблюдений
        recent = self._text_log[-8:] if self._text_log else []
        context_tokens = [
            o.token_label for o in recent
            if o.outcome_tag in ("CONFIRMED", "COMPLETED")
        ][:4]

        if outcome_tag == "EXPLORING":
            if context_tokens:
                ctx_str = ", ".join(f"«{t}»" for t in context_tokens)
                return self._fmt(
                    f"Что значит «{trigger_token}» после {ctx_str}?",
                    f"What does '{trigger_token}' mean after {ctx_str}?",
                )
            return self._fmt(
                f"Контекст для «{trigger_token}»: совсем не знаю.",
                f"Need context for '{trigger_token}': no pattern matched.",
            )

        if outcome_tag == "REFUTED":
            if context_tokens:
                ctx_str = ", ".join(f"«{t}»" for t in context_tokens)
                return self._fmt(
                    f"Несколько раз ошиблась на «{trigger_token}» "
                    f"(ожидала: {missing_hint}). Контекст был: {ctx_str}. "
                    f"Напомни исходный текст.",
                    f"Repeatedly wrong on '{trigger_token}' "
                    f"(expected: {missing_hint}). Context: {ctx_str}. "
                    f"Please recall the source text.",
                )
            return self._fmt(
                f"Несколько раз ошиблась на «{trigger_token}» "
                f"(ожидала: {missing_hint}). Напомни исходный текст.",
                f"Repeatedly wrong on '{trigger_token}' "
                f"(expected: {missing_hint}). Recall source text.",
            )

        return self._fmt(
            f"Нужен дополнительный контекст для: «{trigger_token}»",
            f"Need additional context for: '{trigger_token}'",
        )


# ──────────────────────────────────────────────────────────────────────────────
# Удобная обёртка: прогнать текст с речевым комментарием
# ──────────────────────────────────────────────────────────────────────────────

def run_with_speech(
    system,          # LearningSystem
    text: str,
    speech: Optional[SpeechDriver] = None,
    print_live: bool = True,
    verbosity: int = 1,
) -> List[Observation]:
    """
    Прогнать текст через систему и получить речевой нарратив.

    Возвращает список Observation (канал B).
    Если print_live=True — печатает каждое наблюдение по мере появления.
    """
    from drivers.text_driver import TextDriver

    if speech is None:
        speech = SpeechDriver(verbosity=verbosity)
    speech.reset_session()

    d = TextDriver(driver_id="text")
    observations: List[Observation] = []
    tokens = list(d.produce(text))

    for tok in tokens:
        result = system.process_token(tok)
        active = system.engine.context.active_gen_ids()
        obs = speech.observe(result, system.base, active)
        if obs:
            observations.append(obs)
            if print_live:
                _print_obs(obs)

    system.reset_context()

    summary = speech.summarize(text, observations, len(tokens))
    if print_live:
        print()
        print(summary)
        print()

    return observations


def _print_obs(obs: Observation) -> None:
    W  = "\033[0m"; GR = "\033[92m"; AM = "\033[93m"
    RD = "\033[91m"; DM = "\033[90m"; CY = "\033[96m"
    COLOR = {
        "CONFIRMED": GR,
        "COMPLETED": CY,
        "REFUTED":   RD,
        "EXPLORING": DM,
    }
    c = COLOR.get(obs.outcome_tag, W)
    print(f"  {c}[{obs.outcome_tag[:4]}]{W} {obs.text}")


# ──────────────────────────────────────────────────────────────────────────────
# Демо
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    from core.app import CoreApplication
    from training.serial_corpus import ALL_SERIAL_TEXTS

    W  = "\033[0m"; CY = "\033[96m"; BD = "\033[1m"

    def hdr(t: str) -> None:
        print(f"\n{BD}{CY}{'═'*68}{W}")
        print(f"{BD}{CY}  {t}{W}")
        print(f"{BD}{CY}{'═'*68}{W}\n")

    hdr("SpeechDriver — демонстрация двухканального обучения")

    app = CoreApplication(config={"mock_teacher": False, "feature_tolerance": 0.15})
    app.startup()

    speech = SpeechDriver(verbosity=1, lang="ru")

    # Обучение на нескольких текстах
    hdr("Фаза 1: Обучение (5 проходов)")
    from drivers.text_driver import TextDriver
    d = TextDriver(driver_id="text")
    for _ in range(5):
        for t in ALL_SERIAL_TEXTS[:10]:
            for tok in d.produce(t):
                app.system.process_token(tok)
            app.system.reset_context()
    print(f"  База: {len(app.system.base.all())} Gen после 5 проходов")

    # Речевой нарратив на нескольких текстах
    hdr("Фаза 2: Путь внимания (канал B)")

    test_texts = [
        "маша пришла к медведю медведь обрадовался поздоровались",
        "волк встретил зайца заяц испугался волк сказал не бойся",
        "маша приготовила суп позвала всех поели поблагодарили",   # частично незнакомый
    ]

    for i, text in enumerate(test_texts, 1):
        print(f"{BD}— Текст {i} —{W}")
        run_with_speech(app.system, text, speech=speech, verbosity=1)

    # Полный нарратив сессии
    hdr("Нарратив всей сессии (последние 15 наблюдений)")
    print(speech.session_narrative(max_lines=15))
