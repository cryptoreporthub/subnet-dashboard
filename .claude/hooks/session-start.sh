#!/bin/bash
# SessionStart hook: sets up a Claude Code cloud session for this repo's workflow.
#  1. Installs the pstack skills from the pstack-skills-bundle branch into
#     ~/.claude/skills, so the main agent and every subagent can load them.
#  2. Installs the Ditto memory CLI (heyditto) and every dependency from the
#     lockfile in .claude/hooks/ditto.
#  3. Turns on poteto mode for the session.
# Each step is idempotent and skips work that is already done.
set -uo pipefail

# Cloud sessions only. GitHub Actions jobs (the Claude review and mention
# workflows) read the same settings and must stay untouched.
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ] || [ "${GITHUB_ACTIONS:-}" = "true" ]; then
  exit 0
fi

repo="${CLAUDE_PROJECT_DIR:-$(pwd)}"
skills_dir="$HOME/.claude/skills"
manifest="$skills_dir/.pstack-bundle"
# Marks a skill dir as installed by this hook; staging sits on the same
# filesystem as the skills dir so the final rename is atomic.
owner_mark=".pstack-bundle-skill"
stage_dir="$HOME/.claude/.pstack-stage"
bundle_branch="pstack-skills-bundle"
# Pinned bundle commit. Skills are instructions, so a new bundle only lands by
# bumping this pin in a reviewed PR, never by moving the branch.
bundle_sha="53f1161a6a549a5319d655943296ce875c12efda"
# The Ditto CLI and all its dependencies are pinned by .claude/hooks/ditto's
# package-lock.json, which npm ci checks by integrity hash. To upgrade, change
# the version in its package.json and regenerate the lockfile in a reviewed PR.
ditto_src="$repo/.claude/hooks/ditto"
ditto_dir="$HOME/.local/share/session-ditto-cli"
ditto_bin="$HOME/.local/bin/heyditto"

log() { echo "[session-start] $*" >&2; }

# True when $1 is a skill dir this hook installed (a real dir with its marker).
owned() { [ ! -L "$1" ] && [ -f "$1/$owner_mark" ]; }

# Rename $1 to the free name $2 in one step that never replaces anything at
# $2, not even an empty dir a platform sync has only just made (GNU mv -n is
# renameat2 RENAME_NOREPLACE). An mv that skips without failing still leaves
# $1, which counts as a failure. Errors other than mv's "not replacing" note
# are logged. mv runs in this shell (no $(...)), so a kill stops it too.
place() {
  local err="$stage_dir/place.err"
  mv -n -T "$1" "$2" 2>"$err"
  grep -v "not replacing" "$err" >&2
  rm -f "$err"
  [ ! -e "$1" ] && [ ! -L "$1" ]
}

# Move $1, a platform copy of skill $2, to ~/.claude/.pstack-orphans under a
# fresh name, so an earlier orphan never blocks the move.
orphan() {
  mkdir -p "$HOME/.claude/.pstack-orphans" \
    && mv -T "$1" "$(mktemp -u "$HOME/.claude/.pstack-orphans/$2.XXXXXX")"
}

# Move the hook's copy of skill $1 out of the skills dir in one rename, so
# it can be deleted where a crash leaves nothing behind at its name. If what
# was moved turns out not to be the hook's (the platform replaced it after the
# check), it goes straight back.
set_aside() {
  local name="$1"
  if ! mv -T "$skills_dir/$name" "$stage_dir/old/$name"; then
    log "could not replace skill $name"
    return 1
  fi
  if ! owned "$stage_dir/old/$name"; then
    if place "$stage_dir/old/$name" "$skills_dir/$name"; then
      log "kept a platform copy of skill $name that appeared during the install"
    elif orphan "$stage_dir/old/$name" "$name"; then
      # Something else took the name meanwhile: keep the copy out of the stage.
      log "moved a platform copy of skill $name to ~/.claude/.pstack-orphans; check it"
    fi
    # A crash between the two moves leaves that copy in the stage; the next
    # run puts it back first (recover_set_aside).
    return 1
  fi
  return 0
}

