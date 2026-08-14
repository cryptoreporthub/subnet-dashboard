from __future__ import annotations


def test_who_without_author_returns_top_three_with_auditable_accuracy(monkeypatch):
    import internal.message_intel.summary_bot as bot

    monkeypatch.setattr(
        "internal.message_intel.rollup.build_telegram_caller_leaderboard",
        lambda **_kwargs: {
            "callers": [
                {"author_name": "Dr.dre", "sample_size": 145, "hits": 135, "misses": 0, "neutral": 10, "accuracy": 100.0},
                {"author_name": "Second", "sample_size": 13, "hits": 12, "misses": 1, "neutral": 0, "accuracy": 92.3},
                {"author_name": "Third", "sample_size": 8, "hits": 4, "misses": 2, "neutral": 2, "accuracy": 66.7},
            ]
        },
    )
    text = bot.handle_command("/who")
    assert "1. Dr.dre" in text
    assert "2. Second" in text
    assert "3. Third" in text
    assert "135 hits / 135 scored; 10 neutral excluded" in text
    assert "Accuracy is hits/(hits+misses)" in text


def test_who_author_filter_returns_one_author(monkeypatch):
    import internal.message_intel.summary_bot as bot

    monkeypatch.setattr(
        "internal.message_intel.rollup.build_telegram_caller_leaderboard",
        lambda **_kwargs: {
            "callers": [
                {"author_name": "Dr.dre", "sample_size": 145, "hits": 135, "misses": 0, "neutral": 10, "accuracy": 100.0},
                {"author_name": "Second", "sample_size": 13, "hits": 12, "misses": 1, "neutral": 0, "accuracy": 92.3},
            ]
        },
    )
    text = bot.handle_command("/who second")
    assert "1. Second" in text
    assert "Dr.dre" not in text


def test_every_command_response_includes_clickable_full_desk_link(monkeypatch):
    import internal.message_intel.summary_bot as bot

    monkeypatch.setattr(bot, "_format_help", lambda: "Help")
    reply = bot.handle_command("/start")
    assert 'href="https://subnet-dashboard.fly.dev/subnetsummer"' in reply
    assert "View full Subnet Summer Analytics here." in reply
