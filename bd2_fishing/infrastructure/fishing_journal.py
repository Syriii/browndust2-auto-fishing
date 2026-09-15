"""鱼获与待办共用事务；文件日志和诊断轮转不影响个人记录。"""

import sqlite3
import threading
from pathlib import Path


class FishingJournal:
    def __init__(self, path=None):
        self.lock = threading.RLock()
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS catches (
                id INTEGER PRIMARY KEY, run_id TEXT NOT NULL, round_id TEXT NOT NULL,
                caught_at TEXT NOT NULL, fish_id TEXT, name TEXT NOT NULL,
                location TEXT NOT NULL, size_cm REAL, size_kind TEXT NOT NULL,
                rarity TEXT NOT NULL, first_catch INTEGER NOT NULL,
                evidence BLOB, UNIQUE(run_id, round_id)
            );
            CREATE TABLE IF NOT EXISTS targets (
                fish_id TEXT NOT NULL, condition TEXT NOT NULL,
                PRIMARY KEY(fish_id, condition)
            );
            CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS catches_fish ON catches(fish_id);
        """)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(catches)")}
        for name, declaration in (
            ("stars", "INTEGER"),
            ("border_color", "TEXT NOT NULL DEFAULT 'unknown'"),
            ("new_record", "INTEGER NOT NULL DEFAULT 0"),
        ):
            if name not in columns:
                self.db.execute(f"ALTER TABLE catches ADD COLUMN {name} {declaration}")
        self.db.commit()
        self.revision = 0

    def targets(self):
        with self.lock:
            return [tuple(row) for row in self.db.execute("SELECT * FROM targets ORDER BY rowid")]

    def replace_targets(self, targets):
        with self.lock, self.db:
            self.db.execute("DELETE FROM targets")
            self.db.executemany("INSERT INTO targets VALUES (?, ?)", targets)
            self.db.execute("DELETE FROM state WHERE key='active_run'")
        self.revision += 1

    def begin_run(self, identity, targeted):
        with self.lock, self.db:
            self.db.execute(
                "INSERT OR REPLACE INTO state VALUES ('active_run', ?)",
                (identity if targeted else "",),
            )

    def record(self, event, evidence):
        with self.lock, self.db:
            duplicate = self.db.execute(
                "SELECT id FROM catches WHERE run_id=? AND round_id=?",
                (event["run_id"], event["round_id"]),
            ).fetchone()
            if duplicate:
                return False
            first = (
                bool(event["fish_id"])
                and not self.db.execute(
                    "SELECT 1 FROM catches WHERE fish_id=? LIMIT 1", (event["fish_id"],)
                ).fetchone()
            )
            self.db.execute(
                """INSERT INTO catches
                (run_id,round_id,caught_at,fish_id,name,location,size_cm,size_kind,
                 rarity,first_catch,evidence,stars,border_color,new_record)
                 VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    *[
                        event[k]
                        for k in (
                            "run_id",
                            "round_id",
                            "caught_at",
                            "fish_id",
                            "name",
                            "location",
                            "size_cm",
                            "size_kind",
                            "rarity",
                        )
                    ],
                    int(first),
                    evidence,
                    event.get("stars"),
                    event.get("border_color", "unknown"),
                    int(event.get("new_record", False)),
                ),
            )
            active = self.db.execute("SELECT value FROM state WHERE key='active_run'").fetchone()
            if active and active[0] == event["run_id"] and event["fish_id"]:
                self.db.execute(
                    "DELETE FROM targets WHERE fish_id=? AND condition IN ('any', ?)",
                    (event["fish_id"], event["size_kind"]),
                )
        self.revision += 1
        return True

    def history(self, category="all", before=None, limit=100, *, day=None):
        filters = {
            "all": "1",
            "first": "first_catch=1",
            "color": "rarity='legendary'",
            "max": "size_kind='max'",
            "min": "size_kind='min'",
        }
        where = filters[category]
        parameters = []
        if day == "unknown":
            where += " AND date(caught_at, 'localtime') IS NULL"
        elif day is not None:
            where += " AND date(caught_at, 'localtime') = ?"
            parameters.append(day)
        if before is not None:
            where += " AND id < ?"
            parameters.append(before)
        with self.lock:
            return [
                dict(row)
                for row in self.db.execute(
                    "SELECT id,caught_at,fish_id,name,location,size_cm,size_kind,rarity,first_catch,"
                    "stars,border_color,new_record "
                    f"FROM catches WHERE {where} ORDER BY julianday(caught_at) DESC, id DESC LIMIT ?",
                    (*parameters, limit),
                )
            ]

    def history_dates(self):
        with self.lock:
            return [
                row[0]
                for row in self.db.execute(
                    "SELECT DISTINCT date(caught_at, 'localtime') AS day FROM catches ORDER BY day DESC"
                )
            ]

    def evidence(self, identity):
        with self.lock:
            row = self.db.execute("SELECT evidence FROM catches WHERE id=?", (identity,)).fetchone()
            return row[0] if row else None

    def close(self):
        with self.lock:
            self.db.close()
