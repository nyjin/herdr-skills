# herdr delegation routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inside herdr, worktree work that a subagent or worker tries to do on its own is stopped at the action and handed back to the main session, which runs it as a visible herdr worker through the `herdr-parallel-worktree` skill.

**Architecture:** `route.py` becomes a pure decision function `decide(event, env, probe)` that classifies the caller (main / sub / worker / worker-sub, from `agent_id` and `HERDR_PW_WORKER`) and the action (worktree creation, or a write into another linked worktree), and returns a deny or a context note. Hook registrations grow to Write/Edit tools, `cd`/`git -C` Bash commands and PostToolUse(Agent). The skill exports `HERDR_PW_WORKER` into each worker pane and learns to receive a HERDR-HANDOFF block.

**Tech Stack:** Python 3 standard library only (`json`, `os`, `re`, `subprocess`, `unittest`), Claude Code hooks, herdr CLI 0.x, git.

**Spec:** `docs/superpowers/specs/2026-10-04-herdr-delegation-routing-design.md`

## Global Constraints

- Python standard library only; no third-party packages, no pytest. Tests run with `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v` from the repo root.
- Fail open: any exception, git error or git timeout (2 seconds) → no output (allow).
- Outside herdr (`HERDR_ENV` != `1`) or with `"hooks": "off"` in `DATA_DIR/config.json`: no output and no python process (shell guard `[ "$HERDR_ENV" = 1 ] || exit 0;`).
- Judge actions only (tool name and `tool_input` fields); never inspect prompt prose.
- Worker marker variable name: `HERDR_PW_WORKER`, value = worker name.
- Handoff block marker: first line exactly `HERDR-HANDOFF`.
- `hooks/hooks.json` and `manage.py hook_entries()` must register the same set (enforced by a test).
- Five files were already modified in the working tree before this work (`.claude-plugin/plugin.json`, `README.ko.md`, `README.md`, `skills/herdr-parallel-worktree/SKILL.md`, `skills/herdr-parallel-worktree/references/config.schema.json`). They are the user's. Before the first task that edits one of them (Task 5), stop and ask the user to commit them or say how to handle them. Never `git add` them as part of another commit without that answer.
- Never commit, push or open a PR beyond the per-task commits listed here. Work on branch `design/delegation-routing`.
- Test files: `tests/test_*.py` are unit tests (L1, run by `unittest discover`, no network, no claude). `tests/live_*.py` and `tests/hook_cost.py` are run by hand (L2/L3/cost); their names keep them out of `discover`.

## Review Focus

1. A `file_path` given through a symlinked directory (macOS `/var` → `/private/var`, `/tmp` → `/private/tmp`) while `cwd` is the resolved path — must still be recognised as the same or a different worktree correctly (Task 2, integration test `test_symlinked_path_is_resolved`).
2. A Write to a file whose parent directories do not exist yet inside another worktree — must still be denied (Task 2, `test_new_file_in_missing_dir_of_other_worktree`).
3. `cd "/path with spaces/wt"` — quoted targets must be read; `cd $WT` must be ignored, not mis-read (Task 2, `test_quoted_cd_target`, `test_variable_cd_target_ignored`).
4. "cd" or "git -C" appearing inside a quoted argument such as a commit message — must not be treated as a command (Task 2, `test_cd_inside_commit_message_ignored`).
5. git hanging (slow or network filesystem) — must time out and allow, never block the user (Task 2, `test_git_timeout_allows`).


## Verification Model

Four layers. A requirement counts as verified only at the layer named for it in the traceability table; a lower layer passing is not evidence for a higher one.

| Layer | What it proves | How | Cost | When |
|---|---|---|---|---|
| L1 unit | `decide()` returns the right outcome for every rule × caller, git probing and parsing edge cases, process entry point, registration parity | `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v` | seconds, no network | every task from 1 on, before each commit |
| L2 live hooks | The real Claude Code sends the fields we rely on (`agent_id`, `cwd`, `tool_input`), the registered matchers and `if` filters fire, denies reach the model, the subagent actually returns a filled handoff, the main session actually receives the note | `python3 skills/herdr-parallel-worktree/tests/live_hooks.py` (4 × `claude -p`, HERDR_ENV faked, Skill disallowed, no herdr) | ~3 min, model calls | Task 4, Task 6 |
| L2c cost | Spec §6: outside herdr no python, inside herdr cheap | `python3 skills/herdr-parallel-worktree/tests/hook_cost.py` | seconds | Task 4 |
| L3 skill behaviour | With the edited SKILL.md, the main session takes a handoff over with the skill, does not advise `!` / hooks off, and a worker refuses to orchestrate | `python3 skills/herdr-parallel-worktree/tests/live_skill.py` (3 scenarios × `claude -p`, only `test`/`printenv`/`echo` Bash allowed, so no herdr command can run) | ~3 min, model calls | Task 5 (before and after the edits), Task 6 |
| L4 herdr E2E | The whole flow in a real herdr: handoff → one confirmation → visible worker with `HERDR_PW_WORKER` → nested creation refused | Task 7, by hand with the user | ~15 min, user present | Task 7 |

Rules:
- **Red before green.** Every L1 test is run and seen failing before the code that makes it pass. L3 is run once before the SKILL.md edits; S2 and S3 must not PASS there (the old skill has no worker guard and still advises `!` — that is the W3 reproduction). A check that already passes before the change proves nothing about the change.
- **INCONCLUSIVE is not PASS.** L2/L3 print INCONCLUSIVE when the model never attempted the action under test (or hit `--max-turns`). Rerun once; if it stays INCONCLUSIVE, report it as unverified, with the output.
- **Model-behaviour checks get one rerun.** A FAIL in L2 C4 or in L3 is rerun once. Two FAILs in a row are a real failure: report it, do not loosen the check.
- **Evidence.** Each task's report includes the exact commands run and the summary lines they printed (`Ran N tests … OK`, `summary: N pass, 0 fail, 0 inconclusive`, cost lines). Task 0 and Task 7 record their results in the spec §11 table / the final report.
- **Pre-measured.** The L1 code, `live_hooks.py`, `live_skill.py` and `hook_cost.py` in this plan were assembled and run against a scratch copy while writing it (L1: 38 tests OK; L2: 11 pass; L3 against the unedited skill: S1a/S1b pass, S2/S3 not passing as expected; cost: 7.7 / 41 / 56 ms). Differences from those results on the real branch are findings, not noise.

### Traceability

| Spec requirement | Verified by |
|---|---|
| §1-1 subagent stopped, returns HERDR-HANDOFF | L1 `CreationTest.test_sub_is_told_to_hand_off`, `WriteRuleTest`, `SpecMatrixTest`; L2 C1, C2, C4, C5; L4 Task 7 expectations 1–2 |
| §1-2 main takes the handoff over, no `!` / hooks-off advice | L1 `MessageTest`; L2 C3; L3 S1a, S1b, S3; L4 Task 7 expectation 3 |
| §1-3 no nested orchestration in a worker | L1 `SpecMatrixTest` (worker column), `test_worker_is_told_to_do_it_itself`; L2 C8, C9; L3 S2; L4 Task 7 expectation 6 |
| §1-4 zero cost outside herdr | L1 `EntryPointTest.test_silent_outside_herdr`, `RegistrationTest.test_every_command_is_guarded_and_names_its_event`; L2 C10, C11; L2c outside line |
| §1-5 decisions pinned by unit tests | L1 `SpecMatrixTest.test_every_cell` (24 cells = spec §5.3 table) |
| §5.2 own worktree / main checkout / outside git / git failure allowed | L1 `OtherWorktreeTest`, `GitProbeTest`, `WriteRuleTest.test_allowed_writes`; L2 C6, C7 |
| §5.3 R5 Bash target parsing | L1 `DirTargetsTest`; `if` filters by Task 0 V2 |
| §5.4 message texts | L1 `MessageTest`, `SpecMatrixTest.outcome` (exact text equality) |
| §5.5 skill text: worker stop, handoff receipt, export, W4, Never | L3 S1–S3; Task 5 Step 7 greps; L4 Task 7 |
| §5.6 plugin and standalone register the same hooks | L1 `RegistrationTest.test_same_set`, `test_manage_marker_still_finds_every_group` |
| §6 cost | L2c `hook_cost.py` |
| §9 V1–V4 | Task 0, results in spec §11 |
| `hooks: off`, bad input, unknown argument → silent | L1 `EntryPointTest` |

---

### Task 0: Measure V1–V4 before coding

No code changes. Results go into the spec as a new section and decide two details used later (Task 4's `if` patterns, Task 5's W4 text). If V1 fails, stop and report to the user: the worker marker design must change before anything else.

**Done when:** spec §11 has a filled row for V1–V4 (no `<…>` left), V1's decision row is stated, and the spec commit exists. If V1 chose anything but export, the plan stops here.

**Files:**
- Modify: `docs/superpowers/specs/2026-10-04-herdr-delegation-routing-design.md` (append `## 11. 실측 결과`)

Use a scratch directory outside the repo for every probe file: `S="$(mktemp -d)"`. Shell variables do not survive between Bash calls; put the printed value of `S` into later commands.

- [ ] **Step 1: V1 — which way of setting `HERDR_PW_WORKER` reaches a claude started by `herdr agent start`?**

`herdr agent start` and `herdr worktree create` take no environment option (checked in `herdr api schema --json`: `AgentStartParams`, `WorktreeCreateParams` have no `env`); only `pane split` does (`PaneSplitParams.env`). Compare the two candidate ways in one run:

- **A. export**: type `export HERDR_PW_WORKER=…` into the pane's shell, then `agent start` (the plan's design).
- **B. split --env**: create the pane with `herdr pane split --env HERDR_PW_WORKER=…`, then `agent start` without any export.

Must be run inside herdr (`HERDR_ENV=1`). Creates two panes; close both yourself at the end (this probe created them).

```bash
S="$(mktemp -d)"; echo "$S"
for v in a b; do
cat > "$S/v1-$v.json" <<EOF
{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"echo \"worker=\${HERDR_PW_WORKER:-unset}\" > $S/v1-$v.out"}]}]}}
EOF
done
herdr pane split --current --direction down | jq .
herdr pane split --current --direction down --env HERDR_PW_WORKER=v1b | jq .
```

Read each new pane id from its output (`.result.pane.pane_id`, or the id field the output shows): the first is `PA`, the second `PB`. Then:

