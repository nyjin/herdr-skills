#!/usr/bin/env python3
"""Claude Code hooks that route worktree work to herdr-parallel-worktree inside herdr.

Usage (from a hooks config):
  route.py pre-tool-use           PreToolUse Bash(worktree add) / EnterWorktree / Agent / Task: deny creating a
                                  worktree outside the skill (R1-R3). The main session is told to use the skill,
                                  a subagent to hand the task back as a HERDR-HANDOFF block, a worker to do it itself.
  route.py pre-tool-use-write     PreToolUse Write/Edit/MultiEdit/NotebookEdit: deny a subagent's or worker's write
                                  outside its own worktree, naming the target's owner (R4).
  route.py post-tool-use          PostToolUse Agent/Task in the main session: how to handle a HERDR-HANDOFF (R6).
  route.py post-tool-use-bash     PostToolUse / PostToolUseFailure Bash: tell a subagent or worker that its command
  route.py post-tool-use-failure  changed a worktree outside its own (R7, observe.py), so it stops and hands it back.

Who called: HERDR_PW_WORKER (exported by the skill into each worker's pane) marks a herdr worker; `agent_id`
in the hook input marks a subagent. Owners come from DATA_DIR/runs.json (owners.py).

It does nothing — no output, no tokens — outside herdr (HERDR_ENV != 1) or when the user turned the hooks off
("hooks": "off" in DATA_DIR/config.json). Any unexpected error also results in no output, so a broken hook
never blocks the user's work.
"""
import os
import sys

# Arguments whose hooks never concern the plain main session (Write/Edit before, Bash after). For them, a run
# with neither `"agent_id"` in the raw input nor HERDR_PW_WORKER set ends here, before json or git are even
# imported: these hooks fire on every edit and every Bash command inside herdr.
NON_MAIN_ARGS = ("pre-tool-use-write", "post-tool-use-bash", "post-tool-use-failure")
ALL_ARGS = ("pre-tool-use", "post-tool-use") + NON_MAIN_ARGS
EVENT_OF_ARG = {"pre-tool-use": "PreToolUse", "pre-tool-use-write": "PreToolUse", "post-tool-use": "PostToolUse",
                "post-tool-use-bash": "PostToolUse", "post-tool-use-failure": "PostToolUseFailure"}
_RAW = None
if __name__ == "__main__" and len(sys.argv) == 2 and sys.argv[1] in NON_MAIN_ARGS:
    _RAW = sys.stdin.buffer.read()
    if b'"agent_id"' not in _RAW and not os.environ.get("HERDR_PW_WORKER"):
        sys.exit(0)

import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import observe  # noqa: E402
import owners  # noqa: E402

SKILL = "herdr-parallel-worktree"
WORKER_VAR = "HERDR_PW_WORKER"


def owner_label(owner):
    if not owner:
        return "<worker name | main-checkout | none>"
    return owner[1] if owner[0] == "worker" else owner[0]


