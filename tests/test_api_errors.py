"""API error sanitization (audit phase 3)."""

from internal.api_errors import public_error


def test_public_error_hides_exception_text():
    payload = public_error(ValueError("secret sqlite path /app/data/foo.db"))
    assert payload["status"] == "error"
    assert payload["error"] == "request_failed"
    assert "sqlite" not in str(payload)
