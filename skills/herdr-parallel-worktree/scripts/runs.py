#!/usr/bin/env python3
"""Registry of workers started by herdr-parallel-worktree: record, scan for cleanup, resume info.

The registry is DATA_DIR/runs.json (DATA_DIR = ${HERDR_SKILLS_DATA_HOME:-~/.local/share/herdr-skills}/herdr-parallel-worktree).
herdr does not know which worktrees this skill created, so cleanup only ever considers entries recorded here.

Usage:
  runs.py add --name N --root ROOT --branch B --base SHA --from-branch FB --worktree WT --workspace W --pane P [--brief PATH]
  runs.py scan --root ROOT [--fetch]      classify open runs of ROOT: candidates, keep, stale (JSON)
  runs.py mark-cleaned --root ROOT --name N [--session-id SID]
  runs.py mark-open --root ROOT --name N --workspace W --pane P
  runs.py show --root ROOT [--name N]     print runs (JSON), including resume commands for cleaned ones

All output is JSON on stdout; errors go to stderr with exit code 1.
"""
import argparse
import datetime
import json
import os
import subprocess
import sys
import tempfile


def data_dir():
    base = os.environ.get("HERDR_SKILLS_DATA_HOME") or os.path.expanduser("~/.local/share/herdr-skills")
    return os.path.join(base, "herdr-parallel-worktree")


def registry_path():
    return os.path.join(data_dir(), "runs.json")


