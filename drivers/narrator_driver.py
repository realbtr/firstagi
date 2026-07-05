"""
NarratorDriver — активная фаза: модель рассказывает о том, что знает.

Четыре уровня творчества:
  RECALL  (0) — точное воспроизведение: жадный путь по максимальному весу
  RETELL  (1) — пересказ: softmax с температурой, топ-3 кандидата
  COMPOSE (2) — свободное сочинение: BFS между персонажами / доменами
  DREAM   (3) — творческая аналогия: исследование малозначимых рёбер

Компоненты:
  WordGraph          — граф слов, построенный из Gen.label
  CharacterExtractor — профили персонажей из Gen-структуры
  NarratorDriver     — генератор нарративов с CreativityLevel
  GapQuestionGenerator — вопросы о пробелах знания
  NarratorBridge     — связывает SpeechDriver с WordGraph

Использование:
    from drivers.narrator_driver import NarratorDriver, CreativityLevel
    narrator = NarratorDriver(system.base)
    result = narrator.generate(CreativityLevel.RETELL, start_word="муми-тролль")
    print(result.text)
    for q in result.questions:
        print(q)
"""
from __future__ import annotations

import math
import random
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from core.generalization import GeneralizationBase, Generalization


# ══════════════════════════════════════════════════════════════════════
# CreativityLevel
# ══════════════════════════════════════════════════════════════════════

class CreativityLevel(Enum):
    """Уровень творчества: от точного воспроизведения до свободной аналогии."""
    RECALL  = 0   # точное воспроизведение
    RETELL  = 1   # пересказ, softmax top-3
    COMPOSE = 2   # свободное сочинение, BFS через домены
    DREAM   = 3   # творческая аналогия, малозначимые рёбра


# ══════════════════════════════════════════════════════════════════════
# WordNode
# ══════════════════════════════════════════════════════════════════════

@dataclass
class WordNode:
    """Узел WordGraph — слово с накопленной статистикой из Gen."""
    word: str
    total_significance: float = 0.0
    occurrence_count:   int   = 0
    gen_ids:            List[str] = field(default_factory=list)

    @property
    def avg_significance(self) -> float:
        if self.occurrence_count == 0:
            return 0.0
        return self.total_significance / self.occurrence_count

    def add_gen(self, gen_id: str, significance: float) -> None:
        self.gen_ids.append(gen_id)
        self.total_significance += significance
        self.occurrence_count += 1


# ══════════════════════════════════════════════════════════════════════
# WordGraph
# ══════════════════════════════════════════════════════════════════════

class WordGraph:
    """
    Граф слов, построенный из Gen.label.

    Узлы:   слова (из Gen.label)
    Рёбра:  биграммы переходов word_i → word_{i+1}
    Вес:    сумма Gen.significance по всем Gen, содержащим данный переход

    Label-формат поддерживается:
      «муми·тролль·живёт»           — TextDriver (разделитель ·)
      «слово|p=N|h=X.X|role=theme»  — SmartTextDriver (берём первую часть до |)
    """

    def __init__(self) -> None:
        # node_word → WordNode
        self._nodes: Dict[str, WordNode] = {}
        # (src_word, dst_word) → суммарный вес
        self._edges: Dict[Tuple[str, str], float] = {}
        # word → список (dst, weight) для быстрого lookup (исходящие рёбра)
        self._out: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        # word → список (src, weight) для быстрого lookup (входящие рёбра)
        self._in:  Dict[str, List[Tuple[str, float]]] = defaultdict(list)
        self._built = False

    # ── Построение ────────────────────────────────────────────────────

    @staticmethod
    def build(base: "GeneralizationBase", min_significance: float = 0.0) -> "WordGraph":
        """Построить граф из GeneralizationBase."""
        g = WordGraph()
        for gen in base.all():
            if gen.label is None:
                continue
            # Пропускаем системные авто-метки вроде "fork_l4", "auto_12" и т.п.
            if re.match(r"^(fork_|auto_|gen_)\w+$", gen.label):
                continue
            sig = gen.significance
            if sig < min_significance:
                continue
            words = WordGraph._parse_label(gen.label)
            if not words:
                continue
            # Обновляем узлы
            for w in words:
                if w not in g._nodes:
                    g._nodes[w] = WordNode(word=w)
                g._nodes[w].add_gen(gen.gen_id, sig)
            # Обновляем рёбра (биграммы)
            for i in range(len(words) - 1):
                src, dst = words[i], words[i + 1]
                key = (src, dst)
                g._edges[key] = g._edges.get(key, 0.0) + sig
        # Строим индексы исходящих и входящих рёбер
        for (src, dst), w in g._edges.items():
            g._out[src].append((dst, w))
            g._in[dst].append((src, w))
        for src in g._out:
            g._out[src].sort(key=lambda x: -x[1])
        for dst in g._in:
            g._in[dst].sort(key=lambda x: -x[1])
        g._built = True
        return g

    @staticmethod
    def _parse_label(label: str) -> List[str]:
        """
        Разбить метку Gen на список слов.

        Форматы:
          «w0·w1·w2»            → ["w0", "w1", "w2"]
          «w0|p=N|h=X»         → ["w0"]
          «w0·w1|p=N|h=X·w2»   → разбиваем по · затем берём часть до |
        """
        # Сначала разбиваем по · (separator TextDriver)
        parts = label.split("·")
        words = []
        for p in parts:
            # Убираем SmartTextDriver-суффиксы вида |p=...|h=...|role=...
            clean = p.split("|")[0].strip()
            if clean:
                words.append(clean.lower())
        return words

    # ── Навигация ─────────────────────────────────────────────────────

    def neighbors(self, word: str, top_n: int = 5) -> List[Tuple[str, float]]:
        """Топ-N соседей (исходящие рёбра) для слова, отсортированных по весу."""
        return self._out.get(word.lower(), [])[:top_n]

    def has_node(self, word: str) -> bool:
        return word.lower() in self._nodes

    def node(self, word: str) -> Optional[WordNode]:
        return self._nodes.get(word.lower())

    def all_words(self) -> List[str]:
        return list(self._nodes.keys())

    def high_significance_words(self, top_n: int = 20) -> List[WordNode]:
        """Слова с наибольшей средней значимостью."""
        nodes = sorted(self._nodes.values(), key=lambda n: -n.avg_significance)
        return nodes[:top_n]

    def edge_weight(self, src: str, dst: str) -> float:
        return self._edges.get((src.lower(), dst.lower()), 0.0)

    def degree(self, word: str) -> int:
        """Число исходящих рёбер."""
        return len(self._out.get(word.lower(), []))

    def predecessors(self, word: str, top_n: int = 5) -> List[Tuple[str, float]]:
        """Топ-N предшественников (входящие рёбра) по убыванию веса."""
        return self._in.get(word.lower(), [])[:top_n]

    def in_degree(self, word: str) -> int:
        """Число входящих рёбер."""
        return len(self._in.get(word.lower(), []))


