"""Behavior tests for .claude/hooks/session-start.sh against a throwaway git origin."""

import json
import os
import re
import shutil
import subprocess
import time
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
        # A killed run never removes its mktemp dir: keep those inside tmp_path.
        "TMPDIR": str(tmp_path),
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


@pytest.mark.parametrize("bundle", ["no-skills-dir", "no-skill-dirs"])
def test_bundle_without_skills_leaves_installed_ones(env, bundle):
    # A pin whose archive fails, or holds no skill dirs, must not read as
    # "every installed skill was dropped".
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    manifest = env["home"] / ".claude" / "skills" / ".pstack-bundle"
    before = manifest.read_text()
    work = env["work"]
    if bundle == "no-skill-dirs":
        shutil.rmtree(work / "pstack-skills")
        (work / "pstack-skills").mkdir()
        (work / "pstack-skills" / "README.md").write_text("empty")
        git(work, "add", "-A")
        git(work, "commit", "-qm", bundle)
        git(work, "push", "-q", "-f", "origin", "HEAD:refs/heads/pstack-skills-bundle")
        empty = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=work, check=True, capture_output=True, text=True
        ).stdout.strip()
    else:
        empty = publish_bundle(work, {})
    run(env["env"], pinned_script(env["tmp"], empty))
    assert skill(env["home"], "poteto-mode") == "v1"
    assert manifest.read_text() == before


def test_bundle_with_nothing_installable_keeps_ownership(env):
    # A bundle that ships only "synced" copies nothing; the skills the hook
    # installed must still be updated and dropped by the next bundle.
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", "tdd": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    v2 = publish_bundle(env["work"], {"synced": "x"})
    run(env["env"], pinned_script(env["tmp"], v2))
    assert skill(env["home"], "poteto-mode") == "v1"
    v3 = publish_bundle(env["work"], {"poteto-mode": "v3"})
    run(env["env"], pinned_script(env["tmp"], v3))
    assert skill(env["home"], "poteto-mode") == "v3"
    assert skill(env["home"], "tdd") is None


@pytest.mark.skipif(not os.path.exists("/dev/full"), reason="needs /dev/full")
def test_failed_manifest_write_retries_next_session(env):
    # A full disk when recording the installed bundle leaves the old record,
    # so the next session redoes the install; the skills stay owned and a
    # later bundle still removes the one it drops.
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", "old": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    manifest = env["home"] / ".claude" / "skills" / ".pstack-bundle"
    tmp_manifest = Path(str(manifest) + ".tmp")
    tmp_manifest.symlink_to("/dev/full")
    v2 = publish_bundle(env["work"], {"poteto-mode": "v2", "old": "v2", "added": "v2"})
    run(env["env"], pinned_script(env["tmp"], v2))
    assert manifest.read_text().strip() == v1
    assert not tmp_manifest.is_symlink()
    assert skill(env["home"], "added") == "v2"
    run(env["env"], pinned_script(env["tmp"], v2))
    assert manifest.read_text().strip() == v2
    v3 = publish_bundle(env["work"], {"poteto-mode": "v3"})
    run(env["env"], pinned_script(env["tmp"], v3))
    assert skill(env["home"], "poteto-mode") == "v3"
    assert skill(env["home"], "old") is None
    assert skill(env["home"], "added") is None
    assert skill(env["home"], "kept") == "platform copy"


