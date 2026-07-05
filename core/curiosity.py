"""
core/curiosity.py — Движок любопытства: модель просит истории о персонажах.

Анализирует базу Gen и находит:
  1. «Опоры» — слова с высокой значимостью и малой длиной цепочки
     (персонажи и ключевые предметы)
  2. «Незнакомцы» — опоры, о которых мало известно (мало Gen)
  3. «Развилки» — точки бифуркации, где есть альтернативные продолжения

Генерирует structured queries для LLM:
  - «Расскажи историю с [персонаж]»
  - «Что [персонаж] делает в [ситуация]?»
  - «Какие ещё [предметы] встречались?»

Использование:
    engine = CharacterCuriosityEngine(base)
    anchors = engine.find_anchors()
    unfamiliar = engine.find_unfamiliar(anchors)
    questions = engine.generate_queries(anchors, unfamiliar)
"""
from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from core.generalization import GeneralizationBase, Generalization


# ══════════════════════════════════════════════════════════════════════
# Служебные слова (не персонажи)
# ══════════════════════════════════════════════════════════════════════

_SERVICE_WORDS = {
    "и", "в", "на", "с", "по", "за", "из", "не", "что", "это",
    "как", "он", "она", "оно", "они", "а", "но", "или", "то",
    "всё", "все", "был", "была", "были", "есть", "стал", "стала",
    "к", "до", "у", "о", "их", "от", "его", "её", "им", "ему",
    "бы", "ни", "же", "вот", "тут", "там", "где", "когда", "потом",
    "после", "перед", "между", "без", "над", "под", "про", "для",
    "так", "уже", "ещё", "еще", "тоже", "только", "даже", "вот",
    "да", "нет", "может", "будет", "было", "быть",
    "я", "ты", "мы", "вы",
}


# ══════════════════════════════════════════════════════════════════════
# Опора (Anchor) — слово-кандидат в персонажи/предметы
# ══════════════════════════════════════════════════════════════════════

@dataclass
class Anchor:
    """
    Опора — слово с высокой значимостью.

    word         — слово (lemma)
    significance — средняя значимость Gen, содержащих это слово
    gen_count    — сколько Gen содержат это слово
    avg_chain    — средняя длина цепочки Gen
    contexts     — список контекстов (в каких Gen встречается)
    is_unfamiliar — мало известно (gen_count < порога)
    """
    word: str
    significance: float
    gen_count: int
    avg_chain: float
    contexts: List[str] = field(default_factory=list)
    is_unfamiliar: bool = False


# ══════════════════════════════════════════════════════════════════════
# CharacterCuriosityEngine
# ══════════════════════════════════════════════════════════════════════

