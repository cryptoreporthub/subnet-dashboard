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

# Replace the skills manifest: a header line, then the names in the given
# files. Only a fully written file replaces the old manifest; every write is
# checked, so a full disk keeps the old one.
write_manifest() {
  local header="$1"
  shift
  if { echo "$header" && LC_ALL=C sort -u "$@"; } > "$manifest.tmp" && mv "$manifest.tmp" "$manifest"; then
    return 0
  fi
  rm -f "$manifest.tmp"
  return 1
}

install_pstack_skills() {
  local commit="$bundle_sha" tmp name ref="refs/remotes/origin/$bundle_branch"
  if ! git -C "$repo" cat-file -e "$commit^{commit}" 2>/dev/null; then
    git -C "$repo" -c gc.autoDetach=false fetch --quiet origin "+refs/heads/$bundle_branch:$ref" 9>&- ||
      log "could not fetch $bundle_branch"
  fi
  if ! git -C "$repo" cat-file -e "$commit^{commit}" 2>/dev/null; then
    log "pinned bundle ${commit:0:7} not found; pstack skills not installed"
    return 0
  fi
  if [ -f "$manifest" ] && [ "$(head -n1 "$manifest")" = "$commit" ]; then
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
  mkdir -p "$skills_dir"
  local names="$tmp/names" owned="$tmp/owned" failed=0
  : > "$names"
  # Pick the skills to install before touching the skills dir.
  for dir in "$tmp"/pstack-skills/*/; do
    dir="${dir%/}"
    # A link could point outside the bundle: skip a skill dir that is one, and
    # drop any link inside a skill after copying it.
    [ -L "$dir" ] && continue
    name="$(basename "$dir")"
    [ "$name" = "synced" ] && continue
    # Keep a skill this hook did not install, such as one the platform synced.
    if [ -e "$skills_dir/$name" ] && ! grep -Fqx -- "$name" "$manifest" 2>/dev/null; then
      continue
    fi
    echo "$name" >> "$names"
  done
  # No skill to copy (only links, "synced" or platform copies): keep the
  # manifest as it is, so the skills it lists stay ours for the next bundle.
  if [ ! -s "$names" ]; then
    log "pinned bundle ${commit:0:7} ships no installable skills; nothing changed"
    rm -rf "$tmp"
    return 0
  fi
  : > "$owned"
  if [ -f "$manifest" ] && ! tail -n +2 "$manifest" > "$owned"; then
    log "could not read the skills manifest; nothing changed"
    rm -rf "$tmp"
    return 0
  fi
  # Ownership is recorded one skill ahead of the copy: the manifest, marked
  # incomplete, lists every name the old manifest owns plus each skill this
  # run has started to copy, and nothing it has not touched yet. A crash or a
  # failed write at any point leaves every skill this hook put on disk listed,
  # so a later bundle can still remove it, and a platform copy under a name
  # not reached yet stays unclaimed. The next session retries.
  local claimed="$tmp/claimed"
  : > "$claimed"
  if ! write_manifest incomplete "$owned" "$claimed"; then
    log "could not write the skills manifest; nothing changed, the next session retries"
    rm -rf "$tmp"
    return 0
  fi
  while read -r name; do
    # The platform can sync a skill after the selection above: check again
    # just before claiming it, and keep a copy this hook doesn't own.
    if [ -e "$skills_dir/$name" ] && ! grep -Fqx -- "$name" "$manifest" 2>/dev/null; then
      continue
    fi
    # $claimed only grows once the manifest listing this skill is written.
    if ! { cat "$claimed" && echo "$name"; } > "$claimed.next" ||
      ! write_manifest incomplete "$owned" "$claimed.next" ||
      ! mv "$claimed.next" "$claimed"; then
      # Can't record this skill as ours, so it and the rest are not copied.
      log "could not write the skills manifest; stopped before skill $name"
      failed=1
      break
    fi
    if ! { rm -rf "${skills_dir:?}/$name" && cp -RP "$tmp/pstack-skills/$name" "$skills_dir/$name" \
      && find "$skills_dir/$name" -type l -delete; }; then
      log "could not install skill $name"
      failed=1
    fi
  done < "$names"
  # Remove skills an earlier bundle installed that this bundle no longer ships.
  while read -r name; do
    if [ -n "$name" ] && ! grep -Fqx -- "$name" "$names"; then
      rm -rf "${skills_dir:?}/$name"
    fi
  done < "$owned"
  # The final manifest lists the skills this run touched plus the old ones
  # this bundle still ships (on a stopped run, some of those were not
  # reached). On a failed copy or write it keeps the incomplete header, so
  # the next session retries. If this write fails, the incomplete manifest
  # above stays.
  local kept="$tmp/kept"
  grep -Fx -f "$names" -- "$owned" > "$kept"
  if [ "$?" -gt 1 ]; then
    log "could not finish the skills manifest; the next session retries"
    rm -rf "$tmp"
    return 0
  fi
  # ponytail: ceiling: that manifest can still list an old skill the loop
  # above already removed; a platform copy synced under exactly that name
  # before the next successful run is treated as ours.
  local header="$commit"
  [ "$failed" = 0 ] || header="incomplete"
  if ! write_manifest "$header" "$claimed" "$kept"; then
    log "could not finish the skills manifest; the next session retries"
    failed=1
  fi
  rm -rf "$tmp"
  if [ "$failed" = 0 ]; then
    log "pstack skills installed from $bundle_branch@${commit:0:7}"
  else
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
