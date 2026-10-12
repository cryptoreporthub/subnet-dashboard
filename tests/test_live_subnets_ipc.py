"""Unit tests for length-prefixed live_subnets IPC framing."""

from __future__ import annotations

import pickle
import socket
import struct
import threading
import time

from internal.live_subnets_ipc import _HEADER, recv_message, send_message


def _frame(payload: bytes) -> bytes:
    return _HEADER.pack(len(payload)) + payload


def test_send_recv_roundtrip():
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    assert send_message(left, {"phase": "ready", "n": 3}) is True
    out = recv_message(right, time.monotonic() + 2.0)
    assert out == {"phase": "ready", "n": 3}


def test_partial_header_then_body():
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    body = pickle.dumps({"ok": True})
    frame = _frame(body)

    def _slow_write():
        left.send(frame[:2])
        time.sleep(0.15)
        left.send(frame[2:])

    threading.Thread(target=_slow_write, daemon=True).start()
    assert recv_message(right, time.monotonic() + 3.0) == {"ok": True}


def test_partial_body_then_rest():
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    body = pickle.dumps({"data": [1, 2, 3]})
    frame = _frame(body)
    split = 4 + max(1, len(body) // 2)

    def _slow_write():
        left.send(frame[:split])
        time.sleep(0.15)
        left.send(frame[split:])

    threading.Thread(target=_slow_write, daemon=True).start()
    assert recv_message(right, time.monotonic() + 3.0) == {"data": [1, 2, 3]}


def test_eof_mid_frame_closes_and_returns_none():
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    left.send(_HEADER.pack(100))
    left.close()
    assert recv_message(right, time.monotonic() + 1.0) is None


def test_start_failure_timeout_before_data():
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    assert recv_message(right, time.monotonic() + 0.05) is None


def test_send_one_megabyte_with_small_socket_buffers():
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    right.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
    payload = {"blob": "x" * (1024 * 1024)}
    received: dict = {}

    def _reader():
        received["out"] = recv_message(right, time.monotonic() + 30.0)

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    assert send_message(left, payload, deadline=time.monotonic() + 30.0) is True
    reader.join(timeout=35.0)
    assert received.get("out") == payload


def test_send_times_out_when_peer_never_reads():
    left, right = socket.socketpair()
    left.setblocking(False)
    right.setblocking(False)
    left.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, 4096)
    payload = {"blob": "y" * (1024 * 1024)}
    assert send_message(left, payload, deadline=time.monotonic() + 0.15) is False
