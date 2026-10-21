"""Public write/read routes reject unbounded or malformed input at the boundary."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from internal.investigation import service
from internal.simivision.routes import MAX_CHAT_BODY_BYTES, MAX_CHAT_MESSAGE_CHARS
from server import app

GOOD = "5GrwvaEF5zXb26Fz9rcQpDWS57CtERHpNehXCPcNoHGKutQY"  # well-formed SS58, 48 chars


@pytest.fixture
def client():
    return TestClient(app)


def test_chat_rejects_oversized_message(client):
    resp = client.post("/api/simivision/chat", json={"message": "x" * (MAX_CHAT_MESSAGE_CHARS + 1)})
    assert resp.status_code == 422


def test_chat_rejects_non_string_message(client):
    assert client.post("/api/simivision/chat", json={"message": {"a": 1}}).status_code == 422


def test_chat_accepts_message_at_the_limit(client):
    with patch("internal.simivision.routes.handle_simivision_chat", return_value={"reply": "ok"}):
        resp = client.post("/api/simivision/chat", json={"message": "x" * MAX_CHAT_MESSAGE_CHARS})
    assert resp.status_code == 200


def test_chat_rejects_oversized_body_before_parsing(client):
    big = b'{"message": "ok", "pad": "' + b"x" * (MAX_CHAT_BODY_BYTES + 1) + b'"}'
    with patch("internal.simivision.routes.handle_simivision_chat") as handler:
        resp = client.post("/api/simivision/chat", content=big, headers={"content-type": "application/json"})
    assert resp.status_code == 413
    handler.assert_not_called()


def test_chat_rejects_oversized_chunked_body(client):
    def chunks():
        for _ in range(MAX_CHAT_BODY_BYTES // 1024 + 2):
            yield b"x" * 1024

    with patch("internal.simivision.routes.handle_simivision_chat") as handler:
        resp = client.post("/api/simivision/chat", content=chunks(), headers={"content-type": "application/json"})
    assert resp.status_code == 413
    handler.assert_not_called()


def test_chat_body_reader_never_copies_an_oversized_chunk(monkeypatch):
    import asyncio

    from internal.simivision import routes

    extended = []

    class RecordingBuffer(bytearray):
        def extend(self, data):
            extended.append(len(data))
            super().extend(data)

    class OneChunk:
        headers = {}

        async def stream(self):
            yield b"x" * (MAX_CHAT_BODY_BYTES + 1)

    monkeypatch.setattr(routes, "bytearray", RecordingBuffer, raising=False)
    with pytest.raises(routes._BodyTooLarge):
        asyncio.run(routes._read_bounded_json(OneChunk()))
    assert extended == []


@pytest.mark.parametrize("body", [b"{", b"", b"[]", b"[1]", b'"text"', b"null"])
def test_chat_rejects_malformed_or_non_object_json_before_the_paid_handler(client, body):
    with patch("internal.simivision.routes.handle_simivision_chat") as handler:
        resp = client.post("/api/simivision/chat", content=body, headers={"content-type": "application/json"})
    assert resp.status_code == 422
    handler.assert_not_called()


def test_ask_rejects_long_question_and_bad_wallet(client):
    assert client.post("/api/investigate/ask", json={"question": "q" * 501}).status_code == 422
    assert client.post("/api/investigate/ask", json={"question": "q", "wallet": "not a wallet!"}).status_code == 422
    assert client.post("/api/investigate/ask", json={"question": "q", "wallet": "5A"}).status_code == 422


def test_ask_accepts_valid_wallet(client):
    with patch("internal.investigation.routes.build_investigation_report", return_value={"ok": True}) as m:
        resp = client.post("/api/investigate/ask", json={"question": "q", "wallet": GOOD})
    assert resp.status_code == 200 and m.call_args.kwargs["wallet"] == GOOD


@pytest.mark.parametrize("path", ["/api/investigate/wallet/{w}", "/api/investigate/wallet/{w}/flow"])
def test_wallet_paths_reject_malformed_wallet(client, path):
    assert client.get(path.format(w="x" * 500)).status_code == 422
    assert client.get(path.format(w="0OIl" * 12)).status_code == 422  # excluded base58 characters


def test_flow_rejects_malformed_counterparty(client):
    assert client.get(f"/api/investigate/wallet/{GOOD}/flow?counterparty=nope").status_code == 422


def test_owner_check_bounds_wallet_list(client):
    many = ",".join([GOOD] * 21)
    assert client.get(f"/api/investigate/subnet/1/owner-check?wallets={many}").status_code == 422
    assert client.get("/api/investigate/subnet/1/owner-check?wallets=bad").status_code == 422


def test_investigation_cache_is_bounded(tmp_path, monkeypatch):
    db = str(tmp_path / "inv.db")
    monkeypatch.setattr(service, "CACHE_DB", db)
    monkeypatch.setattr(service, "CACHE_MAX_ROWS", 5)
    for i in range(12):
        service._cache_set(f"wallet:{i}:50", {"status": "success", "i": i})
    rows = sqlite3.connect(db).execute("SELECT cache_key FROM investigation_cache").fetchall()
    assert len(rows) == 5
    assert {r[0] for r in rows} == {f"wallet:{i}:50" for i in range(7, 12)}
