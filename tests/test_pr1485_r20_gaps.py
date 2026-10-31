"""PR #1485 R20: G2 hard gate — real ``_PROBE_UNKNOWN`` placeholder resume + mutants."""

from __future__ import annotations

import pytest

from internal import loop_stall_guard as g


def test_g2_probe_unknown_placeholder_resume_refreshes_once_cap_unchanged():
    """Real placeholder token (never pre-set ``watch.token``); resume + frozen observe."""
    watch = g._TickWatch(g._PROBE_UNKNOWN, 1000.0, probe_unknown=True)
    assert watch.token is g._PROBE_UNKNOWN
    assert watch.first_seen == 1000.0
    out = g._watch_active_tick(watch, (None, None), 1900.0)
    assert out.last_progress == 1900.0
    assert out.first_seen == 1000.0
    out.observe((None, None), 3200.0)
    assert out.last_progress == 1900.0
    assert out.first_seen == 1000.0


def _g2_mutant_token_progress_unknown_returns_none(monkeypatch) -> None:
    real = g._token_progress

    def _fake(token):
        if token is g._PROBE_UNKNOWN:
            return None
        return real(token)

    monkeypatch.setattr(g, "_token_progress", _fake)


def _g2_mutant_token_progress_unknown_returns_fresh_object(monkeypatch) -> None:
    real = g._token_progress

    def _fake(token):
        if token is g._PROBE_UNKNOWN:
            return object()
        return real(token)

    monkeypatch.setattr(g, "_token_progress", _fake)


def _g2_mutant_always_refresh_at_sentinel(monkeypatch) -> None:
    from tests.test_pr1485_r18_probe_sentinel_cap import _r3_sentinel_refresh_every_resume

    _r3_sentinel_refresh_every_resume(monkeypatch)


def test_g2_probe_unknown_placeholder_progress_sentinel_is_identity():
    assert g._token_progress(g._PROBE_UNKNOWN) is g._PROBE_UNKNOWN


@pytest.mark.parametrize(
    "mutator",
    [_g2_mutant_token_progress_unknown_returns_none],
    ids=["token-progress-unknown-none"],
)
def test_g2_token_progress_none_mutant_fails_resume_and_identity_pin(monkeypatch, mutator):
    mutator(monkeypatch)
    with pytest.raises(AssertionError):
        test_g2_probe_unknown_placeholder_resume_refreshes_once_cap_unchanged()
    with pytest.raises(AssertionError):
        test_g2_probe_unknown_placeholder_progress_sentinel_is_identity()


def test_g2_token_progress_object_mutant_fails_sentinel_identity_pin(monkeypatch):
    _g2_mutant_token_progress_unknown_returns_fresh_object(monkeypatch)
    with pytest.raises(AssertionError):
        test_g2_probe_unknown_placeholder_progress_sentinel_is_identity()


def test_g2_always_refresh_mutant_fails_same_progress_resume_pin(monkeypatch):
    _g2_mutant_always_refresh_at_sentinel(monkeypatch)
    from tests.test_pr1485_r19_gaps import (
        test_g2_probe_unknown_same_progress_does_not_refresh_last_progress,
    )

    with pytest.raises(AssertionError):
        test_g2_probe_unknown_same_progress_does_not_refresh_last_progress()


def test_g2_placeholder_resume_then_repeated_probe_unknown_resumes_keep_last_progress():
    """R22: the placeholder refresh happens once; later same-progress resumes must not refresh again.

    Real ``_watch_active_tick``: resume from the placeholder at t=1900, then three more probe-unknown
    windows each followed by a resume with the same frozen token. ``last_progress`` stays 1900 and
    ``first_seen`` stays 1000; a changed progress still refreshes.
    """
    watch = g._TickWatch(g._PROBE_UNKNOWN, 1000.0, probe_unknown=True)
    out = g._watch_active_tick(watch, (None, "5/128"), 1900.0)
    assert out.last_progress == 1900.0
    for now in (2140.0, 2380.0, 2620.0):
        out.probe_unknown = True
        out = g._watch_active_tick(out, (None, "5/128"), now)
        assert out.probe_unknown is False
        assert out.last_progress == 1900.0, now
        assert out.first_seen == 1000.0
    out.probe_unknown = True
    out = g._watch_active_tick(out, (None, "6/128"), 2860.0)
    assert out.last_progress == 2860.0
    assert out.first_seen == 1000.0


def test_g2_always_refresh_every_resume_mutant_fails_repeated_resume_pin(monkeypatch):
    from tests.test_pr1485_r18_probe_sentinel_cap import _r3_sentinel_refresh_every_resume

    _r3_sentinel_refresh_every_resume(monkeypatch)
    with pytest.raises(AssertionError):
        test_g2_placeholder_resume_then_repeated_probe_unknown_resumes_keep_last_progress()
