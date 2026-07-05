"""
ContextBroker — брокер контекста за горизонтом восприятия.

Когда текстовый драйвер уже не видит исходного текста, а система
встречает незнакомые паттерны, нужен механизм «повернуть голову»:

  1. SpeechDriver обнаруживает разрыв (detect_context_gap)
  2. SpeechDriver формулирует запрос  (formulate_query)
  3. ContextBroker: находит в реестре → грузит в буфер драйвера
                   ИЛИ отправляет запрос в TeachingLog для LLM
  4. LLM-учитель возвращает нужный текст через обычный канал TEACH

Аналогия из системного мышления:
  Драйвер = сенсор с ограниченным полем зрения.
  ContextBroker = «мышцы поворота внимания».
  TeachingLog  = канал связи с долговременной памятью учителя.

Использование:
    broker = ContextBroker(teaching_log=system.teaching_log, db=db)
    broker.register_source(text, source_id="text_1", origin="serial")

    # После каждого шага:
    query = speech.detect_context_gap(result, lead_gen, lead_sig)
    if query:
        found = broker.handle_query(query, driver)
        if not found:
            teaching_log.push_query(query)   # уйдёт к LLM на следующем тике
"""
from __future__ import annotations

import re
from typing import List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.teacher import TeachingLog
    from core.budget import QuestionBudget
    from drivers.speech_driver import ContextQuery
    from drivers.base import PeripheralDriver
    from data.gen_base import GenBaseDB


# ──────────────────────────────────────────────────────────────────────────────
# CurriculumIndex — tier 2: FTS5 поиск по всему корпусу
# ──────────────────────────────────────────────────────────────────────────────

class CurriculumIndex:
    """
    Уровень 2 брокера контекста: полнотекстовый поиск по всему
    накопленному корпусу через FTS5 (SQLite virtual table).

    Обёртка вокруг GenBaseDB.fts_search(), не хранит тексты сама.
    """

    def __init__(self, db: "GenBaseDB") -> None:
        self._db = db

    def lookup(
        self,
        query: "ContextQuery",
        top_n: int = 3,
    ) -> List[str]:
        """Найти тексты, релевантные запросу, через FTS5."""
        terms = query.trigger_token
        if query.missing_hint and query.missing_hint != "?":
            terms = f"{terms} {query.missing_hint}"
        return self._db.fts_search(terms, top_n=top_n)


# ──────────────────────────────────────────────────────────────────────────────
# Реестр исходных текстов
# ──────────────────────────────────────────────────────────────────────────────

class SourceTextRegistry:
    """
    Хранилище исходных текстов.

    Поддерживает два режима:
      • in-memory (по умолчанию) — для тестов и коротких сессий
      • + SQLite через GenBaseDB  — для долгосрочного накопления

    Поиск в реестре — простой keyword match по токенам запроса.
    Семантический поиск (embedding similarity) — задача для будущей версии.
    """

    def __init__(self, db: Optional["GenBaseDB"] = None) -> None:
        self._db = db
        self._memory: List[dict] = []   # [{source_id, text, origin}, ...]

    def register(
        self,
        text: str,
        source_id: str = "",
        origin: str = "",
    ) -> None:
        """Зарегистрировать исходный текст."""
        self._memory.append({"source_id": source_id, "text": text, "origin": origin})
        # Ограничить in-memory буфер последними 500 текстами
        if len(self._memory) > 500:
            self._memory = self._memory[-500:]
        if self._db is not None:
            self._db.log_text(text, source_id=source_id, origin=origin)

    def lookup(
        self,
        query: "ContextQuery",
        top_n: int = 3,
    ) -> List[str]:
        """
        Найти тексты, релевантные запросу.

        Использует token overlap: считает, сколько слов из
        query.missing_hint и query.trigger_token встречается в тексте.
        Возвращает топ-N по релевантности.
        """
        keywords = _tokenize(query.trigger_token)
        if query.missing_hint and query.missing_hint != "?":
            keywords += _tokenize(query.missing_hint)

        # Получить все тексты: сначала in-memory (свежие), потом из БД
        candidates = list(self._memory)
        if self._db is not None:
            db_rows = self._db.recent_texts(n=200)
            seen = {e["text"] for e in candidates}
            for row in db_rows:
                if row["text"] not in seen:
                    candidates.append({"text": row["text"],
                                       "source_id": row.get("source_id", ""),
                                       "origin": row.get("origin", "")})

        if not candidates or not keywords:
            return []

        # Ранжирование по количеству совпадений ключевых слов
        scored = []
        for entry in candidates:
            text_tokens = set(_tokenize(entry["text"]))
            score = sum(1 for kw in keywords if kw in text_tokens)
            if score > 0:
                scored.append((score, entry["text"]))

        scored.sort(key=lambda x: -x[0])
        return [text for _, text in scored[:top_n]]

    def size(self) -> int:
        return len(self._memory)


# ──────────────────────────────────────────────────────────────────────────────
# ContextBroker
# ──────────────────────────────────────────────────────────────────────────────

