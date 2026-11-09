#!/usr/bin/env python3
"""Place a worker under its repository's herdr space, or as a tab in this session's space.

Usage:
  place.py where --dir DIR
  place.py worktree --root ROOT --name N --branch B (--base SHA | --existing) [--path P] [--trust-repository]
  place.py reopen --root ROOT --name N --worktree WT

The rule (scripts/hooks/spaces.py, shared with the hooks): the worker goes under this session's space when that
space is bound to the repository, else under the space herdr knows for the repository, else it runs as a tab in
this session's space ($HERDR_WORKSPACE_ID). It never lets herdr make a new top-level space.

- where: only decide; for a worker without a worktree working in DIR (outside git: a tab here).
- worktree: decide and create the worktree. Placement "workspace": `herdr worktree create --workspace <space>`,
  which opens the worktree as a workspace under that space. Placement "tab": `git worktree add`, at --path or
  herdr's default path (~/.herdr/worktrees/<repo>/<branch, "/" as "-">); nothing is opened in herdr.
  --existing checks out an existing branch (resume) instead of creating one from --base.
- reopen: the worktree WT still exists but its workspace or tab is gone. Placement "workspace":
  `herdr worktree open --workspace <space>`; "tab": nothing to open.

Prints JSON: {"placement": "workspace"|"tab", "space": the space it belongs under, "why"} for where, plus
"workspace" (where the worker's tab goes: the worktree's workspace, or this session's space for a tab),
"worktree" and "since" (milliseconds, taken just before herdr or git acted; worker-pane.py --since) for worktree
and reopen. Nothing is overwritten: an occupied path, a failed git or herdr call, or herdr being unreachable
prints the reason on stderr and exits 1.
"""
import argparse
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "hooks"))
import spaces  # noqa: E402


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def herdr(args):
    """herdr's parsed JSON (a result or an error object), or None when herdr could not be run or answered no JSON."""
    try:
        p = subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    out = p.stdout.strip() or p.stderr.strip()   # herdr writes error JSON to stderr
    try:
        data = json.loads(out) if out else None
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def herdr_or_die(args):
    data = herdr(args)
    result = (data or {}).get("result")
    if not isinstance(result, dict):
        err = (data or {}).get("error") or {}
        die(f"herdr {' '.join(args[:2])} failed: {err.get('code', 'no answer')} {err.get('message', '')}".rstrip())
    return result


def git(*args):
    p = subprocess.run(["git", *args], capture_output=True, text=True)
    return p.returncode, p.stdout.strip(), p.stderr.strip()


def toplevel(path):
    rc, out, _ = git("-C", path, "rev-parse", "--show-toplevel")
    return out if rc == 0 else None


def now_ms():
    return int(time.time() * 1000)


def current():
    ws = os.environ.get("HERDR_WORKSPACE_ID")
    if not ws:
        die("HERDR_WORKSPACE_ID is not set: this is not a session inside a herdr workspace")
    return ws


def decide(root, cur):
    """(placement, space, why) for a worktree of the repository at root."""
    space, why = spaces.repo_space(root, cur, herdr)
    if why == "herdr-error":
        die(f"herdr could not tell which space {root} belongs under (herdr worktree list / workspace get failed)")
    return ("workspace", space, why) if space else ("tab", cur, why)


def repo_name(root):
    listed = (herdr(["worktree", "list", "--cwd", root]) or {}).get("result") or {}
    name = (listed.get("source") or {}).get("repo_name")
    if isinstance(name, str) and name:
        return name
    rc, common, _ = git("-C", root, "rev-parse", "--path-format=absolute", "--git-common-dir")
    return os.path.basename(os.path.dirname(common)) if rc == 0 else os.path.basename(root)


def cmd_where(a):
    cur = current()
    root = toplevel(a.dir)
    if root is None:
        print(json.dumps({"placement": "tab", "space": cur, "why": "outside git"}))
        return
    placement, space, why = decide(root, cur)
    print(json.dumps({"placement": placement, "space": space, "why": why}))


def cmd_worktree(a):
    cur = current()
    root = toplevel(a.root) or die(f"not a git repository: {a.root}")
    path = os.path.normpath(os.path.join(root, os.path.expanduser(a.path))) if a.path else None
    placement, space, why = decide(root, cur)
    if placement == "workspace":
        args = ["worktree", "create", "--workspace", space, "--branch", a.branch]
        args += ["--base", a.base] if a.base else []
        args += ["--path", path] if path else []
        args += ["--label", a.name, "--no-focus"] + (["--trust-repository"] if a.trust_repository else [])
        since = now_ms()
        made = herdr_or_die(args)
        workspace = (made.get("workspace") or {}).get("workspace_id")
        path = (made.get("worktree") or {}).get("path") or path
        if not workspace or not path:
            die(f"herdr worktree create gave no workspace or path: {json.dumps(made)[:300]}")
    else:
        path = path or os.path.join(os.path.expanduser("~"), ".herdr", "worktrees", repo_name(root),
                                    a.branch.replace("/", "-"))
        if os.path.exists(path) and (not os.path.isdir(path) or os.listdir(path)):
            die(f"{path} already exists and is not empty: nothing was created")
        add = ["-b", a.branch, path, a.base] if a.base else [path, a.branch]
        since = now_ms()
        rc, _, err = git("-C", root, "worktree", "add", *add)
        if rc != 0:
            die(f"git worktree add failed: {err}")
        workspace = cur
    print(json.dumps({"placement": placement, "space": space, "workspace": workspace, "worktree": path,
                      "since": since, "why": why}))


def cmd_reopen(a):
    cur = current()
    root = toplevel(a.root) or die(f"not a git repository: {a.root}")
    if not os.path.isdir(a.worktree):
        die(f"{a.worktree} does not exist: recreate it instead (place.py worktree --existing)")
    placement, space, why = decide(root, cur)
    since = now_ms()
    workspace = cur
    if placement == "workspace":
        opened = herdr_or_die(["worktree", "open", "--workspace", space, "--path", a.worktree, "--label", a.name,
                               "--no-focus"])
        workspace = (opened.get("workspace") or {}).get("workspace_id") or die(
            f"herdr worktree open gave no workspace: {json.dumps(opened)[:300]}")
    print(json.dumps({"placement": placement, "space": space, "workspace": workspace, "worktree": a.worktree,
                      "since": since, "why": why}))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("where", help="decide where a worker without a worktree goes")
    s.add_argument("--dir", required=True, help="the directory the worker works in")
    s = sub.add_parser("worktree", help="decide where a worker goes and create its worktree")
    s.add_argument("--root", required=True)
    s.add_argument("--name", required=True, help="the worker's name: the workspace label")
    s.add_argument("--branch", required=True)
    how = s.add_mutually_exclusive_group(required=True)
    how.add_argument("--base", help="create the branch from this commit")
    how.add_argument("--existing", action="store_true", help="check out an existing branch (resume)")
    s.add_argument("--path", help="the worktree path from the repository's convention (relative: to ROOT)")
    s.add_argument("--trust-repository", action="store_true", help="passed to herdr; only after the user checked")
    s = sub.add_parser("reopen", help="give an existing worktree back its place")
    s.add_argument("--root", required=True)
    s.add_argument("--name", required=True)
    s.add_argument("--worktree", required=True)
    a = p.parse_args()
    {"where": cmd_where, "worktree": cmd_worktree, "reopen": cmd_reopen}[a.cmd](a)


if __name__ == "__main__":
    main()
