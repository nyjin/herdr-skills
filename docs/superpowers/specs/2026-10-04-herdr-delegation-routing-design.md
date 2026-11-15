# herdr-parallel-worktree: route delegation to a herdr worker whatever path it takes — design

- Status: draft (awaiting approval)
- Date: 2026-10-04
- Baseline: `494a0d7` plus uncommitted working-tree changes (`SKILL.md`, `config.schema.json`, `plugin.json`, two READMEs). The skill is installed through a symlink, so the working-tree state is what actually runs.
- Measured on: Claude Code 2.1.289, hook input JSON recorded with `claude -p --settings <temporary settings>`. User settings were left alone.
- Document location: the repo has no documentation convention, so we propose `docs/superpowers/specs/`.

## 1. Goal

Inside herdr, work that needs a worktree is taken over by the main session through this skill and run as a herdr worker (a pane visible in the sidebar), **whichever path requested it**. The result must be the same whether the main session does it directly or hands it to a subagent.

Success criteria:
1. If a subagent tries to create a worktree or write to another worktree, it is blocked. The subagent then returns a work order in a fixed format (HERDR-HANDOFF) and stops.
2. When the main session receives a HANDOFF, it does not tell the user to run a `!` command or turn the hooks off. It takes over through the skill, goes through the single confirmation of §0, and starts the worker.
3. Inside a worker, no new worker or worktree can be created (prevents nested orchestration).
4. Outside herdr, the token cost is 0.
5. The decision logic is pinned by unit tests.

## 2. Principle: look at the action, not the prompt

The decision uses **deterministic tool calls and their fields** only. It does not look at the wording of the request prompt or the Agent prompt. Interpreting wording produces both false positives and misses, while an action is settled by the hook input JSON.

As a result, we block at the moment work involving a worktree actually starts. We accept the cost of a subagent starting some work and then stopping. In the incident that started this, the subagent's first action was `git worktree add`, so it would have been blocked before any work.

## 3. Facts confirmed by measurement

| # | Fact | Effect on the design |
|---|---|---|
| F1 | PreToolUse input: the main session has `session_id, cwd, permission_mode, prompt_id, tool_name, tool_input, tool_use_id, transcript_path, hook_event_name`. Calls inside a subagent **add `agent_id` and `agent_type`** | The actor is told apart by whether `agent_id` is present |
| F2 | `Agent`'s `tool_input` is `description, prompt, subagent_type` (plus `isolation` when set). No field says where the subagent will work | At Agent call time, only `isolation` is judged |
| F3 | After a subagent ran `cd <other directory>`, the hook's `cwd` was still the directory the session started in (measured against a directory outside the project) | The target path comes from `file_path` and command arguments. `cwd` is used only as the "session's home" |
| F4 | In this version `Agent` is asynchronous by default. PostToolUse(Agent) fires right after launch with `status: "async_launched"` and has no result text | Detecting the HANDOFF at result time is impossible |
| F5 | PostToolUse(Agent)'s `additionalContext` **reaches the main session** | An instruction can be given to the main session at launch time (§5 R6) |
| F6 | SubagentStop has `last_assistant_message`. But `additionalContext` is injected **into the subagent**, and the subagent ran 9 times in a loop (`stop_hook_active: true`) | SubagentStop prints nothing |
| F7 | `herdr agent start` has no environment variable option. The pane must be at an interactive shell prompt, and the agent runs in that shell | The worker marker is exported in the pane shell before `agent start` (unverified, §9 V1) |

## 4. Verdict on hypotheses W1 to W4

- **W1 (the subagent has no context): true.** `route.py` has no `agent_id` branch. So even a blocked subagent is told "Load that skill and follow it", while the skill forbids a subagent from acting as orchestrator.
- **W2 (the exception clause fires wrongly): true.** The subagent has no basis for judging "If the user explicitly asked for a plain git worktree". For a subagent, the orchestrator's prompt is the "user".
- **W3 (no guidance on the main side): true.** SKILL.md has no section for when a subagent report arrives. The Hooks sentence "If a hook blocks something the user explicitly asked for … offer `! <command>`" is what led to this wrong answer.
- **W4 (`wait-output` 5-second timeout): unverified.** There is only a record that timeouts happened. The cause (brief length, shell speed, mismatch between the `--match` string and the output) was not reproduced. This design only changes the handling so that a failure still proceeds, and checks the cause in V4.