# ══════════════════════════════════════════════════════════════════════
# CharacterProfile
# ══════════════════════════════════════════════════════════════════════

@dataclass
class CharacterProfile:
    """Профиль персонажа, извлечённый из Gen-структуры."""
    name:              str
    significance:      float          # средняя значимость Gen с этим именем
    typical_actions:   List[str]      # глаголы/действия после имени
    typical_contexts:  List[str]      # слова-контексты, встречающиеся рядом
    gen_count:         int            = 0
    is_protagonist:    bool           = False  # True если имя встречается >10 раз

    def __str__(self) -> str:
        actions = ", ".join(self.typical_actions[:3]) or "—"
        ctx     = ", ".join(self.typical_contexts[:3]) or "—"
        star    = "★" if self.is_protagonist else " "
        return (
            f"{star} {self.name:<20s} sig={self.significance:.3f}  "
            f"gen={self.gen_count}  actions=[{actions}]  ctx=[{ctx}]"
        )


# ══════════════════════════════════════════════════════════════════════
# CharacterExtractor
# ══════════════════════════════════════════════════════════════════════

# Список известных персонажей для эвристики
_KNOWN_MOOMIN = {
    "муми-тролль", "муми-мама", "муми-папа", "снусмумрик",
    "малышка", "мю", "снорочка", "снорк", "хемуль", "морра",
    "хатифнатты", "филифьонка",
}
_KNOWN_WINNIE = {
    "винни-пух", "пух", "пятачок", "тигруля", "иа", "кролик",
    "сова", "кенга", "ру", "кристофер",
}

_ALL_KNOWN = _KNOWN_MOOMIN | _KNOWN_WINNIE


class CharacterExtractor:
    """
    Извлекает профили персонажей из WordGraph.

    Эвристика:
      1. Слова из _ALL_KNOWN — прямое имя персонажа.
      2. Узел с avg_significance > threshold — возможный персонаж.
      3. Действия = слова, идущие сразу после имени в WordGraph.
      4. Контекст = все соседи имени (любые слова рядом).
    """

    def __init__(self, graph: WordGraph, sig_threshold: float = 0.7) -> None:
        self._graph = graph
        self._threshold = sig_threshold

    def extract(self, max_profiles: int = 20) -> List[CharacterProfile]:
        """Извлечь список персонажей, отсортированных по значимости."""
        profiles: Dict[str, CharacterProfile] = {}

        for word, node in self._graph._nodes.items():
            # Проверяем: известный персонаж ИЛИ кандидат-персонаж
            is_known = word in _ALL_KNOWN
            # Кандидат: высокая значимость + многократное использование +
            # не является служебным/функциональным словом
            is_candidate = (
                node.avg_significance >= self._threshold
                and node.occurrence_count >= 5
                and not self._is_function_word(word)
                and len(word) >= 4  # короткие слова (и, в, на) не персонажи
            )
            if not (is_known or is_candidate):
                continue

            neighbors = self._graph.neighbors(word, top_n=8)
            actions  = [w for w, _ in neighbors if self._is_action(w)][:5]
            contexts = [w for w, _ in neighbors if not self._is_action(w)][:5]

            profiles[word] = CharacterProfile(
                name=word,
                significance=node.avg_significance,
                typical_actions=actions,
                typical_contexts=contexts,
                gen_count=node.occurrence_count,
                is_protagonist=node.occurrence_count >= 10,
            )

        result = sorted(profiles.values(), key=lambda p: -p.significance)
        return result[:max_profiles]

    def relationship(self, char_a: str, char_b: str) -> Optional[float]:
        """
        Сила связи между двумя персонажами = вес ребра char_a→char_b
        (или среднее в обе стороны).
        """
        a = char_a.lower()
        b = char_b.lower()
        w1 = self._graph.edge_weight(a, b)
        w2 = self._graph.edge_weight(b, a)
        if w1 == 0.0 and w2 == 0.0:
            return None
        return (w1 + w2) / 2.0

    @staticmethod
    def _is_function_word(word: str) -> bool:
        """Вернуть True для служебных/очень частых функциональных слов."""
        return word in {
            "занят", "длинная", "всем", "очень", "приходит", "долгую", "зиму",
            "всю", "пахнет", "доме", "тепло", "всех", "даже", "тоже",
            "этот", "этого", "этой", "такой", "такая", "такие",
            "всегда", "никогда", "иногда", "просто", "только", "самый",
            "каждый", "каждая", "весну", "осенью", "зимой",
        }

    @staticmethod
    def _is_action(word: str) -> bool:
        """
        Простая эвристика: слово является действием, если оканчивается
        на типичные русские глагольные суффиксы или это инфинитив.
        """
        return bool(re.search(
            r"(ет|ит|ют|ят|ёт|ал|ала|ает|яет|ить|ать|еть|оть|"
            r"ится|ется|идёт|шёл|шла|ждёт|стоит|живёт|носит|пишет|"
            r"любит|говорит|боится|хочет|знает|видит|играет|собирал|"
            r"строил|нашёл|нашла|уходит|приходит|спит|проснулся)$",
            word
        ))


