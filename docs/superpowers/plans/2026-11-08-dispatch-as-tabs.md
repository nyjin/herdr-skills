# herdr-parallel-worktree: Per-Task Delegation as Tabs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Inside herdr, when another skill (SDD and others) dispatches a subagent per task, that work goes to herdr tabs by role (implement, review). The main session keeps the flow. The only direct tab-to-tab handoff is the fix → re-review step, and only when the brief allows it.

**Architecture:** The hooks point to one guide (`references/dispatch.md`) at two moments. When another skill is loaded, they add a single line of guidance. At the session's first task dispatch, they save the prompt to a file and deny once. `finalize-brief.py` builds the brief's Environment and On completion sections as options. The write hook (R4) judges, at runtime, paths outside the brief's Environment section and "a tab that sits in someone else's worktree". No new mapping file is added.

**Tech Stack:** Python 3 standard library, Claude Code hooks, herdr CLI, git.

**Spec:** The "Decisions" section below (user decisions of 2026-11-08). For background, see the discussion brief `~/.local/share/herdr-skills/herdr-parallel-worktree/briefs/discuss-sdd-routing-20261108.md`. For the earlier design, see `docs/superpowers/specs/2026-10-20-orchestrator-role-and-worker-tab-design.md`.

## Background

In the skills-98 session (11-02 to 11-08), the main session ran plan 44 as SDD inside herdr. Every per-task implementer and reviewer dispatch went to an Agent subagent (27 dispatch lines in the ledger). SKILL.md has a rule at the top, but it was read once early in the session, and right before acting only the SDD procedure was in front of the model. The hooks only blocked worktree-isolated Agents.

Counting the plan 44 ledger by stage gives the following. These numbers are the basis for D2.

| Stage | What the main session did |
|---|---|
| implement → review | In 7 of 10 tasks, a verdict, question or fix-up came in before review. Tasks that passed on straight away: 0/10 |
| review → fix | 10/10 went through a fix round. At least 11 verdicts, 48 lines of minor findings deferred to the ledger |
| fix → re-review | One clear intervention (T6 R31). Mechanical |
| re-review → next | T8b hit the 5/5 cap and the main session put 3 items on hold |

## Decisions

**Earlier decisions**
- A different role means a different tab. The reviewer goes in another tab of the implementer's workspace.
- The "whole plan in one worker" approach is not offered. Only the main session writes the ledger.
- Outside paths (ii): a worker writes only to the outside paths listed in the brief's Environment section. Its own repository's main checkout is blocked even if listed, and paths outside git are free to write.
- The handoff request is the brief. The hooks point to one guide only. A brief has three parts: Environment / Instructions / On completion (optional).

