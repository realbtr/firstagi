"""
core/dual_driver.py — Двойной цикл внимания: TextDriver + SmartTextDriver.

Архитектура «переосмысления в новом свете»:

  text_system  — накопленная база (TextDriver Gen, уровень слов).
                 Поставляет КАНДИДАТОВ для SmartDriver через активные цепочки.

  smart_system — свежая база (SmartDriver Gen, уровень роли+проб).
                 Видит те же слова, но строит ДРУГИЕ обобщения:
                 «слово|p=N|role=theme/rheme».

Ключевое свойство («переосмысление»):
  Слово CONFIRMED для text_system → кандидат для SmartDriver.
  Если SmartDriver REFUTED → слово знакомо по смыслу, но ново по роли.
  Накопленное знание text_system не перекрывает smart_system — обе базы
  растут независимо, но связаны потоком кандидатов.

Алгоритм на каждое слово:
  1. TextDriver → feature F → text_system.process_token(F) → outcome_T
  2. get_next_expected_words(text_system) → candidates C  ← из активных цепочек
  3. EntropyMinimizer.probe_word(next_word, C) → probe_stats
  4. SmartDriver → feature F (тот же!) + label «слово|p=N|role=R» → smart_system → outcome_S
  5. Если outcome_T=CONFIRMED и outcome_S=REFUTED → событие REINTERPRETATION

Замыкание петли:
  После обучения обеих систем на одном корпусе — candidates C сужается
  до 1–3 слов (вместо 87), число проб падает до 1.
  Это показывает, что SmartDriver «усвоил» текстовое пространство.

Использование:
    loop = DualDriverLoop(text_app, smart_app)
    results = loop.process_text("маша пошла в лес")
    for step in results:
        print(step.word, step.text_outcome, step.smart_outcome,
              "!" if step.is_reinterpretation else "")
"""
from __future__ import annotations

import math
import re
import uuid
from dataclasses import dataclass, field
from typing import List, Optional, TYPE_CHECKING

from core.algorithm import StepOutcome
from core.feature import Feature, RegionCharacteristics
from core.generalization import PeripheralToken
from drivers.text_driver import _build_vocab, _word_to_region
from drivers.smart_text_driver import (
    CandidateSet, EntropyMinimizer, ProbeStats, ThemeRhemeRouter,
)

if TYPE_CHECKING:
    from core.app import CoreApplication


# ──────────────────────────────────────────────────────────────────────────────
# Извлечение ожидаемых следующих слов из активных Gen цепочек
# ──────────────────────────────────────────────────────────────────────────────

def build_next_word_index(system) -> dict:
    """
    Построить биграммный индекс {слово → [следующие слова]} из меток Gen.

    Перебирает все Gen в базе, разбивает label по «·» и строит словарь переходов.
    Используется DualDriverLoop как быстрая альтернатива поиску по активным цепочкам
    (цепочки chain=1 сразу COMPLETE и не дают ничего из контекста).
    """
    index: dict = {}
    for gen in system.base.all():
        if not gen.label:
            continue
        parts = [p.split("|")[0].strip() for p in gen.label.split("·")]
        for i in range(len(parts) - 1):
            w_from, w_to = parts[i], parts[i + 1]
            if w_from and w_to:
                index.setdefault(w_from, []).append(w_to)
    return {k: list(set(v)) for k, v in index.items()}


def get_next_expected_words(system, tolerance: float = 0.25) -> List[str]:
    """
    Из активных Gen цепочек извлечь ожидаемые следующие слова.

    Два источника (объединяем):

    Источник А — Label-based (точный, работает для цепочечных Gen):
      Для каждой активной цепочки g в позиции k:
        gen.label = «w0·w1·w2...» (chain Gen) или «w0» (atomic Gen)
        expected_next = label_parts[k]   ← слово на позиции k

    Источник Б — Vector-based (для Gen из других текстов):
      Найти Feature-объект для следующего ожидаемого feature_id.
      Найти в базе Gen, чей первый вектор близок к этому.
      Их labels = кандидаты.

    Возвращает список уникальных слов (без метаданных |p=...|role=...).
    Пустой список если контекст пуст.
    """
    context = system.engine.context
    engine  = system.engine
    base    = system.base
    words: List[str] = []

    for gen_id in context.active_gen_ids():
        gen = base.get(gen_id)
        ag  = context._active.get(gen_id)
        if gen is None or ag is None:
            continue

        k = ag.current_feature_index

        # Источник А: из label цепочки
        if gen.label:
            label_parts = gen.label.split("·")
            if k < len(label_parts):
                raw = label_parts[k].split("|")[0].strip()
                if raw:
                    words.append(raw)

        # Источник Б: vector-based — из Gen в базе с похожим первым вектором
        if k < len(gen.feature_chain):
            next_feat_id = gen.feature_chain[k]
            next_feat = engine._features.get(next_feat_id)
            if next_feat is not None:
                next_vec = next_feat.vector
                for other in base.all():
                    if not other.feature_chain or not other.label:
                        continue
                    first_fid = other.feature_chain[0]
                    first_f   = engine._features.get(first_fid)
                    if first_f is None:
                        continue
                    if first_f.vector.distance_to(next_vec) <= tolerance:
                        # Берём последнее слово label или первое (атомарный Gen)
                        raw = other.label.split("·")[-1].split("|")[0].strip()
                        if raw:
                            words.append(raw)

    return list(set(words))


