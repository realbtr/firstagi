"""
tests/test_curriculum_index.py — тесты для CurriculumIndex и 3-tier ContextBroker.

Покрытие (24 теста):
  TestFTSSearch          (8)  — fts_search: базовый поиск, OR-логика, пустой запрос,
                                  Unicode/кириллица, top_n ограничение, нет совпадений
  TestCurriculumIndex    (6)  — lookup: запрос через ContextQuery, missing_hint,
                                  пустой хинт, нет совпадений
  TestContextBrokerTier2 (10) — 3-tier: tier1 hit, tier2 hit, tier3 fallback,
                                  tick tier1/tier2/tier3, stats, curriculum=None
"""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from data.gen_base import GenBaseDB
from drivers.context_broker import (
    ContextBroker,
    CurriculumIndex,
    SourceTextRegistry,
)


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _tmp_db() -> GenBaseDB:
    """Создать GenBaseDB во временном файле."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return GenBaseDB(path=Path(tmp.name))


def _mock_query(trigger: str, hint: str = "?") -> MagicMock:
    q = MagicMock()
    q.trigger_token = trigger
    q.missing_hint = hint
    return q


def _mock_teaching_log() -> MagicMock:
    tl = MagicMock()
    tl.peek_queries.return_value = []
    tl.pending_query_count.return_value = 0
    return tl


# ══════════════════════════════════════════════════════════════════════════════
# TestFTSSearch
# ══════════════════════════════════════════════════════════════════════════════

class TestFTSSearch:
    def _db_with_texts(self, texts):
        db = _tmp_db()
        for t in texts:
            db.log_text(t, origin="test")
        return db

    def test_basic_match(self):
        db = self._db_with_texts(["кот сидит на крыше", "пёс бежит по полю"])
        result = db.fts_search("кот")
        assert any("кот" in r for r in result)

    def test_or_logic_returns_both(self):
        db = self._db_with_texts(["кот сидит", "пёс бежит"])
        result = db.fts_search("кот пёс")
        assert len(result) == 2

    def test_empty_query_returns_empty(self):
        db = self._db_with_texts(["что-то важное"])
        assert db.fts_search("") == []

    def test_single_char_words_ignored(self):
        # Слова длиной <= 1 пропускаются
        db = self._db_with_texts(["a b c"])
        # запрос состоит только из односимвольных слов → пустой fts_query
        assert db.fts_search("a b c") == []

    def test_top_n_limits_results(self):
        texts = [f"слово{i} текст" for i in range(10)]
        db = self._db_with_texts(texts)
        result = db.fts_search("текст", top_n=3)
        assert len(result) <= 3

    def test_no_match_returns_empty(self):
        db = self._db_with_texts(["совершенно другой текст"])
        assert db.fts_search("несуществующее слово xyz") == []

    def test_cyrillic_unicode(self):
        db = self._db_with_texts(["медведь гуляет по лесу", "лось прыгает"])
        result = db.fts_search("лесу")
        assert any("лесу" in r for r in result)

    def test_fts_after_log_text(self):
        db = _tmp_db()
        db.log_text("утро туманное утро седое", origin="poem")
        result = db.fts_search("туманное")
        assert len(result) == 1
        assert "туманное" in result[0]


# ══════════════════════════════════════════════════════════════════════════════
# TestCurriculumIndex
# ══════════════════════════════════════════════════════════════════════════════

class TestCurriculumIndex:
    def _setup(self, texts):
        db = _tmp_db()
        for t in texts:
            db.log_text(t, origin="curriculum")
        return db, CurriculumIndex(db)

    def test_lookup_trigger_token(self):
        db, ci = self._setup(["лес густой и тёмный", "поле широкое"])
        q = _mock_query("лес")
        results = ci.lookup(q)
        assert any("лес" in r for r in results)

    def test_lookup_uses_missing_hint(self):
        db, ci = self._setup(["берёза стоит у реки", "дуб растёт в лесу"])
        q = _mock_query("берёза", hint="реки")
        results = ci.lookup(q)
        assert any("реки" in r for r in results)

    def test_lookup_ignores_empty_hint(self):
        db, ci = self._setup(["гора высокая снежная"])
        q = _mock_query("гора", hint="?")
        results = ci.lookup(q)
        assert any("гора" in r for r in results)

    def test_lookup_no_match(self):
        db, ci = self._setup(["лес и поле"])
        q = _mock_query("космос", hint="ракета")
        assert ci.lookup(q) == []

    def test_top_n_respected(self):
        texts = [f"слово{i} важное" for i in range(10)]
        db, ci = self._setup(texts)
        q = _mock_query("важное")
        results = ci.lookup(q, top_n=2)
        assert len(results) <= 2

    def test_returns_list(self):
        db, ci = self._setup(["что-то"])
        q = _mock_query("что-то")
        result = ci.lookup(q)
        assert isinstance(result, list)


# ══════════════════════════════════════════════════════════════════════════════
# TestContextBrokerTier2
# ══════════════════════════════════════════════════════════════════════════════

class TestContextBrokerTier2:
    def _setup(self, registry_texts=(), curriculum_texts=()):
        db = _tmp_db()
        for t in curriculum_texts:
            db.log_text(t, origin="curriculum")
        ci = CurriculumIndex(db)
        tl = _mock_teaching_log()
        reg = SourceTextRegistry()
        for t in registry_texts:
            reg.register(t)
        broker = ContextBroker(teaching_log=tl, registry=reg, curriculum=ci)
        return broker, tl

    def test_tier1_hit_returns_true(self):
        broker, _ = self._setup(registry_texts=["медведь в лесу"])
        driver = MagicMock()
        q = _mock_query("медведь")
        assert broker.handle_query(q, driver) is True
        driver.load_buffer.assert_called()

    def test_tier2_hit_returns_true_when_tier1_misses(self):
        broker, tl = self._setup(curriculum_texts=["орёл летит высоко"])
        driver = MagicMock()
        q = _mock_query("орёл")
        assert broker.handle_query(q, driver) is True
        tl.push_query.assert_not_called()

    def test_tier3_fallback_when_both_miss(self):
        broker, tl = self._setup()
        driver = MagicMock()
        q = _mock_query("несуществующий")
        assert broker.handle_query(q, driver) is False
        tl.push_query.assert_called_once_with(q)

    def test_curriculum_none_falls_to_tier3(self):
        tl = _mock_teaching_log()
        broker = ContextBroker(teaching_log=tl, curriculum=None)
        q = _mock_query("что-то")
        assert broker.handle_query(q, None) is False
        tl.push_query.assert_called_once()

    def test_stats_includes_curriculum_hits(self):
        broker, _ = self._setup(curriculum_texts=["лось в поле"])
        q = _mock_query("лось")
        broker.handle_query(q, driver=None)
        s = broker.stats()
        assert "curriculum_hits" in s
        assert s["curriculum_hits"] == 1

    def test_stats_tier1_hit(self):
        broker, _ = self._setup(registry_texts=["волк бежит"])
        q = _mock_query("волк")
        broker.handle_query(q, driver=None)
        s = broker.stats()
        assert s["local_hits"] == 1
        assert s["curriculum_hits"] == 0

    def test_tick_tier2_resolves_query(self):
        db = _tmp_db()
        db.log_text("рысь живёт в тайге", origin="curriculum")
        ci = CurriculumIndex(db)
        tl = _mock_teaching_log()
        tl.peek_queries.return_value = [_mock_query("рысь")]
        broker = ContextBroker(teaching_log=tl, curriculum=ci)
        resolved = broker.tick()
        assert resolved == 1
        assert broker._curriculum_hits == 1

    def test_tick_tier3_stays_pending(self):
        broker, tl = self._setup()
        tl.peek_queries.return_value = [_mock_query("несуществующий")]
        resolved = broker.tick()
        assert resolved == 0
        tl.push_query.assert_called()

    def test_handle_query_no_driver_still_counts(self):
        broker, _ = self._setup(curriculum_texts=["туман над рекой"])
        q = _mock_query("туман")
        result = broker.handle_query(q, driver=None)
        assert result is True
        assert broker._curriculum_hits == 1

    def test_repr_unchanged(self):
        broker, _ = self._setup()
        r = repr(broker)
        assert "ContextBroker" in r
