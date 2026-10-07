#!/usr/bin/env bash
# Repository checks, run the same way locally and in CI (.github/workflows/skills-check.yaml).
#
# Usage: scripts/check.sh [check ...]     no argument runs every check, in order
#        scripts/check.sh --list          print the check names
#
# Checks: skill-spec names readme manifests finalize-brief hooks runs unit
# Errors are printed as GitHub annotations (::error ...), which read fine in a terminal too.
set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

CHECKS=(skill-spec names readme manifests finalize-brief hooks runs unit)
TMP="${RUNNER_TEMP:-$(mktemp -d)}"
SKILL=skills/herdr-parallel-worktree

# gh skill publish --dry-run validates every skill against the spec. Diagnostics come as
# 'level<TAB>skill<TAB>message'; only errors naming a skill fail. Without `gh skill` (older gh, local use)
# the check is skipped outside CI and fails in CI.
check_skill_spec() {
  if ! gh skill --help >/dev/null 2>&1; then
    if [ -n "${CI:-}" ]; then echo "::error::gh skill is not available (need gh 2.90.0+)"; return 1; fi
    echo "skip: gh skill is not available here (gh 2.90.0+)"; return 0
  fi
  local diag="$TMP/skill-diag.tsv" err="$TMP/skill-stderr.txt" rc=0 lines errors
  NO_COLOR=1 gh skill publish . --dry-run >"$diag" 2>"$err" || rc=$?
  cat "$diag"
  lines=$(grep -cE '^(error|warning)\b' "$diag" || true)
  if [ "$rc" -ne 0 ] && [ "$lines" -eq 0 ]; then
    echo "::error::gh skill publish --dry-run failed to run (rc=${rc})."; cat "$err"; return 1
  fi
  errors=$(grep -E "^error"$'\t'"[^"$'\t'"]+"$'\t' "$diag" || true)
  [ -z "$errors" ] && return 0
  while IFS=$'\t' read -r _ skill msg; do
    echo "::error file=skills/${skill}/SKILL.md::${skill}: ${msg}"
  done <<< "$errors"
  return 1
}

# gh skill silently skips skills whose name breaks the naming rule, so check it directly.
check_names() {
  local fail=0 f dir name
  while IFS= read -r f; do
    dir=$(basename "$(dirname "$f")")
    name=$(awk '/^---$/{n++; next} n==1 && /^name:/{sub(/^name:[[:space:]]*/,""); print; exit}' "$f")
    if [ "$name" != "$dir" ]; then echo "::error file=${f}::name '${name}' != directory '${dir}'"; fail=1; fi
    if ! printf '%s' "$name" | grep -qE '^[a-z0-9]([a-z0-9-]*[a-z0-9])?$'; then
      echo "::error file=${f}::name '${name}' breaks the agentskills naming rule"; fail=1
    fi
  done < <(find skills -mindepth 2 -maxdepth 2 -name SKILL.md | sort)
  return "$fail"
}

# The skills tables between <!-- skills:start --> and <!-- skills:end --> list exactly the skills/ directories.
check_readme() {
  local fail=0 dirs readme table
  dirs=$(find skills -mindepth 2 -maxdepth 2 -name SKILL.md | cut -d/ -f2 | sort)
  for readme in README.md README.ko.md; do
    table=$(awk '/<!-- skills:start -->/{f=1;next} /<!-- skills:end -->/{if(f)exit} f' "$readme" \
      | sed -nE 's/^\| *\[?`([a-z0-9][a-z0-9-]*)`\]?.*/\1/p' | sort)
    if [ "$table" != "$dirs" ]; then
      echo "::error file=${readme}::${readme} table ($(echo $table)) != skills/ ($(echo $dirs))"; fail=1
    fi
  done
  return "$fail"
}

check_manifests() {
  local f
  for f in .claude-plugin/plugin.json .claude-plugin/marketplace.json; do
    jq -e . "$f" >/dev/null || { echo "::error file=${f}::not valid JSON"; return 1; }
  done
  [ "$(jq -r .name .claude-plugin/plugin.json)" = "$(jq -r '.plugins[0].name' .claude-plugin/marketplace.json)" ] \
    || { echo "::error::plugin.json name != marketplace.json plugins[0].name"; return 1; }
}

