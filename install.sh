#!/usr/bin/env bash
# Install skills from nyjin/herdr-skills individually (without the Claude Code plugin).
#
# Usage:
#   ./install.sh <skill>...            install the named skills
#   ./install.sh --all                 install every skill
#   ./install.sh --scope project ...   install into the current repo's .claude/skills (default: user)
#
# Uses `gh skill` (GitHub CLI 2.90.0+) when available and falls back to `npx skills`.
# Remote use:
#   curl -fsSL https://raw.githubusercontent.com/nyjin/herdr-skills/main/install.sh | bash -s -- herdr-parallel-worktree
set -euo pipefail

REPO="nyjin/herdr-skills"
scope="user"
all=0
skills=()

while [ $# -gt 0 ]; do
  case "$1" in
    --all) all=1 ;;
    --scope) scope="${2:?--scope needs user or project}"; shift ;;
    -h|--help) sed -n '2,12p' "$0" 2>/dev/null || true; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) skills+=("$1") ;;
  esac
  shift
done

case "$scope" in user|project) ;; *) echo "--scope must be user or project" >&2; exit 2 ;; esac
if [ "$all" -eq 0 ] && [ "${#skills[@]}" -eq 0 ]; then
  echo "name at least one skill, or pass --all" >&2
  exit 2
fi

if gh skill --help >/dev/null 2>&1; then
  echo "Installing with gh skill ($(gh --version | head -1))"
  if [ "$all" -eq 1 ]; then
    gh skill install "$REPO" --all --agent claude-code --scope "$scope"
  else
    for s in "${skills[@]}"; do
      gh skill install "$REPO" "$s" --agent claude-code --scope "$scope"
    done
  fi
elif command -v npx >/dev/null 2>&1; then
  echo "gh skill not available (needs GitHub CLI 2.90.0+); falling back to npx skills"
  args=(-y skills add "$REPO" -a claude-code -y)
  [ "$scope" = user ] && args+=(-g)
  if [ "$all" -eq 1 ]; then
    args+=(-s '*')
  else
    args+=(-s "${skills[@]}")
  fi
  npx "${args[@]}"
else
  echo "Neither gh skill (GitHub CLI 2.90.0+) nor npx is available." >&2
  echo "Upgrade gh (e.g. 'brew upgrade gh') or install Node.js, then run again." >&2
  exit 1
fi
