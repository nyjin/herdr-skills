#!/usr/bin/env python3
"""Claude Code PreToolUse hook that routes worktree creation to herdr-parallel-worktree inside herdr.

Usage (from a hooks config):
  route.py pre-tool-use    PreToolUse: inside herdr, deny creating a worktree outside the skill —
                           `git worktree add`, EnterWorktree without `path` (which creates one), and
                           worktree-isolated Agent calls — telling Claude to use the skill.
                           EnterWorktree with `path` only enters an existing worktree and is allowed.

It does nothing — no output, no tokens — outside herdr (HERDR_ENV != 1) or when the user turned the
hooks off ("hooks": "off" in DATA_DIR/config.json). Any unexpected error also results in no output,
so a broken hook never blocks the user's work.
"""
import json
import os
import re
import sys

SKILL = "herdr-parallel-worktree"
DENY = (f"Inside herdr, worktree work goes through the {SKILL} skill, so the user can watch each worker in the "
        "herdr sidebar. Load that skill and follow it. If the user explicitly asked for a plain git worktree, "
        "tell them this hook blocked it: they can run it themselves with `! <command>`, or turn the hooks off "
        f"by asking to \"turn off the {SKILL} hooks\".")
# `git [global options] worktree add` in command position (start, or after ; & | ( or $( ), optionally
# behind VAR=value assignments — not the phrase quoted inside a commit message or a grep pattern.
WORKTREE_ADD = re.compile(r"(?:^|[;&|(\n]|\$\()\s*(?:\w+=\S*\s+)*(?:command\s+)?git\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+worktree\s+add\b")


def enabled():
    if os.environ.get("HERDR_ENV") != "1":
        return False
    base = os.environ.get("HERDR_SKILLS_DATA_HOME") or os.path.expanduser("~/.local/share/herdr-skills")
    try:
        with open(os.path.join(base, SKILL, "config.json"), encoding="utf-8") as f:
            return json.load(f).get("hooks", "on") != "off"
    except (OSError, ValueError, AttributeError):
        return True   # no or unreadable config: the default is on


def pre_tool_use():
    try:
        event = json.load(sys.stdin)
    except ValueError:
        return
    tool, args = event.get("tool_name"), event.get("tool_input") or {}
    hit = (tool == "Bash" and WORKTREE_ADD.search(args.get("command", ""))) \
        or (tool == "EnterWorktree" and not args.get("path")) \
        or (tool in ("Agent", "Task") and args.get("isolation") == "worktree")   # Task: the Agent tool's older name
    if hit:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": DENY}}))


def main():
    try:
        if len(sys.argv) != 2 or not enabled():
            return
        if sys.argv[1] == "pre-tool-use":
            pre_tool_use()
    except Exception:   # never block the user's work because of a hook bug
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
