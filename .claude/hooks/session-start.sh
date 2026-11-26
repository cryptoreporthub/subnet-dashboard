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

install_pstack_skills() {
  local commit="$bundle_sha" tmp name ref="refs/remotes/origin/$bundle_branch"
  if ! git -C "$repo" cat-file -e "$commit^{commit}" 2>/dev/null; then
    git -C "$repo" fetch --quiet origin "+refs/heads/$bundle_branch:$ref" ||
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
  if ! git -C "$repo" archive "$commit" pstack-skills | tar -x -C "$tmp"; then
    log "could not unpack pstack skills"
    rm -rf "$tmp"
    return 0
  fi
  mkdir -p "$skills_dir"
  local names="$tmp/names" failed=0
  : > "$names"
  for dir in "$tmp"/pstack-skills/*/; do
    name="$(basename "$dir")"
    [ "$name" = "synced" ] && continue
    # Keep a skill this hook did not install, such as one the platform synced.
    if [ -e "$skills_dir/$name" ] && ! grep -Fqx "$name" "$manifest" 2>/dev/null; then
      continue
    fi
    # Record the name first, so a half-copied skill still counts as ours.
    echo "$name" >> "$names"
    if ! { rm -rf "${skills_dir:?}/$name" && cp -R "$dir" "$skills_dir/$name"; }; then
      log "could not install skill $name"
      failed=1
    fi
  done
  # Remove skills an earlier bundle installed that this bundle no longer ships.
  if [ -f "$manifest" ]; then
    tail -n +2 "$manifest" | while read -r name; do
      if [ -n "$name" ] && ! grep -Fqx "$name" "$names"; then
        rm -rf "${skills_dir:?}/$name"
      fi
    done
  fi
  # On a failed copy, record the names but not the commit, so the next session retries.
  if [ "$failed" = 0 ]; then
    { echo "$commit"; cat "$names"; } > "$manifest.tmp"
  else
    { echo "incomplete"; cat "$names"; } > "$manifest.tmp"
  fi
  mv "$manifest.tmp" "$manifest"
  rm -rf "$tmp"
  if [ "$failed" = 0 ]; then
    log "pstack skills installed from $bundle_branch@${commit:0:7}"
  else
    log "pstack skills partly installed from $bundle_branch@${commit:0:7}; the next session retries"
  fi
}

install_ditto_cli() {
  local lock="$ditto_src/package-lock.json" want tmp
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
  if (cd "$tmp" && npm ci --ignore-scripts --no-fund --no-audit >&2) \
    && echo "$want" > "$tmp/.lock-sha" \
    && rm -rf "$ditto_dir" && mv "$tmp" "$ditto_dir" \
    && ln -sfn "$ditto_dir/node_modules/.bin/heyditto" "$ditto_bin"; then
    log "Ditto CLI installed from the lockfile (command: heyditto)"
  else
    rm -rf "$tmp"
    log "Ditto CLI install failed; continuing without it"
  fi
}

install_pstack_skills
install_ditto_cli
# Put the locked heyditto ahead of any other copy for this session's commands.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$CLAUDE_ENV_FILE"
fi

if [ -f "$skills_dir/poteto-mode/SKILL.md" ]; then
  echo "Poteto mode is on for this session. Before your first action, read $skills_dir/poteto-mode/SKILL.md in full and follow it."
else
  echo "Poteto mode is on, but the pstack skills did not install. Tell the user, then load them from the $bundle_branch branch before starting work."
fi
