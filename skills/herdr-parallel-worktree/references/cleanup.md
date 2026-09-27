# Cleaning up finished workers

Every run leaves a worktree and a workspace behind, and they pile up. This document covers when a worker may be cleaned up, how to confirm with the user, and how to report so that every cleaned session can be resumed later (`references/resume.md`).

Cleaning up removes the worktree and closes its workspace (`herdr worktree remove`). The branch, the brief and the worker's Claude session log all stay, which is what makes resuming possible.

## When

- **Before starting new workers (step 0)**: scan, and offer the candidates in the same confirmation question as the new tasks. Never clean up without that confirmation.
- **On request**: "clean up finished worktrees", "정리해줘". Scan and confirm the same way.

## 1. Scan

```bash
python3 "<skill directory>/scripts/runs.py" scan --root "$ROOT"
```

Add `--fetch` when the user wants merge and push status checked against the remote; without it, remote-tracking refs may be stale.

It only looks at runs recorded in `runs.json` (step 3 records each worker). herdr cannot tell which worktrees this skill created, and removing a worktree the user made by hand could destroy their work.

A run is a **candidate** only when all of these hold:

| Condition | Why |
|---|---|
| Worker is not `working` or `blocked` | never cut off a worker mid-task or while it waits for the user |
| User is not viewing the workspace (`focused` is false) | the screen they are reading should not vanish |
| No uncommitted changes in the worktree | removing it would lose them; herdr refuses anyway without `--force` |
| The result is safe elsewhere: no commits at all, merged into the branch it was created from, or pushed with nothing unpushed | the branch survives removal, but unmerged and unpushed work is most likely still under review |

Squash- or rebase-merged branches are not ancestors of the target branch, so they show as `pushed, not merged`; they are still cleanable.

Everything else lands in `keep` with its reasons. `stale` lists recorded runs whose worktree directory is already gone (removed outside this skill); there is nothing left to delete. `untracked_worktrees` lists linked worktrees of this repository that are not in the registry (made by hand, or before this skill kept records). Only show them; never remove them.

## 2. Confirm

Run the scan right before asking, not earlier: `focused` and the worker status change as the user moves around the sidebar. Show candidates and kept runs in the confirmation question. For candidates, include why they qualify (`no commits`, `merged into main`, `pushed, not merged`). Mark "pushed, not merged" clearly: a pull request may still be under review and the user may want to keep editing locally. For kept runs, show the reasons, so the user knows what to do to make them cleanable (merge, push, commit, answer the blocked worker).

Offer: "clean up all candidates", "choose which", "clean up none".

## 3. Clean up each approved candidate

Run the entry's `remove_command`, then mark it:

```bash
<remove_command from scan>
python3 "<skill directory>/scripts/runs.py" mark-cleaned --root "$ROOT" --name <name> --session-id <session_id from scan>
```

`remove_command` is `herdr worktree remove --workspace <id>` while the workspace is open. If the user already closed the workspace, the worktree has no workspace to remove it with, so it is `git -C <root> worktree remove <path>`. Both refuse to delete uncommitted changes.

Remove first, then mark. If the removal fails (for example, a change appeared since the scan), do not retry with `--force`; report it and leave the run open. For `stale` runs, only run `mark-cleaned`: the branch still exists, so they can be resumed like any cleaned run. `mark-cleaned` prints the run with its `resume` commands and whether the session log file still exists.

## 4. Report

Report every cleaned run with enough to bring it back, in a table:

| Name | Branch | Why it was cleanable | Session ID | To resume |
|---|---|---|---|---|
| `proj-101` | `feature/PROJ-101` | merged into main | `40e7b47d-…` | ask "resume proj-101" |

Below the table, give the manual commands from `mark-cleaned`'s `resume.manual` for anyone resuming without this skill:

```bash
herdr worktree create --cwd <root> --branch <branch> --path <worktree> --label <name>
claude --resume <session id>   # in the new workspace pane
```

If `session_file_exists` is false, say so: the worktree can still be recreated from the branch, but the conversation cannot be restored.

Then list the kept runs with their reasons in one line each, and any untracked worktrees.
