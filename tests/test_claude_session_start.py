"""Behavior tests for .claude/hooks/session-start.sh against a throwaway git origin."""

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "session-start.sh"
DITTO = SCRIPT.parent / "ditto"

pytestmark = pytest.mark.skipif(
    not (shutil.which("bash") and shutil.which("git") and shutil.which("tar")),
    reason="needs bash, git and tar",
)


def git(cwd, *args):
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false", *args],
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
    shutil.copytree(DITTO, repo / ".claude" / "hooks" / "ditto")
    npm_log = tmp_path / "npm.log"
    npm_fail = tmp_path / "npm-fail"
    # npm ci stub: logs its arguments and lays down the heyditto bin, or fails
    # while npm-fail exists.
    (stub_bin / "npm").write_text(
        f'#!/bin/bash\necho "$*" >> {npm_log}\n'
        f'[ -e {npm_fail} ] && exit 1\n'
        '[ "$1" = ci ] && mkdir -p node_modules/.bin '
        '&& printf "#!/bin/sh\\n" > node_modules/.bin/heyditto '
        '&& chmod +x node_modules/.bin/heyditto\nexit 0\n'
    )
    (stub_bin / "npm").chmod(0o755)
    run_env = {
        **{k: v for k, v in os.environ.items() if k != "GITHUB_ACTIONS"},
        "HOME": str(home),
        "PATH": f"{stub_bin}:{os.environ['PATH']}",
        "CLAUDE_PROJECT_DIR": str(repo),
        "CLAUDE_CODE_REMOTE": "true",
    }
    return {
        "work": work,
        "home": home,
        "env": run_env,
        "npm_log": npm_log,
        "npm_fail": npm_fail,
        "repo": repo,
        "tmp": tmp_path,
    }


def pinned_script(tmp, sha):
    """A copy of session-start.sh whose bundle pin is the given sha.

    ponytail: the tests run offline against a local bundle repo, so none runs
    the shipped pin itself. Check it by hand with
    git ls-remote origin pstack-skills-bundle when bumping it.
    """
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
    installs = env["npm_log"].read_text().splitlines()
    assert len(installs) == 1 and installs[0].split()[0] == "ci"  # lockfile only
    assert "--ignore-scripts" in installs[0].split()  # no lifecycle scripts
    assert os.access(home / ".local" / "bin" / "heyditto", os.X_OK)


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


def test_drops_skills_a_new_bundle_no_longer_ships(env):
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", "old": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    assert skill(env["home"], "old") == "v1"
    v2 = publish_bundle(env["work"], {"poteto-mode": "v2"})
    run(env["env"], pinned_script(env["tmp"], v2))
    assert skill(env["home"], "old") is None
    assert skill(env["home"], "kept") == "platform copy"


def test_bundle_links_are_never_installed(env):
    secret = env["tmp"] / "outside.txt"
    secret.write_text("outside the bundle")
    skills = env["work"] / "pstack-skills"
    shutil.rmtree(skills, ignore_errors=True)
    (skills / "poteto-mode").mkdir(parents=True)
    (skills / "poteto-mode" / "SKILL.md").write_text("v1")
    (skills / "poteto-mode" / "leak").symlink_to(secret)
    (skills / "linked").symlink_to(env["tmp"])
    git(env["work"], "add", "-A")
    git(env["work"], "commit", "-qm", "bundle")
    git(env["work"], "push", "-q", "-f", "origin", "HEAD:refs/heads/pstack-skills-bundle")
    sha = subprocess.run(["git", "rev-parse", "HEAD"], cwd=env["work"], check=True,
                         capture_output=True, text=True).stdout.strip()
    run(env["env"], pinned_script(env["tmp"], sha))
    installed = env["home"] / ".claude" / "skills"
    assert skill(env["home"], "poteto-mode") == "v1"
    assert not os.path.lexists(installed / "poteto-mode" / "leak")
    assert not (installed / "linked").exists()


def ditto_installs(env):
    log = env["npm_log"]
    return [l for l in log.read_text().splitlines() if l.startswith("ci")] if log.exists() else []


def test_skips_ditto_install_while_the_lockfile_is_unchanged(env):
    sha = publish_bundle(env["work"], {"poteto-mode": "v1"})
    script = pinned_script(env["tmp"], sha)
    run(env["env"], script)
    run(env["env"], script)
    assert len(ditto_installs(env)) == 1


def test_reinstalls_ditto_when_the_lockfile_changes(env):
    sha = publish_bundle(env["work"], {"poteto-mode": "v1"})
    script = pinned_script(env["tmp"], sha)
    run(env["env"], script)
    lock = env["repo"] / ".claude" / "hooks" / "ditto" / "package-lock.json"
    lock.write_text(lock.read_text() + "\n")
    run(env["env"], script)
    assert len(ditto_installs(env)) == 2


