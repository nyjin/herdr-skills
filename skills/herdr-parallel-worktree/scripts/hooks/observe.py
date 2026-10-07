"""R7: what a subagent's or worker's Bash command actually changed outside its own worktree.

A Bash command is attributed a change in a worktree only when both hold:
  - the command mentions that worktree (a path in its text resolves inside it), and
  - something in that worktree changed while the command ran: a path from `git status`, the parent of a deleted
    path, a path the command named (or its nearest existing ancestor), or the worktree's logs/HEAD has a ctime
    inside the run's time window.
The index is not used: any plain `git status` in that worktree (a worker's status line, say) rewrites it, so it
would blame a subagent that only read there. A path the command named catches what leaves the status clean
again (`git restore f`, `git -C wt restore f` through the directory's ctime) without that noise.
The window comes from the hook's duration_ms, so no "before" snapshot is needed. ctime is used because
`cp -p`, `rsync -a` and `touch -t` can set mtime to the past, but nothing sets ctime.

Everything here is a pure function of its inputs (git, lstat and realpath are passed in) except BgStore, which
keeps background commands between hook runs. Nothing raises to the caller.
"""
import json
import math
import os
import re
import shlex
import time
from collections import namedtuple

import owners

# What observe() needs from the outside world; tests pass fakes.
Deps = namedtuple("Deps", "now lstat realpath git probe runs main_of bg")


# ---- time window -------------------------------------------------------------------------------------------

def window(now, duration_ms, pending_starts, margin=0.5):
    """(start, end) of the period a command ran in, widened to earlier background starts; None if unknown.
    The start is floored to a whole second so filesystems with 1-second timestamps are still covered."""
    if isinstance(duration_ms, bool) or not isinstance(duration_ms, (int, float)) \
            or math.isnan(duration_ms) or duration_ms < 0:
        return None
    start = min([now - duration_ms / 1000.0, *pending_starts]) - margin
    return (float(math.floor(start)), now)


# ---- what the command mentions ----------------------------------------------------------------------------

SPLIT = re.compile(r"[\s;&|()<>`]+")


def tokens(text):
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=";&|()<>")
        lex.whitespace_split = True
        return list(lex)
    except ValueError:                              # unbalanced quotes: a rougher split still finds paths
        return [t.strip("'\"") for t in SPLIT.split(text) if t]


def mentioned_paths(texts, cwd, home, realpath=os.path.realpath):
    """Resolved paths named in the command texts that lie outside `home`. A path is a token (or the value after
    `=` in `D=/x` or `--work-tree=/x`) that contains `/` or starts with `~`; relative ones resolve against cwd.
    Tokens with `$` are skipped: a variable's value is only known where it was assigned."""
    out = []
    for text in texts:
        for tok in tokens(text):
            for part in tok.split("="):
                if not part or "$" in part or not ("/" in part or part.startswith("~")):
                    continue
                p = realpath(os.path.normpath(os.path.join(cwd, os.path.expanduser(part))))
                if (home is None or not owners.inside(p, home)) and p not in out:
                    out.append(p)
    return out


def candidates(paths, runs, writer_wts, writer_main, home):
    """[(worktree, owner)] for the watched worktrees that hold a mentioned path, in first-mention order.
    Watched: open runs' worktrees, the writer repository's linked worktrees, and its main checkout when
    `writer_main` is given; never `home`. The innermost (longest) worktree holding a path wins."""
    watched = {}
    if writer_main:
        watched[writer_main] = ("main-checkout", None, writer_main)
    for wt in writer_wts:
        watched.setdefault(wt, ("none", None, wt))
    for r in runs:
        watched[r["worktree"]] = ("worker", r["name"], r["worktree"])
    watched.pop(home, None)
    out = []
    for p in paths:
        best = max((wt for wt in watched if owners.inside(p, wt)), key=len, default=None)
        if best and best not in [w for w, _ in out] and not owners.inside(best, home):
            out.append((best, watched[best]))
    return out


