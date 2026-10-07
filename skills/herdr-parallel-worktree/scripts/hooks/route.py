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
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import owners  # noqa: E402

SKILL = "herdr-parallel-worktree"
WORKER_VAR = "HERDR_PW_WORKER"


def owner_label(owner):
    if not owner:
        return "<worker name | main-checkout | none>"
    return owner[1] if owner[0] == "worker" else owner[0]


def handoff(owner):
    """The block a subagent or worker ends with; the main session routes it by its `owner:` line."""
    return ("HERDR-HANDOFF\n"
            f"To the main session: load the {SKILL} skill and handle this by its `owner:` line (step 0, "
            "Receiving a handoff): pass it to that worker, ask the user about the main checkout, or start a new "
            "worker for `none`, confirming with the user once. Do not tell the user to run it with `!` or to "
            "turn the hooks off.\n"
            "name: <suggested worker name>\n"
            "repo: <absolute path of the target repository>\n"
            f"owner: {owner_label(owner)}\n"
            "goal: <one line>\n"
            "branch: <suggested branch, or ->\n"
            "steps:\n"
            "- <step>\n"
            "done: <what was already done, or nothing>")


HANDOFF = handoff(None)
NEW = ("none", None, None)   # a new worktree: nobody owns it yet


def where(owner):
    """How a message names the target, by owner."""
    kind, name, top = owner
    if kind == "worker":
        return f"`{top}`, which worker `{name}` owns; the main session will pass this to worker `{name}`"
    if kind == "main-checkout":
        return f"the main checkout `{top}`; the main session will ask the user about it"
    return f"another worktree (`{top}`)" if top else "a new worktree"


DENY_MAIN = (
    f"Inside herdr, worktree work goes through the {SKILL} skill, so the user can watch each worker in the "
    "herdr sidebar. Load that skill and follow it from step 0, which confirms the tasks with the user once. "
    "This holds even when the plan to use a plain worktree or a subagent came from you or from a subagent. "
    "Only if the user, in this conversation, explicitly asked for a plain git worktree: tell them this hook "
    "blocked it; they can run it themselves with `! <command>`, or turn the hooks off by asking to "
    f"\"turn off the {SKILL} hooks\"."
)


def deny_sub(owner):
    return ("You are a subagent. Inside herdr, work outside your own worktree goes back to the main session, which "
            "hands it to the worktree's owner or starts a herdr worker after confirming with the user. "
            f"Do not create a worktree or write into {where(owner)}, and do not retry another way. Do not suggest "
            "running anything with `!` or turning the hooks off. Stop now and end your final reply with this "
            "block, filled in:\n\n" + handoff(owner))


DENY_SUB = deny_sub(NEW)
NOTE_HANDOFF = (
    f"If this subagent returns a HERDR-HANDOFF block, load the {SKILL} skill and handle it by the block's "
    "`owner:` line (step 0, Receiving a handoff). Do not tell the user to run anything with `!` or to turn "
    "the hooks off."
)


def deny_worker_create(name, home):
    return (f"You are the herdr worker `{name}`. Workers do not create worktrees or start workers. Do the work "
            f"yourself in your own worktree ({home}). If it really needs a separate worker, put this block, "
            "filled in, in your `## Result` and let the orchestrator decide:\n\n" + handoff(NEW))


def deny_worker_write(name, home, owner):
    return (f"You are the herdr worker `{name}`. That file is outside your worktree ({home}): it is in "
            f"{where(owner)}. Do not change it, and do not retry another way. Finish the rest of your task in your "
            "own worktree, and put this block, filled in, in your `## Result` so the orchestrator can pass it "
            "on:\n\n" + handoff(owner))


# `git [global options] worktree add` in command position (start, or after ; & | ( or $( ), optionally
# behind VAR=value assignments. Matched against code_only(command), so the phrase inside a commit message, a
# grep pattern or a heredoc is not a command, and a quoted option value with spaces (`-C "/my repo"`) is one word.
WORKTREE_ADD = re.compile(r"(?:^|[;&|(\n]|\$\()\s*(?:\w+=\S*\s+)*(?:command\s+)?git\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+worktree\s+add\b")

# `git -C <dir>` anywhere, or `cd <dir>` in command position. <dir> must be a plain word or a simply quoted
# one with no variables or substitutions; anything this cannot read for certain is left alone.
DIR_ARG = re.compile(r"""(?:\bgit\s+-C|(?:^|[;&|(\n])\s*cd)\s+("[^"$`\\]*"|'[^']*'|[^\s;&|()<>$`'"\\]+)(?=[\s;&|)]|$)""")
WRITE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
QUOTED = re.compile(r"""("[^"]*"|'[^']*')""")
# A heredoc from `<<WORD` (or <<'WORD', <<-WORD) through the line holding only WORD: its body is data, not commands.
HEREDOC = re.compile(r"""<<-?[ \t]*(['"]?)(\w+)\1[^\n]*\n(?:.*?\n)?[ \t]*\2[ \t]*(?=\n|$)""", re.S)


