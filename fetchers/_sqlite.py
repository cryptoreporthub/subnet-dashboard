"""Shared WAL SQLite connection per DB path (§31-8)."""

from __future__ import annotations

import sqlite3
import threading
from contextlib import contextmanager
from typing import Iterator

_meta_lock = threading.Lock()
_locks: dict[str, threading.Lock] = {}
_conns: dict[str, sqlite3.Connection] = {}


def _lock_for(path: str) -> threading.Lock:
    with _meta_lock:
        lock = _locks.get(path)
        if lock is None:
            lock = threading.Lock()
            _locks[path] = lock
        return lock


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
