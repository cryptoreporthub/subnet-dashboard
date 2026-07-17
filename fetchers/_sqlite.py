"""Shared WAL SQLite connection per DB path (§31-8)."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

_locks: dict[str, threading.Lock] = {}
_conns: dict[str, sqlite3.Connection] = {}


def _lock_for(path: str) -> threading.Lock:
    if path not in _locks:
        _locks[path] = threading.Lock()
    return _locks[path]


def get_connection(path: str) -> sqlite3.Connection:
    """Return a reused connection for ``path`` (caller holds per-path lock)."""
    conn = _conns.get(path)
    if conn is None:
        conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
        _conns[path] = conn
    return conn


@contextmanager
def db_conn(path: str) -> Iterator[sqlite3.Connection]:
    lock = _lock_for(path)
    with lock:
        yield get_connection(path)
