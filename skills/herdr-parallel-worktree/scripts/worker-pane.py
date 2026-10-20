#!/usr/bin/env python3
"""Give a worker its own shell in a worktree workspace, after herdr's plugins have laid out that workspace.

Usage:
  worker-pane.py --workspace W --worktree WT --name N --since MS [--timeout-ms 15000] [--quiet-ms 2000] [--poll-ms 200]

herdr runs plugins on `worktree.created` / `worktree.opened`, and a plugin may fill the new workspace with its
own tabs and start programs in them, including the root pane (herdr-plus, for example, starts claude there).
Whether a pane is free cannot be told from a moment's look: a plugin's command can still sit in the shell's input
queue. So the worker never uses those panes:

1. Wait until every plugin handler for those events that started at or after --since (milliseconds, taken just
   before `herdr worktree create` or `worktree open`) has finished, as `herdr plugin log list` reports. With no
   such handler within --quiet-ms, no plugin reacted. A tab created before a plugin runs can make it skip its
   layout, so this comes first.
2. Create a tab labelled N in workspace W, cwd WT, with HERDR_PW_WORKER=N in its environment.
3. Wait until the tab's shell owns the terminal's foreground, i.e. it is at its prompt.

Prints JSON: {"tab", "pane", "settled", "handlers": [{"plugin", "event", "status"}], "still_running": [...],
"shell_ready"}. A plugin still running at --timeout-ms or a shell not ready in time is reported, not fatal: the
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


def handlers(since):
    try:
        logs = herdr("plugin", "log", "list", "--limit", "100").get("logs") or []
    except RuntimeError:
        return []   # an older herdr without plugin logs: nothing to wait for
    return [{"plugin": e.get("plugin_id"), "event": e.get("event"), "status": e.get("status")}
            for e in logs if e.get("event") in EVENTS and (e.get("started_unix_ms") or 0) >= since]


def settle(since, timeout_ms, quiet_ms, poll_ms):
    start = time.monotonic()
    while True:
        seen = handlers(since)
        elapsed = (time.monotonic() - start) * 1000
        running = [h["plugin"] for h in seen if h["status"] == "running"]
        if seen and not running:
            return True, seen, []
        if not seen and elapsed >= quiet_ms:
            return True, [], []
        if elapsed >= timeout_ms:
            return False, seen, running
        time.sleep(poll_ms / 1000)


def shell_ready(pane, timeout_ms, poll_ms):
    start = time.monotonic()
    while True:
        try:
            info = herdr("pane", "process-info", "--pane", pane).get("process_info") or {}
            if info.get("shell_pid") and info.get("foreground_process_group_id") == info.get("shell_pid"):
                return True
        except RuntimeError:
            pass
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

    settled, seen, running = settle(a.since, a.timeout_ms, a.quiet_ms, a.poll_ms)
    try:
        tab = herdr("tab", "create", "--workspace", a.workspace, "--cwd", a.worktree, "--label", a.name,
                    "--env", f"HERDR_PW_WORKER={a.name}", "--no-focus")
    except RuntimeError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
    pane = (tab.get("root_pane") or {}).get("pane_id")
    print(json.dumps({"tab": (tab.get("tab") or {}).get("tab_id"), "pane": pane, "settled": settled,
                      "handlers": seen, "still_running": running,
                      "shell_ready": bool(pane) and shell_ready(pane, a.timeout_ms, a.poll_ms)}))


if __name__ == "__main__":
    main()