```bash
herdr pane run "<PA>" "export HERDR_PW_WORKER=v1a; echo v1-ready"
herdr pane wait-output "<PA>" --match v1-ready --timeout 10000
herdr agent start v1a --kind claude --pane "<PA>" --timeout 30000 -- --settings "<S>/v1-a.json" "Reply with the single word ok."
herdr pane run "<PB>" "echo v1-ready"
herdr pane wait-output "<PB>" --match v1-ready --timeout 10000
herdr agent start v1b --kind claude --pane "<PB>" --timeout 30000 -- --settings "<S>/v1-b.json" "Reply with the single word ok."
cat "<S>/v1-a.out" "<S>/v1-b.out"
herdr pane close "<PA>"; herdr pane close "<PB>"
```

Decide from the two lines:

| A (`v1-a.out`) | B (`v1-b.out`) | Decision |
|---|---|---|
| `worker=v1a` | any | Keep export (Tasks 1–7 as written). |
| `worker=unset` | `worker=v1b` | Stop the plan. Report to the user: the design changes to "create the worktree, split its root pane with `--env`, run the worker in the split pane", which needs its own check of closing the root pane against `worktree remove`, cleanup and resume before Tasks 5 and 7 are rewritten. |
| `worker=unset` | `worker=unset` | Stop the plan. Report to the user: fall back to identifying workers from `runs.json` (the worker's worktree path vs the hook's `cwd`), which changes `route.actor` and needs a design update first. |

A missing `.out` file means the SessionStart hook did not run (claude did not start); look at the pane with `herdr pane read "<P>" --source visible --lines 40` and report instead of guessing.

- [ ] **Step 2: V2 — which `if` patterns select `cd` / `git -C` Bash commands?**

```bash
S="<S from step 1>"
cat > "$S/mark.sh" <<'EOF'
#!/bin/sh
echo "$1" >> "$(dirname "$0")/v2.out"
EOF
chmod +x "$S/mark.sh"
cat > "$S/v2.json" <<EOF
{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[
 {"type":"command","if":"Bash(*git -C *)","command":"$S/mark.sh gitC"},
 {"type":"command","if":"Bash(cd *)","command":"$S/mark.sh cdStart"},
 {"type":"command","if":"Bash(* cd *)","command":"$S/mark.sh cdMid"}]}]}}
EOF
: > "$S/v2.out"
cd "$S" && claude -p --settings "$S/v2.json" --permission-mode bypassPermissions --model sonnet "Run these four Bash commands one at a time, each as its own Bash call, then reply done: (1) cd /tmp && true (2) git -C /tmp status || true (3) ls (4) true && cd /tmp" < /dev/null
cat "$S/v2.out"
```

Expected: command (1) → `cdStart`, (2) → `gitC`, (3) → nothing, (4) → `cdMid`. Record the exact lines. Task 4 uses the three patterns as written if they behave like this; if a pattern never fires, Task 4 drops `if` for that hook group (runs on every Bash inside herdr — the shell guard still keeps the cost outside herdr at zero) and the result says so.

- [ ] **Step 3: V3 — does the hook `cwd` follow `cd` into a directory inside the project?**

```bash
S="<S>"
mkdir -p "$S/v3/repo/.worktrees/x" && git -C "$S/v3/repo" init -q
cat > "$S/dump.sh" <<'EOF'
#!/bin/sh
python3 -c 'import json,sys; e=json.load(sys.stdin); print(e["tool_name"], "sub" if "agent_id" in e else "main", e["cwd"])' >> "$(dirname "$0")/v3.out"
EOF
chmod +x "$S/dump.sh"
printf '{"hooks":{"PreToolUse":[{"matcher":"Bash","hooks":[{"type":"command","command":"%s/dump.sh"}]}]}}\n' "$S" > "$S/v3.json"
: > "$S/v3.out"
cd "$S/v3/repo" && claude -p --settings "$S/v3.json" --permission-mode bypassPermissions --model sonnet "Run Bash: cd .worktrees/x && pwd. Then run Bash: pwd. Then call the Agent tool once (subagent_type general-purpose) with prompt 'Run Bash: cd .worktrees/x && pwd. Then run Bash: pwd. Reply done.' and wait for it. Reply done." < /dev/null
cat "$S/v3.out"
```

Record whether the second `cwd` of main and of sub ends in `/.worktrees/x`. The design does not depend on either answer (it never uses `cwd` as the target); record it so the spec's F3 is complete. If `cwd` does follow `cd`, add one sentence to the spec: "`home` is the worktree of the hook's `cwd`, which can be the directory last entered with `cd`."

- [ ] **Step 4: V4 — reproduce the `wait-output` timeout**

Inside herdr. One pane, closed at the end.

```bash
S="<S>"
python3 - "$S/brief.md" <<'EOF'
import sys
lines = [f"- step {i}: " + "lorem ipsum dolor sit amet " * 4 for i in range(300)]
tail = ("When the work is done, commit any changes you made to this branch, and end your final response "
        "with a `## Result` heading that covers the change summary, test results and open issues. "
        "Do not push or open a pull request.")
open(sys.argv[1], "w").write("# Brief\n\n" + "\n".join(lines) + "\n\n" + tail + "\n")
EOF
herdr pane split --current --direction down | jq .
herdr pane run "<P>" "cat <S>/brief.md"
time herdr pane wait-output "<P>" --match "Do not push or open a pull request." --source recent-unwrapped --timeout 5000; echo "exit=$?"
time herdr pane wait-output "<P>" --match "Do not push or open a pull request." --source recent-unwrapped --lines 400 --timeout 5000; echo "exit=$?"
herdr pane read "<P>" --source recent-unwrapped --lines 5
herdr pane close "<P>"
```

Record: exit code and time of each wait, and whether the last line is visible in `pane read`. Task 5 Step 4 uses this: if the `--lines 400` variant succeeds where the plain one fails, the fix is to add `--lines`; otherwise the fix is the longer timeout plus the read-back check.

- [ ] **Step 5: Write the results into the spec and commit**

Append to the spec:

```markdown
## 11. 실측 결과 (구현 전)

| 항목 | 결과 | 반영 |
|---|---|---|
| V1 워커 표식 전달 | A export: <worker=… 출력 그대로>, B split `--env`: <worker=… 출력 그대로> | <export 유지 / split 방식으로 변경 / runs.json 대체> |
| V2 `if` 패턴 | (1)<…> (2)<…> (3)<…> (4)<…> | Task 4 등록 패턴 |
| V3 프로젝트 안 `cd` 후 `cwd` | main: <…>, sub: <…> | F3 보완 |
| V4 `wait-output` | 기본: exit <…> / <…>s, `--lines 400`: exit <…> / <…>s | Task 5 W4 수정 방식 |
```

Fill every `<…>` with the observed value (this is a results table, not a template left for later).

```bash
git add docs/superpowers/specs/2026-10-04-herdr-delegation-routing-design.md
git commit -m "docs: record pre-implementation measurements for delegation routing"
```

---

### Task 1: Caller-aware creation rules (R1–R3) in `route.py`

**Done when:**
- Step 2 showed the new tests failing for the missing names (record the error line).
- `unittest discover` ends with `OK`; `ActorTest`, `CreationTest`, `MessageTest` all ran.
- `git diff --stat` touches only `route.py` and `tests/test_route.py`.
- Existing behaviour kept: `CreationTest.test_allowed_creation_lookalikes` passes (commit-message and grep look-alikes, `EnterWorktree` with `path`).

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/hooks/route.py` (whole file rewritten below)
- Create: `skills/herdr-parallel-worktree/tests/test_route.py`

**Interfaces:**
- Produces (used by Tasks 2–4):
  - `actor(event: dict, env: Mapping[str, str]) -> str` — one of `"main"`, `"sub"`, `"worker"`, `"worker-sub"`
  - `decide(event: dict, env: Mapping[str, str], probe=git_probe) -> dict | None` — the full hook output object, or `None` for no output
  - `git_probe(path: str) -> tuple[str, str, str] | None` — `(git_dir, git_common_dir, toplevel)`, absolute; `None` on any failure. In this task it is a stub returning `None`; Task 2 implements it.
  - Message constants `DENY_MAIN`, `DENY_SUB`, `NOTE_HANDOFF`, `HANDOFF` and function `deny_worker(name: str, home: str) -> str`
  - `main()` reads `sys.argv[1]` in `{"pre-tool-use", "post-tool-use"}`

- [ ] **Step 1: Write the failing tests**

Create `skills/herdr-parallel-worktree/tests/test_route.py`:

