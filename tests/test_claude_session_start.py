"""Behavior tests for .claude/hooks/session-start.sh against a throwaway git origin."""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "session-start.sh"

pytestmark = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("git") and shutil.which("tar")),
    reason="needs bash, git and tar",
)


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
    )


def publish_bundle(work, skills):
    """Commit the given {skill: text} set to pstack-skills-bundle and push it."""
    shutil.rmtree(work / "pstack-skills", ignore_errors=True)
    for name, text in skills.items():
        (work / "pstack-skills" / name).mkdir(parents=True)
        (work / "pstack-skills" / name / "SKILL.md").write_text(text)
    git(work, "add", "-A")
    git(work, "commit", "-qm", "bundle")
    git(work, "push", "-q", "-f", "origin", "HEAD:refs/heads/pstack-skills-bundle")


@pytest.fixture
def env(tmp_path):
    origin = tmp_path / "origin.git"
    git(tmp_path, "init", "-q", "--bare", str(origin))
    work = tmp_path / "work"
    work.mkdir()
    git(work, "init", "-q")
    git(work, "remote", "add", "origin", str(origin))
    repo = tmp_path / "repo"
    git(tmp_path, "init", "-q", str(repo))
    git(repo, "remote", "add", "origin", str(origin))
    home = tmp_path / "home"
    (home / ".claude" / "skills" / "kept").mkdir(parents=True)
    (home / ".claude" / "skills" / "kept" / "SKILL.md").write_text("platform copy")
    stub_bin = tmp_path / "bin"
    stub_bin.mkdir()
    npm_log = tmp_path / "npm.log"
    (stub_bin / "npm").write_text(f'#!/bin/bash\necho "$*" >> {npm_log}\n[ "$1" = ls ] && exit 1\nexit 0\n')
    (stub_bin / "npm").chmod(0o755)
    run_env = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{stub_bin}:{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(repo),
        "CLAUDE_CODE_REMOTE": "true",
    }
    return {"work": work, "home": home, "env": run_env, "npm_log": npm_log}


def run(env):
    proc = subprocess.run(
        ["bash", str(SCRIPT)], env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def skill(home, name):
    path = home / ".claude" / "skills" / name / "SKILL.md"
    return path.read_text() if path.exists() else None


def test_installs_bundle_and_turns_on_poteto_mode(env):
    publish_bundle(env["work"], {"poteto-mode": "v1", "tdd": "v1", "kept": "bundle", "synced": "x"})
    out = run(env["env"])
    home = env["home"]
    assert "Poteto mode is on" in out and "did not install" not in out
    assert skill(home, "poteto-mode") == "v1"
    assert skill(home, "tdd") == "v1"
    assert skill(home, "kept") == "platform copy"
    assert skill(home, "synced") is None
    assert "install -g --no-fund --no-audit @heyditto/cli@" in env["npm_log"].read_text()


def test_refreshes_only_when_the_bundle_changes(env):
    publish_bundle(env["work"], {"poteto-mode": "v1"})
    run(env["env"])
    (env["home"] / ".claude" / "skills" / "poteto-mode" / "SKILL.md").write_text("edited")
    run(env["env"])
    assert skill(env["home"], "poteto-mode") == "edited"
    publish_bundle(env["work"], {"poteto-mode": "v2"})
    run(env["env"])
    assert skill(env["home"], "poteto-mode") == "v2"


def test_missing_bundle_fails_safe(env):
    out = run(env["env"])
    assert "did not install" in out


def test_does_nothing_outside_cloud_sessions(env):
    local = {k: v for k, v in env["env"].items() if k != "CLAUDE_CODE_REMOTE"}
    assert run(local) == ""
    assert not env["npm_log"].exists()
