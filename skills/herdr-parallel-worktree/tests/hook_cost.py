#!/usr/bin/env python3
"""Measure the routing hook's cost per call (verification of spec §6). Usage (repo root):
python3 skills/herdr-parallel-worktree/tests/hook_cost.py"""
import json, os, statistics, subprocess, sys, tempfile, time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
with open(os.path.join(ROOT, "hooks", "hooks.json")) as f:
    hooks = json.load(f)["hooks"]
write_cmd = next(g for g in hooks["PreToolUse"] if g["matcher"].startswith("Write"))["hooks"][0]["command"]
write_cmd = write_cmd.replace("${CLAUDE_PLUGIN_ROOT}", ROOT)

tmp = os.path.realpath(tempfile.mkdtemp())
repo, wt = os.path.join(tmp, "repo"), os.path.join(tmp, "wt")
g = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]
subprocess.run(["git", "init", "-q", repo], check=True)
subprocess.run(g + ["-C", repo, "commit", "-q", "--allow-empty", "-m", "i"], check=True)
subprocess.run(["git", "-C", repo, "worktree", "add", "-q", wt, "-b", "p"], check=True)
base = {k: v for k, v in os.environ.items() if k not in ("HERDR_ENV", "HERDR_PW_WORKER")}
base["HERDR_SKILLS_DATA_HOME"] = os.path.join(tmp, "data")


def ms(event, env, n=20):
    payload = json.dumps(event)
    times = []
    for _ in range(n):
        t = time.perf_counter()
        subprocess.run(["sh", "-c", write_cmd], input=payload, capture_output=True, text=True, env=env)
        times.append((time.perf_counter() - t) * 1000)
    return statistics.median(times)


main_ev = {"hook_event_name": "PreToolUse", "tool_name": "Write", "cwd": repo,
           "tool_input": {"file_path": os.path.join(wt, "f")}}
sub_ev = dict(main_ev, agent_id="a1", agent_type="general-purpose")
rows = [("outside herdr (guard only)", ms(sub_ev, base), 30),
        ("inside herdr, main session", ms(main_ev, dict(base, HERDR_ENV="1")), 200),
        ("inside herdr, subagent (python + 2 git)", ms(sub_ev, dict(base, HERDR_ENV="1")), 300)]
subprocess.run(["rm", "-rf", tmp])
bad = False
for name, v, limit in rows:
    ok = v <= limit
    bad |= not ok
    print(f"{'PASS' if ok else 'FAIL':5} {name}: median {v:.1f} ms (limit {limit} ms)")
sys.exit(1 if bad else 0)