class CharacterCuriosityEngine:
    """
    Движок любопытства: анализирует базу Gen и генерирует вопросы.

    Алгоритм:
      1. Собрать все слова из Gen.label
      2. Рассчитать significance для каждого слова
      3. Отфильтровать служебные слова
      4. Определить unfamiliar (мало Gen, низкая связность)
      5. Сгенерировать structured queries для LLM

    Параметры
    ---------
    base                : GeneralizationBase  — база Gen
    min_significance    : float               — мин. значимость для опоры (0.5)
    min_gen_count       : int                 — мин. число Gen для «знакомства» (3)
    unfamiliar_threshold: float               — порог unfamiliarness (0.3)
    """

    def __init__(
        self,
        base: "GeneralizationBase",
        min_significance: float = 0.5,
        min_gen_count: int = 3,
        unfamiliar_threshold: float = 0.3,
    ) -> None:
        self._base = base
        self._min_significance = min_significance
        self._min_gen_count = min_gen_count
        self._unfamiliar_threshold = unfamiliar_threshold

    # ------------------------------------------------------------------
    # Поиск опор
    # ------------------------------------------------------------------

    def find_anchors(self) -> List[Anchor]:
        """
        Найти опоры — слова с высокой значимостью в базе Gen.

        Алгоритм:
          1. Для каждого Gen разбить label на слова
          2. Для каждого слова накопить: significance, gen_count, contexts
          3. Рассчитать среднюю significance
          4. Отфильтровать служебные слова
          5. Отсортировать по significance
        """
        word_stats: Dict[str, Dict] = defaultdict(lambda: {
            "total_sig": 0.0,
            "gen_count": 0,
            "chains": [],
            "contexts": [],
        })

        for gen in self._base.all():
            if not gen.label:
                continue
            if self._is_noise(gen.label):
                continue

            words = self._tokenize(gen.label)
            chain_len = len(gen.feature_chain)

            for word in words:
                if word in _SERVICE_WORDS or len(word) < 2:
                    continue

                stats = word_stats[word]
                stats["total_sig"] += gen.significance
                stats["gen_count"] += 1
                stats["chains"].append(chain_len)
                # Контекст = surrounding words
                idx = words.index(word)
                context = " ".join(words[max(0, idx - 2):idx + 3])
                if context not in stats["contexts"]:
                    stats["contexts"].append(context)

        anchors = []
        for word, stats in word_stats.items():
            if stats["gen_count"] == 0:
                continue

            avg_sig = stats["total_sig"] / stats["gen_count"]
            avg_chain = sum(stats["chains"]) / len(stats["chains"])

            if avg_sig < self._min_significance:
                continue

            is_unfamiliar = (
                stats["gen_count"] < self._min_gen_count
                or avg_sig < self._unfamiliar_threshold
            )

            anchors.append(Anchor(
                word=word,
                significance=round(avg_sig, 3),
                gen_count=stats["gen_count"],
                avg_chain=round(avg_chain, 1),
                contexts=stats["contexts"][:5],
                is_unfamiliar=is_unfamiliar,
            ))

        anchors.sort(key=lambda a: -a.significance)
        return anchors

    # ------------------------------------------------------------------
    # Поиск unfamiliar
    # ------------------------------------------------------------------

    def find_unfamiliar(self, anchors: Optional[List[Anchor]] = None) -> List[Anchor]:
        """
        Найти unfamiliar опоры — те, о которых мало известно.

        Критерии unfamiliarity:
          - gen_count < min_gen_count
          - significance < unfamiliar_threshold
          - мало контекстов (contexts < 2)
        """
        if anchors is None:
            anchors = self.find_anchors()

        return [
            a for a in anchors
            if a.is_unfamiliar
            or a.gen_count < self._min_gen_count
            or len(a.contexts) < 2
        ]

    # ------------------------------------------------------------------
    # Генерация запросов
    # ------------------------------------------------------------------

    def generate_queries(
        self,
        anchors: Optional[List[Anchor]] = None,
        unfamiliar: Optional[List[Anchor]] = None,
        max_queries: int = 10,
    ) -> List[Dict]:
        """
        Сгенерировать structured queries для LLM.

        Возвращает список:
          [{"type": "story_request", "target": "маша", "context": "...", "priority": 1}, ...]
        """
        if anchors is None:
            anchors = self.find_anchors()
        if unfamiliar is None:
            unfamiliar = self.find_unfamiliar(anchors)

        queries = []

        # 1. Запросы об unfamiliar персонажах (высокий приоритет)
        for a in unfamiliar[:5]:
            queries.append({
                "type": "story_request",
                "target": a.word,
                "context": f"Модель знает «{a.word}» из {a.gen_count} Gen, "
                           f"но хочет узнать больше. "
                           f"Контекст: {'; '.join(a.contexts[:2])}",
                "priority": 1,
                "question": f"Расскажи историю, где «{a.word}» играет главную роль",
            })

        # 2. Запросы о familiar персонажах в новых ситуациях
        familiar = [a for a in anchors if not a.is_unfamiliar][:5]
        for a in familiar:
            queries.append({
                "type": "new_situation",
                "target": a.word,
                "context": f"Модель хорошо знает «{a.word}» ({a.gen_count} Gen, "
                           f"sig={a.significance}). "
                           f"Хочет узнать: что {a.word} делает в других ситуациях?",
                "priority": 2,
                "question": f"Расскажи историю, где «{a.word}» оказывается в новой ситуации",
            })

        # 3. Вопросы о связях между опорами
        if len(anchors) >= 2:
            top = anchors[:min(6, len(anchors))]
            for i in range(len(top)):
                for j in range(i + 1, min(i + 3, len(top))):
                    a1, a2 = top[i], top[j]
                    queries.append({
                        "type": "relationship",
                        "target": f"{a1.word} + {a2.word}",
                        "context": f"Оба персонажа известны модели. "
                                   f"Что происходит, когда они встречаются?",
                        "priority": 3,
                        "question": f"Расскажи историю, где «{a1.word}» и «{a2.word}» встречаются",
                    })

        queries.sort(key=lambda q: q["priority"])
        return queries[:max_queries]

    # ------------------------------------------------------------------
    # Навигация по гетерархии
    # ------------------------------------------------------------------

    def hierarchy_path(self, word: str) -> List[Dict]:
        """
        Найти путь от корня до слова в гетерархии.

        Возвращает список Gen, образующих путь:
          [{"gen_id": "...", "label": "...", "chain_len": N, "sig": 0.95}, ...]
        """
        path = []
        for gen in sorted(self._base.all(), key=lambda g: len(g.feature_chain)):
            if gen.label and word in gen.label.lower():
                path.append({
                    "gen_id": gen.gen_id[:8],
                    "label": gen.label,
                    "chain_len": len(gen.feature_chain),
                    "sig": round(gen.significance, 3),
                    "children": len(gen.child_ids),
                    "parents": len(gen.parent_ids),
                })
        return path

    def branch_variants(self, word: str) -> List[Dict]:
        """
        Найти альтернативы на развилке для данного слова.

        Ищет Gen, которые содержат слово и имеют child_ids —
        это развилки, где есть альтернативные продолжения.
        """
        variants = []
        for gen in self._base.all():
            if not gen.label or word not in gen.label.lower():
                continue
            if not gen.child_ids:
                continue

            child_info = []
            for cid in gen.child_ids:
                child = self._base.get(cid)
                if child:
                    child_info.append({
                        "gen_id": child.gen_id[:8],
                        "label": child.label or "?",
                        "sig": round(child.significance, 3),
                    })

            if child_info:
                variants.append({
                    "parent": gen.label,
                    "chain_len": len(gen.feature_chain),
                    "variants": child_info,
                })

        return variants

    # ------------------------------------------------------------------
    # Статистика
    # ------------------------------------------------------------------

    def stats(self) -> Dict:
        """Статистика движка любопытства."""
        anchors = self.find_anchors()
        unfamiliar = self.find_unfamiliar(anchors)
        return {
            "total_anchors": len(anchors),
            "unfamiliar_count": len(unfamiliar),
            "familiar_count": len(anchors) - len(unfamiliar),
            "top_anchors": [(a.word, a.significance, a.gen_count) for a in anchors[:10]],
            "unfamiliar_words": [a.word for a in unfamiliar[:10]],
        }

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        """Токенизация: нижний регистр, разделители."""
        return [
            w.lower() for w in re.split(r"[\s·\-\—\–\,\.\!\?\"\'«»]+", text)
            if len(w) >= 2
        ]

    @staticmethod
    def _is_noise(label: str) -> bool:
        """Проверить, является ли метка шумом (auto_*, fork_*, meta_*)."""
        if not label:
            return True
        if label.startswith("auto_"):
            return True
        if label.startswith("fork_"):
            return True
        if label.startswith("meta_"):
            return True
        if label.startswith("consolidated_"):
            return True
        # Слишком короткая или бессмысленная
        if len(label) < 3:
            return True
        return False

    def __repr__(self) -> str:
        anchors = self.find_anchors()
        unfamiliar = self.find_unfamiliar(anchors)
        return (
            f"CharacterCuriosityEngine("
            f"anchors={len(anchors)}, "
            f"unfamiliar={len(unfamiliar)})"
        )
