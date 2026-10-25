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
# A thread parked in getaddrinfo cannot be cancelled. Past this many in flight, new attempts fail closed.
_MAX_INFLIGHT = 4
_inflight = threading.BoundedSemaphore(_MAX_INFLIGHT)


class _SockHolder:
    """Holds the live connection socket so a timer can hang up at the deadline."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._socks: list = []
        self.expired = False

    def register(self, sock) -> None:
        with self._lock:
            self._socks.append(sock)
            expired = self.expired
        if expired:
            self._hang_up(sock)

    def expire(self) -> None:
        with self._lock:
            self.expired = True
            socks = list(self._socks)
        for sock in socks:
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
    def _new_conn(self):
        # registered at TCP connect, so a proxy exchange (plain or CONNECT tunnel) can be hung up
        sock = super()._new_conn()
        _register_socket(sock)
        return sock


class _DeadlineHTTPSConnection(urllib3.connection.HTTPSConnection):
    def _new_conn(self):
        sock = super()._new_conn()
        _register_socket(sock)
        return sock

    def connect(self) -> None:
        super().connect()
        # the TLS wrap detaches the raw socket; the wrapped one is what a blocked read sits on
        _register_socket(self.sock)


class _DeadlineHTTPPool(urllib3.HTTPConnectionPool):
    ConnectionCls = _DeadlineHTTPConnection


class _DeadlineHTTPSPool(urllib3.HTTPSConnectionPool):
    ConnectionCls = _DeadlineHTTPSConnection


_POOL_CLASSES = {"http": _DeadlineHTTPPool, "https": _DeadlineHTTPSPool}


class _DeadlineAdapter(HTTPAdapter):
    def init_poolmanager(self, *args, **kwargs):
        super().init_poolmanager(*args, **kwargs)
        self.poolmanager.pool_classes_by_scheme = _POOL_CLASSES

    def proxy_manager_for(self, proxy, **proxy_kwargs):
        manager = super().proxy_manager_for(proxy, **proxy_kwargs)
        if hasattr(manager, "pool_classes_by_scheme"):
            manager.pool_classes_by_scheme = _POOL_CLASSES
        return manager


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
    deadline. Once an abandoned attempt has a connected socket (including the one to a proxy,
    and including a CONNECT tunnel) it is hung up at the deadline, or as soon as it gets one if
    the resolver was still running. A direct TLS handshake is not cut by the hang-up (the wrap
    detaches the raw socket); it is bounded by the per-attempt timeout, capped to the remaining
    deadline, which CPython applies to the whole handshake. Two phases are not cancelled at all:
    name resolution (a parked getaddrinfo cannot be interrupted) and the TCP connect itself,
    bounded by the connect timeout per resolved address. At most four attempts can be stuck in
    those phases at once; past that, new attempts fail closed.
    """
    remaining = deadline_monotonic - time.monotonic()
    if remaining <= 0:
        raise requests.Timeout("rpc deadline exceeded")
    if not _inflight.acquire(blocking=False):
        raise requests.Timeout("rpc deadline exceeded: too many abandoned attempts still in flight")
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
            _inflight.release()
            done.set()

    try:
        threading.Thread(target=work, daemon=True, name="rpc-deadline-post").start()
    except BaseException:
        _inflight.release()
        raise
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
