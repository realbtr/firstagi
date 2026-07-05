"""
SmartTextDriver — энтропийно-минимизирующий текстовый драйвер.

Активное чтение: вместо последовательного обхода слово за словом,
драйвер прыгает к информативным позициям символов, минимизируя
число проверок для идентификации слова из множества кандидатов.

Архитектура (четыре уровня):

  Уровень 0: TextDriver (fallback)
      Стандартный побуквенный обход при отсутствии кандидатов.

  Уровень 1: EntropyMinimizer
      CandidateSet → LengthProbe → SuffixProbe → PrefixProbe → RootProbe.
      IG(pos k) = H(CandidateSet) - H(CandidateSet | char_at_k).
      Выбирает позиции в порядке убывания информационного выигрыша.

  Уровень 2: ThemeRhemeRouter
      Тема (Theme): 1 идентификационный символ → CONFIRMED для N Gen сразу.
      Рема (Rheme): 1 символ → переключает контекст на нужное подмножество Gen.
      Основано на Коммуникативном динамизме Фирбаса (1992).

  Уровень 3: Contextualizer
      RegisterEstimator: формальный / разговорный / нейтральный.
      DomainEstimator: технический / бытовой / нарратив.
      OrderAdapter: SVO / SOV / free (по доле инверсий).
      MorphologyAdapter: аналитический / синтетический (по доле суффиксов).

Биологическая аналогия:
  • Длина слова из парафовеальной зоны = бесплатная зацепка (McConkie & Rayner 1975).
  • Первый/последний символ — самые диагностичные (Jordan et al., Moukhliss 2022).
  • Оптимальная точка фиксации — левее центра (корень слова, Rayner 1979).
  • ~33% слов пропускается при чтении (Slattery & Yates 2018).
  • Активный вывод Фристона (2010): выбор точки взгляда = минимизация энтропии.

Ссылка с TextDriver:
  SmartTextDriver.produce() возвращает те же PeripheralToken[Feature], что
  и TextDriver. Дополнительная информация хранится в поле `label`:
      «слово|p=N|h=X.X» (probes=N, entropy_saved=X.X bits).

Пример использования:
    drv = SmartTextDriver("smart0")
    drv.set_candidates(["кот", "кошка", "котёнок"])
    for tok in drv.produce("кот сидит на окне"):
        result = engine.step(tok)
"""
from __future__ import annotations

import math
import re
import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Dict, Iterator, List, Optional, Tuple

from core.feature import Feature, RegionCharacteristics
from core.generalization import PeripheralToken
from .base import PeripheralDriver
from .text_driver import TextDriver, _build_vocab, _word_to_region

if TYPE_CHECKING:
    from core.learning import LearningSystem


# ──────────────────────────────────────────────────────────────────────────────
# Уровень 1: CandidateSet + EntropyMinimizer
# ──────────────────────────────────────────────────────────────────────────────

class CandidateSet:
    """
    Множество слов-кандидатов с операциями энтропийной фильтрации.

    Поддерживает:
      entropy()              — H = log2(n) равномерного распределения
      filter_by_length(n)    — оставить слова длиной n
      filter_by_char(pos, c) — оставить слова с символом c на позиции pos
      information_gain(pos, c) — IG при проверке символа c на позиции pos
      best_probe(word)       — позиция с максимальным IG для данного слова
    """

    def __init__(self, words: List[str]) -> None:
        self._words: List[str] = list(words)

    @property
    def words(self) -> List[str]:
        return list(self._words)

    def __len__(self) -> int:
        return len(self._words)

    def __bool__(self) -> bool:
        return bool(self._words)

    def entropy(self) -> float:
        """Энтропия при равномерном распределении по кандидатам (биты)."""
        n = len(self._words)
        return math.log2(n) if n > 1 else 0.0

    def filter_by_length(self, length: int) -> "CandidateSet":
        """Убрать кандидатов неподходящей длины."""
        return CandidateSet([w for w in self._words if len(w) == length])

    def filter_by_char(self, pos: int, char: str) -> "CandidateSet":
        """Убрать кандидатов без символа char на позиции pos."""
        return CandidateSet(
            [w for w in self._words if pos < len(w) and w[pos] == char]
        )

    def information_gain(self, pos: int, char: str) -> float:
        """
        IG(pos, char) = H(before) − H(after | char на pos).

        Если после фильтрации 0 кандидатов — слово не в наборе,
        IG = H(before) (полное устранение неопределённости).
        """
        h_before = self.entropy()
        filtered = self.filter_by_char(pos, char)
        if not filtered:
            # Символ полностью отсекает всё — слово вне кандидатов
            return h_before
        h_after = filtered.entropy()
        return h_before - h_after

    def best_probe(self, word: str) -> int:
        """
        Найти позицию в слове с максимальным IG.

        Возвращает индекс символа (0-based) или 0 при пустом наборе.
        """
        if not self._words:
            return 0
        best_pos, best_ig = 0, -1.0
        for pos in range(len(word)):
            ig = self.information_gain(pos, word[pos])
            if ig > best_ig:
                best_ig = ig
                best_pos = pos
        return best_pos

    def contains(self, word: str) -> bool:
        return word in self._words


