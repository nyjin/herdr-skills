#!/usr/bin/env python3
"""Claude Code hooks that route worktree work to herdr-parallel-worktree inside herdr.

Usage (from a hooks config):
  route.py pre-tool-use    PreToolUse: deny creating a worktree outside the skill — `git worktree add`,
                           EnterWorktree without `path` (which creates one), worktree-isolated Agent calls.
                           For a subagent, also deny writing into a linked worktree other than the session's
                           own. The reason depends on who called: the main session is told to use the skill,
                           a subagent to stop and hand the task back as a HERDR-HANDOFF block, a herdr worker
                           to do the work itself.
  route.py post-tool-use   PostToolUse on Agent/Task in the main session: says what to do if that subagent
                           returns a HERDR-HANDOFF block.

Who called: HERDR_PW_WORKER (exported by the skill into each worker's pane) marks a herdr worker; `agent_id`
in the hook input marks a subagent.

It does nothing — no output, no tokens — outside herdr (HERDR_ENV != 1) or when the user turned the hooks off
("hooks": "off" in DATA_DIR/config.json). Any unexpected error also results in no output, so a broken hook
never blocks the user's work.
"""
import json
import os
import re
import sys

SKILL = "herdr-parallel-worktree"
WORKER_VAR = "HERDR_PW_WORKER"
HANDOFF = (
    "HERDR-HANDOFF\n"
    f"To the main session: load the {SKILL} skill and turn this into a worker, confirming with the user once "
    "(step 0). Do not tell the user to run it with `!` or to turn the hooks off.\n"
    "name: <suggested worker name>\n"
    "repo: <absolute path of the target repository>\n"
    "goal: <one line>\n"
    "branch: <suggested branch, or ->\n"
    "steps:\n"
    "- <step>\n"
    "done: <what was already done, or nothing>"
)
DENY_MAIN = (
    f"Inside herdr, worktree work goes through the {SKILL} skill, so the user can watch each worker in the "
    "herdr sidebar. Load that skill and follow it from step 0, which confirms the tasks with the user once. "
    "This holds even when the plan to use a plain worktree or a subagent came from you or from a subagent. "
    "Only if the user, in this conversation, explicitly asked for a plain git worktree: tell them this hook "
    "blocked it; they can run it themselves with `! <command>`, or turn the hooks off by asking to "
    f"\"turn off the {SKILL} hooks\"."
)
DENY_SUB = (
    "You are a subagent. Inside herdr, work that needs its own worktree runs as a herdr worker, and only the "
    "main session starts workers, after confirming with the user. Do not create the worktree or write into "
    "another worktree, and do not retry another way. Do not suggest running anything with `!` or turning the "
    "hooks off. Stop now and end your final reply with this block, filled in:\n\n" + HANDOFF
)
NOTE_HANDOFF = (
    f"If this subagent returns a HERDR-HANDOFF block, load the {SKILL} skill and continue from its step 0 "
    "with that block as one of the tasks. Do not tell the user to run anything with `!` or to turn the "
    "hooks off."
)


def deny_worker(name, home):
    return (f"You are the herdr worker `{name}`. Workers do not create worktrees or start workers. Do the work "
            f"yourself in your own worktree ({home}). If it really needs a separate worker, put this block, "
            "filled in, in your `## Result` and let the orchestrator decide:\n\n" + HANDOFF)


# `git [global options] worktree add` in command position (start, or after ; & | ( or $( ), optionally
# behind VAR=value assignments — not the phrase quoted inside a commit message or a grep pattern.
WORKTREE_ADD = re.compile(r"(?:^|[;&|(\n]|\$\()\s*(?:\w+=\S*\s+)*(?:command\s+)?git\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+worktree\s+add\b")


def actor(event, env):
    worker = bool(env.get(WORKER_VAR))
    sub = bool(event.get("agent_id"))
    if worker:
        return "worker-sub" if sub else "worker"
    return "sub" if sub else "main"


def git_probe(path):
    return None   # Task 2


def deny(text):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": text}}


def home_of(cwd, probe):
    found = probe(cwd)
    return found[2] if found else cwd


def creates_worktree(tool, args):
    return bool((tool == "Bash" and WORKTREE_ADD.search(args.get("command") or ""))
                or (tool == "EnterWorktree" and not args.get("path"))
                or (tool in ("Agent", "Task") and args.get("isolation") == "worktree"))   # Task: Agent's older name


def decide(event, env, probe=git_probe):
    hook, tool = event.get("hook_event_name"), event.get("tool_name")
    args = event.get("tool_input") or {}
    who = actor(event, env)
    cwd = event.get("cwd") or os.getcwd()
    if hook != "PreToolUse":
        return None
    if creates_worktree(tool, args):
        if who == "main":
            return deny(DENY_MAIN)
        if who == "worker":
            return deny(deny_worker(env[WORKER_VAR], home_of(cwd, probe)))
        return deny(DENY_SUB)
    return None


def enabled():
    if os.environ.get("HERDR_ENV") != "1":
        return False
    base = os.environ.get("HERDR_SKILLS_DATA_HOME") or os.path.expanduser("~/.local/share/herdr-skills")
    try:
        with open(os.path.join(base, SKILL, "config.json"), encoding="utf-8") as f:
            return json.load(f).get("hooks", "on") != "off"
    except (OSError, ValueError, AttributeError):
        return True   # no or unreadable config: the default is on


def main():
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ("pre-tool-use", "post-tool-use") or not enabled():
            return
        try:
            event = json.load(sys.stdin)
        except ValueError:
            return
        out = decide(event, os.environ)
        if out:
            print(json.dumps(out))
    except Exception:   # never block the user's work because of a hook bug
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
