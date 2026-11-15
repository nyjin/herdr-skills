# Worker placement: under the target repo's space, else a tab in the current space — design

- Date: 2026-11-10
- Base: `2f5abc0` (0.8.0)
- Measured on: herdr 0.9.0, Claude Code 2.1.319
- Scope: `herdr-parallel-worktree` skill body and reference docs, `scripts/place.py` (new), `scripts/hooks/spaces.py` (new), `runs.py`, `finalize-brief.py`, `worker-pane.py` (docs only), `route.py`, tests, README

## 1. What the problem was

In the early hours of 2026-11-10, an orchestrator session working in `~/src/skills` sat in a tab (`good-skills`) of the kb-skills space (w22). Only its cwd was `~/src/skills`. What this session launched did not land where the user expected.

| What | How it was launched | Where it landed | User expectation |
|---|---|---|---|
| `decided-result` worker (worktree) | Skill step 1. The current space (kb-skills) differs from the target repo (skills), so `--cwd ~/src/skills` | herdr **created a new skills space (w3S)** and put it under that | Under the skills space. If there is none, do not create a new top-level space |
| `t13-main`, `t13-eval` (no worktree) | `herdr tab create --workspace "$HERDR_WORKSPACE_ID"`, outside the skill | kb-skills, where the session was | Same rule |

The t13 tabs started without `HERDR_PW_WORKER`. So the hook took these sessions for main sessions and applied the orchestrator role paragraph and the first-dispatch stop. To avoid this, the orchestrator wrote "this instruction takes priority over the herdr guidance" into the brief and created the hook's dispatch record file by hand. This was an improvised workaround, because the skill had no way to launch a visible session without a worktree.

User decision (2026-11-10): "If the space is different, look it up with herdr, create under it if it exists, and use a tab only if there is none." Sessions without a worktree follow the same rule.

## 2. What was measured

Checked with two temporary repositories (repoA, repoB) and a lab space. Everything created was deleted.

| # | What was checked | Result | Effect on the design |
|---|---|---|---|
| P1 | `herdr workspace create --cwd <repo root>` | The space is created but its `worktree` (repo_key) is empty. It is not tied to the repo | repo_key alone does not find every "space of that repo" |
| P2 | `worktree create --cwd <repo root>` while the P1 space exists | Does not create a new space. It reuses the P1 space and ties it to the repo. The new worktree appears under it | herdr also looks for "the space of that repo" |
| P3 | `herdr worktree list --cwd <repo root>` | `result.source.source_workspace_id` is the space herdr linked to that repo's original checkout. The untied P1 space shows up too. If there is none, the key is absent (kurly-fulfillment-auth: only linked worktree spaces) | **Lookup uses this value.** It is herdr's own verdict, so we need not imitate it |
| P4 | `worktree create --workspace <id>` on an untied space | Works, and ties that space to the repo | For a space we found, always attach with `--workspace` |
| P5 | Branch `feat/x-y` without `--path` | `~/.herdr/worktrees/<repo_name>/feat-x-y` (`/` becomes `-`) | For tab placement, follow the herdr default path as is |
| P6 | Under `--cwd`, when the repo's space does not exist (w3S) | Creates a new space for the original repo (same as G7 of the 2026-10-13 design) | This is the behavior the user does not want |
| P7 | `herdr tab get <tab>` / `herdr pane get <pane>` | A tab has `agent_status` and `focused`. A pane has `tab_id`. A closed pane gives `pane_not_found` | Cleanup of a tab worker is judged by its tab instead of its workspace |

## 3. The rule

Placement is decided by the target repo `ROOT` and this session's space `CUR` (`HERDR_WORKSPACE_ID`).

1. If `CUR` is tied to `ROOT`'s repo (same repo_key) → under `CUR` (same as today).
2. Otherwise, if `source_workspace_id` from `herdr worktree list --cwd ROOT` exists → under that space (`--workspace`). If it is `CUR`, this is the same as 1.
3. Otherwise → do not create a new space. Launch in a **tab of `CUR`**.