```python
"""Unit tests for scripts/hooks/route.py. Run from the repo root:
python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
ROUTE_PATH = os.path.join(SKILL_DIR, "scripts", "hooks", "route.py")

spec = importlib.util.spec_from_file_location("route", ROUTE_PATH)
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)

MAIN_ENV = {"HERDR_ENV": "1"}
WORKER_ENV = {"HERDR_ENV": "1", "HERDR_PW_WORKER": "w1"}

# A fake repository: main checkout /r, linked worktrees /w/a and /w/b, and /x outside git.
FAKE = {
    "/r": ("/r/.git", "/r/.git", "/r"),
    "/w/a": ("/r/.git/worktrees/a", "/r/.git", "/w/a"),
    "/w/b": ("/r/.git/worktrees/b", "/r/.git", "/w/b"),
}


def fake_probe(path):
    for top, info in FAKE.items():
        if path == top or path.startswith(top + "/"):
            return info
    return None


def event(tool, sub=False, cwd="/r", hook="PreToolUse", **tool_input):
    e = {"session_id": "s", "cwd": cwd, "permission_mode": "default", "prompt_id": "p",
         "hook_event_name": hook, "tool_name": tool, "tool_input": tool_input,
         "tool_use_id": "t", "transcript_path": "/tmp/t.jsonl"}
    if sub:
        e["agent_id"] = "a1"
        e["agent_type"] = "general-purpose"
    return e


def reason(out):
    assert out is not None, "expected a deny, got no output"
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    return hso["permissionDecisionReason"]


class ActorTest(unittest.TestCase):
    def test_four_actors(self):
        self.assertEqual(route.actor(event("Bash"), MAIN_ENV), "main")
        self.assertEqual(route.actor(event("Bash", sub=True), MAIN_ENV), "sub")
        self.assertEqual(route.actor(event("Bash"), WORKER_ENV), "worker")
        self.assertEqual(route.actor(event("Bash", sub=True), WORKER_ENV), "worker-sub")

    def test_empty_worker_var_is_not_a_worker(self):
        self.assertEqual(route.actor(event("Bash"), {"HERDR_ENV": "1", "HERDR_PW_WORKER": ""}), "main")


class CreationTest(unittest.TestCase):
    CASES = [
        ("Bash", {"command": "git worktree add ../fix -b fix/x"}),
        ("Bash", {"command": "cd /r && git -C /r worktree add /w/c"}),
        ("EnterWorktree", {}),
        ("Agent", {"prompt": "fix it", "subagent_type": "general-purpose", "isolation": "worktree"}),
        ("Task", {"prompt": "fix it", "isolation": "worktree"}),
    ]

    def decide(self, tool, args, sub, env):
        return route.decide(event(tool, sub=sub, **args), env, fake_probe)

    def test_main_is_sent_to_the_skill(self):
        for tool, args in self.CASES:
            with self.subTest(tool=tool, args=args):
                self.assertEqual(reason(self.decide(tool, args, False, MAIN_ENV)), route.DENY_MAIN)

    def test_sub_is_told_to_hand_off(self):
        for tool, args in self.CASES:
            with self.subTest(tool=tool, args=args):
                self.assertEqual(reason(self.decide(tool, args, True, MAIN_ENV)), route.DENY_SUB)

    def test_worker_is_told_to_do_it_itself(self):
        for tool, args in self.CASES:
            with self.subTest(tool=tool, args=args):
                r = reason(route.decide(event(tool, cwd="/w/a", **args), WORKER_ENV, fake_probe))
                self.assertEqual(r, route.deny_worker("w1", "/w/a"))

    def test_worker_sub_is_told_to_hand_off(self):
        for tool, args in self.CASES:
            with self.subTest(tool=tool, args=args):
                r = reason(route.decide(event(tool, sub=True, cwd="/w/a", **args), WORKER_ENV, fake_probe))
                self.assertEqual(r, route.DENY_SUB)

    def test_incident_command_from_the_saju_session(self):
        cmd = "git worktree add ../kb-skills-fix-normalize -b fix/normalize-alias"
        self.assertEqual(reason(route.decide(event("Bash", sub=True, command=cmd), MAIN_ENV, fake_probe)),
                         route.DENY_SUB)

    def test_allowed_creation_lookalikes(self):
        allowed = [
            ("Bash", {"command": 'git commit -m "explain git worktree add"'}),
            ("Bash", {"command": "grep -rn 'worktree add' docs"}),
            ("Bash", {"command": "git worktree list"}),
            ("EnterWorktree", {"path": "/w/a"}),
            ("Agent", {"prompt": "run git worktree add ../x", "subagent_type": "general-purpose"}),
        ]
        for tool, args in allowed:
            for sub in (False, True):
                with self.subTest(tool=tool, args=args, sub=sub):
                    self.assertIsNone(self.decide(tool, args, sub, MAIN_ENV))


class MessageTest(unittest.TestCase):
    def test_sub_message_carries_the_handoff_block(self):
        self.assertIn("\nHERDR-HANDOFF\n", "\n" + route.DENY_SUB + "\n")
        self.assertTrue(route.HANDOFF.startswith("HERDR-HANDOFF\nTo the main session:"))
        for field in ("name:", "repo:", "goal:", "branch:", "steps:", "done:"):
            self.assertIn("\n" + field, route.HANDOFF)

    def test_messages_never_suggest_bang_to_subagents(self):
        self.assertIn("Do not suggest", route.DENY_SUB)
        self.assertIn("Do not tell the user", route.NOTE_HANDOFF)

    def test_main_exception_is_limited_to_the_user_in_this_conversation(self):
        self.assertIn("the user, in this conversation, explicitly asked", route.DENY_MAIN)

    def test_worker_message_names_worker_and_home(self):
        m = route.deny_worker("w1", "/w/a")
        self.assertIn("`w1`", m)
        self.assertIn("/w/a", m)
        self.assertIn("HERDR-HANDOFF", m)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v`
Expected: ERROR/FAIL — `AttributeError: module 'route' has no attribute 'actor'` (and `decide`, `DENY_SUB`, …).

- [ ] **Step 3: Rewrite `route.py`**

Replace the whole file `skills/herdr-parallel-worktree/scripts/hooks/route.py` with:

```python
#!/usr/bin/env python3
"""Claude Code hooks that route worktree work to herdr-parallel-worktree inside herdr.

Usage (from a hooks config):
  route.py pre-tool-use    PreToolUse: deny creating a worktree outside the skill — `git worktree add`,
                           EnterWorktree without `path` (which creates one), worktree-isolated Agent calls.
                           For a subagent, also deny writing into a linked worktree other than the session's
                           own. The reason depends on who called: the main session is told to use the skill,
                           a subagent to stop and hand the task back as a HERDR-HANDOFF block, a herdr worker
                           to do the work itself.
  route.py post-tool-use   PostToolUse on Agent/Task in the main session: says what to do if that subagent
                           returns a HERDR-HANDOFF block.

Who called: HERDR_PW_WORKER (exported by the skill into each worker's pane) marks a herdr worker; `agent_id`
in the hook input marks a subagent.

It does nothing — no output, no tokens — outside herdr (HERDR_ENV != 1) or when the user turned the hooks off
("hooks": "off" in DATA_DIR/config.json). Any unexpected error also results in no output, so a broken hook
never blocks the user's work.
"""
import json
import os
import re
import sys

SKILL = "herdr-parallel-worktree"
WORKER_VAR = "HERDR_PW_WORKER"
HANDOFF = (
    "HERDR-HANDOFF\n"
    f"To the main session: load the {SKILL} skill and turn this into a worker, confirming with the user once "
    "(step 0). Do not tell the user to run it with `!` or to turn the hooks off.\n"
    "name: <suggested worker name>\n"
    "repo: <absolute path of the target repository>\n"
    "goal: <one line>\n"
    "branch: <suggested branch, or ->\n"
    "steps:\n"
    "- <step>\n"
    "done: <what was already done, or nothing>"
)
DENY_MAIN = (
    f"Inside herdr, worktree work goes through the {SKILL} skill, so the user can watch each worker in the "
    "herdr sidebar. Load that skill and follow it from step 0, which confirms the tasks with the user once. "
    "This holds even when the plan to use a plain worktree or a subagent came from you or from a subagent. "
    "Only if the user, in this conversation, explicitly asked for a plain git worktree: tell them this hook "
    "blocked it; they can run it themselves with `! <command>`, or turn the hooks off by asking to "
    f"\"turn off the {SKILL} hooks\"."
)
DENY_SUB = (
    "You are a subagent. Inside herdr, work that needs its own worktree runs as a herdr worker, and only the "
    "main session starts workers, after confirming with the user. Do not create the worktree or write into "
    "another worktree, and do not retry another way. Do not suggest running anything with `!` or turning the "
    "hooks off. Stop now and end your final reply with this block, filled in:\n\n" + HANDOFF
)
NOTE_HANDOFF = (
    f"If this subagent returns a HERDR-HANDOFF block, load the {SKILL} skill and continue from its step 0 "
    "with that block as one of the tasks. Do not tell the user to run anything with `!` or to turn the "
    "hooks off."
)


def deny_worker(name, home):
    return (f"You are the herdr worker `{name}`. Workers do not create worktrees or start workers. Do the work "
            f"yourself in your own worktree ({home}). If it really needs a separate worker, put this block, "
            "filled in, in your `## Result` and let the orchestrator decide:\n\n" + HANDOFF)


# `git [global options] worktree add` in command position (start, or after ; & | ( or $( ), optionally
# behind VAR=value assignments — not the phrase quoted inside a commit message or a grep pattern.
WORKTREE_ADD = re.compile(r"(?:^|[;&|(\n]|\$\()\s*(?:\w+=\S*\s+)*(?:command\s+)?git\b(?:\s+-\S+(?:\s+[^-\s]\S*)?)*\s+worktree\s+add\b")


def actor(event, env):
    worker = bool(env.get(WORKER_VAR))
    sub = bool(event.get("agent_id"))
    if worker:
        return "worker-sub" if sub else "worker"
    return "sub" if sub else "main"


def git_probe(path):
    return None   # Task 2


def deny(text):
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                   "permissionDecision": "deny",
                                   "permissionDecisionReason": text}}


def home_of(cwd, probe):
    found = probe(cwd)
    return found[2] if found else cwd


def creates_worktree(tool, args):
    return bool((tool == "Bash" and WORKTREE_ADD.search(args.get("command") or ""))
                or (tool == "EnterWorktree" and not args.get("path"))
                or (tool in ("Agent", "Task") and args.get("isolation") == "worktree"))   # Task: Agent's older name


def decide(event, env, probe=git_probe):
    hook, tool = event.get("hook_event_name"), event.get("tool_name")
    args = event.get("tool_input") or {}
    who = actor(event, env)
    cwd = event.get("cwd") or os.getcwd()
    if hook != "PreToolUse":
        return None
    if creates_worktree(tool, args):
        if who == "main":
            return deny(DENY_MAIN)
        if who == "worker":
            return deny(deny_worker(env[WORKER_VAR], home_of(cwd, probe)))
        return deny(DENY_SUB)
    return None


def enabled():
    if os.environ.get("HERDR_ENV") != "1":
        return False
    base = os.environ.get("HERDR_SKILLS_DATA_HOME") or os.path.expanduser("~/.local/share/herdr-skills")
    try:
        with open(os.path.join(base, SKILL, "config.json"), encoding="utf-8") as f:
            return json.load(f).get("hooks", "on") != "off"
    except (OSError, ValueError, AttributeError):
        return True   # no or unreadable config: the default is on


def main():
    try:
        if len(sys.argv) != 2 or sys.argv[1] not in ("pre-tool-use", "post-tool-use") or not enabled():
            return
        try:
            event = json.load(sys.stdin)
        except ValueError:
            return
        out = decide(event, os.environ)
        if out:
            print(json.dumps(out))
    except Exception:   # never block the user's work because of a hook bug
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v`
Expected: all tests in `ActorTest`, `CreationTest`, `MessageTest` PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/herdr-parallel-worktree/scripts/hooks/route.py skills/herdr-parallel-worktree/tests/test_route.py
git commit -m "feat: tell main, subagent and worker apart when blocking worktree creation"
```

---

### Task 2: Block subagent writes into another worktree (R4, R5)

