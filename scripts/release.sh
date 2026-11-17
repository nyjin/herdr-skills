#!/usr/bin/env bash
# Publish a skills release when the commits since the last one changed skills/. CI runs it after the checks pass on
# a push to main (.github/workflows/skills-check.yaml, job `release`).
#
# Usage: scripts/release.sh [--dry-run]     --dry-run prints the decision and publishes nothing
#
# The last release is the highest v<major>.<minor>.<patch> tag. Only the commits since it that change skills/ count,
# and their Conventional Commit types set the bump: a breaking change (`type!:` subject or a BREAKING CHANGE footer)
# is major, a feat is minor, a fix or perf is patch. Anything else (docs, test, refactor, chore, ...) publishes
# nothing, and so do commits outside skills/: a herdr plugin's version lives in its herdr-plugin.toml.
# It works on the repository of the current directory, so tests can run it in a throwaway one.
set -euo pipefail

dry_run=0
case "${1:-}" in
  "") ;;
  --dry-run) dry_run=1 ;;
  *) echo "usage: scripts/release.sh [--dry-run]" >&2; exit 2 ;;
esac
cd "$(git rev-parse --show-toplevel)"

last=$(git tag --list --sort=-v:refname | awk '!found && /^v[0-9]+\.[0-9]+\.[0-9]+$/ { print; found = 1 }')
if [ -z "$last" ]; then
  echo "no release tag (v<major>.<minor>.<patch>): nothing to compare with, nothing to release"
  exit 0
fi
echo "last release: $last"

commits=$(git log --no-merges --format=%H "$last..HEAD" -- skills/)
if [ -z "$commits" ]; then
  echo "no commit since $last changes skills/: nothing to release"
  exit 0
fi
echo "commits since $last that change skills/: $(printf '%s\n' "$commits" | wc -l | tr -d ' ')"

breaking='^[a-z]+(\([^)]*\))?!:'
feat='^feat(\([^)]*\))?:'
fix='^(fix|perf)(\([^)]*\))?:'
rank() { case "$1" in major) echo 3 ;; minor) echo 2 ;; patch) echo 1 ;; *) echo 0 ;; esac; }
bump=none
while read -r sha; do
  subject=$(git log -1 --format=%s "$sha")
  body=$(git log -1 --format=%b "$sha")
  if [[ $subject =~ $breaking ]] || grep -qE '^BREAKING[ -]CHANGE:' <<< "$body"; then kind=major
  elif [[ $subject =~ $feat ]]; then kind=minor
  elif [[ $subject =~ $fix ]]; then kind=patch
  else kind=none
  fi
  echo "  ${sha:0:7} ${subject} -> ${kind}"
  if [ "$(rank "$kind")" -gt "$(rank "$bump")" ]; then bump=$kind; fi
done <<< "$commits"

IFS=. read -r major minor patch <<< "${last#v}"
case "$bump" in
  none) echo "no feat, fix, perf or breaking change among them: nothing to release"; exit 0 ;;
  major) next="v$((major + 1)).0.0" ;;
  minor) next="v${major}.$((minor + 1)).0" ;;
  patch) next="v${major}.${minor}.$((patch + 1))" ;;
esac
echo "next version: $next ($bump)"

if [ "$dry_run" = 1 ]; then
  echo "dry run: would run gh skill publish --tag $next"
  exit 0
fi

# gh skill publish tags the tip of the current branch on GitHub, not this checkout. If the branch moved on since this
# run started, that tip holds commits counted by no one and maybe failing the checks: the newer push's run publishes.
branch=$(git symbolic-ref --quiet --short HEAD) \
  || { echo "not on a branch: gh skill publish would tag the default branch's tip, not this commit" >&2; exit 1; }
tip=$(git ls-remote origin "refs/heads/$branch" | cut -f1)
if [ "$tip" != "$(git rev-parse HEAD)" ]; then
  echo "origin's $branch is at ${tip:-nothing}, not at this checkout: nothing published, the newer push's run publishes"
  exit 0
fi
gh skill publish --tag "$next"
