"""memory fix 2 (#1538): web-only MALLOC_ARENA_MAX via WEB_MALLOC_ARENA_MAX (default 2)."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import internal.process_memory as pm

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "scripts/fly_web_entrypoint.sh"
OPTIN = "${WEB_MALLOC_ARENA_MAX:+MALLOC_ARENA_MAX=${WEB_MALLOC_ARENA_MAX}}"
PROBE = "sh -c 'echo ${MALLOC_ARENA_MAX:-unset}'"


def _lines():
    return WEB.read_text().splitlines()


def _web_exec_line():
    return next(ln for ln in _lines() if ln.startswith("exec ") and "run_web_with_guard.py" in ln)


def _worker_line():
    return next(ln for ln in _lines() if "RUN_MODE=worker" in ln and "setsid" in ln)


def _run(env_overrides: dict, which: str) -> subprocess.CompletedProcess:
    """Execute the real toggle+guard lines (both knobs), then the real web exec / worker launch prefixes with a probe."""
    head = [
        ln
        for ln in _lines()
        if ln.startswith(("WEB_MALLOC_ARENA_MAX=", "WORKER_MALLOC_ARENA_MAX="))
        or (ln.startswith("case ") and "MALLOC_ARENA_MAX" in ln)
    ]
    assert len(head) == 4
    if which == "web":
        tail = _web_exec_line().replace("python scripts/run_web_with_guard.py", PROBE)
    else:  # worker: reuse its exact env prefix from the launch line
        line = _worker_line().strip()
        prefix = line[line.index("env -u WEB_MALLOC_ARENA_MAX") : line.index("setsid")]
        tail = f"env -u MALLOC_ARENA_MAX {prefix.removeprefix('env ')} sh -c 'echo ${{MALLOC_ARENA_MAX:-unset}} web=${{WEB_MALLOC_ARENA_MAX-absent}}'"
    prog = "set -eu\n" + "\n".join(head) + "\n" + tail + "\n"
    env = {"PATH": os.environ["PATH"], **env_overrides}
    return subprocess.run(["sh", "-c", prog], capture_output=True, text=True, env=env)


def test_web_exec_line_uses_optin_and_toggle_is_single():
    assert OPTIN in _web_exec_line()
    text = WEB.read_text()
    assert text.count('WEB_MALLOC_ARENA_MAX="${WEB_MALLOC_ARENA_MAX-2}"') == 1
    guard = [ln for ln in _lines() if ln.startswith("case ") and "WEB_MALLOC_ARENA_MAX" in ln]
    assert len(guard) == 1 and "*[!0-9]*|0*)" in guard[0]
    # WEB_ knob is used only on the toggle, guard and web exec line (never the worker launch, never fly.toml)
    uses = [ln for ln in _lines() if "WEB_MALLOC_ARENA_MAX" in ln and not ln.startswith("#")]
    assert len(uses) == 4 and uses[-1] == _web_exec_line()
    assert "env -u WEB_MALLOC_ARENA_MAX RUN_MODE=worker" in _worker_line()
    assert "MALLOC_ARENA_MAX" not in (ROOT / "fly.toml").read_text()
    assert "WEB_MALLOC_ARENA_MAX" not in (ROOT / "scripts/fly_worker_entrypoint.sh").read_text()


@pytest.mark.parametrize(
    "value,expected",
    [(None, "2"), ("2", "2"), ("4", "4"), ("", "unset"), ("abc", "unset"), ("2 FOO=bar", "unset"), ("-1", "unset"), ("0", "unset"), ("00", "unset"), ("002", "unset"), ("10", "10")],
)
def test_web_arena_toggle_through_sh(value, expected):
    env = {} if value is None else {"WEB_MALLOC_ARENA_MAX": value}
    res = _run(env, "web")
    assert res.returncode == 0, res
    assert res.stdout.strip() == expected, res
    if value not in (None, "", "2", "4", "10"):
        assert "ignoring invalid WEB_MALLOC_ARENA_MAX" in res.stderr


def test_web_off_when_parent_env_unset_and_blank():
    res = _run({"WEB_MALLOC_ARENA_MAX": ""}, "web")
    assert res.stdout.strip() == "unset"


@pytest.mark.parametrize("web", [None, "", "8", "abc"])
def test_worker_unaffected_by_web_knob(web):
    # export the web knob so the inherited-env path is exercised; env -u must strip it from the worker
    base = {} if web is None else {"WEB_MALLOC_ARENA_MAX": web}
    assert _run({**base, "WORKER_MALLOC_ARENA_MAX": ""}, "worker").stdout.strip() == "unset web=absent"
    assert _run({**base, "WORKER_MALLOC_ARENA_MAX": "3"}, "worker").stdout.strip() == "3 web=absent"
    assert _run(base, "worker").stdout.strip() == "2 web=absent"  # worker default unchanged


def _run_whole_entrypoint_env(extra: dict) -> dict:
    """End-to-end: the WHOLE web entrypoint with exec replaced by `env`, inline worker disabled."""
    src = WEB.read_text()
    line = _web_exec_line()
    assert src.count(line) == 1
    stub = src.replace(line, line.replace("python scripts/run_web_with_guard.py", "env"))
    env = {"PATH": os.environ["PATH"], "ENABLE_INLINE_WORKER": "0", **extra}
    res = subprocess.run(["sh", "-s"], input=stub, capture_output=True, text=True, timeout=20, env=env, cwd=ROOT)
    assert res.returncode == 0, res
    return dict(ln.split("=", 1) for ln in res.stdout.splitlines() if "=" in ln and not ln.startswith(" "))


def test_end_to_end_web_exec_env_default_on():
    got = _run_whole_entrypoint_env({})
    assert got.get("MALLOC_ARENA_MAX") == "2"
    assert "WEB_MALLOC_ARENA_MAX" not in got  # shell var, never exported to the web process


def test_end_to_end_web_exec_env_empty_is_off():
    got = _run_whole_entrypoint_env({"WEB_MALLOC_ARENA_MAX": ""})
    assert "MALLOC_ARENA_MAX" not in got


def test_web_boot_breakdown_reports_arena_max(caplog, monkeypatch):
    """web_boot:* end lines (server._rss_scoped) carry arena_max via the breakdown."""
    import logging

    caplog.set_level(logging.DEBUG)
    monkeypatch.setenv("RUN_MODE", "web")
    monkeypatch.setenv("MALLOC_ARENA_MAX", "2")
    with pm.heavy_job_rss_scope("web_boot:homepage-warm-boot"):
        pass
    end = [r.getMessage() for r in caplog.records if "phase=end" in r.getMessage()]
    assert end and "arena_max=2" in end[-1] and "web_boot:homepage-warm-boot" in end[-1]
    assert '_rss_scoped("web_boot:' in (ROOT / "server.py").read_text()