@dataclass
class ProbeStats:
    """Статистика энтропийных проб для одного слова."""
    word: str
    candidates_before: int          # число кандидатов до проб
    probes_used: int                # 0 = нет кандидатов, N = N проб
    positions_checked: List[int]    # проверенные позиции символов
    was_predicted: bool             # слово было среди кандидатов
    entropy_saved: float            # биты энтропии, сэкономленные vs полного чтения
    skipped: bool = False           # слово было пропущено как предсказанное


class EntropyMinimizer:
    """
    Выбирает минимальный набор символьных позиций для идентификации слова
    среди кандидатов.

    Стратегия (5 фаз):
      0. Length probe  — паrafoveально, «бесплатно» (длина из контекста)
      1. Suffix probe  — последний символ (Crepaldi et al. 2016)
      2. Prefix probe  — первый символ (Jordan et al.)
      3. Root probe    — позиция левее центра (Rayner 1979)
      4. Greedy IG     — последовательные позиции с max IG

    Остановка: entropy ≤ min_entropy_threshold (биты).
    """

    def __init__(
        self,
        min_entropy_threshold: float = 0.5,
        skip_threshold: float = 0.0,
        max_probes: int = 5,
    ) -> None:
        """
        min_entropy_threshold : остановиться, когда H ≤ этого значения
        skip_threshold        : пропустить слово, если H=0 уже (точно известно)
        max_probes            : не делать больше N проб (аварийный выход)
        """
        self.min_entropy_threshold = min_entropy_threshold
        self.skip_threshold = skip_threshold
        self.max_probes = max_probes

    def probe_word(self, word: str, candidates: CandidateSet) -> ProbeStats:
        """
        Определить минимальный набор проб для word при данных candidates.

        Возвращает ProbeStats с полной информацией о процессе.
        """
        n_before = len(candidates)
        was_predicted = candidates.contains(word)

        if not candidates:
            # Нет кандидатов — полное чтение (fallback)
            return ProbeStats(
                word=word,
                candidates_before=0,
                probes_used=0,
                positions_checked=[],
                was_predicted=False,
                entropy_saved=0.0,
            )

        h_full = math.log2(len(word)) if len(word) > 1 else 0.0  # энтропия полного чтения
        positions: List[int] = []
        remaining = candidates

        # Фаза 0: Length probe (бесплатная)
        remaining = remaining.filter_by_length(len(word))
        if remaining.entropy() <= self.min_entropy_threshold:
            entropy_saved = max(0.0, h_full - 0.0)
            return ProbeStats(
                word=word,
                candidates_before=n_before,
                probes_used=0,
                positions_checked=[],
                was_predicted=was_predicted,
                entropy_saved=entropy_saved,
                skipped=(remaining.entropy() <= self.skip_threshold),
            )

        n = len(word)
        checked: set = set()

        # Фаза 1: Suffix probe (последний символ)
        if n > 0:
            pos = n - 1
            positions.append(pos)
            checked.add(pos)
            remaining = remaining.filter_by_char(pos, word[pos])
            if remaining.entropy() <= self.min_entropy_threshold:
                return self._make_stats(
                    word, n_before, positions, was_predicted, h_full
                )

        # Фаза 2: Prefix probe (первый символ)
        if n > 1:
            pos = 0
            positions.append(pos)
            checked.add(pos)
            remaining = remaining.filter_by_char(pos, word[pos])
            if remaining.entropy() <= self.min_entropy_threshold:
                return self._make_stats(
                    word, n_before, positions, was_predicted, h_full
                )

        # Фаза 3: Root probe (левее центра — примерно 1/3)
        if n > 3:
            pos = max(1, n // 3)
            if pos not in checked:
                positions.append(pos)
                checked.add(pos)
                remaining = remaining.filter_by_char(pos, word[pos])
                if remaining.entropy() <= self.min_entropy_threshold:
                    return self._make_stats(
                        word, n_before, positions, was_predicted, h_full
                    )

        # Фаза 4: Жадный IG — пока не достигнут порог или лимит проб
        while (
            remaining.entropy() > self.min_entropy_threshold
            and len(positions) < self.max_probes
        ):
            best_ig = -1.0
            best_pos = -1
            for pos in range(n):
                if pos in checked:
                    continue
                ig = remaining.information_gain(pos, word[pos])
                if ig > best_ig:
                    best_ig = ig
                    best_pos = pos
            if best_pos == -1:
                break
            positions.append(best_pos)
            checked.add(best_pos)
            remaining = remaining.filter_by_char(best_pos, word[best_pos])

        return self._make_stats(word, n_before, positions, was_predicted, h_full)

    @staticmethod
    def _make_stats(
        word: str,
        n_before: int,
        positions: List[int],
        was_predicted: bool,
        h_full: float,
    ) -> ProbeStats:
        probes = len(positions)
        entropy_saved = max(0.0, h_full - probes * math.log2(max(probes, 1)))
        return ProbeStats(
            word=word,
            candidates_before=n_before,
            probes_used=probes,
            positions_checked=positions,
            was_predicted=was_predicted,
            entropy_saved=entropy_saved,
        )


# ──────────────────────────────────────────────────────────────────────────────
# Уровень 2: ThemeRhemeRouter
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ThemeRhemeLabel:
    """Тема/Рема разметка для слова."""
    word: str
    role: str           # "theme" или "rheme"
    cd_score: float     # коммуникативный динамизм [0, 1]; тема→0, рема→1


class ThemeRhemeRouter:
    """
    Идентифицирует тему (стабильный контекст) и рему (новая информация)
    в последовательности слов.

    Основано на Коммуникативном динамизме Фирбаса (1992):
      • Тема: высокочастотные слова, ранние в предложении → CD низкий
      • Рема: редкие слова, поздние в предложении → CD высокий

    В SVO-языках: Субъект = тема, Предикат/Объект = рема.
    В свободном порядке слов: частота слова + позиция = суррогат CD.
    """

    def __init__(self, vocab: Optional[Dict[str, float]] = None) -> None:
        """
        vocab : {слово → нормированный индекс}, где 0 = самое частое.
                Если None — тема/рема по позиции в предложении.
        """
        self._vocab = vocab or {}

    def label_sequence(self, words: List[str]) -> List[ThemeRhemeLabel]:
        """
        Разметить последовательность слов как тема/рема.

        Алгоритм:
          cd_score(word, pos) = 0.5 * freq_rarity(word) + 0.5 * (pos / n)

          Слова с cd < медиана → тема (theme).
          Слова с cd ≥ медиана → рема (rheme).
        """
        if not words:
            return []

        n = len(words)
        scores: List[float] = []

        for i, word in enumerate(words):
            freq_index = self._vocab.get(word, 0.5)
            freq_rarity = 1.0 - freq_index      # редкое = большая рема
            pos_score = i / max(n - 1, 1)       # позднее = большая рема
            cd = 0.5 * freq_rarity + 0.5 * pos_score
            scores.append(cd)

        if len(scores) > 1:
            median_cd = sorted(scores)[len(scores) // 2]
        else:
            median_cd = 0.5

        result = []
        for word, cd in zip(words, scores):
            role = "theme" if cd < median_cd else "rheme"
            result.append(ThemeRhemeLabel(word=word, role=role, cd_score=cd))
        return result

    def theme_identifier_char(self, theme_word: str) -> Optional[str]:
        """
        Вернуть один «идентификационный» символ темы.

        Тема однозначно идентифицируется по одному символу (она ожидаема).
        Используем первый символ (наиболее диагностичный для высокочастотных слов).
        """
        return theme_word[0] if theme_word else None

    def rheme_pivot_char(self, rheme_word: str) -> Optional[str]:
        """
        Вернуть «стержневой» символ ремы.

        Рема несёт новую информацию. Левее центра (корень) — наиболее
        диагностичная позиция (Rayner 1979).
        """
        if not rheme_word:
            return None
        n = len(rheme_word)
        root_pos = max(1, n // 3)
        return rheme_word[root_pos]


# ──────────────────────────────────────────────────────────────────────────────
# Уровень 3: Contextualizer
# ──────────────────────────────────────────────────────────────────────────────

@dataclass
class ContextParameters:
    """
    Глобальные параметры контекста — аналог «баланса белого» в зрении.

    Они не кодируются в Feature напрямую, но влияют на интерпретацию
    признаков в SmartTextDriver (сдвигают пороги и веса).
    """
    register: str = "neutral"        # "formal" | "informal" | "neutral"
    domain: str = "general"          # "technical" | "narrative" | "general"
    word_order: str = "svo"          # "svo" | "sov" | "free"
    morphology: str = "synthetic"    # "analytic" | "synthetic"
    avg_word_length: float = 5.0     # средняя длина слова
    lexical_diversity: float = 0.5   # TTR (type/token ratio)


class Contextualizer:
    """
    Оценивает глобальные параметры контекста (ContextParameters) по корпусу
    или тексту — аналог автоматической регулировки яркости/контраста в зрении.

    Компоненты:
      RegisterEstimator  : формальный vs разговорный (длина слов + частота)
      DomainEstimator    : технический vs нарратив (TTR + длина слов)
      OrderAdapter       : порядок слов по сигналам
      MorphologyAdapter  : аналитический vs синтетический (суффиксы)
    """

    # Маркеры формальности (упрощённый набор для RU/EN)
    _FORMAL_MARKERS_RU = frozenset([
        "данный", "указанный", "следовательно", "таким образом",
        "вследствие", "согласно", "однако", "тем не менее",
    ])
    _INFORMAL_MARKERS_RU = frozenset([
        "вот", "ну", "ладно", "короче", "типа", "значит", "блин",
    ])
    _TECHNICAL_MARKERS = frozenset([
        "алгоритм", "система", "функция", "параметр", "конфигурация",
        "протокол", "интерфейс", "архитектура", "модель", "данные",
        "algorithm", "function", "parameter", "interface", "protocol",
    ])

    def estimate(self, text: str, lowercase: bool = True) -> ContextParameters:
        """
        Оценить параметры контекста по тексту.

        Работает на лету без предварительного обучения.
        """
        if lowercase:
            text_lc = text.lower()
        else:
            text_lc = text

        words_raw = re.split(r"[\s,.\-!?;:\"'()]+", text_lc)
        words = [w for w in words_raw if w]
        if not words:
            return ContextParameters()

        n = len(words)
        types = len(set(words))
        ttr = types / n
        avg_len = sum(len(w) for w in words) / n

        # Регистр
        formal_hits = sum(1 for w in words if w in self._FORMAL_MARKERS_RU)
        informal_hits = sum(1 for w in words if w in self._INFORMAL_MARKERS_RU)
        if formal_hits > informal_hits and avg_len > 6:
            register = "formal"
        elif informal_hits > formal_hits:
            register = "informal"
        else:
            register = "neutral"

        # Домен
        tech_hits = sum(1 for w in words if w in self._TECHNICAL_MARKERS)
        if tech_hits / max(n, 1) > 0.05:
            domain = "technical"
        elif ttr < 0.4 and avg_len < 5:
            domain = "narrative"
        else:
            domain = "general"

        # Морфология: наличие явных суффиксов → синтетический
        suffix_endings = ("ость", "ение", "ание", "ый", "ой", "ся", "tion", "ing", "ness")
        suffix_count = sum(1 for w in words if any(w.endswith(s) for s in suffix_endings))
        morphology = "synthetic" if suffix_count / max(n, 1) > 0.15 else "analytic"

        return ContextParameters(
            register=register,
            domain=domain,
            word_order="svo",       # упрощение; определение порядка требует парсинга
            morphology=morphology,
            avg_word_length=avg_len,
            lexical_diversity=ttr,
        )

    def adjust_tolerance(self, params: ContextParameters, base_tolerance: float) -> float:
        """
        Скорректировать feature_tolerance по параметрам контекста.

        Формальный/технический текст → строже (меньше tolerance).
        Разговорный текст → мягче (больше tolerance).
        """
        delta = 0.0
        if params.register == "formal":
            delta -= 0.03
        elif params.register == "informal":
            delta += 0.05
        if params.domain == "technical":
            delta -= 0.02
        return max(0.05, min(0.5, base_tolerance + delta))


# ──────────────────────────────────────────────────────────────────────────────
# SmartTextDriver
# ──────────────────────────────────────────────────────────────────────────────

class SmartTextDriver(PeripheralDriver):
    """
    Энтропийно-минимизирующий текстовый драйвер.

    Совместим с TextDriver: produce() возвращает те же PeripheralToken[Feature].
    Дополнительная информация в label: «слово|p=N|h=X.X».

    Параметры
    ----------
    driver_id       : str
    lowercase       : bool (по умолчанию True)
    min_entropy     : float (порог остановки IG-цикла, в битах, по умолчанию 0.5)
    skip_high_prob  : bool (пропускать слова с p=1.0 в кандидатах)
    max_probes      : int (лимит проб на слово, по умолчанию 5)
    enable_context  : bool (включить Contextualizer, по умолчанию True)

    Основное использование (активное):
        drv = SmartTextDriver("smart0")
        drv.set_candidates(["кот", "кошка"])   # от Gen-системы
        for tok in drv.produce("кот сидит"):
            result = engine.step(tok)

    Пассивный режим (без кандидатов):
        drv = SmartTextDriver("smart0")
        for tok in drv.produce("любой текст"):  # как TextDriver
            result = engine.step(tok)
    """

    def __init__(
        self,
        driver_id: str,
        lowercase: bool = True,
        min_entropy: float = 0.5,
        skip_high_prob: bool = False,
        max_probes: int = 5,
        enable_context: bool = True,
    ) -> None:
        super().__init__(driver_id)
        self.lowercase = lowercase
        self._min_entropy = min_entropy
        self._skip_high_prob = skip_high_prob
        self._max_probes = max_probes
        self._enable_context = enable_context

        self._candidates: CandidateSet = CandidateSet([])
        self._minimizer = EntropyMinimizer(
            min_entropy_threshold=min_entropy,
            max_probes=max_probes,
        )
        self._router = ThemeRhemeRouter()
        self._contextualizer = Contextualizer()
        self._context_params: Optional[ContextParameters] = None
        self._vocab: Dict[str, float] = {}

        # Статистика текущей сессии
        self._session_stats: List[ProbeStats] = []

        # Опциональная ссылка на Gen-систему для автообновления кандидатов
        self._gen_system: Optional[LearningSystem] = None

    # ──────────────────────────────────────────────────────────────────────
    # Публичный API

    def connect_gen_system(self, system: LearningSystem) -> None:
        """
        Подключить Gen-систему для автоматического обновления кандидатов.

        После подключения produce() будет вызывать system.get_next_word_candidates()
        перед каждым токеном — кандидаты всегда отражают живое состояние Gen.

        Для отключения: connect_gen_system(None).
        """
        self._gen_system = system

    def set_candidates(self, candidate_words: List[str]) -> None:
        """
        Установить ожидаемые слова-кандидаты (от Gen-системы).

        Вызывается после каждого шага engine.step(), чтобы обновить
        ожидания перед следующим словом.
        """
        if self.lowercase:
            candidate_words = [w.lower() for w in candidate_words]
        self._candidates = CandidateSet(candidate_words)

    def set_vocab(self, vocab: Dict[str, float]) -> None:
        """
        Установить словарь частот для ThemeRhemeRouter и кодирования.

        vocab : {слово → нормированный индекс [0, 1]}; 0 = самое частое.
        """
        self._vocab = vocab
        self._router = ThemeRhemeRouter(vocab)

    def build_vocab(self, texts: List[str]) -> None:
        """Построить словарь по корпусу текстов (аналог TextDriver.build_vocab)."""
        from .text_driver import _build_vocab
        all_words: List[str] = []
        for t in texts:
            all_words.extend(self._tokenize(t))
        self._vocab = _build_vocab(all_words)
        self._router = ThemeRhemeRouter(self._vocab)

    def context_params(self) -> Optional[ContextParameters]:
        """Вернуть последние вычисленные параметры контекста."""
        return self._context_params

    def session_stats(self) -> List[ProbeStats]:
        """Вернуть статистику проб за текущую сессию."""
        return list(self._session_stats)

    def clear_session_stats(self) -> None:
        """Сбросить накопленную статистику."""
        self._session_stats.clear()

    def efficiency_summary(self) -> Dict[str, float]:
        """
        Сводка эффективности текущей сессии.

        Возвращает:
          avg_probes   — среднее число проб на слово
          predicted_rate — доля слов, совпавших с кандидатами
          avg_entropy_saved — средняя экономия битов
          skipped_rate — доля пропущенных слов
        """
        stats = self._session_stats
        if not stats:
            return {"avg_probes": 0.0, "predicted_rate": 0.0,
                    "avg_entropy_saved": 0.0, "skipped_rate": 0.0}
        n = len(stats)
        return {
            "avg_probes": sum(s.probes_used for s in stats) / n,
            "predicted_rate": sum(1 for s in stats if s.was_predicted) / n,
            "avg_entropy_saved": sum(s.entropy_saved for s in stats) / n,
            "skipped_rate": sum(1 for s in stats if s.skipped) / n,
        }

    # ──────────────────────────────────────────────────────────────────────
    # Интерфейс PeripheralDriver

    def produce(self, text: Optional[str] = None) -> Iterator[PeripheralToken]:
        """
        Генерировать токены из текста с энтропийной минимизацией.

        Каждая пара соседних слов (w_i, w_{i+1}) → один PeripheralToken.
        label = «слово|p=N|h=X.X|role=theme/rheme»

        Если кандидаты не установлены — работает как TextDriver.
        """
        source_text = text if text is not None else ""
        words = self._tokenize(source_text)

        if len(words) < 2:
            return

        # Обновить словарь на лету если пуст
        if not self._vocab:
            from .text_driver import _build_vocab
            self._vocab = _build_vocab(words)
            self._router = ThemeRhemeRouter(self._vocab)

        # Уровень 3: оценить параметры контекста
        if self._enable_context:
            self._context_params = self._contextualizer.estimate(source_text)

        # Тема/Рема разметка
        tr_labels = self._router.label_sequence(words)
        tr_map = {lbl.word: lbl for lbl in tr_labels}

        n = len(words)
        for i in range(n - 1):
            # Автообновление кандидатов от Gen-системы (после предыдущего токена).
            # На i=0: система в исходном состоянии (до первого токена).
            # На i>0: система уже обработала токен i-1, кандидаты отражают живой контекст.
            if self._gen_system is not None:
                live = self._gen_system.get_next_word_candidates()
                if live:
                    self._candidates = CandidateSet(
                        [w.lower() for w in live] if self.lowercase else live
                    )

            w1, w2 = words[i], words[i + 1]

            # Уровень 1: EntropyMinimizer для w2 (следующее слово)
            probe_result = self._minimizer.probe_word(w2, self._candidates)
            self._session_stats.append(probe_result)

            # Кодирование токена (идентично TextDriver)
            vi1 = self._vocab.get(w1, 0.5)
            vi2 = self._vocab.get(w2, 0.5)

            import math as _math
            src = _word_to_region(w1, vi1)
            tgt = _word_to_region(w2, vi2)
            direction = (vi2 - vi1) * _math.pi

            feature = Feature.from_regions(
                feature_id=str(uuid.uuid4()),
                direction=direction,
                distance=1.0,
                source=src,
                target=tgt,
            )

            # Уровень 2: роль слова в теме/реме
            tr = tr_map.get(w2)
            role = tr.role if tr else "rheme"

            # Метка с метаданными
            label = (
                f"{w2}"
                f"|p={probe_result.probes_used}"
                f"|h={probe_result.entropy_saved:.1f}"
                f"|role={role}"
            )

            token = PeripheralToken.new(
                driver_id=self.driver_id,
                data=feature,
                label=label,
            )
            yield token

    def load_buffer(self, text_or_tokens, **kwargs) -> int:  # type: ignore[override]
        """Принимает строку или List[PeripheralToken]."""
        if isinstance(text_or_tokens, str):
            tokens = list(self.produce(text=text_or_tokens))
            return super().load_buffer(tokens)
        return super().load_buffer(text_or_tokens)

    def reset(self) -> None:
        self.clear_buffer()
        self._candidates = CandidateSet([])
        self._session_stats.clear()

    # ──────────────────────────────────────────────────────────────────────
    # Вспомогательные методы

    def _tokenize(self, text: str) -> List[str]:
        if self.lowercase:
            text = text.lower()
        return [w for w in re.split(r"[\s,.\-!?;:\"'()]+", text) if w]

    def __repr__(self) -> str:
        return (
            f"SmartTextDriver(id={self.driver_id!r}, "
            f"candidates={len(self._candidates)}, "
            f"buf={self.buffer_size})"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Демо
# ──────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

    W = "\033[0m"; CY = "\033[96m"; GR = "\033[92m"; BD = "\033[1m"; DM = "\033[90m"
    YL = "\033[93m"

    def hdr(t: str) -> None:
        print(f"\n{BD}{CY}{'═'*68}{W}")
        print(f"{BD}{CY}  {t}{W}")
        print(f"{BD}{CY}{'═'*68}{W}\n")

    hdr("SmartTextDriver — энтропийно-минимизирующее чтение")

    # ── 1. EntropyMinimizer ─────────────────────────────────────────────────
    hdr("Уровень 1: EntropyMinimizer")

    candidates = CandidateSet(["кот", "кошка", "котёнок", "копейка", "корень"])
    minimizer = EntropyMinimizer()

    for test_word in ["кот", "кошка", "котёнок", "медведь"]:
        stats = minimizer.probe_word(test_word, candidates)
        pred = GR + "✓" + W if stats.was_predicted else YL + "✗" + W
        print(
            f"  {pred} «{test_word:<10}»  "
            f"кандидатов={stats.candidates_before}  "
            f"проб={stats.probes_used}  "
            f"позиции={stats.positions_checked}  "
            f"экономия={stats.entropy_saved:.2f} бит"
        )

    # ── 2. ThemeRhemeRouter ─────────────────────────────────────────────────
    hdr("Уровень 2: Тема/Рема")

    router = ThemeRhemeRouter()
    text_sample = "кот сидит на окне и смотрит на улицу"
    words_sample = text_sample.split()
    labels = router.label_sequence(words_sample)
    for lbl in labels:
        role_str = GR + "ТЕМА" + W if lbl.role == "theme" else CY + "РЕМА" + W
        print(f"  {role_str}  «{lbl.word:<12}»  cd={lbl.cd_score:.2f}")

    # ── 3. Contextualizer ───────────────────────────────────────────────────
    hdr("Уровень 3: Контекст")

    contextualizer = Contextualizer()
    texts = [
        "кот сидит и смотрит в окно",
        "данный алгоритм следовательно обеспечивает согласно протоколу конфигурацию системы",
        "ну вот типа значит короче всё понятно",
    ]
    for t in texts:
        cp = contextualizer.estimate(t)
        print(
            f"  register={cp.register:<10}  domain={cp.domain:<12}  "
            f"morph={cp.morphology:<11}  ttr={cp.lexical_diversity:.2f}  "
            f"«{t[:40]}»"
        )

    # ── 4. SmartTextDriver полный проход ────────────────────────────────────
    hdr("SmartTextDriver: полный проход")

    drv = SmartTextDriver("smart_demo", min_entropy=0.5)
    drv.set_candidates(["сидит", "лежит", "спит", "идёт"])

    text = "кот сидит на окне"
    print(f"  Текст: «{text}»")
    print(f"  Кандидаты: {drv._candidates.words}")
    print()

    for tok in drv.produce(text):
        print(f"  label={tok.label}")

    summary = drv.efficiency_summary()
    print(f"\n  Эффективность:")
    print(f"    avg_probes      = {summary['avg_probes']:.2f}")
    print(f"    predicted_rate  = {summary['predicted_rate']:.0%}")
    print(f"    entropy_saved   = {summary['avg_entropy_saved']:.2f} бит")