def code_only(command):
    """`command` with heredoc bodies dropped and quoted spans replaced by a placeholder word, so text that is only
    data — a commit message, an echo, a heredoc — is never read as a command."""
    return QUOTED.sub("Q", HEREDOC.sub("<<HEREDOC", command))


def actor(event, env):
    worker = bool(env.get(WORKER_VAR))
    sub = bool(event.get("agent_id"))
    if worker:
        return "worker-sub" if sub else "worker"
    return "sub" if sub else "main"


def git_probe(path):
    """(git_dir, git_common_dir, toplevel) of the checkout holding `path`, all absolute; None if unknown."""
    d = path
    while not os.path.isdir(d):   # a file, or a directory that does not exist yet
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    try:
        r = subprocess.run(["git", "-C", d, "rev-parse", "--path-format=absolute",
                            "--git-dir", "--git-common-dir", "--show-toplevel"],
                           capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = r.stdout.splitlines()
    if r.returncode != 0 or len(lines) != 3:
        return None
    return lines[0], lines[1], lines[2]


def other_worktree(path, cwd, probe):
    """Toplevel of the linked worktree holding `path`, unless it is the session's own (cwd's); else None."""
    path = os.path.normpath(os.path.join(cwd, os.path.expanduser(path)))
    found = probe(path)
    if not found or found[0] == found[1]:   # unknown, or the main checkout
        return None
    home = probe(cwd)
    if not home or home[2] == found[2]:   # own worktree, or the session's own directory is unknown (fail open)
        return None
    return found[2]


def dir_targets(command):
    """Directories that `cd <dir>` or `git -C <dir>` in `command` act on, when they can be read for certain."""
    # Blank out quoted arguments that are not themselves a cd / git -C target, so a commit message or an
    # echo that mentions "cd …" is not read as a command.
    command = HEREDOC.sub("<<HEREDOC", command)
    out = []
    for m in DIR_ARG.finditer(command):
        start = m.start()
        if any(q.start() < start < q.end() for q in QUOTED.finditer(command)):
            continue
        token = m.group(1)
        if token[:1] in "\"'":
            token = token[1:-1]
        if token and token != "-":
            out.append(os.path.expanduser(token))
    return out


def deny(text):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": text}}


def home_of(cwd, probe):
    found = probe(cwd)
    return found[2] if found else cwd


def creates_worktree(tool, args):
    return bool((tool == "Bash" and WORKTREE_ADD.search(code_only(args.get("command") or "")))
                or (tool == "EnterWorktree" and not args.get("path"))
                or (tool in ("Agent", "Task") and args.get("isolation") == "worktree"))   # Task: Agent's older name


def write_target(event, env, probe, runs, main_of):
    """R4: deny a subagent's or worker's Write/Edit outside its own worktree, by the owner of the target."""
    who = actor(event, env)
    args = event.get("tool_input") or {}
    target = args.get(WRITE_TOOLS[event.get("tool_name")]) or ""
    cwd = event.get("cwd") or os.getcwd()
    if who == "main" or not target:
        return None
    home = probe(cwd)
    if not home:
        return None                              # the session's own directory is unknown: fail open
    home_top, writer_common = os.path.realpath(home[2]), os.path.realpath(home[1])
    writer_main = home_top if home[0] == home[1] else main_of(cwd)
    path = os.path.normpath(os.path.join(cwd, os.path.expanduser(target)))
    if owners.inside(os.path.realpath(path), home_top):
        return None
    if runs is None:
        runs = owners.read_open_runs(owners.runs_path(env))
    own = owners.owner_of(path, runs, probe, writer_common, writer_main)
    if own is None or (who == "sub" and own[0] == "main-checkout"):   # out of scope, or the main session's home
        return None
    if who == "worker":
        return deny(deny_worker_write(env[WORKER_VAR], home_top, own))
    return deny(deny_sub(own))


def decide(event, env, probe=git_probe, runs=None, main_of=owners.main_checkout_of):
    hook, tool = event.get("hook_event_name"), event.get("tool_name")
    args = event.get("tool_input") or {}
    who = actor(event, env)
    cwd = event.get("cwd") or os.getcwd()
    if hook == "PostToolUse":
        if tool in ("Agent", "Task") and who == "main":
            return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": NOTE_HANDOFF}}
        return None
    if hook != "PreToolUse":
        return None
    if creates_worktree(tool, args):
        if who == "main":
            return deny(DENY_MAIN)
        if who == "worker":
            return deny(deny_worker_create(env[WORKER_VAR], home_of(cwd, probe)))
        return deny(DENY_SUB)
    if tool in WRITE_TOOLS:
        return write_target(event, env, probe, runs, main_of)
    if who in ("sub", "worker-sub") and tool == "Bash":   # R5, replaced by observing results in a later task
        if any(t and other_worktree(t, cwd, probe) for t in dir_targets(args.get("command") or "")):
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
