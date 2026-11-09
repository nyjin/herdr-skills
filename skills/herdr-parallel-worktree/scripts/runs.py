#!/usr/bin/env python3
"""Registry of workers started by herdr-parallel-worktree: record, scan for cleanup, resume clues.

The registry is DATA_DIR/runs.json (DATA_DIR = ${HERDR_SKILLS_DATA_HOME:-~/.local/share/herdr-skills}/herdr-parallel-worktree).
herdr does not know which worktrees this skill created, so cleanup only ever considers entries recorded here.

Usage:
  runs.py add --name N --root ROOT --branch B --base SHA --from-branch FB --worktree WT --workspace W --pane P
              --placement workspace|tab [--brief PATH]
  runs.py scan --root ROOT [--fetch]      classify open runs of ROOT: candidates, keep, stale (JSON)
  runs.py mark-cleaned --root ROOT --name N [--session-id SID]
  runs.py mark-open --root ROOT --name N --workspace W --pane P [--placement workspace|tab]
  runs.py relocate --root ROOT --name N --workspace W --pane P [--placement workspace|tab]
                                          an open run reopened in a new place
  runs.py show --root ROOT [--name N]     print runs (JSON)

`placement` is what scripts/place.py decided: "workspace" (the worktree has a workspace of its own, recorded as
`workspace`) or "tab" (the worker is a tab in `workspace`, the space it runs in; herdr did not open the worktree).
A record without it was written before 0.9.0 and is a "workspace" run. A tab worker is judged and cleaned up by
its tab, never by the space it runs in, which is not this skill's to close; a dispatch plan's `<plan>-impl` tab
brings its unrecorded `<plan>-rev` tab in the same worktree along (references/dispatch.md).

It records clues, not procedures: which agent herdr saw in the pane and the session reference herdr's
integration reported (the same data herdr uses to resume agents after a server restart), plus the worktree
path and branch. How to resume a given agent is left to the orchestrator to work out at resume time.

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


def current_session(pane):
    """Return herdr's agent_session for the pane ({agent, kind, source, value}) or None."""
    info = herdr_json("pane", "get", pane)
    if not info:
        return None
    return (info.get("pane") or {}).get("agent_session") or None


def session_fields(sess):
    sess = sess or {}
    return {"agent": sess.get("agent"), "session_id": sess.get("value"), "session_source": sess.get("source")}


def cmd_add(a):
    runs = load()
    root = norm_root(a.root)
    if find(runs, root, a.name, "open"):
        die(f"an open run named {a.name} already exists for {root}")
    runs.append({
        "name": a.name, "root": root, "branch": a.branch, "base": a.base, "from_branch": a.from_branch,
        "worktree": a.worktree, "workspace": a.workspace, "pane": a.pane, "placement": a.placement,
        "brief": a.brief, **session_fields(current_session(a.pane)), "state": "open", "created_at": now(),
        "cleaned_at": None,
    })
    save(runs)
    print(json.dumps(runs[-1], ensure_ascii=False))


PLACEMENTS = ("workspace", "tab")


def placement(r):
    return r.get("placement") or "workspace"


def inside(path, top):
    return path == top or path.startswith(top.rstrip(os.sep) + os.sep)


def companion_tabs(r):
    """([tab ids], error): a dispatch plan's reviewer tab `<plan>-rev` beside its recorded implementer `<plan>-impl`
    (references/dispatch.md), in the same space, with a pane working in the same worktree. A workspace placement
    closes it with the workspace; a tab placement must judge and close it itself. Any other tab is left alone."""
    if not r["name"].endswith("-impl"):
        return [], None
    want = r["name"][:-len("-impl")] + "-rev"
    tabs, err = herdr_call("tab", "list", "--workspace", r["workspace"])
    if err:
        return None, err
    panes, err = herdr_call("pane", "list", "--workspace", r["workspace"])
    if err:
        return None, err
    ids = {t.get("tab_id") for t in (tabs or {}).get("tabs") or [] if t.get("label") == want}
    wt = os.path.realpath(r["worktree"])
    return sorted({p["tab_id"] for p in (panes or {}).get("panes") or []
                   if p.get("tab_id") in ids and inside(os.path.realpath(p.get("cwd") or "/"), wt)}), None


def tab_facts(r):
    """(facts, error) for a tab worker, read from its pane and tab only: the space it runs in is someone else's."""
    pane, err = herdr_call("pane", "get", r["pane"])
    if err and err != "pane_not_found":
        return None, err
    info = (pane or {}).get("pane") or {}
    tab = {}
    if info.get("tab_id"):
        t, err = herdr_call("tab", "get", info["tab_id"])
        if err and err != "tab_not_found":
            return None, err
        tab = (t or {}).get("tab") or {}
    facts = {"tab": info.get("tab_id") if tab else None, "tab_open": bool(tab),
             "agent_status": tab.get("agent_status"), "focused": tab.get("focused", False)}
    sess = info.get("agent_session")
    if tab and sess and sess.get("value"):
        facts.update(session_fields(sess))
    ids, err = companion_tabs(r)
    if err:
        return None, err
    facts["companions"] = []
    for tid in ids:
        t, err = herdr_call("tab", "get", tid)
        if err and err != "tab_not_found":
            return None, err
        t = (t or {}).get("tab") or {}
        if t:
            facts["companions"].append({"tab": tid, "label": t.get("label"), "agent_status": t.get("agent_status"),
                                        "focused": t.get("focused", False)})
    return facts, None


