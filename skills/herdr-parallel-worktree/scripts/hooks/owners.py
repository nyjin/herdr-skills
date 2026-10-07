"""Who owns a path, for herdr-parallel-worktree's hooks.

A path belongs to one of:
  ("worker", name, worktree)    a worktree of an open run in DATA_DIR/runs.json (any repository)
  ("main-checkout", None, top)  the main checkout of the writer's own repository
  ("none", None, worktree)      a linked worktree of the writer's repository that no worker owns
  None                          anything else (outside git, other repositories): out of scope

Nothing here raises: an unreadable runs.json is an empty list, a failed git call is "unknown". The hooks
fail open on unknown.
"""
import json
import os
import subprocess

SKILL = "herdr-parallel-worktree"


def runs_path(env):
    base = env.get("HERDR_SKILLS_DATA_HOME") or os.path.expanduser("~/.local/share/herdr-skills")
    return os.path.join(base, SKILL, "runs.json")


def read_open_runs(path, realpath=os.path.realpath):
    """Open runs from runs.json with their worktree paths resolved. Never raises: anything unreadable is []."""
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    runs = []
    for r in data:
        if isinstance(r, dict) and r.get("state") == "open" \
                and isinstance(r.get("name"), str) and isinstance(r.get("worktree"), str):
            runs.append(dict(r, worktree=realpath(r["worktree"])))
    return runs


def inside(path, top):
    """True if `path` is `top` or below it, on a path-component boundary (/w/a does not contain /w/ab)."""
    top = top.rstrip(os.sep) or os.sep
    return path == top or path.startswith(top if top == os.sep else top + os.sep)


def git(args, timeout=2):
    """stdout of `git --no-optional-locks <args>`, or None on any failure."""
    try:
        r = subprocess.run(["git", "--no-optional-locks", *args], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if r.returncode == 0 else None


def parse_worktree_list_z(data):
    """Entries of `git worktree list --porcelain -z`: [{"path", "bare", "prunable"}], in git's order."""
    entries, cur = [], None
    for field in data.split("\0"):
        if not field:            # an empty field ends a record
            if cur:
                entries.append(cur)
            cur = None
            continue
        key, _, value = field.partition(" ")
        if key == "worktree":
            if cur:
                entries.append(cur)
            cur = {"path": value, "bare": False, "prunable": False}
        elif cur is not None and key in ("bare", "prunable"):
            cur[key] = True
    if cur:
        entries.append(cur)
    return entries


def nearest_dir(path):
    d = path
    while not os.path.isdir(d):
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    return d


def worktree_list(path, git=git, realpath=os.path.realpath):
    """Worktrees of the repository holding `path`, paths resolved; [] if unknown."""
    d = nearest_dir(path)
    out = git(["-C", d, "worktree", "list", "--porcelain", "-z"]) if d else None
    entries = parse_worktree_list_z(out or "")
    for e in entries:
        e["path"] = realpath(e["path"])
    return entries


def main_checkout_of(path, git=git, realpath=os.path.realpath):
    """The main checkout of the repository holding `path`; None for a bare repository or when unknown.

    From inside the main checkout, that checkout's toplevel. From a linked worktree, the first entry of
    `git worktree list`, but only after checking it really is a main checkout: for a --separate-git-dir
    repository git lists the git directory there instead."""
    d = nearest_dir(path)
    here = git(["-C", d, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir",
                "--show-toplevel"]) if d else None
    lines = (here or "").splitlines()
    if len(lines) == 3 and lines[0] == lines[1]:
        return realpath(lines[2])
    entries = worktree_list(path, git, realpath)
    if not entries or entries[0]["bare"]:
        return None
    cand = entries[0]["path"]
    check = (git(["-C", cand, "rev-parse", "--path-format=absolute", "--git-dir", "--git-common-dir",
                  "--show-toplevel"]) or "").splitlines() if os.path.isdir(cand) else []
    if len(check) == 3 and check[0] == check[1] and realpath(check[2]) == cand:
        return cand
    return None


def run_owning(path, runs):
    """The open run whose worktree holds `path` (the longest one when worktrees nest), or None."""
    best = None
    for r in runs:
        if inside(path, r["worktree"]) and (best is None or len(r["worktree"]) > len(best["worktree"])):
            best = r
    return best


def owner_of(path, runs, probe, writer_common, writer_main, realpath=os.path.realpath):
    """Owner of `path` (see module doc). runs.json is consulted before git, so a submodule inside a worker's
    worktree still belongs to that worker. `writer_common` / `writer_main` are the writer's repository
    (resolved git common dir, main checkout) and decide which unrecorded worktrees are in scope."""
    path = realpath(os.path.normpath(path))
    r = run_owning(path, runs)
    if r:
        return ("worker", r["name"], r["worktree"])
    found = probe(path)
    if not found:
        return None
    git_dir, common, top = found
    top, common = realpath(top), realpath(common)
    if git_dir != found[1]:                      # a linked worktree
        return ("none", None, top) if writer_common and common == writer_common else None
    if writer_main and top == writer_main:       # the writer's own main checkout
        return ("main-checkout", None, top)
    return None
