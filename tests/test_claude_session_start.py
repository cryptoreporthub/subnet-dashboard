"""Behavior tests for .claude/hooks/session-start.sh against a throwaway git origin."""

import os
import re
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
    """Commit the given {skill: text} set to pstack-skills-bundle, push it, return its sha."""
    shutil.rmtree(work / "pstack-skills", ignore_errors=True)
    for name, text in skills.items():
        (work / "pstack-skills" / name).mkdir(parents=True)
        (work / "pstack-skills" / name / "SKILL.md").write_text(text)
    git(work, "add", "-A")
    git(work, "commit", "-qm", "bundle")
    git(work, "push", "-q", "-f", "origin", "HEAD:refs/heads/pstack-skills-bundle")
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=work, check=True, capture_output=True, text=True
    ).stdout.strip()


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
        **{k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"},
        "HOME": str(home),
        "PATH": f"{stub_bin}:{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(repo),
        "CLAUDE_CODE_REMOTE": "true",
    }
    return {"work": work, "home": home, "env": run_env, "npm_log": npm_log, "tmp": tmp_path}


def pinned_script(tmp, sha):
    """A copy of session-start.sh whose bundle pin is the given sha."""
    text = SCRIPT.read_text()
    assert re.search(r'^bundle_sha="[0-9a-f]{40}"$', text, re.M), "pin line missing"
    copy = tmp / f"session-start-{sha[:7]}.sh"
    copy.write_text(re.sub(r'^bundle_sha="[0-9a-f]{40}"$', f'bundle_sha="{sha}"', text, flags=re.M))
    return copy


def run(env, script=SCRIPT):
    proc = subprocess.run(
        ["bash", str(script)], env=env, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout


def skill(home, name):
    path = home / ".claude" / "skills" / name / "SKILL.md"
    return path.read_text() if path.exists() else None


def test_installs_bundle_and_turns_on_poteto_mode(env):
    sha = publish_bundle(
        env["work"], {"poteto-mode": "v1", "tdd": "v1", "kept": "bundle", "synced": "x"}
    )
    out = run(env["env"], pinned_script(env["tmp"], sha))
    home = env["home"]
    assert "Poteto mode is on" in out and "did not install" not in out
    assert skill(home, "poteto-mode") == "v1"
    assert skill(home, "tdd") == "v1"
    assert skill(home, "kept") == "platform copy"
    assert skill(home, "synced") is None
    assert "install -g --no-fund --no-audit @heyditto/cli@" in env["npm_log"].read_text()


def test_installs_the_pinned_commit_not_the_branch_tip(env):
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1"})
    publish_bundle(env["work"], {"poteto-mode": "tip"})
    run(env["env"], pinned_script(env["tmp"], v1))
    assert skill(env["home"], "poteto-mode") == "v1"


def test_refreshes_only_when_the_pin_changes(env):
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    (env["home"] / ".claude" / "skills" / "poteto-mode" / "SKILL.md").write_text("edited")
    run(env["env"], pinned_script(env["tmp"], v1))
    assert skill(env["home"], "poteto-mode") == "edited"
    v2 = publish_bundle(env["work"], {"poteto-mode": "v2"})
    run(env["env"], pinned_script(env["tmp"], v2))
    assert skill(env["home"], "poteto-mode") == "v2"


def test_missing_pinned_commit_fails_safe(env):
    publish_bundle(env["work"], {"poteto-mode": "v1"})
    out = run(env["env"], pinned_script(env["tmp"], "0" * 40))
    assert "did not install" in out
    assert skill(env["home"], "poteto-mode") is None


def test_does_nothing_outside_cloud_sessions(env):
    local = {k: v for k, v in env["env"].items() if k != "CLAUDE_CODE_REMOTE"}
    assert run(local) == ""
    assert run({**env["env"], "GITHUB_ACTIONS": "true"}) == ""
    assert not env["npm_log"].exists()