# ══════════════════════════════════════════════════════════════════════
# NarrativeSegment & NarrativeResult
# ══════════════════════════════════════════════════════════════════════

@dataclass
class NarrativeSegment:
    """Один сегмент нарратива — слово + откуда оно взято."""
    word:       str
    weight:     float   # вес перехода (0 = начало / фантазия)
    is_bridge:  bool = False  # True = «мостик» между доменами (COMPOSE/DREAM)


@dataclass
class NarrativeResult:
    """Результат генерации нарратива."""
    text:                str
    segments:            List[NarrativeSegment]
    questions:           List[str]
    characters_mentioned: List[str]
    coherence_score:     float   # [0, 1]: насколько путь «связный» (по средн. весу)
    creativity_level:    CreativityLevel = CreativityLevel.RECALL

    def __str__(self) -> str:
        return (
            f"[{self.creativity_level.name}] «{self.text}»\n"
            f"  coherence={self.coherence_score:.3f}  "
            f"chars={self.characters_mentioned}\n"
            + (f"  ? {chr(10).join(self.questions)}" if self.questions else "")
        )


# ══════════════════════════════════════════════════════════════════════
# GapQuestionGenerator
# ══════════════════════════════════════════════════════════════════════

class GapQuestionGenerator:
    """
    Генератор вопросов о пробелах знания.

    Пробелы обнаруживаются двумя способами:
      1. Слова с высокой значимостью, у которых нет исходящих рёбер
         (знаем слово, не знаем что за ним)
      2. Пары (персонаж, действие) с низким весом — слабо подкреплённая связь
    """

    def __init__(self, graph: WordGraph, extractor: CharacterExtractor) -> None:
        self._graph = graph
        self._extractor = extractor

    def generate(
        self,
        max_questions: int = 10,
        min_node_sig: float = 0.5,
    ) -> List[str]:
        """Сформулировать вопросы о пробелах знания."""
        questions: List[str] = []

        # 1. Слова без продолжений (не функциональные слова, длина ≥ 4)
        for node in self._graph.high_significance_words(top_n=50):
            if node.avg_significance < min_node_sig:
                break
            if self._graph.degree(node.word) == 0:
                if self._is_filler(node.word) or len(node.word) < 4:
                    continue
                q = self._formulate_dead_end_question(node.word)
                if q:
                    questions.append(q)
            if len(questions) >= max_questions // 2:
                break

        # 2. Слабо подкреплённые переходы от персонажей
        profiles = self._extractor.extract(max_profiles=10)
        for profile in profiles:
            neighbors = self._graph.neighbors(profile.name, top_n=5)
            weak = [
                (dst, w) for dst, w in neighbors
                if w < 0.3 and not self._is_filler(dst)
            ]
            for dst, w in weak[:2]:
                q = f"Что происходит, когда {profile.name} встречает «{dst}»?"
                questions.append(q)
            if len(questions) >= max_questions:
                break

        return questions[:max_questions]

    @staticmethod
    def _formulate_dead_end_question(word: str) -> Optional[str]:
        templates = [
            f"Что делает {word} дальше?",
            f"Что происходит с {word}?",
            f"Куда идёт {word}?",
            f"Почему {word}?",
        ]
        # Выбираем шаблон детерминированно по слову
        idx = sum(ord(c) for c in word) % len(templates)
        return templates[idx]

    @staticmethod
    def _is_filler(word: str) -> bool:
        """Служебные слова, не несущие смысла для вопроса."""
        return word in {
            "и", "в", "на", "у", "к", "с", "а", "но", "он", "она",
            "они", "это", "то", "все", "всё", "не", "по", "за", "из",
            "что", "как", "его", "её", "их",
        }


# ══════════════════════════════════════════════════════════════════════
# UnnamedClusterDetector
# ══════════════════════════════════════════════════════════════════════

class UnnamedClusterDetector:
    """
    Находит родительские Gen без label (безымянные кластеры), у которых
    ≥ min_children потомков с осмысленными метками.

    Генерирует вопросы вида «Как называется группа: морковка, мёд, пирог?»

    Пример: parent Gen (label=None) → children: "морковка", "мёд", "пирог", "ягоды"
    → Вопрос: «Как называется группа: морковка, мёд, пирог, ягоды?»

    Применение:
        detector = UnnamedClusterDetector(system.base, min_children=3)
        for q in detector.detect():
            print(q)
    """

    def __init__(self, base: "GeneralizationBase", min_children: int = 3) -> None:
        self._base = base
        self._min_children = min_children

    def detect(self, max_questions: int = 10) -> List[str]:
        """Вернуть список вопросов об именах безымянных кластеров."""
        questions: List[str] = []
        seen: Set[str] = set()

        for gen in self._base.all():
            # Ищем безымянных родителей
            if gen.label is not None:
                continue
            if len(gen.child_ids) < self._min_children:
                continue

            # Собираем терминальные слова из меток детей
            child_terms: List[str] = []
            for cid in gen.child_ids:
                child = self._base.get(cid)
                if child is None or child.label is None:
                    continue
                label = child.label
                if re.match(r"^(fork_|auto_|gen_)\w+$", label):
                    continue
                words = WordGraph._parse_label(label)
                if words:
                    # Берём последнее слово (самый конкретный термин)
                    term = words[-1]
                    if len(term) >= 3 and term not in child_terms:
                        child_terms.append(term)

            if len(child_terms) < self._min_children:
                continue

            key = frozenset(child_terms[:6])
            if key in seen:
                continue
            seen.add(key)

            sample = ", ".join(child_terms[:6])
            questions.append(f"Как называется группа: {sample}?")

            if len(questions) >= max_questions:
                break

        return questions

    def name_cluster(
        self,
        gen_id: str,
        name: str,
    ) -> bool:
        """
        Назначить имя безымянному Gen (ответ учителя на вопрос detect()).
        Возвращает True если Gen найден и обновлён.
        """
        gen = self._base.get(gen_id)
        if gen is None:
            return False
        gen.label = name
        return True

    def find_unnamed_parents(self, min_children: int = 3) -> List["Generalization"]:
        """Список безымянных Gen-родителей с числом детей ≥ min_children."""
        result = []
        for gen in self._base.all():
            if gen.label is None and len(gen.child_ids) >= min_children:
                result.append(gen)
        result.sort(key=lambda g: -len(g.child_ids))
        return result