def load():
    try:
        with open(registry_path(), encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    except (OSError, json.JSONDecodeError) as e:
        die(f"cannot read {registry_path()}: {e}")
    if not isinstance(data, list):
        die(f"{registry_path()} must contain a JSON array")
    return data


def save(runs):
    try:
        os.makedirs(data_dir(), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=data_dir(), prefix=".runs-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(runs, f, ensure_ascii=False, indent=2)
            f.write("\n")
        os.replace(tmp, registry_path())
    except OSError as e:
        die(f"cannot write {registry_path()}: {e.strerror}")


def die(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


def now():
    return datetime.datetime.now(datetime.timezone.utc).astimezone().isoformat(timespec="seconds")


def run(cmd, cwd=None):
    """Run a command; return (returncode, stdout). Never raises for a non-zero exit."""
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as e:
        return 1, str(e)
    return p.returncode, p.stdout.strip()


def herdr_call(*args):
    """Return (result, error_code). error_code is None on success, herdr's code on a herdr error,
    or "herdr_unavailable" when herdr could not be run or its output was not JSON."""
    try:
        p = subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None, "herdr_unavailable"
    rc = p.returncode
    out = p.stdout.strip() or p.stderr.strip()   # herdr writes error JSON to stderr
    try:
        data = json.loads(out) if out else {}
    except json.JSONDecodeError:
        return None, "herdr_unavailable"
    if "error" in data:
        return None, (data["error"] or {}).get("code") or "herdr_error"
    if rc != 0 or "result" not in data:
        return None, "herdr_unavailable"
    return data["result"], None


def herdr_json(*args):
    return herdr_call(*args)[0]


def git(root, *args):
    return run(["git", "-C", root, *args])


def norm_root(root):
    rc, out = git(root, "rev-parse", "--show-toplevel")
    if rc != 0:
        die(f"not a git repository: {root}")
    return out


def find(runs, root, name, state=None):
    hits = [r for r in runs if r["root"] == root and r["name"] == name and (state is None or r["state"] == state)]
    return hits[-1] if hits else None


def session_file(worktree, session_id):
    """Claude Code stores sessions per working directory: ~/.claude/projects/<path with / and . as ->/<id>.jsonl"""
    key = worktree.replace("/", "-").replace(".", "-")
    return os.path.expanduser(f"~/.claude/projects/{key}/{session_id}.jsonl")


def current_session(pane):
    info = herdr_json("pane", "get", pane)
    if not info:
        return None
    return ((info.get("pane") or {}).get("agent_session") or {}).get("value")


def resume_commands(r):
    return {
        "ask": f'resume {r["name"]}',
        "manual": [
            f'herdr worktree create --cwd {r["root"]} --branch {r["branch"]} --path {r["worktree"]} --label {r["name"]}',
            f'claude --resume {r["session_id"]}   # run in the new workspace pane' if r.get("session_id")
            else "claude --continue   # no session id was recorded; resumes the latest session in that directory",
        ],
    }


def cmd_add(a):
    runs = load()
    root = norm_root(a.root)
    if find(runs, root, a.name, "open"):
        die(f"an open run named {a.name} already exists for {root}")
    runs.append({
        "name": a.name, "root": root, "branch": a.branch, "base": a.base, "from_branch": a.from_branch,
        "worktree": a.worktree, "workspace": a.workspace, "pane": a.pane, "brief": a.brief,
        "session_id": current_session(a.pane), "state": "open", "created_at": now(), "cleaned_at": None,
    })
    save(runs)
    print(json.dumps(runs[-1], ensure_ascii=False))


def classify(r, fetch):
    """Return (kind, reasons, facts); kind is "candidate", "keep" or "stale"."""
    keep, facts = [], {}
    ws, err = herdr_call("workspace", "get", r["workspace"])
    if err and err != "workspace_not_found":
        # Only an explicit "not found" means the user closed it. Any other failure must not be read as
        # "closed": that would skip the worker-status check and remove a worktree under a live worker.
        return "keep", [f"could not query herdr ({err})"], facts
    wsinfo = (ws or {}).get("workspace") or {}
    facts["workspace_open"] = bool(wsinfo)
    facts["agent_status"] = wsinfo.get("agent_status")
    facts["focused"] = wsinfo.get("focused", False)
    if wsinfo:
        sid = current_session(r["pane"])
        if sid:
            facts["session_id"] = sid
    if facts["agent_status"] in ("working", "blocked"):
        keep.append(f"worker is {facts['agent_status']}")
    if facts["focused"]:
        keep.append("user is viewing this workspace")

    wt, branch, root = r["worktree"], r["branch"], r["root"]
    if not os.path.isdir(wt):
        # removed outside this skill: nothing left to delete, only the record to update
        facts["why"] = "worktree already removed"
        facts["remove_command"] = None
        return "stale", [], facts
    # The user may have closed the workspace by hand; the worktree then has no workspace to remove it with.
    facts["remove_command"] = (f'herdr worktree remove --workspace {r["workspace"]}' if wsinfo
                               else f'git -C {root} worktree remove {wt}')
    rc, dirty = git(wt, "status", "--porcelain", "--untracked-files=all")
    if rc != 0:
        keep.append("git status failed in worktree")
    elif dirty:
        keep.append(f"uncommitted changes ({len(dirty.splitlines())} paths)")

    rc, ahead = git(root, "rev-list", "--count", f'{r["base"]}..{branch}')
    ahead = int(ahead) if rc == 0 and ahead.isdigit() else None
    facts["commits"] = ahead
    if fetch:
        git(root, "fetch", "--quiet", "--all", "--prune")
    merged_into = None
    for target in (r.get("from_branch"), f'origin/{r.get("from_branch")}'):
        if target and git(root, "rev-parse", "--verify", "--quiet", target)[0] == 0 \
                and git(root, "merge-base", "--is-ancestor", branch, target)[0] == 0:
            merged_into = target
            break
    pushed = False
    if git(root, "rev-parse", "--verify", "--quiet", f"origin/{branch}")[0] == 0:
        rc, unpushed = git(root, "rev-list", "--count", f"origin/{branch}..{branch}")
        pushed = rc == 0 and unpushed == "0"
    facts["merged_into"], facts["pushed"] = merged_into, pushed

    if ahead == 0:
        facts["why"] = "no commits"
    elif merged_into:
        facts["why"] = f"merged into {merged_into}"
    elif pushed:
        facts["why"] = "pushed, not merged"
    else:
        keep.append("commits not merged or pushed")
    return ("keep" if keep else "candidate"), keep, facts


def cmd_scan(a):
    runs = load()
    root = norm_root(a.root)
    out = {"candidates": [], "keep": [], "stale": [], "untracked_worktrees": []}
    tracked = set()
    for r in runs:
        if r["root"] != root or r["state"] != "open":
            continue
        tracked.add(r["worktree"])
        kind, reasons, facts = classify(r, a.fetch)
        entry = {"name": r["name"], "branch": r["branch"], "worktree": r["worktree"],
                 "workspace": r["workspace"], **facts, "session_id": facts.get("session_id") or r.get("session_id")}
        if kind == "keep":
            out["keep"].append({**entry, "reasons": reasons})
        else:
            out["candidates" if kind == "candidate" else "stale"].append(entry)
    wl = herdr_json("worktree", "list", "--cwd", root) or {}
    for w in wl.get("worktrees", []):
        if w.get("is_linked_worktree") and w.get("path") not in tracked:
            out["untracked_worktrees"].append({"path": w.get("path"), "branch": w.get("branch"),
                                               "workspace": w.get("open_workspace_id")})
    print(json.dumps(out, ensure_ascii=False, indent=2))


def cmd_mark_cleaned(a):
    runs = load()
    r = find(runs, norm_root(a.root), a.name, "open")
    if not r:
        die(f"no open run named {a.name}")
    if a.session_id:
        r["session_id"] = a.session_id
    r["state"], r["cleaned_at"] = "cleaned", now()
    save(runs)
    print(json.dumps({**r, "session_file_exists": bool(r.get("session_id")) and os.path.exists(
        session_file(r["worktree"], r["session_id"])), "resume": resume_commands(r)}, ensure_ascii=False, indent=2))


def cmd_mark_open(a):
    runs = load()
    r = find(runs, norm_root(a.root), a.name, "cleaned")
    if not r:
        die(f"no cleaned run named {a.name}")
    r.update(state="open", workspace=a.workspace, pane=a.pane, cleaned_at=None)
    save(runs)
    print(json.dumps(r, ensure_ascii=False))


def cmd_show(a):
    root = norm_root(a.root)
    runs = [r for r in load() if r["root"] == root and (a.name is None or r["name"] == a.name)]
    for r in runs:
        if r["state"] == "cleaned":
            r["resume"] = resume_commands(r)
            r["session_file_exists"] = bool(r.get("session_id")) and os.path.exists(
                session_file(r["worktree"], r["session_id"]))
    print(json.dumps(runs, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add")
    for k in ("name", "root", "branch", "base", "from-branch", "worktree", "workspace", "pane"):
        s.add_argument(f"--{k}", required=True)
    s.add_argument("--brief")
    s = sub.add_parser("scan"); s.add_argument("--root", required=True); s.add_argument("--fetch", action="store_true")
    s = sub.add_parser("mark-cleaned"); s.add_argument("--root", required=True); s.add_argument("--name", required=True)
    s.add_argument("--session-id")
    s = sub.add_parser("mark-open"); s.add_argument("--root", required=True); s.add_argument("--name", required=True)
    s.add_argument("--workspace", required=True); s.add_argument("--pane", required=True)
    s = sub.add_parser("show"); s.add_argument("--root", required=True); s.add_argument("--name")
    a = p.parse_args()
    {"add": cmd_add, "scan": cmd_scan, "mark-cleaned": cmd_mark_cleaned,
     "mark-open": cmd_mark_open, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    main()
