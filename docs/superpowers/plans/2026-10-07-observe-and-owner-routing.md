# herdr-parallel-worktree: result observation (R7) + owner-based delivery (§13) implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Spec: `docs/superpowers/specs/2026-10-04-herdr-delegation-routing-design.md` (§12, §13, §13.5).

## Context

The `design/delegation-routing` branch (not yet merged) implements the hooks that block a subagent or worker from doing worktree work inside herdr and hand it to the main session through HERDR-HANDOFF (E2E 6/6 passed). A check just before the merge exposed two problems.

1. **A command-string regex (R5: `cd`/`git -C`) is incomplete in principle.** It caught only 2 of the 9 commands with which a subagent writes to another worktree.
2. **A blocked task can go to only one place: a "new worker".** If the target worktree has an owner (a sibling worker), the task must go to that owner.

The fix agreed with the user (spec `docs/superpowers/specs/2026-10-04-herdr-delegation-routing-design.md` §12 and §13, plus this decision) is as follows.

- **Remove R5 and add R7.** After Bash finishes (PostToolUse/PostToolUseFailure), R7 attributes a write to the actor that ran the command only when **"it really changed inside the `duration_ms` time window (ctime), and the command mentioned that worktree's path"** are both true. This rule was settled now. It removes the false positives from parallel subagents, the main session, and user edits. It checks only mentioned worktrees, so most Bash calls make 0 git calls.
- **Owner-based delivery:** if a write goes outside the actor's own worktree, the owner of that worktree receives it. If there is no owner, a new one is created. The main session always does the delivery. If the target is the main checkout, the main session tells the user and asks.

After the plan is fully executed, the whole branch is reviewed again. Then the **merge into main and push** that the user asked for follow.

## Global Constraints

- Use only the Python standard library. Run the unit tests with `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v` (collects `test_*.py` only). Run `live_*.py` and `hook_cost.py` by hand.
- **fail-open:** an exception, a git or herdr error, a timeout (2 seconds), a missing `duration_ms`, or a state file error all produce no output. Read runs.json with a **dedicated reader that never raises**. Do not reuse `runs.load()`, because it calls `sys.exit`.
- Outside herdr, or with `hooks: off`, python is not started and there is no output.
- Every git call uses `--no-optional-locks`.
- Normalize every path with `os.path.realpath`. Decide containment on a path separator boundary (`/w/a` does not contain `/w/ab`). When several overlap, the longest prefix wins.
- `hooks/hooks.json` and `manage.py hook_entries()` register the same set (enforced by a test).
- The test claude is always started with config `workerArgs` (currently `--dangerously-skip-permissions`). Reuse the already trusted scratch (`/private/tmp/herdr-e2e.XTll/repo`). This keeps a confirmation dialog from getting in the way.
- Commit per task on `design/delegation-routing`. **Put the R5 removal in the same commit as the R7 registration.** This avoids an intermediate state where nobody watches Bash writes.
- **Scope:** what is observed and judged is (a) worker worktrees open in runs.json (any repository), (b) linked worktrees of the writer's repository, and (c) the main checkout of the writer's repository. Other repositories and paths are allowed.

## Module structure and interfaces

```
scripts/hooks/route.py    entry point (main/argv), enabled(), actor(), creates_worktree() [R1–R3, kept],
                          decide(event, env, deps=None) → R1–R4 + R6, Bash Post/Failure delegate to observe.observe
scripts/hooks/owners.py   read_open_runs(path) -> list[dict]           # never raises, realpath-normalized
                          main_checkout_of(path, git) -> str | None     # first entry of git worktree list --porcelain -z (skips bare/prunable)
                          owner_of(path, runs, probe, writer_common, writer_main) -> Owner | None
                          # Owner = ("worker", name, wt) | ("main-checkout", None, top) | ("none", None, wt)
                          # checks runs containment before the git probe (a path inside a submodule also goes to that worker)
scripts/hooks/observe.py  window(now, duration_ms, pending_starts, margin=0.5) -> (start, end) | None
                          mentioned_paths(texts, cwd, home) -> list[str]        # absolute, ~, cwd-relative, assignment right-hand side (D=/x) tokens → realpath
                          candidates(paths, runs, writer_wts, writer_main, home) -> list[str]   # observed worktrees that contain a mentioned path
                          parse_status_v2_z(data: str) -> list[tuple[str, bool]]   # (relpath, deleted)
                          changed(wt, entries, lstat, win, exclude_dirs, git_paths) -> bool
                          observe(event, env, deps) -> dict | None
                          BgStore: add(session, agent, task_id, start, command) / take(session, agent) / gc(now)
                          Deps(now, lstat, realpath, git, runs, bg)    # real_deps() injects the real implementations
```

