# Worker Placement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every worker (and every visible session without a worktree) lands under the target repository's herdr space — the current one if it is that repository's, else the one herdr knows for it — and as a tab in the current space when herdr knows none, never in a new top-level space.

**Architecture:** One placement rule in `scripts/hooks/spaces.py` (`repo_space`), read by `scripts/place.py` (placement + worktree creation for the skill's docs) and `route.py` (EnterWorktree registration). `runs.py` records each worker's `placement` and judges tab workers by their tab. Docs call `place.py` instead of re-describing the rule; `test_skill_text.py` pins that.

**Tech Stack:** Python 3 stdlib, git, herdr 0.9.0 CLI, unittest.

**Spec:** `docs/superpowers/specs/2026-11-10-worker-placement-design.md`

## Global Constraints

- Skill text (SKILL.md, references, assets, scripts, hook messages) stays English (`tests/test_language.py`).
- herdr facts: `herdr worktree list --cwd ROOT` → `result.source.{repo_key, repo_name, source_workspace_id}` (id absent when herdr knows no space); `herdr workspace get W` → `result.workspace.worktree.repo_key` (absent when unbound); `herdr tab get T` → `result.tab.{agent_status, focused}` (`focused` = the user is looking at it); `herdr pane get P` → `result.pane.tab_id`, `pane_not_found` once closed.
- herdr default worktree path: `~/.herdr/worktrees/<repo_name>/<branch with "/" → "-">`.
- Never close the space a tab worker lives in; never overwrite a path or branch; never create a herdr workspace in tab placement.
- Hooks keep judging by tool calls and command text; no hook exemption is added.
- Version 0.9.0. Commit on branch `worktree-space-placement`; no push, no merge.
- Run tests from the repo root: `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests` (abbreviated `UT` below; add `-k <name>` to narrow).

## Review Focus

- herdr fails mid-placement (server down, bad JSON): `place.py` exits 1 and creates nothing; `route.py` registers nothing — never silently falls back to a tab or a new space. (Task 1, Task 2 tests)
- A tab worker in a background space: cleanup must read the tab's `focused`, not the host space's, and never run `workspace get` for it. (Task 3)
- Records written before 0.9.0 (no `placement`) keep behaving as workspace workers in scan, mark-open and relocate. (Task 3)
- Rerunning `finalize-brief.py` on a `--workdir` brief or its follow-up keeps exactly one no-commit closing paragraph whose last sentence is still `Do not push or open a pull request.` (Task 4)
- A doc that still says `worktree create --cwd` / `worktree open --cwd`, or calls a `place.py` option that does not exist. (Task 6)

---

### Task 1: `spaces.repo_space`

**Files:**
- Create: `skills/herdr-parallel-worktree/scripts/hooks/spaces.py`
- Test: `skills/herdr-parallel-worktree/tests/test_spaces.py`

**Interfaces:**
- Produces: `repo_space(root: str, current: str | None, herdr: Callable[[list[str]], dict | None]) -> tuple[str | None, str]`. `why` ∈ `"current"`, `"repo-space"`, `"none"`, `"herdr-error"`. `herdr(args)` returns herdr's parsed JSON (`{"result": …}` or `{"error": …}`) or `None` when it could not run. Calls `worktree list --cwd root` first, then `workspace get current` only when `current` is set and is not the source workspace. Compares repo keys with `os.path.realpath`.

- [ ] **Step 1: Write the failing tests** — a dict-driven fake `herdr` callable that records calls:
  - `test_current_bound_to_the_repository` → `("w1", "current")`
  - `test_current_is_the_source_space_even_unbound` (current `w1` has no repo_key, source `w1`) → `("w1", "current")`, no `workspace get` call
  - `test_another_space_herdr_knows` (current bound to `/other/.git`, source `w7`) → `("w7", "repo-space")`
  - `test_no_current_uses_the_source_space` (`current=None`) → `("w7", "repo-space")`
  - `test_none_when_herdr_knows_no_space` (no `source_workspace_id`, current bound elsewhere) → `(None, "none")`
  - `test_herdr_failure_is_an_error_not_none`: `worktree list` → `None`; `worktree list` → `{"error": …}`; `workspace get` → `None` → each `(None, "herdr-error")`
- [ ] **Step 2: Run** `UT -k test_spaces` → FAIL (no module).
- [ ] **Step 3: Implement** `spaces.py` (stdlib `os` only; it is imported by the hook).
- [ ] **Step 4: Run** `UT -k test_spaces` → PASS.
- [ ] **Step 5: Commit** `feat: decide a worker's herdr space in one place`

### Task 2: `scripts/place.py`

**Files:**
- Create: `skills/herdr-parallel-worktree/scripts/place.py`
- Test: `skills/herdr-parallel-worktree/tests/test_place.py`

**Interfaces:**
- Consumes: `spaces.repo_space` (import via `sys.path.insert(0, <scripts/hooks>)`).
- Produces (CLI, JSON on stdout, errors on stderr with exit 1; `CUR` = `$HERDR_WORKSPACE_ID`, required):
  - `place.py where --dir DIR` → `{"placement", "space", "why"}`. `DIR` outside git → `{"placement": "tab", "space": CUR, "why": "outside git"}`. Else ROOT = `git -C DIR rev-parse --show-toplevel`; `repo_space` → found: `placement: "workspace"`, `space: <id>`; none: `placement: "tab"`, `space: CUR`.
  - `place.py worktree --root ROOT --name N --branch B (--base SHA | --existing) [--path P] [--trust-repository]` → `{"placement", "space", "workspace", "worktree", "since", "why"}`. `workspace` is where the worker's tab goes: the new worktree workspace (placement `workspace`) or `CUR` (placement `tab`). `since` = ms taken just before creation. Relative `P` resolves against ROOT.
    - placement `workspace`: `herdr worktree create --workspace <space> --branch B [--base SHA] [--path P] --label N --no-focus [--trust-repository]`; `workspace`/`worktree` from herdr's `result.workspace.workspace_id` / `result.worktree.path`.
    - placement `tab`: path = P or the herdr default (repo_name from `worktree list`'s `source.repo_name`); refuse an existing non-empty path; `git -C ROOT worktree add -b B <path> SHA` (new) or `git -C ROOT worktree add <path> B` (`--existing`).
  - `place.py reopen --root ROOT --name N --worktree WT` → same keys (`worktree` = WT). `workspace` placement: `herdr worktree open --workspace <space> --path WT --label N --no-focus`; `tab`: nothing opened, `workspace` = CUR. WT must exist.

- [ ] **Step 1: Write the failing tests** — a scripted fake `herdr` on PATH (answers from `$FAKE/plan.json`: `source_workspace_id`, `repo_key` per workspace, `fail` per command; logs calls), a real temp git repo with one commit, `HOME` pointed into the temp dir:
  - `test_worktree_in_the_current_space` → one `worktree create` call with `--workspace w1 --branch b1 --base <sha> --label n1 --no-focus`; output `placement == "workspace"`, `workspace` = fake's new id
  - `test_worktree_under_the_space_herdr_knows` (current bound elsewhere, source `w7`) → `--workspace w7`
  - `test_worktree_as_a_tab_when_no_space` → no `worktree create` call; `git worktree list` shows the path on branch `b1`; output `placement == "tab"`, `workspace == space == "w1"`
  - `test_tab_default_path_follows_herdr` (branch `feat/x`) → `$HOME/.herdr/worktrees/<repo>/feat-x`
  - `test_tab_existing_branch_is_checked_out` (`--existing`, branch made beforehand) → checked out, no new branch
  - `test_occupied_path_is_refused` → exit 1, no worktree added
  - `test_relative_path_resolves_against_root` → `<root>/.worktrees/b1`
  - `test_herdr_error_creates_nothing` (`worktree list` fails) → exit 1, `git worktree list` unchanged
  - `test_reopen_tab_opens_nothing` / `test_reopen_workspace_opens_under_the_space` → no herdr open call / `worktree open --workspace w7 --path <WT> --label n1 --no-focus`
  - `test_where_outside_git_is_a_tab_here`, `test_missing_workspace_id_fails`
- [ ] **Step 2: Run** `UT -k test_place` → FAIL.
- [ ] **Step 3: Implement** `place.py` (argparse subcommands; module docstring states the rule in three lines and the output keys).
- [ ] **Step 4: Run** `UT -k test_place` → PASS.
- [ ] **Step 5: Commit** `feat: place.py creates a worker's worktree under its repository's space, or as a tab here`

### Task 3: `runs.py` placement

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/runs.py` (docstring usage, `cmd_add`, `classify`, `cmd_scan`, `cmd_mark_open`, `cmd_relocate`, `main`)
- Test: `skills/herdr-parallel-worktree/tests/test_runs.py`

**Interfaces:**
- Produces: `--placement {workspace,tab}` on `add` (default `workspace`), `mark-open` and `relocate` (default: keep the record's). Records carry `"placement"`; a missing key reads as `"workspace"`. `scan` entries carry `placement`; tab entries carry `tab`, `tab_open` instead of `workspace_open`.
- Tab classify: `pane get <pane>` (`pane_not_found` → tab closed, any other error → keep "could not query herdr"), then `tab get <tab_id>` for `agent_status` and `focused`; never `workspace get`. Keep reason when focused: `user is viewing this tab`. `remove_command`: open tab → `git -C <root> worktree remove <wt> && herdr tab close <tab>`; closed → `git -C <root> worktree remove <wt>`.

- [ ] **Step 1: Write the failing tests** — extend the test's fake `herdr` (shell script → small Python script) to log calls and answer `pane get` (with `tab_id`, or `pane_not_found` for panes listed in `$CLOSED`), `tab get` (`focused` from `$FOCUSED_TABS`), `workspace get`:
  - `test_add_records_placement_default_workspace`, `test_add_records_tab_placement`
  - `test_scan_tab_worker_is_judged_by_its_tab` (real linked worktree, clean, no commits) → candidate, `remove_command == f"git -C {root} worktree remove {wt} && herdr tab close {tab}"`, no `workspace get` in the call log
  - `test_scan_closed_tab_removes_only_the_worktree`
  - `test_scan_focused_tab_is_kept` → reason `user is viewing this tab`
  - `test_record_without_placement_scans_as_workspace` (write a pre-0.9.0 record by hand) → `workspace get` used, `remove_command` starts `herdr worktree remove --workspace`
  - `test_relocate_and_mark_open_take_placement`
- [ ] **Step 2: Run** `UT -k test_runs` → new tests FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run** `UT -k test_runs` → PASS.
- [ ] **Step 5: Commit** `feat: runs.py records placement and cleans a tab worker by its tab`

### Task 4: `finalize-brief.py --workdir`

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/finalize-brief.py`, `skills/herdr-parallel-worktree/references/brief-filling.md` (options line), `skills/herdr-parallel-worktree/tests/test_skill_text.py` (`test_finalize_options_documented` adds `--workdir`)
- Test: `skills/herdr-parallel-worktree/tests/test_finalize.py`

**Interfaces:**
- Produces: `--workdir PATH` (excludes `--worktree`/`--branch`) writes `- Working directory: \`PATH\` (no worktree or branch of its own)` in `## Environment` and uses the closing paragraph `NO_BRANCH_TAIL = "When the work is done, end your final response with a \`## Result\` heading that covers what you did, test results and open issues. You have no branch of your own: do not commit. Do not push or open a pull request."` The variant is also chosen when the file already has a `- Working directory:` line. Either closing paragraph is removed before the chosen one is appended.

- [ ] **Step 1: Write the failing tests**: `test_workdir_writes_the_line_and_the_no_commit_tail`; `test_rerun_keeps_one_no_commit_tail` (second run without flags → exactly one `NO_BRANCH_TAIL`, no `TAIL`); `test_workdir_with_worktree_is_refused` (exit 1, file untouched).
- [ ] **Step 2: Run** `UT -k test_finalize` → FAIL.
- [ ] **Step 3: Implement**; document `--workdir` in brief-filling.md section 4's option list.
- [ ] **Step 4: Run** `UT -k "test_finalize or test_skill_text"` → PASS.
- [ ] **Step 5: Commit** `feat: finalize a brief for a worker without a worktree`

### Task 5: `route.py` R8 and the worker role; fake herdr

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/hooks/route.py` (`register`, `role_worker`, docstring line on R8), `skills/herdr-parallel-worktree/tests/fake_herdr.py` (`worktree list`, `worktree create --workspace`, `tab get`)
- Test: `skills/herdr-parallel-worktree/tests/test_route.py` (`FakeHerdr` answers `worktree list` with `source` built from `repo_key` and a new `source` argument; `RegisterTest`)

**Interfaces:**
- Consumes: `spaces.repo_space`.
- `register` on EnterWorktree: `main = main_of(path)` (None → return); `ws, why = spaces.repo_space(main, env.get("HERDR_WORKSPACE_ID"), herdr)`; `ws` → `worktree open --workspace ws --path … --label … --no-focus`; otherwise open nothing and return None.
- `role_worker`: "the main checkout" → "a main checkout you were not started in".
- fake_herdr: `worktree list` → `{"result": {"source": {"repo_key": $FAKE_HERDR_REPO_KEY, "repo_name": <basename>, "source_workspace_id": $FAKE_HERDR_SOURCE_WS (omitted when unset)}}}`.

- [ ] **Step 1: Write the failing tests** (replace the two `--cwd` tests):
  - `test_enter_opens_the_worktree_in_the_sessions_workspace` (unchanged expectation: `--workspace w1`)
  - `test_enter_goes_under_the_space_herdr_knows` (current bound to `/other/.git`, source `w7`) → `["worktree","open","--workspace","w7",…]`
  - `test_enter_without_a_workspace_id_uses_the_known_space` → `--workspace w7`
  - `test_enter_opens_nothing_when_no_space_is_known` → no `worktree open` call, output `None`
  - `test_enter_opens_nothing_when_herdr_fails` (`worktree list` → `None`)
  - `test_worker_role_allows_its_own_checkout`: `"a main checkout you were not started in" in route.role_worker("w1")`
- [ ] **Step 2: Run** `UT -k test_route` → FAIL.
- [ ] **Step 3: Implement**; update fake_herdr.py.
- [ ] **Step 4: Run** `UT` (all) → PASS.
- [ ] **Step 5: Commit** `feat: EnterWorktree registration follows the same placement rule`

### Task 6: Docs without drift

**Files:**
- Modify: `skills/herdr-parallel-worktree/SKILL.md`, `references/resume.md`, `references/deliver.md`, `references/cleanup.md`, `references/dispatch.md`, `README.md`, `README.ko.md`, `.claude-plugin/plugin.json` (0.9.0), `skills/herdr-parallel-worktree/tests/live_skill.py` (`ORCHESTRATION` also matches `place\.py\s+worktree`; S1c's `asked_before(tools, "place.py worktree")`; S2 description)
- Test: `skills/herdr-parallel-worktree/tests/test_skill_text.py`

**What changes** (spec §4 table): SKILL.md intro sentence, step 0 name line, step 1 (one `place.py worktree` call + the three-line rule + tab bullet: herdr's sidebar does not show a tab worker's worktree; opening it from herdr would make a workspace while the tab still runs there), step 3 (`runs.py add --placement "$PLACEMENT"`, tab note), step 4 report line (where it landed and why), new section `## A worker without a worktree` (when; `place.py where --dir`; `worker-pane.py --workspace <space> --worktree <dir>`; `finalize-brief.py --workdir`; not recorded, so this skill cannot resume it once its tab is gone; follow-ups by name with `deliver.md` steps 2, 4, 5), Hooks (EnterWorktree registration follows the rule; `place.py` makes a tab worker's worktree). resume.md step 1/2/4 and deliver.md step 3 call `place.py worktree --existing` / `place.py reopen` and pass `--placement`. cleanup.md: tab workers close their tab; manual recreation `git -C <root> worktree add <worktree> <branch>`. dispatch.md: the plan's place comes from step 1; in tab placement both role tabs are in the current space.

- [ ] **Step 1: Write the failing drift tests** in `test_skill_text.py`:
  - `test_docs_place_workers_with_place_py`: SKILL.md, resume.md, deliver.md, dispatch.md each contain `scripts/place.py`
  - `test_no_doc_lets_herdr_make_a_space`: no skill doc contains `worktree create --cwd`, `worktree open --cwd` or `LOC=(`
  - `test_place_py_calls_in_docs_exist`: every `place.py <sub>` in fenced or inline code across SKILL.md and references names a subcommand of `place.py --help`, and every `--option` on that line exists in `place.py <sub> --help`
  - `test_runs_py_records_placement`: SKILL.md's `runs.py add`, resume.md's `mark-open` and deliver.md's/resume.md's `relocate` lines carry `--placement`
- [ ] **Step 2: Run** `UT -k test_skill_text` → FAIL.
- [ ] **Step 3: Edit the docs**; bump version; update live_skill.py.
- [ ] **Step 4: Run** `UT` and `bash scripts/check.sh` → all pass.
- [ ] **Step 5: Commit** `docs: place workers with place.py everywhere; bump to 0.9.0`

### Task 7: Live check and record

**Files:**
- Modify: `docs/superpowers/specs/2026-11-10-worker-placement-design.md` (§8 결과)
- Scratch only: a check script in the session scratchpad (literal absolute paths)

- [ ] **Step 1:** In real herdr, with a scratch repo: (a) a space for the repo exists but is not the current one → `place.py worktree` + `worker-pane.py` → the worktree workspace is grouped with that repo space (`workspace list` repo_key, linked); (b) no space → tab in the current space (`tab list`), no new workspace (`workspace list` count unchanged); (c) `place.py reopen` on an unbound repo space; (d) `runs.py add` + `scan` → `remove_command` runs cleanly for both. No claude is started. Remove everything made.
- [ ] **Step 2:** `bash scripts/check.sh` → all checks pass.
- [ ] **Step 3:** Write §8 결과 in the spec (what was measured, anything that differed from the design), commit `docs: record the placement live check`.
- [ ] **Step 4:** Whole-branch review by a fresh reviewer (herdr tab per `references/dispatch.md`, read-only, verdict file); fix Critical/Important findings, recheck, commit.
