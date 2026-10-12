"""Deadline-aware length-prefixed framing for live_subnets parent/child IPC."""

from __future__ import annotations

import fcntl
import os
import pickle
import select
import struct
import time
from typing import Any, Optional, Union

_HEADER = struct.Struct("!I")
_MAX_PAYLOAD = 8 * 1024 * 1024

_Conn = Union[Any, "os.SocketLike"]


def _close_conn(conn: _Conn) -> None:
    try:
        conn.close()
    except Exception:
        pass


def _fileno(conn: _Conn) -> int:
    if hasattr(conn, "fileno"):
        return int(conn.fileno())
    raise TypeError("connection has no fileno")


def _read_exact(conn: _Conn, nbytes: int, deadline: float) -> Optional[bytes]:
    """Accumulate nbytes before deadline using select + non-blocking reads."""
    fd = _fileno(conn)
    flags = fcntl.fcntl(fd, fcntl.F_GETFL)
    fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
    buf = bytearray()
    try:
        while len(buf) < nbytes:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None
            ready, _, _ = select.select([fd], [], [], min(remaining, 0.05))
            if not ready:
                continue
            try:
                chunk = os.read(fd, nbytes - len(buf))
            except BlockingIOError:
                continue
            except OSError:
                return None
            if not chunk:
                return None
            buf.extend(chunk)
        return bytes(buf)
    finally:
        fcntl.fcntl(fd, fcntl.F_SETFL, flags)


def recv_message(conn: _Conn, deadline: float) -> Optional[Any]:
    """Read one length-prefixed pickle payload before ``deadline`` (monotonic)."""
    header = _read_exact(conn, _HEADER.size, deadline)
    if header is None:
        _close_conn(conn)
        return None
    (body_len,) = _HEADER.unpack(header)
    if body_len > _MAX_PAYLOAD:
        _close_conn(conn)
        return None
    body = _read_exact(conn, body_len, deadline)
    if body is None:
        _close_conn(conn)
        return None
    try:
        return pickle.loads(body)
    except Exception:
        _close_conn(conn)
        return None


def send_message(conn: _Conn, payload: Any) -> bool:
    try:
        body = pickle.dumps(payload, protocol=pickle.HIGHEST_PROTOCOL)
        if len(body) > _MAX_PAYLOAD:
            return False
        frame = _HEADER.pack(len(body)) + body
        if hasattr(conn, "sendall"):
            conn.sendall(frame)
            return True
        conn.send_bytes(frame)
        return True
    except (EOFError, OSError, BrokenPipeError):
        return False
