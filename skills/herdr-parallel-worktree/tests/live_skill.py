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
# The model answers in the user's language, so these patterns match Korean replies as well as English ones.
WORKER_STOP = re.compile(r"\bw1\b|HERDR_PW_WORKER|inside (a|the|this) (herdr )?worker|워커 (안|내부|세션)", re.I)
BAD_ADVICE = re.compile(r"`!\s*git|!\s*git\s+worktree|turn (the )?(herdr[- ]parallel[- ]worktree )?hooks? off|"
                        r"turn off the herdr|훅을 끄", re.I)
NEGATION = re.compile(r"않|말고|마세요|말아|아니라|안\s*(함|해|합니다|할)|없(습니다|어요|다|음)|\bnot\b|n't\b|\bnever\b|instead of", re.I)
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


def bad_advice(text):
    """The first sentence that tells the user to run it with `!` or turn the hooks off; None if there is none.
    A sentence that says it will NOT do so ("I will not suggest `! git worktree add`") is not advice."""
    for sentence in re.split(r"(?<=[.?。])\s+|\n+", text):
        if BAD_ADVICE.search(sentence) and not NEGATION.search(sentence):
            return sentence
    return None


def deliver_attempt(tools):
    """Signs the main session followed the delivery path: read deliver.md, or tried `herdr agent prompt`,
    `runs.py show`/`relocate`, `herdr worktree open`, or `herdr agent wait`."""
    for n, i in tools:
        blob = json.dumps(i)
        if n == "Read" and "deliver.md" in blob:
            return True
        if n == "Bash" and re.search(r"herdr\s+agent\s+(prompt|wait)|runs\.py\s+(show|relocate)|herdr\s+worktree\s+open",
                                     i.get("command") or ""):
            return True
    return False


def tried_new_worker(tools):
    return [i.get("command") for n, i in tools if n == "Bash" and re.search(r"herdr\s+worktree\s+create",
                                                                         i.get("command") or "")]


def tried_herdr(tools):
    return [i.get("command") for n, i in tools if n == "Bash" and re.search(r"\bherdr\s", i.get("command") or "")]


ASKS = re.compile(r"\?|？|알려\s*주세요|말씀해\s*주세요|답해\s*주시면|골라\s*주세요|let me know|which (do you|would you)", re.I)
NEW_WORKER = re.compile(r"(워커|worker)\s*(를|을)?\s*(띄|시작|start)|(새|new)\s*(워커|worker)|worktree.{0,20}(만들|생성|시작)|(create|start)\S*\s.{0,20}(worker|worktree)",
                        re.I | re.S)


def tried_git_change(tools):
    return [i.get("command") for n, i in tools if n == "Bash" and re.search(
        r"git\s+(-C\s+\S+\s+)?(commit|restore|checkout\s+--|stash|reset|add)\b", i.get("command") or "")]


def asked_user(tools, final):
    """It asked: an AskUserQuestion call, or a question in the last part of the reply."""
    return any(n == "AskUserQuestion" for n, _ in tools) or bool(ASKS.search(final[-400:]))


def offers_new_worker(tools, final):
    """For a main-checkout handoff, offering a new worker or worktree is the wrong answer. Returns the first
    sentence that offers one (a sentence saying it will NOT start one is not an offer), or None."""
    texts = [final] + [json.dumps(i, ensure_ascii=False) for n, i in tools if n == "AskUserQuestion"]
    for text in texts:
        for sentence in re.split(r"(?<=[.?。])\s+|\n+", text):
            if NEW_WORKER.search(sentence) and not NEGATION.search(sentence):
                return sentence
    return None


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
    check("S1b", "handoff → no `!` / hooks-off advice", not bad_advice(final), bad_advice(final) or "")

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
          used_skill(tools) and not bad_advice(final), f"skill={used_skill(tools)} advice={bad_advice(final)!r}", final)

    def block(owner, goal):
        return (f"HERDR-HANDOFF\nTo the main session: load the {SKILL} skill and handle this by its `owner:` line "
                "(step 0, Receiving a handoff): pass it to that worker, ask the user about the main checkout, or "
                "start a new worker for `none`, confirming with the user once. Do not tell the user to run it with "
                f"`!` or to turn the hooks off.\nname: fix-b\nrepo: {repo}\nowner: {owner}\ngoal: {goal}\n"
                "branch: -\nsteps:\n- edit notes.md\ndone: nothing")

    # S4 — owner is an existing worker: deliver to it, never start a new worker for it.
    tools, final = run(repo, "A subagent I started returned this as its final message:\n\n"
                       + block("sib", "add a line to notes.md in worker sib's worktree"), a.model, {})
    check("S4", "owner worker → delivery path (deliver.md / agent prompt), no new worktree",
          deliver_attempt(tools) and not tried_new_worker(tools),
          f"deliver={deliver_attempt(tools)} new={tried_new_worker(tools)} tools={[n for n, _ in tools]}", final)

    # S5 — owner is the main checkout: tell the user and ask; no herdr command.
    tools, final = run(repo, "A subagent I started returned this as its final message:\n\n"
                       + block("main-checkout", "it changed notes.md in the main checkout"), a.model, {})
    # Offering "commit first, then continue in a worker" as a choice is allowed (user decision 2026-10-07);
    # acting on the user's checkout or starting anything is not.
    check("S5", "owner main-checkout → tells the user and asks; acts on nothing (no herdr, no git change)",
          asked_user(tools, final) and not tried_herdr(tools) and not tried_git_change(tools),
          f"asked={asked_user(tools, final)} herdr={tried_herdr(tools)} git={tried_git_change(tools)}", final)

    # S6 — the block arrives in a worker's `## Result` instead of from a subagent.
    result = ("Worker `fix-a` finished. Its final response:\n\n## Result\nDone in my worktree. One part belongs to "
              "another worker:\n\n" + block("sib", "add a line to notes.md in worker sib's worktree"))
    tools, final = run(repo, result, a.model, {})
    check("S6", "HANDOFF inside a worker's ## Result → same delivery path",
          deliver_attempt(tools) and not tried_new_worker(tools),
          f"deliver={deliver_attempt(tools)} new={tried_new_worker(tools)} tools={[n for n, _ in tools]}", final)

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"summary: {results.count('PASS')} pass, {results.count('FAIL')} fail, "
          f"{results.count('INCONCLUSIVE')} inconclusive")
    sys.exit(1 if "FAIL" in results else 0)


if __name__ == "__main__":
    main()
