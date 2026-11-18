# Worker cleanup by choice: the user picks which workers to clean up — design

- Date: 2026-11-18
- Base: `21522a9`
- Scope: `herdr-parallel-worktree`: `scripts/runs.py` (`scan`, `add`), `SKILL.md` (description, steps 0, 3, 4 and 6, Never), `references/cleanup.md`, `README.md`, `README.ko.md`, `tests/test_runs.py`, `tests/test_skill_text.py`

## 1. What the problem was

Until now the skill decided which workers were finished. `runs.py scan` offered a run as a cleanup candidate only when its work was merged into the branch it came from, pushed with nothing unpushed, or empty, and the orchestrator ran that scan only for the repository a new worker started in.

No moment marks a worker as finished, though. After a worker commits, the user may review and have it commit again, or keep it open to look at its history for a while. So the candidates were the wrong set, and the rest piled up: on 2026-11-18 six workers had stayed open for up to 37 days. Four were never merged, one was merged in a repository where no new worker started, and one was cherry-picked, so it did not show as merged.

User decisions (2026-11-18):

1. The skill stops deciding which workers may go. It lists the open workers with the facts needed to decide, and the user picks. Only the picked workers are cleaned up, as before: the worktree is removed, the branch is kept, and the resume clues are reported.
2. The list appears at two moments only: in the report after new workers start, and when the user asks to clean up. Nothing is cleaned up at any other time.
3. The list covers the current repository: the git checkout the orchestrator session works in, the top level of its working directory (SKILL.md step 0's `ROOT` when the user named no other repository). When the session is not inside a git repository, or the user asks for every repository's workers, it covers every repository. There is no repository column. One line under the table gives the number of open workers in other repositories, only when there are any, and says that asking to clean up all workers shows them. This keeps leftovers elsewhere from being forgotten without adding a column (an assumption the user can drop).
4. Each row shows what the worker is for: the one-line task summary the orchestrator wrote when it started it. Nothing is interpreted.
5. The table lists only workers that can be cleaned up now, so it needs no cleanable column. The others are named in one line under the table, each with its reason. A worker with uncommitted changes cannot be cleaned up until they are committed, and hiding it would let it pile up unnoticed again.
6. The table's heading is just "Cleanable workers", written in the user's language like the rest of the report. The cleanup report afterwards already says that branches stay and how to resume.
7. The list after new workers start leaves out the workers that run started, from the table and from the "Left out" line: they were started a moment ago and are not candidates for anything. A cleanup the user asks for later lists every worker.

## 2. `runs.py scan`

```
runs.py scan (--root ROOT | --all) [--fetch]
```

- `--root ROOT`: the open runs of that repository. `ROOT` must be a git repository, as before.
- `--all`: the open runs of every repository in the registry. A recorded root that is no longer a repository does not stop the scan: its runs are reported with `work.state: unknown`.
- `--fetch` fetches each repository once, before its runs are judged.

Output (JSON):

| Key | Content |
|---|---|
| `workers` | every open run of the scanned repositories, grouped by repository in registry order; each entry below |
| `open_elsewhere` | with `--root`: the number of open runs in other repositories; `0` with `--all` |
| `untracked_worktrees` | linked worktrees of the scanned repositories that the registry does not record, each with its `root`; shown, never removed |

Each entry keeps `root` for the commands that need it (`remove_command`, `mark-cleaned --root`); the list does not show it.

| Field | Content |
|---|---|
| `name`, `branch`, `root` | the run |
| `summary` | the run's one-line task summary (section 3), or `null` |
| `agent_status`, `focused` | herdr's view of the worker: its workspace, or its tab for a tab worker |
| `last_activity` | the branch's last commit date (committer date), or `created_at` when the branch has no commits of its own |
| `work` | `{state, into, commits, pushed, text}`: where its work stands (below) |
| `cleanable`, `blockers` | whether it can be cleaned up now, and what blocks it |
| `worktree_exists` | `false` when the worktree directory is gone and only the record is left |
| `remove_command`, `agent`, `session_id` | as before; `remove_command` is `null` when there is nothing to remove or herdr could not be queried |
| `placement`, `workspace`, `workspace_open` or `tab`, `tab_open`, `companions` | as before |

### Where the work stands

Judged against the branch it came from (`from_branch`, then `origin/<from_branch>`), in this order; the first that holds wins:

| `work.state` | `work.text` (target `main`) | Test |
|---|---|---|
| `no_commits` | `no commits` | `base..branch` is empty |
| `merged` | `merged into main` | the branch is an ancestor of the target |
| `same_patches` | `in main by patch (cherry-pick or rebase)` | `git cherry <target> <branch>` prints at least one line and every line starts with `-` |
| `same_content` | `in main by content (squash merge)` | the branch changed at least one file since `base`, and every such file is identical in the target (`git diff --no-renames --name-only`) |
| `pushed` | `pushed, not merged` | `origin/<branch>` exists and holds every commit |
| `not_merged` | `not merged (3 commits)` | otherwise; the count is `<target>..<branch>` (`base..branch` when no target resolves) |
| `unknown` | `unknown: branch not found` / `unknown: repository not found` | the branch or the repository is gone |

`work.into` names the target that matched, `work.commits` the count above, and `work.pushed` whether `origin/<branch>` holds every commit (also for the merged states).

Measured on git 2.52.0 before choosing the tests:

- `git cherry` without a limit compares exactly the commits the target lacks and skips merge commits. A cherry-pick of every commit, a rebase merge and a one-commit squash all print only `-` lines. An empty output means nothing is missing by ancestry, which `merged` already covers; it is never read as "by patch".
- A squash of two or more commits prints `+` lines (no single commit matches the squashed patch), so it needs the content test.
- After a cherry-pick, merging the target back into the branch makes `git cherry` print `+` for the picked commits: their copies are on the branch side now. The content test still catches it because its file set is taken from the recorded `base`, not from the merge-base, which would be the target itself and leave nothing to compare. A file set taken from `base` can only be too large (files the target changed and the branch merged in), which makes the test miss, never claim, a match.
- A branch whose commits change no file (empty commits) is not claimed to be "in main by content": it shows as `not_merged`.

Where the work stands never blocks cleanup. The branch and its commits stay, and a cleaned worker can be resumed (`references/resume.md`); the state is there for the user to decide.

### What blocks cleanup

| Blocker | Why |
|---|---|
| `working`, `blocked` | the worker would be cut off mid-task or while it waits for the user |
| `<plan>-rev is working` / `blocked` | the same for a dispatch plan's reviewer tab beside a tab worker |
| `user is viewing its workspace` / `its tab` / `<plan>-rev` | the screen the user is reading would vanish |
| `3 uncommitted changes` | removing the worktree would lose them; git and herdr refuse anyway |
| `git status failed`, `could not read the worktree's HEAD` | its changes cannot be checked |
| `2 commits on no branch (detached HEAD)` | those commits live only in the worktree's HEAD and would be lost with it |
| `herdr could not be queried (<code>)` | the worker's status is unknown; a failure is never read as "closed" |

The detached-HEAD blocker is an addition to the brief's list. Dropping "not merged" as a blocker rests on "the branch and its commits stay"; a commit made on a detached HEAD in the worktree is on no branch, so removing the worktree would lose it. One `git rev-list --count HEAD --not --branches --tags --remotes` checks it.

A run whose worktree is already gone has no worktree checks and `remove_command: null`: cleaning it up only marks the record. The herdr blockers apply to it as to any other run. This changes the old `stale` handling, which skipped them: a worker still working where its worktree was deleted is not one to mark cleaned behind its back.

## 3. The task summary

- `runs.py add --summary TEXT` keeps the one-line summary in the record. SKILL.md step 3 passes the same text as `SUMMARY` there, which is also the brief's title (`# [<name>] <summary>`).
- A run recorded before this change has no `summary`. `scan` then reads the title line of the run's brief (the record's `brief`) and takes what follows `# [<name>] `. A missing or unreadable brief, or a first line of another shape, gives `null`.
- The table cuts a long summary to about 50 characters and ends it with `…`; an empty cell means no summary.

