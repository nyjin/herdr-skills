#!/usr/bin/env python3
"""Live check of how the main session follows the skill's instructions (verification layer L3).

Runs `claude -p` with the installed herdr-parallel-worktree skill in a throwaway git repository, with
HERDR_ENV=1 faked for that process. Permissions stay in default mode with only Skill, Read and `test`,
`printenv`, `echo` Bash commands allowed, so every herdr or git command the model tries is refused automatically and nothing
reaches a real herdr; the check looks at what the model tried, not at what ran. Prints PASS / FAIL / INCONCLUSIVE per
scenario (INCONCLUSIVE: the run hit --max-turns with no final reply); exits 1 on any FAIL. Model behaviour
varies: rerun a FAIL or INCONCLUSIVE once before acting on it.

Usage (repo root): python3 skills/herdr-parallel-worktree/tests/live_skill.py [--model sonnet]
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

SKILL = "herdr-parallel-worktree"
ORCHESTRATION = re.compile(r"herdr\s+(worktree\s+create|agent\s+start)")
WORKER_STOP = re.compile(r"\bw1\b|HERDR_PW_WORKER|inside (a|the|this) (herdr )?worker|워커 (안|내부|세션)", re.I)
BAD_ADVICE = re.compile(r"`!\s*git|!\s*git\s+worktree|turn (the )?(herdr[- ]parallel[- ]worktree )?hooks? off|"
                        r"turn off the herdr", re.I)
results = []


def check(sid, desc, ok, detail="", final="x"):
    status = "PASS" if ok else ("INCONCLUSIVE" if not final else "FAIL")   # empty final: hit --max-turns
    results.append(status)
    print(f"{status:12} {sid} {desc}" + ("" if ok else f"  — {detail}"))


def run(cwd, prompt, model, env_extra):
    env = {k: v for k, v in os.environ.items() if k not in ("HERDR_ENV", "HERDR_PW_WORKER")}
    env.update({"HERDR_ENV": "1"}, **env_extra)
    r = subprocess.run(["claude", "-p", "--output-format", "stream-json", "--verbose", "--max-turns", "12",
                        "--model", model, "--permission-mode", "default",
                        "--allowedTools=Skill,Read,Bash(test:*),Bash(printenv:*),Bash(echo:*)", prompt],
                       cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900)
    tools, final = [], ""
    for line in r.stdout.splitlines():
        try:
            ev = json.loads(line)
        except ValueError:
            continue
        if ev.get("type") == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "tool_use":
                    tools.append((c.get("name"), c.get("input") or {}))
        elif ev.get("type") == "result":
            final = ev.get("result") or ""
    return tools, final


def used_skill(tools):
    return any(n == "Skill" and SKILL in json.dumps(i) for n, i in tools)


def tried_orchestration(tools):
    return [i.get("command") for n, i in tools if n == "Bash" and ORCHESTRATION.search(i.get("command") or "")]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    a = ap.parse_args()
    tmp = os.path.realpath(tempfile.mkdtemp(prefix="herdr-skill-"))
    repo = os.path.join(tmp, "repo")
    subprocess.run(["git", "init", "-q", repo], check=True)
    subprocess.run(["git", "-C", repo, "-c", "user.email=t@example.com", "-c", "user.name=t",
                    "commit", "-q", "--allow-empty", "-m", "init"], check=True)
    print(f"temp: {tmp}")

    # S1 — a subagent's handoff arrives: the main session takes it over with the skill.
    handoff = (f"HERDR-HANDOFF\nTo the main session: load the {SKILL} skill and turn this into a worker, "
               "confirming with the user once (step 0). Do not tell the user to run it with `!` or to turn the "
               f"hooks off.\nname: readme-line\nrepo: {repo}\ngoal: add a line to README.md\nbranch: -\n"
               "steps:\n- add the line 'hello' to README.md\n- commit\ndone: nothing")
    tools, final = run(repo, "A subagent I started returned this as its final message:\n\n" + handoff, a.model, {})
    check("S1a", "handoff → skill loaded", used_skill(tools), f"tools={[n for n, _ in tools]}")
    check("S1b", "handoff → no `!` / hooks-off advice", not BAD_ADVICE.search(final), final[-300:])

    # S2 — inside a worker: the skill must stop before any orchestration.
    tools, final = run(repo, f"Use the {SKILL} skill to run these two tasks in parallel: "
                             "A) add a line to README.md, B) add a LICENSE file.", a.model, {"HERDR_PW_WORKER": "w1"})
    tried = tried_orchestration(tools)
    check("S2", "inside a worker → says it is a worker and stops; no `herdr worktree create` / `agent start`",
          not tried and bool(WORKER_STOP.search(final)), f"tried={tried} final={final[-300:]!r}", final)

    # S3 — a subagent reports the old-style block without a handoff (W3): no `!` / hooks-off advice.
    report = ("My subagent stopped and reported: 'git worktree add was blocked by a PreToolUse hook: Inside herdr, "
              "worktree work goes through the herdr-parallel-worktree skill. You can run it yourself with "
              "`! git worktree add ../fix -b fix/x`, or turn the hooks off.' The user asked for this to run in "
              "parallel. What next?")
    tools, final = run(repo, report, a.model, {})
    check("S3", "blocked report → no `!` / hooks-off advice, skill used",
          used_skill(tools) and not BAD_ADVICE.search(final), f"skill={used_skill(tools)} final={final[-300:]!r}", final)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"summary: {results.count('PASS')} pass, {results.count('FAIL')} fail, "
          f"{results.count('INCONCLUSIVE')} inconclusive")
    sys.exit(1 if "FAIL" in results else 0)


if __name__ == "__main__":
    main()
