#!/usr/bin/env python3
"""A stand-in for the herdr CLI in live tests, so a real `claude -p` run never touches the user's herdr.

Records every call and answers the commands the hooks make, in the shapes herdr 0.9.0 prints:
`workspace get`, `workspace list`, `worktree open` (idempotent, like herdr's `already_open`) and
`workspace close`. It also plays through the skill's worker start (`worktree create` makes a real git worktree,
`plugin log list` (no plugins), `tab create`, `pane process-info`, `pane run`, `agent start`, `agent wait`,
`agent read`, ...) without running any agent. Anything else is recorded
and fails, which is enough to see that it was attempted.

  FAKE_HERDR_DIR       directory for calls.jsonl (one JSON array of arguments per call) and state.json
  FAKE_HERDR_REPO_KEY  the repo_key `workspace get` reports for any workspace
  FAKE_HERDR_REPO      the repository `worktree create` uses when called without --cwd

Install it as `herdr` on PATH with fake_herdr.install(bin_dir).
"""
import json
import os
import subprocess
import sys


def install(bin_dir):
    """Write a `herdr` shim into bin_dir that runs this file; return bin_dir."""
    os.makedirs(bin_dir, exist_ok=True)
    shim = os.path.join(bin_dir, "herdr")
    with open(shim, "w") as f:
        f.write(f'#!/bin/sh\nexec "{sys.executable}" "{os.path.abspath(__file__)}" "$@"\n')
    os.chmod(shim, 0o755)
    return bin_dir


def calls(fake_dir):
    path = os.path.join(fake_dir, "calls.jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [json.loads(line) for line in f if line.strip()]


def main():
    d = os.environ["FAKE_HERDR_DIR"]
    args = sys.argv[1:]
    with open(os.path.join(d, "calls.jsonl"), "a") as f:
        f.write(json.dumps(args) + "\n")
    state_path = os.path.join(d, "state.json")
    state = {"workspaces": []}
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)

    def save():
        with open(state_path, "w") as f:
            json.dump(state, f)

    def opt(name):
        return args[args.index(name) + 1] if name in args[:-1] else None

    def reply(obj, code=0):
        print(json.dumps(obj))
        sys.exit(code)

    if args[:2] == ["workspace", "get"] and len(args) > 2:
        reply({"result": {"workspace": {"workspace_id": args[2],
                                        "worktree": {"repo_key": os.environ.get("FAKE_HERDR_REPO_KEY", "")}}}})
    if args[:2] == ["workspace", "list"]:
        reply({"result": {"workspaces": state["workspaces"]}})
    if args[:2] == ["worktree", "open"]:
        path = opt("--path")
        for w in state["workspaces"]:
            if w["worktree"]["checkout_path"] == path:
                reply({"result": {"already_open": True, "workspace": w}})
        w = {"workspace_id": f"wf{len(state['workspaces']) + 1}", "label": opt("--label"),
             "worktree": {"checkout_path": path}}
        state["workspaces"].append(w)
        save()
        reply({"result": {"already_open": False, "workspace": w}})
    if args[:2] == ["workspace", "close"] and len(args) > 2:
        state["workspaces"] = [w for w in state["workspaces"] if w["workspace_id"] != args[2]]
        save()
        reply({"result": {"type": "ok"}})

    # The skill's worker start (steps 1-5). The worktree is a real one, so `git -C <worktree>` works afterwards;
    # no agent runs: every worker "finishes" at once with an empty result.
    if args[:2] == ["worktree", "create"]:
        repo = opt("--cwd") or os.environ.get("FAKE_HERDR_REPO") or os.getcwd()
        branch = opt("--branch") or f"fake-{len(state['workspaces']) + 1}"
        path = opt("--path") or os.path.join(d, "worktrees", branch.replace("/", "-"))
        r = subprocess.run(["git", "-C", repo, "worktree", "add", "-q", "-b", branch, path, opt("--base") or "HEAD"],
                           capture_output=True, text=True)
        if r.returncode != 0:
            reply({"error": {"code": "git_failed", "message": r.stderr.strip()}}, 1)
        wid = f"wf{len(state['workspaces']) + 1}"
        w = {"workspace_id": wid, "label": opt("--label") or branch, "worktree": {"checkout_path": path}}
        state["workspaces"].append(w)
        save()
        reply({"result": {"worktree": {"path": path, "branch": branch}, "workspace": w,
                          "root_pane": {"pane_id": f"{wid}:p1"}}})
    if args[:3] == ["plugin", "log", "list"]:
        reply({"result": {"logs": []}})                      # no plugins react to the fake worktrees
    if args[:2] == ["tab", "create"]:
        wid = opt("--workspace") or "wf0"
        n = state.setdefault("tabs", 0) + 1
        state["tabs"] = n
        save()
        reply({"result": {"tab": {"tab_id": f"{wid}:t{n + 1}"}, "root_pane": {"pane_id": f"{wid}:p{n + 1}"}}})
    if args[:2] == ["pane", "process-info"]:
        reply({"result": {"process_info": {"shell_pid": 1, "foreground_process_group_id": 1}}})
    if args[:2] in (["pane", "run"], ["agent", "rename"], ["pane", "wait-output"]):
        reply({"result": {"type": "ok"}})
    if args[:2] == ["pane", "get"]:
        reply({"result": {"pane": {"pane_id": args[2] if len(args) > 2 else "", "agent_status": "working",
                                   "agent": "claude", "session_id": "fake-session"}}})
    if args[:2] == ["pane", "read"]:
        reply({"result": {"text": "Commit your work. Do not push or open a pull request.\n$ "}})
    if args[:2] == ["agent", "start"]:
        reply({"result": {"type": "agent_started", "status": "working"}})
    if args[:2] == ["agent", "wait"]:
        reply({"result": {"status": "done"}})
    if args[:2] == ["agent", "read"]:
        reply({"result": {"text": "## Result\nFake worker for a test run: nothing was changed."}})
    reply({"error": {"code": "not_supported", "message": "fake herdr: this command is not simulated"}}, 1)


if __name__ == "__main__":
    main()