# ──────────────────────────────────────────────────────────────────────────────
# Результат одного шага
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class DualStep:
    """
    Результат обработки одного перехода (w_i → w_{i+1}) обоими драйверами.

    word              — слово w_{i+1}
    text_outcome      — результат TextDriver / text_system
    smart_outcome     — результат SmartTextDriver / smart_system
    probe_stats       — статистика символьных проб
    role              — тема/рема (ThemeRhemeRouter)
    candidates        — кандидаты от text_system (N слов)
    is_reinterpretation — TextDriver CONFIRMED + SmartDriver REFUTED
    is_discovery      — SmartDriver нашёл что-то новое (REFUTED), TextDriver тоже REFUTED
    """
    word:               str
    text_outcome:       str
    smart_outcome:      str
    probe_stats:        ProbeStats
    role:               str
    candidates:         List[str]

    @property
    def is_reinterpretation(self) -> bool:
        """Знакомо по смыслу (TextDriver) но ново в этой роли (SmartDriver)."""
        return (
            self.text_outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED)
            and self.smart_outcome == StepOutcome.REFUTED
        )

    @property
    def is_discovery(self) -> bool:
        """Оба драйвера нашли что-то новое."""
        return (
            self.text_outcome == StepOutcome.REFUTED
            and self.smart_outcome == StepOutcome.REFUTED
        )

    @property
    def is_convergent(self) -> bool:
        """Оба драйвера согласны (оба CONFIRMED/COMPLETED)."""
        return (
            self.text_outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED)
            and self.smart_outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED)
        )


@dataclass
class DualPassResult:
    """Результат одного прогона текста через DualDriverLoop."""
    text:       str
    steps:      List[DualStep]

    @property
    def text_mr(self) -> float:
        """Match rate TextDriver."""
        conf = sum(1 for s in self.steps
                   if s.text_outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED))
        return conf / len(self.steps) if self.steps else 0.0

    @property
    def smart_mr(self) -> float:
        """Match rate SmartDriver."""
        conf = sum(1 for s in self.steps
                   if s.smart_outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED))
        return conf / len(self.steps) if self.steps else 0.0

    @property
    def reinterpretations(self) -> List[DualStep]:
        return [s for s in self.steps if s.is_reinterpretation]

    @property
    def discoveries(self) -> List[DualStep]:
        return [s for s in self.steps if s.is_discovery]

    @property
    def convergent(self) -> List[DualStep]:
        return [s for s in self.steps if s.is_convergent]

    @property
    def avg_probes(self) -> float:
        if not self.steps:
            return 0.0
        return sum(s.probe_stats.probes_used for s in self.steps) / len(self.steps)

    @property
    def avg_candidates(self) -> float:
        if not self.steps:
            return 0.0
        return sum(s.probe_stats.candidates_before for s in self.steps) / len(self.steps)


# ──────────────────────────────────────────────────────────────────────────────
# DualDriverLoop
# ──────────────────────────────────────────────────────────────────────────────