| Placement | Who creates the worktree | Where the worker runs | Sidebar |
|---|---|---|---|
| `workspace` (1, 2) | `herdr worktree create --workspace <space>` | A `<name>` tab inside the new worktree space (same as 0.7.0) | A sub-space under that repo's space |
| `tab` (3) | `git -C ROOT worktree add` | A `<name>` tab in `CUR`, cwd is that worktree | A tab in the current space |

A session without a worktree only skips creating one. Its place is decided by the same rule. If the directory the session works in is inside a repo, that repo is `ROOT`. If it is outside any repo, the place is `CUR`.

## 4. Structure

### `scripts/hooks/spaces.py` (new)

A single `repo_space(root, current, herdr)`. It decides rules 1 and 2 above and returns `(space id or None, reason)`. `place.py` and `route.py` share it. The decision must live in one place so the two cannot drift apart.

### `scripts/place.py` (new)

Handles the placement decision and worktree creation. Three docs (SKILL.md step 1, resume.md, deliver.md) and dispatch.md call the same commands.

- `place.py where --dir DIR`: only decides placement. Used by sessions without a worktree. If `DIR` is outside a repo, `tab` (CUR).
- `place.py worktree --root ROOT --name N --branch B (--base SHA | --existing) [--path P] [--trust-repository]`: decides placement and creates the worktree. For `workspace` it runs `herdr worktree create --workspace`, for `tab` it runs `git worktree add`. `--existing` is for resume (it checks out the branch instead of creating it). It returns the time just before creation as `since` (for waiting on plugins).
- `place.py reopen --root ROOT --name N --worktree WT`: used when the worktree is still there but its place (space or tab) is gone. For `workspace` it runs `herdr worktree open --workspace`. For `tab` it opens nothing and only returns the place.
- Output (JSON): `placement` (`workspace`|`tab`), `workspace` (the space to create the worker tab in), `worktree`, `since`, `why`.
- It overwrites nothing. If the path is occupied, the branch exists, or herdr or git fails, it prints that error to stderr and exits 1.
- If `--path` is relative, it is resolved against `ROOT`. For `tab` without `--path`, the herdr default path (P5) is used.

The hook blocks the main session's `git worktree add` (branch). The worktree for tab placement is created by this script. The hook's rejection message already says "load the skill to launch a worker, the skill creates the worktree", so this is the same path. The hook judges by command text, so it does not see git calls inside the script. The hook needs no change.

### `runs.py`

- Add `placement` to the record (`--placement` on `add`, `mark-open`, `relocate`). Old records without it are read as `workspace`.
- A tab worker's `workspace` is the space the tab is in (`CUR`).
- In the cleanup decision (`scan`), a tab worker is judged by its **tab**, not its space. It finds the tab with `pane get` and reads `agent_status` and `focused` with `tab get`. If the pane is gone, the tab is closed.
- A tab worker's `remove_command` is `git -C <root> worktree remove <wt> && herdr tab close <tab>`. If the tab is already closed, only the first part is used. The worktree is removed first. If there are uncommitted changes, git refuses, so the tab stays too. **The `CUR` space is never closed.**

### `finalize-brief.py`

`--workdir PATH`: writes the Environment line (`- Working directory: …`) for a session without a worktree. It also changes the closing paragraph. Instead of "commit to this branch" it says "do not commit, and do not change files git tracks", and the last sentence "Do not push or open a pull request." stays as is. The `wait-output` in step 3 waits for that sentence. Running it again recognizes the Environment line and writes the same paragraph.

### `route.py`