# ══════════════════════════════════════════════════════════════════════
# NarratorDriver
# ══════════════════════════════════════════════════════════════════════

class NarratorDriver:
    """
    Главный нарратор — генерирует тексты из знаний модели.

    Работает с WordGraph (строит из GeneralizationBase при создании).
    Поддерживает четыре уровня творчества (CreativityLevel).

    Параметры
    ----------
    base          : GeneralizationBase — база обобщений
    min_sig       : float — минимальная значимость для включения Gen в граф
    seed          : Optional[int] — seed для воспроизводимости (None = случайный)
    """

    # Температуры для softmax по уровням творчества
    _TEMPERATURES = {
        CreativityLevel.RECALL:  0.0,   # детерминированный (greedy)
        CreativityLevel.RETELL:  0.5,   # мягкий softmax
        CreativityLevel.COMPOSE: 1.2,   # ослабленный
        CreativityLevel.DREAM:   2.5,   # почти случайный
    }

    def __init__(
        self,
        base: "GeneralizationBase",
        min_sig: float = 0.0,
        seed: Optional[int] = None,
    ) -> None:
        self._base = base
        self._graph = WordGraph.build(base, min_significance=min_sig)
        self._extractor = CharacterExtractor(self._graph)
        self._gap_gen = GapQuestionGenerator(self._graph, self._extractor)
        self._rng = random.Random(seed)

    # ── Публичный API ─────────────────────────────────────────────────

    def rebuild_graph(self, min_sig: float = 0.0) -> None:
        """Пересобрать граф после обновления базы."""
        self._graph = WordGraph.build(self._base, min_significance=min_sig)
        self._extractor = CharacterExtractor(self._graph)
        self._gap_gen = GapQuestionGenerator(self._graph, self._extractor)

    def generate(
        self,
        creativity: CreativityLevel = CreativityLevel.RETELL,
        start_word: Optional[str] = None,
        max_words: int = 15,
        topic_hint: Optional[str] = None,
    ) -> NarrativeResult:
        """
        Сгенерировать нарратив.

        Parameters
        ----------
        creativity  : уровень творчества
        start_word  : стартовое слово (None = выбирается автоматически)
        max_words   : максимальное число слов в тексте
        topic_hint  : слово-тема для направления (COMPOSE/DREAM)
        """
        start = self._resolve_start(start_word, creativity)
        if start is None:
            return self._empty_result(creativity)

        segments = self._walk(start, creativity, max_words, topic_hint)
        text     = self._segments_to_text(segments)
        chars    = self._extract_mentioned_chars(segments)
        coherence = self._coherence(segments)
        questions = self._gap_gen.generate(max_questions=5)

        return NarrativeResult(
            text=text,
            segments=segments,
            questions=questions,
            characters_mentioned=chars,
            coherence_score=coherence,
            creativity_level=creativity,
        )

    def generate_about_character(
        self,
        character_name: str,
        creativity: CreativityLevel = CreativityLevel.RETELL,
        max_words: int = 15,
    ) -> NarrativeResult:
        """Сгенерировать нарратив про конкретного персонажа."""
        name = character_name.lower()
        if not self._graph.has_node(name):
            # Ищем ближайшее совпадение
            candidates = [w for w in self._graph.all_words() if name in w or w in name]
            name = candidates[0] if candidates else name
        return self.generate(creativity, start_word=name, max_words=max_words)

    def generate_cross_domain(
        self,
        char_a: str,
        char_b: str,
        max_words: int = 20,
    ) -> NarrativeResult:
        """
        Сгенерировать «мостик» между двумя персонажами (COMPOSE-уровень).
        BFS от char_a до char_b, затем дописываем от char_b.
        """
        path = self._bfs_path(char_a.lower(), char_b.lower(), max_hops=8)
        if not path:
            path = [char_a.lower(), char_b.lower()]

        segments: List[NarrativeSegment] = []
        for i, w in enumerate(path):
            is_bridge = (i > 0 and i < len(path) - 1)
            w_prev = path[i - 1] if i > 0 else None
            weight = self._graph.edge_weight(w_prev, w) if w_prev else 0.0
            segments.append(NarrativeSegment(word=w, weight=weight, is_bridge=is_bridge))

        # Дописываем от char_b
        tail = self._walk(
            char_b.lower(),
            CreativityLevel.COMPOSE,
            max_words - len(segments),
            topic_hint=None,
        )
        segments.extend(tail[1:])  # пропускаем первый (уже есть char_b)

        text     = self._segments_to_text(segments)
        chars    = self._extract_mentioned_chars(segments)
        coherence = self._coherence(segments)
        questions = self._gap_gen.generate(max_questions=3)

        return NarrativeResult(
            text=text,
            segments=segments,
            questions=questions,
            characters_mentioned=chars,
            coherence_score=coherence,
            creativity_level=CreativityLevel.COMPOSE,
        )

    def what_i_know_about(self, word: str, top_n: int = 10) -> List[str]:
        """
        Вернуть список «знаний» о слове — ближайшие слова из графа,
        отсортированные по весу.

        Поддерживает дефисные слова и частичное совпадение.
        """
        key = word.lower()
        if not self._graph.has_node(key):
            # Части через дефис
            for part in key.split("-"):
                if part and self._graph.has_node(part):
                    key = part
                    break
            else:
                # Частичное совпадение
                for w in self._graph.all_words():
                    if key in w or w in key:
                        key = w
                        break
        neighbors = self._graph.neighbors(key, top_n=top_n)
        return [w for w, _ in neighbors]

    def character_profiles(self, max_profiles: int = 15) -> List[CharacterProfile]:
        """Извлечь профили персонажей."""
        return self._extractor.extract(max_profiles=max_profiles)

    def knowledge_gaps(self, max_questions: int = 10) -> List[str]:
        """Вернуть список вопросов о пробелах знания."""
        return self._gap_gen.generate(max_questions=max_questions)

    def pattern_questions(self, max_questions: int = 10) -> List[str]:
        """
        Вопросы-расширения паттернов — «почемучка».

        Находит «мостовые» слова (in_degree ≥ 2 AND out_degree ≥ 2) — слова,
        которые соединяют многих «отправителей» с многими «получателями»
        (как правило, глаголы: «ест», «нашёл», «угостил»).

        Для каждого моста генерирует:
          • «Что {verb} {agent}?»      — для агентов без известных объектов
          • «Кто ещё {verb} {object}?» — расширяем список субъектов
          • «Что ещё {agent} {verb}?»  — расширяем список объектов

        Пример:
          граф знает: заяц→ест→морковку, медведь→ест→мёд
          pattern_questions() → ["Что ест лиса?", "Кто ещё ест морковку?",
                                  "Что ещё заяц ест?", ...]
        """
        graph = self._graph
        questions: List[str] = []
        seen: Set[str] = set()

        # 1. Найти мостовые слова (in ≥ 2, out ≥ 2, не стоп-слово, len ≥ 3)
        bridges = [
            (w, graph.in_degree(w) + graph.degree(w))
            for w in graph.all_words()
            if graph.in_degree(w) >= 2
            and graph.degree(w) >= 2
            and len(w) >= 3
            and not GapQuestionGenerator._is_filler(w)
        ]
        bridges.sort(key=lambda x: -x[1])

        for bridge_word, _ in bridges[:8]:
            agents  = [w for w, _ in graph.predecessors(bridge_word, top_n=5)]
            objects = [w for w, _ in graph.neighbors(bridge_word, top_n=5)]

            # «Что {verb} {agent}?» — для агентов с малым кол-вом исходящих
            for agent in agents[:3]:
                if len(graph.neighbors(agent)) < 2:
                    q = f"Что {bridge_word} {agent}?"
                    if q not in seen:
                        seen.add(q)
                        questions.append(q)

            # «Кто ещё {verb} {object}?»
            for obj in objects[:2]:
                if len(obj) >= 3 and not GapQuestionGenerator._is_filler(obj):
                    q = f"Кто ещё {bridge_word} {obj}?"
                    if q not in seen:
                        seen.add(q)
                        questions.append(q)

            # «Что ещё {agent} {verb}?» — для первого агента
            if agents:
                q = f"Что ещё {agents[0]} {bridge_word}?"
                if q not in seen:
                    seen.add(q)
                    questions.append(q)

            if len(questions) >= max_questions:
                break

        return questions[:max_questions]

    def voiced_questions(
        self,
        questions: Optional[List[str]] = None,
        max_questions: int = 10,
        max_chars: int = 3,
        seed: Optional[int] = None,
    ) -> List[str]:
        """
        Переформулировать вопросы о пробелах знания в голосах персонажей.

        Объединяет knowledge_gaps() + pattern_questions(), затем пропускает
        через CharacterVoice — каждый вопрос звучит как реплика персонажа.

        Parameters
        ----------
        questions     : готовый список вопросов (None = генерировать автоматически)
        max_questions : сколько вопросов генерировать (если questions=None)
        max_chars     : сколько персонажей «говорят» (голоса чередуются)
        seed          : seed для воспроизводимости шаблонов

        Returns
        -------
        Список реплик в голосах персонажей.

        Пример::

            narrator = NarratorDriver(system.base)
            for line in narrator.voiced_questions(max_chars=2):
                print(line)
            # — Что делает медведь дальше? — думал Винни, шагая вперёд.
            # — Кто ещё ест мёд? — тихо спросил Пятачок.
        """
        if questions is None:
            gap_qs     = self._gap_gen.generate(max_questions=max_questions // 2 + 1)
            pattern_qs = self.pattern_questions(max_questions=max_questions // 2 + 1)
            questions  = (gap_qs + pattern_qs)[:max_questions]

        if not questions:
            return []

        profiles = self._extractor.extract(max_profiles=max_chars)
        if not profiles:
            return questions[:]

        voice = CharacterVoice(profiles, seed=seed)
        return voice.voice_questions(questions, max_chars=max_chars)

    def unnamed_clusters(self, min_children: int = 3, max_questions: int = 8) -> List[str]:
        """
        Вопросы о безымянных категориях.
        Делегирует в UnnamedClusterDetector.

        Пример: «Как называется группа: морковка, мёд, пирог, ягоды?»
        """
        detector = UnnamedClusterDetector(self._base, min_children=min_children)
        return detector.detect(max_questions=max_questions)

    # ── Внутренняя логика ─────────────────────────────────────────────

    def _walk(
        self,
        start: str,
        creativity: CreativityLevel,
        max_words: int,
        topic_hint: Optional[str],
    ) -> List[NarrativeSegment]:
        """Пройти по графу, генерируя список сегментов."""
        segments: List[NarrativeSegment] = [
            NarrativeSegment(word=start, weight=1.0)
        ]
        visited: Set[str] = {start}
        current = start
        temp = self._TEMPERATURES[creativity]

        for _ in range(max_words - 1):
            nbs = self._graph.neighbors(current, top_n=10)
            if not nbs:
                break

            # При DREAM: подмешиваем случайные слова с низкой значимостью
            if creativity == CreativityLevel.DREAM:
                nbs = self._dream_expand(nbs, current, visited)

            # RECALL/RETELL: останавливаемся, если все соседи уже посещены
            if creativity.value <= CreativityLevel.RETELL.value:
                unvisited = [(w, wt) for w, wt in nbs if w not in visited]
                if not unvisited:
                    break
                nbs = unvisited

            # Выбираем следующее слово
            next_word, weight = self._pick(nbs, temp, creativity, topic_hint, visited)
            if next_word is None:
                break

            is_bridge = (next_word not in visited and creativity.value >= CreativityLevel.COMPOSE.value)
            segments.append(NarrativeSegment(word=next_word, weight=weight, is_bridge=is_bridge))
            visited.add(next_word)
            current = next_word

        return segments

    def _pick(
        self,
        candidates: List[Tuple[str, float]],
        temperature: float,
        creativity: CreativityLevel,
        topic_hint: Optional[str],
        visited: Set[str],
    ) -> Tuple[Optional[str], float]:
        """Выбрать следующее слово по уровню творчества."""
        if not candidates:
            return None, 0.0

        # Greedy (RECALL, temp=0)
        if temperature == 0.0:
            return candidates[0]

        # Взвешиваем по topic_hint — усиливаем слова, близкие к теме
        if topic_hint:
            hint = topic_hint.lower()
            candidates = [
                (w, wt * (1.5 if hint in w or w in hint else 1.0))
                for w, wt in candidates
            ]

        # При COMPOSE/DREAM — штрафуем уже посещённые
        if creativity.value >= CreativityLevel.COMPOSE.value:
            candidates = [
                (w, wt * (0.1 if w in visited else 1.0))
                for w, wt in candidates
            ]

        words, weights = zip(*candidates)
        weights = list(weights)

        # softmax с температурой
        probs = _softmax(weights, temperature)
        idx   = self._rng.choices(range(len(words)), weights=probs, k=1)[0]
        return words[idx], weights[idx]

    def _dream_expand(
        self,
        nbs: List[Tuple[str, float]],
        current: str,
        visited: Set[str],
    ) -> List[Tuple[str, float]]:
        """
        DREAM: добавляем слова из графа с низкой значимостью
        (исследуем малоизученные связи).
        """
        all_words = self._graph.all_words()
        random_sample = self._rng.sample(all_words, min(5, len(all_words)))
        extras = []
        for w in random_sample:
            if w not in visited:
                node = self._graph.node(w)
                sig  = node.avg_significance if node else 0.01
                # Усиливаем малозначимые слова (исследование)
                extras.append((w, max(0.01, (1.0 - sig) * 0.3)))
        return nbs + extras

    def _bfs_path(self, src: str, dst: str, max_hops: int = 8) -> List[str]:
        """BFS от src до dst в WordGraph. Возвращает путь или []."""
        if src == dst:
            return [src]
        if not self._graph.has_node(src) or not self._graph.has_node(dst):
            return []

        from collections import deque
        queue: deque = deque([[src]])
        visited: Set[str] = {src}

        while queue:
            path = queue.popleft()
            if len(path) > max_hops:
                break
            for nxt, _ in self._graph.neighbors(path[-1], top_n=5):
                if nxt == dst:
                    return path + [nxt]
                if nxt not in visited:
                    visited.add(nxt)
                    queue.append(path + [nxt])
        return []

    def _resolve_start(
        self, start_word: Optional[str], creativity: CreativityLevel
    ) -> Optional[str]:
        """Выбрать стартовое слово."""
        if start_word:
            w = start_word.lower()
            # Точное совпадение
            if self._graph.has_node(w):
                return w
            # Части через дефис: "муми-тролль" → "муми" или "тролль"
            for part in w.split("-"):
                if part and self._graph.has_node(part):
                    return part
            # Частичное совпадение (подстрока) — минимальный overlap 4 символа
            for word in self._graph.all_words():
                if (len(w) >= 4 and w in word) or (len(word) >= 4 and word in w):
                    return word
            return None

        high = self._graph.high_significance_words(top_n=20)
        if not high:
            return None

        if creativity == CreativityLevel.RECALL:
            return high[0].word
        elif creativity == CreativityLevel.DREAM:
            # Стартуем с менее значимого слова для исследования
            all_nodes = list(self._graph._nodes.values())
            mid = sorted(all_nodes, key=lambda n: n.avg_significance)
            mid_nodes = mid[len(mid) // 4: 3 * len(mid) // 4]
            if mid_nodes:
                return self._rng.choice(mid_nodes).word
        # RETELL / COMPOSE — взвешенный выбор среди топ
        probs = _softmax([n.avg_significance for n in high], temperature=1.0)
        idx   = self._rng.choices(range(len(high)), weights=probs, k=1)[0]
        return high[idx].word

    @staticmethod
    def _segments_to_text(segments: List[NarrativeSegment]) -> str:
        """Собрать текст из сегментов."""
        if not segments:
            return ""
        words = [s.word for s in segments]
        # Первое слово — с большой буквы
        if words:
            words[0] = words[0].capitalize()
        return " ".join(words)

    @staticmethod
    def _extract_mentioned_chars(segments: List[NarrativeSegment]) -> List[str]:
        words = {s.word for s in segments}
        return [c for c in _ALL_KNOWN if c in words]

    @staticmethod
    def _coherence(segments: List[NarrativeSegment]) -> float:
        """Связность пути = среднее по ненулевым весам переходов."""
        weights = [s.weight for s in segments if s.weight > 0]
        if not weights:
            return 0.0
        total = sum(min(w, 1.0) for w in weights)
        return total / len(weights)

    @staticmethod
    def _empty_result(creativity: CreativityLevel) -> NarrativeResult:
        return NarrativeResult(
            text="",
            segments=[],
            questions=[],
            characters_mentioned=[],
            coherence_score=0.0,
            creativity_level=creativity,
        )

    # ------------------------------------------------------------------
    # Навигация по гетерархии
    # ------------------------------------------------------------------

    def hierarchy_path(self, word: str) -> List[Dict]:
        """
        Найти путь от корня до слова в гетерархии Gen.

        Возвращает список Gen, образующих путь (от коротких к длинным):
          [{"gen_id", "label", "chain_len", "sig", "children", "parents"}, ...]
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


# ══════════════════════════════════════════════════════════════════════
# NarratorBridge
# ══════════════════════════════════════════════════════════════════════

class NarratorBridge:
    """
    Связывает SpeechDriver с NarratorDriver.

    При каждом CONFIRMED/COMPLETED-переходе усиливает рёбра WordGraph.
    При EXPLORING/REFUTED — регистрирует пробел знания.

    Позволяет NarratorDriver «учиться» в реальном времени, не пересобирая
    граф с нуля после каждого токена.
    """

    def __init__(self, narrator: NarratorDriver) -> None:
        self._narrator  = narrator
        self._prev_word: Optional[str] = None
        self._gap_words: List[str] = []

    def on_step(self, token_label: str, outcome: str) -> None:
        """
        Вызывать после каждого process_token().

        Parameters
        ----------
        token_label : str   — метка токена (слово)
        outcome     : str   — "CONFIRMED" / "COMPLETED" / "REFUTED" / "EXPLORING"
        """
        word = token_label.lower().split("|")[0].strip()

        if outcome in ("CONFIRMED", "COMPLETED"):
            if self._prev_word and self._prev_word != word:
                # Усиливаем ребро в графе
                key = (self._prev_word, word)
                old = self._narrator._graph._edges.get(key, 0.0)
                self._narrator._graph._edges[key] = old + 0.1
                # Обновляем индекс исходящих рёбер
                out = self._narrator._graph._out[self._prev_word]
                for i, (w, wt) in enumerate(out):
                    if w == word:
                        out[i] = (w, wt + 0.1)
                        break
                else:
                    out.append((word, 0.1))
                    out.sort(key=lambda x: -x[1])
            # Обновляем узел
            if word not in self._narrator._graph._nodes:
                self._narrator._graph._nodes[word] = WordNode(word=word)
            self._narrator._graph._nodes[word].occurrence_count += 1
            self._narrator._graph._nodes[word].total_significance += 0.5

        elif outcome in ("REFUTED", "EXPLORING"):
            self._gap_words.append(word)

        self._prev_word = word

    def recent_gaps(self, n: int = 10) -> List[str]:
        """Последние N слов, вызвавших пробел знания."""
        return self._gap_words[-n:]

    def reset(self) -> None:
        self._prev_word = None
        self._gap_words.clear()


# ══════════════════════════════════════════════════════════════════════
# CharacterVoice
# ══════════════════════════════════════════════════════════════════════

class _VoiceRole(Enum):
    """Архетип роли персонажа — определяет шаблон голоса."""
    EXPLORER   = "explorer"    # исследователь, движение, поиск
    GIVER      = "giver"       # даритель, угощает, помогает
    REACTOR    = "reactor"     # реагирует, чувствует, удивляется
    QUESTIONER = "questioner"  # говорит, спрашивает, знает


# Глагольные маркеры для каждой роли
_ROLE_MARKERS: Dict[_VoiceRole, Set[str]] = {
    _VoiceRole.EXPLORER: {
        "идёт", "нашёл", "нашла", "ищет", "уходит", "приходит",
        "шёл", "шла", "отправился", "отправилась", "бежит",
        "летит", "прыгает", "плывёт", "идти", "пошёл", "пошла",
    },
    _VoiceRole.GIVER: {
        "угостил", "угостила", "дал", "дала", "принёс", "принесла",
        "помог", "помогла", "носит", "подарил", "подарила",
        "отдал", "отдала", "накормил", "накормила", "поделился",
    },
    _VoiceRole.REACTOR: {
        "боится", "хочет", "любит", "удивился", "удивилась",
        "испугался", "испугалась", "обрадовался", "обрадовалась",
        "расстроился", "расстроилась", "смеётся", "плачет",
        "рад", "рада", "грустит",
    },
    _VoiceRole.QUESTIONER: {
        "говорит", "спросил", "спросила", "знает", "думает",
        "понял", "поняла", "сказал", "сказала", "отвечает",
        "рассказал", "рассказала", "объяснил", "объяснила",
    },
}

# Шаблоны голоса: ключ — (роль, is_protagonist)
# {char} — имя персонажа, {query} — исходный вопрос (без «?»)
_VOICE_TEMPLATES: Dict[Tuple[_VoiceRole, bool], List[str]] = {
    (_VoiceRole.EXPLORER,   True):  [
        "— {query}? — думал {char}, шагая вперёд.",
        "— Интересно, {query}? — {char} решил это выяснить.",
    ],
    (_VoiceRole.EXPLORER,   False): [
        "— {query}? — {char} отправился искать ответ.",
        "{char} остановился: — А {query}?",
    ],
    (_VoiceRole.GIVER,      True):  [
        "— {query}? — {char} хотел помочь разобраться.",
        "{char} предложил: — Давай узнаем, {query}?",
    ],
    (_VoiceRole.GIVER,      False): [
        "{char} протянул лапу: — {query}?",
        "— Может, {query}? — добродушно спросил {char}.",
    ],
    (_VoiceRole.REACTOR,    True):  [
        "— {query}?! — {char} широко раскрыл глаза.",
        "{char} удивился: — Но как же, {query}?",
    ],
    (_VoiceRole.REACTOR,    False): [
        "— {query}? — {char} даже испугался немного.",
        "{char} замер: — А вдруг {query}?",
    ],
    (_VoiceRole.QUESTIONER, True):  [
        "— {query}? — важно спросил {char}.",
        "{char} задумался вслух: — {query}?",
    ],
    (_VoiceRole.QUESTIONER, False): [
        "— {query}? — тихо спросил {char}.",
        "{char} повернулся: — А {query}?",
    ],
}


class CharacterVoice:
    """
    Преобразует нейтральные вопросы в реплики конкретных персонажей.

    Каждому персонажу автоматически присваивается архетип роли
    на основе типичных действий из WordGraph:
      EXPLORER  — движение и открытие (идёт, нашёл, ищет…)
      GIVER     — щедрость и помощь (угостил, принёс, дал…)
      REACTOR   — эмоции и реакции (боится, удивился, рад…)
      QUESTIONER— речь и знание (говорит, спросил, думает…)

    Пример использования::

        cv = CharacterVoice(profiles)
        voiced = cv.voice_questions(["Что делает медведь дальше?"])
        # ["— Что делает медведь дальше? — думал Винни, шагая вперёд."]
    """

    def __init__(self, profiles: List[CharacterProfile], seed: Optional[int] = None) -> None:
        self._profiles = profiles
        self._rng = random.Random(seed)
        self._roles: Dict[str, _VoiceRole] = {
            p.name: self._detect_role(p) for p in profiles
        }

    # ── Публичный API ─────────────────────────────────────────────────

    def voice_questions(
        self,
        questions: List[str],
        max_chars: int = 3,
    ) -> List[str]:
        """
        Переформулировать список вопросов в голосах персонажей.

        Вопросы равномерно распределяются между персонажами.
        Если персонажей нет — вопросы возвращаются без изменений.

        Parameters
        ----------
        questions  : исходные вопросы (могут заканчиваться на «?»)
        max_chars  : сколько персонажей использовать (≥ 1)

        Returns
        -------
        Список реплик в голосах персонажей (по одной на вопрос).
        """
        if not questions:
            return []
        active = self._profiles[:max_chars]
        if not active:
            return questions[:]

        result: List[str] = []
        for i, q in enumerate(questions):
            profile = active[i % len(active)]
            voiced  = self._apply_voice(q, profile)
            result.append(voiced)
        return result

    def role_of(self, char_name: str) -> Optional[_VoiceRole]:
        """Вернуть архетип роли для персонажа (None если не найден)."""
        return self._roles.get(char_name.lower())

    def voice_one(self, question: str, char_name: str) -> str:
        """Переформулировать один вопрос в голос конкретного персонажа."""
        name = char_name.lower()
        profile = next((p for p in self._profiles if p.name == name), None)
        if profile is None:
            return question
        return self._apply_voice(question, profile)

    # ── Внутренняя логика ─────────────────────────────────────────────

    def _detect_role(self, profile: CharacterProfile) -> _VoiceRole:
        """
        Определить роль по типичным действиям персонажа.

        Считаем «голоса» для каждой роли: сколько действий
        попадает в маркеры роли. Побеждает роль с наибольшим счётом.
        Ничья → QUESTIONER (универсальный резерв).
        """
        scores: Dict[_VoiceRole, int] = {r: 0 for r in _VoiceRole}
        for action in profile.typical_actions:
            a = action.lower()
            for role, markers in _ROLE_MARKERS.items():
                if a in markers or any(m in a for m in markers):
                    scores[role] += 1

        best_role = max(scores, key=lambda r: scores[r])
        # Если все нули → QUESTIONER по умолчанию
        if scores[best_role] == 0:
            return _VoiceRole.QUESTIONER
        return best_role

    def _apply_voice(self, question: str, profile: CharacterProfile) -> str:
        """Применить голос персонажа к вопросу."""
        # Убираем «?» в конце для вставки в шаблон
        q_clean = question.rstrip("?").rstrip()
        # Переводим первую букву в нижний регистр
        if q_clean:
            q_clean = q_clean[0].lower() + q_clean[1:]

        role = self._roles.get(profile.name, _VoiceRole.QUESTIONER)
        templates = _VOICE_TEMPLATES.get((role, profile.is_protagonist))
        if not templates:
            # Фоллбэк для незнакомой комбинации
            templates = _VOICE_TEMPLATES.get((_VoiceRole.QUESTIONER, False), ["{char}: — {query}?"])

        tpl = self._rng.choice(templates)
        # Имя персонажа с большой буквы для реплики
        char_display = profile.name.capitalize()
        return tpl.format(char=char_display, query=q_clean)


def _softmax(weights: List[float], temperature: float) -> List[float]:
    """
    Softmax с температурой.

    temperature=0 → одинаковые веса → uniform (не greedy — используй pick(temp=0) отдельно)
    temperature→∞ → uniform
    temperature=1 → обычный softmax
    """
    if not weights:
        return []
    if temperature <= 0.0:
        # Greedy — вернуть вектор с 1 у максимума
        mx = max(weights)
        return [1.0 if w == mx else 0.0 for w in weights]
    scaled = [w / temperature for w in weights]
    # Стабилизация
    mx = max(scaled)
    exp_w = [math.exp(s - mx) for s in scaled]
    total = sum(exp_w)
    if total == 0:
        return [1.0 / len(weights)] * len(weights)
    return [e / total for e in exp_w]
