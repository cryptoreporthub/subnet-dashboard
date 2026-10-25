"""Wall-clock-capped HTTP POST for chain RPC: the caller returns by the deadline.

Used only when a caller sets a deadline (the universe registration probe). Other chain
RPC callers use plain ``requests.post``.
"""

from __future__ import annotations

import socket
import threading
import time
from typing import Any, Dict

import requests
import urllib3
from requests.adapters import HTTPAdapter


def _set_stream_read_timeout(response: requests.Response, remaining: float) -> None:
    """Cap the next blocking socket read to ``remaining`` seconds (slow-drip safe)."""
    if remaining <= 0:
        return
    raw = getattr(response, "raw", None)
    if raw is None:
        return
    conn = getattr(raw, "connection", None)
    sock = getattr(conn, "sock", None) if conn is not None else getattr(raw, "sock", None)
    if sock is not None:
        sock.settimeout(remaining)


# Byte-at-a-time reads cost ~2.7 us of GIL-held CPU per byte; the hang-up timer already bounds a drip.
_BODY_CHUNK_BYTES = 16384


class _SockHolder:
    """Holds the live connection socket so a timer can hang up at the deadline."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sock = None
        self.expired = False

    def register(self, sock) -> None:
        with self._lock:
            self._sock = sock
            expired = self.expired
        if expired:
            self._hang_up(sock)

    def expire(self) -> None:
        with self._lock:
            self.expired = True
            sock = self._sock
        if sock is not None:
            self._hang_up(sock)

    @staticmethod
    def _hang_up(sock) -> None:
        # shutdown, not close: close() from another thread does not reliably wake a blocked recv
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass


_active_holder = threading.local()


def _register_socket(sock) -> None:
    holder = getattr(_active_holder, "holder", None)
    if holder is not None:
        holder.register(sock)


class _DeadlineHTTPConnection(urllib3.connection.HTTPConnection):
    def connect(self) -> None:
        super().connect()
        _register_socket(self.sock)


class _DeadlineHTTPSConnection(urllib3.connection.HTTPSConnection):
    def connect(self) -> None:
        super().connect()
        _register_socket(self.sock)


class _DeadlineHTTPPool(urllib3.HTTPConnectionPool):
    ConnectionCls = _DeadlineHTTPConnection


class _DeadlineHTTPSPool(urllib3.HTTPSConnectionPool):
    ConnectionCls = _DeadlineHTTPSConnection


class _DeadlineAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = {"http": _DeadlineHTTPPool, "https": _DeadlineHTTPSPool}


def stream_post(
    endpoint: str,
    payload: Dict[str, Any],
    timeout: float,
    deadline_monotonic: float,
) -> requests.Response:
    """POST that returns to the caller by the deadline, whatever the server or resolver does.

    ``requests.post`` blocks inside header parsing and its socket timeout restarts on
    every received byte, so a slow header drip outlives any deadline checked after it
    returns. The request runs on a daemon thread and the caller waits only until the
    deadline. An abandoned attempt is hung up at the deadline, or as soon as its socket
    registers if the resolver was still running. The window between registration points
    (TCP connect and the TLS handshake after a slow resolve) and proxy-routed
    connections, which bypass the connection classes, are bounded by the per-attempt
    timeout instead.
    """
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise requests.Timeout("rpc deadline exceeded")
    holder = _SockHolder()
    outcome: Dict[str, Any] = {}
    done = threading.Event()

    def work() -> None:
        _active_holder.holder = holder
        try:
            outcome["response"] = _stream_post_worker(
                endpoint, payload, min(timeout, remaining), deadline_monotonic, holder
            )
        except BaseException as exc:  # handed to the caller below
            outcome["error"] = exc
        finally:
            _active_holder.holder = None
            done.set()

    threading.Thread(target=work, daemon=True, name="rpc-deadline-post").start()
    if not done.wait(max(0.0, deadline_monotonic - time.monotonic())):
        holder.expire()
        raise requests.Timeout("rpc deadline exceeded")
    if "error" in outcome:
        raise outcome["error"]
    return outcome["response"]


def _stream_post_worker(
    endpoint: str,
    payload: Dict[str, Any],
    slice_timeout: float,
    deadline_monotonic: float,
    holder: _SockHolder,
) -> requests.Response:
    session = requests.Session()
    adapter = _DeadlineAdapter()
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    response = None
    try:
        response = session.post(
            endpoint,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=(slice_timeout, slice_timeout),
            stream=True,
        )
        body = bytearray()
        chunks = response.iter_content(chunk_size=_BODY_CHUNK_BYTES)
        while True:
            remaining = deadline_monotonic - time.monotonic()
            if remaining <= 0:
                raise requests.Timeout("rpc deadline exceeded")
            _set_stream_read_timeout(response, remaining)
            try:
                chunk = next(chunks)
            except StopIteration:
                break
            if time.monotonic() >= deadline_monotonic:
                raise requests.Timeout("rpc deadline exceeded")
            if chunk:
                body.extend(chunk)
        if time.monotonic() >= deadline_monotonic:
            raise requests.Timeout("rpc deadline exceeded")
        response._content = bytes(body)
        return response
    except requests.Timeout:
        if response is not None:
            response.close()
        raise
    except Exception as exc:
        if response is not None:
            response.close()
        if holder.expired or time.monotonic() >= deadline_monotonic:
            raise requests.Timeout("rpc deadline exceeded") from exc
        raise
    finally:
        session.close()
