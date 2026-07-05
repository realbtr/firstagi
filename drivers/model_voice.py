"""
ModelVoice — Канал B_модель (Phase 2 двухканального обучения).

Пока SpeechDriver (B_интерпретатор) описывает произошедшее после обработки токена,
ModelVoice предсказывает ожидаемое слово ДО его прихода — из активных Gen цепочек.
Расхождение двух голосов = тренировочный сигнал Phase 2.

```
[ПЕРЕД токеном]
  B_модель:    predict(system) → «маша»  conf=0.73
  (реальный токен приходит)
[ПОСЛЕ токена]
  B_интерпр:  [CONF] Подтверждает: «маша» ← gen_abc
  Δ:          diverge(pred, «маша»)  → ✓ 0.00

  B_модель:    predict(system) → «пошла» conf=0.61
  (реальный токен приходит: «побежала»)
[ПОСЛЕ токена]
  B_интерпр:  [REFU] Удивилась: «побежала». Ожидала: «пошла».
  Δ:          diverge(pred, «побежала») → ↔ 0.80
```

Два источника предсказаний (как в get_next_expected_words, core/dual_driver.py):
  А) Label-based: Gen.label = «w0·w1·w2», берём слово на текущей позиции
  Б) Feature-based: feature_id → Counter[word] (накапливаем по ходу обучения)

Использование:
    voice = ModelVoice()
    pred  = voice.predict(system)          # до process_token
    result = system.process_token(tok)
    voice.record_feature(result.matched_feature_id, tok.label)
    div   = voice.diverge(pred, tok.label) # дивергенция
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.algorithm import StepResult
    from core.learning import LearningSystem


# ══════════════════════════════════════════════════════════════════════════════
# VoicePrediction — что B_модель предсказала до токена
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class VoicePrediction:
    """Предсказание B_модель — вычислено ДО обработки токена."""
    words:      List[str]         # топ-N предсказанных слов (или [] если пусто)
    confidence: float             # уверенность в первом слове [0, 1]
    source_gen: Optional[str]     # gen_id с наивысшей значимостью

    @property
    def top_word(self) -> Optional[str]:
        return self.words[0] if self.words else None

    @property
    def has_prediction(self) -> bool:
        return bool(self.words)

    def as_text(self, lang: str = "ru") -> str:
        if not self.words:
            return "~" if lang == "ru" else "~"
        top = f"«{self.words[0]}»" if lang == "ru" else f"'{self.words[0]}'"
        conf_str = f" conf={self.confidence:.2f}"
        if len(self.words) > 1:
            alts = ", ".join(
                (f"«{w}»" if lang == "ru" else f"'{w}'") for w in self.words[1:3]
            )
            suffix = f" (или: {alts})" if lang == "ru" else f" (or: {alts})"
            return f"{top}{conf_str}{suffix}"
        return f"{top}{conf_str}"


# ══════════════════════════════════════════════════════════════════════════════
# ChannelDivergence — дивергенция B_модель vs реальность
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ChannelDivergence:
    """
    Дивергенция между предсказанием B_модель и фактическим токеном.

    divergence ∈ [0.0, 1.0]:
      0.0 = идеальное совпадение
      1.0 = полный сюрприз

    Это и есть тренировочный сигнал Phase 2:
    высокая дивергенция при высокой уверенности → обновить ожидания.
    """
    predicted_words: List[str]    # что модель предсказала
    actual_word:     str          # что реально пришло
    match:           bool         # точное совпадение
    divergence:      float        # [0.0, 1.0]
    confidence:      float        # уверенность предсказания
    source_gen:      Optional[str]

    def as_text(self, lang: str = "ru") -> str:
        if not self.predicted_words:
            if lang == "ru":
                return f"~ Нет предсказания → «{self.actual_word}»"
            return f"~ No prediction → '{self.actual_word}'"
        if self.match:
            return (f"✓ Угадала «{self.actual_word}»" if lang == "ru"
                    else f"✓ Correct: '{self.actual_word}'")
        pred = self.predicted_words[0]
        div  = f"[div={self.divergence:.2f}]"
        if lang == "ru":
            return f"↔ Ждала «{pred}», получила «{self.actual_word}» {div}"
        return f"↔ Expected '{pred}', got '{self.actual_word}' {div}"


# ══════════════════════════════════════════════════════════════════════════════
# ModelVoice
# ══════════════════════════════════════════════════════════════════════════════

class ModelVoice:
    """
    Канал B_модель — предсказывает следующий токен из активных Gen.

    Три уровня знания (объединяем, взвешиваем по значимости):
      1. Feature-based: feature_id → Counter[word]
         Строится через record_feature(). Работает для любых Gen.
      2. Label-based: читает Gen.label как «w0·w1·w2» на позиции k.
         Работает для Gen с человекочитаемыми метками.
      3. Bigram-based (fallback): word_i → Counter[word_{i+1}]
         Строится через record_transition(). Критически важен для
         chain=1 Gen, которые немедленно COMPLETED и оставляют
         контекст пустым (в этом случае источники 1 и 2 молчат).

    Операции read-only: predict() НЕ мутирует контекст движка.
    """

    def __init__(self) -> None:
        # feature_id → Counter[word] — обратный маппинг (источник 1)
        self._feature_words: Dict[str, Counter] = {}
        # word → Counter[next_word] — биграммный индекс (источник 3)
        self._bigrams: Dict[str, Counter] = {}
        # последнее обработанное слово (для биграммного fallback)
        self._last_word: Optional[str] = None
        # история дивергенций за текущую сессию
        self._history: List[ChannelDivergence] = []

    # ------------------------------------------------------------------
    # Запись (вызывать ПОСЛЕ process_token)

    def record_feature(
        self,
        feature_id: Optional[str],
        word: str,
    ) -> None:
        """
        Зафиксировать, что слово word соответствует feature_id.

        Вызывать после process_token() с result.matched_feature_id.
        Строит обратный маппинг feature → [слова].
        Также обновляет _last_word для биграммного fallback.
        """
        if not word or word == "?":
            return
        w = word.lower()
        if feature_id:
            if feature_id not in self._feature_words:
                self._feature_words[feature_id] = Counter()
            self._feature_words[feature_id][w] += 1
        self._last_word = w

    def record_transition(self, from_word: str, to_word: str) -> None:
        """
        Зафиксировать биграмму from_word → to_word.

        Строит биграммный индекс для fallback-предсказания когда
        активный контекст пуст (chain=1 Gen немедленно COMPLETED).

        Вызывать во время фазы обучения:
            voice.record_transition(prev_tok_label, curr_tok_label)
        """
        if not from_word or not to_word or from_word == "?" or to_word == "?":
            return
        fw = from_word.lower()
        tw = to_word.lower()
        if fw not in self._bigrams:
            self._bigrams[fw] = Counter()
        self._bigrams[fw][tw] += 1

    # ------------------------------------------------------------------
    # Предсказание (вызывать ДО process_token)

    def predict(
        self,
        system: "LearningSystem",
        top_n: int = 3,
    ) -> VoicePrediction:
        """
        Предсказать следующее слово из активного контекста.

        Источники предсказаний (объединяем, взвешиваем по значимости):
          А) Label-based: Gen.label.split('·')[current_pos].split('|')[0]
          Б) Feature-based: self._feature_words[expected_feature_id]

        Возвращает VoicePrediction (пустой если контекст пуст).
        Не изменяет состояние движка.
        """
        context = system.engine.context
        base    = system.base
        engine  = system.engine

        # {gen_id: feature_id} — что каждый активный Gen ожидает следующим
        expected = context.get_expected_features(base)

        candidates: Counter = Counter()
        best_gen  = None
        best_sig  = 0.0

        for gen_id, feature_id in expected.items():
            gen = base.get(gen_id)
            sig = gen.significance if gen else 0.05
            if sig > best_sig:
                best_sig = sig
                best_gen = gen_id

            # Источник А: Label-based (если Gen имеет читаемый label)
            if gen and gen.label:
                ag = context._active.get(gen_id)
                if ag is not None:
                    k     = ag.current_feature_index
                    parts = gen.label.split("·")
                    if k < len(parts):
                        raw = parts[k].split("|")[0].strip().lower()
                        if raw:
                            candidates[raw] += sig * 2.0   # усиленный вес

            # Источник Б: Feature-based (из накопленного маппинга)
            if feature_id in self._feature_words:
                for word, count in self._feature_words[feature_id].items():
                    candidates[word] += count * sig

        # Источник В (fallback): биграммный индекс.
        # Критически важен когда контекст пуст (chain=1 Gen немедленно COMPLETED).
        # Активируется всегда когда candidates пусты — не только при empty expected.
        if not candidates and self._last_word and self._last_word in self._bigrams:
            for word, count in self._bigrams[self._last_word].items():
                candidates[word] += count * 0.3   # пониженный вес биграмм

        if not candidates:
            return VoicePrediction(words=[], confidence=0.0, source_gen=best_gen)

        top          = candidates.most_common(top_n)
        total_weight = sum(candidates.values())
        words        = [w for w, _ in top]
        confidence   = top[0][1] / total_weight if total_weight > 0 else 0.0

        return VoicePrediction(
            words      = words,
            confidence = round(confidence, 3),
            source_gen = best_gen,
        )

    # ------------------------------------------------------------------
    # Дивергенция (вызывать ПОСЛЕ process_token)

    def diverge(
        self,
        prediction:  VoicePrediction,
        actual_word: str,
    ) -> ChannelDivergence:
        """
        Вычислить дивергенцию между предсказанием и реальным словом.

        Формула:
          match         → 0.0
          нет предсказ. → 1.0
          промах        → 0.5 + confidence * 0.5
            (чем увереннее было неверное предсказание, тем выше сигнал)
        """
        actual_low = actual_word.lower()
        match = actual_low in [w.lower() for w in prediction.words]

        if not prediction.words:
            div = 1.0
        elif match:
            div = 0.0
        else:
            div = round(min(1.0, 0.5 + prediction.confidence * 0.5), 3)

        cd = ChannelDivergence(
            predicted_words = prediction.words,
            actual_word     = actual_word,
            match           = match,
            divergence      = div,
            confidence      = prediction.confidence,
            source_gen      = prediction.source_gen,
        )
        self._history.append(cd)
        return cd

    # ------------------------------------------------------------------
    # Статистика

    def stats(self) -> dict:
        """Статистика предсказаний за сессию."""
        if not self._history:
            return {
                "total":           0,
                "matches":         0,
                "match_rate":      0.0,
                "avg_divergence":  0.0,
                "feature_vocab":   self.vocab_size,
                "bigram_vocab":    self.bigram_vocab_size,
            }
        total   = len(self._history)
        matches = sum(1 for d in self._history if d.match)
        avg_div = sum(d.divergence for d in self._history) / total
        return {
            "total":          total,
            "matches":        matches,
            "match_rate":     round(matches / total, 3),
            "avg_divergence": round(avg_div, 3),
            "feature_vocab":  self.vocab_size,
            "bigram_vocab":   self.bigram_vocab_size,
        }

    @property
    def vocab_size(self) -> int:
        """Размер словаря feature → word (накопительный)."""
        return len(self._feature_words)

    @property
    def bigram_vocab_size(self) -> int:
        """Число уникальных слов в биграммном индексе."""
        return len(self._bigrams)

    @property
    def history(self) -> List[ChannelDivergence]:
        return list(self._history)

    def get_divergence_corrections(
        self,
        window:            int   = 200,
        high_div_threshold: float = 0.7,
        min_confidence:    float = 0.5,
    ) -> Dict[str, float]:
        """
        Вычислить поправки к значимости Gen на основе дивергенций.

        Логика: если Gen предсказал уверенно (confidence ≥ min_confidence),
        но ошибся (divergence ≥ high_div_threshold) — его significance
        завышена. Возвращает {gen_id: penalty} где penalty < 0.

        Параметры
        ---------
        window            : число последних записей для анализа
        high_div_threshold: порог дивергенции (0.7 = «уверенная ошибка»)
        min_confidence    : минимальная уверенность предсказания
        """
        recent = self._history[-window:]
        penalties: Dict[str, float] = {}
        for div_rec in recent:
            if (div_rec.source_gen
                    and div_rec.divergence >= high_div_threshold
                    and div_rec.confidence >= min_confidence):
                penalties[div_rec.source_gen] = (
                    penalties.get(div_rec.source_gen, 0.0) - div_rec.divergence
                )
        return penalties

    def reset_history(self) -> None:
        """Сброс истории. Словарь feature→word сохраняется (долгосрочный)."""
        self._history.clear()

    def __repr__(self) -> str:
        s = self.stats()
        return (
            f"ModelVoice("
            f"vocab={self.vocab_size}, "
            f"bigrams={self.bigram_vocab_size}, "
            f"total={s['total']}, "
            f"match_rate={s['match_rate']:.2f}, "
            f"avg_div={s['avg_divergence']:.2f})"
        )
