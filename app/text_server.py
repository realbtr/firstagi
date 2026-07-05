"""
app/text_server.py — Active Corpus Server с курсорной навигацией.

Архитектура
───────────
Модель НЕ читает тексты пассивно. Она управляет навигационным курсором:
  1. Выдаёт Search-запрос (LeakyTemplate → regex/FTS5)
  2. Получает список позиций (doc_id, paragraph, token_idx)
  3. Выдаёт Probe — ожидает конкретный токен в позиции cursor+delta
  4. Получает ProbeResult: hit / miss(+shift)
  5. При miss — Shift(delta) для перехода к следующему вхождению

Масштабы навигации (ZoomLevel):
  CORPUS     — поиск по всей библиотеке
  DOCUMENT   — навигация по документу
  PARAGRAPH  — чтение абзаца
  SENTENCE   — обработка предложения (токены → Gen)
  TOKEN      — проверка конкретной позиции

Запуск сервера:
  py -X utf8 app/text_server.py --port 8100 --db data/gen_base.db

Или встроенно:
  server = ActiveTextServer()
  server.add_document("winnie1", "Пух шёл через лес...", domain="children")
  server.start_loop(system, driver)
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from core.query_builder import LeakyTemplate, QueryBuilder
from core.exploration import ExplorationPolicy, ProbeChain


# ══════════════════════════════════════════════════════════════════════════════
# Перечисления и структуры данных
# ══════════════════════════════════════════════════════════════════════════════

class ZoomLevel(Enum):
    CORPUS    = 0   # «библиотека» — поиск по всем документам
    DOCUMENT  = 1   # «книга» — по одному документу
    PARAGRAPH = 2   # «абзац»
    SENTENCE  = 3   # «предложение»
    TOKEN     = 4   # «позиция»


@dataclass
class Paragraph:
    """Абзац с индексированными токенами."""
    idx: int
    text: str
    tokens: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.tokens:
            self.tokens = self.text.split()


@dataclass
class CorpusEntry:
    """Один документ в корпусе."""
    doc_id:     str
    content:    str
    domain:     str = ""
    title:      str = ""
    paragraphs: List[Paragraph] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.paragraphs:
            self._build_paragraphs()

    def _build_paragraphs(self) -> None:
        raw = [p.strip() for p in self.content.split("\n") if p.strip()]
        self.paragraphs = [Paragraph(i, p) for i, p in enumerate(raw)]

    @property
    def all_tokens(self) -> List[Tuple[int, int, str]]:
        """(paragraph_idx, token_idx, token) — плоский список."""
        result = []
        for p in self.paragraphs:
            for ti, tok in enumerate(p.tokens):
                result.append((p.idx, ti, tok))
        return result


@dataclass
class NavigationCursor:
    """Текущая позиция модели в корпусе."""
    doc_id:        Optional[str] = None
    paragraph_idx: int           = 0
    token_idx:     int           = 0
    zoom:          ZoomLevel     = ZoomLevel.CORPUS

    def advance(self, delta: int = 1) -> None:
        self.token_idx += delta

    def reset_to_doc(self, doc_id: str) -> None:
        self.doc_id        = doc_id
        self.paragraph_idx = 0
        self.token_idx     = 0
        self.zoom          = ZoomLevel.DOCUMENT


@dataclass
class SearchMatch:
    """Результат поиска."""
    doc_id:     str
    para_idx:   int
    token_idx:  int
    fragment:   str          # несколько слов вокруг совпадения
    score:      float = 1.0  # релевантность


@dataclass
class ProbeResult:
    """Результат проверки позиции."""
    hit:          bool          # совпало?
    actual_token: str           # реальный токен на позиции
    expected:     str           # что ожидалось
    shift_to_next: int = 0      # смещение к следующему вхождению expected в тексте


@dataclass
class Fragment:
    """Фрагмент текста, возвращённый по запросу."""
    doc_id:    str
    para_idx:  int
    tokens:    List[str]
    start_idx: int = 0


# ══════════════════════════════════════════════════════════════════════════════
# Команды навигации (Command Pattern)
# ══════════════════════════════════════════════════════════════════════════════

class NavCmd:
    """Базовый класс команды навигации."""

@dataclass
class CmdSearch(NavCmd):
    """Поиск по шаблону."""
    template:  LeakyTemplate
    zoom:      ZoomLevel = ZoomLevel.CORPUS
    max_hits:  int       = 10

@dataclass
class CmdProbe(NavCmd):
    """Проверить конкретный токен на позиции cursor+delta."""
    expected:  str
    delta:     int = 0       # относительно текущей позиции
    tolerance: float = 0.0   # 0 = точное совпадение

@dataclass
class CmdShift(NavCmd):
    """Сдвинуть курсор."""
    delta:   int
    doc_id:  Optional[str] = None  # если None — в текущем документе

@dataclass
class CmdZoom(NavCmd):
    """Изменить масштаб навигации."""
    level: ZoomLevel

@dataclass
class CmdRead(NavCmd):
    """Прочитать N токенов с текущей позиции."""
    length: int = 10

@dataclass
class CmdAddDoc(NavCmd):
    """Добавить документ в корпус."""
    doc_id:  str
    content: str
    domain:  str = ""
    title:   str = ""


# ══════════════════════════════════════════════════════════════════════════════
# Active Text Server
# ══════════════════════════════════════════════════════════════════════════════

class ActiveTextServer:
    """
    Персистентный сервер корпуса с курсорной навигацией.

    Модель управляет чтением через команды:
      search(template) → List[SearchMatch]
      probe(expected, delta) → ProbeResult
      shift(delta) → cursor updated
      read(length) → Fragment

    Основной цикл работы:
      server.start_loop(system, driver) — запускает автономный цикл
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        exploration_policy: Optional[ExplorationPolicy] = None,
        use_probe_chain: bool = True,
    ) -> None:
        self._corpus:  Dict[str, CorpusEntry] = {}
        self._cursor:  NavigationCursor       = NavigationCursor()
        self._qbuilder = QueryBuilder()
        self._db_path  = db_path
        self._policy   = exploration_policy or ExplorationPolicy()
        self._use_probe_chain = use_probe_chain

        # Статистика
        self._stats = {
            "searches": 0, "probes": 0, "hits": 0, "misses": 0, "shifts": 0,
            "probe_chains": 0, "probe_aborts": 0,
        }
        # Колбэки для интеграции
        self._on_fragment: Optional[Callable[[Fragment], None]] = None
        self._on_search_fail: Optional[Callable[[LeakyTemplate], None]] = None

    # ── Управление корпусом ───────────────────────────────────────────────────

    def add_document(
        self, doc_id: str, content: str,
        domain: str = "", title: str = "",
    ) -> None:
        entry = CorpusEntry(doc_id=doc_id, content=content, domain=domain, title=title)
        self._corpus[doc_id] = entry

    def list_documents(self, domain: str = "") -> List[str]:
        if not domain:
            return list(self._corpus.keys())
        return [did for did, e in self._corpus.items() if e.domain == domain]

    def document_count(self) -> int:
        return len(self._corpus)

    # ── Поиск ─────────────────────────────────────────────────────────────────

    def search(
        self,
        template: LeakyTemplate,
        zoom: ZoomLevel = ZoomLevel.CORPUS,
        max_hits: int = 10,
    ) -> List[SearchMatch]:
        """
        Поиск по дырявому шаблону.
        1. FTS5-предфильтр (если подключена GenBaseDB)
        2. Regex-поиск по подходящим документам
        3. Zoom: если DOCUMENT — искать только в текущем doc_id
        """
        self._stats["searches"] += 1
        pattern = template.to_regex()
        docs = (
            [self._corpus[self._cursor.doc_id]]
            if zoom in (ZoomLevel.DOCUMENT, ZoomLevel.PARAGRAPH, ZoomLevel.SENTENCE)
               and self._cursor.doc_id in self._corpus
            else list(self._corpus.values())
        )
        return self._regex_search(docs, pattern, max_hits)

    def _regex_search(
        self, docs: List[CorpusEntry], pattern: re.Pattern, max_hits: int
    ) -> List[SearchMatch]:
        matches: List[SearchMatch] = []
        for doc in docs:
            for para in doc.paragraphs:
                m = pattern.search(para.text)
                if m:
                    # Контекст: ±3 слова вокруг совпадения
                    start_tok = max(0, len(para.text[:m.start()].split()) - 3)
                    frag_tokens = para.tokens[start_tok: start_tok + 10]
                    matches.append(SearchMatch(
                        doc_id    = doc.doc_id,
                        para_idx  = para.idx,
                        token_idx = start_tok,
                        fragment  = " ".join(frag_tokens),
                        score     = 1.0,
                    ))
                    if len(matches) >= max_hits:
                        return matches
        return matches

    # ── Проверка позиции (Probe) ───────────────────────────────────────────────

    def probe(self, expected: str, delta: int = 0) -> ProbeResult:
        """
        Проверить токен на позиции cursor + delta.
        Если промах — вычислить смещение до следующего вхождения.
        """
        self._stats["probes"] += 1
        doc = self._corpus.get(self._cursor.doc_id)
        if doc is None:
            return ProbeResult(hit=False, actual_token="<no_doc>", expected=expected)

        para = self._get_paragraph(doc, self._cursor.paragraph_idx)
        if para is None:
            return ProbeResult(hit=False, actual_token="<no_para>", expected=expected)

        pos = self._cursor.token_idx + delta
        if pos < 0 or pos >= len(para.tokens):
            return ProbeResult(hit=False, actual_token="<eof>", expected=expected)

        actual = para.tokens[pos].lower()
        hit    = (actual == expected.lower())
        shift  = 0

        if not hit:
            self._stats["misses"] += 1
            # Найти следующее вхождение expected в документе
            shift = self._find_next(doc, self._cursor.paragraph_idx, pos, expected)
        else:
            self._stats["hits"] += 1

        return ProbeResult(hit=hit, actual_token=actual, expected=expected, shift_to_next=shift)

    def _find_next(
        self, doc: CorpusEntry, para_idx: int, token_idx: int, word: str
    ) -> int:
        """Вернуть количество токенов до следующего вхождения word после (para_idx, token_idx)."""
        offset = 0
        w = word.lower()
        for p in doc.paragraphs[para_idx:]:
            start = token_idx + 1 if p.idx == para_idx else 0
            for ti, tok in enumerate(p.tokens[start:], start=start):
                offset += 1
                if tok.lower() == w:
                    return offset
        return -1   # не найдено

    # ── Курсорные операции ────────────────────────────────────────────────────

    def shift(self, delta: int, doc_id: Optional[str] = None) -> None:
        """Сдвинуть курсор на delta токенов (или перейти в другой документ)."""
        self._stats["shifts"] += 1
        if doc_id and doc_id != self._cursor.doc_id:
            self._cursor.reset_to_doc(doc_id)
        doc = self._corpus.get(self._cursor.doc_id)
        if doc is None:
            return
        # Переместить через абзацы
        pos    = self._cursor.token_idx + delta
        para   = self._get_paragraph(doc, self._cursor.paragraph_idx)
        while para and pos >= len(para.tokens):
            pos -= len(para.tokens)
            next_idx = self._cursor.paragraph_idx + 1
            if next_idx >= len(doc.paragraphs):
                self._cursor.token_idx = max(0, len(para.tokens) - 1)
                return
            self._cursor.paragraph_idx = next_idx
            para = doc.paragraphs[next_idx]
        self._cursor.token_idx = max(0, pos)

    def navigate_to(self, match: SearchMatch) -> None:
        """Переместить курсор к результату поиска."""
        self._cursor.doc_id        = match.doc_id
        self._cursor.paragraph_idx = match.para_idx
        self._cursor.token_idx     = match.token_idx
        self._cursor.zoom          = ZoomLevel.PARAGRAPH

    def read(self, length: int = 10) -> Fragment:
        """Прочитать length токенов с текущей позиции."""
        doc = self._corpus.get(self._cursor.doc_id)
        if doc is None:
            return Fragment(doc_id="", para_idx=0, tokens=[])
        para = self._get_paragraph(doc, self._cursor.paragraph_idx)
        if para is None:
            return Fragment(doc_id=self._cursor.doc_id, para_idx=0, tokens=[])
        start = self._cursor.token_idx
        tokens = para.tokens[start: start + length]
        return Fragment(
            doc_id    = self._cursor.doc_id,
            para_idx  = self._cursor.paragraph_idx,
            tokens    = tokens,
            start_idx = start,
        )

    # ── Основной цикл ─────────────────────────────────────────────────────────

    def run_active_loop(
        self,
        system,
        driver,
        max_cycles: int = 0,
        on_cycle: Optional[Callable[[int, str], None]] = None,
    ) -> None:
        """
        Автономный цикл активного чтения:
          1. Построить LeakyTemplate из текущего состояния Gen-системы
          2. Поискать в корпусе
          3. Если нашли → navigate_to + read + feed tokens to system
          4. Если не нашли → эскалация через on_search_fail
          5. Повторить

        on_cycle(cycle, status) — колбэк для логирования
        """
        qbuilder = QueryBuilder()
        cycle    = 0

        while max_cycles == 0 or cycle < max_cycles:
            cycle += 1
            status = "idle"

            # Шаг 1: запрос
            templates = qbuilder.build_from_active_gen(system)
            if not templates:
                # Нет активных Gen — начать с любого документа
                if self._corpus:
                    doc_id = next(iter(self._corpus))
                    self._cursor.reset_to_doc(doc_id)
                    frag = self.read(20)
                    status = f"cold_start:{doc_id}"
                    self._feed_fragment(system, driver, frag)
            else:
                # Шаг 2: поиск
                t = templates[0]
                hits = self.search(t, zoom=ZoomLevel.CORPUS, max_hits=10)
                if hits:
                    # Выбрать наиболее привлекательный фрагмент (ExplorationPolicy)
                    best = self._policy.select(hits, self._corpus, top_k=1)
                    chosen = best[0] if best else hits[0]

                    # ProbeChain: быстро проверить гипотезу перед полным чтением
                    should_read = True
                    if self._use_probe_chain and len(t.slots) >= 2:
                        self._stats["probe_chains"] += 1
                        self.navigate_to(chosen)
                        chain = ProbeChain.from_template(t, max_steps=3)
                        chain_result = chain.run(self)
                        if not chain_result.passed:
                            self._stats["probe_aborts"] += 1
                            should_read = False
                            status = f"probe_abort:{chosen.doc_id}[{chosen.para_idx}]"

                    if should_read:
                        self.navigate_to(chosen)
                        frag = self.read(15)
                        status = f"search_hit:{frag.doc_id}[{frag.para_idx}:{frag.start_idx}]"
                        self._policy.record_visit(frag.doc_id, frag.para_idx, frag.tokens)
                        self._feed_fragment(system, driver, frag)
                else:
                    status = f"search_miss:«{t}»"
                    if self._on_search_fail:
                        self._on_search_fail(t)

            if on_cycle:
                on_cycle(cycle, status)

    def _feed_fragment(self, system, driver, fragment: Fragment) -> None:
        """Подать токены фрагмента в Gen-систему через driver."""
        text = " ".join(fragment.tokens)
        for tok in driver.produce(text):
            system.process_token(tok)
        if self._on_fragment:
            self._on_fragment(fragment)

    # ── Колбэки ───────────────────────────────────────────────────────────────

    def on_fragment(self, fn: Callable[[Fragment], None]) -> None:
        self._on_fragment = fn

    def on_search_fail(self, fn: Callable[[LeakyTemplate], None]) -> None:
        self._on_search_fail = fn

    # ── Статистика ────────────────────────────────────────────────────────────

    @property
    def stats(self) -> Dict[str, Any]:
        return {
            **self._stats,
            "corpus_size": len(self._corpus),
            "cursor": {
                "doc_id": self._cursor.doc_id,
                "para":   self._cursor.paragraph_idx,
                "token":  self._cursor.token_idx,
                "zoom":   self._cursor.zoom.name,
            },
        }

    # ── Вспомогательные ───────────────────────────────────────────────────────

    def _get_paragraph(self, doc: CorpusEntry, idx: int) -> Optional[Paragraph]:
        if 0 <= idx < len(doc.paragraphs):
            return doc.paragraphs[idx]
        return None