# ---- did it change -----------------------------------------------------------------------------------------

def parse_status_v2_z(data):
    """[(path, deleted)] from `git status --porcelain=v2 -z`. Renames carry their original path as the next
    NUL field, which is consumed; ignored (`!`) and header (`#`) records are skipped."""
    out, fields, i = [], data.split("\0"), 0
    while i < len(fields):
        rec, i = fields[i], i + 1
        if not rec:
            continue
        kind = rec[0]
        if kind == "1":
            parts = rec.split(" ", 8)
            if len(parts) == 9:
                out.append((parts[8], "D" in parts[1]))
        elif kind == "2":
            parts = rec.split(" ", 9)
            i += 1                                    # the original path
            if len(parts) == 10:
                out.append((parts[9], "D" in parts[1]))
        elif kind == "u":
            parts = rec.split(" ", 10)
            if len(parts) == 11:
                out.append((parts[10], False))
        elif kind == "?" and rec.startswith("? "):
            out.append((rec[2:], False))
    return out


def status_entries(wt, git):
    return parse_status_v2_z(git(["-C", wt, "status", "--porcelain=v2", "-z", "--untracked-files=all"]) or "")


def git_state_paths(wt, git):
    """Absolute path of the worktree's logs/HEAD: written on commits, checkouts and resets, never by status."""
    out = git(["-C", wt, "rev-parse", "--path-format=absolute", "--git-path", "logs/HEAD"])
    return [l for l in (out or "").splitlines() if l]


def ctime_in(path, lstat, win):
    try:
        c = lstat(path).st_ctime
    except OSError:
        return False
    return win[0] <= c <= win[1] + 1


def existing_ancestor(path, stop, lstat):
    d = os.path.dirname(path)
    while owners.inside(d, stop):
        try:
            lstat(d)
            return d
        except OSError:
            if d == stop:
                return None
            d = os.path.dirname(d)
    return None


def changed(wt, entries, lstat, win, exclude_dirs, git_paths, mentioned=()):
    """True if anything in worktree `wt` has a ctime inside `win`: a status entry (a deleted one through its
    nearest existing ancestor), a `mentioned` path inside `wt` (or its nearest existing ancestor), or one of
    `git_paths`. Paths inside `exclude_dirs` (home, nested worktrees) are skipped."""
    for p in mentioned:
        if not owners.inside(p, wt) or any(owners.inside(p, ex) for ex in exclude_dirs):
            continue
        if ctime_in(p, lstat, win):
            return True
        if not os.path.lexists(p):
            anc = existing_ancestor(p, wt, lstat)
            if anc and ctime_in(anc, lstat, win):
                return True
    for rel, deleted in entries:
        full = os.path.join(wt, rel)
        if any(owners.inside(full, ex) for ex in exclude_dirs):
            continue
        if not deleted and ctime_in(full, lstat, win):
            return True
        if deleted or not os.path.lexists(full):
            anc = existing_ancestor(full, wt, lstat)
            if anc and ctime_in(anc, lstat, win):
                return True
    return any(ctime_in(p, lstat, win) for p in git_paths)


# ---- background commands -----------------------------------------------------------------------------------

SAFE = re.compile(r"[^A-Za-z0-9_.-]")