def test_crash_mid_copy_keeps_ownership(env):
    # The session dies right after staging "added" (cp kills the script
    # through BASH_ENV): the skills already in place stay the hook's, so a
    # later bundle still updates and removes them, and the half-staged copy
    # never lands.
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", "old": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    v2 = publish_bundle(env["work"], {"poteto-mode": "v2", "added": "v2"})
    shim = env["tmp"] / "crash-cp.sh"
    shim.write_text('cp() { command cp "$@"; case "$*" in *"/added"*) kill -9 $$ ;; esac; }\n')
    proc = subprocess.run(
        ["bash", str(pinned_script(env["tmp"], v2))],
        env={**env["env"], "BASH_ENV": str(shim)}, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    v3 = publish_bundle(env["work"], {"poteto-mode": "v3"})
    run(env["env"], pinned_script(env["tmp"], v3))
    assert skill(env["home"], "poteto-mode") == "v3"
    assert skill(env["home"], "old") is None
    assert skill(env["home"], "added") is None
    assert skill(env["home"], "kept") == "platform copy"


def test_crash_leaves_skills_not_reached_unclaimed(env):
    # The session dies after copying the first new skill. A platform copy that
    # appears later under a name the run never reached is not ours: a bundle
    # that doesn't ship it must leave it alone (Replit's sequence).
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", "old": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    v2 = publish_bundle(env["work"], {"a-first": "v2", "poteto-mode": "v2", "z-platform": "v2"})
    shim = env["tmp"] / "crash-cp.sh"
    shim.write_text('cp() { command cp "$@"; case "$*" in *"/a-first"*) kill -9 $$ ;; esac; }\n')
    proc = subprocess.run(
        ["bash", str(pinned_script(env["tmp"], v2))],
        env={**env["env"], "BASH_ENV": str(shim)}, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    platform = env["home"] / ".claude" / "skills" / "z-platform"
    platform.mkdir()
    (platform / "SKILL.md").write_text("platform copy")
    v3 = publish_bundle(env["work"], {"poteto-mode": "v3"})
    run(env["env"], pinned_script(env["tmp"], v3))
    assert skill(env["home"], "z-platform") == "platform copy"
    assert skill(env["home"], "a-first") is None
    assert skill(env["home"], "old") is None
    assert skill(env["home"], "poteto-mode") == "v3"


def crash_on_move(env, name):
    """A BASH_ENV shim that kills the hook just before it moves skill `name` into place."""
    shim = env["tmp"] / f"crash-mv-{name}.sh"
    shim.write_text(
        'mv() { case "${@: -2:1}" in */.pstack-stage/new/%s) kill -9 $$ ;; esac; command mv "$@"; }\n'
        % name
    )
    return shim


@pytest.mark.parametrize("owned_before", [False, True])
def test_crash_before_a_skill_is_placed_never_claims_its_name(env, owned_before):
    # Replit's sequence: the session dies after it removed or never had the
    # skill, before the new copy is in place. A platform copy that lands under
    # that name before the next session is not ours, and a bundle that drops
    # the name must leave it alone.
    old = {"z-platform": "v1"} if owned_before else {}
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", **old})
    run(env["env"], pinned_script(env["tmp"], v1))
    v2 = publish_bundle(env["work"], {"a-first": "v2", "poteto-mode": "v2", "z-platform": "v2"})
    proc = subprocess.run(
        ["bash", str(pinned_script(env["tmp"], v2))],
        env={**env["env"], "BASH_ENV": str(crash_on_move(env, "z-platform"))},
        capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    assert skill(env["home"], "a-first") == "v2"
    platform = env["home"] / ".claude" / "skills" / "z-platform"
    assert not platform.exists()
    platform.mkdir()
    (platform / "SKILL.md").write_text("platform copy")
    v3 = publish_bundle(env["work"], {"poteto-mode": "v3"})
    run(env["env"], pinned_script(env["tmp"], v3))
    assert skill(env["home"], "z-platform") == "platform copy"
    assert skill(env["home"], "a-first") is None
    assert skill(env["home"], "poteto-mode") == "v3"
    assert not (env["home"] / ".claude" / ".pstack-stage" / "new" / "z-platform").exists()


@pytest.mark.parametrize("deleted", ["poteto-mode", "old"])
def test_crash_while_deleting_an_old_copy_leaves_no_stuck_skill(env, deleted):
    # The session dies part way through deleting the hook's old copy of a
    # skill, either one being replaced (poteto-mode) or one the bundle dropped
    # (old). rm walks a dir in no set order, so the marker can go first; the
    # shim removes just the marker, then kills the script. The half-deleted
    # copy must never be left at the skill's name looking like a platform
    # copy: the next bundle still installs and removes as usual.
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", "old": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    v2 = publish_bundle(env["work"], {"poteto-mode": "v2"})
    shim = env["tmp"] / "crash-rm.sh"
    shim.write_text(
        'rm() {\n'
        '  local a\n'
        '  for a in "$@"; do case "$a" in */%s)\n'
        '    command rm -f "$a/.pstack-bundle-skill"; kill -9 $$ ;;\n'
        '  esac; done\n'
        '  command rm "$@"\n'
        '}\n' % deleted
    )
    proc = subprocess.run(
        ["bash", str(pinned_script(env["tmp"], v2))],
        env={**env["env"], "BASH_ENV": str(shim)}, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    v3 = publish_bundle(env["work"], {"poteto-mode": "v3"})
    run(env["env"], pinned_script(env["tmp"], v3))
    assert skill(env["home"], "poteto-mode") == "v3"
    assert skill(env["home"], "old") is None
    assert skill(env["home"], "kept") == "platform copy"


@pytest.mark.parametrize("name_taken", [False, True])
def test_crash_while_putting_back_a_platform_copy_loses_nothing(env, name_taken):
    # The platform replaces the hook's z-platform after the hook checked it
    # (the shim swaps in a platform copy just as the hook moves it aside), and
    # the session dies just before moving it back. The next session puts it
    # back before clearing the stage, or, if something else took the name
    # meanwhile, keeps it in ~/.claude/.pstack-orphans (Replit's sequence).
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", "z-platform": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    skills = env["home"] / ".claude" / "skills"
    shim = env["tmp"] / "crash-put-back.sh"
    shim.write_text(
        'mv() {\n'
        '  case "${@: -2:1}" in\n'
        '    %(s)s/z-platform)\n'
        '      command rm -f %(s)s/z-platform/.pstack-bundle-skill\n'
        '      builtin printf "platform copy" > %(s)s/z-platform/SKILL.md ;;\n'
        '    */.pstack-stage/old/z-platform) kill -9 $$ ;;\n'
        '  esac\n'
        '  command mv "$@"\n'
        '}\n' % {"s": skills}
    )
    v2 = publish_bundle(env["work"], {"poteto-mode": "v2", "z-platform": "v2"})
    proc = subprocess.run(
        ["bash", str(pinned_script(env["tmp"], v2))],
        env={**env["env"], "BASH_ENV": str(shim)}, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    assert skill(env["home"], "z-platform") is None
    if name_taken:
        (skills / "z-platform").mkdir()
        (skills / "z-platform" / "SKILL.md").write_text("newer platform copy")
    run(env["env"], pinned_script(env["tmp"], v2))
    orphans = list((env["home"] / ".claude" / ".pstack-orphans").glob("z-platform.*"))
    if name_taken:
        assert skill(env["home"], "z-platform") == "newer platform copy"
        assert len(orphans) == 1 and (orphans[0] / "SKILL.md").read_text() == "platform copy"
    else:
        assert skill(env["home"], "z-platform") == "platform copy"
        assert orphans == []
    assert skill(env["home"], "poteto-mode") == "v2"


def test_failed_put_back_keeps_the_stage_for_the_next_session(env):
    # Same crash as above, but the next session can't move the platform copy
    # out of the stage either: it must not clear the stage, and a later
    # session that can still puts the copy back.
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", "z-platform": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    skills = env["home"] / ".claude" / "skills"
    shim = env["tmp"] / "crash-put-back.sh"
    shim.write_text(
        'mv() {\n'
        '  case "${@: -2:1}" in\n'
        '    %(s)s/z-platform)\n'
        '      command rm -f %(s)s/z-platform/.pstack-bundle-skill\n'
        '      builtin printf "platform copy" > %(s)s/z-platform/SKILL.md ;;\n'
        '    */.pstack-stage/old/z-platform) kill -9 $$ ;;\n'
        '  esac\n'
        '  command mv "$@"\n'
        '}\n' % {"s": skills}
    )
    v2 = publish_bundle(env["work"], {"poteto-mode": "v2", "z-platform": "v2"})
    script = pinned_script(env["tmp"], v2)
    proc = subprocess.run(
        ["bash", str(script)],
        env={**env["env"], "BASH_ENV": str(shim)}, capture_output=True, text=True, timeout=60,
    )
    assert proc.returncode != 0
    stuck = env["tmp"] / "mv-fails.sh"
    stuck.write_text(
        'mv() { case "${@: -2:1}" in */.pstack-stage/old/z-platform) return 1 ;; esac; command mv "$@"; }\n'
    )
    run({**env["env"], "BASH_ENV": str(stuck)}, script)
    staged = env["home"] / ".claude" / ".pstack-stage" / "old" / "z-platform" / "SKILL.md"
    assert staged.read_text() == "platform copy"
    run(env["env"], script)
    assert skill(env["home"], "z-platform") == "platform copy"
    assert skill(env["home"], "poteto-mode") == "v2"


@pytest.mark.parametrize("when", ["before its turn", "while it is staged", "as it is placed"])
def test_platform_copy_synced_mid_install_is_kept(env, when):
    # The platform syncs a skill while the hook runs: before the hook reaches
    # that name (while it places the first skill), after the hook checked the
    # name was free (while it stages its copy), or right as the hook moves its
    # copy into place. Each time the platform copy stays and is never treated
    # as the hook's (Cursor's race).
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    v2 = publish_bundle(env["work"], {"a-first": "v2", "poteto-mode": "v2", "z-platform": "v2"})
    platform = env["home"] / ".claude" / "skills" / "z-platform"
    trigger = "a-first" if when == "before its turn" else "z-platform"
    tool = "cp" if when == "while it is staged" else "mv"
    shim = env["tmp"] / "sync-mid-install.sh"
    shim.write_text(
        '%(tool)s() {\n'
        '  case "${@: -2:1} ${@: -1}" in *"/.pstack-stage/new/%(t)s"*)\n'
        '    [ -e %(p)s ] || { mkdir %(p)s && builtin printf "platform copy" > %(p)s/SKILL.md; } ;;\n'
        '  esac\n'
        '  command %(tool)s "$@"\n'
        '}\n' % {"t": trigger, "p": platform, "tool": tool}
    )
    run({**env["env"], "BASH_ENV": str(shim)}, pinned_script(env["tmp"], v2))
    assert skill(env["home"], "z-platform") == "platform copy"
    assert skill(env["home"], "a-first") == "v2"
    assert skill(env["home"], "poteto-mode") == "v2"
    v3 = publish_bundle(env["work"], {"poteto-mode": "v3"})
    run(env["env"], pinned_script(env["tmp"], v3))
    assert skill(env["home"], "z-platform") == "platform copy"
    assert skill(env["home"], "a-first") is None


@pytest.mark.parametrize("owned_before", [False, True])
def test_empty_platform_dir_made_just_before_placing_is_never_taken(env, owned_before):
    # The platform sync has only made an empty dir at a skill's name when the
    # hook moves its copy there (Replit's sequence). A plain rename would
    # replace the empty dir and mark it as the hook's, so the platform's later
    # files would be deleted with it once a bundle drops the skill. The hook
    # must leave the dir alone, whether the name was free or held the hook's
    # older copy.
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", **({"z-platform": "v1"} if owned_before else {})})
    run(env["env"], pinned_script(env["tmp"], v1))
    platform = env["home"] / ".claude" / "skills" / "z-platform"
    shim = env["tmp"] / "empty-dir.sh"
    shim.write_text(
        'mv() {\n'
        '  case "${@: -2:1}" in */.pstack-stage/new/z-platform) [ -e %(p)s ] || command mkdir %(p)s ;; esac\n'
        '  command mv "$@"\n'
        '}\n' % {"p": platform}
    )
    v2 = publish_bundle(env["work"], {"poteto-mode": "v2", "z-platform": "v2"})
    run({**env["env"], "BASH_ENV": str(shim)}, pinned_script(env["tmp"], v2))
    assert platform.is_dir() and not (platform / ".pstack-bundle-skill").exists()
    (platform / "SKILL.md").write_text("platform copy")  # the sync finishes
    v3 = publish_bundle(env["work"], {"poteto-mode": "v3"})
    run(env["env"], pinned_script(env["tmp"], v3))
    assert skill(env["home"], "z-platform") == "platform copy"
    assert skill(env["home"], "poteto-mode") == "v3"


# Counts every file command the hook runs. At call SWEEP_INJECT it plays the
# platform syncing skill "late" (if the name is free) and at call SWEEP_KILL
# it kills the hook. Matching on call order, not on paths, keeps the sweep
# about behavior: it holds whatever the stage looks like inside.
SWEEP_SHIM = """
__step() {
  local n=$(( $(<"$SWEEP_COUNT") + 1 ))
  builtin printf '%s' "$n" > "$SWEEP_COUNT"
  if [ "$n" = "$SWEEP_INJECT" ] && [ ! -e "$SWEEP_LATE" ]; then
    command mkdir "$SWEEP_LATE" && builtin printf 'platform copy' > "$SWEEP_LATE/SKILL.md"
    builtin printf 'injected' > "$SWEEP_COUNT.injected"
  fi
  [ "$n" = "$SWEEP_KILL" ] && kill -9 $$
}
mv() { __step; command mv "$@"; }
cp() { __step; command cp "$@"; }
rm() { __step; command rm "$@"; }
mkdir() { __step; command mkdir "$@"; }
find() { __step; command find "$@"; }
"""


def test_crash_at_any_step_converges_and_loses_no_platform_copy(env):
    # An upgrade from v1 to v2 is killed at every file command in turn, with
    # the platform syncing a skill the bundle also ships one step earlier.
    # Whichever step the crash lands on, the next session ends with the v2
    # skills, the dropped skill gone, every platform copy kept at its name,
    # and nothing orphaned or left in the stage.
    v1 = publish_bundle(env["work"], {"poteto-mode": "v1", "old": "v1", "kept": "v1"})
    run(env["env"], pinned_script(env["tmp"], v1))
    v2 = publish_bundle(env["work"], {"poteto-mode": "v2", "kept": "v2", "late": "v2"})
    script = pinned_script(env["tmp"], v2)
    home, snapshot = env["home"], env["tmp"] / "home-v1"
    shutil.copytree(home, snapshot, symlinks=True)
    shim = env["tmp"] / "sweep.sh"
    shim.write_text(SWEEP_SHIM)
    count = env["tmp"] / "sweep-count"
    late = home / ".claude" / "skills" / "late"
    injected_runs = 0
    for kill_at in range(1, 200):
        shutil.rmtree(home)
        shutil.copytree(snapshot, home, symlinks=True)
        count.write_text("0")
        Path(f"{count}.injected").unlink(missing_ok=True)
        proc = subprocess.run(
            ["bash", str(script)],
            env={**env["env"], "BASH_ENV": str(shim), "SWEEP_COUNT": str(count),
                 "SWEEP_INJECT": str(kill_at - 1), "SWEEP_KILL": str(kill_at),
                 "SWEEP_LATE": str(late)},
            capture_output=True, text=True, timeout=60,
        )
        finished = proc.returncode == 0
        injected = Path(f"{count}.injected").exists()
        injected_runs += injected
        out = subprocess.run(["bash", str(script)], env=env["env"], capture_output=True,
                             text=True, timeout=60)
        where = f"killed at call {kill_at}: {out.stderr}"
        assert out.returncode == 0, where
        assert skill(home, "poteto-mode") == "v2", where
        assert skill(home, "old") is None, where
        assert skill(home, "kept") == "platform copy", where
        if injected:
            assert skill(home, "late") == "platform copy", where
            assert not (late / ".pstack-bundle-skill").exists(), where
        else:
            assert skill(home, "late") == "v2", where
        assert (home / ".claude" / "skills" / ".pstack-bundle").read_text().strip() == v2, where
        orphans = home / ".claude" / ".pstack-orphans"
        assert not orphans.exists() or not any(orphans.iterdir()), where
        stage = home / ".claude" / ".pstack-stage"
        for part in ("new", "old", "trash"):
            assert not (stage / part).exists() or not any((stage / part).iterdir()), where
        if finished:
            break
    else:
        pytest.fail("the hook never ran to the end")
    assert kill_at > 10  # the sweep really walked the install
    assert injected_runs > 0  # and the platform really synced during it


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
    (share / "session-ditto-cli.Ab12Cd").mkdir()  # a temp dir from a killed npm ci
    env["npm_fail"].unlink()
    run(env["env"], script)
    run(env["env"], script)
    assert not list(share.glob("session-ditto-cli.old.*"))
    assert not (share / "session-ditto-cli.Ab12Cd").exists()


def test_interrupted_swap_is_recovered_even_without_a_lockfile(env):
    script = pinned_script(env["tmp"], publish_bundle(env["work"], {"poteto-mode": "v1"}))
    run(env["env"], script)
    share = env["home"] / ".local" / "share"
    (share / "session-ditto-cli").rename(share / "session-ditto-cli.old.4242")
    (env["repo"] / ".claude" / "hooks" / "ditto" / "package-lock.json").unlink()
    run(env["env"], script)
    assert os.access(env["home"] / ".local" / "bin" / "heyditto", os.X_OK)
    assert not list(share.glob("session-ditto-cli.old.*"))


@pytest.mark.skipif(shutil.which("flock") is None, reason="needs flock")
def test_setup_waits_for_another_sessions_lock(env):
    script = pinned_script(env["tmp"], publish_bundle(env["work"], {"poteto-mode": "v1"}))
    share = env["home"] / ".local" / "share"
    share.mkdir(parents=True, exist_ok=True)
    # Another session holds the setup lock for 2 seconds.
    holder = subprocess.Popen(
        ["flock", str(share / "session-setup.lock"), "sh", "-c", "echo held; sleep 2"],
        stdout=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "held"
        start = time.monotonic()
        run(env["env"], script)
        assert time.monotonic() - start >= 1.5
    finally:
        try:
            holder.wait(timeout=10)
        except subprocess.TimeoutExpired:
            holder.kill()
        holder.stdout.close()
    assert os.access(env["home"] / ".local" / "bin" / "heyditto", os.X_OK)
    assert skill(env["home"], "poteto-mode")


def path_without_flock(tmp):
    """A PATH dir that links every command on PATH except flock."""
    bin_dir = tmp / "no-flock-bin"
    bin_dir.mkdir()
    for d in os.environ["PATH"].split(os.pathsep):
        # Skip wrapper dirs (such as a sandbox's rm guard) that find the real
        # command through their own location; link the system copies instead.
        if not os.path.isdir(d) or "rm-guard" in d:
            continue
        for name in os.listdir(d):
            target = bin_dir / name
            if name != "flock" and not target.exists() and not target.is_symlink():
                target.symlink_to(os.path.join(d, name))
    return bin_dir


def test_without_flock_nothing_shared_is_touched(env):
    script = pinned_script(env["tmp"], publish_bundle(env["work"], {"poteto-mode": "v1"}))
    share = env["home"] / ".local" / "share"
    share.mkdir(parents=True, exist_ok=True)
    # An interrupted swap: without the lock even its recovery must wait.
    stale = share / "session-ditto-cli.old.1"
    stale.mkdir()
    stub_bin = env["env"]["PATH"].split(os.pathsep)[0]
    no_flock = {**env["env"], "PATH": f"{stub_bin}:{path_without_flock(env['tmp'])}"}
    assert subprocess.run(["bash", "-c", "command -v flock"], env=no_flock).returncode != 0
    proc = subprocess.run(
        ["bash", str(script)], env=no_flock, capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    assert "flock not found" in proc.stderr
    assert not env["npm_log"].exists()
    assert not (env["home"] / ".local" / "bin" / "heyditto").exists()
    assert skill(env["home"], "poteto-mode") is None
    assert stale.is_dir()


def test_lock_that_cannot_be_opened_skips_the_installs(env):
    script = pinned_script(env["tmp"], publish_bundle(env["work"], {"poteto-mode": "v1"}))
    # A directory where the lock file should be: the open fails.
    (env["home"] / ".local" / "share" / "session-setup.lock").mkdir(parents=True)
    proc = subprocess.run(
        ["bash", str(script)], env=env["env"], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, proc.stderr
    assert "could not open" in proc.stderr
    assert not env["npm_log"].exists()
    assert not (env["home"] / ".local" / "bin" / "heyditto").exists()
    assert skill(env["home"], "poteto-mode") is None


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
    assert skill(env["home"], "tdd") == "v1"  # the old copy stays until a new one is staged
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
