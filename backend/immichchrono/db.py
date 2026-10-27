from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  token TEXT NOT NULL,
  user_id TEXT NOT NULL,
  name TEXT,
  email TEXT,
  is_admin INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  checked_at TEXT
);
CREATE TABLE IF NOT EXISTS assets (
  id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  file_name TEXT,
  path TEXT,
  type TEXT,
  date_original TEXT,
  local_dt TEXT,
  uploaded_at TEXT,
  make TEXT,
  model TEXT,
  checksum TEXT,
  duplicate_id TEXT,
  updated_at TEXT,
  issues TEXT NOT NULL DEFAULT '[]',
  category TEXT,
  data TEXT NOT NULL,
  deep_checked INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (user_id, id)
);
CREATE INDEX IF NOT EXISTS assets_category ON assets(user_id, category);
CREATE TABLE IF NOT EXISTS suggestions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  source TEXT NOT NULL,
  proposed TEXT NOT NULL,
  precision TEXT NOT NULL,
  range_start TEXT,
  range_end TEXT,
  confidence REAL NOT NULL,
  explanation TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending',
  previous_date TEXT,
  created_at TEXT NOT NULL,
  applied_at TEXT
);
CREATE INDEX IF NOT EXISTS suggestions_status ON suggestions(user_id, status);
CREATE INDEX IF NOT EXISTS suggestions_asset ON suggestions(user_id, asset_id);
CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  status TEXT NOT NULL,
  phase TEXT,
  progress INTEGER NOT NULL DEFAULT 0,
  total INTEGER NOT NULL DEFAULT 0,
  message TEXT,
  stats TEXT NOT NULL DEFAULT '{}',
  started_at TEXT NOT NULL,
  finished_at TEXT
);
CREATE TABLE IF NOT EXISTS settings (
  user_id TEXT NOT NULL,
  key TEXT NOT NULL,
  value TEXT NOT NULL,
  PRIMARY KEY (user_id, key)
);
CREATE TABLE IF NOT EXISTS claude_usage (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id TEXT NOT NULL,
  asset_id TEXT NOT NULL,
  model TEXT NOT NULL,
  input_tokens INTEGER NOT NULL,
  output_tokens INTEGER NOT NULL,
  cost_usd REAL NOT NULL,
  created_at TEXT NOT NULL
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Database:
    """Thin thread-safe wrapper around one SQLite connection (WAL mode)."""

    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.RLock()
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(SCHEMA)

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            self._conn.execute("BEGIN")
            try:
                yield self._conn
            except BaseException:
                self._conn.execute("ROLLBACK")
                raise
            self._conn.execute("COMMIT")

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            return self._conn.execute(sql, tuple(params))

    def all(self, sql: str, params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql, tuple(params)).fetchall()]

    def one(self, sql: str, params: Iterable[Any] = ()) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
            return dict(row) if row else None

    def scalar(self, sql: str, params: Iterable[Any] = ()) -> Any:
        with self._lock:
            row = self._conn.execute(sql, tuple(params)).fetchone()
            return row[0] if row else None

    # --- settings -------------------------------------------------------
    def get_setting(self, user_id: str, key: str, default: Any = None) -> Any:
        v = self.scalar("SELECT value FROM settings WHERE user_id=? AND key=?", (user_id, key))
        return default if v is None else json.loads(v)

    def set_setting(self, user_id: str, key: str, value: Any) -> None:
        self.execute(
            "INSERT INTO settings(user_id,key,value) VALUES(?,?,?) "
            "ON CONFLICT(user_id,key) DO UPDATE SET value=excluded.value",
            (user_id, key, json.dumps(value)),
        )