def handoff(owner, repo=None):
    """The block a subagent or worker ends with; the main session routes it by its `owner:` line."""
    return ("HERDR-HANDOFF\n"
            f"To the main session: load the {SKILL} skill and handle this by its `owner:` line (step 0, "
            "Receiving a handoff): pass it to that worker, ask the user about the main checkout, or start a new "
            "worker for `none`, confirming with the user once. Do not tell the user to run it with `!` or to "
            "turn the hooks off.\n"
            "name: <suggested worker name>\n"
            f"repo: {repo or '<absolute path of the target repository>'}\n"
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


def deny_sub(owner, repo=None):
    return ("You are a subagent. Inside herdr, work outside your own worktree goes back to the main session, which "
            "hands it to the worktree's owner or starts a herdr worker after confirming with the user. "
            f"Do not create a worktree or write into {where(owner)}, and do not retry another way. Do not suggest "
            "running anything with `!` or turning the hooks off. Stop now and end your final reply with this "
            "block, filled in:\n\n" + handoff(owner, repo))


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


def deny_worker_write(name, home, owner, repo=None):
    return (f"You are the herdr worker `{name}`. That file is outside your worktree ({home}): it is in "
            f"{where(owner)}. Do not change it, and do not retry another way. Finish the rest of your task in your "
            "own worktree, and put this block, filled in, in your `## Result` so the orchestrator can pass it "
            "on:\n\n" + handoff(owner, repo))


def observed(who, hits, env, home, repo=None):
    """R7: what a subagent or worker is told after its Bash command changed worktrees outside its own."""
    changed = "; ".join(where(own) for _, own in hits)
    blocks = "one block per owner" if len({own[:2] for _, own in hits}) > 1 else "this block"
    if who == "worker":
        return (f"You are the herdr worker `{env.get(WORKER_VAR)}`. Your last command changed {changed}, outside "
                f"your worktree ({home}). Do not change anything there again, and do not try to undo it yourself. "
                "Finish the rest of your task in your own worktree, and put "
                f"{blocks} in your `## Result`, listing what you changed there under `done:`:\n\n"
                + handoff(hits[0][1], repo))
    return ("You are a subagent. Your last command changed " + changed + ", outside your own worktree. Inside "
            "herdr that work goes back to the main session. Do not change anything there again, do not try to "
            "undo it yourself, and do not suggest running anything with `!` or turning the hooks off. Stop now "
            f"and end your final reply with {blocks}, listing what you changed there under `done:`:\n\n"
            + handoff(hits[0][1], repo))


def real_deps(env, probe):
    import tempfile
    return observe.Deps(now=time.time, lstat=os.lstat, realpath=os.path.realpath, git=owners.git, probe=probe,
                        runs=lambda: owners.read_open_runs(owners.runs_path(env)),
                        main_of=owners.main_checkout_of,
                        bg=observe.BgStore(os.path.join(tempfile.gettempdir(), "herdr-pw-observe")))


# `git [global options] worktree add` in command position (start, or after ; & | ( or $( ), optionally
# behind VAR=value assignments. Matched against code_only(command), so the phrase inside a commit message, a
# grep pattern or a heredoc is not a command, and a quoted option value with spaces (`-C "/my repo"`) is one word.
WORKTREE_ADD = re.compile(r"(?:^|[;&|(\n]|\$\()\s*(?:\w+=\S*\s+)*(?:command\s+)?git\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+worktree\s+add\b")

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
    rp = os.path.realpath(path)
    if runs is None:
        runs = owners.read_open_runs(owners.runs_path(env))
    inner = owners.run_owning(rp, runs)
    if owners.inside(rp, home_top) and not observe.nested_root(rp, home_top) \
            and not (inner and inner["worktree"] != home_top and owners.inside(inner["worktree"], home_top)):
        return None                              # home itself, not a worktree nested inside it: no git call
    own = owners.owner_of(path, runs, probe, writer_common, writer_main)
    if own is None or os.path.realpath(own[2]) == home_top or (who == "sub" and own[0] == "main-checkout"):
        return None                              # out of scope, home, or the main session's home
    repo = repo_of(own, runs, writer_main)
    if who == "worker":
        return deny(deny_worker_write(env[WORKER_VAR], home_top, own, repo))
    return deny(deny_sub(own, repo))


def repo_of(own, runs, writer_main):
    """The repository a handoff belongs to: the owning worker's recorded root, else the writer's main checkout."""
    if own and own[0] == "worker":
        r = next((r for r in runs if r.get("name") == own[1] and isinstance(r.get("root"), str)), None)
        if r:
            return r["root"]
    return writer_main


def decide(event, env, probe=git_probe, runs=None, main_of=owners.main_checkout_of, deps=None):
    hook, tool = event.get("hook_event_name"), event.get("tool_name")
    args = event.get("tool_input") or {}
    who = actor(event, env)
    cwd = event.get("cwd") or os.getcwd()
    if hook in ("PostToolUse", "PostToolUseFailure") and tool == "Bash":
        if who == "main":
            return None
        deps = deps or real_deps(env, probe)
        hits = observe.observe(event, env, deps)
        if not hits:
            return None
        home = probe(cwd)
        d = deps or real_deps(env, probe)
        writer_main = (os.path.realpath(home[2]) if home and home[0] == home[1] else d.main_of(cwd)) if home else None
        repo = repo_of(hits[0][1], d.runs(), writer_main)
        text = observed(who, hits, env, os.path.realpath(home[2]) if home else cwd, repo)
        return {"hookSpecificOutput": {"hookEventName": hook, "additionalContext": text}}
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
        if len(sys.argv) != 2 or sys.argv[1] not in ALL_ARGS or not enabled():
            return
        try:
            event = json.loads(_RAW if _RAW is not None else sys.stdin.buffer.read())
        except ValueError:
            return
        if isinstance(event, dict) and not event.get("hook_event_name"):   # hand-written input: trust the argument
            event["hook_event_name"] = EVENT_OF_ARG[sys.argv[1]]
        out = decide(event, os.environ)
        if out:
            print(json.dumps(out))
    except Exception:   # never block the user's work because of a hook bug
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
