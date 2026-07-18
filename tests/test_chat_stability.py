"""Prod stability — chat must not block on live subnet feeds."""

from unittest.mock import patch

from internal.simivision.chat_service import build_chat_context


def test_build_chat_context_uses_registry_not_live_feed():
    with patch("server._get_subnets_with_source") as live_feed:
        ctx = build_chat_context()
        live_feed.assert_not_called()
    assert ctx.get("simivision_picks") is not None
    assert ctx.get("source") == "registry-fallback"