# Before the stage is cleared, put back anything in it that isn't the hook's
# own: a platform copy that set_aside moved and a crash kept from moving back.
# The skills dir gets it back if the name is free, else ~/.claude/.pstack-orphans.
recover_set_aside() {
  local dir name
  for dir in "$stage_dir"/old/*; do
    [ -e "$dir" ] || [ -L "$dir" ] || continue
    # The hook's own copy: the stage clear deletes it.
    if owned "$dir"; then
      continue
    fi
    name="$(basename "$dir")"
    if place "$dir" "$skills_dir/$name"; then
      log "put back a platform copy of skill $name left by an interrupted install"
    elif orphan "$dir" "$name"; then
      log "moved a platform copy of skill $name to ~/.claude/.pstack-orphans; check it"
    else
      log "could not put back $dir (a platform copy of skill $name); move it into $skills_dir or delete it. pstack skills not installed"
      return 1
    fi
  done
}

# Delete the hook's set-aside copy of skill $1. It is first renamed into
# trash/, so a crash mid-delete never leaves a half-deleted, unmarked copy in
# old/, where recover_set_aside would take it for a platform copy.
discard() {
  [ -d "$stage_dir/old/$1" ] || return 0
  mv -T "$stage_dir/old/$1" "$stage_dir/trash/$1" && rm -rf "${stage_dir:?}/trash/$1"
}

install_pstack_skills() {
  local commit="$bundle_sha" tmp name dest dir ref="refs/remotes/origin/$bundle_branch"
  # Runs every session, so a copy left in the stage never waits for a new pin.
  recover_set_aside || return 0
  if ! git -C "$repo" cat-file -e "$commit^{commit}" 2>/dev/null; then
    git -C "$repo" -c gc.autoDetach=false fetch --quiet origin "+refs/heads/$bundle_branch:$ref" 9>&- ||
      log "could not fetch $bundle_branch"
  fi
  if ! git -C "$repo" cat-file -e "$commit^{commit}" 2>/dev/null; then
    log "pinned bundle ${commit:0:7} not found; pstack skills not installed"
    return 0
  fi
  if [ "$(cat "$manifest" 2>/dev/null)" = "$commit" ]; then
    return 0
  fi
  tmp="$(mktemp -d)"
  if ! git -C "$repo" archive "$commit" pstack-skills 9>&- | tar -x -C "$tmp" 9>&-; then
    log "could not unpack pstack skills"
    rm -rf "$tmp"
    return 0
  fi
  # A bundle with no skill dirs leaves the glob unmatched; touching nothing is
  # safer than reading it as "every installed skill was dropped".
  set -- "$tmp"/pstack-skills/*/
  if [ ! -d "${1-}" ]; then
    log "pinned bundle ${commit:0:7} has no skills; nothing changed"
    rm -rf "$tmp"
    return 0
  fi
  # Each installed skill carries its own ownership marker, so whose a skill
  # is never depends on a list that a crash can leave out of step with the
  # disk: a dir without the marker (a platform copy) is never replaced or
  # removed. Every change at a skill's name is one rename on the same
  # filesystem: a new copy is staged with its marker and renamed in, and an
  # old one is renamed aside before it is deleted, so a crash never leaves a
  # half-deleted, unmarked dir at the name. Nothing is ever renamed onto a
  # name that is taken, even by an empty dir (place), so a platform copy that
  # lands at a free name mid-install wins.
  # ponytail: ceiling: on a filesystem without RENAME_NOREPLACE, mv -n checks
  # then renames, which leaves a race of a few microseconds.
  # A stage left by a killed session is never ours to finish: start clean.
  rm -rf "${stage_dir:?}" && mkdir -p "$skills_dir" "$stage_dir/new" "$stage_dir/old" "$stage_dir/trash" || {
    log "could not prepare $stage_dir; pstack skills not installed"
    rm -rf "$tmp"
    return 0
  }
  local names="$tmp/names" failed=0
  : > "$names"
  for dir in "$tmp"/pstack-skills/*/; do
    dir="${dir%/}"
    # A link could point outside the bundle: skip a skill dir that is one, and
    # drop any link inside a skill after copying it.
    [ -L "$dir" ] && continue
    name="$(basename "$dir")"
    [ "$name" = "synced" ] && continue
    echo "$name" >> "$names"
    dest="$skills_dir/$name"
    if [ -e "$dest" ] || [ -L "$dest" ]; then
      # Not ours, such as a skill the platform synced: leave it.
      if ! owned "$dest"; then
        continue
      fi
    fi
    if ! { cp -RP "$dir" "$stage_dir/new/$name" && find "$stage_dir/new/$name" -type l -delete \
      && echo "$commit" > "$stage_dir/new/$name/$owner_mark"; }; then
      log "could not install skill $name"
      rm -rf "${stage_dir:?}/new/$name"
      failed=1
      continue
    fi
    if [ -e "$dest" ] && ! set_aside "$name"; then
      rm -rf "${stage_dir:?}/new/$name"
      [ -e "$dest" ] || failed=1
      continue
    fi
    if ! place "$stage_dir/new/$name" "$dest"; then
      rm -rf "${stage_dir:?}/new/$name"
      if [ -e "$dest" ] || [ -L "$dest" ]; then
        log "kept a platform copy of skill $name that appeared during the install"
      else
        log "could not install skill $name"
        # Put the old copy back, so the skill keeps working until the retry.
        [ -d "$stage_dir/old/$name" ] && place "$stage_dir/old/$name" "$dest"
        failed=1
      fi
    fi
    discard "$name"
  done
  # Only links or "synced": keep what is installed, as for an empty bundle.
  if [ ! -s "$names" ]; then
    log "pinned bundle ${commit:0:7} ships no installable skills; nothing changed"
    rm -rf "$tmp"
    return 0
  fi
  # Remove skills an earlier bundle installed that this bundle no longer ships.
  for dir in "$skills_dir"/*/; do
    dir="${dir%/}"
    name="$(basename "$dir")"
    if ! owned "$dir"; then
      continue
    fi
    # Remove only on a clean "not listed" (grep status 1). A grep error keeps
    # the skill and leaves the install unfinished, so the next session retries.
    grep -Fqx -- "$name" "$names"
    case "$?" in
      0) continue ;;
      1) ;;
      *) failed=1; continue ;;
    esac
    set_aside "$name" && discard "$name"
  done
  rm -rf "$tmp"
  # The manifest only records which bundle is fully installed, so the next
  # session skips the work. A failure leaves it as it was, and the next
  # session retries.
  if [ "$failed" = 0 ] && echo "$commit" > "$manifest.tmp" && mv "$manifest.tmp" "$manifest"; then
    log "pstack skills installed from $bundle_branch@${commit:0:7}"
  else
    rm -f "$manifest.tmp"
    log "pstack skills partly installed from $bundle_branch@${commit:0:7}; the next session retries"
  fi
}

