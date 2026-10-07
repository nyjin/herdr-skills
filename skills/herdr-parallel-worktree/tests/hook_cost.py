#!/usr/bin/env python3
"""Measure the routing hooks' cost per call (spec §6, §12.4; plan Task 4 L2c). Usage (repo root):
python3 skills/herdr-parallel-worktree/tests/hook_cost.py

Runs the registered commands from hooks/hooks.json through `sh -c`, as Claude Code does, against a scratch
repository with 3000 files and one linked worktree. Prints PASS/FAIL per line; exits 1 on any FAIL.
"""
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
with open(os.path.join(ROOT, "hooks", "hooks.json")) as f:
    HOOKS = json.load(f)["hooks"]


def command(event, matcher):
    cmd = next(g for g in HOOKS[event] if g["matcher"] == matcher)["hooks"][0]["command"]
    return cmd.replace("${CLAUDE_PLUGIN_ROOT}", ROOT)


def ms(cmd, event, env, n=15):
    payload = json.dumps(event)
    times = []
    for _ in range(n):
        t = time.perf_counter()
        subprocess.run(["sh", "-c", cmd], input=payload, capture_output=True, text=True, env=env)
        times.append((time.perf_counter() - t) * 1000)
    return statistics.median(times)


def main():
    tmp = os.path.realpath(tempfile.mkdtemp())
    repo, wt, home = (os.path.join(tmp, n) for n in ("repo", "wt", "home"))
    g = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]
    subprocess.run(["git", "init", "-q", repo], check=True)
    for i in range(3000):
        d = os.path.join(repo, f"d{i % 30}")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, f"f{i}.txt"), "w") as f:
            f.write(f"{i}\n")
    subprocess.run(g + ["-C", repo, "add", "."], check=True)
    subprocess.run(g + ["-C", repo, "commit", "-q", "-m", "i"], check=True)
    for path, branch in ((wt, "w"), (home, "h")):
        subprocess.run(["git", "-C", repo, "worktree", "add", "-q", path, "-b", branch], check=True)
    base = {k: v for k, v in os.environ.items() if k not in ("HERDR_ENV", "HERDR_PW_WORKER")}
    base.update(HERDR_ENV="1", HERDR_SKILLS_DATA_HOME=os.path.join(tmp, "data"))
    worker = dict(base, HERDR_PW_WORKER="w1")

    def post(cmd_text, sub, stdout_size=1000):
        e = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "cwd": home, "session_id": "s",
             "tool_use_id": "t", "duration_ms": 1500, "tool_input": {"command": cmd_text},
             "tool_response": {"stdout": "a" * stdout_size, "stderr": "", "interrupted": False}}
        if sub:
            e.update(agent_id="a1", agent_type="general-purpose")
        return e

    bash = command("PostToolUse", "Bash")
    rows = [
        ("main Bash Post, 1KB output (early exit)", ms(bash, post("ls", False), base), 40),
        ("main Bash Post, 10MB output (early exit)", ms(bash, post("ls", False, 10_000_000), base, 7), 150),
        ("subagent Bash Post, no path mentioned", ms(bash, post("ls -la", True), base), 80),
        ("worker Bash Post, no path mentioned", ms(bash, post("make test", False), worker), 80),
        ("subagent Bash Post, mentions a 3000-file worktree", ms(bash, post(f"cat {wt}/d1/f1.txt", True), base), 300),
    ]
    subprocess.run(["rm", "-rf", tmp])
    bad = False
    for name, v, limit in rows:
        ok = v <= limit
        bad |= not ok
        print(f"{'PASS' if ok else 'FAIL':5} {name}: median {v:.1f} ms (limit {limit} ms)")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
