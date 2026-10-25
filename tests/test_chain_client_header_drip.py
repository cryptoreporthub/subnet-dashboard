"""Slow status/header drip must not outlive the RPC deadline (#1483 Replit P2)."""

from __future__ import annotations

import shutil
import socket
import ssl
import subprocess
import threading
import time

import pytest
import requests

from internal.chain_client import _timed_post


class _DripServer:
    """Sends one header byte per ``per_byte`` seconds; records when its peer went away."""

    def __init__(self, per_byte: float, total_bytes: int, tls_dir=None):
        self.closed_at = None
        self.finished = threading.Event()
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        self.port = srv.getsockname()[1]
        self._srv = srv
        self._ctx = None
        if tls_dir is not None:
            cert, key = f"{tls_dir}/cert.pem", f"{tls_dir}/key.pem"
            subprocess.run(
                ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
                 "-keyout", key, "-out", cert, "-subj", "/CN=127.0.0.1",
                 "-addext", "subjectAltName=IP:127.0.0.1"],
                check=True, capture_output=True,
            )
            self.cert = cert
            self._ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            self._ctx.load_cert_chain(cert, key)
        threading.Thread(target=self._run, args=(per_byte, total_bytes), daemon=True).start()

    def _run(self, per_byte: float, total_bytes: int) -> None:
        conn, _ = self._srv.accept()
        try:
            if self._ctx is not None:
                conn = self._ctx.wrap_socket(conn, server_side=True)
            conn.recv(65536)
            payload = b"HTTP/1.1 200 OK\r\nX-Pad: " + b"a" * total_bytes + b"\r\n\r\n"
            for i in range(len(payload)):
                conn.send(payload[i : i + 1])
                time.sleep(per_byte)
        except OSError:
            self.closed_at = time.monotonic()
        finally:
            conn.close()
            self._srv.close()
            self.finished.set()


@pytest.mark.parametrize("tls", [False, True], ids=["http", "https"])
def test_header_drip_returns_at_deadline_and_closes_the_connection(tls, tmp_path, monkeypatch):
    if tls and shutil.which("openssl") is None:
        pytest.skip("openssl not available")
    server = _DripServer(per_byte=0.05, total_bytes=60, tls_dir=tmp_path if tls else None)
    if tls:
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", server.cert)
    deadline_s = 0.3
    started = time.monotonic()
    with pytest.raises(requests.Timeout):
        _timed_post(
            f"{'https' if tls else 'http'}://127.0.0.1:{server.port}",
            {"jsonrpc": "2.0", "id": 1, "method": "x", "params": []},
            10.0,
            deadline_monotonic=started + deadline_s,
        )
    elapsed = time.monotonic() - started
    assert elapsed < deadline_s + 0.15, f"returned {elapsed:.2f}s after a {deadline_s}s deadline"
    assert server.finished.wait(2.0)
    assert server.closed_at is not None, "server finished its drip: the client never hung up"
    assert server.closed_at - started < deadline_s + 0.4, (
        f"client hung up {server.closed_at - started:.2f}s in, deadline was {deadline_s}s"
    )


@pytest.mark.parametrize("tls", [False, True], ids=["http", "https"])
def test_slow_name_resolution_returns_at_deadline_and_leaves_no_connection(tls, tmp_path, monkeypatch):
    if tls and shutil.which("openssl") is None:
        pytest.skip("openssl not available")
    server = _DripServer(per_byte=0.05, total_bytes=60, tls_dir=tmp_path if tls else None)
    if tls:
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", server.cert)
    real_getaddrinfo = socket.getaddrinfo

    def slow_getaddrinfo(*args, **kwargs):
        time.sleep(0.45)
        return real_getaddrinfo(*args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", slow_getaddrinfo)
    deadline_s = 0.12
    started = time.monotonic()
    with pytest.raises(requests.Timeout):
        _timed_post(
            f"{'https' if tls else 'http'}://127.0.0.1:{server.port}",
            {"jsonrpc": "2.0", "id": 1, "method": "x", "params": []},
            10.0,
            deadline_monotonic=started + deadline_s,
        )
    elapsed = time.monotonic() - started
    assert elapsed < deadline_s + 0.15, f"returned {elapsed:.2f}s after a {deadline_s}s deadline"
    assert server.finished.wait(4.0)
    assert server.closed_at is not None, "the late connection was left open"


def test_dripping_proxy_returns_at_deadline(monkeypatch):
    proxy = _DripServer(per_byte=0.05, total_bytes=60)
    monkeypatch.setenv("HTTP_PROXY", f"http://127.0.0.1:{proxy.port}")
    monkeypatch.setenv("NO_PROXY", "")
    deadline_s = 0.3
    started = time.monotonic()
    with pytest.raises(requests.Timeout):
        _timed_post(
            "http://rpc.example.invalid/",
            {"jsonrpc": "2.0", "id": 1, "method": "x", "params": []},
            10.0,
            deadline_monotonic=started + deadline_s,
        )
    elapsed = time.monotonic() - started
    assert elapsed < deadline_s + 0.15, f"returned {elapsed:.2f}s after a {deadline_s}s deadline"


def test_hung_resolver_cannot_pile_up_worker_threads(monkeypatch):
    release = threading.Event()
    real_getaddrinfo = socket.getaddrinfo

    def hung_getaddrinfo(*args, **kwargs):
        release.wait(10)
        return real_getaddrinfo(*args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", hung_getaddrinfo)
    payload = {"jsonrpc": "2.0", "id": 1, "method": "x", "params": []}
    try:
        for _ in range(12):
            started = time.monotonic()
            with pytest.raises(requests.Timeout):
                _timed_post(
                    "http://127.0.0.1:9/",
                    payload,
                    10.0,
                    deadline_monotonic=started + 0.05,
                )
            assert time.monotonic() - started < 0.25
        alive = [t for t in threading.enumerate() if t.name == "rpc-deadline-post"]
        assert len(alive) <= 4, f"{len(alive)} abandoned worker threads are still parked in the resolver"
    finally:
        release.set()
        time.sleep(0.2)