**Done when:**
- Step 2 showed `OtherWorktreeTest`, `DirTargetsTest`, `WriteRuleTest`, `GitProbeTest` failing.
- `unittest discover` ends with `OK`, and `GitProbeTest` ran against a real linked worktree (not skipped).
- Every Review Focus item 1–5 has its named test passing.

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/hooks/route.py` (imports, `git_probe`, new helpers, `decide`)
- Modify: `skills/herdr-parallel-worktree/tests/test_route.py` (append classes)

**Interfaces:**
- Consumes: `actor`, `decide`, `deny`, `DENY_SUB`, `home_of` from Task 1
- Produces: `git_probe(path) -> tuple[str, str, str] | None` (real), `other_worktree(path: str, cwd: str, probe) -> str | None`, `dir_targets(command: str) -> list[str]`, `WRITE_TOOLS: dict[str, str]`

- [ ] **Step 1: Write the failing tests**

Append to `test_route.py` (before the `if __name__ == "__main__":` line):

```python
import subprocess
import tempfile
from unittest import mock


class OtherWorktreeTest(unittest.TestCase):
    def test_decisions(self):
        cases = [
            ("/w/b/f.py", "/r", "/w/b"),       # linked worktree, session in main checkout
            ("/w/b/f.py", "/w/a", "/w/b"),     # another worker's worktree
            ("/w/a/f.py", "/w/a", None),       # own worktree
            ("/w/a/sub/f.py", "/w/a/sub", None),
            ("/r/f.py", "/w/a", None),         # main checkout is not a linked worktree
            ("/x/f.py", "/r", None),           # not in git
        ]
        for path, cwd, expected in cases:
            with self.subTest(path=path, cwd=cwd):
                self.assertEqual(route.other_worktree(path, cwd, fake_probe), expected)

    def test_relative_path_resolves_against_cwd(self):
        self.assertEqual(route.other_worktree("../b/f.py", "/w/a", fake_probe), "/w/b")


class DirTargetsTest(unittest.TestCase):
    def test_reads_plain_and_quoted_targets(self):
        self.assertEqual(route.dir_targets("cd /w/b && make"), ["/w/b"])
        self.assertEqual(route.dir_targets("git -C /w/b commit -am x"), ["/w/b"])
        self.assertEqual(route.dir_targets("true; cd '/w/b' && git -C \"/w/a\" status"), ["/w/b", "/w/a"])

    def test_quoted_cd_target(self):
        self.assertEqual(route.dir_targets('cd "/p with spaces/wt" && ls'), ["/p with spaces/wt"])

    def test_variable_cd_target_ignored(self):
        for cmd in ("cd $WT && ls", 'cd "$WT"', "cd foo$bar", "cd $(git rev-parse --show-toplevel)",
                    "git -C `pwd` status"):
            with self.subTest(cmd=cmd):
                self.assertEqual(route.dir_targets(cmd), [])

    def test_cd_inside_commit_message_ignored(self):
        self.assertEqual(route.dir_targets('git commit -m "cd into the wt first"'), [])
        self.assertEqual(route.dir_targets("echo 'then git -C /w/b status'"), [])

    def test_home_shortcut_is_expanded(self):
        self.assertEqual(route.dir_targets("cd ~/w"), [os.path.expanduser("~/w")])


class WriteRuleTest(unittest.TestCase):
    def test_sub_write_into_other_worktree_is_denied(self):
        for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("MultiEdit", "file_path"),
                          ("NotebookEdit", "notebook_path")):
            with self.subTest(tool=tool):
                out = route.decide(event(tool, sub=True, **{key: "/w/b/f.py"}), MAIN_ENV, fake_probe)
                self.assertEqual(reason(out), route.DENY_SUB)

    def test_sub_bash_into_other_worktree_is_denied(self):
        out = route.decide(event("Bash", sub=True, command="cd /w/b && sed -i s/a/b/ f.py"), MAIN_ENV, fake_probe)
        self.assertEqual(reason(out), route.DENY_SUB)

    def test_allowed_writes(self):
        allowed = [
            (event("Write", sub=False, file_path="/w/b/f.py"), MAIN_ENV),                 # main may write anywhere
            (event("Write", sub=True, file_path="/r/f.py"), MAIN_ENV),                    # main checkout
            (event("Write", sub=True, file_path="/x/f.py"), MAIN_ENV),                    # outside git
            (event("Write", cwd="/w/a", file_path="/w/b/f.py"), WORKER_ENV),              # worker itself
            (event("Write", sub=True, cwd="/w/a", file_path="/w/a/f.py"), WORKER_ENV),    # worker-sub, own worktree
            (event("Bash", sub=True, command="cd $WT && make"), MAIN_ENV),                # unreadable target
            (event("Bash", sub=True, command="ls /w/b"), MAIN_ENV),                       # no cd / git -C
        ]
        for e, env in allowed:
            with self.subTest(e=e["tool_input"], env=env):
                self.assertIsNone(route.decide(e, env, fake_probe))

    def test_worker_sub_write_into_other_worktree_is_denied(self):
        out = route.decide(event("Edit", sub=True, cwd="/w/a", file_path="/w/b/f.py"), WORKER_ENV, fake_probe)
        self.assertEqual(reason(out), route.DENY_SUB)


class GitProbeTest(unittest.TestCase):
    """Real git: a main checkout and one linked worktree in a temp directory."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()            # on macOS this is under the /var -> /private/var symlink
        cls.repo = os.path.join(cls.tmp, "repo")
        cls.wt = os.path.join(cls.tmp, "wt")
        git = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]
        subprocess.run(["git", "init", "-q", cls.repo], check=True)
        subprocess.run(git + ["-C", cls.repo, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        subprocess.run(["git", "-C", cls.repo, "worktree", "add", "-q", cls.wt, "-b", "probe"], check=True)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["rm", "-rf", cls.tmp], check=False)

    def test_main_checkout_is_not_linked(self):
        git_dir, common, top = route.git_probe(os.path.join(self.repo, "f.py"))
        self.assertEqual(git_dir, common)
        self.assertEqual(top, os.path.realpath(self.repo))

    def test_linked_worktree(self):
        git_dir, common, top = route.git_probe(os.path.join(self.wt, "f.py"))
        self.assertNotEqual(git_dir, common)
        self.assertEqual(top, os.path.realpath(self.wt))

    def test_symlinked_path_is_resolved(self):
        cwd = os.path.realpath(self.repo)
        self.assertEqual(route.other_worktree(os.path.join(self.wt, "f.py"), cwd, route.git_probe),
                         os.path.realpath(self.wt))
        self.assertIsNone(route.other_worktree(os.path.join(self.wt, "f.py"), os.path.realpath(self.wt),
                                               route.git_probe))

    def test_new_file_in_missing_dir_of_other_worktree(self):
        path = os.path.join(self.wt, "new", "deeper", "f.py")
        self.assertEqual(route.other_worktree(path, self.repo, route.git_probe), os.path.realpath(self.wt))

    def test_outside_git_is_none(self):
        self.assertIsNone(route.git_probe(os.path.join(self.tmp, "f.py")))

    def test_git_timeout_allows(self):
        with mock.patch.object(route.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 2)):
            self.assertIsNone(route.git_probe(self.wt))
            out = route.decide(event("Write", sub=True, cwd=self.repo, file_path=os.path.join(self.wt, "f")),
                               MAIN_ENV)
            self.assertIsNone(out)

    def test_missing_git_allows(self):
        with mock.patch.object(route.subprocess, "run", side_effect=FileNotFoundError("git")):
            self.assertIsNone(route.git_probe(self.wt))
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v`
Expected: FAIL/ERROR — `AttributeError: module 'route' has no attribute 'other_worktree'` / `'dir_targets'`; `GitProbeTest` fails because `git_probe` returns `None`; `route.subprocess` missing.

- [ ] **Step 3: Implement**

In `route.py`, change the imports to:

```python
import json
import os
import re
import subprocess
import sys
```

Add below `WORKTREE_ADD`:

```python
# `git -C <dir>` anywhere, or `cd <dir>` in command position. <dir> must be a plain word or a simply quoted
# one with no variables or substitutions; anything this cannot read for certain is left alone.
DIR_ARG = re.compile(r"""(?:\bgit\s+-C|(?:^|[;&|(\n])\s*cd)\s+("[^"$`\\]*"|'[^']*'|[^\s;&|()<>$`'"\\]+)(?=[\s;&|)]|$)""")
WRITE_TOOLS = {"Write": "file_path", "Edit": "file_path", "MultiEdit": "file_path", "NotebookEdit": "notebook_path"}
QUOTED = re.compile(r"""("[^"]*"|'[^']*')""")
```

Replace the stub `git_probe` with:

```python
def git_probe(path):
    """(git_dir, git_common_dir, toplevel) of the checkout holding `path`, all absolute; None if unknown."""
    d = path
    while not os.path.isdir(d):   # a file, or a directory that does not exist yet
        parent = os.path.dirname(d)
        if parent == d:
            return None
        d = parent
    try:
        r = subprocess.run(["git", "-C", d, "rev-parse", "--path-format=absolute",
                            "--git-dir", "--git-common-dir", "--show-toplevel"],
                           capture_output=True, text=True, timeout=2)
    except (OSError, subprocess.SubprocessError):
        return None
    lines = r.stdout.splitlines()
    if r.returncode != 0 or len(lines) != 3:
        return None
    return lines[0], lines[1], lines[2]


def other_worktree(path, cwd, probe):
    """Toplevel of the linked worktree holding `path`, unless it is the session's own (cwd's); else None."""
    path = os.path.normpath(os.path.join(cwd, os.path.expanduser(path)))
    found = probe(path)
    if not found or found[0] == found[1]:   # unknown, or the main checkout
        return None
    home = probe(cwd)
    if home and home[2] == found[2]:
        return None
    return found[2]


def dir_targets(command):
    """Directories that `cd <dir>` or `git -C <dir>` in `command` act on, when they can be read for certain."""
    # Blank out quoted arguments that are not themselves a cd / git -C target, so a commit message or an
    # echo that mentions "cd …" is not read as a command.
    out = []
    for m in DIR_ARG.finditer(command):
        start = m.start()
        if any(q.start() < start < q.end() for q in QUOTED.finditer(command)):
            continue
        token = m.group(1)
        if token[:1] in "\"'":
            token = token[1:-1]
        if token and token != "-":
            out.append(os.path.expanduser(token))
    return out
```

In `decide`, replace the final `return None` (after the `creates_worktree` block) with:

```python
    if who in ("sub", "worker-sub"):
        if tool in WRITE_TOOLS:
            targets = [args.get(WRITE_TOOLS[tool]) or ""]
        elif tool == "Bash":
            targets = dir_targets(args.get("command") or "")
        else:
            targets = []
        if any(t and other_worktree(t, cwd, probe) for t in targets):
            return deny(DENY_SUB)
    return None
```

Note on `dir_targets`: a match is skipped when it starts inside a quoted span. For `cd '/w/b'` the match starts at `cd`, which is outside the quotes, so the quoted target is still read. For `git commit -m "cd into …"` the `cd` sits inside the double-quoted span and is skipped. `DIR_ARG` also requires `cd` in command position, and after a `"` it is not, so both checks agree; the quoted-span check is what protects `echo 'then git -C /w/b status'`, where `git -C` has no command-position requirement.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v`
Expected: all tests PASS, including `GitProbeTest` (it creates a real linked worktree with `git worktree add` from Python; the Claude Code hook only inspects Bash tool commands, and `python3 -m unittest …` does not contain `worktree add`, so it is not blocked).

- [ ] **Step 5: Commit**

```bash
git add skills/herdr-parallel-worktree/scripts/hooks/route.py skills/herdr-parallel-worktree/tests/test_route.py
git commit -m "feat: stop subagents from writing into another worktree and hand the task back"
```

---

### Task 3: PostToolUse note and the process entry point (R6)

**Done when:**
- `SpecMatrixTest.test_every_cell` passes all 24 subtests, and its `TABLE` matches the spec §5.3 table row by row (a mismatch means one of them is wrong — stop and ask which).
- `EntryPointTest` passes: the real `route.py` process is silent outside herdr, with `hooks: off`, on bad input and on an unknown argument, and always exits 0.
- `unittest discover` ends with `OK`.

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/hooks/route.py` (`decide`)
- Modify: `skills/herdr-parallel-worktree/tests/test_route.py` (append classes)

**Interfaces:**
- Consumes: `decide`, `actor`, `NOTE_HANDOFF`, `main` from Tasks 1–2
- Produces: `decide` returns `{"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": NOTE_HANDOFF}}` for a main-session Agent/Task PostToolUse event

- [ ] **Step 1: Write the failing tests**

Append to `test_route.py` (before `if __name__ == "__main__":`):

```python
import json as _json
import sys as _sys


class PostToolUseTest(unittest.TestCase):
    # Shape measured on Claude Code 2.1.289: PostToolUse(Agent) fires at launch with an async status.
    RESPONSE = {"isAsync": True, "status": "async_launched", "agentId": "a17c", "description": "probe"}

    def post(self, tool="Agent", sub=False):
        e = event(tool, sub=sub, hook="PostToolUse", prompt="x", subagent_type="general-purpose")
        e["tool_response"] = self.RESPONSE
        return e

    def test_main_gets_the_note(self):
        for tool in ("Agent", "Task"):
            with self.subTest(tool=tool):
                out = route.decide(self.post(tool), MAIN_ENV, fake_probe)
                self.assertEqual(out, {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                              "additionalContext": route.NOTE_HANDOFF}})

    def test_no_note_for_sub_worker_or_other_tools(self):
        self.assertIsNone(route.decide(self.post(sub=True), MAIN_ENV, fake_probe))
        self.assertIsNone(route.decide(self.post(), WORKER_ENV, fake_probe))
        e = event("Bash", hook="PostToolUse", command="ls")
        self.assertIsNone(route.decide(e, MAIN_ENV, fake_probe))


