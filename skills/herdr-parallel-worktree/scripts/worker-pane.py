#!/usr/bin/env python3
"""Give a worker its own shell in a worktree workspace, after herdr's plugins have laid out that workspace.

Usage:
  worker-pane.py --workspace W --worktree WT --name N --since MS [--timeout-ms 15000] [--quiet-ms 2000] [--poll-ms 200]

herdr runs plugins on `worktree.created` / `worktree.opened`, and a plugin may fill the new workspace with its
own tabs and start programs in them, including the root pane (herdr-plus, for example, starts claude there).
Whether a pane is free cannot be told from a moment's look: a plugin's command can still sit in the shell's input
queue. So the worker never uses those panes:

1. Wait until every plugin handler for those events that started at or after --since (milliseconds, taken just
   before `herdr worktree create` or `worktree open`) has finished, as `herdr plugin log list` reports, and no
   new one has appeared for --quiet-ms after that (plugins' handlers need not show up at the same moment). With
   no such handler within --quiet-ms, no plugin reacted. A tab created before a plugin runs can make it skip its
   layout, so this comes first. A herdr without plugin logs has nothing to wait for; any other failure of the
   log query is not read as "no plugins": the wait goes on and, if it never succeeds, is reported.
2. Create a tab labelled N in workspace W, cwd WT, with HERDR_PW_WORKER=N in its environment.
3. Wait until the tab's shell is idle at its prompt: the shell is the only foreground process, twice in a row.
   Owning the foreground is not enough: prompt hooks (mise, direnv, ...) run in the shell's own process group,
   and herdr refuses `agent start` with `agent_pane_busy` while one runs.

Prints JSON: {"tab", "pane", "settled", "handlers": [{"plugin", "event", "status"}], "still_running": [...],
"log_error", "shell_ready"}. A plugin still running at --timeout-ms or a shell not ready in time is reported, not fatal: the
caller decides. Exits 1 with herdr's error on stderr only when the tab cannot be created.
"""
import argparse
import json
import subprocess
import sys
import time

EVENTS = ("worktree.created", "worktree.opened")


def herdr(*args):
    """Return herdr's result, or raise RuntimeError with its error code or output."""
    try:
        p = subprocess.run(["herdr", *args], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise RuntimeError(f"herdr {' '.join(args[:2])}: {e}")
    out = p.stdout.strip() or p.stderr.strip()
    try:
        data = json.loads(out) if out else {}
    except json.JSONDecodeError:
        raise RuntimeError(f"herdr {' '.join(args[:2])}: {out[:200]}")
    if p.returncode != 0 or "result" not in data:
        code = (data.get("error") or {}).get("code") or out[:200]
        raise RuntimeError(f"herdr {' '.join(args[:2])}: {code}")
    return data["result"]


UNSUPPORTED = ("unrecognized subcommand", "unsupported", "not_supported", "unknown_command")


def handlers(since):
    """Return (handlers, error). An older herdr without plugin logs gives ([], None): nothing to wait for."""
    try:
        logs = herdr("plugin", "log", "list", "--limit", "100").get("logs") or []
    except RuntimeError as e:
        return ([], None) if any(k in str(e) for k in UNSUPPORTED) else ([], str(e))
    return [{"plugin": e.get("plugin_id"), "event": e.get("event"), "status": e.get("status")}
            for e in logs if e.get("event") in EVENTS and (e.get("started_unix_ms") or 0) >= since], None


def settle(since, timeout_ms, quiet_ms, poll_ms):
    """Return (settled, handlers, still_running, log_error)."""
    start, done_at, done_n = time.monotonic(), None, 0
    while True:
        seen, error = handlers(since)
        now = time.monotonic()
        elapsed = (now - start) * 1000
        running = [h["plugin"] for h in seen if h["status"] == "running"]
        if error is None:
            if seen and not running:
                if done_at is None or len(seen) != done_n:   # all done for now; wait for a late handler
                    done_at, done_n = now, len(seen)
                elif (now - done_at) * 1000 >= quiet_ms:
                    return True, seen, [], None
            else:
                done_at = None
                if not seen and elapsed >= quiet_ms:
                    return True, [], [], None
        if elapsed >= timeout_ms:
            return False, seen, running, error
        time.sleep(poll_ms / 1000)


def idle_shell(info):
    shell = info.get("shell_pid")
    procs = [p.get("pid") for p in info.get("foreground_processes") or []]
    return bool(shell) and info.get("foreground_process_group_id") == shell and set(procs) <= {shell}


def shell_ready(pane, timeout_ms, poll_ms):
    start, streak = time.monotonic(), 0
    while True:
        try:
            streak = streak + 1 if idle_shell(herdr("pane", "process-info", "--pane", pane).get("process_info") or {}) else 0
        except RuntimeError:
            streak = 0
        if streak >= 2:
            return True
        if (time.monotonic() - start) * 1000 >= timeout_ms:
            return False
        time.sleep(poll_ms / 1000)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--workspace", required=True)
    p.add_argument("--worktree", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--since", type=int, required=True)
    p.add_argument("--timeout-ms", type=int, default=15000)
    p.add_argument("--quiet-ms", type=int, default=2000)
    p.add_argument("--poll-ms", type=int, default=200)
    a = p.parse_args()

    settled, seen, running, log_error = settle(a.since, a.timeout_ms, a.quiet_ms, a.poll_ms)
    try:
        tab = herdr("tab", "create", "--workspace", a.workspace, "--cwd", a.worktree, "--label", a.name,
                    "--env", f"HERDR_PW_WORKER={a.name}", "--no-focus")
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    pane = (tab.get("root_pane") or {}).get("pane_id")
    print(json.dumps({"tab": (tab.get("tab") or {}).get("tab_id"), "pane": pane, "settled": settled,
                      "handlers": seen, "still_running": running, "log_error": log_error,
                      "shell_ready": bool(pane) and shell_ready(pane, a.timeout_ms, a.poll_ms)}))


if __name__ == "__main__":
    main()
