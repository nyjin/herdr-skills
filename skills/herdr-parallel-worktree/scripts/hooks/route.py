#!/usr/bin/env python3
"""Claude Code hooks that route worktree work to herdr-parallel-worktree inside herdr.

Usage (from a hooks config):
  route.py pre-tool-use           PreToolUse Bash(worktree add) / EnterWorktree / Agent / Task: worktree creation
                                  (R1-R3). The main session's EnterWorktree and detached checkouts go through; its
                                  other `git worktree add` is pointed at EnterWorktree, and a worktree-isolated Agent
                                  at the skill. A subagent is told to hand the task back as a HERDR-HANDOFF block, a
                                  worker to do it itself.
  route.py pre-tool-use-write     PreToolUse Write/Edit/MultiEdit/NotebookEdit: deny a subagent's or worker's write
                                  outside its own worktree, naming the target's owner (R4).
  route.py post-tool-use          PostToolUse in the main session. Agent/Task: how to handle a HERDR-HANDOFF (R6).
                                  EnterWorktree: open the worktree Claude Code just made in the herdr sidebar;
                                  ExitWorktree that removed it: close that workspace (R8).
  route.py post-tool-use-bash     PostToolUse / PostToolUseFailure Bash: tell a subagent or worker that its command
  route.py post-tool-use-failure  changed a worktree outside its own (R7, observe.py), so it stops and hands it back.
  route.py session-start          SessionStart: tell the session its role, orchestrator or worker <name> (R9).
  route.py user-prompt-submit     UserPromptSubmit in the main session: a prompt that starts with `/<dispatching skill>`
                                  gets a pointer to the dispatch guide; any other prompt ends before json is imported.

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
ALL_ARGS = ("pre-tool-use", "post-tool-use", "session-start", "user-prompt-submit") + NON_MAIN_ARGS
EVENT_OF_ARG = {"pre-tool-use": "PreToolUse", "pre-tool-use-write": "PreToolUse", "post-tool-use": "PostToolUse",
                "post-tool-use-bash": "PostToolUse", "post-tool-use-failure": "PostToolUseFailure",
                "session-start": "SessionStart", "user-prompt-submit": "UserPromptSubmit"}
_RAW = None
if __name__ == "__main__" and len(sys.argv) == 2 and sys.argv[1] in NON_MAIN_ARGS:
    _RAW = sys.stdin.buffer.read()
    if b'"agent_id"' not in _RAW and not os.environ.get("HERDR_PW_WORKER"):
        sys.exit(0)
elif __name__ == "__main__" and len(sys.argv) == 2 and sys.argv[1] == "user-prompt-submit":
    # Fires on every prompt: only one that starts with `/` (a slash command) can concern us.
    import re  # noqa: E402
    _RAW = sys.stdin.buffer.read()
    if not re.search(rb'"prompt"\s*:\s*"\s*/', _RAW):
        sys.exit(0)

import json  # noqa: E402
import re  # noqa: E402
import shlex  # noqa: E402
import subprocess  # noqa: E402
import time  # noqa: E402

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import observe  # noqa: E402
import owners  # noqa: E402

SKILL = "herdr-parallel-worktree"
WORKER_VAR = "HERDR_PW_WORKER"
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GUIDE = os.path.join(SKILL_DIR, "references", "dispatch.md")
READ_ONLY_AGENTS = ("Explore", "Plan", "claude-code-guide")   # searches and questions: never a tab


def owner_label(owner):
    if not owner:
        return "<worker name | main-checkout | none>"
    return owner[1] if owner[0] == "worker" else owner[0]


def handoff(owner, repo=None):
    """The block a subagent or worker ends with; the main session routes it by its `owner:` line."""
    return ("HERDR-HANDOFF\n"
            f"To the main session: load the {SKILL} skill and handle this by its `owner:` line (step 0, "
            "Receiving a handoff): pass it to that worker, ask the user about the main checkout, or start a new "
            "worker for `none`, without asking first. Do not tell the user to run it with `!` or to turn the "
            "hooks off.\n"
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


DENY_MAIN_BASH = (
    "Inside herdr, the user installed these hooks: you are the orchestrator, and a branch for a task or ticket, "
    "even a single one, becomes a herdr worker with its own worktree and its own claude in the sidebar. That is "
    f"their standing choice: do not ask whether to get around it. Load the {SKILL} skill and start the worker; it "
    "creates the worktree at the repository's conventional path and branch. Use the EnterWorktree tool only when "
    "the user asks for this session itself to move into a worktree: it creates `.claude/worktrees/<name>` on "
    "branch `worktree-<name>` (a `/` in the name becomes `+`), and the sidebar shows it. A detached checkout for "
    "reading (`--detach`, or a commit that is not a branch) is not blocked."
)
DENY_MAIN_AGENT = (
    "Inside herdr, the user installed these hooks so that an agent working in its own worktree runs as a herdr "
    "worker they can watch in the sidebar, not as a hidden subagent. That is their standing choice: do not ask "
    f"whether to bypass it. Load the {SKILL} skill and start the worker without asking first; tell the user what "
    "you started afterwards."
)


def deny_first_dispatch(draft):
    return ("Inside herdr, the user installed these hooks so that a task handed to another agent runs as a herdr "
            "tab they can watch, not as a hidden subagent. Nothing is lost: this dispatch (description, model and "
            f"prompt) is saved at {draft}. Read {GUIDE} and start the tab with that file as the brief's "
            "instructions, then carry on with the user's request from where you were. Do not ask the user first, "
            "and do not suggest turning the hooks off. This happens once per session: a search or a question you "
            "meant for a subagent can be sent again unchanged.")


def deny_sub(owner, repo=None):
    return ("You are a subagent. Inside herdr, work outside your own worktree goes back to the main session, which "
            "hands it to the worktree's owner or starts a herdr worker. "
            f"Do not create a worktree or write into {where(owner)}, and do not retry another way. Do not suggest "
            "running anything with `!` or turning the hooks off. Stop now and end your final reply with this "
            "block, filled in:\n\n" + handoff(owner, repo))


DENY_SUB = deny_sub(NEW)
ROLE_MAIN = (
    "You are the orchestrator of this herdr session. Every task you hand to another agent, even a single ticket, "
    "runs as a herdr worker: its own worktree and its own claude in the user's sidebar, where the user can watch it "
    f"and step in. You start, follow and clean up those workers with the {SKILL} skill. Implementation subagents "
    "belong inside the workers, not here: when another skill tells you to dispatch a subagent for a ticket or task, "
    "that dispatch is a worker (see the skill's references/dispatch.md), and that skill's rules go into the worker's brief."
)


def role_worker(name):
    return (f"You are herdr worker `{name}`. Your brief says where you work and what you may touch outside it. "
            "Do not start workers or create worktrees: herdr runs you in a tab, and nested workers break it. "
            "Do not write where another session works (another worker's worktree, the main checkout, or a "
            "repository your brief does not list); anything needed there goes back to the orchestrator in your "
            "`## Result`, as a HERDR-HANDOFF block when it is code work. Never send anything to the orchestrator's "
            "pane: it is the user's conversation. A step your brief tells you to take, such as sending a re-review "
            "request to another tab, is yours to take. If your brief asks for something this rules out, say so in "
            "your `## Result` instead of doing it.")


def note_entered(label):
    return (f"herdr shows this worktree in the sidebar as workspace `{label}`. You keep working in this session; "
            "a claude that a herdr plugin started in that workspace is a separate, idle session.")


DISPATCH_SKILLS = ("superpowers:subagent-driven-development", "superpowers:dispatching-parallel-agents")


def note_dispatch_skill(skill):
    return (f"Inside herdr, {skill} hands each task to an agent; here each of those agents runs as a herdr tab the "
            f"user can watch. Before the first dispatch, read {GUIDE}.")


def slash_skill(prompt):
    """The skill name in a prompt that starts (after spaces) with `/name`, else None."""
    text = prompt.lstrip() if isinstance(prompt, str) else ""
    if not text.startswith("/"):
        return None
    return text.split(None, 1)[0][1:] or None


def dispatch_skills(cfg):
    """The skills that dispatch tasks: `dispatchSkills` from the config when it is a list of strings, else the default."""
    names = cfg.get("dispatchSkills") if isinstance(cfg, dict) else None
    if isinstance(names, list) and all(isinstance(n, str) for n in names):
        return tuple(names)
    return DISPATCH_SKILLS


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


def deny_not_your_worktree(name, home, owner):
    return (f"You are herdr tab `{name}`, working in `{home}`, which belongs to `{owner}`. Only `{owner}` writes "
            "here, so two tabs never edit the same files. Do not change files here, and do not retry another way; "
            "put what should change in your `## Result` or your verdict file instead.")


def deny_undeclared(name, top):
    return (f"You are herdr tab `{name}`. `{top}` is another repository, and your brief does not list this path "
            "under outside paths; another session may be working there. Do not write it, and do not retry another "
            "way. Finish the rest of your task, and say in your `## Result` which path you needed and why, so the "
            "orchestrator can add it to your brief.")


def briefs_dir(env):
    return os.path.join(os.path.dirname(owners.runs_path(env)), "briefs")


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


CONTROL = re.compile(r"^[;&|()]+$")
GIT_VALUE_OPTS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace", "--config-env"}


def worktree_adds(command):
    """(the -C directory or None, the arguments after `worktree add`) for each `git … worktree add` in command
    position, or None when the command cannot be split (unbalanced quotes). Heredoc bodies are dropped and
    redirections skipped, so `2>&1` is not read as an argument."""
    found = []
    for line in HEREDOC.sub("<<HEREDOC", command).replace("\\\n", " ").split("\n"):
        try:
            lex = shlex.shlex(line, posix=True, punctuation_chars=";&|()<>")
            lex.whitespace_split = True
            toks = list(lex) + [";"]
        except ValueError:
            return None
        seg, skip = [], False
        for t in toks:
            if skip:
                skip = False
            elif CONTROL.match(t):
                add = parse_add(seg)
                if add:
                    found.append(add)
                seg = []
            elif "<" in t or ">" in t:   # a redirection: drop its file descriptor and its target
                if seg and seg[-1].isdigit():
                    seg.pop()
                skip = True
            else:
                seg.append(t)
    return found


def parse_add(seg):
    i = 0
    while i < len(seg) and re.match(r"^\w+=", seg[i]):   # VAR=value prefixes
        i += 1
    if i < len(seg) and seg[i] == "command":
        i += 1
    if i >= len(seg) or os.path.basename(seg[i]) != "git":
        return None
    i, cdir = i + 1, None
    while i < len(seg) and seg[i].startswith("-"):
        if seg[i] in GIT_VALUE_OPTS and i + 1 < len(seg):
            if seg[i] == "-C":
                cdir = os.path.join(cdir, seg[i + 1]) if cdir else seg[i + 1]
            i += 2
        else:
            i += 1
    return (cdir, seg[i + 2:]) if seg[i:i + 2] == ["worktree", "add"] else None


def makes_branch(args, repo, refs):
    """Whether `git worktree add <args>` checks out or creates a branch, rather than a detached HEAD."""
    if any(a in ("-b", "-B", "--orphan") or a.startswith("--orphan=") for a in args):
        return True
    if "--detach" in args or "-d" in args:
        return False
    pos, skip = [], False
    for a in args:
        if skip:
            skip = False
        elif a == "--reason":
            skip = True
        elif not a.startswith("-"):
            pos.append(a)
    if len(pos) < 2:
        return True                                    # no commit-ish: git names a new branch after the path
    if "$" in pos[1] or "`" in pos[1]:
        return True                                    # known only when the shell runs it
    return refs(repo, pos[1])


def branch_ref(repo, name):
    """Whether `name` makes `git worktree add` check out a branch in `repo`: a local branch, or a branch in exactly
    one remote (git then creates the local branch). Unknown (git failed) counts as a branch."""
    if owners.git(["-C", repo, "rev-parse", "--verify", "-q", f"refs/heads/{name}"]) is not None:
        return True
    remote = owners.git(["-C", repo, "for-each-ref", "--format=%(refname)", f"refs/remotes/*/{name}"])
    return remote is None or len(remote.split()) == 1


def main_bash_makes_branch(command, cwd, refs):
    adds = worktree_adds(command)
    if not adds:
        return True                                    # matched as a command but not understood: as before
    return any(makes_branch(args, os.path.normpath(os.path.join(cwd, os.path.expanduser(cdir))) if cdir else cwd,
                            refs) for cdir, args in adds)


def run_herdr(args):
    """The JSON herdr prints for `herdr <args>`, or None."""
    try:
        r = subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=5)
        return json.loads(r.stdout) if r.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def register(event, env, probe, runs, main_of, herdr):
    """R8: show the worktree Claude Code just made (EnterWorktree) in the herdr sidebar, and close its workspace
    once ExitWorktree has removed it. Claude Code's own worktree handling is left exactly as it is. Returns the
    sidebar label of a workspace it opened, else None."""
    resp = event.get("tool_response")
    path = resp.get("worktreePath") if isinstance(resp, dict) else None
    if not isinstance(path, str) or not path:
        return
    if event.get("tool_name") == "EnterWorktree":
        found = probe(path)
        if not found:
            return
        loc, ws = None, env.get("HERDR_WORKSPACE_ID")
        if ws:   # the session's workspace belongs to this repository: attach there (skill step 1)
            info = (herdr(["workspace", "get", ws]) or {}).get("result") or {}
            key = ((info.get("workspace") or {}).get("worktree") or {}).get("repo_key")
            if isinstance(key, str) and os.path.realpath(key) == os.path.realpath(found[1]):
                loc = ["--workspace", ws]
        if loc is None:
            main = main_of(path)
            if not main:
                return
            loc = ["--cwd", main]
        label = os.path.basename(path.rstrip(os.sep))
        opened = herdr(["worktree", "open", *loc, "--path", path, "--label", label, "--no-focus"])
        return label if opened else None
    if resp.get("action") != "remove" or os.path.exists(path):
        return                                         # kept, or still on disk: the workspace still shows it
    rp = os.path.realpath(path)
    if runs is None:
        runs = owners.read_open_runs(owners.runs_path(env))
    if any(os.path.realpath(r.get("worktree") or "") == rp for r in runs):
        return                                         # a worker's workspace is the skill's to clean up
    for w in ((herdr(["workspace", "list"]) or {}).get("result") or {}).get("workspaces") or []:
        cp = (w.get("worktree") or {}).get("checkout_path")
        if isinstance(cp, str) and os.path.realpath(cp) == rp and w.get("workspace_id"):
            herdr(["workspace", "close", w["workspace_id"]])


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


class DispatchStore:
    """Sessions whose first task dispatch was already stopped: one file per session. Never raises."""

    def __init__(self, path):
        self.path = path

    def _file(self, session_id):
        return os.path.join(self.path, re.sub(r"[^0-9A-Za-z_-]", "_", session_id))

    def seen(self, session_id):
        try:
            return os.path.exists(self._file(session_id))
        except Exception:
            return False

    def mark(self, session_id):
        try:
            os.makedirs(self.path, exist_ok=True)
            with open(self._file(session_id), "w"):
                pass
        except Exception:
            pass


def real_dispatch_store():
    import tempfile
    return DispatchStore(os.path.join(tempfile.gettempdir(), "herdr-pw-dispatch"))


def save_draft(env, session_id, tool_input, now=time.time):
    """Write a dispatch (description, model, prompt) to DATA_DIR/briefs and return the path; None on any failure."""
    try:
        base = env.get("HERDR_SKILLS_DATA_HOME") or os.path.expanduser("~/.local/share/herdr-skills")
        briefs = os.path.join(base, SKILL, "briefs")
        os.makedirs(briefs, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(now()))
        short = re.sub(r"[^0-9A-Za-z_-]", "_", session_id)[:8] or "-"
        path = os.path.join(briefs, f"dispatch-{short}-{stamp}.md")
        text = ("# Dispatch draft\n\n"
                f"- subagent_type: {tool_input.get('subagent_type') or '-'}\n"
                f"- model: {tool_input.get('model') or '-'}\n"
                f"- description: {tool_input.get('description') or '-'}\n\n"
                f"## Prompt\n{tool_input.get('prompt') or ''}\n")
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path
    except Exception:
        return None


def creates_worktree(tool, args):
    return bool((tool == "Bash" and WORKTREE_ADD.search(code_only(args.get("command") or "")))
                or (tool == "EnterWorktree" and not args.get("path"))
                or (tool in ("Agent", "Task") and args.get("isolation") == "worktree"))   # Task: Agent's older name


def write_target(event, env, probe, runs, main_of, declared=None):
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
    if env.get(WORKER_VAR) and owners.inside(rp, home_top):
        mine = owners.run_owning(home_top, runs)
        if mine and mine["name"] != env[WORKER_VAR]:
            return deny(deny_not_your_worktree(env[WORKER_VAR], home_top, mine["name"]))
    inner = owners.run_owning(rp, runs)
    if owners.inside(rp, home_top) and not observe.nested_root(rp, home_top) \
            and not (inner and inner["worktree"] != home_top and owners.inside(inner["worktree"], home_top)):
        return None                              # home itself, not a worktree nested inside it: no git call
    own = owners.owner_of(path, runs, probe, writer_common, writer_main)
    if own is None and env.get(WORKER_VAR):
        other = probe(path)                      # another repository: only the paths the brief lists
        if other:
            names = declared or (lambda n: owners.declared_outside(briefs_dir(env), n))
            if not any(owners.inside(rp, d) for d in names(env[WORKER_VAR])):
                return deny(deny_undeclared(env[WORKER_VAR], os.path.realpath(other[2])))
        return None
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


def decide(event, env, probe=git_probe, runs=None, main_of=owners.main_checkout_of, deps=None, herdr=None,
           refs=None, store=None, save=None, cfg=None, declared=None):
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
        if tool == "Skill" and who == "main":
            skill = args.get("skill")
            if isinstance(skill, str) and skill in dispatch_skills(read_config(env) if cfg is None else cfg):
                return {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                               "additionalContext": note_dispatch_skill(skill)}}
            return None
        if tool in ("EnterWorktree", "ExitWorktree") and who == "main":
            label = register(event, env, probe, runs, main_of, herdr or run_herdr)
            if label:
                return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": note_entered(label)}}
        return None
    if hook == "UserPromptSubmit":
        if who != "main":
            return None
        skill = slash_skill(event.get("prompt"))
        if skill and skill in dispatch_skills(read_config(env) if cfg is None else cfg):
            return {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                           "additionalContext": note_dispatch_skill(skill)}}
        return None
    if hook == "SessionStart":
        if who not in ("main", "worker"):
            return None                          # a subagent's own start, should one ever reach here
        if who == "main":
            home = probe(cwd)
            if home and home[0] != home[1]:
                return None                      # a plain claude in a linked worktree, e.g. one a plugin started
        text = role_worker(env[WORKER_VAR]) if who == "worker" else ROLE_MAIN
        return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": text}}
    if hook != "PreToolUse":
        return None
    if creates_worktree(tool, args):
        if who == "main":
            if tool == "EnterWorktree":
                return None                      # Claude Code makes it as usual; PostToolUse shows it in herdr
            if tool == "Bash":
                command = args.get("command") or ""
                return deny(DENY_MAIN_BASH) if main_bash_makes_branch(command, cwd, refs or branch_ref) else None
            return deny(DENY_MAIN_AGENT)
        if who == "worker":
            return deny(deny_worker_create(env[WORKER_VAR], home_of(cwd, probe)))
        return deny(DENY_SUB)
    if tool in ("Agent", "Task") and who == "main" and args.get("subagent_type") not in READ_ONLY_AGENTS:
        home = probe(cwd)
        sid = event.get("session_id")
        if home and home[0] == home[1] and isinstance(sid, str) and sid:
            store = store or real_dispatch_store()
            if not store.seen(sid):
                draft = (save or save_draft)(env, sid, args)
                if draft:
                    store.mark(sid)
                    return deny(deny_first_dispatch(draft))
        return None
    if tool in WRITE_TOOLS:
        return write_target(event, env, probe, runs, main_of, declared)
    return None


def read_config(env):
    """DATA_DIR/config.json as a dict; {} when it is missing, unreadable or not an object."""
    base = env.get("HERDR_SKILLS_DATA_HOME") or os.path.expanduser("~/.local/share/herdr-skills")
    try:
        with open(os.path.join(base, SKILL, "config.json"), encoding="utf-8") as f:
            cfg = json.load(f)
    except (OSError, ValueError):
        return {}
    return cfg if isinstance(cfg, dict) else {}


def enabled():
    if os.environ.get("HERDR_ENV") != "1":
        return False
    return read_config(os.environ).get("hooks", "on") != "off"   # no or unreadable config: the default is on


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