class EntryPointTest(unittest.TestCase):
    """Run route.py as Claude Code does: JSON on stdin, decision on stdout, always exit 0."""

    def run_route(self, arg, payload, env_extra, data_home):
        env = {k: v for k, v in os.environ.items() if k not in ("HERDR_ENV", "HERDR_PW_WORKER")}
        env.update(env_extra)
        env["HERDR_SKILLS_DATA_HOME"] = data_home
        r = subprocess.run([_sys.executable, ROUTE_PATH, arg], input=payload, capture_output=True,
                           text=True, env=env, timeout=10)
        self.assertEqual(r.returncode, 0)
        return r.stdout

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.payload = _json.dumps(event("Bash", command="git worktree add ../x"))

    def tearDown(self):
        subprocess.run(["rm", "-rf", self.data], check=False)

    def test_denies_inside_herdr(self):
        out = self.run_route("pre-tool-use", self.payload, {"HERDR_ENV": "1"}, self.data)
        self.assertEqual(_json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_silent_outside_herdr(self):
        self.assertEqual(self.run_route("pre-tool-use", self.payload, {}, self.data), "")

    def test_silent_when_hooks_off(self):
        os.makedirs(os.path.join(self.data, "herdr-parallel-worktree"))
        with open(os.path.join(self.data, "herdr-parallel-worktree", "config.json"), "w") as f:
            f.write('{"hooks": "off"}')
        self.assertEqual(self.run_route("pre-tool-use", self.payload, {"HERDR_ENV": "1"}, self.data), "")

    def test_silent_on_bad_input_or_argument(self):
        self.assertEqual(self.run_route("pre-tool-use", "not json", {"HERDR_ENV": "1"}, self.data), "")
        self.assertEqual(self.run_route("bogus", self.payload, {"HERDR_ENV": "1"}, self.data), "")
        self.assertEqual(self.run_route("pre-tool-use", "[]", {"HERDR_ENV": "1"}, self.data), "")

    def test_post_tool_use_note(self):
        payload = _json.dumps(event("Agent", hook="PostToolUse", prompt="x"))
        out = self.run_route("post-tool-use", payload, {"HERDR_ENV": "1"}, self.data)
        self.assertEqual(_json.loads(out)["hookSpecificOutput"]["additionalContext"], route.NOTE_HANDOFF)


class SpecMatrixTest(unittest.TestCase):
    """Spec §5.3, cell by cell: every rule R1–R6 for every caller. Keep this table identical to the spec's."""
    RULES = {
        "R1": lambda sub, cwd: event("Bash", sub=sub, cwd=cwd, command="git worktree add ../x -b x"),
        "R2": lambda sub, cwd: event("EnterWorktree", sub=sub, cwd=cwd),
        "R3": lambda sub, cwd: event("Agent", sub=sub, cwd=cwd, prompt="p", isolation="worktree"),
        "R4": lambda sub, cwd: event("Write", sub=sub, cwd=cwd, file_path="/w/b/f.py"),
        "R5": lambda sub, cwd: event("Bash", sub=sub, cwd=cwd, command="cd /w/b && make"),
        "R6": lambda sub, cwd: event("Agent", sub=sub, cwd=cwd, hook="PostToolUse", prompt="p"),
    }
    ACTORS = {"main": (False, "/r", MAIN_ENV), "sub": (True, "/r", MAIN_ENV),
              "worker": (False, "/w/a", WORKER_ENV), "worker-sub": (True, "/w/a", WORKER_ENV)}
    #          main     sub    worker    worker-sub
    TABLE = {
        "R1": ("MAIN", "SUB", "WORKER", "SUB"),
        "R2": ("MAIN", "SUB", "WORKER", "SUB"),
        "R3": ("MAIN", "SUB", "WORKER", "SUB"),
        "R4": (None, "SUB", None, "SUB"),
        "R5": (None, "SUB", None, "SUB"),
        "R6": ("NOTE", None, None, None),
    }

    @staticmethod
    def outcome(out):
        if out is None:
            return None
        hso = out["hookSpecificOutput"]
        if hso.get("additionalContext") == route.NOTE_HANDOFF:
            return "NOTE"
        return {route.DENY_MAIN: "MAIN", route.DENY_SUB: "SUB",
                route.deny_worker("w1", "/w/a"): "WORKER"}.get(hso.get("permissionDecisionReason"), "OTHER")

    def test_every_cell(self):
        for rule, expected in self.TABLE.items():
            for (who, (sub, cwd, env)), want in zip(self.ACTORS.items(), expected):
                with self.subTest(rule=rule, caller=who):
                    got = self.outcome(route.decide(self.RULES[rule](sub, cwd), env, fake_probe))
                    self.assertEqual(got, want)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v`
Expected: `PostToolUseTest.test_main_gets_the_note`, `EntryPointTest.test_post_tool_use_note` and the `R6/main` subtest of `SpecMatrixTest.test_every_cell` FAIL (no output for PostToolUse); every other `SpecMatrixTest` cell already passes. `test_silent_on_bad_input_or_argument` with `"[]"` may already pass because `main()` catches the `AttributeError`; keep it as a regression guard.

- [ ] **Step 3: Implement**

In `decide`, replace

```python
    if hook != "PreToolUse":
        return None
```

with

```python
    if hook == "PostToolUse":
        if tool in ("Agent", "Task") and who == "main":
            return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": NOTE_HANDOFF}}
        return None
    if hook != "PreToolUse":
        return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v`
Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/herdr-parallel-worktree/scripts/hooks/route.py skills/herdr-parallel-worktree/tests/test_route.py
git commit -m "feat: tell the main session how to take over a subagent's handoff"
```

---

### Task 4: Register the hooks (plugin and standalone) with a shell guard

**Done when:**
- `RegistrationTest` passes (plugin and standalone sets identical, every command guarded, `strip_ours` finds every group).
- The guard check in Step 4 prints `outside exit=0` with no output, then a deny JSON and `inside exit=0`.
- `hook_cost.py` prints three PASS lines (Step 6).
- `live_hooks.py` ends with `summary: 11 pass, 0 fail, 0 inconclusive` (Step 7), after at most one rerun.

**Files:**
- Modify: `hooks/hooks.json` (whole file)
- Modify: `skills/herdr-parallel-worktree/scripts/hooks/manage.py` (`hook_entries`, module docstring line 1)
- Create: `skills/herdr-parallel-worktree/tests/test_registration.py`
- Create: `skills/herdr-parallel-worktree/tests/hook_cost.py` (L2c)
- Create: `skills/herdr-parallel-worktree/tests/live_hooks.py` (L2)

**Interfaces:**
- Consumes: `route.py` arguments `pre-tool-use` / `post-tool-use` (Tasks 1, 3); Task 0 V2 result for the `if` patterns
- Produces: `manage.hook_entries(skill_dir: str) -> dict[str, list[dict]]` with keys `"PreToolUse"` and `"PostToolUse"`

If Task 0 V2 showed that one of `Bash(*git -C *)`, `Bash(cd *)`, `Bash(* cd *)` never fires, remove the `"if"` key from that one group in both files and in the test's expectation; keep everything else as written.

- [ ] **Step 1: Write the failing test**

Create `skills/herdr-parallel-worktree/tests/test_registration.py`:

```python
"""hooks/hooks.json (plugin installs) and manage.py hook_entries() (other installs) must register the same hooks."""
import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SKILL_DIR))

spec = importlib.util.spec_from_file_location("manage", os.path.join(SKILL_DIR, "scripts", "hooks", "manage.py"))
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)

PLUGIN_ROUTE = '"${CLAUDE_PLUGIN_ROOT}/skills/herdr-parallel-worktree/scripts/hooks/route.py"'
GUARD = '[ "$HERDR_ENV" = 1 ] || exit 0; '


def normalise(hooks, route_ref):
    return json.loads(json.dumps(hooks).replace(json.dumps(route_ref)[1:-1], "ROUTE"))


class RegistrationTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(REPO, "hooks", "hooks.json"), encoding="utf-8") as f:
            self.plugin = json.load(f)["hooks"]
        self.standalone = manage.hook_entries("/SKILL")

    def test_same_set(self):
        self.assertEqual(normalise(self.plugin, PLUGIN_ROUTE),
                         normalise(self.standalone, '"/SKILL/scripts/hooks/route.py"'))

    def test_every_command_is_guarded_and_names_its_event(self):
        for event, groups in self.plugin.items():
            arg = {"PreToolUse": "pre-tool-use", "PostToolUse": "post-tool-use"}[event]
            for g in groups:
                for h in g["hooks"]:
                    with self.subTest(event=event, matcher=g["matcher"], cmd=h["command"]):
                        self.assertTrue(h["command"].startswith(GUARD))
                        self.assertTrue(h["command"].endswith(" " + arg))

    def test_expected_matchers(self):
        pre = [(g["matcher"], g["hooks"][0].get("if")) for g in self.plugin["PreToolUse"]]
        self.assertEqual(pre, [
            ("Bash", "Bash(*worktree add*)"),
            ("Bash", "Bash(*git -C *)"),
            ("Bash", "Bash(cd *)"),
            ("Bash", "Bash(* cd *)"),
            ("EnterWorktree|Agent|Task", None),
            ("Write|Edit|MultiEdit|NotebookEdit", None),
        ])
        self.assertEqual([g["matcher"] for g in self.plugin["PostToolUse"]], ["Agent|Task"])

    def test_manage_marker_still_finds_every_group(self):
        # strip_ours() finds our groups by MARK ("herdr-parallel-worktree/scripts/hooks/route.py"), so use a
        # skill directory shaped like a real install.
        entries = manage.hook_entries("/home/u/.claude/skills/herdr-parallel-worktree")
        groups = [g for gs in entries.values() for g in gs]
        settings = {"hooks": json.loads(json.dumps(entries))}
        self.assertEqual(manage.strip_ours(settings), len(groups))
        self.assertNotIn("hooks", settings)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v`
Expected: `RegistrationTest` FAILs (no guard, missing groups, no `PostToolUse`).

- [ ] **Step 3: Implement**

Replace `hooks/hooks.json` with:

```json
{
  "hooks": {
    "PreToolUse": [
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "if": "Bash(*worktree add*)",
            "command": "[ \"$HERDR_ENV\" = 1 ] || exit 0; python3 \"${CLAUDE_PLUGIN_ROOT}/skills/herdr-parallel-worktree/scripts/hooks/route.py\" pre-tool-use"
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "if": "Bash(*git -C *)",
            "command": "[ \"$HERDR_ENV\" = 1 ] || exit 0; python3 \"${CLAUDE_PLUGIN_ROOT}/skills/herdr-parallel-worktree/scripts/hooks/route.py\" pre-tool-use"
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "if": "Bash(cd *)",
            "command": "[ \"$HERDR_ENV\" = 1 ] || exit 0; python3 \"${CLAUDE_PLUGIN_ROOT}/skills/herdr-parallel-worktree/scripts/hooks/route.py\" pre-tool-use"
          }
        ]
      },
      {
        "matcher": "Bash",
        "hooks": [
          {
            "type": "command",
            "if": "Bash(* cd *)",
            "command": "[ \"$HERDR_ENV\" = 1 ] || exit 0; python3 \"${CLAUDE_PLUGIN_ROOT}/skills/herdr-parallel-worktree/scripts/hooks/route.py\" pre-tool-use"
          }
        ]
      },
      {
        "matcher": "EnterWorktree|Agent|Task",
        "hooks": [
          {
            "type": "command",
            "command": "[ \"$HERDR_ENV\" = 1 ] || exit 0; python3 \"${CLAUDE_PLUGIN_ROOT}/skills/herdr-parallel-worktree/scripts/hooks/route.py\" pre-tool-use"
          }
        ]
      },
      {
        "matcher": "Write|Edit|MultiEdit|NotebookEdit",
        "hooks": [
          {
            "type": "command",
            "command": "[ \"$HERDR_ENV\" = 1 ] || exit 0; python3 \"${CLAUDE_PLUGIN_ROOT}/skills/herdr-parallel-worktree/scripts/hooks/route.py\" pre-tool-use"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": "Agent|Task",
        "hooks": [
          {
            "type": "command",
            "command": "[ \"$HERDR_ENV\" = 1 ] || exit 0; python3 \"${CLAUDE_PLUGIN_ROOT}/skills/herdr-parallel-worktree/scripts/hooks/route.py\" post-tool-use"
          }
        ]
      }
    ]
  }
}
```

In `manage.py`, change the docstring's first line to:

```python
"""Turn herdr-parallel-worktree's routing hooks (PreToolUse, PostToolUse) on or off, or remove them.
```

and replace `hook_entries` with:

```python
GUARD = '[ "$HERDR_ENV" = 1 ] || exit 0; '   # outside herdr, never start python


def hook_entries(skill_dir):
    route = f'python3 "{os.path.join(skill_dir, "scripts", "hooks", "route.py")}"'
    pre = {"type": "command", "command": f"{GUARD}{route} pre-tool-use"}
    post = {"type": "command", "command": f"{GUARD}{route} post-tool-use"}

    def bash(rule):
        return {"matcher": "Bash", "hooks": [{**pre, "if": rule}]}

    return {
        "PreToolUse": [
            bash("Bash(*worktree add*)"),
            bash("Bash(*git -C *)"),
            bash("Bash(cd *)"),
            bash("Bash(* cd *)"),
            {"matcher": "EnterWorktree|Agent|Task", "hooks": [dict(pre)]},
            {"matcher": "Write|Edit|MultiEdit|NotebookEdit", "hooks": [dict(pre)]},
        ],
        "PostToolUse": [
            {"matcher": "Agent|Task", "hooks": [dict(post)]},
        ],
    }
```

Key order inside each hook object differs between the two files (`"if"` before `"command"` in JSON, after it in Python); the test compares parsed dicts, so order does not matter.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v`
Expected: all tests PASS.

Then check the guard end to end (outside herdr nothing runs, inside it does):

```bash
CMD="$(jq -r '.hooks.PreToolUse[0].hooks[0].command' hooks/hooks.json | sed "s#\${CLAUDE_PLUGIN_ROOT}#$PWD#")"
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git worktree add ../x"},"cwd":"/tmp"}' | env -u HERDR_ENV sh -c "$CMD"; echo "outside exit=$?"
echo '{"hook_event_name":"PreToolUse","tool_name":"Bash","tool_input":{"command":"git worktree add ../x"},"cwd":"/tmp"}' | HERDR_ENV=1 sh -c "$CMD"; echo "inside exit=$?"
```

Expected: `outside exit=0` with no output; then a deny JSON and `inside exit=0`.

- [ ] **Step 6: L2c — measure the hook cost**

Create `skills/herdr-parallel-worktree/tests/hook_cost.py`:

```python
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
```

Run: `python3 skills/herdr-parallel-worktree/tests/hook_cost.py`
Expected: three `PASS` lines. Medians measured while writing this plan: 7.7 / 41 / 56 ms. A FAIL on the outside line means the guard is missing or broken; on the inside lines, report the numbers.

- [ ] **Step 7: L2 — live hooks with a real Claude Code**

Create `skills/herdr-parallel-worktree/tests/live_hooks.py`:

```python
#!/usr/bin/env python3
"""Live check of the routing hooks with a real Claude Code (verification layer L2).

Builds a throwaway repository with one linked worktree, registers this skill's hooks through `--settings`
(generated by manage.hook_entries, each command teed into a log so every decision is recorded), and runs
`claude -p` four times. HERDR_ENV=1 is faked for the claude process only, and the Skill tool is disallowed,
so nothing reaches a real herdr. Prints PASS / FAIL / INCONCLUSIVE per check; exits 1 on any FAIL.
INCONCLUSIVE means the model never attempted the action under test: rerun once before treating it as a FAIL.

Usage (repo root): python3 skills/herdr-parallel-worktree/tests/live_hooks.py [--model sonnet] [--keep]
"""
import argparse
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)