class DualDriverLoop:
    """
    Двойной цикл внимания: TextDriver + SmartTextDriver.

    Параметры
    ----------
    text_app  : CoreApplication — система с накопленной базой TextDriver Gen
    smart_app : CoreApplication — система с пустой (или частично заполненной) базой
    min_entropy : float         — порог EntropyMinimizer (биты)
    max_probes  : int           — лимит символьных проб

    Основные методы
    ---------------
    process_text(text)     — прогнать текст, вернуть DualPassResult
    train_parallel(texts, n_passes) — обучить обе системы параллельно
    """

    def __init__(
        self,
        text_app:    "CoreApplication",
        smart_app:   "CoreApplication",
        min_entropy: float = 0.5,
        max_probes:  int   = 5,
    ) -> None:
        self._text_app  = text_app
        self._smart_app = smart_app

        self._minimizer = EntropyMinimizer(
            min_entropy_threshold=min_entropy,
            max_probes=max_probes,
        )
        self._vocab: dict[str, float] = {}
        self._next_word_index: dict = {}  # {word → [next_words]}, rebuilt per process_text

    # ──────────────────────────────────────────────────────────────────────
    # Основной метод

    def process_text(self, text: str) -> DualPassResult:
        """
        Прогнать текст через оба драйвера, слово за словом.

        Порядок:
          1. TextDriver токен → text_system  → outcome_T, обновляет контекст
          2. get_next_expected_words         → кандидаты C (из цепочек text_system)
          3. EntropyMinimizer на w2 с C      → probe_stats
          4. SmartDriver токен               → smart_system → outcome_S

        Возвращает DualPassResult со всеми шагами.
        """
        words = self._tokenize(text)
        if len(words) < 2:
            return DualPassResult(text=text, steps=[])

        # Перестраиваем vocab если нужно (объединяем словари обеих систем)
        if not self._vocab:
            self._rebuild_vocab(words)

        # Тема/Рема разметка всего текста
        router    = ThemeRhemeRouter(self._vocab)
        tr_labels = {lbl.word: lbl.role for lbl in router.label_sequence(words)}

        steps: List[DualStep] = []

        self._text_app.system.reset_context()
        self._smart_app.system.reset_context()

        # Биграммный индекс из накопленной базы text_system: {слово → [след. слова]}
        # Нужен потому что chain=1 Gen немедленно COMPLETE → активный контекст пуст.
        self._next_word_index = build_next_word_index(self._text_app.system)

        last_confirmed_word: Optional[str] = None

        for i in range(len(words) - 1):
            w1, w2 = words[i], words[i + 1]

            # 1. Кандидаты: если предыдущий переход был подтверждён, берём продолжения
            #    из биграммного индекса (что text_system ожидает после w1).
            candidates_list = self._next_word_index.get(w1, [])
            candidates      = CandidateSet(candidates_list)

            # 2. EntropyMinimizer: сколько символьных проб нужно для w2
            probe = self._minimizer.probe_word(w2, candidates)

            # 3. TextDriver токен → text_system (обновляет контекст для следующего шага)
            text_token  = self._make_token(w1, w2, label=w2, driver_id="dual_td")
            text_result = self._text_app.system.process_token(text_token)

            # 4. SmartDriver токен (тот же Feature vector, обогащённый label)
            role  = tr_labels.get(w2, "rheme")
            label = f"{w2}|p={probe.probes_used}|h={probe.entropy_saved:.1f}|role={role}"
            smart_token  = self._make_token(w1, w2, label=label, driver_id="dual_sd")
            smart_result = self._smart_app.system.process_token(smart_token)

            if text_result.outcome in (StepOutcome.CONFIRMED, StepOutcome.COMPLETED):
                last_confirmed_word = w2

            steps.append(DualStep(
                word          = w2,
                text_outcome  = text_result.outcome,
                smart_outcome = smart_result.outcome,
                probe_stats   = probe,
                role          = role,
                candidates    = candidates_list,
            ))

        return DualPassResult(text=text, steps=steps)

    # ──────────────────────────────────────────────────────────────────────
    # Параллельное обучение

    def train_parallel(self, texts: List[str], n_passes: int = 1) -> dict:
        """
        Обучить обе системы параллельно на одном корпусе.

        Возвращает сводку за последний проход:
          text_base   — размер базы text_system
          smart_base  — размер базы smart_system
          reinterp    — число событий «переосмысления» в последнем проходе
          avg_probes  — среднее число проб в последнем проходе
          avg_candidates — среднее число кандидатов из text_system
        """
        # Перестраиваем vocab по всему корпусу
        all_words = [w for t in texts for w in self._tokenize(t)]
        from drivers.text_driver import _build_vocab
        self._vocab = _build_vocab(all_words)

        stats = {"text_base": 0, "smart_base": 0,
                 "reinterp": 0, "avg_probes": 0.0, "avg_candidates": 0.0}

        for p in range(1, n_passes + 1):
            all_steps: List[DualStep] = []
            for t in texts:
                r = self.process_text(t)
                all_steps.extend(r.steps)

            n = len(all_steps)
            stats = {
                "text_base":      len(self._text_app.system.base.all()),
                "smart_base":     len(self._smart_app.system.base.all()),
                "reinterp":       sum(1 for s in all_steps if s.is_reinterpretation),
                "avg_probes":     sum(s.probe_stats.probes_used for s in all_steps) / max(n, 1),
                "avg_candidates": sum(s.probe_stats.candidates_before for s in all_steps) / max(n, 1),
                "pass":           p,
            }

        return stats

    # ──────────────────────────────────────────────────────────────────────
    # Вспомогательные методы

    def _make_token(
        self, w1: str, w2: str, label: str, driver_id: str
    ) -> PeripheralToken:
        """Создать PeripheralToken для пары слов (w1, w2)."""
        vi1 = self._vocab.get(w1, 0.5)
        vi2 = self._vocab.get(w2, 0.5)

        src = _word_to_region(w1, vi1)
        tgt = _word_to_region(w2, vi2)
        direction = (vi2 - vi1) * math.pi

        feat = Feature.from_regions(
            feature_id=str(uuid.uuid4()),
            direction=direction,
            distance=1.0,
            source=src,
            target=tgt,
        )
        return PeripheralToken.new(driver_id=driver_id, data=feat, label=label)

    def _tokenize(self, text: str) -> List[str]:
        return [w for w in re.split(r"[\s,.\-!?;:\"'()]+", text.lower()) if w]

    def _rebuild_vocab(self, words: List[str]) -> None:
        from drivers.text_driver import _build_vocab
        self._vocab = _build_vocab(words)
