#!/usr/bin/env python3
"""Registry of workers started by herdr-parallel-worktree: record, list for cleanup, resume clues.

The registry is DATA_DIR/runs.json (DATA_DIR = ${HERDR_SKILLS_DATA_HOME:-~/.local/share/herdr-skills}/herdr-parallel-worktree).
herdr does not know which worktrees this skill created, so cleanup only ever considers entries recorded here.
Which workers to clean up is the user's choice: `scan` reports every open run with where its work stands and what,
if anything, blocks cleaning it up now; it never decides that a worker is finished.

Usage:
  runs.py add --name N --root ROOT --branch B --base SHA --from-branch FB --worktree WT --workspace W --pane P
              --placement workspace|tab [--brief PATH] [--summary TEXT]
  runs.py scan (--root ROOT | --all) [--fetch]
                                          every open run of ROOT (or of every repository): where its work stands,
                                          cleanable or what blocks it (JSON), sorted by status: done, working,
                                          idle, then any other
  runs.py mark-cleaned --root ROOT --name N [--agent A] [--session-id SID]
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
        "brief": a.brief, "summary": a.summary, **session_fields(current_session(a.pane)), "state": "open",
        "created_at": now(),
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
        if tab.get("label") != r["name"]:
            # worker-pane.py labels the worker's tab with its name. Another label means the recorded pane's
            # tab is not the worker's any more (ids reused after a herdr restart, or the user took it over).
            tab = {}
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


def plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def resolves(root, ref):
    return git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")[0] == 0


def count(root, *revs):
    rc, out = git(root, "rev-list", "--count", *revs)
    return int(out) if rc == 0 and out.isdigit() else None


def lines(root, *args):
    rc, out = git(root, *args)
    return out.splitlines() if rc == 0 and out else ([] if rc == 0 else None)


def work_state(r):
    """Where the run's work stands against the branch it came from. Informational only: it never blocks cleanup,
    because the branch and its commits stay and a cleaned worker can be resumed."""
    root, branch, base = r["root"], r["branch"], r["base"]
    w = {"state": "unknown", "into": None, "commits": None, "pushed": False}
    if not os.path.isdir(root):
        return {**w, "text": "unknown: repository not found"}
    if not resolves(root, f"refs/heads/{branch}"):
        return {**w, "text": "unknown: branch not found"}
    if git(root, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{branch}")[0] == 0:
        w["pushed"] = count(root, f"origin/{branch}..{branch}") == 0
    own = count(root, f"{base}..{branch}") if resolves(root, base) else None
    fb = r.get("from_branch")
    targets = [t for t in (fb, f"origin/{fb}") if fb and resolves(root, t)]
    w["commits"] = count(root, f"{targets[0]}..{branch}") if targets else own
    if own == 0:
        return {**w, "state": "no_commits", "commits": 0, "text": "no commits"}
    for t in targets:
        if git(root, "merge-base", "--is-ancestor", branch, t)[0] == 0:
            return {**w, "state": "merged", "into": t, "text": f"merged into {t}"}
    for t in targets:
        # `git cherry` lists the commits t lacks, skipping merges: "-" when an equivalent patch is in t (a
        # cherry-pick, a rebase merge, a one-commit squash). No line at all is not "by patch": nothing to compare.
        out = lines(root, "cherry", t, branch)
        if out and all(line.startswith("-") for line in out):
            return {**w, "state": "same_patches", "into": t, "text": f"in {t} by patch (cherry-pick or rebase)"}
    # Every file the branch changed since it started is identical in t (a squash merge). The set comes from the
    # recorded base, not the merge-base: after t was merged back into the branch that would be t itself. A base
    # made stale that way only adds files, which can make this miss a match, never claim a false one.
    changed = set(lines(root, "diff", "--no-renames", "--name-only", base, branch) or []) \
        if own is not None else set()
    if changed:
        for t in targets:
            differ = lines(root, "diff", "--no-renames", "--name-only", t, branch)
            if differ is not None and not changed & set(differ):
                return {**w, "state": "same_content", "into": t, "text": f"in {t} by content (squash merge)"}
    if w["pushed"]:
        return {**w, "state": "pushed", "text": "pushed, not merged"}
    if w["commits"] is None:
        return {**w, "text": "unknown: commits could not be counted"}
    return {**w, "state": "not_merged", "text": f"not merged ({plural(w['commits'], 'commit')})"}


WORK_STATES = ("no_commits", "merged", "same_patches", "same_content", "pushed", "not_merged", "unknown")

# The order the cleanup list shows workers in: done first, then working, then idle, then anything else (blocked,
# unknown, no agent running). Within one status the registry order stays (the sort is stable).
STATUS_ORDER = ("done", "working", "idle")


def status_rank(entry):
    s = entry.get("agent_status")
    return STATUS_ORDER.index(s) if s in STATUS_ORDER else len(STATUS_ORDER)


def last_activity(r, work):
    """The branch's last commit (committer date), or when the run started if it has no commits of its own."""
    if work["state"] not in ("no_commits", "unknown"):
        rc, out = git(r["root"], "log", "-1", "--format=%cI", r["branch"])
        if rc == 0 and out:
            return out
    return r.get("created_at")