class ContextBroker:
    """
    Брокер контекста: связывает горизонт восприятия драйвера,
    реестр исходных текстов и TeachingLog.

    Три уровня поиска:

      TIER1  — SourceTextRegistry (in-memory 500 + БД 200 последних)
      TIER2  — CurriculumIndex (FTS5 по всему накопленному корпусу)
      TIER3  — TeachingLog → LLM (бюджетируемые удалённые запросы)

    Параметры
    ----------
    teaching_log : TeachingLog          — для отправки запросов к LLM
    registry     : SourceTextRegistry   — tier 1
    curriculum   : CurriculumIndex      — tier 2 (опционально)
    db           : GenBaseDB            — создаёт SourceTextRegistry если registry=None
    budget       : QuestionBudget       — суточный лимит tier-3 запросов (опционально)
    """

    def __init__(
        self,
        teaching_log: "TeachingLog",
        registry: Optional[SourceTextRegistry] = None,
        db: Optional["GenBaseDB"] = None,
        curriculum: Optional["CurriculumIndex"] = None,
        budget: Optional["QuestionBudget"] = None,
    ) -> None:
        self.teaching_log = teaching_log
        self.registry = registry or SourceTextRegistry(db=db)
        self.curriculum = curriculum
        self.budget = budget
        self._handled_count: int = 0
        self._local_hits: int = 0
        self._curriculum_hits: int = 0
        self._remote_queries: int = 0
        self._budget_blocked: int = 0

    def register_source(
        self,
        text: str,
        source_id: str = "",
        origin: str = "",
    ) -> None:
        """Зарегистрировать исходный текст сессии обучения в реестре."""
        self.registry.register(text, source_id=source_id, origin=origin)

    def handle_query(
        self,
        query: "ContextQuery",
        driver: Optional["PeripheralDriver"] = None,
    ) -> bool:
        """
        Обработать запрос на восстановление контекста.

        Алгоритм:
          1. TIER1: ищем в SourceTextRegistry (in-memory + БД recent).
          2. TIER2: если не нашли — ищем в CurriculumIndex (FTS5).
          3. Если нашли (tier1 или tier2) И драйвер передан → грузим в буфер.
          4. TIER3: иначе → отправляем в TeachingLog для LLM.

        Возвращает True если нашёл локально (tier1/tier2), False если ушёл к LLM.
        """
        self._handled_count += 1

        # Tier 1
        found_texts = self.registry.lookup(query, top_n=3)
        if found_texts:
            if driver is not None:
                for text in found_texts:
                    driver.load_buffer(text)
            self._local_hits += 1
            return True

        # Tier 2
        if self.curriculum is not None:
            found_texts = self.curriculum.lookup(query, top_n=3)
            if found_texts:
                if driver is not None:
                    for text in found_texts:
                        driver.load_buffer(text)
                self._curriculum_hits += 1
                return True

        # Tier 3: LLM (проверяем бюджет)
        if self.budget is not None and not self.budget.consume():
            self._budget_blocked += 1
            return False
        self.teaching_log.push_query(query)
        self._remote_queries += 1
        return False

    def tick(self) -> int:
        """
        Обработать все накопленные запросы из TeachingLog.

        Для каждого ContextQuery пытается найти текст локально;
        если нашёл — кладёт в pending_content (driver его заберёт сам).
        Нерешённые запросы остаются в очереди для LLM.

        Возвращает число локально решённых запросов.
        """
        queries = self.teaching_log.peek_queries()
        resolved = 0
        still_pending = []

        for q in queries:
            found_texts = self.registry.lookup(q, top_n=2)
            if found_texts:
                for text in found_texts:
                    self.teaching_log.push_content(text)
                resolved += 1
                self._local_hits += 1
                continue

            if self.curriculum is not None:
                found_texts = self.curriculum.lookup(q, top_n=2)
                if found_texts:
                    for text in found_texts:
                        self.teaching_log.push_content(text)
                    resolved += 1
                    self._curriculum_hits += 1
                    continue

            # Tier 3: LLM (проверяем бюджет)
            if self.budget is not None and not self.budget.consume():
                self._budget_blocked += 1
                continue
            still_pending.append(q)

        # Заменяем очередь на нерешённые запросы → уйдут к LLM
        self.teaching_log.clear_queries()
        for q in still_pending:
            self.teaching_log.push_query(q)
            self._remote_queries += 1

        return resolved

    def stats(self) -> dict:
        s = {
            "handled":          self._handled_count,
            "local_hits":       self._local_hits,
            "curriculum_hits":  self._curriculum_hits,
            "remote_queries":   self._remote_queries,
            "budget_blocked":   self._budget_blocked,
            "registry_size":    self.registry.size(),
            "pending_queries":  self.teaching_log.pending_query_count(),
        }
        if self.budget is not None:
            s["budget_remaining"] = self.budget.remaining()
        return s

    def __repr__(self) -> str:
        return (
            f"ContextBroker("
            f"registry={self.registry.size()}, "
            f"local_hits={self._local_hits}, "
            f"remote={self._remote_queries})"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Утилиты
# ──────────────────────────────────────────────────────────────────────────────

def _tokenize(text: str) -> List[str]:
    """Простая токенизация для keyword match."""
    return [w.lower() for w in re.split(r"[\s,.\-!?;:\"'()«»]+", text) if w]
