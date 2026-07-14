"""Sentry init is optional when SENTRY_DSN is unset."""

from internal.sentry_setup import init_sentry


def test_init_sentry_noop_without_dsn(monkeypatch):
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    assert init_sentry() is False
