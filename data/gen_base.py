"""
GenBaseDB — постоянное SQLite-хранилище базы обобщений и истории обучения.

Схема:
  gens            — снимки Gen (обновляются при каждом checkpoint)
  training_runs   — журнал тренировочных сессий
  run_snapshots   — состояние базы по проходам (n_new, avg_sig, mr)
  experiments     — гипотезы H1-H15+ и их результаты
  speech_log      — лог канала B (SpeechDriver наблюдения)

Использование:
    from data.gen_base import GenBaseDB
    db = GenBaseDB()               # открыть/создать data/gen_base.db
    db.checkpoint(system.base)     # сохранить текущее состояние базы Gen
    db.log_run("serial", passes=100, mr=0.92)
    db.log_experiment("H15", "CONFIRMED", {"plateau_pass": 6})
    db.close()

Запуск инспектора:
    py -X utf8 data/gen_base.py --stats
    py -X utf8 data/gen_base.py --top 10
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from core.generalization import GeneralizationBase

# ─── Путь к базе данных ───────────────────────────────────────────────────────
_DB_PATH = Path(__file__).parent / "gen_base.db"


# ══════════════════════════════════════════════════════════════════════════════
# GenBaseDB
# ══════════════════════════════════════════════════════════════════════════════

class GenBaseDB:
    """
    SQLite-хранилище для постоянного накопления данных FirstAGI.

    Потокобезопасен для одного соединения. Для параллельного доступа
    создавать отдельные экземпляры.
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = path or _DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._ensure_schema()

    # ------------------------------------------------------------------
    # Схема
    # ------------------------------------------------------------------

    def _ensure_schema(self) -> None:
        c = self._conn.cursor()
        c.executescript("""
        CREATE TABLE IF NOT EXISTS gens (
            gen_id       TEXT    PRIMARY KEY,
            label        TEXT,
            chain_len    INTEGER,
            chain_json   TEXT,
            significance REAL,
            success      INTEGER,
            stop         INTEGER,
            first_seen   TEXT,
            last_updated TEXT
        );

        CREATE TABLE IF NOT EXISTS training_runs (
            run_id       TEXT    PRIMARY KEY,
            corpus_name  TEXT,
            n_passes     INTEGER,
            base_size    INTEGER,
            final_mr     REAL,
            duration_s   REAL,
            started_at   TEXT,
            notes        TEXT
        );

        CREATE TABLE IF NOT EXISTS run_snapshots (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id       TEXT,
            pass_num     INTEGER,
            base_size    INTEGER,
            n_new        INTEGER,
            avg_sig      REAL,
            avg_mi       REAL,
            mr           REAL,
            step         INTEGER,
            recorded_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS experiments (
            exp_id       TEXT    PRIMARY KEY,
            hypothesis   TEXT,
            status       TEXT,
            key_metric   TEXT,
            metrics_json TEXT,
            notes        TEXT,
            recorded_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS speech_log (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id   TEXT,
            token_label  TEXT,
            outcome_tag  TEXT,
            text         TEXT,
            confidence   REAL,
            is_surprise  INTEGER,
            new_gen_hint TEXT,
            recorded_at  TEXT
        );

        CREATE TABLE IF NOT EXISTS text_registry (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id    TEXT,
            text         TEXT    NOT NULL,
            origin       TEXT,
            recorded_at  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_text_origin  ON text_registry(origin);
        CREATE INDEX IF NOT EXISTS idx_text_time    ON text_registry(recorded_at DESC);

        CREATE VIRTUAL TABLE IF NOT EXISTS curriculum_fts
        USING fts5(text, content='text_registry', content_rowid='id',
                   tokenize='unicode61');

        CREATE TRIGGER IF NOT EXISTS text_registry_ai
        AFTER INSERT ON text_registry BEGIN
            INSERT INTO curriculum_fts(rowid, text) VALUES (new.id, new.text);
        END;

        CREATE TRIGGER IF NOT EXISTS text_registry_ad
        AFTER DELETE ON text_registry BEGIN
            INSERT INTO curriculum_fts(curriculum_fts, rowid, text)
            VALUES ('delete', old.id, old.text);
        END;

        CREATE INDEX IF NOT EXISTS idx_gens_sig      ON gens(significance DESC);
        CREATE INDEX IF NOT EXISTS idx_gens_chain    ON gens(chain_len);
        CREATE INDEX IF NOT EXISTS idx_snap_run      ON run_snapshots(run_id, pass_num);
        CREATE INDEX IF NOT EXISTS idx_speech_sess   ON speech_log(session_id);
        """)
        self._conn.commit()

        # Миграция: добавить колонки связей гетерархии (безопасно для старых БД)
        for col_def in (
            "ALTER TABLE gens ADD COLUMN parent_ids_json TEXT DEFAULT '[]'",
            "ALTER TABLE gens ADD COLUMN child_ids_json  TEXT DEFAULT '[]'",
        ):
            try:
                self._conn.execute(col_def)
                self._conn.commit()
            except sqlite3.OperationalError:
                pass  # колонка уже существует

    # ------------------------------------------------------------------
    # Gen checkpoint
    # ------------------------------------------------------------------

    def checkpoint(self, base: "GeneralizationBase", batch_size: int = 500) -> int:
        """
        Сохранить/обновить все Gen из base в таблицу gens.

        Возвращает число затронутых строк.
        """
        now = _ts()
        rows = []
        for g in base.all():
            chain = [str(f) for f in g.feature_chain]
            rows.append((
                g.gen_id,
                g.label or "",
                len(g.feature_chain),
                json.dumps(chain, ensure_ascii=False),
                round(g.significance, 6),
                g.success_count,
                g.stop_count,
                json.dumps(g.parent_ids, ensure_ascii=False),
                json.dumps(g.child_ids,  ensure_ascii=False),
                now,  # first_seen — перезаписывается только при INSERT
                now,  # last_updated
            ))

        c = self._conn.cursor()
        affected = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            c.executemany("""
                INSERT INTO gens
                    (gen_id, label, chain_len, chain_json, significance,
                     success, stop, parent_ids_json, child_ids_json,
                     first_seen, last_updated)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(gen_id) DO UPDATE SET
                    label           = excluded.label,
                    chain_len       = excluded.chain_len,
                    chain_json      = excluded.chain_json,
                    significance    = excluded.significance,
                    success         = excluded.success,
                    stop            = excluded.stop,
                    parent_ids_json = excluded.parent_ids_json,
                    child_ids_json  = excluded.child_ids_json,
                    last_updated    = excluded.last_updated
            """, batch)
            affected += c.rowcount
        self._conn.commit()
        return affected

    def load(self, base: "GeneralizationBase") -> int:
        """
        Восстановить GeneralizationBase из БД («холодный старт»).

        Шаг 1: создаёт все Gen и добавляет их в base.
        Шаг 2: восстанавливает связи гетерархии через base.link().

        Возвращает число загруженных Gen.
        """
        from core.generalization import Generalization

        rows = self._conn.execute(
            "SELECT gen_id, label, chain_json, success, stop, "
            "       parent_ids_json, child_ids_json "
            "FROM gens"
        ).fetchall()

        # Шаг 1: восстановить Gen без связей
        for row in rows:
            chain = json.loads(row["chain_json"] or "[]")
            gen = Generalization(
                gen_id        = row["gen_id"],
                label         = row["label"] or None,
                feature_chain = chain,
                success_count = row["success"],
                stop_count    = row["stop"],
            )
            base.add(gen)

        # Шаг 2: восстановить связи гетерархии
        # Итерируем только по child_ids чтобы не дублировать вызовы link()
        for row in rows:
            child_ids = json.loads(row["child_ids_json"] or "[]")
            for child_id in child_ids:
                base.link(row["gen_id"], child_id)

        return len(rows)

    # ------------------------------------------------------------------
    # Training runs
    # ------------------------------------------------------------------

    def start_run(
        self,
        corpus_name: str,
        notes: str = "",
    ) -> str:
        """Начать новую тренировочную сессию. Возвращает run_id."""
        run_id = f"run_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
        self._conn.execute("""
            INSERT INTO training_runs
                (run_id, corpus_name, n_passes, base_size, final_mr,
                 duration_s, started_at, notes)
            VALUES (?,?,0,0,0.0,0.0,?,?)
        """, (run_id, corpus_name, _ts(), notes))
        self._conn.commit()
        return run_id

    def finish_run(
        self,
        run_id: str,
        n_passes: int,
        base_size: int,
        final_mr: float,
        duration_s: float,
    ) -> None:
        """Завершить тренировочную сессию."""
        self._conn.execute("""
            UPDATE training_runs
            SET n_passes=?, base_size=?, final_mr=?, duration_s=?
            WHERE run_id=?
        """, (n_passes, base_size, round(final_mr, 4), round(duration_s, 2), run_id))
        self._conn.commit()

    def log_snapshot(
        self,
        run_id: str,
        pass_num: int,
        base_size: int,
        n_new: int,
        avg_sig: float,
        avg_mi: float,
        mr: float,
        step: int,
    ) -> None:
        """Записать снимок состояния в середине тренировки."""
        self._conn.execute("""
            INSERT INTO run_snapshots
                (run_id, pass_num, base_size, n_new, avg_sig, avg_mi, mr, step, recorded_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (run_id, pass_num, base_size, n_new,
              round(avg_sig, 4), round(avg_mi, 2), round(mr, 4), step, _ts()))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Experiments
    # ------------------------------------------------------------------

    def log_experiment(
        self,
        exp_id: str,
        hypothesis: str,
        status: str,
        key_metric: str = "",
        metrics: Optional[Dict[str, Any]] = None,
        notes: str = "",
    ) -> None:
        """
        Записать результат эксперимента.

        status: "CONFIRMED" | "REFUTED" | "PARTIAL"
        """
        self._conn.execute("""
            INSERT INTO experiments
                (exp_id, hypothesis, status, key_metric, metrics_json, notes, recorded_at)
            VALUES (?,?,?,?,?,?,?)
            ON CONFLICT(exp_id) DO UPDATE SET
                status       = excluded.status,
                key_metric   = excluded.key_metric,
                metrics_json = excluded.metrics_json,
                notes        = excluded.notes,
                recorded_at  = excluded.recorded_at
        """, (
            exp_id, hypothesis, status, key_metric,
            json.dumps(metrics or {}, ensure_ascii=False),
            notes, _ts(),
        ))
        self._conn.commit()

    # ------------------------------------------------------------------
    # Speech log
    # ------------------------------------------------------------------

    def log_speech(
        self,
        session_id: str,
        observations,   # List[Observation] из SpeechDriver
    ) -> None:
        """Сохранить наблюдения канала B в базу."""
        now = _ts()
        rows = [
            (session_id, o.token_label, o.outcome_tag, o.text,
             round(o.confidence, 4), int(o.is_surprise),
             o.new_gen_hint or "", now)
            for o in observations
        ]
        self._conn.executemany("""
            INSERT INTO speech_log
                (session_id, token_label, outcome_tag, text, confidence,
                 is_surprise, new_gen_hint, recorded_at)
            VALUES (?,?,?,?,?,?,?,?)
        """, rows)
        self._conn.commit()

    def log_text(
        self,
        text: str,
        source_id: str = "",
        origin: str = "",
    ) -> None:
        """Сохранить исходный текст для последующего извлечения контекста."""
        self._conn.execute("""
            INSERT INTO text_registry (source_id, text, origin, recorded_at)
            VALUES (?,?,?,?)
        """, (source_id, text, origin, _ts()))
        self._conn.commit()

    def recent_texts(
        self,
        n: int = 20,
        origin: Optional[str] = None,
    ) -> List[Dict]:
        """Последние n текстов из реестра, опционально фильтрованные по origin."""
        if origin:
            c = self._conn.execute("""
                SELECT id, source_id, text, origin, recorded_at
                FROM text_registry WHERE origin=?
                ORDER BY recorded_at DESC LIMIT ?
            """, (origin, n))
        else:
            c = self._conn.execute("""
                SELECT id, source_id, text, origin, recorded_at
                FROM text_registry ORDER BY recorded_at DESC LIMIT ?
            """, (n,))
        return [dict(r) for r in c.fetchall()]

    def fts_search(
        self,
        query_text: str,
        top_n: int = 5,
    ) -> List[str]:
        """
        Полнотекстовый поиск по corpus_fts (FTS5 индекс text_registry).

        query_text разбивается на слова; каждое слово ищется через OR.
        Возвращает до top_n текстов, отсортированных по релевантности (rank).
        """
        words = [w for w in re.split(r"[\s,.\-!?;:\"'()«»]+", query_text.lower()) if len(w) > 1]
        if not words:
            return []
        fts_query = " OR ".join(f'"{w}"' for w in words)
        try:
            c = self._conn.execute(
                """
                SELECT t.text
                FROM text_registry t
                WHERE t.id IN (
                    SELECT rowid FROM curriculum_fts
                    WHERE curriculum_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                )
                """,
                (fts_query, top_n),
            )
            return [row[0] for row in c.fetchall()]
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Запросы
    # ------------------------------------------------------------------

    def top_gens(self, n: int = 20) -> List[Dict]:
        c = self._conn.execute("""
            SELECT gen_id, label, chain_len, significance, success, stop
            FROM gens ORDER BY significance DESC LIMIT ?
        """, (n,))
        return [dict(r) for r in c.fetchall()]

    def stats(self) -> Dict[str, Any]:
        c = self._conn.cursor()
        c.execute("SELECT COUNT(*), AVG(significance), MAX(significance) FROM gens")
        cnt, avg_sig, max_sig = c.fetchone()
        c.execute("SELECT COUNT(*) FROM training_runs")
        n_runs = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM experiments")
        n_exp = c.fetchone()[0]
        c.execute("SELECT status, COUNT(*) FROM experiments GROUP BY status")
        exp_status = {row[0]: row[1] for row in c.fetchall()}
        c.execute("""
            SELECT chain_len, COUNT(*), AVG(significance)
            FROM gens GROUP BY chain_len ORDER BY chain_len
        """)
        chain_dist = [{"chain_len": r[0], "count": r[1], "avg_sig": round(r[2], 4)}
                      for r in c.fetchall()]
        return {
            "total_gens":    cnt or 0,
            "avg_sig":       round(avg_sig or 0, 4),
            "max_sig":       round(max_sig or 0, 4),
            "training_runs": n_runs,
            "experiments":   n_exp,
            "exp_status":    exp_status,
            "chain_dist":    chain_dist,
        }

    def search(self, query: str, limit: int = 20) -> List[Dict]:
        """Поиск Gen по label или chain_json (LIKE-запрос)."""
        q = f"%{query}%"
        c = self._conn.execute("""
            SELECT gen_id, label, chain_len, significance, chain_json
            FROM gens
            WHERE label LIKE ? OR chain_json LIKE ?
            ORDER BY significance DESC LIMIT ?
        """, (q, q, limit))
        return [dict(r) for r in c.fetchall()]

    def runs(self, limit: int = 20) -> List[Dict]:
        c = self._conn.execute("""
            SELECT run_id, corpus_name, n_passes, base_size, final_mr, duration_s, started_at
            FROM training_runs ORDER BY started_at DESC LIMIT ?
        """, (limit,))
        return [dict(r) for r in c.fetchall()]

    def experiments(self) -> List[Dict]:
        c = self._conn.execute("""
            SELECT exp_id, hypothesis, status, key_metric, recorded_at
            FROM experiments ORDER BY recorded_at DESC
        """)
        return [dict(r) for r in c.fetchall()]

    def snapshots(self, run_id: str) -> List[Dict]:
        c = self._conn.execute("""
            SELECT pass_num, base_size, n_new, avg_sig, mr, step
            FROM run_snapshots WHERE run_id=? ORDER BY pass_num
        """, (run_id,))
        return [dict(r) for r in c.fetchall()]

    def chain_filter(self, min_len: int, max_len: int, limit: int = 50) -> List[Dict]:
        c = self._conn.execute("""
            SELECT gen_id, label, chain_len, significance
            FROM gens WHERE chain_len BETWEEN ? AND ?
            ORDER BY significance DESC LIMIT ?
        """, (min_len, max_len, limit))
        return [dict(r) for r in c.fetchall()]

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def close(self) -> None:
        self._conn.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def _ts() -> str:
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