## 5. Design

### 5.1 Telling actors apart

| Actor | How to tell |
|---|---|
| `main` | no `HERDR_PW_WORKER`, no `agent_id` |
| `sub` | no `HERDR_PW_WORKER`, `agent_id` present |
| `worker` | `HERDR_PW_WORKER` present, no `agent_id` |
| `worker-sub` | `HERDR_PW_WORKER` present, `agent_id` present (the environment variable is inherited) |

`HERDR_PW_WORKER=<worker name>` is exported in the pane shell before `agent start` in §3. The same applies when resuming (`references/resume.md`).

### 5.2 Deciding "another worktree"

For a path `p` (for a file, the nearest existing parent directory), run `git -C <dir> rev-parse --path-format=absolute --git-dir --git-common-dir --show-toplevel` once.

- If `git-dir == git-common-dir`, it is not a linked worktree → **pass**
- If it is not a git repository, or there is an error or timeout (2 seconds) → **pass** (fail-open, as before)
- If it is a linked worktree, call its toplevel `wt(p)`. Call the toplevel of the session `cwd` `home`. If `wt(p) == home` (its own worktree) → **pass**, otherwise → **hit**

### 5.3 Rules

Every rule works only when `HERDR_ENV=1` and the config's `hooks` is not `"off"`.