class BgStore:
    """Background Bash commands an agent started, kept until that agent's next Bash hook. One file per command,
    created exclusively and claimed by rename, so parallel hooks of one agent neither lose nor double-take a
    record. Every failure is silent."""

    def __init__(self, root):
        self.root = root

    def dir_for(self, session, agent):
        return os.path.join(self.root, SAFE.sub("_", session or "-"), SAFE.sub("_", agent or "self"))

    def add(self, session, agent, task_id, start, command):
        try:
            d = self.dir_for(session, agent)
            os.makedirs(d, exist_ok=True)
            fd = os.open(os.path.join(d, SAFE.sub("_", task_id or str(time.time())) + ".json"),
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w") as f:
                json.dump({"start": start, "command": command}, f)
        except Exception:
            pass

    def take(self, session, agent):
        out = []
        try:
            d = self.dir_for(session, agent)
            names = [n for n in os.listdir(d) if n.endswith(".json")]
        except Exception:
            return out
        for n in names:
            src = os.path.join(d, n)
            claimed = f"{src}.taken.{os.getpid()}.{id(out)}"
            try:
                os.rename(src, claimed)
            except OSError:
                continue                              # another hook took it
            try:
                with open(claimed) as f:
                    rec = json.load(f)
                if isinstance(rec, dict) and isinstance(rec.get("start"), (int, float)) \
                        and isinstance(rec.get("command"), str):
                    out.append({"start": rec["start"], "command": rec["command"]})
            except Exception:
                pass
            finally:
                try:
                    os.unlink(claimed)
                except OSError:
                    pass
        return out

    def gc(self, now, max_age=3600):
        try:
            for dirpath, dirnames, filenames in os.walk(self.root, topdown=False):
                for n in filenames:
                    p = os.path.join(dirpath, n)
                    try:
                        if os.lstat(p).st_mtime < now - max_age:
                            os.unlink(p)
                    except OSError:
                        pass
                if dirpath != self.root:
                    try:
                        os.rmdir(dirpath)             # only succeeds when empty
                    except OSError:
                        pass
        except Exception:
            pass


# ---- the whole judgement -----------------------------------------------------------------------------------

def observe(event, env, deps):
    """[(worktree, owner)] that this subagent's or worker's finished Bash command changed outside its own
    worktree; [] when nothing is attributed. A background launch is recorded and judged at the agent's next
    Bash hook."""
    if not (event.get("agent_id") or env.get("HERDR_PW_WORKER")):
        return []
    worker_side = bool(env.get("HERDR_PW_WORKER"))
    args = event.get("tool_input") or {}
    command = args.get("command") if isinstance(args.get("command"), str) else ""
    session, agent = str(event.get("session_id") or "-"), str(event.get("agent_id") or "self")
    now = deps.now()
    deps.bg.gc(now)
    resp = event.get("tool_response")
    if isinstance(resp, dict) and resp.get("backgroundTaskId"):
        deps.bg.add(session, agent, str(resp["backgroundTaskId"]), now, command)
        return []
    pending = deps.bg.take(session, agent)
    cwd = event.get("cwd") or ""
    texts = [command] + [p["command"] for p in pending]
    if not cwd or not mentioned_paths(texts, cwd, None, deps.realpath):
        return []                                     # most commands name no path: stop before any git call
    home = deps.probe(cwd)
    if not home:
        return []
    home_top = deps.realpath(home[2])
    paths = mentioned_paths(texts, cwd, home_top, deps.realpath)
    if not paths:
        return []
    win = window(now, event.get("duration_ms"), [p["start"] for p in pending])
    if not win:
        return []
    writer_main = home_top if home[0] == home[1] else deps.main_of(cwd)
    linked = [e["path"] for e in owners.worktree_list(cwd, deps.git, deps.realpath)
              if not e["bare"] and e["path"] != writer_main]
    runs = deps.runs()
    cands = candidates(paths, runs, linked, writer_main if worker_side else None, home_top)
    if not cands:
        return []
    watched = set(linked) | {r["worktree"] for r in runs} | ({writer_main} if writer_main else set())

    def check(item):
        wt, own = item
        exclude = [home_top] + [x for x in watched if x != wt and owners.inside(x, wt)]
        here = [p for p in paths if owners.inside(p, wt)]
        return changed(wt, status_entries(wt, deps.git), deps.lstat, win, exclude,
                       git_state_paths(wt, deps.git), here)

    from concurrent.futures import ThreadPoolExecutor   # only needed once there is something to check
    with ThreadPoolExecutor(max_workers=min(8, len(cands))) as pool:
        flags = list(pool.map(check, cands))
    return [c for c, hit in zip(cands, flags) if hit]