install_ditto_cli() {
  local lock="$ditto_src/package-lock.json" want tmp
  # A session killed mid-swap can leave the old install under $ditto_dir.old.PID
  # with nothing at $ditto_dir: put it back, and clear any other leftover.
  local stale
  for stale in "$ditto_dir".old.*; do
    [ -d "$stale" ] || continue
    if [ ! -e "$ditto_dir" ]; then
      mv -T "$stale" "$ditto_dir" && log "restored the Ditto CLI from an interrupted install"
    else
      rm -rf "$stale"
    fi
  done
  # A session killed during npm ci leaves its temp dir (mktemp's six-character
  # suffix). This runs only with the setup lock held, so any such dir is stale.
  for stale in "$ditto_dir".??????; do
    case "$stale" in *.old.*) continue ;; esac
    [ -d "$stale" ] && [ ! -L "$stale" ] && rm -rf "$stale"
  done
  if [ ! -f "$lock" ] || [ ! -f "$ditto_src/package.json" ]; then
    log "Ditto CLI lockfile missing; continuing without it"
    return 0
  fi
  want="$(sha256sum "$lock" | cut -d' ' -f1)"
  if [ "$(cat "$ditto_dir/.lock-sha" 2>/dev/null)" = "$want" ] \
    && [ -x "$ditto_dir/node_modules/.bin/heyditto" ] \
    && [ "$(readlink "$ditto_bin" 2>/dev/null)" = "$ditto_dir/node_modules/.bin/heyditto" ]; then
    return 0
  fi
  mkdir -p "$(dirname "$ditto_dir")" "$(dirname "$ditto_bin")" \
    && tmp="$(mktemp -d "$ditto_dir.XXXXXX")" \
    || { log "Ditto CLI install failed; continuing without it"; return 0; }
  cp "$ditto_src/package.json" "$lock" "$tmp/"
  # npm ci installs exactly what the lockfile lists, checks each package's
  # integrity hash, and fails on any mismatch. No lifecycle scripts run.
  # Move any old install aside, then swap the new one in. mv -T never nests
  # tmp inside an existing dir; on failure the old one is put back.
  local old="$ditto_dir.old.$$"
  if (cd "$tmp" && npm ci --ignore-scripts --no-fund --no-audit >&2 9>&-) \
    && echo "$want" > "$tmp/.lock-sha" \
    && { [ ! -e "$ditto_dir" ] || mv -T "$ditto_dir" "$old"; } \
    && { mv -T "$tmp" "$ditto_dir" || { [ ! -e "$old" ] || mv -T "$old" "$ditto_dir"; false; }; } \
    && rm -rf "$old" \
    && ln -sfn "$ditto_dir/node_modules/.bin/heyditto" "$ditto_bin"; then
    log "Ditto CLI installed from the lockfile (command: heyditto)"
  else
    rm -rf "$tmp"
    log "Ditto CLI install failed; continuing without it"
  fi
}

# Two sessions sharing one HOME must not install at the same time: both installs
# replace directories in place. The lock is held until this script exits.
# Without the lock nothing shared is touched (fail closed): no flock, or a lock
# file that can't be opened, skips both installs.
# ponytail: ceiling: a session that waits past 120s skips both installs for
# that run; the next session does them.
setup_lock="$HOME/.local/share/session-setup.lock"
locked=0
if ! command -v flock >/dev/null 2>&1; then
  log "flock not found; skipping the installs so two sessions can't race"
elif ! mkdir -p "$(dirname "$setup_lock")" || ! exec 9>"$setup_lock"; then
  log "could not open $setup_lock; skipping the installs"
elif flock -w 120 9; then
  locked=1
else
  log "another session is setting up; skipping the installs this time"
fi
if [ "$locked" = 1 ]; then
  install_pstack_skills
  install_ditto_cli
fi
# Put the locked heyditto ahead of any other copy for this session's commands.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
fi

if [ -f "$skills_dir/poteto-mode/SKILL.md" ]; then
  echo "Poteto mode is on for this session. Before your first action, read $skills_dir/poteto-mode/SKILL.md in full and follow it."
else
  echo "Poteto mode is on, but the pstack skills did not install. Tell the user, then load them from the $bundle_branch branch before starting work."
fi
