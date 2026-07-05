"""
tests/test_genbase_persistence.py — тесты для checkpoint/load (персистентность).

Покрытие (18 тестов):
  TestCheckpointHierarchy (6) — сохранение parent_ids / child_ids в checkpoint
  TestLoad                (8) — load(): Gen, счётчики, гетерархия, idempotence,
                                 пустая БД, поверх непустой base, load+train
  TestRoundtrip           (4) — полный цикл checkpoint → load → продолжить обучение
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from core.generalization import Generalization, GeneralizationBase
from data.gen_base import GenBaseDB


# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def _make_db(tmp_path: Path) -> GenBaseDB:
    return GenBaseDB(path=tmp_path / "test.db")


def _make_base_with_hierarchy() -> GeneralizationBase:
    """
    Простая гетерархия: parent → child1, child2 → grandchild
    """
    base = GeneralizationBase()
    parent = Generalization.new(feature_chain=["f1"], label="parent")
    child1 = Generalization.new(feature_chain=["f1", "f2"], label="child1")
    child2 = Generalization.new(feature_chain=["f1", "f3"], label="child2")
    grand  = Generalization.new(feature_chain=["f1", "f2", "f4"], label="grand")

    parent.success_count = 10
    parent.stop_count    = 2
    child1.success_count = 5
    child1.stop_count    = 1
    child2.success_count = 3
    grand.success_count  = 1

    base.add(parent)
    base.add(child1)
    base.add(child2)
    base.add(grand)

    base.link(parent.gen_id, child1.gen_id)
    base.link(parent.gen_id, child2.gen_id)
    base.link(child1.gen_id, grand.gen_id)

    return base, parent, child1, child2, grand


# ══════════════════════════════════════════════════════════════════════════════
# TestCheckpointHierarchy
# ══════════════════════════════════════════════════════════════════════════════

class TestCheckpointHierarchy:

    def test_checkpoint_saves_child_ids(self, tmp_path):
        db = _make_db(tmp_path)
        base, parent, child1, child2, grand = _make_base_with_hierarchy()
        db.checkpoint(base)

        row = db._conn.execute(
            "SELECT child_ids_json FROM gens WHERE gen_id=?", (parent.gen_id,)
        ).fetchone()
        import json
        saved = json.loads(row["child_ids_json"])
        assert child1.gen_id in saved
        assert child2.gen_id in saved

    def test_checkpoint_saves_parent_ids(self, tmp_path):
        db = _make_db(tmp_path)
        base, parent, child1, child2, grand = _make_base_with_hierarchy()
        db.checkpoint(base)

        row = db._conn.execute(
            "SELECT parent_ids_json FROM gens WHERE gen_id=?", (child1.gen_id,)
        ).fetchone()
        import json
        saved = json.loads(row["parent_ids_json"])
        assert parent.gen_id in saved

    def test_grandchild_parent_ids(self, tmp_path):
        db = _make_db(tmp_path)
        base, parent, child1, child2, grand = _make_base_with_hierarchy()
        db.checkpoint(base)

        row = db._conn.execute(
            "SELECT parent_ids_json FROM gens WHERE gen_id=?", (grand.gen_id,)
        ).fetchone()
        import json
        assert child1.gen_id in json.loads(row["parent_ids_json"])

    def test_leaf_has_empty_child_ids(self, tmp_path):
        db = _make_db(tmp_path)
        base, parent, child1, child2, grand = _make_base_with_hierarchy()
        db.checkpoint(base)

        row = db._conn.execute(
            "SELECT child_ids_json FROM gens WHERE gen_id=?", (grand.gen_id,)
        ).fetchone()
        import json
        assert json.loads(row["child_ids_json"]) == []

    def test_checkpoint_returns_count(self, tmp_path):
        db = _make_db(tmp_path)
        base, *_ = _make_base_with_hierarchy()
        n = db.checkpoint(base)
        assert n == 4

    def test_checkpoint_update_preserves_links(self, tmp_path):
        """Повторный checkpoint перезаписывает — связи не теряются."""
        db = _make_db(tmp_path)
        base, parent, child1, child2, grand = _make_base_with_hierarchy()
        db.checkpoint(base)
        parent.success_count += 5
        db.checkpoint(base)

        import json
        row = db._conn.execute(
            "SELECT child_ids_json, success FROM gens WHERE gen_id=?",
            (parent.gen_id,)
        ).fetchone()
        assert child1.gen_id in json.loads(row["child_ids_json"])
        assert row["success"] == 15


# ══════════════════════════════════════════════════════════════════════════════
# TestLoad
# ══════════════════════════════════════════════════════════════════════════════

class TestLoad:

    def test_load_restores_gen_count(self, tmp_path):
        db = _make_db(tmp_path)
        base, *_ = _make_base_with_hierarchy()
        db.checkpoint(base)

        restored = GeneralizationBase()
        n = db.load(restored)
        assert n == 4
        assert restored.size() == 4

    def test_load_restores_labels(self, tmp_path):
        db = _make_db(tmp_path)
        base, parent, *_ = _make_base_with_hierarchy()
        db.checkpoint(base)

        restored = GeneralizationBase()
        db.load(restored)
        gen = restored.get(parent.gen_id)
        assert gen is not None
        assert gen.label == "parent"

    def test_load_restores_counters(self, tmp_path):
        db = _make_db(tmp_path)
        base, parent, child1, *_ = _make_base_with_hierarchy()
        db.checkpoint(base)

        restored = GeneralizationBase()
        db.load(restored)
        assert restored.get(parent.gen_id).success_count == 10
        assert restored.get(parent.gen_id).stop_count    == 2
        assert restored.get(child1.gen_id).success_count == 5

    def test_load_restores_significance(self, tmp_path):
        db = _make_db(tmp_path)
        base, parent, *_ = _make_base_with_hierarchy()
        db.checkpoint(base)

        restored = GeneralizationBase()
        db.load(restored)
        gen = restored.get(parent.gen_id)
        assert abs(gen.significance - parent.significance) < 1e-6

    def test_load_restores_child_ids(self, tmp_path):
        db = _make_db(tmp_path)
        base, parent, child1, child2, grand = _make_base_with_hierarchy()
        db.checkpoint(base)

        restored = GeneralizationBase()
        db.load(restored)
        p = restored.get(parent.gen_id)
        assert child1.gen_id in p.child_ids
        assert child2.gen_id in p.child_ids

    def test_load_restores_parent_ids(self, tmp_path):
        db = _make_db(tmp_path)
        base, parent, child1, child2, grand = _make_base_with_hierarchy()
        db.checkpoint(base)

        restored = GeneralizationBase()
        db.load(restored)
        c = restored.get(child1.gen_id)
        assert parent.gen_id in c.parent_ids

    def test_load_empty_db(self, tmp_path):
        db = _make_db(tmp_path)
        restored = GeneralizationBase()
        n = db.load(restored)
        assert n == 0
        assert restored.size() == 0

    def test_load_idempotent(self, tmp_path):
        """Двойной load не дублирует связи."""
        db = _make_db(tmp_path)
        base, parent, child1, *_ = _make_base_with_hierarchy()
        db.checkpoint(base)

        restored = GeneralizationBase()
        db.load(restored)
        db.load(restored)  # второй раз
        p = restored.get(parent.gen_id)
        assert p.child_ids.count(child1.gen_id) == 1


# ══════════════════════════════════════════════════════════════════════════════
# TestRoundtrip
# ══════════════════════════════════════════════════════════════════════════════

class TestRoundtrip:

    def test_feature_chain_preserved(self, tmp_path):
        db = _make_db(tmp_path)
        base, parent, child1, *_ = _make_base_with_hierarchy()
        db.checkpoint(base)

        restored = GeneralizationBase()
        db.load(restored)
        assert restored.get(child1.gen_id).feature_chain == ["f1", "f2"]

    def test_grandchild_links_intact(self, tmp_path):
        db = _make_db(tmp_path)
        base, parent, child1, child2, grand = _make_base_with_hierarchy()
        db.checkpoint(base)

        restored = GeneralizationBase()
        db.load(restored)
        g = restored.get(grand.gen_id)
        assert child1.gen_id in g.parent_ids
        c = restored.get(child1.gen_id)
        assert grand.gen_id in c.child_ids

    def test_train_after_load(self, tmp_path):
        """После load можно добавлять новые Gen и делать новый checkpoint."""
        db = _make_db(tmp_path)
        base, parent, *_ = _make_base_with_hierarchy()
        db.checkpoint(base)

        restored = GeneralizationBase()
        db.load(restored)

        new_gen = Generalization.new(feature_chain=["f1", "f5"], label="new")
        new_gen.success_count = 2
        restored.add(new_gen)
        restored.link(parent.gen_id, new_gen.gen_id)

        db.checkpoint(restored)
        assert db._conn.execute("SELECT COUNT(*) FROM gens").fetchone()[0] == 5

    def test_old_db_migration(self, tmp_path):
        """Старая БД без колонок parent/child_ids — load работает без ошибок."""
        import sqlite3
        old_db_path = tmp_path / "old.db"
        conn = sqlite3.connect(str(old_db_path))
        conn.execute("""
            CREATE TABLE gens (
                gen_id TEXT PRIMARY KEY, label TEXT, chain_len INTEGER,
                chain_json TEXT, significance REAL, success INTEGER,
                stop INTEGER, first_seen TEXT, last_updated TEXT
            )""")
        conn.execute(
            "INSERT INTO gens VALUES (?,?,?,?,?,?,?,?,?)",
            ("gid1", "old", 1, '["f1"]', 0.8, 8, 2, "2024-01-01", "2024-01-01")
        )
        conn.commit()
        conn.close()

        # GenBaseDB.__init__ запустит миграцию
        db = GenBaseDB(path=old_db_path)
        restored = GeneralizationBase()
        n = db.load(restored)
        assert n == 1
        assert restored.get("gid1").success_count == 8