## 4. The flow

- **When**: right before the report after new workers start (SKILL.md step 4), and when the user asks to clean up. Not in step 0 any more (the statuses it showed were stale by the time of the report), not after results come in, and not to free a name.
- **Scan**: `scan --root "$CUR"` for the current repository (`git rev-parse --show-toplevel` of the session's working directory), falling back to `scan --all` in one guarded command when that fails; `scan --all` when the session has no current repository or the user asks for every repository.
- **Show**: under the heading "Cleanable workers", one numbered table of the `cleanable` entries: `#`, name, what it is for (`summary`), branch, status, last activity, where its work stands. Under it, only when there are any: one line naming the others with their reasons (`Left out: cli-run-impl (working), proj-7 (3 uncommitted changes)`), the line with `open_elsewhere`, and the untracked worktrees. With nothing cleanable, one line says so instead of the table, followed by the left-out line, and nothing is asked. The list after starting workers leaves out every worker this run started, from the table, the left-out line and the `open_elsewhere` count: they were started a moment ago and are not candidates for anything (user decision, follow-up 5). The scan still reports them; the orchestrator knows their `root` and `name` and filters them, as it filters the left-out ones. A cleanup the user asks for lists every worker.
- **Ask**: with one to four cleanable workers, one multiple-choice question that allows several answers, one option per worker, plus "None" while there is room (with four, the question says that answering "none" keeps them all); with more, ask for the numbers. "None" is always a valid answer, and the orchestrator never suggests which to pick.
- **Clean up**: numbers map to the entries of the table that was shown, by `root` and `name` (a name can repeat across repositories). Scan again right before removing, clean up each picked worker that is still cleanable (its `remove_command`, then `mark-cleaned --root <its root>`), and report the ones that no longer are with their blockers. A run whose worktree is gone is only marked.
- **Report**: as before, with the resume clues per cleaned worker; the "why it was cleanable" column becomes "where its work stood".

## 5. What does not change

- Cleanup still considers only runs recorded in `runs.json`, removes with `remove_command` (which refuses uncommitted changes), keeps branches, briefs and session history, and never closes the space a tab worker runs in.
- `mark-cleaned`, `mark-open`, `relocate` and `show` keep their arguments; `mark-cleaned --root` takes the entry's own root.
- The hooks are untouched.

## 6. Tests

- `tests/test_runs.py`: `--root` lists one repository and counts the others in `open_elsewhere`; `--all` lists every repository and survives a recorded root that is gone; each work state (no commits, merged, merged into `origin/main` only, cherry-pick, a one-commit squash, a two-commit squash, a cherry-pick followed by merging the target back, a later target change that breaks the content match, empty commits, pushed, not merged with its count, a deleted branch); `last_activity`; an unmerged worker is cleanable; each blocker (working, blocked, viewed, uncommitted changes, git status failed, detached-HEAD commits, herdr unavailable, a working reviewer tab); a run whose worktree is gone, with and without a live blocker; untracked worktrees; the summary from `--summary`, from an older run's brief title, and none when the brief is gone. The existing placement and reviewer-tab tests read `workers` instead of `candidates` and `keep`.
- `tests/test_skill_text.py`: every `runs.py` call in the docs uses a real subcommand and real options, `references/cleanup.md` scans with both `--root` and `--all`, the step 3 `add` call passes `--summary`, and `references/cleanup.md` documents every `work.state` the script can report.
