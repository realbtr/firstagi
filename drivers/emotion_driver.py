"""
drivers/emotion_driver.py — Эмоциональный драйвер: контексты обобщений.

Системный драйвер, который сохраняет эмоционально значимые контексты
отдельных обобщений. Работает как «подсознание»: накапливает связи
между Gen и эмоциональными исходами, без явной интерпретации.

Принцип (из концепции пользователя):
  «Модель не имеет врожденной зеркальной нейронной сети.
   Она работает как нарцисс, вычисляя эмоциональный контекст
   по вторичным признакам.»

Вторичные признаки:
  - CONFIRMED  → позитив (ожидание оправдалось)
  - REFUTED    → удивление/негатив (ожидание не оправдалось)
  - COMPLETED  → удовлетворение (цепочка завершена успешно)

Драйвер накапливает:
  - context_graph: Gen → {другие Gen, с которыми появляется}
  - valence: Gen → средняя эмоциональная окраска
  - co_occurrence: (Gen_A, Gen_B) → частота совместного появления

Использование:
    emotion = EmotionDriver()
    # При каждом шаге:
    emotion.record(active_gen_ids, outcome, token_label)
    # Для генерации вопросов:
    pairs = emotion.unfamiliar_pairs()
    suggestions = emotion.suggest_stories()

Интеграция с AttentionLoop:
    В step() после process_token():
        emotion.record(active_ids, outcome, token_label)
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

from core.generalization import PeripheralToken
from .base import PeripheralDriver


# ══════════════════════════════════════════════════════════════════════
# Запись эмоционального контекста
# ══════════════════════════════════════════════════════════════════════

@dataclass
class EmotionEntry:
    """Одна запись эмоционального контекста."""
    gen_ids: Tuple[str, ...]     # активные Gen в момент записи
    outcome: str                 # CONFIRMED / REFUTED / COMPLETED
    valence: float               # +1.0 (позитив) / -1.0 (негатив) / 0.0 (нейтрально)
    token_label: str             # слово-токен
    step_n: int                  # порядковый номер


@dataclass
class Relationship:
    """Связь между двумя Gen."""
    gen_a: str
    gen_b: str
    co_count: int = 0            # сколько раз появлялись вместе
    positive_count: int = 0      # позитивные исходы вместе
    negative_count: int = 0      # негативные исходы вместе
    avg_valence: float = 0.0     # средняя эмоциональная окраска

    @property
    def strength(self) -> float:
        """Сила связи: частота × |валентность|."""
        if self.co_count == 0:
            return 0.0
        return (self.co_count / 100.0) * abs(self.avg_valence)

    @property
    def emotional_charge(self) -> str:
        """Эмоциональная заряженность связи."""
        if self.avg_valence > 0.3:
            return "positive"
        elif self.avg_valence < -0.3:
            return "negative"
        return "neutral"


# ══════════════════════════════════════════════════════════════════════
# EmotionDriver
# ══════════════════════════════════════════════════════════════════════

class EmotionDriver:
    """
    Эмоциональный драйвер: контексты обобщений.

    Является PeripheralDriver-подобным (имеет record() и stats()),
    но НЕ наследует PeripheralDriver — он не генерирует токены,
    а записывает контексты.

    Приоритет: ниже TextDriver, выше MemoryDriver.
    Активируется автоматически при каждом шаге AttentionLoop.
    """

    DRIVER_ID = "emotion"

    # Валентность исходов
    VALENCE = {
        "CONFIRMED":  0.3,    # позитив: ожидание оправдалось
        "COMPLETED":  0.8,    # сильный позитив: цепочка завершена
        "REFUTED":   -0.5,    # негатив: удивление/опровержение
        "EXPLORING":  0.0,    # нейтрально: исследование
    }

    def __init__(self, max_entries: int = 10000, annotation_driver=None) -> None:
        self._max_entries = max_entries
        self._entries: List[EmotionEntry] = []
        self._step_n: int = 0

        # Ссылка на AnnotationDriver (учительская разметка)
        self._annotation_driver = annotation_driver

        # context_graph: gen_id → {другой_gen_id: частота}
        self._context_graph: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))

        # valence: gen_id → [валентности]
        self._valence: Dict[str, List[float]] = defaultdict(list)

        # co_occurrence: (gen_a, gen_b) → Relationship
        self._relationships: Dict[Tuple[str, str], Relationship] = {}

        # word_emotion: слово → [валентности]
        self._word_emotion: Dict[str, List[float]] = defaultdict(list)

        # Интуиция: паттерны «действие → последствие»
        # action_pattern: (action_word, outcome_word) → {count, valence_sum}
        self._action_patterns: Dict[Tuple[str, str], Dict] = defaultdict(
            lambda: {"count": 0, "valence_sum": 0.0}
        )
        # sequence_patterns: word_i → word_{i+1} → {count, valence_sum}
        self._sequence_patterns: Dict[str, Dict[str, Dict]] = defaultdict(
            lambda: defaultdict(lambda: {"count": 0, "valence_sum": 0.0})
        )

    # ------------------------------------------------------------------
    # Запись
    # ------------------------------------------------------------------

    def record(
        self,
        active_gen_ids: Tuple[str, ...],
        outcome: str,
        token_label: str = "",
    ) -> None:
        """
        Записать эмоциональный контекст шага.

        Вызывается из AttentionLoop.step() после process_token().
        """
        valence = self.VALENCE.get(outcome, 0.0)

        entry = EmotionEntry(
            gen_ids=active_gen_ids,
            outcome=outcome,
            valence=valence,
            token_label=token_label,
            step_n=self._step_n,
        )
        self._entries.append(entry)
        self._step_n += 1

        # Ограничить размер
        if len(self._entries) > self._max_entries:
            self._entries = self._entries[-self._max_entries:]

        # Обновить граф контекстов
        for gid in active_gen_ids:
            self._valence[gid].append(valence)
            if token_label:
                self._word_emotion[token_label.lower()].append(valence)

        # Обновить co-occurrence
        gen_list = list(active_gen_ids)
        for i in range(len(gen_list)):
            for j in range(i + 1, len(gen_list)):
                key = (gen_list[i], gen_list[j]) if gen_list[i] < gen_list[j] else (gen_list[j], gen_list[i])
                if key not in self._relationships:
                    self._relationships[key] = Relationship(gen_a=key[0], gen_b=key[1])
                rel = self._relationships[key]
                rel.co_count += 1
                if valence > 0.1:
                    rel.positive_count += 1
                elif valence < -0.1:
                    rel.negative_count += 1
                # Скользящее среднее
                n = rel.co_count
                rel.avg_valence = rel.avg_valence * (n - 1) / n + valence / n

        # Обновить паттерны «действие → последствие»
        if token_label and len(self._word_emotion) > 1:
            # Предыдущее слово с эмоциональной окраской
            prev_words = [
                w for w, vals in self._word_emotion.items()
                if vals and w != token_label.lower()
            ]
            if prev_words:
                # Ближайшее предыдущее слово в эмоциональном логе
                last_entry = self._entries[-2] if len(self._entries) >= 2 else None
                if last_entry and last_entry.token_label:
                    prev_word = last_entry.token_label.lower()
                    pattern_key = (prev_word, token_label.lower())
                    pat = self._action_patterns[pattern_key]
                    pat["count"] += 1
                    pat["valence_sum"] += valence

            # Последовательности
            if self._entries and len(self._entries) >= 2:
                prev = self._entries[-2]
                if prev.token_label:
                    seq = self._sequence_patterns[prev.token_label.lower()][token_label.lower()]
                    seq["count"] += 1
                    seq["valence_sum"] += valence

    # ------------------------------------------------------------------
    # Анализ
    # ------------------------------------------------------------------

    def get_valence(self, gen_id: str) -> float:
        """Средняя эмоциональная окраска Gen."""
        vals = self._valence.get(gen_id, [])
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    def get_word_valence(self, word: str) -> float:
        """Средняя эмоциональная окраска слова.

        Приоритет:
          1. Аннотация учителя (если есть) — высший приоритет
             Даже valence=0 означает «учитель сказал нейтрально»
          2. Выведенная валентность (от похожих слов)
          3. Вычисленная из опыта (REFUTED/COMPLETED)
        """
        word_lower = word.lower()

        # 1. Аннотация учителя — ВЫСШИЙ ПРИОРИТЕТ
        if self._annotation_driver is not None:
            ann = self._annotation_driver.get_annotation(word_lower)
            if ann is not None:
                return ann.valence

        # 2. Выведенная валентность (от похожих аннотированных слов)
        if self._annotation_driver is not None:
            inf_val = self._annotation_driver.infer_valence(word_lower)
            if inf_val != 0.0:
                return inf_val

        # 3. Вычисленная из опыта
        vals = self._word_emotion.get(word_lower, [])
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    def get_relationships(
        self,
        gen_id: Optional[str] = None,
        min_co: int = 3,
    ) -> List[Relationship]:
        """
        Получить связи. Если gen_id задан — только для данного Gen.
        min_co — минимальная частота совместного появления.
        """
        rels = list(self._relationships.values())
        if gen_id:
            rels = [r for r in rels if r.gen_a == gen_id or r.gen_b == gen_id]
        return [r for r in rels if r.co_count >= min_co]

    def unfamiliar_pairs(self, min_valence_gap: float = 0.5) -> List[Dict]:
        """
        Найти пары Gen с разной эмоциональной окраской.

        Например: «Маша + медведь» = позитив, но «Маша + волк» = негатив.
        Это точки, где есть эмоциональные развилки.
        """
        pairs = []
        gen_ids = list(self._valence.keys())

        for i in range(len(gen_ids)):
            for j in range(i + 1, min(i + 20, len(gen_ids))):
                g1, g2 = gen_ids[i], gen_ids[j]
                v1 = self.get_valence(g1)
                v2 = self.get_valence(g2)

                # Проверить co-occurrence
                key = (g1, g2) if g1 < g2 else (g2, g1)
                rel = self._relationships.get(key)
                if rel and rel.co_count >= 3:
                    gap = abs(v1 - v2)
                    if gap >= min_valence_gap:
                        pairs.append({
                            "gen_a": g1,
                            "gen_b": g2,
                            "valence_a": round(v1, 3),
                            "valence_b": round(v2, 3),
                            "gap": round(gap, 3),
                            "co_count": rel.co_count,
                            "charge": rel.emotional_charge,
                        })

        pairs.sort(key=lambda p: -p["gap"])
        return pairs

    def suggest_stories(self, max_suggestions: int = 10) -> List[Dict]:
        """
        Предложить истории на основе эмоциональных контекстов.

        Логика:
          1. Gen с высокой позитивной валентностью → «расскажи ещё об этом»
          2. Gen с негативной валентностью → «расскажи как исправить»
          3. Parы с разной валентностью → «расскажи о конфликте»
          4. Редкие пары → «расскажи о встрече»
        """
        suggestions = []

        # 1. Позитивные Gen (хочется больше)
        for gen_id, vals in self._valence.items():
            avg = sum(vals) / len(vals) if vals else 0
            if avg > 0.5 and len(vals) >= 3:
                suggestions.append({
                    "type": "positive_repeat",
                    "gen_id": gen_id,
                    "valence": round(avg, 3),
                    "count": len(vals),
                    "question": f"Расскажи ещё историю, где этот паттерн повторяется "
                               f"(positive, valence={avg:.2f})",
                })

        # 2. Негативные Gen (хочется исправить)
        for gen_id, vals in self._valence.items():
            avg = sum(vals) / len(vals) if vals else 0
            if avg < -0.3 and len(vals) >= 2:
                suggestions.append({
                    "type": "negative_resolve",
                    "gen_id": gen_id,
                    "valence": round(avg, 3),
                    "count": len(vals),
                    "question": f"Расскажи историю, где этот конфликт разрешается "
                               f"(negative, valence={avg:.2f})",
                })

        # 3. Эмоциональные развилки
        unfamiliar = self.unfamiliar_pairs()
        for pair in unfamiliar[:5]:
            suggestions.append({
                "type": "emotional_fork",
                "pair": pair,
                "question": f"Расскажи историю, где {pair['gen_a']} и {pair['gen_b']} "
                           f"встречаются (gap={pair['gap']:.2f})",
            })

        suggestions.sort(key=lambda s: abs(s.get("valence", s.get("pair", {}).get("gap", 0))), reverse=True)
        return suggestions[:max_suggestions]

    # ------------------------------------------------------------------
    # Статистика
    # ------------------------------------------------------------------

    def stats(self) -> Dict:
        """Статистика эмоционального драйвера."""
        total_positive = sum(1 for e in self._entries if e.valence > 0.1)
        total_negative = sum(1 for e in self._entries if e.valence < -0.1)
        total_neutral = len(self._entries) - total_positive - total_negative

        avg_co = 0.0
        if self._relationships:
            avg_co = sum(r.co_count for r in self._relationships.values()) / len(self._relationships)

        return {
            "entries": len(self._entries),
            "unique_gens": len(self._valence),
            "unique_words": len(self._word_emotion),
            "relationships": len(self._relationships),
            "avg_co_occurrence": round(avg_co, 1),
            "positive": total_positive,
            "negative": total_negative,
            "neutral": total_neutral,
        }

    def __repr__(self) -> str:
        s = self.stats()
        return (
            f"EmotionDriver("
            f"entries={s['entries']}, "
            f"gens={s['unique_gens']}, "
            f"rels={s['relationships']})"
        )

    # ------------------------------------------------------------------
    # Интуиция: прогноз на основе паттернов
    # ------------------------------------------------------------------

    def predict_outcome(self, action: str, context: str = "") -> Dict:
        """
        Спрогнозировать последствие действия на основе паттернов.

        Например: predict_outcome("обидела") →
          {"action": "обидела", "likely_consequences": [
            {"word": "расстроился", "probability": 0.8, "valence": -0.5},
            {"word": "убежал", "probability": 0.6, "valence": -0.5},
          ], "overall_valence": -0.5, "confidence": 0.7}
        """
        action_lower = action.lower()

        # Найти все паттерны, где action = первый элемент
        consequences = []
        for (a, c), pat in self._action_patterns.items():
            if a == action_lower and pat["count"] >= 1:
                avg_v = pat["valence_sum"] / pat["count"]
                consequences.append({
                    "word": c,
                    "count": pat["count"],
                    "valence": round(avg_v, 3),
                })

        # Сортировать по частоте
        consequences.sort(key=lambda x: -x["count"])
        total = sum(c["count"] for c in consequences)

        if not consequences:
            return {
                "action": action,
                "likely_consequences": [],
                "overall_valence": 0.0,
                "confidence": 0.0,
                "message": "Нет данных о последствиях этого действия",
            }

        # Рассчитать общую валентность
        overall_v = sum(c["valence"] * c["count"] for c in consequences) / total

        # Вероятности
        for c in consequences:
            c["probability"] = round(c["count"] / total, 2)

        return {
            "action": action,
            "likely_consequences": consequences[:5],
            "overall_valence": round(overall_v, 3),
            "confidence": round(min(1.0, total / 10.0), 2),
        }

    def predict_sequence(self, word: str, n_next: int = 3) -> List[Dict]:
        """
        Спрогнозировать продолжение последовательности.

        Например: predict_sequence("маша") →
          [{"next": "пошла", "count": 5, "valence": 0.3},
           {"next": "помогла", "count": 3, "valence": 0.8}, ...]
        """
        word_lower = word.lower()
        next_words = self._sequence_patterns.get(word_lower, {})

        result = []
        for next_w, pat in next_words.items():
            if pat["count"] >= 1:
                avg_v = pat["valence_sum"] / pat["count"]
                result.append({
                    "next": next_w,
                    "count": pat["count"],
                    "valence": round(avg_v, 3),
                    "probability": 0.0,  # заполним ниже
                })

        result.sort(key=lambda x: -x["count"])
        total = sum(r["count"] for r in result)

        if total > 0:
            for r in result[:n_next]:
                r["probability"] = round(r["count"] / total, 2)

        return result[:n_next]

    def intuition_report(self, word: str) -> Dict:
        """
        Полный отчёт об интуиции для данного слова.

        Включает:
          - эмоциональную окраску
          - предсказание последствий
          - предсказание продолжения
          - рекомендацию (стоит ли продолжать взаимодействие)
        """
        valence = self.get_word_valence(word)
        prediction = self.predict_outcome(word)
        sequence = self.predict_sequence(word)

        # Рекомендация
        if valence > 0.3:
            recommendation = "Позитивное взаимодействие — стоит продолжать"
        elif valence < -0.3:
            recommendation = "Негативное взаимодействие — лучше избегать"
        else:
            recommendation = "Нейтрально — нужно больше данных"

        return {
            "word": word,
            "valence": round(valence, 3),
            "prediction": prediction,
            "sequence": sequence,
            "recommendation": recommendation,
        }