Each module is imported by putting the hooks directory on `sys.path`. Tests do the same.

## Decision rules

### R4 extension — PreToolUse Write|Edit|MultiEdit|NotebookEdit (blocked beforehand; the target path is in the input)

| actor \ target owner | home (own) | worker (sibling) | main-checkout | none | out of scope |
|---|---|---|---|---|---|
| main | allow | allow | allow | allow | allow |
| sub (subagent of main) | allow | DENY_SUB(owner) | allow (main's home) | DENY_SUB(owner) | allow |
| worker | allow | DENY_WORKER_WRITE(owner) | DENY_WORKER_WRITE(owner) | DENY_WORKER_WRITE(owner) | allow |
| worker-sub | allow | DENY_SUB(owner) | DENY_SUB(owner) | DENY_SUB(owner) | allow |

home is the toplevel of `probe(cwd)`. If the `cwd` probe fails, allow (the existing fail-open rule).

### R7 — PostToolUse / PostToolUseFailure, tool_name Bash, actors sub, worker, worker-sub
1. If `tool_response.backgroundTaskId` is present, do not judge. Only record it with `BgStore.add`. The record is one file per task id, created with `O_EXCL`. The next judgment fetches it with `take`, which takes ownership by rename, then reads and deletes it.
2. `texts` = this command's text + the background commands fetched by `take`
3. Compute `mentioned_paths`. If there is no path token, or all of them are inside home, **exit without any git call**. Most commands end here.
4. Compute `candidates`: observed worktrees that contain a mentioned path. Call `git worktree list --porcelain -z` once, and only when the writer's repository worktree list is needed.
5. Compute the window `window(now, duration_ms, [background start times])`. The start is `floor(min(now - dur/1000, *starts) - 0.5)`. Round down to also cover 1-second-resolution filesystems.
6. Judge `changed` for each candidate w. It counts as changed if any of the following has a ctime inside the window.
   - An entry of `git -C w status --porcelain=v2 -z --untracked-files=all`
   - For a deleted entry, the ctime of the **nearest existing ancestor** directory
   - The ctime of `git rev-parse --git-path logs/HEAD` and `--git-path index`. The index catches `restore`, `checkout -- f`, and `stash`.
   
   Exclude entries that sit inside home or inside another observed worktree (a non-gitignored `.worktrees/x`). Use `lstat`.
7. If it changed and w was mentioned, send an OBSERVED message per owner as `additionalContext`. Set `hookEventName` to `PostToolUse` or `PostToolUseFailure` to match the event.
8. Every time, delete records older than 1 hour with `BgStore.gc(now)`.

### Messages (all branch on the owner)
- `HANDOFF` template:

  ```
  HERDR-HANDOFF
  To the main session: load the herdr-parallel-worktree skill and handle this by its `owner:` line …
  name: …
  repo: …
  owner: <worker name | main-checkout | none>
  goal: …
  branch: …
  steps:
  …
  done: …
  ```
  
- `NOTE_HANDOFF` (R6): "…handle it by the block's `owner:` line (skill step 0, Receiving a handoff)…"
- `deny_sub(owner)`: the existing DENY_SUB with the owner named. If the owner is a worker, add "the main session will pass it to worker `<n>`".
- `deny_worker_create(name, home)`: the existing deny_worker. It blocks worktree creation.
- `deny_worker_write(name, home, owner)`: new. "That file is outside your worktree (owner …). Do not do that part; write it as a HANDOFF in `## Result`."
- `observed(who, hits)`: "The command changed `<w>` (owner …). Do not change more; stop. Write the changed paths in `done:`." sub and worker-sub report with a HANDOFF in the final response, and worker reports in `## Result`.

### Filtering out the main session (reflects the O9 measurement: early python exit instead of a shell guard)
- Every registered command uses one GUARD only: `[ "$HERDR_ENV" = 1 ] || exit 0; python3 -S "<route>" <arg>`. No shell escaping inside the JSON is needed.
- Groups the main session does not need get their own argv: `pre-tool-use-write` (Pre for Write-type tools), `post-tool-use-bash` (Bash Post), `post-tool-use-failure` (Bash PostFailure). For these argvs, `route.main` **looks for `"agent_id"` in the raw stdin bytes, and if it is absent and `HERDR_PW_WORKER` is also absent, exits before any JSON import or parse**. Measured: 24ms for 1KB, 33ms for 1MB, 86ms for 10MB. The shell guard took 467ms at 10MB.
- `pre-tool-use` (Agent / EnterWorktree / `worktree add`) and `post-tool-use` (the NOTE for Agent|Task), which the main session needs, are handled as before.

## Tasks

Run every task in the executing-plans way. Keep a ledger, confirm RED before going to GREEN, and confirm the completion criterion with evidence.

### Task 0: Measurements (done 2026-10-07, spec §13.5 / commit 9022631)
- **T1:** If you send a live worker a follow-up with "one line that points to a file" (`herdr agent prompt … --wait`), does it follow it? Also check whether it is handled as a paste and rejected.
- **T2:** What happens if you send to a worker in the `working` state: accepted, queued, rejected, error code. And does the flow of sending after `agent wait --until idle --until done` work?
- **T3:** If you terminate the worker claude, resume it with the resume.md procedure (including `--add-dir BRIEFS`), and send a follow-up, does it keep its earlier context?
- **O8:** Do hooks run concurrently for parallel Bash calls of one agent (to confirm the BgStore design)?
- **O9:** The time to run GUARD_NON_MAIN through `sh -c` with a 1MB payload.
- Environment: start the test workers in the scratch repository with the skill's §1 to §3 commands (workerArgs, `HERDR_PW_WORKER` exported).
- **Completion criterion:** spec §13.5 has a result table. **If T1 fails, stop and report** (the delivery method would need a redesign). Clean up the workers this task made with the cleanup procedure, and ask the user if cleanup is refused.

#### Checkpoint — check that the measurements fit the plan (user confirmed 2026-10-07)
- Results: T1 and T3 passed. T2 was handled safely by queueing. O8 confirmed concurrent execution. O9 showed the worst-case cost of the shell guard is large → changed to "Filtering out the main session" above. Additional finding: a worker whose workspace alone was closed must be resumed with `worktree open`, and `runs.py` needs a command to update the location of an open record (reflected in Task 5).
- Report the results of T1 to T3, O8, and O9 in a table. Compare which part of this plan each result confirms or changes.
  - T1, T2 → the delivery method in deliver.md
  - T3 → delivery after a resume
  - O8 → BgStore design
  - O9 → whether to adopt the shell guard
- If the plan needs changes, present the fixes to this file and the spec together.
- Go on to Task 1 only after the user confirms.

### Task 1: owners.py (TDD)
- Tests (`tests/test_owners.py`):
  - `read_open_runs`: missing file, corrupt, not a list, mixed with cleaned, `/var`↔`/private/var` normalization. SystemExit must not occur in any case.
  - `main_checkout_of`: an ordinary repository, `--separate-git-dir`, a worktree of a bare repository, a prunable entry
  - `owner_of`: the 4 return values, longest prefix first (nested worktrees), path boundary, a submodule path inside a sibling worktree → that worker, a linked worktree of another repository (if not in runs.json) → None
  - 1 real git integration test
- **Completion criterion:** tests OK.

### Task 2: R4 extension and messages (route.py, TDD)
- Tests (`test_route.py`):
  - `R4OwnerMatrixTest`: check all 20 cells of the table above. The expected output is the exact message string.
  - Message tests: the position of the `owner:` line, the first-line wording, the worker delivery wording, and the distinction between `deny_worker_write` and `deny_worker_create`
  - Update the R4 rows of the existing `SpecMatrixTest` and mark the R5 row for removal
  
  Update them together, checking against the spec §5.3 and §13.2 tables.
- **Completion criterion:** OK. The existing R1 to R3 and R6 tests pass unchanged.

### Task 3: observe.py pure functions (TDD)
- Tests (`tests/test_observe.py`). Include every item of review section C.
  - `parse_status_v2_z`:
    - `1` (8 fields + path, spaces in the path)
    - `2` (9 fields + path + **the next NUL consumes the original path**, and the records after it parse correctly)
    - `u` (10 fields)
    - reflect `?`, ignore `!`, ignore the `#` header
    - paths with newlines and Korean characters, empty output
    - `.D`/`D.` → deleted
  - `window`: normal, missing, string duration, widening by a background start, rounding down (1-second resolution)
  - `mentioned_paths`: absolute path, `~`, `../b` relative (to cwd), `D=/w/b` assignment, `--work-tree=/w/b`, a path inside quotes, `/w/ab` is not a mention of `/w/a`, an empty result when only paths inside home appear
  - `candidates`: differences in realpath notation, home excluded, out of scope excluded
  - `changed` (lstat injected):
    - ctime inside/outside the window
    - `cp -p` (mtime in the past, ctime inside the window)
    - deletion + parent also deleted → ancestor
    - only logs/HEAD changed, only index changed
    - nested `.worktrees/x` entry excluded
    - git timeout → False, worktree directory missing → False
  - `BgStore`: add, take, gc; two concurrent adds followed by one take returns both; corrupt file; 1-hour cleanup
  - Real filesystem integration: in a temporary repository + linked worktree, do `echo >`, `cp -p`, `git restore`, and a commit one at a time and detect each.
- **Completion criterion:** OK. The integration tests run without skips.

### Task 4: R7 wiring + R5 removal + registration (one commit)
- Tests:
  - `ObserveDecideTest` (use the measured field shapes):
    - PostToolUse and PostToolUseFailure → `hookEventName` matches
    - main is ignored
    - sub, worker, and worker-sub each
    - a mention with no change gives no output; a change with no mention gives no output
    - background: only record and no output → attributed at the next Post
    - corrupt runs.json or missing `duration_ms` → no output
  - R5 removal test: a subagent's `cd /w/b && make` passes at Pre (Post now judges it). Delete `DirTargetsTest`.
  - `test_registration.py`:
    - New matcher list: PreToolUse Bash `Bash(*worktree add*)` / EnterWorktree|Agent|Task / Write|Edit|MultiEdit|NotebookEdit, PostToolUse Agent|Task / Bash, PostToolUseFailure Bash
    - Check that every group is a single GUARD + `python3 -S`
    - argv mapping: `pre-tool-use`, `pre-tool-use-write`, `post-tool-use` (Agent|Task), `post-tool-use-bash`, `post-tool-use-failure`
    - parity, `strip_ours`
  - Early exit test (real process): with the non-main argv and a main JSON, there is no output and the `json` module is not imported (verify with `-X importtime` or a sys.modules check hook). If agent_id is present or `HERDR_PW_WORKER` is set, it goes through to the judgment. Empty stdin or broken bytes also give no output.
- Implementation: put the 5 kinds above in the `route.main` argv, and make the non-main argvs exit early. Change decide to a delegating structure, and delete `DIR_ARG` and `dir_targets`. Update hooks.json and manage.py.
- L2c (update `hook_cost.py`), the targets are:
  - main Bash Post: python early exit, 40ms or less for 1KB / 150ms or less for 10MB
  - sub Post, no path mentioned: 80ms or less
  - sub Post, 1 mention + a large repository: 300ms or less
  - worker Bash, no mention: 80ms or less
- L2 (add to `live_hooks.py`, keep C1 to C11 as regressions):
  - C12: sub `echo x > <wt>/f` → OBSERVED (owner none) + HANDOFF
  - C13: sub re-edits an already modified file with `sed -i` → detected
  - C14: `…; false` → detected in PostToolUseFailure
  - C15: sub writes to its own cwd worktree → none
  - C16: worker Write to a sibling worktree → DENY_WORKER_WRITE(owner)
  - C17: worker Bash to a sibling worktree → OBSERVED
  - C18: main Bash → no log (python not run)
  - C19: sub runs only `cat <wt>/f` (a read) → none
- Finally, re-register the user settings with `manage.py on`. Before running, tell the user that `~/.claude/settings.json` will be modified, and give the background path.
- **Completion criterion:** unit tests OK, L2c 4 lines PASS, L2 `0 fail, 0 inconclusive`.

### Task 5: Skill docs (L3 red → green)
- RED: add S4 to S6 to `live_skill.py` first and confirm they fail.
  - S4: owner worker HANDOFF → the main session follows `deliver.md` (tries Read or `herdr agent prompt`). It does not try `herdr worktree create`.
  - S5: owner main-checkout → asks the user. It does not try a herdr command.
  - S6: the main session that received a HANDOFF contained in a worker's `## Result` → the same handling as S4
  - Keep S1 to S3 as regressions.
- GREEN:
  - **Worker guard at the very top of SKILL.md:** write work outside your own worktree as a HANDOFF (with owner) in `## Result`.
  - **§0 "Receiving a handoff":** branch on the owner (worker → `deliver.md`, main-checkout → tell and ask, none → new worker). Confirm once.
  - **step 5:** a HANDOFF inside Result is passed on with the same handling.
  - **Tidy the Never list:** "Do not send the first instruction with `agent prompt`. Send a follow-up as a file + one line (deliver.md)." Reflect the T1 result.
  - **`references/deliver.md` (new, reflects T1 to T3):**
    1. Look up the worker with runs.py `show`.
    2. If open and alive: write the follow-up file to `BRIEFS/<name>-followup-<ts>.md` and finish it with `finalize-brief.py`. If it is working, wait the T2 way and send the one-line prompt.
    3. If cleaned up or terminated, do `resume.md` next, 2. Tell three cases apart: (a) the worker is open but claude has exited → resume in the same pane, (b) the workspace is closed but the worktree remains → `herdr worktree open --cwd <root> --path <wt> --label <name> --no-focus`, then resume (T3), (c) the worktree is cleaned up too → the existing regeneration path of resume.md.
    - If it is working, wait with `herdr agent wait <name> --until idle --until done --timeout 600000`, then send. If the wait times out, send anyway (T2: it is queued after the current work finishes and is not cut off).
    4. Check with `agent read` and report.
  - **`references/resume.md`:** add `--add-dir "$BRIEFS"` to the `agent start` arguments. Add the "if only the workspace is closed, `worktree open`" path. Link "send follow-ups with `deliver.md`".
  - **`scripts/runs.py`:** `mark-open` now reopens only a cleaned record. Add a `relocate --root --name --workspace --pane` subcommand that updates the location (workspace, pane) of an open record (found in T3). Create `tests/test_runs.py` to verify add, relocate, and show with a temporary DATA_DIR. Handle herdr calls by putting a fake herdr on PATH.
- **Completion criterion:** live_skill S1 to S6 PASS 2 times in a row.

### Task 6: Docs, README, regression
- Both READMEs: delete the R5 description, and describe result observation and owner delivery.
- Update spec §12.3 to the "change + mention" rule (delete the hold rule and the worker status lookup). Add the known gaps to §7.
  - Writes whose path does not appear in the command
  - False positives when a read command and a worker's concurrent write overlap
  - Writes by daemon child processes (`nohup … &`)
- Keep the version at 0.5.0 (recorded as a ruling).
- Rerun L1, L2, L2c, and L3 all as regressions.

### Task 7: herdr E2E (with the user, workerArgs applied, trusted scratch)
- **E1:** Start workers A and B, then have A fix a file in B's worktree. Expected: A leaves a HANDOFF (owner B) in Result → the main session delivers it to B → B does it.
- **E2:** Clean up B, then make the same request. Expected: the main session resumes B and delivers, and B keeps its context.
- **E3:** A worker tries to fix the main checkout. Expected: the main session tells the user and asks.
- **E4:** A subagent of the main session runs `echo > <B wt>/f`. Expected: OBSERVED → HANDOFF (owner B) → delivered to B.
- Record PASS/FAIL and what was observed for each expectation. Clean up with the cleanup procedure, and ask the user if it is refused.

### Task 8: Final review → merge into main → push
- Bundle the whole branch as a review-package and give it to a fresh reviewer (opus). Handle Critical and Important in one fix pass (RED→GREEN).
- Do `git checkout main && git pull --ff-only && git merge design/delegation-routing`. Run L1 on the merge result, then `git push origin main`, and delete the branch with `git branch -d design/delegation-routing`.

## Verification summary

| Layer | Means | What it confirms |
|---|---|---|
| L1 | `test_owners.py`, `test_observe.py`, `test_route.py`, `test_registration.py` | the 20 R4 cells, porcelain parsing, mention extraction, the window, ctime, background, guard execution, parity |
| L2 | `live_hooks.py` C1~C19 | that it fires with the real Claude Code event shapes and the messages arrive |
| L2c | `hook_cost.py` | main early exit 40ms (1KB) and 150ms (10MB), no mention 80ms, a mention 300ms |
| L3 | `live_skill.py` S1~S6 (red first) | that the main session handles each owner correctly |
| L4 | E1~E4 | the whole flow inside herdr |

**Review Focus for the final reviewer**
1. porcelain v2 `-z` renames and special paths
2. realpath boundaries: runs.json, `git worktree list`, the command text, `/var`↔`/private/var`
3. False positives and misses in mention extraction (read commands, assignments, relative paths)
4. Whether the non-main argv early exit wrongly blocks the paths the main session needs (Agent, EnterWorktree, worktree add, NOTE)
5. BgStore concurrency and corruption handling
