#!/usr/bin/env bash
# Install pstack skills (cursor/plugins) into $HOME/.claude/skills, rewritten for Claude Code paths.
# Pinned: bump PSTACK_SHA deliberately after reviewing the upstream diff.
set -euo pipefail
PSTACK_SHA="${PSTACK_SHA:-09d06eb4b97a1020ab31e84030e38baf1099c7dc}"
dest="$HOME/.claude/skills"
if grep -qs "\.claude/projects" "$dest/recall/SKILL.md"; then exit 0; fi

work="$(mktemp -d)"; trap 'rm -rf "$work"' EXIT
git clone -q https://github.com/cursor/plugins "$work/src"
git -C "$work/src" checkout -q "$PSTACK_SHA"
mkdir -p "$dest"; cp -r "$work/src/pstack/skills/"* "$dest/"

# Cursor -> Claude Code paths. Claude transcripts: ~/.claude/projects/<slug>/<uuid>.jsonl,
# slug = absolute path with "/" -> "-" (leading dash kept).
grep -rlE '\.cursor|agent-transcripts' "$dest" | while read -r f; do
  sed -i \
    -e 's#~/\.cursor/projects/<slug>/agent-transcripts/<uuid>/<uuid>\.jsonl#~/.claude/projects/<slug>/<uuid>.jsonl#g' \
    -e 's#with the leading slash dropped and each "/" turned into "-" (so `/Users/you/proj` becomes `Users-you-proj`)#with each "/" turned into "-", leading dash kept (so `/home/user/proj` becomes `-home-user-proj`)#' \
    -e 's#~/\.cursor/rules/pstack-models\.mdc#~/.claude/rules/pstack-models.md#g' \
    -e 's#\.cursor/#.claude/#g' \
    -e 's#<agent-transcripts>#~/.claude/projects/<slug>#g' \
    -e 's#<slugified-repo-path>/agent-transcripts#<slug>#g' \
    -e 's#`agent-transcripts/`#`~/.claude/projects/<slug>/`#g' \
    -e 's#agent-transcripts/#~/.claude/projects/<slug>/#g' \
    "$f"
done
# worktree-audit.sh builds the transcripts dir itself; Claude has no agent-transcripts subdir and keeps the leading dash.
audit="$dest/poteto-mode/scripts/worktree-audit.sh"
sed -i \
  -e "s#slug=\$(printf '%s' \"\$main_wt\" | sed 's\#^/\#\#; s\#/\#-\#g')#slug=\$(printf '%s' \"\$main_wt\" | sed 's\#/\#-\#g')#" \
  -e 's#projects/\$slug/agent-transcripts#projects/$slug#' "$audit"
echo "pstack $PSTACK_SHA installed to $dest"
