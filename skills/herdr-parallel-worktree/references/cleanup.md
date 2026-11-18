# Cleaning up workers

Every run leaves a worktree behind, with its workspace or, for a worker placed as a tab (SKILL.md step 1), its tab, and they pile up. Nothing marks a worker as finished: after it commits, the user may review and have it commit again, or keep it open to look at its history. So this skill never decides which workers may go. It lists the workers that can be cleaned up now, with the facts needed to decide, and the user picks. This document covers when to list them, how to ask, how to clean up the picked ones, and how to report so that every cleaned worker can be resumed later (`references/resume.md`).

Cleaning up removes the worktree and closes its workspace, or a tab worker's own tab, never the space that tab is in. The branch, its commits, the brief and the agent's own session history all stay, which is what makes resuming possible.

## When

Only at these two moments:

- **After new workers start**: at the end of the report (SKILL.md step 4).
- **When the user asks**: "clean up the workers", "tidy up the old worktrees", "clean up every repository's workers" (in any language).

Never at any other time: not when a worker finishes, not with its results (step 5), not to free a name. Never clean up without the user's go-ahead: only the workers the user picked go, and never suggest which ones to pick.

## 1. Scan

Scan the current repository: the git checkout this session works in, the top level of its working directory (step 0's `ROOT` when the user named no other repository).

```bash
CUR="$(git -C "<this session's working directory>" rev-parse --show-toplevel)"
python3 "<skill directory>/scripts/runs.py" scan --root "$CUR"
```

When that is not inside a git repository, there is no current repository; then, and when the user asks for every repository's workers, scan them all:

```bash
python3 "<skill directory>/scripts/runs.py" scan --all
```

Add `--fetch` when the user wants merge and push status checked against the remote; without it, remote-tracking refs may be stale.

It only looks at runs recorded in `runs.json` (SKILL.md step 3 records each worker). herdr cannot tell which worktrees this skill created, and removing a worktree the user made by hand could destroy their work.

`workers` holds every open run of the scanned repositories, the ones this run just started included (they are `working`), in registry order. `open_elsewhere` is the number of open runs in other repositories (`0` with `--all`). Each entry has:

| Field | Meaning |
|---|---|
| `name`, `branch` | the worker and its branch |
| `summary` | what it was started to do: the one-line task summary given to `runs.py add` (SKILL.md step 3), or for an older run its brief's title; `null` when neither exists |
| `agent_status` | herdr's status for the worker (`idle`, `done`, `working`, `blocked`); `null` when no agent is there or its place is closed |
| `last_activity` | the branch's last commit, or when the run started if the branch has no commits |
| `work` | where its work stands against the branch it came from (below); `work.text` is the wording for the table |
| `cleanable`, `blockers` | whether it can be cleaned up now, and if not, what blocks it |
| `worktree_exists` | `false` when the worktree is already gone and only the record is left |
| `root`, `remove_command`, `agent`, `session_id` | for step 3; not shown in the table |

`work.state` is the first of these that holds, checked against `from_branch` and then `origin/<from_branch>` (the matching one is `work.into`):

| `work.state` | `work.text` | Meaning |
|---|---|---|
| `no_commits` | no commits | the branch has no commits since the worker started |
| `merged` | merged into main | the branch is an ancestor of main |
| `same_patches` | in main by patch (cherry-pick or rebase) | main lacks the commits, but `git cherry` finds an equivalent patch for every one of them |
| `same_content` | in main by content (squash merge) | every file the branch changed is identical in main |
| `pushed` | pushed, not merged | `origin/<branch>` holds every commit; a pull request may still be under review |
| `not_merged` | not merged (3 commits) | none of the above; the count is what main lacks |
| `unknown` | unknown: branch not found | the branch, or the whole repository, is gone |

Where the work stands never blocks cleanup: the branch and its commits stay, and a cleaned worker can be resumed. It is there for the user to decide. A worker is `cleanable` unless one of these `blockers` holds:

| Blocker | Why |
|---|---|
| `working`, `blocked`; `<plan>-rev is working` (a dispatch plan's reviewer tab beside a tab worker) | never cut off a worker mid-task or while it waits for the user |
| `user is viewing its workspace`, `its tab` or `<plan>-rev` | the screen they are reading should not vanish |
| `3 uncommitted changes` | removing the worktree would lose them; git and herdr refuse anyway |
| `git status failed`, `could not read the worktree's HEAD` | its changes cannot be checked |
| `1 commit on no branch (detached HEAD)` | that commit lives only in the worktree's HEAD and would go with it |
| `herdr could not be queried (<code>)` | its status is unknown; a failure is never read as "closed" |

A run whose worktree is already gone (`worktree_exists: false`) has nothing left to delete: its `remove_command` is `null`, and cleaning it up only marks the record. The herdr blockers apply to it all the same.

`untracked_worktrees` lists linked worktrees of the scanned repositories that are not in the registry (made by hand, by `EnterWorktree`, or before this skill kept records). Only show them; never remove them.

## 2. Show and ask

Run the scan right before showing it, not earlier: `focused` and the worker status change as the user moves around the sidebar. Under the heading **Cleanable workers**, in the user's language like the rest of the report, show one numbered table of the `cleanable` entries, in the scan's order:

| # | Name | For | Branch | Status | Last activity | Work |
|---|---|---|---|---|---|---|
| 1 | `proj-101` | Implement PROJ-101 | `feature/PROJ-101` | idle | 2026-10-12 (37 days ago) | not merged (3 commits) |
| 2 | `proj-98` | Fix the flaky payments test | `fix/flaky-payments` | done | 2026-11-02 (16 days ago) | in main by content (squash merge) |

- **For** is `summary`, cut to about 50 characters and ended with `…` when longer; empty when there is none.
- **Work** is `work.text`. **Last activity** is a date and how long ago.

Under the table, only when there are any:

- One line naming the workers left out (not `cleanable`), each with its blockers: `Left out: cli-run-impl (working), proj-7 (3 uncommitted changes)`. They stay visible this way: a worker with uncommitted changes cannot be cleaned up until they are committed, and hiding it would let it pile up unnoticed again.
- With `--root`, one line with `open_elsewhere`: "N open workers in other repositories; ask to clean up all workers to see them."
- The untracked worktrees, one line each, as not this skill's to remove.

When nothing is cleanable, say so in one line instead of the table, add the lines above, and ask nothing.

Then let the user pick:

- **One to four cleanable workers**: one multiple-choice question that allows several answers, one option per worker, plus "None" while there is room. With four there is none, so the question says that answering "none" keeps them all.
- **More than four**: ask for the numbers ("1 4 7", or "none").

"None" is always a valid answer. A worker that is not in the table cannot be picked; if the user names one, say what blocks it.

## 3. Clean up each picked worker

Map the numbers or options to names using the table that was shown, then scan again (the same `--root` or `--all`) right before removing anything. Clean up each picked worker that is still `cleanable` in the new scan; for one that no longer is, report its blockers and leave it.

Run the entry's `remove_command`, then mark it with the entry's own `root`:

```bash
<remove_command from scan>
python3 "<skill directory>/scripts/runs.py" mark-cleaned --root "<root from scan>" --name <name> --agent <agent from scan> --session-id <session_id from scan>
```

`remove_command` is `herdr worktree remove --workspace <id>` while the workspace is open. If the user already closed the workspace, the worktree has no workspace to remove it with, so it is `git -C <root> worktree remove <path>`. For a tab worker (`placement: tab`) it is `git -C <root> worktree remove <path> && herdr tab close <tab>`: herdr never opened that worktree, and only the worker's own tab closes, after the worktree is gone. The tab counts as the worker's only while it still carries the worker's name, the label `worker-pane.py` gave it; once it is closed, or carries another label (ids reused after a herdr restart, or a tab the user took over), it is neither judged nor closed, and the command is just the first part. A dispatch plan's `<plan>-impl` placed as a tab has its reviewer tab `<plan>-rev` beside it in the same worktree (`references/dispatch.md`): the scan judges that tab too (the run is left out while it is working, blocked or being viewed) and its `remove_command` closes it as well. All of them refuse to delete uncommitted changes.

Remove first, then mark. If the removal fails (for example, a change appeared since the scan), do not retry with `--force`; report it and leave the run open. For a run whose worktree is already gone (`remove_command: null`), only run `mark-cleaned`: the branch still exists, so it can be resumed like any cleaned run. The scan re-reads the agent and session reference from the pane just before removal, so the record holds the latest ones.

## 4. Report

Report every cleaned worker with the clues needed to bring it back, in a table:

| Name | For | Branch | Work | Agent | Session ID | To resume |
|---|---|---|---|---|---|---|
| `proj-101` | Implement PROJ-101 | `feature/PROJ-101` | not merged (3 commits) | `claude` | `40e7b47d-…` | ask "resume proj-101" |

Below the table, say that the branches stay, and how to resume by hand as well: recreate the worktree at the recorded path, open a tab there, then start the agent with its native resume option. Asking "resume <name>" does the same and also puts the worker back under its repository's space.

```bash
git -C <root> worktree add <worktree> <branch>
<the agent's resume command for this session id>   # in a tab whose cwd is <worktree>
```

Work out that resume command the same way `references/resume.md` step 3 does (herdr's session-state docs, then the installed agent's `--help`), and write the concrete command into the report rather than a placeholder. If there is no session ID, say that the worktree can be recreated from the branch but the conversation may not be restorable.

Then name any picked worker that was not cleaned up, with the reason.
