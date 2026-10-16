"""SQLite connection singleton with WAL journal mode and dict row factory."""

import sqlite3
import threading
from pathlib import Path

_lock = threading.Lock()
_connections: dict[str, sqlite3.Connection] = {}


def get_connection(db_path: str | Path | None = None) -> sqlite3.Connection:
    """Return a reusable SQLite connection for *db_path*.

    Uses WAL journal mode for concurrent reads and a dict-style row factory.
    One connection per unique path is cached (thread-safe via lock).
    If *db_path* is None, the default from config is used.
    """
    if db_path is None:
        from inferforge.config import DB_PATH
        db_path = DB_PATH

    key = str(db_path)

    with _lock:
        conn = _connections.get(key)
        if conn is not None:
            try:
                conn.execute("SELECT 1")
                return conn
            except sqlite3.ProgrammingError:
                _connections.pop(key, None)

        Path(key).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(key, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _connections[key] = conn
        return conn


def close_all() -> None:
    """Close every cached connection (call on shutdown)."""
    with _lock:
        for conn in _connections.values():
            try:
                conn.close()
            except Exception:
                pass
        _connections.clear()