def load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(SKILL_DIR, "scripts", "hooks", f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


route, manage = load("route"), load("manage")
results = []


def check(cid, desc, status, detail=""):
    results.append(status)
    print(f"{status:12} {cid} {desc}" + (f"  — {detail}" if detail and status != "PASS" else ""))


def git(*args):
    subprocess.run(["git", "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
                   check=True, capture_output=True)


def write_settings(path, log):
    entries = manage.hook_entries(SKILL_DIR)
    for groups in entries.values():
        for g in groups:
            for h in g["hooks"]:
                h["command"] += f' | tee -a "{log}"'
    with open(path, "w") as f:
        json.dump({"hooks": entries}, f)


def claude(cwd, prompt, settings, model, env_extra):
    env = {k: v for k, v in os.environ.items() if k not in ("HERDR_ENV", "HERDR_PW_WORKER")}
    env.update(env_extra)
    r = subprocess.run(["claude", "-p", "--settings", settings, "--permission-mode", "bypassPermissions",
                        "--model", model, "--disallowedTools=Skill", prompt],   # =: the option takes many values
                       cwd=cwd, env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True, timeout=900)
    if r.returncode != 0 or not r.stdout.strip():
        print(f"  claude exit={r.returncode} stderr={r.stderr.strip()[-300:]!r}")
    return r.stdout


def decisions(log):
    out = []
    if os.path.exists(log):
        for line in open(log):
            line = line.strip()
            if line:
                out.append(json.loads(line)["hookSpecificOutput"])
    return out


def denied_with(log, text):
    return any(d.get("permissionDecisionReason") == text for d in decisions(log))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sonnet")
    ap.add_argument("--keep", action="store_true", help="keep the temp directory for inspection")
    a = ap.parse_args()

    tmp = os.path.realpath(tempfile.mkdtemp(prefix="herdr-live-"))
    repo, wt = os.path.join(tmp, "repo"), os.path.join(tmp, "wt")
    data = os.path.join(tmp, "data")
    git("init", "-q", repo)
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write("live\n")
    git("-C", repo, "add", "README.md")
    git("-C", repo, "commit", "-q", "-m", "init")
    git("-C", repo, "worktree", "add", "-q", wt, "-b", "probe")
    herdr = {"HERDR_ENV": "1", "HERDR_SKILLS_DATA_HOME": data}
    print(f"temp: {tmp}")

    # Run 1 — a subagent tries to create a worktree: DENY_SUB, a filled handoff, and the main-session note.
    log1, set1 = os.path.join(tmp, "run1.log"), os.path.join(tmp, "run1.json")
    write_settings(set1, log1)
    new_wt = os.path.join(tmp, "new-wt")
    out1 = claude(repo, (
        "This is a hook test. Call the Agent tool exactly once (subagent_type general-purpose, description 'fix') "
        f"with this prompt: 'Run this Bash command exactly: `git -C {repo} worktree add {new_wt} -b fix/live`. "
        "Then add a line to README.md there and commit.' Wait for it to finish. Then reply with the subagent's "
        "final message verbatim and nothing else. Do not run any command yourself."), set1, a.model, herdr)
    attempted = bool(decisions(log1)) or os.path.exists(new_wt)
    if denied_with(log1, route.DENY_SUB):
        check("C1", "subagent worktree creation denied with DENY_SUB", "PASS")
    else:
        check("C1", "subagent worktree creation denied with DENY_SUB", "FAIL" if attempted else "INCONCLUSIVE",
              f"decisions={decisions(log1)}")
    check("C2", "worktree was not created", "FAIL" if os.path.exists(new_wt) else "PASS")
    notes = [d for d in decisions(log1) if d.get("additionalContext") == route.NOTE_HANDOFF]
    check("C3", "main session got NOTE_HANDOFF after starting the subagent", "PASS" if notes else "FAIL")
    filled = "HERDR-HANDOFF" in out1 and "repo:" in out1 and "<absolute path" not in out1
    check("C4", "subagent returned a filled HERDR-HANDOFF block",
          "PASS" if filled else ("FAIL" if denied_with(log1, route.DENY_SUB) else "INCONCLUSIVE"),
          "" if filled else f"reply={out1[-400:]!r}")

    # Run 2 — subagent writes into the linked worktree (denied) and the main checkout (allowed);
    # the main session writes into the linked worktree (allowed).
    log2, set2 = os.path.join(tmp, "run2.log"), os.path.join(tmp, "run2.json")
    write_settings(set2, log2)
    sub_wt, sub_main, main_wt = (os.path.join(wt, "from-sub.txt"), os.path.join(repo, "from-sub-main.txt"),
                                 os.path.join(wt, "from-main.txt"))
    claude(repo, (
        f"This is a hook test. First use the Write tool yourself to create {main_wt} containing hi. "
        "Then call the Agent tool exactly once (subagent_type general-purpose, description 'write') with this "
        f"prompt: 'Use the Write tool to create {sub_main} containing hi. Then use the Write tool to create "
        f"{sub_wt} containing hi. Report exactly what each tool returned.' Wait for it, then reply done."),
        set2, a.model, herdr)
    check("C5", "subagent write into another worktree denied",
          "PASS" if denied_with(log2, route.DENY_SUB) and not os.path.exists(sub_wt)
          else "FAIL" if os.path.exists(sub_wt) else "INCONCLUSIVE")
    check("C6", "subagent write into the main checkout allowed",
          "PASS" if os.path.exists(sub_main) else "INCONCLUSIVE")
    check("C7", "main session write into a worktree allowed", "PASS" if os.path.exists(main_wt) else "FAIL")

    # Run 3 — a herdr worker (HERDR_PW_WORKER set, session in its worktree) tries to create a worktree.
    log3, set3 = os.path.join(tmp, "run3.log"), os.path.join(tmp, "run3.json")
    write_settings(set3, log3)
    nested = os.path.join(tmp, "nested")
    claude(wt, (f"This is a hook test. Run this Bash command exactly: `git -C {wt} worktree add {nested} -b nested`. "
                "Then reply with the exact error text you got, and do not retry."),
           set3, a.model, dict(herdr, HERDR_PW_WORKER="w1"))
    expected = route.deny_worker("w1", route.git_probe(wt)[2])
    check("C8", "worker worktree creation denied with DENY_WORKER naming w1 and its worktree",
          "PASS" if denied_with(log3, expected) else ("FAIL" if decisions(log3) or os.path.exists(nested)
                                                      else "INCONCLUSIVE"), f"decisions={decisions(log3)}")
    check("C9", "nested worktree was not created", "FAIL" if os.path.exists(nested) else "PASS")

    # Run 4 — outside herdr: the hooks must stay silent and the command must go through.
    log4, set4 = os.path.join(tmp, "run4.log"), os.path.join(tmp, "run4.json")
    write_settings(set4, log4)
    outside = os.path.join(tmp, "outside")
    claude(repo, f"This is a hook test. Run this Bash command exactly: `git -C {repo} worktree add {outside} -b outside`. "
                 "Then reply done.", set4, a.model, {"HERDR_SKILLS_DATA_HOME": data})
    check("C10", "outside herdr: no hook output", "PASS" if not decisions(log4) else "FAIL", f"{decisions(log4)}")
    check("C11", "outside herdr: worktree created", "PASS" if os.path.exists(outside) else "INCONCLUSIVE")

    if a.keep:
        print(f"kept: {tmp}")
    else:
        shutil.rmtree(tmp, ignore_errors=True)
    print(f"summary: {results.count('PASS')} pass, {results.count('FAIL')} fail, "
          f"{results.count('INCONCLUSIVE')} inconclusive")
    sys.exit(1 if "FAIL" in results else 0)


if __name__ == "__main__":
    main()
```

Run: `python3 skills/herdr-parallel-worktree/tests/live_hooks.py`
Expected: `summary: 11 pass, 0 fail, 0 inconclusive`. The script creates its fixture worktree from Python; the Claude Code hook inspects Bash tool commands only, and `python3 …/live_hooks.py` contains no `worktree add`. Two lessons already paid for while writing it: `--disallowedTools=Skill` must use `=` (the option takes many values and otherwise swallows the prompt), and commands in prompts are wrapped in backticks (a trailing ` .` was once run as part of the command).

- [ ] **Step 8: Commit**

```bash
git add hooks/hooks.json skills/herdr-parallel-worktree/scripts/hooks/manage.py skills/herdr-parallel-worktree/tests/test_registration.py skills/herdr-parallel-worktree/tests/hook_cost.py skills/herdr-parallel-worktree/tests/live_hooks.py
git commit -m "feat: register write, cd and handoff hooks behind a herdr-only shell guard"
```

---

### Task 5: Skill instructions — worker marker, handoff, W4

**Done when:**
- Step 0 has the user's answer about the pending changes.
- `live_skill.py` before the edits: S2 and S3 not PASS (recorded). After the edits: `summary: 4 pass, 0 fail, 0 inconclusive` (S1a, S1b, S2, S3), after at most one rerun.
- Step 7 greps show every expected location; `unittest discover` still `OK`.

**Files:**
- Modify: `skills/herdr-parallel-worktree/SKILL.md` (Hooks section, §0, §3, Never)
- Modify: `skills/herdr-parallel-worktree/references/resume.md:54`
- Create: `skills/herdr-parallel-worktree/tests/live_skill.py` (L3)

**Interfaces:**
- Consumes: `HERDR_PW_WORKER` (read by `route.actor`), the `HERDR-HANDOFF` block format (`route.HANDOFF`), Task 0 V4 result
- Produces: documentation only

- [ ] **Step 0: Resolve the user's pending changes**

`SKILL.md` has uncommitted edits made before this plan. Stop and ask the user: commit them first (their message), or include them in this task's commit. Do not continue until they answer.

- [ ] **Step 0b: L3 red run — the unedited skill must not pass S2 and S3**

The installed skill is a symlink to this working tree, so `claude -p` uses whatever SKILL.md is on disk. Create `skills/herdr-parallel-worktree/tests/live_skill.py`:

```python
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
```

Run: `python3 skills/herdr-parallel-worktree/tests/live_skill.py`
Expected now (before Steps 1–6): S1a PASS, S1b PASS, **S2 FAIL or INCONCLUSIVE, S3 FAIL** — the old skill has no worker guard and still offers `! git worktree add`. Record the output. If S2 or S3 already PASS, the check cannot tell old from new: stop and report instead of continuing.

- [ ] **Step 1: Hooks section**

Replace the bullet that starts with `- **PreToolUse**: when Claude is about to create a worktree some other way` (the whole bullet, up to `…from even starting on other commands.`) with:

```markdown
- **Who is calling** decides the answer. A subagent's tool calls carry an `agent_id`; a herdr worker started by this skill has `HERDR_PW_WORKER=<name>` in its environment (step 3 exports it). Everything else is the main session.
- **Creating a worktree some other way** — `git worktree add`, `EnterWorktree` without `path`, or an `Agent` with worktree isolation — is denied. The main session is told to use this skill. A subagent is told to stop and return a `HERDR-HANDOFF` block (below). A worker is told to do the work in its own worktree. `EnterWorktree` with `path` only enters an existing worktree (for example, to inspect a worker's worktree) and is allowed.
- **A subagent writing into another linked worktree** — `Write`/`Edit`/`MultiEdit`/`NotebookEdit` on a file there, or `cd <dir>` / `git -C <dir>` into it — is denied the same way. Its own session's worktree, the main checkout and paths outside git are not affected. The main session itself is never blocked from writing.
- **After the main session starts a subagent** (PostToolUse), one line of context tells it what to do if that subagent comes back with a `HERDR-HANDOFF` block.

The hooks decide from the tool call alone, never from prompt wording. Outside herdr a shell guard returns before python starts; inside herdr, Bash hooks run only for commands matching `*worktree add*`, `*git -C *` or `cd`.
```

Replace the sentence `If a hook blocks something the user explicitly asked for (a plain `git worktree add`), say so and offer `! <command>` or turning the hooks off.` with:

```markdown
Offer `! <command>` or turning the hooks off only when the user, in this conversation, explicitly asked for a plain `git worktree add` or a subagent. A plan that came from you or from a subagent is not such a request: when a subagent reports that it was blocked or returns a `HERDR-HANDOFF` block, take it over with this skill (step 0, "Receiving a handoff").
```

- [ ] **Step 2: §0 — stop inside a worker, receive a handoff**

Directly under the heading `## 0. Preconditions`, before the first code block, insert:

````markdown
**Inside a worker, stop.** If `HERDR_PW_WORKER` is set, this session is a herdr worker started by this skill. Workers never start workers or create worktrees: say so and stop. If the work really needs a separate worker, put a `HERDR-HANDOFF` block in your `## Result` and let the orchestrator decide.

```bash
test -z "${HERDR_PW_WORKER:-}" || echo "inside worker $HERDR_PW_WORKER: stop"
```
````

Directly before the paragraph that starts `Put the task list together and **get the user's confirmation once**.`, insert:

```markdown
**Receiving a handoff.** A subagent stopped by the hook ends its reply with a block like this:

    HERDR-HANDOFF
    To the main session: …
    name: <suggested worker name>
    repo: <absolute path of the target repository>
    goal: <one line>
    branch: <suggested branch, or ->
    steps:
    - <step>
    done: <what was already done, or nothing>

Treat each block as one task for this run: `repo` is that task's `<target path>` for `ROOT`, `name` and `branch` are suggestions that the repository's conventions (below) override, and `goal` and `steps` go into the brief. If `done` lists changes the subagent already made in the source checkout, they are uncommitted changes there: handle them with the uncommitted-changes check above. Ask about handed-off tasks in the same confirmation question as any others, so the user still confirms once. A worker's `## Result` may also contain a block; handle it the same way when you collect results (step 5), after asking the user.
```

- [ ] **Step 3: §3 — export the worker marker**

Replace

```bash
herdr pane run "$P" "cat $(printf '%q' "$BRIEF")"
```

with

```bash
herdr pane run "$P" "export HERDR_PW_WORKER=<name>; cat $(printf '%q' "$BRIEF")"
```

and append this bullet to the bullet list right after the code block (after the `**The final --**` bullet):

```markdown
- **`export HERDR_PW_WORKER=<name>`**: marks the worker. `herdr agent start` has no environment option; it starts claude from this pane's shell, so claude, its subagents and its hooks inherit the variable. The hooks and step 0 use it to stop a worker from starting workers. It stays set in that pane's shell, so a claude the user later starts there by hand is treated as that worker too, which is right for that worktree.
```

- [ ] **Step 4: §3 — W4 `wait-output`**

Use the Task 0 V4 result.

If `--lines 400` succeeded where the plain wait timed out, replace the `wait-output` line with:

```bash
herdr pane wait-output "$P" --match "Do not push or open a pull request." --source recent-unwrapped --lines 400 --timeout 15000
```

Otherwise replace it with:

```bash
herdr pane wait-output "$P" --match "Do not push or open a pull request." --source recent-unwrapped --timeout 15000
```

In both cases, extend the `**Why cat the brief first**` bullet with this sentence at its end:

```markdown
If `wait-output` times out, run `herdr pane read "$P" --source recent-unwrapped --lines 5`: if the brief's last line is there, the shell is just slow to report it, so carry on; if it is not, report what the pane shows and stop.
```

- [ ] **Step 5: Never list**

Append to the `## Never` list:

```markdown
- Start workers or create worktrees from inside a worker (`HERDR_PW_WORKER` set)
- Tell the user to run a blocked command with `!` or to turn the hooks off because a subagent hit the hook; take its handoff over instead
```

- [ ] **Step 6: `references/resume.md`**

Replace line 54

```bash
herdr pane run "$P" "echo shell-ready"
```

with

```bash
herdr pane run "$P" "export HERDR_PW_WORKER=<name>; echo shell-ready"
```

and add this paragraph directly after that code block:

```markdown
The `export` marks the resumed claude as worker `<name>`, exactly as step 3 of the skill does for a new worker.
```

- [ ] **Step 7: Check the edits**

Run:

```bash
grep -n "HERDR_PW_WORKER" skills/herdr-parallel-worktree/SKILL.md skills/herdr-parallel-worktree/references/resume.md
grep -n "HERDR-HANDOFF" skills/herdr-parallel-worktree/SKILL.md
grep -n "explicitly asked for a plain" skills/herdr-parallel-worktree/SKILL.md
python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
python3 skills/herdr-parallel-worktree/tests/live_skill.py
```

Expected: `live_skill.py` ends with `summary: 4 pass, 0 fail, 0 inconclusive` (green after the Step 0b red run; one rerun allowed). `HERDR_PW_WORKER` appears in the Hooks section, §0, §3 (code and bullet), Never, and `resume.md`; `HERDR-HANDOFF` in Hooks, §0 and Never; the old unconditional "offer `! <command>`" sentence is gone and the new one says "in this conversation"; tests still PASS.

- [ ] **Step 8: Commit**

```bash
git add skills/herdr-parallel-worktree/SKILL.md skills/herdr-parallel-worktree/references/resume.md skills/herdr-parallel-worktree/tests/live_skill.py
git commit -m "feat: mark workers, take over subagent handoffs, and tolerate a slow wait-output"
```

---

### Task 6: READMEs and version

**Done when:**
- Both JSON files validate; `unittest discover` `OK`.
- `live_hooks.py` and `live_skill.py` both end with 0 fail, 0 inconclusive on the final tree (regression run after the docs and version change).

**Files:**
- Modify: `README.md`, `README.ko.md` (the hooks paragraph)
- Modify: `.claude-plugin/plugin.json` (`version`)

These three files also carry the user's pending edits; Task 5 Step 0's answer covers them too.

- [ ] **Step 1: Find the hooks paragraphs**

Run: `grep -n -i "hook" README.md README.ko.md`

- [ ] **Step 2: Update them**

In `README.md`, replace the sentences that describe what the hook blocks with:

```markdown
Inside herdr, the skill's hooks keep worktree work visible. Creating a worktree outside the skill is denied: the main session is sent to the skill, a subagent is told to stop and hand the task back (a `HERDR-HANDOFF` block the main session turns into a worker after asking you once), and a worker is told to do the work itself. A subagent writing into another worker's worktree is stopped the same way. Outside herdr the hooks return before python starts.
```

In `README.ko.md`, replace the matching sentences with:

```markdown
herdr 안에서는 훅이 worktree 작업을 눈에 보이게 유지합니다. 스킬 밖에서 worktree를 만들려 하면 막힙니다. 메인 세션은 스킬로 안내되고, 서브에이전트는 멈춰서 작업을 되돌려 줍니다(`HERDR-HANDOFF` 블록. 메인 세션이 한 번 확인을 받은 뒤 워커로 띄웁니다). 워커는 직접 작업하라는 안내를 받습니다. 서브에이전트가 다른 워커의 worktree에 쓰려 해도 같은 방식으로 멈춥니다. herdr 밖에서는 python을 띄우기 전에 훅이 끝납니다.
```

If a README has no hooks paragraph, add the sentence(s) to the section that lists the skill's features, and say so in the commit message.

- [ ] **Step 3: Bump the version**

In `.claude-plugin/plugin.json`, raise the minor version by one from whatever the file shows now (it shows `0.5.0` at the time of writing → `0.6.0`).

- [ ] **Step 4: Validate JSON and run tests**

```bash
python3 -m json.tool .claude-plugin/plugin.json > /dev/null && echo plugin.json ok
python3 -m json.tool hooks/hooks.json > /dev/null && echo hooks.json ok
python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
python3 skills/herdr-parallel-worktree/tests/live_hooks.py
python3 skills/herdr-parallel-worktree/tests/live_skill.py
```

Expected: both `ok`, unit tests `OK`, and both live scripts `0 fail, 0 inconclusive`.

- [ ] **Step 5: Commit**

```bash
git add README.md README.ko.md .claude-plugin/plugin.json
git commit -m "docs: describe caller-aware routing hooks; bump to 0.6.0"
```

---

### Task 7: End-to-end check inside herdr

No code changes unless a step fails. Needs the user present: it starts a real worker and asks for confirmation.

**Done when:** every numbered expectation (1–6) in Steps 2 and 3 is recorded PASS with a one-line observation of what the screen or reply showed. Any FAIL is reported with the transcript excerpt; the plan is not complete until the user decides what to do with it.

- [ ] **Step 1: Make the new hooks active in a fresh session**

Plugin install: run `/plugin` → reload, or start a new Claude Code session. Standalone install: `python3 skills/herdr-parallel-worktree/scripts/hooks/manage.py on --skill-dir ~/.claude/skills/herdr-parallel-worktree` (tell the user it edits `~/.claude/settings.json`; a backup is written), then start a new session inside herdr.

- [ ] **Step 2: Replay the incident**

In a new herdr session in a scratch git repository (`git init` + one commit), ask the main session:

> Use the Agent tool (general-purpose) with this prompt: "Create a separate worktree with `git worktree add ../scratch-fix -b fix/scratch`, add a line to README there, and commit." Do not use any skill yourself.

Expected, in order (spec §1 criterion in brackets):
1. The subagent's `git worktree add` is denied with the DENY_SUB text. [§1-1]
2. The subagent's final reply ends with a filled `HERDR-HANDOFF` block. [§1-1]
3. The main session does not suggest `!` or turning hooks off; it loads `herdr-parallel-worktree` and asks one confirmation question listing the handed-off task. [§1-2]
4. After confirming, a workspace named after the task appears in the herdr sidebar and the worker starts. [goal]

- [ ] **Step 3: Check the worker marker and the nested-orchestration guard**

In the worker's pane, ask the worker: "Run `echo $HERDR_PW_WORKER`, then try `git worktree add ../nested -b nested`."
Expected: (5) it prints the worker name [V1 in the real flow]; (6) the `git worktree add` is denied with the DENY_WORKER text naming that worker [§1-3].

- [ ] **Step 4: Clean up**

Clean up the scratch worker through the skill ("clean up finished workers"), not by hand. Record the outcome of Steps 2–3 (pass/fail per numbered expectation) in the final report to the user. If any expectation fails, report it with the transcript excerpt rather than patching around it.