| ID | Event / tool | Condition that hits | main | sub | worker | worker-sub |
|---|---|---|---|---|---|---|
| R1 | PreToolUse `Bash` | `git … worktree add` in command position (existing regex) | DENY_MAIN | DENY_SUB | DENY_WORKER | DENY_SUB |
| R2 | PreToolUse `EnterWorktree` | no `path` | DENY_MAIN | DENY_SUB | DENY_WORKER | DENY_SUB |
| R3 | PreToolUse `Agent`/`Task` | `isolation == "worktree"` | DENY_MAIN | DENY_SUB | DENY_WORKER | DENY_SUB |
| R4 | PreToolUse `Write`/`Edit`/`MultiEdit`/`NotebookEdit` | `file_path` (or `notebook_path`) is outside its own worktree and has an owner (§13.2 revision: by the target's owner) | pass | DENY_SUB(owner). The main checkout passes | DENY_WORKER_WRITE(owner) | DENY_SUB(owner) |
| R5 | PreToolUse `Bash` | `p` in `git -C <p>` or `cd <p>` in the command is another worktree. Only unquoted tokens or simple quoted tokens are resolved. If a variable or substitution is present, no decision is made | pass | DENY_SUB | pass | DENY_SUB |
| R6 | PostToolUse `Agent`/`Task` | always | inject NOTE_HANDOFF | — | — | — |

Writes by the main session (R4, R5) are not blocked. A user telling the main session to edit a worker's worktree directly is normal use.

### 5.4 Messages

- **DENY_MAIN** (R1 to R3, replaces the existing `DENY`): it keeps the point that worktree work inside herdr must go through this skill. The exception clause is narrowed to "**only when the user directly** asked for a plain worktree or subagent in this conversation". It states explicitly that a plan the orchestrator already made is not an exception.
- **DENY_SUB**: "You are a subagent. Only the main session starts workers. Do not create a worktree or write to one, and do not retry another way. Stop and end your final response with the block below." It also says not to suggest `!` commands or turning the hooks off to the user.
- **DENY_WORKER**: "You are the herdr worker `<name>`. A worker does not create worktrees or workers. Do the work directly in your own worktree (`<home>`), or if a separate worker is needed, write it as a HANDOFF block in `## Result`. The orchestrator decides."
- **NOTE_HANDOFF** (R6, `additionalContext`): "If this subagent returns a `HERDR-HANDOFF` block, load the herdr-parallel-worktree skill and continue from §0. Do not tell the user to run a `!` command or turn the hooks off."

HANDOFF format (required by DENY_SUB and DENY_WORKER):

```
HERDR-HANDOFF
To the main session: load the herdr-parallel-worktree skill and turn this into a worker, confirming with the user once (§0). Do not tell the user to run it with `!` or to turn the hooks off.
name: <suggested worker name>
repo: <absolute path of the target repository>
goal: <one line>
branch: <suggested branch, or ->
steps:
- <step>
done: <what was already done, or nothing>
```

A block returned by a worker-sub is received by the worker's main session. Even if the worker's main session loads the skill as the block says, it stops at the worker check in §0 and copies the block into `## Result`. The orchestrator then receives it and decides when it collects results in §5.

The first line of the block also carries an instruction to the main session. It overlaps with the instruction R6 already injected, so that the main session takes the right path even if one of the two is missing.

### 5.5 Skill (SKILL.md etc.) changes

- **Hooks section:** a summary of the per-actor rules (§5.3) and the cost (§6). The sentence "offer `! <command>`" that caused W3 is limited to "only when the user asked directly in this conversation".
- **§0 start:** if `HERDR_PW_WORKER` is present, stop immediately ("Orchestration is not possible inside a worker. If a separate worker is needed, write a HANDOFF in `## Result`"). This is the second line of defense against nesting.
- **New §0 "Receiving a handoff":** treat a HERDR-HANDOFF as a single task proposal. `repo` → `ROOT`; use `name`/`branch` as proposed values, but the repo's conventions come first. Reflect `steps`/`done` in the brief. Put it in the same confirmation question as the other tasks, so there is still one confirmation. If partial changes left by the subagent (`done`) are in the main working tree, handle them with the existing "check uncommitted changes" rule.
- **§3:** `herdr pane run "$P" "export HERDR_PW_WORKER=<name>; cat <brief>"`
- **§3 W4:** raise `wait-output`'s `--timeout` to 15000. On a timeout (exit 1), check the last line with `herdr pane read "$P" --source recent-unwrapped --lines 5`. If the brief's last line is visible, proceed as is. If it is not visible, report and stop.
- **`references/resume.md`:** change `pane run "$P" "echo shell-ready"` to `"export HERDR_PW_WORKER=<name>; echo shell-ready"`.
- **Never list:** add "Start workers or create worktrees from inside a worker (`HERDR_PW_WORKER` set)". Keep the existing "Substitute an `Agent` subagent".
- **Two READMEs:** update the hook description.

### 5.6 Code structure

- `scripts/hooks/route.py`
  - `decide(event: dict, env: Mapping[str, str], probe) -> dict | None`: pure decision. It takes `probe(path) -> (git_dir, common_dir, toplevel) | None` by injection (a fake in tests, git at runtime).
  - `main()`: argv (`pre-tool-use` | `post-tool-use`), `enabled()`, stdin parsing, output. It keeps the property of printing nothing when an exception occurs.
- `hooks/hooks.json` and `hook_entries()` in `scripts/hooks/manage.py` must be **the same set**. A test compares them.
- Registration (the same in both places):

| Event | matcher | `if` | Argument |
|---|---|---|---|
| PreToolUse | `Bash` | `Bash(*worktree add*)` | `pre-tool-use` |
| PreToolUse | `Bash` | only commands containing `git -C` or `cd` (exact pattern fixed in V2) | `pre-tool-use` |
| PreToolUse | `EnterWorktree\|Agent\|Task` | — | `pre-tool-use` |
| PreToolUse | `Write\|Edit\|MultiEdit\|NotebookEdit` | — | `pre-tool-use` |
| PostToolUse | `Agent\|Task` | — | `post-tool-use` |

- Put a `[ "$HERDR_ENV" = 1 ] || exit 0;` shell guard in front of every hook command. Outside herdr, python does not start.
- `strip_ours()` in `manage.py` finds groups by `MARK`, so it keeps working when the number of groups grows. Running `on` again removes the existing groups and registers the new set, so upgrades are handled too.

## 6. Cost

- **Outside herdr:** 0 tokens. Only one shell guard runs per matching tool call.
- **Inside herdr:** one python run per Write/Edit etc. call. git is called once, and only for a subagent (`agent_id`). Each Agent launch adds one NOTE_HANDOFF line (about 50 tokens).

## 7. Known gaps

1. **Delegation where a subagent edits the main working tree directly.** No worktree is involved, so this is normal within scope (a). If it later needs widening, consider a config key (for example `routeSubagentWrites: "worktree" | "all"`). Not implemented this time.
2. **Bash writes whose path cannot be extracted:** writes inside a script, paths assembled from variables, `pushd`, and so on.
3. **Whether the main session that receives a HANDOFF follows the instruction is model behavior.** It is doubled up by R6 and the first line of the block, but not guaranteed. V3 checks it by reproducing the incident.

## 8. Rejected alternatives

| Alternative | Why rejected |
|---|---|
| Check the Agent prompt text for worktree instructions | A wording heuristic, so it gives false positives and misses. Against the action principle (§2) |
| Detect a "parallel" keyword in UserPromptSubmit | Same reason |
| C. Pre-approved delegation (the subagent runs the skill itself) | AskUserQuestion exists only in the main session, so the confirmation principle breaks and there is a nesting risk |
| Detect a HANDOFF in the result at PostToolUse(Agent) | F4: it is asynchronous, so there is no result text |
| Inject an instruction into the main session from SubagentStop | F6: it is injected into the subagent and runs 9 times in a loop. **Do not try again** |
| Identify a worker by the worktree path in runs.json | Indirect inference. Used as a fallback only if V1 fails |
| Block all subagent writes to the repository (b′) | Blocks even light delegation. The user chose (a) |

## 9. Verification

### Measurements before implementation (the plan's first step)

- **V1:** In a herdr pane, run `export HERDR_PW_WORKER=x`, then check whether the hook of the claude started with `herdr agent start` sees this variable. If it fails, switch to the fallback that compares `worktree` and `cwd` in runs.json.
- **V2:** Check whether the `if` filter syntax lets through only commands containing `git -C` or `cd` (`Bash(*git -C *)`, `Bash(cd *)`, `Bash(* cd *)`, and so on).
- **V3:** Check whether F3 (`cwd` does not follow `cd`) also holds for a path inside the project (`.worktrees/x`).
- **V4:** Reproduce W4. Use a long brief to find the cause of the `wait-output` timeout.

### Unit tests (`skills/herdr-parallel-worktree/tests/`, standard library `unittest` only)

- **Input fixtures:** use the JSON shapes measured in §3 as they are (main/sub PreToolUse, PostToolUse(Agent)).
- **Decision matrix:** R1 to R6 × 4 actors × hit/pass. Plus these cases.
  - Writing to its own worktree passes
  - Not a repository, a git error, or a timeout passes
  - No `HERDR_ENV`, or `hooks: off`, gives no output
  - "worktree add" inside a commit message passes (existing behavior)
  - The incident's subagent command `git worktree add ../kb-skills-fix-normalize -b fix/...` → DENY_SUB
- **One real git integration test:** create a temporary repository and a linked worktree inside the test code (`subprocess`), and check §5.2 with the real `probe`.
- **Registration match:** check that `hooks/hooks.json` and `manage.py hook_entries()` are the same apart from the path prefix.

### Manual E2E

Reproduce the incident inside herdr. The main session starts an Agent carrying a worktree instruction → R1 DENY_SUB → a HANDOFF is returned → the main session confirms once per skill §0 → the worker appears in the sidebar and `HERDR_PW_WORKER` must be set.

## 10. Changed files

- `skills/herdr-parallel-worktree/scripts/hooks/route.py` — rebuild the decision, add `post-tool-use`
- `hooks/hooks.json`, `skills/herdr-parallel-worktree/scripts/hooks/manage.py` — registration set
- `skills/herdr-parallel-worktree/SKILL.md` — Hooks, §0, §3, Never
- `skills/herdr-parallel-worktree/references/resume.md` — export
- `skills/herdr-parallel-worktree/tests/` — new
- `README.md`, `README.ko.md` — hook description
- `.claude-plugin/plugin.json` — version bump

## 11. Measured results (before implementation, 2026-10-05)

| Item | Result | Applied as |
|---|---|---|
| V1 worker marker passing | A export: `worker=v1a`, B split `--env`: `worker=v1b` (both passed. Both panes were `agent_not_ready` because of the startup dialog, but the SessionStart hook ran) | keep export |
| V2 `if` pattern | (1) `cd /tmp && true` → `Bash(cd *)` (2) `git -C /tmp status` → `Bash(*git -C *)` (3) `ls` → none (4) `true && cd /tmp` → `Bash(cd *)`. `Bash(* cd *)` never fired: Claude Code matches a compound command per subcommand | In Task 4, remove the `Bash(* cd *)` group (do not drop the `if`) |
| V3 `cwd` after `cd` inside the project | main: from the call after `cd .worktrees/x`, `cwd` is `…/.worktrees/x`. sub: receives the `cwd` the main session changed (shares the session's shell state). A `cd` outside the project resets it to the original (F3) | `home` is "the worktree of the hook `cwd`, which may be the directory last `cd`'d into". Added to known gaps (§7-4) |
| V4 `wait-output` | 300 lines in a new pane: exit 0 / 2.64s. 900 lines in a pane with a running shell: exit 0 / 0.56s. `--lines 400`: once exit 2 / 0.03s, the retry exit 0 (unstable) | The cause is the shell startup time of a new pane, not the brief length. Task 5 uses timeout 15000 without `--lines`, then rechecks the screen |

§7 addition:

4. **When the main session has `cd`'d into a linked worktree inside the project** (for example `.worktrees/x`), that worktree becomes `home`. A subagent writing there passes as "its own worktree" (V3).

## 12. Revision: detect Bash writes by their result, not by the command (2026-10-05)

### 12.1 Background
In a check just before merging, R5 (the `cd`/`git -C` regex) caught only 2 of 9 Bash commands in which a subagent changes another worktree. `echo > …`, `sed -i …`, `cp`, `python -c`, `git --work-tree=…`, `npm --prefix …`, and paths assembled from variables all passed. Bash runs arbitrary programs, so judging "where it writes" from the command string cannot be complete in principle. By the user's decision, **writes are detected by their result**, and **creation keeps the current deterministic pre-block (R1 to R3)**.

### 12.2 Measurements (Claude Code 2.1.289)

| # | Item | Result |
|---|---|---|
| O1 | A failed Bash | `PostToolUseFailure` fires instead of PostToolUse. `tool_use_id` is the same as in Pre. `error: "Exit code 1"` |
| O1b | Response to the failure event | `additionalContext` reaches the subagent |
| O2 | Response to the success event | Both the `reason` of `decision: "block"` and `additionalContext` reach the subagent. But it does not stop execution (the subagent keeps running the next command) |
| O3 | Background Bash | PostToolUse fires 0.06 seconds after execution starts (`tool_response.backgroundTaskId`). The actual write happens after that. When the subagent finished, the background job also ended (`backgroundEndsWithFinalResponse`) |
| O4 | Editing a file that was already modified again | `git status --porcelain` does not change. mtime does change (for both tracked and untracked files) |
| O5 | Cost | Small repository + 5 linked worktrees: one snapshot 134ms (sequential). One `git status` on a real repository (1.8 to 2.8 thousand files): 71ms (warm) to 177ms (cold) |
| O7 | mtime vs ctime | An overwrite with `cp -p`, `touch -t` to a past time, and a new file from `rsync -a` keep an mtime outside the window and are missed. ctime (inode change time) was inside the window in all three. `git --no-optional-locks status` and file reads did not change ctime |
| O6 | Run time | Both PostToolUse and PostToolUseFailure of Bash have `duration_ms`. The real write mtime fell inside the window [Post time − duration, Post time] (a 4.6-second window for success, a 1.1-second window for failure). The window start is about 0.07 seconds later than the PreToolUse hook time |

### 12.3 Design

**R5 is replaced.** `DIR_ARG`/`dir_targets` and the `cd`/`git -C` `if` filter are removed. R4 (pre-blocking of the Write/Edit tools) stays. A tool's write has its target path in the input, so it is better blocked in advance.

**R7 — observe the result of a subagent's Bash** (PostToolUse and PostToolUseFailure, only when `agent_id` is present. The main session and the worker itself exit immediately). No snapshot is taken before execution. O6's `duration_ms` gives the time window in which the command ran, so no PreToolUse hook and no per-call state file are needed.

1. The **observed set W** is the union of two sets.
   - The linked worktrees of the session `cwd` repository: one `git worktree list --porcelain`
   - The worktrees of open workers recorded in runs.json: including other repositories (like the incident, where the repository differed from the main session's)
   
   But `home` (the worktree of the session `cwd`) is excluded. If W is empty, do nothing.
2. **Window** = [Post time − `duration_ms` − 0.5 seconds, Post time]. The 0.5 seconds is slack to absorb the clock and the moment the time is recorded. All file times are read as **ctime** (O7). mtime can hold a past value through `cp -p`, `rsync -a`, or `touch`, but ctime always becomes the current time on a write or a metadata change and cannot be set arbitrarily.
3. **Change detection:** for each worktree in W, in parallel, with a 2-second timeout per call, treat it as "changed" if any of the following is inside the window.
   - Among the files that `git --no-optional-locks status --porcelain=v2 -z --untracked-files=all` lists, one whose ctime is inside the window: this catches both new modifications and re-modifications (O4).
   - For a file listed as deleted, check whether the parent directory's ctime is inside the window.
   - Check whether the ctime of `git rev-parse --git-path logs/HEAD` is inside the window: this catches commit, checkout, and reset.
   
   Call the set of changed worktrees C.
4. **Attribution:** decide for each worktree w in C.
   - If the raw command contains w's path → the subagent changed it.
   - Otherwise, if w is the worktree of an open worker and that worker is `working` → **hold (pass)**. The worker itself may have edited it.
   - In any other case → the subagent changed it (no other actor could edit w at that time).
5. **Response:** if any w is attributed to the subagent, send OBSERVED_SUB through `additionalContext`. Its content is "You changed worktree `<w>`. Do not change more. Stop and return a HANDOFF. Write what you already changed in `done:`". By O2 nothing stops execution, so this relies on the instruction text.
6. **Background (O3):** on a PostToolUse that has `tool_response.backgroundTaskId`, no decision is made. Instead, append (start time, raw command) to `${TMPDIR}/herdr-pw-observe/<session_id>/<agent_id>.json`. At the same agent's next PostToolUse/PostToolUseFailure, widen the window start to the earliest start time in that record, and include those background commands in the raw command used by the attribution rule. After deciding, delete the record. If the agent stops using Bash, it is missed (known gap). Records older than 1 hour are deleted when the hook runs.
7. **Pass on failure:** a git error, a timeout, a missing `duration_ms`, and a record file error are all treated as no detection.

**Worker state check:** `herdr agent get <name>` is called only in attribution step 4, and only when there is no path mention and a runs.json worker worktree is in C.

### 12.4 Cost target
- With no workers and no linked worktrees: only python startup (about 40ms). The main session and the worker itself pay only this cost each time.
- Subagent Bash, 5 worktrees: the target is 0.3 seconds or less per PostToolUse (parallel git, no Pre). Measure it as L2c in the implementation step, and report if it is exceeded.

### 12.5 Known gaps (added to §7)
5. Writes are detected **after the fact**. The change from the first command remains. It is not reverted and is passed on through the HANDOFF's `done:`.
6. A write to the worktree of a `working` worker, in a way that does not show the path in the raw command, passes as a hold (avoiding false positives comes first).
7. A write by a background command is detected only when the same agent uses Bash next.
8. Bash writes by the main session and the worker itself are not observed (normal use).
9. ctime also changes on metadata changes (chmod, rename). These are treated as a worktree change. If a system process (such as a security tool that uses extended attributes) changes ctime inside the window, a false positive can occur.
10. Changes to files ignored by `.gitignore` (build outputs and so on) do not appear in `git status`, so they are not seen.

### 12.6 Verification additions
- **L1:** window calculation (`duration_ms`, 0.5-second slack, widening by the background record), the pure change-detection function (ctime inside/outside the window, re-modification, a write whose mtime is in the past like `cp -p`, the parent directory of a deletion, logs/HEAD), the attribution rule table (path mention × worker state), pass on failure, cleanup of background records
- **L2:** add C12 to C15 to live_hooks
  - C12: a subagent runs `echo > <other wt>/f` → receives OBSERVED_SUB, returns a HANDOFF
  - C13: re-modifying an already modified file with `sed -i` → detected
  - C14: a write that ends in failure (`…; false`) → detected in `PostToolUseFailure`
  - C15: a subagent writes to the worktree of its own `cwd` → passes
- **L2c:** measure the PostToolUse delay of one subagent Bash call with 5 worktrees, target 0.3 seconds

## 13. Revision: a write outside its own worktree goes to that worktree's owner (2026-10-07)

### 13.1 Principle
**If you write outside your own worktree, the owner of that worktree receives it. If there is no owner, a new one is created. The main session always does the delivery.** A child and a child's subagent are treated as the same scope. A child using subagents inside its own worktree (delegating test writing, review and fix plugins, and so on) stays allowed.

### 13.2 Writer × target

| Writer ↓ / target → | own worktree (`home`) | a sibling child's worktree (owner in runs.json) | the original repository's main checkout | a linked worktree with no owner |
|---|---|---|---|---|
| main | allowed | allowed | allowed | allowed |
| main's subagent | allowed | HANDOFF → main delivers to the owner child | allowed (main's home) | HANDOFF → main creates a new child (one confirmation) |
| child / child's subagent | allowed | report to main → main delivers to the owner child | report to main → **main tells the user and asks** | report to main → main creates a new child (one confirmation) |
| worktree creation (child / child's subagent) | blocked. So no worktree made by a child ever exists | | | |

The "owner" is found from the open records in runs.json by worktree path. The "main checkout" is the case where the target worktree is not a linked worktree (`git-dir == common-dir`) and its repository is the same as the child's repository.

### 13.3 Widening the detection scope
- **The child itself is also a detection target.** R4 of §5.3 (pre-blocking Write/Edit) and R7 of §12 (observing Bash results) also apply to the `worker` actor. The criterion is "outside home". Work inside home keeps passing and has no observation cost (home is excluded from the target set W).
- The child's observed set W also includes the main checkout. For the main-side actors the main checkout is home, so it is not a target.
- Block and detection messages include the target worktree's **owner name** (if any). The HANDOFF gets an added line `owner: <worker name | main-checkout | none>`.

### 13.4 The main session's delivery procedure (a new section in the skill)
When it receives a HANDOFF, or a report in a child's `## Result`, the main session acts by `owner`.
- **`owner: <worker>`**
  1. If that worker is open and its claude is alive, send a follow-up instruction. Use the same method as the first instruction: write the instruction to a file and send one line pointing at that file (a long paste may be rejected). If the worker is `working`, wait until it is `idle`/`done` and then send.
  2. If the worker was cleaned up or its session ended, resume it with `references/resume.md` and then send.
  
  This adds work to an existing worker, so it is shown to the user and confirmed within the same confirmation question, keeping the confirmation to one.
- **`owner: main-checkout`**: tell the user what changed (or tried to change) and the path as they are, and ask what to do. The main session does not apply or revert it on its own.
- **`owner: none`**: create a new child as in the existing flow (one confirmation).

### 13.5 Measured results (2026-10-07, scratch worker `scratch-fix`)

| # | Item | Result | Applied as |
|---|---|---|---|
| T3 | A follow-up instruction after resuming a cleaned-up worker | The workspace was closed but the worktree remained → reopen it with `herdr worktree open --cwd <root> --path <wt> --label <name>`, then `export HERDR_PW_WORKER` and `agent start … -- <workerArgs> --add-dir <BRIEFS> --resume <session_id>`. It came back with the same session_id. When the "one line pointing at a file" was sent with `agent prompt --wait`, it remembered the hook error sentence it had received in the earlier conversation and used it exactly | Delivery works after resuming. resume.md must cover the case where "the worktree remains and only the workspace is closed" (`worktree open`) |
| T1 | A one-line follow-up instruction to a live worker | The resumed worker above and the later T2 read the file and followed it all 3 times without refusing | deliver.md is "file + one-line `agent prompt`" |
| T2 | Sending to a working worker | Sent (21:00:08) while a 25-second loop was running. The loop finished without interruption (21:00:33), and the follow-up instruction was handled after it (21:00:38). No error and no refusal (queued). The flow of sending after `agent wait --until idle --until done` also worked | Default is deliver after waiting. If the wait times out, sending anyway is safe because it is queued |
| O8 | Parallel Bash hooks of one agent | The PostToolUse hooks of 2 parallel Bash calls ran at the same time (±0.01 seconds) | BgStore must use per-job files + rename ownership (safe under concurrency) |
| O9 | Cost of filtering out the main session | Shell guard (`IN=$(cat)`; bash 3.2): 1KB 12ms, 1MB 58ms, 10MB 467ms. python `-S` early exit (look for `"agent_id"` in the raw bytes and exit before parsing JSON if absent): 24 / 33 / 86ms | Use the python early exit instead of the shell guard. The worst case is bounded, and no shell escaping inside JSON is needed |

## 14. Rules settled by the implementation (2026-10-07, plan `docs/superpowers/plans/2026-10-07-observe-and-owner-routing.md`)

R7 of §12.3 was settled as follows during implementation. If §12.3 and this section differ, follow this section.

- **Attribution is "change + mention".** A worktree is attributed only when it actually changed inside the run-time window (ctime) and the command mentioned a path inside that worktree. The "judge by worker state when there is no mention" of §12.3-4 (the hold rule and the `herdr agent get` lookup) was removed. This is to avoid false positives from parallel subagents, the main session, and concurrent edits by the user (user decision).
- **With no mention, git is not called.** With no path token, the session directory lookup is not done either. Measured: a subagent's or worker's Bash with no mention took 54 to 56ms.
- **The index ctime is not used.** The index was rewritten every time another process ran a plain `git status` (measured). Instead, look at the ctime of the path the command mentioned (or, if it does not exist, the nearest existing parent directory) and at `logs/HEAD`. This catches `git restore f` and `git -C wt restore f`.
- **Filtering out the main session is done by python early exit (§13.5 O9).** The `pre-tool-use-write`, `post-tool-use-bash`, and `post-tool-use-failure` arguments end before importing json when the raw bytes have no `"agent_id"` and there is no `HERDR_PW_WORKER`.
- **The owner decision (§13.2) is made by `owners.py`.** It looks at runs.json before git, so a submodule inside a worker's worktree also belongs to that worker. In a `--separate-git-dir` repository git reports the git directory instead of the main checkout, so if verification fails it is treated as "unknown" (allowed).

§7 known gaps added:

11. A write whose path does not show in the command is missed (inside a script, or a path built in steps like `cd ..; cd b`).
12. A command that reads another worktree can be a false positive if it overlaps in the same time window with a write by another actor happening there at the same time. The window start is rounded down to a 1-second unit, so it widens by up to 1.5 seconds earlier.
13. A write that a daemonized child process (`nohup … &`) makes after the command ends is missed. A destructive command that touches neither the mentioned path nor logs/HEAD, such as `git -C wt stash` that touches only files in subdirectories, is also missed.