# An unfilled template must be rejected; a filled brief gets the closing paragraph appended.
check_finalize_brief() {
  local s="$SKILL/scripts/finalize-brief.py" t
  t=$(mktemp); cp "$SKILL/assets/brief-template.md" "$t"
  if python3 "$s" "$t" >/dev/null 2>&1; then echo "::error::an unfilled template should fail"; return 1; fi
  printf '# [t] x\n\n## Goal\ndone\n' > "$t"
  python3 "$s" "$t" >/dev/null || { echo "::error::a filled brief should pass"; return 1; }
  tail -1 "$t" | grep -q 'Do not push or open a pull request.' || { echo "::error::closing paragraph missing"; return 1; }
}

# The route.py hook as Claude Code calls it: silent outside herdr, denies `git worktree add` inside it,
# leaves look-alikes alone, and exits before any work for the plain main session's Bash.
check_hooks() {
  local r="$SKILL/scripts/hooks/route.py" data ev post
  jq -e '.hooks.PreToolUse and .hooks.PostToolUse and .hooks.PostToolUseFailure and (.hooks.SessionStart | not)' \
    hooks/hooks.json >/dev/null || { echo "::error file=hooks/hooks.json::unexpected hook events"; return 1; }
  data=$(mktemp -d)
  pre() { printf '{"hook_event_name":"PreToolUse","cwd":"%s","tool_name":"Bash","tool_input":{"command":%s}}' "$PWD" "$1"; }
  ev=$(pre '"git worktree add ../x -b x"')
  [ -z "$(echo "$ev" | env -u HERDR_ENV python3 "$r" pre-tool-use)" ] \
    || { echo "::error::route.py printed output outside herdr"; return 1; }
  echo "$ev" | HERDR_ENV=1 HERDR_SKILLS_DATA_HOME="$data" python3 "$r" pre-tool-use \
    | jq -e '.hookSpecificOutput.permissionDecision == "deny"' >/dev/null \
    || { echo "::error::route.py did not deny git worktree add inside herdr"; return 1; }
  [ -z "$(pre '"git status"' | HERDR_ENV=1 HERDR_SKILLS_DATA_HOME="$data" python3 "$r" pre-tool-use)" ] \
    || { echo "::error::route.py reacted to git status"; return 1; }
  [ -z "$(pre '"git commit -m \"explain git worktree add\""' | HERDR_ENV=1 HERDR_SKILLS_DATA_HOME="$data" python3 "$r" pre-tool-use)" ] \
    || { echo "::error::route.py read a quoted phrase as a command"; return 1; }
  post='{"hook_event_name":"PostToolUse","cwd":"'"$PWD"'","tool_name":"Bash","duration_ms":10,"tool_input":{"command":"ls"},"tool_response":{"stdout":""}}'
  [ -z "$(echo "$post" | HERDR_ENV=1 HERDR_SKILLS_DATA_HOME="$data" python3 -S "$r" post-tool-use-bash)" ] \
    || { echo "::error::route.py did not exit early for the main session's Bash"; return 1; }
}

check_runs() {
  local r="$SKILL/scripts/runs.py" data
  data=$(mktemp -d)
  python3 "$r" --help >/dev/null || { echo "::error::runs.py --help failed"; return 1; }
  HERDR_SKILLS_DATA_HOME="$data" python3 "$r" show --root . | jq -e 'length == 0' >/dev/null \
    || { echo "::error::runs.py show on an empty registry should print []"; return 1; }
}

# Unit tests (tests/test_*.py). The live_*.py and hook_cost.py scripts start claude and are run by hand.
check_unit() {
  python3 -m unittest discover -s "$SKILL/tests" || { echo "::error::unit tests failed"; return 1; }
}

run_check() {
  local fn="check_${1//-/_}"
  if ! declare -F "$fn" >/dev/null; then echo "unknown check: $1 (known: ${CHECKS[*]})" >&2; return 2; fi
  echo "== $1"
  "$fn"
}

main() {
  if [ "${1:-}" = "--list" ]; then printf '%s\n' "${CHECKS[@]}"; return 0; fi
  local -a todo failed=()
  if [ "$#" -gt 0 ]; then todo=("$@"); else todo=("${CHECKS[@]}"); fi
  local c rc
  for c in "${todo[@]}"; do
    run_check "$c"; rc=$?
    [ "$rc" -eq 2 ] && return 2
    [ "$rc" -ne 0 ] && failed+=("$c")
  done
  if [ "${#failed[@]}" -gt 0 ]; then echo "failed: ${failed[*]}"; return 1; fi
  echo "all passed: ${todo[*]}"
}

main "$@"