def test_failed_ditto_install_keeps_the_previous_one(env):
    sha = publish_bundle(env["work"], {"poteto-mode": "v1"})
    script = pinned_script(env["tmp"], sha)
    run(env["env"], script)
    lock = env["repo"] / ".claude" / "hooks" / "ditto" / "package-lock.json"
    lock.write_text(lock.read_text() + "\n")
    env["npm_fail"].touch()
    out = run(env["env"], script)
    assert "Poteto mode is on" in out
    assert os.access(env["home"] / ".local" / "bin" / "heyditto", os.X_OK)
    env["npm_fail"].unlink()
    run(env["env"], script)
    assert len(ditto_installs(env)) == 3  # retried on the next session


def test_failed_ditto_swap_keeps_the_previous_one(env):
    sha = publish_bundle(env["work"], {"poteto-mode": "v1"})
    script = pinned_script(env["tmp"], sha)
    run(env["env"], script)
    heyditto = env["home"] / ".local" / "bin" / "heyditto"
    marker = env["home"] / ".local" / "share" / "session-ditto-cli" / ".lock-sha"
    before = marker.read_text()
    lock = env["repo"] / ".claude" / "hooks" / "ditto" / "package-lock.json"
    lock.write_text(lock.read_text() + "\n")
    # npm ci succeeds, then moving the new install into place fails.
    stub_mv = env["tmp"] / "bin" / "mv"
    stub_mv.write_text(
        '#!/bin/bash\ncase "$2" in *session-ditto-cli.old.*) ;; '
        f'*session-ditto-cli.*) exit 1;; esac\nexec {shutil.which("mv")} "$@"\n'
    )
    stub_mv.chmod(0o755)
    out = run(env["env"], script)
    assert "Poteto mode is on" in out
    assert len(ditto_installs(env)) == 2
    assert os.access(heyditto, os.X_OK)
    assert marker.read_text() == before  # the old install is back in place
    stub_mv.unlink()
    run(env["env"], script)
    assert marker.read_text() != before  # retried on the next session


def test_interrupted_ditto_swap_is_recovered_next_session(env):
    sha = publish_bundle(env["work"], {"poteto-mode": "v1"})
    script = pinned_script(env["tmp"], sha)
    run(env["env"], script)
    share = env["home"] / ".local" / "share"
    heyditto = env["home"] / ".local" / "bin" / "heyditto"
    # A session killed right after moving the old install aside.
    (share / "session-ditto-cli").rename(share / "session-ditto-cli.old.4242")
    assert not os.access(heyditto, os.X_OK)
    lock = env["repo"] / ".claude" / "hooks" / "ditto" / "package-lock.json"
    lock.write_text(lock.read_text() + "\n")
    env["npm_fail"].touch()  # and the next install fails too
    run(env["env"], script)
    assert os.access(heyditto, os.X_OK)
    assert not list(share.glob("session-ditto-cli.old.*"))
    # Killed after the swap but before the old copy was removed: an up-to-date
    # session still clears it.
    (share / "session-ditto-cli.old.4343").mkdir()
    env["npm_fail"].unlink()
    run(env["env"], script)
    run(env["env"], script)
    assert not list(share.glob("session-ditto-cli.old.*"))


def test_interrupted_swap_is_recovered_even_without_a_lockfile(env):
    script = pinned_script(env["tmp"], publish_bundle(env["work"], {"poteto-mode": "v1"}))
    run(env["env"], script)
    share = env["home"] / ".local" / "share"
    (share / "session-ditto-cli").rename(share / "session-ditto-cli.old.4242")
    (env["repo"] / ".claude" / "hooks" / "ditto" / "package-lock.json").unlink()
    run(env["env"], script)
    assert os.access(env["home"] / ".local" / "bin" / "heyditto", os.X_OK)
    assert not list(share.glob("session-ditto-cli.old.*"))


def test_ditto_lockfile_pins_every_package():
    manifest = json.loads((DITTO / "package.json").read_text())
    lock = json.loads((DITTO / "package-lock.json").read_text())
    (version,) = manifest["dependencies"].values()
    assert lock["packages"][""]["dependencies"] == manifest["dependencies"]
    assert lock["packages"]["node_modules/@heyditto/cli"]["version"] == version
    for path, pkg in lock["packages"].items():
        if path:
            assert pkg["resolved"].startswith("https://registry.npmjs.org/"), path
            assert pkg["integrity"].startswith("sha512-"), path


def test_failed_copy_retries_next_session(env):
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", "tdd": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    v2 = publish_bundle(env["work"], {"poteto-mode": "v2", "tdd": "v2"})
    script = pinned_script(env["tmp"], v2)
    stub_cp = env["tmp"] / "bin" / "cp"
    stub_cp.write_text('#!/bin/bash\ncase "$*" in *tdd*) exit 1;; esac\nexec /bin/cp "$@"\n')
    stub_cp.chmod(0o755)
    run(env["env"], script)
    assert skill(env["home"], "tdd") is None
    stub_cp.unlink()
    run(env["env"], script)
    assert skill(env["home"], "tdd") == "v2"
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