**Decisions of 2026-11-08**
- **D1 Enforcement:** When a skill is loaded, the hook only gives guidance and does not deny. It catches both paths (the Skill tool and `/name`). The session's first task dispatch is denied once, after the prompt is saved. The list of skills that get guidance lives in config `dispatchSkills`.
- **D2:** The only direct tab-to-tab handoff is fix → re-review. The other stages go through the main session.
- **D3:** Files the tabs share go in `$BRIEFS/<plan>/`.
- **D4:** Roles are found at runtime by the tab naming rule (`<plan>-impl`, `<plan>-rev`). `report-metadata` is not used.
- **D5:** The review tab is started under its own name, and `runs.json` records only the implement tab.
- **D6:** The only things that stop a worker are environment constraints and conflicts. These are nested workers and worktree creation, writing where another session works (another worker's worktree, the main checkout, another repository not in the brief), and sending to the main session's pane. Everything else is free, and there is no prohibition list for checking briefs.
- **D7:** No code is added to check hook registration. A changed hook is registered by running `manage.py on` once after the merge.
- **D8:** Test leftovers are removed after the lessons are recorded in this document (done).
- **D9:** The working and blocked branches get no further testing. The skill says "not verified".
- **Execution:** Split the work finely and verify each piece. Run it with subagents.

**Author decisions (confirmed with no objection)**
- The hook's deny text is written in the form "carry on".
- `finalize-brief.py` builds the Environment and On completion sections.
- The main session is notified by pull (background `agent wait`). Sending a prompt to the main pane is forbidden.
- The direct-handoff text is the text used in the test, unchanged.
- Correct the paste-in note in SKILL.md step 2.
- The R9 role text includes "a step the brief allows".

**Correction to the D5 rationale.** In the discussion we said "the current owner check blocks the review tab's writes". That was wrong. `write_target` lets a write inside the writer's own cwd worktree through before it looks at `runs.json` (`route.py:405-407`). It did not show up because the test's review tab never tried Write or Edit. So Task 6 adds "block it if the owner of its own cwd worktree has a different name". This prevents two tabs from editing the same files, so it falls within D6.

## Facts from the Test (2026-11-08)

We ran the worker → worker handoff test 3 times. We used a scratch repository, data isolated with `HERDR_SKILLS_DATA_HOME`, and one workspace holding an implement tab and a review tab. The test leftovers were removed after this section was written.

| What | What we confirmed |
|---|---|
| Loading a skill with the Skill tool | Both PreToolUse and PostToolUse fire. `tool_name: "Skill"`, `tool_input: {"skill": "superpowers:subagent-driven-development"}` |
| Loading a skill with `/name` | Only UserPromptSubmit fires. `prompt` is `/superpowers:subagent-driven-development <args>` unchanged, and the skill body arrives as a user message. We did not check whether UserPromptSubmit's `additionalContext` reaches the model (Task 11 checks) |
| One-line `herdr agent prompt` | 6/6 arrived as a normal user message with no `<pasted_content>` (main → review 3, implement → review 3). This matches the earlier note that a multi-line body goes as a paste |
| `agent prompt` to a pane with half-typed text in its input | It is appended after the half-typed text and submitted as one message. So we never send to the main pane |
| Direct handoff (fix → re-review) | Sent 3/3, received and handled 3/3 (all re-reviews APPROVED), main session's re-trace matched 3/3, status checked before sending 3/3. With the R9 role text in place: 2/3 (runs 2 and 3). The review tab started work 10 to 13 seconds before the implement tab finished its `## Result` |
| Time | Relay through the main session 7 to 24 seconds (including the session's reading and judging; the request was built by a script). Direct handoff: status check → send 3 to 4 seconds, send → working within 1 second |
| What is left even with a direct handoff | The implement tab's result raised something for the main session to decide (run 3, empty-key handling). The review tab left a note for the main session all 3 times: "the implement brief was missing a spec". A direct handoff does not remove the main session's reading of the Result |
| `report-metadata` | The pane id must come first (`herdr pane report-metadata <pane> --source <id> --display-agent X`). The `--k=v` form fails. The values do not show in get or list, only in `herdr api snapshot` as `display_agent` and `title` |
| Finding by name | `herdr agent get <name>` has `name`, and `tab list` has `label`. The implement tab found the review tab by this alone |
| Hook registration | `~/.claude/settings.json` had no SessionStart (registration lagged the code). So R9 was off in the real environment. `manage.py status` only reports `registered_in_settings: true` |
| Trust dialog | The `~/.claude.json` trust entry stayed at the repository path, not the worktree path. One click lets every worktree of that repository through |
| Test method | Creating tabs with `herdr tab create --env HERDR_PW_WORKER=… --env HERDR_SKILLS_DATA_HOME=…` keeps them from mixing with the real `runs.json`. `claude --settings <file>` can add hooks per tab (merged with the user's settings). Background `herdr agent wait` was enough to notify the main session |
| Other | The `__pycache__` the review tab made while running tests was a Bash write, so it was not blocked. This environment has no herdr plugin |

## Global Constraints

- Use only the Python standard library. Unit tests (all): `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v`. A subset: add `-k <name>` to the same command. Repository checks: `scripts/check.sh [check ...]`.
- **fail-open:** Exceptions, git or herdr errors, and file errors all produce no output. If the draft cannot be saved, the dispatch is not blocked.
- Outside herdr (`HERDR_ENV != 1`) or with `"hooks": "off"`, print nothing.
- `hooks/hooks.json` and `manage.hook_entries()` register the same set (`test_registration`).
- Skill files (SKILL.md, references, assets, scripts) are written in English (`test_language`). This plan was written in Korean.
- Do not ask the user before starting. Do not use the forbidden words of `test_no_pause`.
- Judge only by the tool call and its input. The one exception is UserPromptSubmit, where we check whether the prompt's first token is `/<a skill name in the list>`.
- Normalize paths with `os.path.realpath`, and judge containment with `owners.inside` (path separator boundary).
- Text marked "exactly as written" below is used character for character.
- The working branch is the branch of the worktree for the SDD work. Commit per task, and do not push.
- **Test isolation:** Unit tests do not touch the real `~/.local/share/herdr-skills` or the real `herdr`. Use the existing `NO_DATA` (`/nonexistent/...`) and temporary directories.

## Verification Model

| Layer | What it proves | How | When |
|---|---|---|---|
| L1 unit | Input → output of the judging functions and scripts | `unittest` (per task with `-k`, all at the end) | Every task |
| L1.5 repository checks | Registration set, hook execution path, closing paragraph, language and forbidden words, skill spec | `scripts/check.sh <check>` | Tasks that change registration, scripts or docs |
| L2 real Claude Code | Whether the hook output reaches a real session (deny, draft saving, guidance injection) | `tests/live_hooks.py` (fake herdr, `--settings`, isolated data) | Task 11 |
| L3 real use | Whether SDD flows into tabs inside herdr | When the next SDD plan runs in herdr (outside this plan) | After merge |

To say a requirement is verified, it must pass at the layer listed in the table below. Passing at a lower layer is not evidence for a higher one.

**Decision → task → confirming test**

| Decision | Task | Test |
|---|---|---|
| D1 stop the first dispatch once | 1, 11 | `FirstDispatchTest.*`, live `first_dispatch` |
| D1 guidance when a skill is loaded (Skill tool) + `dispatchSkills` | 2 | `SkillNoteTest.*`, `RegistrationTest.*` |
| D1 guidance when a skill is loaded (`/name`) | 3, 11 | `SlashNoteTest.*`, `EarlyExitTest.test_plain_prompt_stops_before_json`, live `slash_note` |
| Outside paths (ii): Environment section | 4 | `FinalizeTest.*`, `check.sh finalize-brief` |
| Outside paths (ii): reading declared paths | 5 | `DeclaredOutsideTest.*` |
| D5 and D6 a tab in someone else's worktree | 6 | `OtherTabsWorktreeTest.*` |
| (ii) and D6 another repository not in the brief | 7 | `OutsidePathTest.*` |
| D6 role text, no main pane, steps the brief allows | 8 | `SessionStartTest.test_role_texts` |
| D2, D3, D4, D5, D9, pull notification | 9 | `DispatchGuideTest.*` |
| Paste-in note correction, `dispatchSkills` doc, hook doc | 10 | `SkillTextTest.*`, `LanguageTest`, `NoPauseTest`, `check.sh` |
| D7 register once | after merge | the `jq` check in the after-merge step |

## Review Focus

1. **A first dispatch that must not be blocked.** If the first dispatch is for search (`Explore`, `Plan`, `claude-code-guide`), or comes from a plain session of a worker, a subagent or a linked worktree, do not block it and do not leave a mark → Task 1.
2. **The second one onward passes.** A second dispatch with the same `session_id` passes. The id stays the same after a resume or compact, so it is not blocked again → Task 1.
3. **The cost of UserPromptSubmit.** This hook fires on every prompt. A prompt that does not start with `/` must end without importing `json`, and a `/name` that is not in the list must produce no output → Task 3.
4. **Name prefix collisions when finding a brief.** Worker `proj` must not read `proj-101-…md` as its own brief → Task 5.
5. **Declared path matching.** Symbolic paths such as `/tmp` and `/private/tmp` count as the same, and `/o/out` must not count as containing `/o/outside` → Task 5, Task 7.

## File Structure

| File | What changes | Task |
|---|---|---|
| `skills/herdr-parallel-worktree/scripts/hooks/route.py` | First-dispatch stop, skill guidance, UserPromptSubmit early exit, R4 extension, role text | 1, 2, 3, 6, 7, 8 |
| `skills/herdr-parallel-worktree/scripts/hooks/owners.py` | `brief_files()`, `declared_outside()` | 5 |
| `skills/herdr-parallel-worktree/scripts/finalize-brief.py` | `--role --worktree --branch --outside --then` | 4 |
| `skills/herdr-parallel-worktree/scripts/hooks/manage.py`, `hooks/hooks.json` | `Skill` in the PostToolUse matcher, UserPromptSubmit group | 2, 3 |
| `skills/herdr-parallel-worktree/references/config.schema.json` | `dispatchSkills` | 2 |
| `skills/herdr-parallel-worktree/references/dispatch.md` (new file) | The one guide the hooks point to | 9 |
| `SKILL.md`, `references/brief-filling.md`, `references/deliver.md` | Body updates | 10 |
| `skills/herdr-parallel-worktree/tests/` | `test_route.py`, `test_registration.py`, `test_owners.py`, new `test_finalize.py`, `test_dispatch_guide.py`, `test_skill_text.py`, `live_hooks.py` | each task |
| `scripts/check.sh` | `check_hooks`, `check_finalize_brief` | 3, 4 |
| `.claude-plugin/plugin.json` | Version 0.8.0 | 12 |

---

### Task 1: Stop the session's first task dispatch once and save the prompt

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/hooks/route.py` (the PreToolUse branch of `decide()`, new functions)
- Test: `skills/herdr-parallel-worktree/tests/test_route.py` (new `FirstDispatchTest`)

**Interfaces:**
- Produces:
  - `route.SKILL_DIR: str`: absolute path of the skill directory (three levels up from `route.py`)
  - `route.GUIDE: str = os.path.join(SKILL_DIR, "references", "dispatch.md")`. Task 9 creates the file.
  - `route.READ_ONLY_AGENTS = ("Explore", "Plan", "claude-code-guide")`
  - `class route.DispatchStore(path: str)`: `.seen(session_id: str) -> bool`, `.mark(session_id: str) -> None`. One file per session, and it never raises. The default location is `tempfile.gettempdir()/herdr-pw-dispatch`.
  - `route.save_draft(env, session_id: str, tool_input: dict, now=time.time) -> str | None`: writes to `$DATA_DIR/briefs/dispatch-<session_id[:8]>-<YYYYmmdd-HHMMSS>.md` and returns the path. Returns None on failure. The file content is `# Dispatch draft`, then the lines `- subagent_type: …`, `- model: …`, `- description: …`, then `## Prompt` and the prompt verbatim.
  - `route.deny_first_dispatch(draft: str) -> str`
  - `route.decide(..., store=None, save=None)`: None means use the real implementation.

Deny text (exactly as written, fill in only `{draft}` and `{GUIDE}`):
```
Inside herdr, the user installed these hooks so that a task handed to another agent runs as a herdr tab they can watch, not as a hidden subagent. Nothing is lost: this dispatch (description, model and prompt) is saved at {draft}. Read {GUIDE} and start the tab with that file as the brief's instructions, then carry on with the user's request from where you were. Do not ask the user first, and do not suggest turning the hooks off. This happens once per session: a search or a question you meant for a subagent can be sent again unchanged.
```

- [ ] **Step 1: Write the failing tests** (`FirstDispatchTest`; pass `decide` a `set`-based fake store and a fake save that returns a fixed path)
  - `test_first_task_dispatch_is_stopped_once`: `MAIN_ENV`, cwd `/r`, `Agent(subagent_type="general-purpose", description="Task 3", prompt="Implement Task 3")`.
    - The first call is a deny, and the reason equals the text above with `{draft}="/d/briefs/dispatch-s-1.md"` filled in.
    - Calling again with the same `session_id` gives `None`.
  - `test_saved_draft_keeps_the_prompt_verbatim`: give the real `save_draft` a temporary `HERDR_SKILLS_DATA_HOME`. The file holds the multi-line prompt (including backticks and `$VAR`) character for character, and has the `subagent_type`, `model` and `description` lines. The file name matches `dispatch-[0-9A-Za-z_-]{1,8}-\d{8}-\d{6}\.md`.
  - `test_read_only_agents_pass_without_marking`: for each of `READ_ONLY_AGENTS`, the result is `None` and the store is empty.
  - `test_others_pass`: `WORKER_ENV`, `sub=True`, and a main session with cwd `/w/a` (a linked worktree) all give `None` and the store is empty.
  - `test_unsaved_draft_does_not_block`: when save returns `None`, the result is `None` and the store is empty.
  - `test_worktree_isolation_keeps_its_own_deny`: a main Agent with `isolation="worktree"` still gets `DENY_MAIN_AGENT`, as now.
  - `test_store_survives_bad_dir`: for a `DispatchStore` on an unwritable path (`/nonexistent/x`), `seen` is False and `mark` finishes without an exception.
- [ ] **Step 2: Confirm the failure.** Run: `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -k FirstDispatch -v` → FAIL (no `DispatchStore`)
- [ ] **Step 3: Implement.** In PreToolUse of `decide()`, put it after the `creates_worktree` branch.
  - Condition: `tool in ("Agent", "Task")`, `who == "main"`, `args.get("subagent_type") not in READ_ONLY_AGENTS`, and cwd is the main checkout (`[0] == [1]` of `probe(cwd)`, the same rule as SessionStart).
  - If the session is already marked, return None. Otherwise call `save(...)`. If a path comes back, `mark` and then deny. If None, return None.
- [ ] **Step 4: Verify**
  - `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -k FirstDispatch -v` → all 7 OK
  - All unit tests → OK. Existing tests fail to save because of `NO_DATA`, so their results must not change. A changed test is a defect in this task.
  - `scripts/check.sh hooks` → OK
- [ ] **Step 5: Commit.** `feat: stop a session's first task dispatch once and save it as a tab brief draft`

### Task 2: Guide pointer when loading via the Skill tool + `dispatchSkills` setting

**Files:**
- Modify: `route.py`, `scripts/hooks/manage.py` (`hook_entries`), `hooks/hooks.json`, `references/config.schema.json`
- Test: `tests/test_route.py` (new `SkillNoteTest`), `tests/test_registration.py`

**Interfaces:**
- Consumes: `route.GUIDE` (Task 1)
- Produces:
  - `route.DISPATCH_SKILLS = ("superpowers:subagent-driven-development", "superpowers:dispatching-parallel-agents")`
  - `route.read_config(env) -> dict`: `{}` on error. `enabled()` uses it.
  - `route.dispatch_skills(cfg: dict) -> tuple[str, ...]`: if `cfg["dispatchSkills"]` is an array of strings, that tuple; otherwise `DISPATCH_SKILLS`.
  - `route.note_dispatch_skill(skill: str) -> str`
  - `route.decide(..., cfg=None)`: None means `read_config(env)`.
  - `hook_entries()` and `hooks.json`: change the matcher of the first PostToolUse group to `"Agent|Task|EnterWorktree|ExitWorktree|Skill"`.
  - Config key `dispatchSkills`: an array of strings, default the two names above. In the schema: `"type": "array"`, `"items": {"type": "string"}`, `"default"`, and a one-line description. Keep `additionalProperties: false`.

Guidance text (exactly as written):
```
Inside herdr, {skill} hands each task to an agent; here each of those agents runs as a herdr tab the user can watch. Before the first dispatch, read {GUIDE}.
```

- [ ] **Step 1: Write the failing tests**
  - `SkillNoteTest.test_skill_tool_load_adds_note`: main session PostToolUse `Skill`, `tool_input={"skill": "superpowers:subagent-driven-development"}` → `hookEventName == "PostToolUse"`, `additionalContext == note_dispatch_skill("superpowers:subagent-driven-development")`, and `route.GUIDE` is inside it.
  - `test_other_skill_gets_nothing`: `{"skill": "superpowers:brainstorming"}` → `None`.
  - `test_worker_and_subagent_get_nothing`: the same input with `WORKER_ENV` or `sub=True` gives `None`.
  - `test_config_list_replaces_default`: `dispatch_skills({"dispatchSkills": ["my:skill"]}) == ("my:skill",)`. `{"dispatchSkills": "x"}`, `{"dispatchSkills": [1]}` and `{}` give `DISPATCH_SKILLS`. With `decide(..., cfg={"dispatchSkills": ["my:skill"]})`, only `my:skill` gets guidance.
  - `test_read_config_never_raises`: a missing path, broken JSON, or array JSON gives `{}`.
  - `RegistrationTest`: change the PostToolUse key in `ARGS` to the new matcher, and change the PostToolUse list in `test_expected_matchers` to `["Agent|Task|EnterWorktree|ExitWorktree|Skill", "Bash"]`.
- [ ] **Step 2: Confirm the failure.** `-k SkillNote` and `-k Registration` → FAIL
- [ ] **Step 3: Implement.** Add a `tool == "Skill" and who == "main"` branch to PostToolUse in `decide()` (separate from the NOTE_HANDOFF branch). Fix `hooks.json` and `hook_entries()` together.
- [ ] **Step 4: Verify**
  - `-k SkillNote` → OK, `-k Registration` → OK
  - All unit tests → OK
  - `scripts/check.sh hooks` → OK
  - `jq -e '.properties.dispatchSkills.default | length == 2' skills/herdr-parallel-worktree/references/config.schema.json` → true
- [ ] **Step 5: Commit.** `feat: point the main session to the dispatch guide when it loads a dispatching skill`

### Task 3: Guide pointer when loading via `/name` (UserPromptSubmit)

**Files:**
- Modify: `route.py` (early-exit block, `ALL_ARGS`, `EVENT_OF_ARG`, `decide()`), `manage.py`, `hooks/hooks.json`, `scripts/check.sh` (`check_hooks`)
- Test: `tests/test_route.py` (new `SlashNoteTest`, extend `EarlyExitTest`), `tests/test_registration.py`

**Interfaces:**
- Consumes: `route.dispatch_skills`, `route.note_dispatch_skill`, `route.read_config` (Task 2)
- Produces:
  - Add `"user-prompt-submit"` to `route.ALL_ARGS` and set `EVENT_OF_ARG["user-prompt-submit"] = "UserPromptSubmit"`. Leave `NON_MAIN_ARGS` as it is.
  - `"UserPromptSubmit": [group(None, "user-prompt-submit")]` in `hook_entries()` and `hooks.json`
  - `route.slash_skill(prompt: str) -> str | None`: if the prompt with leading whitespace removed starts with `/`, the first token with the `/` stripped; otherwise None

- [ ] **Step 1: Write the failing tests**
  - `SlashNoteTest.test_slash_prompt_adds_note`: `{"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": "/r", "prompt": "/superpowers:subagent-driven-development go"}`, `MAIN_ENV` → `hookEventName == "UserPromptSubmit"`, `additionalContext == note_dispatch_skill("superpowers:subagent-driven-development")`
  - `test_other_or_plain_prompt_gets_nothing`: `"/superpowers:brainstorming"`, `"hello /superpowers:subagent-driven-development"`, `""` → `None`
  - `test_worker_gets_nothing`: the same slash prompt with `WORKER_ENV` → `None`
  - `test_slash_skill`: `slash_skill("  /a:b c") == "a:b"`, `slash_skill("/a") == "a"`, `slash_skill("a /b") is None`, `slash_skill("/") is None`
  - `EarlyExitTest.test_plain_prompt_stops_before_json`: `run_route("user-prompt-submit", '{"prompt": "hello"}')` → output `""`, `json` not imported. `'{"prompt": "/superpowers:subagent-driven-development"}'` → `json` imported.
  - `RegistrationTest`: add `("UserPromptSubmit", None): "user-prompt-submit"` to `ARGS`. Add `[g.get("matcher") for g in self.plugin["UserPromptSubmit"]] == [None]` to `test_expected_matchers`.
- [ ] **Step 2: Confirm the failure.** `-k SlashNote`, `-k EarlyExit`, `-k Registration` → FAIL
- [ ] **Step 3: Implement.**
  - Early-exit block at the top: if the argument is `user-prompt-submit`, read the raw input, and if `re.search(rb'"prompt"\s*:\s*"\s*/', raw)` finds nothing, `sys.exit(0)`.
  - `decide()`: when `hook == "UserPromptSubmit"` and `who == "main"`, return the guidance if `slash_skill(event.get("prompt") or "")` is in the list.
  - `check.sh check_hooks`: add `.hooks.UserPromptSubmit` to the jq condition, and check in one line that feeding `{"prompt":"hello"}` under `HERDR_ENV=1` gives empty output.
- [ ] **Step 4: Verify**
  - `-k SlashNote`, `-k EarlyExit`, `-k Registration` → OK
  - All unit tests → OK
  - `scripts/check.sh hooks` → OK
  - Direct run: `echo '{"prompt":"hello"}' | HERDR_ENV=1 HERDR_SKILLS_DATA_HOME=/nonexistent python3 -S skills/herdr-parallel-worktree/scripts/hooks/route.py user-prompt-submit` → no output
- [ ] **Step 5: Commit.** `feat: point the main session to the dispatch guide when the user types a dispatching skill`

### Task 4: The brief's Environment and On completion sections (`finalize-brief.py`)

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/finalize-brief.py`, `scripts/check.sh` (`check_finalize_brief`)
- Create: `skills/herdr-parallel-worktree/tests/test_finalize.py` (`FinalizeTest`)

**Interfaces:**
- Produces:
  - CLI: `finalize-brief.py BRIEF [--role TEXT] [--worktree PATH] [--branch NAME] [--outside PATH REASON]... [--then FILE]` (`--outside` is `nargs=2`, `action="append"`). With no options it behaves exactly as it does now.
  - Environment section format (exactly as written). Write only the lines for the options given, and drop the parentheses if there is no `--branch`.
    ```
    ## Environment

    - Role: <role>
    - Worktree: `<path>` (branch `<branch>`)
    - Outside path: `<absolute path>` — <reason>
    ```
  - Position: `## Environment` goes right after the first `# ` line (at the very top if there is none). `## On completion` (the content of the `--then` file) goes right before the closing paragraph (TAIL). If a section with the same title already exists, it is replaced.
  - Checks: if an `--outside` path is not absolute, or the `--then` file is missing or empty, exit 1 and do not touch the file.
  - Task 5 reads this format.

- [ ] **Step 1: Write the failing tests** (`FinalizeTest`, run the script as a subprocess)
  - `test_environment_follows_the_title`: for a brief `# [t] x\n\n## Goal\ndone\n` with `--role reviewer --worktree /w/a --branch b --outside /o/data "shared output"` → the section right after the title matches the format above character for character.
  - `test_rerun_replaces_sections`: running twice with the same options and `--then` still leaves exactly one `## Environment` and one `## On completion`.
  - `test_on_completion_sits_before_the_closing_paragraph`: the last line is TAIL, the section right before it is `## On completion`, and its content equals the `--then` file.
  - `test_relative_outside_path_fails`: `--outside rel "x"` → exit 1, file unchanged.
  - `test_missing_or_empty_then_fails`: a missing file or an empty file → exit 1, file unchanged.
  - `test_no_options_keeps_todays_output`: the result of a run with no options equals the current script's result (write the expected output into the test before implementing).
- [ ] **Step 2: Confirm the failure.** `-k Finalize` → FAIL
- [ ] **Step 3: Implement.** Section replacement treats everything from a level-2 heading up to the next heading of the same or higher level as one section (the same rule as the existing `check()`). Order: strip comments → strip the existing TAIL → insert sections → `check()` → append TAIL.
- [ ] **Step 4: Verify**
  - `-k Finalize` → 6 OK
  - All unit tests → OK
  - `scripts/check.sh finalize-brief` → OK. Add one line to this check: "giving `--outside` creates an `## Environment` section".
- [ ] **Step 5: Commit.** `feat: let finalize-brief write the brief's environment and completion sections`

### Task 5: Read the outside paths a brief declares (`owners.py`)

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/hooks/owners.py`
- Test: `tests/test_owners.py` (new `DeclaredOutsideTest`)

**Interfaces:**
- Consumes: the Environment section format of Task 4
- Produces:
  - `owners.brief_files(briefs_dir: str, name: str) -> list[str]`: only files whose name matches `^{re.escape(name)}-(followup-)?\d{8}-\d{6}\.md$`, sorted.
  - `owners.declared_outside(briefs_dir: str, name: str, realpath=os.path.realpath) -> list[str]`: the paths from the ``^- Outside path: `([^`]+)` `` lines in the `## Environment` section of those files, passed through realpath. Never raises.

- [ ] **Step 1: Write the failing tests**
  - `test_brief_files_ignore_longer_names`: in a temporary directory with `proj-20261108-120000.md`, `proj-followup-20261108-130000.md`, `proj-101-20261108-120000.md`, `proj-20261108-120000-ref.md` → `brief_files(d, "proj")` returns only the first two.
  - `test_round_trip_with_finalize`: `<d>/w1-20261108-120000.md` made with `finalize-brief.py --outside <tmp>/o "r"` → `declared_outside(d, "w1") == [os.path.realpath(<tmp>/o)]`. On macOS, a path under `tempfile.gettempdir()` must equal the `/private/...` realpath.
  - `test_outside_lines_elsewhere_are_ignored`: a `- Outside path:` line outside the `## Environment` section (for example under `## Steps`) is not read.
  - `test_never_raises`: a missing directory or an unreadable file → `[]`.
- [ ] **Step 2: Confirm the failure.** `-k DeclaredOutside` → FAIL
- [ ] **Step 3: Implement.** Use only the standard library `re` and `os`.
- [ ] **Step 4: Verify.** `-k DeclaredOutside` → 4 OK. All unit tests → OK.
- [ ] **Step 5: Commit.** `feat: read the outside paths a worker's briefs declare`

### Task 6: A tab in someone else's worktree cannot write (R4 extension a)

**Files:**
- Modify: `route.py` (`write_target`, a new text function)
- Test: `tests/test_route.py` (new `OtherTabsWorktreeTest`)

**Interfaces:**
- Consumes: `owners.run_owning` (existing)
- Produces: `route.deny_not_your_worktree(name: str, home: str, owner: str) -> str`

Rule: for the side with `HERDR_PW_WORKER=name` (worker, worker-sub), if its cwd worktree is the worktree of an open run and that run's name differs from `name`, block Write and Edit inside it. The main session and its subagents stay as they are now.

Text (exactly as written):
```
You are herdr tab `{name}`, working in `{home}`, which belongs to `{owner}`. Only `{owner}` writes here, so two tabs never edit the same files. Do not change files here, and do not retry another way; put what should change in your `## Result` or your verdict file instead.
```

- [ ] **Step 1: Write the failing tests** (runs `[{"name": "p-impl", "worktree": "/w/a", "state": "open"}]`)
  - `test_reviewer_tab_cannot_write_in_the_implementers_worktree`: env `HERDR_PW_WORKER=p-rev`, cwd `/w/a`, `Write /w/a/x.py` → deny, and the reason equals `deny_not_your_worktree("p-rev", "/w/a", "p-impl")`.
  - `test_its_subagent_too`: the same input with `sub=True` → deny.
  - `test_owner_tab_writes_its_worktree`: env `p-impl` → `None`.
  - `test_unrecorded_worktree_unchanged`: no runs, env `p-rev`, cwd `/w/a` → `None` (current behavior kept).
- [ ] **Step 2: Confirm the failure.** `-k OtherTabsWorktree` → FAIL
- [ ] **Step 3: Implement.** Right before `write_target` lets a write through as "inside home", judge with `owners.run_owning(home_top, runs)`.
- [ ] **Step 4: Verify.** `-k OtherTabsWorktree` → 4 OK. All unit tests → OK. If a `SpecMatrixTest` cell changes, check that it is a cell this rule covers and update it to match.
- [ ] **Step 5: Commit.** `feat: keep a tab from writing in another tab's worktree`

### Task 7: No writes to another repository not in the brief (R4 extension b)

**Files:**
- Modify: `route.py` (`write_target`, `decide(..., declared=None)`, a new function)
- Test: `tests/test_route.py` (new `OutsidePathTest`; add `"/o": ("/o/.git", "/o/.git", "/o")` to `FAKE`)

**Interfaces:**
- Consumes: `owners.declared_outside` (Task 5)
- Produces:
  - `route.briefs_dir(env) -> str`: `$DATA_DIR/briefs`
  - `route.deny_undeclared(name: str, top: str) -> str`
  - `route.decide(..., declared=None)`: `declared(name) -> list[str]`. None means `owners.declared_outside(briefs_dir(env), name)`.

Rule (only for the side with `HERDR_PW_WORKER`):
  - If `owner_of` is None and `probe(target)` finds a git checkout (another repository), the write passes only when the target is inside one of the `declared(name)` paths. Otherwise `deny_undeclared`.
  - Paths outside git pass, as now.
  - Its own repository's main checkout is blocked even if declared, as now.

Text (exactly as written):
```
You are herdr tab `{name}`. `{top}` is another repository, and your brief does not list this path under outside paths; another session may be working there. Do not write it, and do not retry another way. Finish the rest of your task, and say in your `## Result` which path you needed and why, so the orchestrator can add it to your brief.
```

- [ ] **Step 1: Write the failing tests** (worker env `w1`, cwd `/w/b`)
  - `test_undeclared_other_repo_is_denied`: `declared=lambda n: []`, `Write /o/f` → deny, and the reason equals `deny_undeclared("w1", "/o")`.
  - `test_declared_other_repo_passes_on_boundaries`: `declared=lambda n: ["/o/out"]` → `/o/out/f` is `None`, `/o/outside/f` is deny.
  - `test_outside_git_stays_free`: `/x/f` → `None`.
  - `test_declared_main_checkout_still_denied`: `declared=lambda n: ["/r"]`, `Write /r/f` → deny (main-checkout text).
  - `test_worker_subagent_follows_the_same_rules`: for the deny cases above, `sub=True` → deny.
  - `test_main_session_and_its_subagents_unchanged`: `/o/f` with `MAIN_ENV` → `None`, and with `sub=True` also `None`.
- [ ] **Step 2: Confirm the failure.** `-k OutsidePath` → FAIL
- [ ] **Step 3: Implement.** Call `probe(path)` one more time only when `own is None` (it is an uncommon case, so the extra git call is fine).
- [ ] **Step 4: Verify.** `-k OutsidePath` → 6 OK. All unit tests → OK. If a `SpecMatrixTest` cell where a worker writes to another repository changes from `None` to deny, update it as a change due to this rule.
- [ ] **Step 5: Commit.** `feat: keep tabs out of repositories their brief does not list`

### Task 8: Role text (worker, main)

**Files:**
- Modify: `route.py` (`role_worker`, `ROLE_MAIN`)
- Test: `tests/test_route.py` (`SessionStartTest.test_role_texts`)

**Interfaces:** Nothing to hand over to other tasks.

`role_worker(name)` (exactly as written):
```
You are herdr worker `{name}`. Your brief says where you work and what you may touch outside it. Do not start workers or create worktrees: herdr runs you in a tab, and nested workers break it. Do not write where another session works (another worker's worktree, the main checkout, or a repository your brief does not list); anything needed there goes back to the orchestrator in your `## Result`, as a HERDR-HANDOFF block when it is code work. Never send anything to the orchestrator's pane: it is the user's conversation. A step your brief tells you to take, such as sending a re-review request to another tab, is yours to take. If your brief asks for something this rules out, say so in your `## Result` instead of doing it.
```
`ROLE_MAIN`: put ` (see the skill's references/dispatch.md)` right after `that dispatch is a worker` in the current sentence. Leave the rest as it is.

- [ ] **Step 1: Write the failing tests.** Update `test_role_texts`.
  - Worker text: it contains `` `w1` ``, `HERDR-HANDOFF`, `"orchestrator's pane"`, `"brief tells you to take"`, `"nested workers"`.
  - Main text: it contains `"references/dispatch.md"`, and the existing checks (`even a single ticket`, `route.SKILL`, `that dispatch is a worker`) still pass.
  - Neither text has `confirm` or `` `! `` (existing check).
- [ ] **Step 2: Confirm the failure.** `-k SessionStart` → FAIL
- [ ] **Step 3: Implement.** Change the text only.
- [ ] **Step 4: Verify.** `-k SessionStart` → OK. All unit tests → OK. `scripts/check.sh hooks` → OK (including the session-start role output check).
- [ ] **Step 5: Commit.** `feat: tell workers what conflicts to avoid and that brief-authorized steps are theirs`

### Task 9: One guide (`references/dispatch.md`)

**Files:**
- Create: `skills/herdr-parallel-worktree/references/dispatch.md`, `skills/herdr-parallel-worktree/tests/test_dispatch_guide.py` (`DispatchGuideTest`)

**Interfaces:**
- Consumes: the `route.GUIDE` path (Task 1), the `finalize-brief.py` options (Task 4), the naming rule (D4)

What the guide holds (English, in this order, each item short):
1. **When this applies:** when the hook stopped the first dispatch, when the guidance appeared as a skill loaded, and when another skill dispatches an agent per task inside herdr. Exploration and research subagents stay subagents.
2. **Tabs per role:**
   - One workspace per plan. Make it with SKILL.md steps 1 to 3, and name it `<plan>`.
   - The implement tab is `<plan>-impl`, and it is recorded with `runs.py add`.
   - The review tab is `<plan>-rev`, started in the same workspace with `worker-pane.py --name <plan>-rev --since <now>`. It is not recorded. The review tab also does the re-review.
   - If another skill asks for a new agent (for example a stronger model), start a new tab (`<plan>-impl2`) in the same workspace with that model (`--model`).
   - Tasks pile up on the plan branch, and the next task goes to the same implement tab as a follow-up (`deliver.md`).
   - The review tab cannot write in the implement tab's worktree (the hook blocks it).
3. **Files:** Reports, review bundles and verdicts go in `$BRIEFS/<plan>/`. Another skill's ledger stays where it is, and only the orchestrator writes it.
4. **The brief:**
   - For the instructions section, put in the saved dispatch draft or the other skill's prompt as it is. No template is used.
   - Give `finalize-brief.py` `--role`, `--worktree`, `--branch`, and `--outside "$BRIEFS/<plan>" "shared review folder"`. If the work needs to write in another repository, add that path and the reason with `--outside`.
   - Use `--then` only when handing off fix → re-review. With no on-completion action, reporting to the orchestrator is the default.
5. **The one direct hop:** Only fix → re-review is handed off directly. Include the `--then` file example as it is.
   - After committing, write `$BRIEFS/<plan>/rereview-request-<n>.md` (scope, findings file, spec, test command, verdict path).
   - Check the status with `herdr agent get <plan>-rev | jq -r .result.agent.agent_status`. If idle, done or working, send with `herdr agent prompt <plan>-rev "[<plan>-impl] Re-review request: read <file> and follow it." --wait --until working --timeout 15000`. If blocked, do not send.
   - Leave a `Handoff` line in the `## Result`, and do not wait for the re-review.
6. **Waiting:**
   - The orchestrator runs `herdr agent wait <name> --until idle --until done --until blocked --timeout <ms>` in the background (in Claude Code with run_in_background, and a notification comes when it ends).
   - Read the `## Result` and cross-check it with `herdr agent get` and the files. The orchestrator counts the fix rounds.
   - Never send to the orchestrator pane. It would be submitted together with the user's half-typed text (confirmed in the test).
7. **Not verified:** A direct handoff while the review tab is working seems to go into a queue (orchestrator → worker was tested). If blocked, herdr refuses it with `agent_blocked` (per the help text).

- [ ] **Step 1: Write the failing tests** (`DispatchGuideTest`)
  - `test_guide_is_where_the_hooks_point`: `os.path.isfile(route.GUIDE)`
  - `test_names_the_contract`: the body has all of `<plan>-impl`, `<plan>-rev`, `$BRIEFS/<plan>/`, `finalize-brief.py`, `--outside`, `--then`, `--role`, `agent wait`, `run_in_background`, `Not verified`, `agent_blocked`.
  - `test_only_one_direct_hop`: every line where `herdr agent prompt` appears contains `Re-review request` (there is no other direct-send example).
  - `test_finalize_options_in_the_guide_exist`: the `--role`, `--worktree`, `--branch`, `--outside` and `--then` that appear in the guide are all in the output of `finalize-brief.py --help`.
- [ ] **Step 2: Confirm the failure.** `-k DispatchGuide` → FAIL (no file)
- [ ] **Step 3: Write the guide.**
- [ ] **Step 4: Verify.** `-k DispatchGuide` → 4 OK. `-k Language`, `-k NoPause` → OK. All unit tests → OK.
- [ ] **Step 5: Commit.** `docs: one guide for running per-task dispatch as tabs`

### Task 10: Skill body (SKILL.md, brief-filling.md, deliver.md)

**Files:**
- Modify: `SKILL.md`, `references/brief-filling.md`, `references/deliver.md`
- Create: `skills/herdr-parallel-worktree/tests/test_skill_text.py` (`SkillTextTest`)

**Interfaces:**
- Consumes: the keys, options and guide path from Tasks 1 to 9

SKILL.md:
- Make the "When another skill says to dispatch …" sentence in the first paragraph point to `references/dispatch.md`.
- Add a `dispatchSkills` row to the Configuration table, change the key list of the jq check to `["workerArgs", "hooks", "dispatchSkills"]`, and add an array check.
- Hooks section:
  - Add two items: guidance when a skill is loaded (two paths, the Skill tool and `/name`), and stopping the first task dispatch once (draft saved, search agents excepted).
  - To the "Writing outside" item, add another repository not in the brief and a tab in someone else's worktree.
  - Match the role item to the new worker text.
- Step 2, first item: a multi-line body arrives as pasted content, and a one-line one arrives as a normal user message (tested). So send the instructions that follow as a file plus one line.
- In the Never list, change the rationale of the `Send the first instructions with agent prompt` item to the same content.

`brief-filling.md`:
- Add a row "Environment and On completion sections | the skill | `finalize-brief.py` options" to the first table.
- Put an option example in section 4, and say that the two headings are written by the script, so the template does not hold them.

`deliver.md` step 5: add one sentence saying that a one-line prompt arrives as a normal message (tested).

- [ ] **Step 1: Write the failing tests** (`SkillTextTest`)
  - `test_config_keys_match_the_schema`: the key list of the SKILL.md jq check (inside `keys - [...]`) equals the set of `properties` keys of `config.schema.json`.
  - `test_config_table_lists_every_key`: the Configuration table has every key of the schema.
  - `test_skill_points_to_the_guide`: SKILL.md has `references/dispatch.md`.
  - `test_hooks_section_names_both_load_paths`: the Hooks section has `Skill` and `UserPromptSubmit`.
  - `test_finalize_options_documented`: `brief-filling.md` has `--outside` and `--then`.
- [ ] **Step 2: Confirm the failure.** `-k SkillText` → FAIL
- [ ] **Step 3: Fix the body.**
- [ ] **Step 4: Verify.** `-k SkillText` → 5 OK. `-k Language`, `-k NoPause` → OK. All unit tests → OK. `scripts/check.sh skill-spec names readme manifests` → OK (a skip is allowed if `gh skill` is missing).
- [ ] **Step 5: Commit.** `docs: document the dispatch hooks, brief sections and the one-line prompt finding`

### Task 11: Check with real Claude Code (L2)

**Files:**
- Modify: `skills/herdr-parallel-worktree/tests/live_hooks.py`

**Interfaces:**
- Consumes: the hooks of Tasks 1 to 3

- [ ] **Step 1: Add two checks.** Use the existing method as it is (fake herdr, register `hook_entries` with `--settings`, isolated data directory, hook log).
  - `first_dispatch`: give the prompt "Have a general-purpose subagent run `echo hi`".
    - PASS condition: the hook log has a deny for the first Agent PreToolUse. The prompt is in `briefs/dispatch-*.md` of the isolated data. A dispatch sent again in the same session has no deny.
    - If the model did not try a dispatch, INCONCLUSIVE.
  - `slash_note`: allow the Skill tool only in this check, and run `claude -p "/superpowers:subagent-driven-development Reply only with the path of any guide you were told to read."`.
    - PASS condition: the hook log has UserPromptSubmit output, and the answer has `dispatch.md`.
    - If it is only in the log and not in the answer, INCONCLUSIVE. If the superpowers plugin is absent, SKIP.
- [ ] **Step 2: Verify.** Run: `python3 skills/herdr-parallel-worktree/tests/live_hooks.py --model sonnet` → both the existing checks and the new checks PASS. If INCONCLUSIVE, run once more. Paste the result output into the report file.
- [ ] **Step 3: Commit.** `test: live-check the first-dispatch stop and the slash-load note`

### Task 12: Version and final check

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1:** Raise `"version"` to `"0.8.0"`.
- [ ] **Step 2: Verify.**
  - All unit tests → OK
  - `scripts/check.sh` → all checks OK (a skip is allowed if `gh skill` is missing)
  - `git log --oneline <start commit>..HEAD` → at least one commit per task
- [ ] **Step 3: Commit.** `chore: bump to 0.8.0`

## After the merge (after the user confirms)

- **D7 registration, once:** The installed copy (`~/.claude/skills/herdr-parallel-worktree`) points to the main checkout, so run this once after the merge. Tell the user that `~/.claude/settings.json` will be changed and where the backup is.

  Run: `python3 ~/.claude/skills/herdr-parallel-worktree/scripts/hooks/manage.py on --skill-dir ~/.claude/skills/herdr-parallel-worktree`

  Check: `jq '.hooks | keys' ~/.claude/settings.json` has `SessionStart` and `UserPromptSubmit`, and the PostToolUse matcher has `Skill`.
- **What to watch in the first L3 real use:**
  - Does the first dispatch move on to tabs naturally (does it carry on without asking the user)?
  - Does the review tab ever get blocked while trying to write?
  - Does the implement tab hand off fix → re-review, and does the main session keep track of the rounds?
  - A concern with evidence: in the L2 check of Task 11, the model under `claude -p` (no herdr) stopped after the first dispatch was denied and did not send it again. That made 7 existing checks undecidable, and we fixed it by adding "if denied, send it once more" to the instructions. In real herdr, watch whether the main session reads `dispatch.md` and opens tabs by SKILL.md steps 0 to 3, and whether it sends a normal, non-search dispatch again unchanged. If it stops, the thing to fix is the deny text, not the hook.
- **L3 measurement (2026-11-09, before the merge):** We ran it 4 times with an orchestrator started in a herdr tab. This branch's hooks were attached with `--settings`, data was kept separate with `HERDR_SKILLS_DATA_HOME`, and the workers got the same settings through `workerArgs`.

  | Run | Hooks | Request | Result |
  |---|---|---|---|
  | 1 | all | SDD plan (1 task) | Skill guidance → `dispatch.md` → implement tab → review tab → final review (follow-up brief to the same review tab) → fix → `--then` direct handoff → re-review → the main session took the round and went on to the wrap-up menu |
  | 2 | all | a one-off task "with a subagent" | It saw the session-start role text and started one worker |
  | 3 | first-dispatch deny only | same kind as 2 | It saw only the skill description and started a worker |
  | 4 | first-dispatch deny only | SDD plan (1 task) | existing `git worktree add` deny → skill → implement tab (stopped at the first tab) |

  - In all four runs there were 0 `Agent` calls, 0 user questions, and 0 denials by this branch's hooks. The first-dispatch deny was never used. The earlier layers (role text, Skill guidance, skill description, the existing deny) led to tabs first. So the only evidence for the effect of the deny text is still L2.
  - The review tab was never blocked. `runs.json` recorded only `<plan>-impl`.
  - There was one point of friction. The empty subheadings of the SDD review template (`#### Critical (Must Fix)` and so on) were caught by `finalize-brief`'s empty-section check. The orchestrator put a line under each subheading and it passed in one go. If the same thing keeps happening, add one line to section 4 of `dispatch.md`.
  - Confounders: in runs 2 to 4, claude-mem remembered the earlier runs and used them. Run 1 had no memory. The orchestrator read the installed copy's (`main`) SKILL.md, but for scripts that needed the new options it chose the ones at the guide's path (this branch).
- **Notice of changed behavior:** The brief of a worker started before 0.8.0 has no `## Environment`. So if that worker writes to another repository while it works, it is now blocked with `deny_undeclared`. It is unblocked when the orchestrator sends a follow-up brief that holds `--outside` (an intended change per D6 and (ii)).
