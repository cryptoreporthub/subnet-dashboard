#!/bin/bash
# SessionStart hook: sets up a Claude Code cloud session for this repo's workflow.
#  1. Installs the pstack skills from the pstack-skills-bundle branch into
#     ~/.claude/skills, so the main agent and every subagent can load them.
#  2. Installs the Ditto memory CLI (heyditto), pinned.
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
ditto_version="3.22.0"

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
  {
    echo "$commit"
    for dir in "$tmp"/pstack-skills/*/; do
      name="$(basename "$dir")"
      [ "$name" = "synced" ] && continue
      # Keep a skill this hook did not install, such as one the platform synced.
      if [ -e "$skills_dir/$name" ] && ! grep -qx "$name" "$manifest" 2>/dev/null; then
        continue
      fi
      rm -rf "${skills_dir:?}/$name"
      cp -R "$dir" "$skills_dir/$name"
      echo "$name"
    done
  } > "$manifest.tmp"
  mv "$manifest.tmp" "$manifest"
  rm -rf "$tmp"
  log "pstack skills installed from $bundle_branch@${commit:0:7}"
}

install_ditto_cli() {
  if npm ls -g --depth=0 "@heyditto/cli@$ditto_version" >/dev/null 2>&1; then
    return 0
  fi
  if npm install -g --no-fund --no-audit "@heyditto/cli@$ditto_version" >&2; then
    log "Ditto CLI $ditto_version installed (command: heyditto)"
  else
    log "Ditto CLI install failed; continuing without it"
  fi
}

install_pstack_skills
install_ditto_cli

if [ -f "$skills_dir/poteto-mode/SKILL.md" ]; then
  echo "Poteto mode is on for this session. Before your first action, read $skills_dir/poteto-mode/SKILL.md in full and follow it."
else
  echo "Poteto mode is on, but the pstack skills did not install. Tell the user, then load them from the $bundle_branch branch before starting work."
fi