def workspace_facts(r):
    ws, err = herdr_call("workspace", "get", r["workspace"])
    if err and err != "workspace_not_found":
        return None, err
    wsinfo = (ws or {}).get("workspace") or {}
    facts = {"workspace_open": bool(wsinfo), "agent_status": wsinfo.get("agent_status"),
             "focused": wsinfo.get("focused", False)}
    if wsinfo:
        sess = current_session(r["pane"])
        if sess and sess.get("value"):
            facts.update(session_fields(sess))
    return facts, None


def classify(r, fetch):
    """Return (kind, reasons, facts); kind is "candidate", "keep" or "stale"."""
    keep, facts = [], {"placement": placement(r)}
    tab = facts["placement"] == "tab"
    found, err = tab_facts(r) if tab else workspace_facts(r)
    if err:
        # Only an explicit "not found" means the user closed it. Any other failure must not be read as
        # "closed": that would skip the worker-status check and remove a worktree under a live worker.
        return "keep", [f"could not query herdr ({err})"], facts
    facts.update(found)
    if facts["agent_status"] in ("working", "blocked"):
        keep.append(f"worker is {facts['agent_status']}")
    if facts["focused"]:
        keep.append(f"user is viewing this {'tab' if tab else 'workspace'}")
    for c in facts.get("companions") or []:
        if c["agent_status"] in ("working", "blocked"):
            keep.append(f"{c['label']} is {c['agent_status']}")
        if c["focused"]:
            keep.append(f"user is viewing tab {c['label']}")

    wt, branch, root = r["worktree"], r["branch"], r["root"]
    if not os.path.isdir(wt):
        # removed outside this skill: nothing left to delete, only the record to update
        facts["why"] = "worktree already removed"
        facts["remove_command"] = None
        return "stale", [], facts
    # The user may have closed the workspace by hand; the worktree then has no workspace to remove it with.
    # A tab worker's worktree was never opened in herdr: git removes it (refusing uncommitted changes), and only
    # then is its own tab closed, never the space it runs in.
    if tab:
        closing = ([facts["tab"]] if facts["tab_open"] else []) + [c["tab"] for c in facts["companions"]]
        facts["remove_command"] = f'git -C {root} worktree remove {wt}' + "".join(
            f" && herdr tab close {t}" for t in closing)
    else:
        facts["remove_command"] = (f'herdr worktree remove --workspace {r["workspace"]}' if facts["workspace_open"]
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
        entry = {"name": r["name"], "branch": r["branch"], "worktree": r["worktree"], "workspace": r["workspace"],
                 **facts, "agent": facts.get("agent") or r.get("agent"),
                 "session_id": facts.get("session_id") or r.get("session_id")}
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
    if a.agent:
        r["agent"] = a.agent
    r["state"], r["cleaned_at"] = "cleaned", now()
    save(runs)
    print(json.dumps(r, ensure_ascii=False, indent=2))


def cmd_mark_open(a):
    runs = load()
    r = find(runs, norm_root(a.root), a.name, "cleaned")
    if not r:
        die(f"no cleaned run named {a.name}")
    r.update(state="open", workspace=a.workspace, pane=a.pane, cleaned_at=None, placement=a.placement or placement(r))
    # The resumed (or freshly started) agent may report a different agent or session; keep the clues current.
    sess = current_session(a.pane)
    if sess and sess.get("value"):
        r.update(session_fields(sess))
    save(runs)
    print(json.dumps(r, ensure_ascii=False))


def cmd_relocate(a):
    """An open run whose workspace or tab was closed and given back (place.py reopen) lives in a new place."""
    runs = load()
    r = find(runs, norm_root(a.root), a.name, "open")
    if not r:
        die(f"no open run named {a.name}")
    r.update(workspace=a.workspace, pane=a.pane, placement=a.placement or placement(r))
    sess = current_session(a.pane)
    if sess and sess.get("value"):
        r.update(session_fields(sess))
    save(runs)
    print(json.dumps(r, ensure_ascii=False))


def cmd_show(a):
    root = norm_root(a.root)
    runs = [r for r in load() if r["root"] == root and (a.name is None or r["name"] == a.name)]
    print(json.dumps(runs, ensure_ascii=False, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("add")
    for k in ("name", "root", "branch", "base", "from-branch", "worktree", "workspace", "pane"):
        s.add_argument(f"--{k}", required=True)
    s.add_argument("--placement", choices=PLACEMENTS, required=True)   # place.py's output; no default to fall back on
    s.add_argument("--brief")
    s = sub.add_parser("scan"); s.add_argument("--root", required=True); s.add_argument("--fetch", action="store_true")
    s = sub.add_parser("mark-cleaned"); s.add_argument("--root", required=True); s.add_argument("--name", required=True)
    s.add_argument("--session-id"); s.add_argument("--agent")
    for cmd in ("mark-open", "relocate"):
        s = sub.add_parser(cmd); s.add_argument("--root", required=True); s.add_argument("--name", required=True)
        s.add_argument("--workspace", required=True); s.add_argument("--pane", required=True)
        s.add_argument("--placement", choices=PLACEMENTS)
    s = sub.add_parser("show"); s.add_argument("--root", required=True); s.add_argument("--name")
    a = p.parse_args()
    {"add": cmd_add, "scan": cmd_scan, "mark-cleaned": cmd_mark_cleaned,
     "mark-open": cmd_mark_open, "relocate": cmd_relocate, "show": cmd_show}[a.cmd](a)


if __name__ == "__main__":
    main()
