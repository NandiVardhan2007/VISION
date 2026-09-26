"""
SQLite Persistent Storage for user preferences, memory facts, and conversation history.
"""

import sqlite3
from contextlib import contextmanager
from typing import List, Dict, Any, Optional, Iterator
from pathlib import Path
from vision.logger import logger

# Anchor the DB to the project root (not the CWD) so launching VISION from a
# different working directory doesn't silently create/point at a second, empty DB.
DB_PATH = Path(__file__).resolve().parents[2] / "vision_data.sqlite"


class Database:
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Connection that commits on success and always closes (Windows-safe)."""
        conn = sqlite3.connect(self.db_path, timeout=15.0)
        try:
            # WAL lets readers and a writer proceed concurrently and greatly
            # reduces "database is locked" errors under the thread-pool executor
            # that runs sync tools alongside the main loop.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    key TEXT UNIQUE,
                    value TEXT,
                    category TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

    def set_memory(self, key: str, value: str, category: str = "general"):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO memories (key, value, category)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value, category=excluded.category
            """, (key, value, category))

    def get_memory(self, key: str) -> Optional[str]:
        with self._connect() as conn:
            cur = conn.execute("SELECT value FROM memories WHERE key = ?", (key,))
            row = cur.fetchone()
            return row[0] if row else None

    def get_all_memories(self) -> List[Dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute("SELECT key, value, category, created_at FROM memories")
            return [{"key": r[0], "value": r[1], "category": r[2], "created_at": r[3]} for r in cur.fetchall()]


db = Database()