def summary(r):
    """The run's one-line task summary: recorded by `add --summary`, or for an older run the title of its brief,
    `# [<name>] <summary>`. None when neither is there."""
    if r.get("summary"):
        return r["summary"]
    try:
        with open(r.get("brief") or "", encoding="utf-8") as f:
            first = f.readline().strip()
    except (OSError, UnicodeDecodeError):
        return None
    head = f"# [{r['name']}] "
    if not first.startswith(head):
        return None
    return first[len(head):].strip() or None


def classify(r):
    """Return (facts, blockers). Nothing about where the work stands blocks: only what would lose work or cut off
    a live worker does, and an unknown herdr status, which is never read as "closed"."""
    blockers, facts = [], {"placement": placement(r), "agent_status": None, "focused": False}
    tab = facts["placement"] == "tab"
    found, err = tab_facts(r) if tab else workspace_facts(r)
    if err:
        blockers.append(f"herdr could not be queried ({err})")
    else:
        facts.update(found)
        if facts["agent_status"] in ("working", "blocked"):
            blockers.append(facts["agent_status"])
        if facts["focused"]:
            blockers.append(f"user is viewing its {'tab' if tab else 'workspace'}")
        for c in facts.get("companions") or []:
            if c["agent_status"] in ("working", "blocked"):
                blockers.append(f"{c['label']} is {c['agent_status']}")
            if c["focused"]:
                blockers.append(f"user is viewing {c['label']}")

    wt, root = r["worktree"], r["root"]
    facts["worktree_exists"] = os.path.isdir(wt)
    facts["remove_command"] = None
    if not facts["worktree_exists"]:
        # removed outside this skill: nothing left to delete, only the record to mark
        return facts, blockers
    rc, dirty = git(wt, "status", "--porcelain", "--untracked-files=all")
    if rc != 0:
        blockers.append("git status failed")
    else:
        if dirty:
            blockers.append(plural(len(dirty.splitlines()), "uncommitted change"))
        # A commit made on a detached HEAD is on no branch: it would go with the worktree.
        n = count(wt, "HEAD", "--not", "--branches", "--tags", "--remotes")
        if n is None:
            blockers.append("could not read the worktree's HEAD")
        elif n:
            blockers.append(f"{plural(n, 'commit')} on no branch (detached HEAD)")
    if err:
        return facts, blockers
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
    return facts, blockers


def cmd_scan(a):
    open_runs = [r for r in load() if r["state"] == "open"]
    if a.all:
        roots = list(dict.fromkeys(r["root"] for r in open_runs))
    else:
        roots = [norm_root(a.root)]
    out = {"workers": [], "open_elsewhere": sum(r["root"] not in roots for r in open_runs),
           "untracked_worktrees": []}
    for root in roots:
        if a.fetch and os.path.isdir(root):
            git(root, "fetch", "--quiet", "--all", "--prune")
        tracked = set()
        for r in open_runs:
            if r["root"] != root:
                continue
            tracked.add(os.path.realpath(r["worktree"]))
            facts, blockers = classify(r)
            work = work_state(r)
            out["workers"].append({
                "name": r["name"], "branch": r["branch"], "root": root, "summary": summary(r),
                "worktree": r["worktree"], "workspace": r["workspace"], **facts,
                "created_at": r.get("created_at"), "last_activity": last_activity(r, work), "work": work,
                "cleanable": not blockers, "blockers": blockers,
                "agent": facts.get("agent") or r.get("agent"),
                "session_id": facts.get("session_id") or r.get("session_id")})
        wl = (herdr_json("worktree", "list", "--cwd", root) if os.path.isdir(root) else None) or {}
        for w in wl.get("worktrees", []):
            if w.get("is_linked_worktree") and os.path.realpath(w.get("path") or "/") not in tracked:
                out["untracked_worktrees"].append({"root": root, "path": w.get("path"), "branch": w.get("branch"),
                                                   "workspace": w.get("open_workspace_id")})
    out["workers"].sort(key=status_rank)
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
    s.add_argument("--summary")   # the one-line task summary of SKILL.md step 3 (the brief's title)
    s = sub.add_parser("scan")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--root")
    g.add_argument("--all", action="store_true")
    s.add_argument("--fetch", action="store_true")
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