- **R8 (EnterWorktree registration)**: uses the same rule through `spaces.repo_space`. For 1 and 2, run `worktree open --workspace` on that space. For 3, do not register. This session is already in its own tab, and no new top-level space is created. Until now it opened with `--cwd`, which could create a new space as in P6.
- **Worker role paragraph**: "Do not write where another session works (… the main checkout …)" conflicts with a worker that has no worktree and works inside a repo's original checkout (a working folder that git ignores). Change "the main checkout" to "a main checkout outside the working directory your brief gives you". The hook's verdict (writes inside the worker's own home are allowed) already behaves that way.

### Skill docs (without drift)

| Doc | What changes |
|---|---|
| SKILL.md first paragraph | "a worktree space for each task" → one sentence on the placement rule |
| SKILL.md step 0 | Name is "a space or tab label" |
| SKILL.md step 1 | The `LOC`/`WS_KEY` decision becomes the single line `place.py worktree`. The placement rule and its reasons |
| SKILL.md step 3 | `runs.py add --placement`. Tab placement in the tab description |
| SKILL.md step 4 report | Where it landed (under a space / a tab of the current space, and why) |
| SKILL.md new section "A worker without a worktree" | When, `place.py where`, `worker-pane.py` (`HERDR_PW_WORKER`), `finalize-brief.py --workdir`, not recorded, follow-ups delivered by name |
| SKILL.md Hooks | EnterWorktree registration follows the same rule. `place.py` creates a tab worker's worktree |
| resume.md | Step 2 becomes `place.py worktree --existing`. Resuming a closed place uses `place.py reopen`. `mark-open`/`relocate --placement`. For a tab worker, "the place exists" means the pane exists |
| deliver.md | The step 3 table and reopening use `place.py reopen`. A worker without a worktree has no record, so deliver by name |
| cleanup.md | A tab worker closes its tab. The manual revive command is written in a form that does not depend on placement |
| dispatch.md | "One space per plan" becomes "the place step 1 decided". With tab placement, `<plan>-impl` and `<plan>-rev` are tabs in the current space |
| brief-filling.md | `--workdir` |
| README.md / README.ko.md | The one-line skill description and the EnterWorktree paragraph |

What prevents drift:
- The placement decision lives only in `spaces.py`.
- Docs do not re-explain the decision. They call `place.py`.
- Add checks to `test_skill_text.py`. They check that the docs call `place.py`. They also check that the old commands that can create a new space (`worktree create --cwd`, `worktree open --cwd`) do not remain in the docs.

## 5. What this does not do

- It does not move workers that are already running. Placement is decided only at creation and at resume.
- It does not create new spaces. If the user wants one, they create it themselves. Workers launched after that attach under it by rule 2.
- It does not register a tab placement's worktree with herdr (`worktree open` creates a space).
- It does not record sessions without a worktree in runs.json. There is no worktree to delete or revive.
- It does not change how the hook judges (command text, tool calls).

## 6. Decided on my own judgment

- Lookup uses herdr's `source_workspace_id` (P3). We do not compare space cwds ourselves.
- A repo that has only linked worktree spaces and no original space (kurly-fulfillment-auth) counts as "no space". There is no "under" to attach to.
- EnterWorktree registration (R8) also changes to the same rule. The same complaint (a new top-level space) comes from the same cause, and with two rules the docs would drift.
- The version goes up to 0.9.0 (behavior visible in the sidebar changes).
- **When to use a worker without a worktree** (builder review question 1): coding work in a repository always has a worktree. A worker without a worktree is used only for work that must not or need not have one. That means cases where the user or a repository rule forbids worktrees and branches, or work that changes no repository (evaluations, research or review that writes results into a working folder). `ROLE_MAIN` and the skill description (frontmatter) stay as they are. Every session pays for that sentence, so the exception goes only in the SKILL.md body.
- **Can several sessions edit the same checkout** (question 2): No. A worker without a worktree does not change or commit files that git tracks. It writes only in its own working directory (outside git, or a place git ignores). This rule is written in the SKILL.md section, the `--workdir` closing paragraph, and the worker role paragraph. No hook enforcement is added (natural and economical).
- **Follow-up delivery** (question 3): there is no record, so find the worker by name (`herdr agent get <name>`). Follow-up files are also finalized with `--workdir`. The name must not collide with a recorded or running worker, because the hook reads outside paths from the brief by name.
- Another session is using this skill right now (the installed copy points at the main checkout). So implement and verify only on the branch, and leave the merge to main to the user.

## 7. Verification

- Unit: `spaces.repo_space` (three cases and herdr failure), the three `place.py` subcommands (fake herdr, real git), `runs.py` tab judgment and `remove_command`, `finalize-brief.py --workdir`, the three cases of `route.py` R8, the doc drift check.
- Live (herdr 0.9.0, temporary repositories): in each of the three placements, run `place.py worktree` through `worker-pane.py`. Check sidebar placement and tab position with `workspace list` and `tab list`. Do not launch claude. Then clean up with the `remove_command` from `runs.py scan`.
- All of `scripts/check.sh`.

## 8. Results (2026-11-10)

- 267 unit tests (including the review fixes below), and all of `scripts/check.sh` passes (run outside a herdr worker).
- Live checks 11/11 passed. herdr 0.9.0, three temporary repositories, and a `lab-host` space not tied to any repo was used instead of this session's space. Everything created was deleted.

| # | Situation | Result |
|---|---|---|
| a | The repo has its own space (`lab-c`) | `placement: workspace`, a worktree space linked to the repo under `lab-c`, worker tab `pc1` inside it, shell ready |
| b | The repo has no space | `placement: tab`, tab `pd1` in `lab-host` (cwd = worktree), space count unchanged, path is the herdr default (`~/.herdr/worktrees/repoD/feat-pd1`) |
| c | `place.py reopen` on an untied repo space | `herdr worktree open --workspace` worked and opened under it |
| d | `remove_command` from `runs.py scan` | A space worker is removed with `herdr worktree remove`. A tab worker has its worktree removed, then only its own tab is closed. `lab-host` stays |

What differed from the design:
- The wording of the worker role paragraph and the `--workdir` closing paragraph was set as decided in the builder review in §6 (reflected in §4).
- Both herdr and git leave the empty parent directory (`~/.herdr/worktrees/<repo>/`) after removing a worktree. This is existing behavior, so it was left alone.
- Hook-side changes (R8, worker role paragraph) were checked only by unit tests. The hook actually running in this session is the old code of the main checkout (the installed copy). `live_hooks.py` and `live_skill.py` (which run claude -p) were not run this time. They were adjusted to match, and only the syntax was checked.

### Fixed after the final review

The review of the whole branch (herdr tab `placement-rev`, read-only) said "fix, then merge". What was fixed:
- `finalize-brief.py`: the option decides the closing paragraph first. Only when there is no option does the `- Working directory:` line inside the Environment section decide. If Environment is rewritten without `--workdir`, that line is carried over. Before, rerunning a `--workdir` brief with `--outside` flipped it to "commit to this branch".
- `runs.py`: the `<plan>-rev` tab of a tab-placement dispatch plan is also included in the cleanup decision. Only a tab in the same space whose label is `<plan>-rev` and whose pane is in the same worktree is considered. If that tab is working, blocked, or being watched by the user, it stays, and it is closed together when cleaning up. `add --placement` is required. Without it, the cleanup command would aim at the host space.
- `place.py`: an existing branch (`--base`) or a missing branch (`--existing`) is rejected up front instead of being left to herdr. herdr just checks out an existing branch.
- Docs: fixed that the hook cannot check writes of a worker without a worktree in a directory outside git, that the brief for such a worker omits the template's commit and branch steps, and the leftover phrases "its own worktree" and "`--path` to herdr".
- Four minor items first deferred, then fixed at the user's request (2026-11-14):
  - `check.sh` starts by clearing `HERDR_PW_WORKER` and `HERDR_WORKSPACE_ID`. The `hooks` check now passes inside a worker tab too (`test_check.py`).
  - `place.py worktree` first runs `git worktree prune` on a worktree whose directory is gone but which git still lists, then creates it again.
  - `runs.py` treats the recorded pane's tab as the worker's only if it still carries the worker name as its label. With any other label it is left out of the decision and not closed.
  - `place.py where --dir` rejects a path that does not exist.
- Live check after the fixes 5/5 (herdr 0.9.0). In a tab-placement plan, both the `pf-impl` and `pf-rev` tabs opened in the current space, and no new space appeared. `scan` found `pf-rev` as the paired tab. `remove_command` removed the worktree and then closed both tabs, and the host space stayed. Running the new `scan` read-only against the real registry (`decided-result-impl`, workspace placement) did not change the record.
