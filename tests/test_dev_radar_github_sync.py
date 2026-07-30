"""Dev Pulse v2 — GitHub velocity sync."""

import json

from internal.dev_radar.github_sync import (
    fetch_repo_commits_7d,
    parse_github_repo,
    run_github_sync,
    save_dev_radar_cache,
)
from internal.dev_radar.service import build_dev_radar_rows


def test_parse_github_repo():
    assert parse_github_repo("https://github.com/org/repo") == ("org", "repo")
    assert parse_github_repo("https://github.com/org/repo.git") == ("org", "repo")
    assert parse_github_repo("not-a-url") is None


def test_fetch_repo_commits_7d_mocked(monkeypatch):
    class _Resp:
        status_code = 200

        def json(self):
            return [
                {
                    "commit": {
                        "author": {"email": "a@example.com", "date": "2026-07-29T12:00:00Z"}
                    }
                },
                {
                    "commit": {
                        "author": {"email": "b@example.com", "date": "2026-07-28T12:00:00Z"}
                    }
                },
            ]

    monkeypatch.setattr(
        "internal.dev_radar.github_sync.requests.get",
        lambda *a, **k: _Resp(),
    )
    out = fetch_repo_commits_7d("org", "repo")
    assert out["ok"] is True
    assert out["commits_7d"] == 2
    assert out["authors_7d"] == 2


def test_run_github_sync_writes_cache(tmp_path, monkeypatch):
    cache_path = tmp_path / "dev_radar_cache.json"
    monkeypatch.setattr("internal.dev_radar.github_sync.CACHE_PATH", str(cache_path))
    monkeypatch.setattr(
        "internal.dev_radar.service._load_registry_subnets",
        lambda: [
            {
                "netuid": 64,
                "name": "Chutes",
                "github": "https://github.com/org/chutes",
                "emission": 5.0,
                "price_change_24h": 0.5,
            }
        ],
    )
    monkeypatch.setattr(
        "internal.dev_radar.github_sync.fetch_repo_commits_7d",
        lambda *_a, **_k: {
            "ok": True,
            "commits_7d": 8,
            "authors_7d": 2,
            "last_push_at": "2026-07-29T12:00:00Z",
        },
    )
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {"predictions": [], "resolved": []},
    )

    result = run_github_sync()
    assert result["ok"] is True
    assert result["synced"] == 1
    data = json.loads(cache_path.read_text(encoding="utf-8"))
    assert data["subnets"]["64"]["commits_7d"] == 8
    assert data["subnets"]["64"]["velocity_score"] == 100.0


def test_gap_signal_when_velocity_high_price_flat(tmp_path, monkeypatch):
    cache_path = tmp_path / "dev_radar_cache.json"
    save_dev_radar_cache(
        {
            "updated_at": "2026-07-30T00:00:00Z",
            "subnets": {
                "64": {"commits_7d": 20, "velocity_score": 90.0},
                "1": {"commits_7d": 2, "velocity_score": 10.0},
            },
        },
        path=str(cache_path),
    )
    monkeypatch.setattr("internal.dev_radar.github_sync.CACHE_PATH", str(cache_path))
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {"predictions": [], "resolved": []},
    )
    rows = build_dev_radar_rows(
        [
            {"netuid": 64, "github": "https://github.com/a/b", "price_change_24h": 0.2, "emission": 5},
            {"netuid": 1, "github": "https://github.com/a/c", "price_change_24h": 8.0, "emission": 4},
        ],
        limit=10,
    )
    hot = next(r for r in rows if r["netuid"] == 64)
    assert hot.get("gap_signal") == "dev_ahead_of_price"


def test_velocity_null_when_github_unreachable(monkeypatch):
    monkeypatch.setattr(
        "internal.dev_radar.github_sync.load_dev_radar_cache",
        lambda: {"subnets": {"7": {"sync_error": "rate_limited"}}},
    )
    monkeypatch.setattr(
        "internal.learning.predictions_store.load_predictions",
        lambda: {"predictions": [], "resolved": []},
    )
    rows = build_dev_radar_rows(
        [{"netuid": 7, "github": "https://github.com/a/b", "emission": 1.0}],
        limit=5,
    )
    assert rows[0]["velocity_score"] is None
