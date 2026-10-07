# Delivering work to an existing worker

Use this when a `HERDR-HANDOFF` block names a worker as its `owner:` (SKILL.md step 0, "Receiving a handoff"), or when the user asks to give more work to a worker they already have ("give this to proj-101 too"). The work goes to that worker, in its own worktree; never start a second worker for it.

The user confirms once, in the same question as any other tasks of this run: show the worker's name, the goal and the steps you are about to deliver.

## 1. Find the worker

```bash
python3 "<skill directory>/scripts/runs.py" show --root "$ROOT" --name <name>
```

`ROOT` is the repository the worker belongs to (its record's `root`; for a handoff, the block's `repo:`). No record: tell the user that `<name>` is not a worker this skill started, and handle the block as `owner: none` only if they agree.

## 2. Write the follow-up

Write the instructions as a file, exactly like a first brief, so the worker reads them in full instead of receiving pasted text:

```bash
BRIEFS="${HERDR_SKILLS_DATA_HOME:-$HOME/.local/share/herdr-skills}/herdr-parallel-worktree/briefs"
FOLLOWUP="$BRIEFS/<name>-followup-$(date +%Y%m%d-%H%M%S).md"
```

Write `$FOLLOWUP` with the Write tool: the block's `goal`, its `steps`, and its `done:` (what was already changed, and where, so the worker does not redo or fight it). Then finalize it like a brief: `python3 "<skill directory>/scripts/finalize-brief.py" "$FOLLOWUP"`. Workers started by this skill can read `BRIEFS` (`--add-dir`).

## 3. Make sure a claude is running there

Check the record against herdr, in this order:

| What you find | What to do |
|---|---|
| `state: open`, `herdr agent get <name>` shows the agent | Running. Go to step 4. |
| `state: open`, the workspace exists (`herdr workspace get <workspace>`), but no agent in the pane | The session ended. Resume it in that pane: `references/resume.md` step 3, with the recorded `pane`. |
| `state: open`, `herdr workspace get <workspace>` says `workspace_not_found`, and the worktree directory still exists | The workspace was closed and the worktree kept. Reopen it, resume, and record where it is now (below). |
| `state: cleaned`, or the worktree directory is gone | Follow `references/resume.md` from step 1; it recreates the worktree and records the run as open again. |

Reopening a closed workspace whose worktree is still there:

```bash
OUT="$(herdr worktree open --cwd "$ROOT" --path <worktree> --label <name> --no-focus)"
W="$(printf '%s' "$OUT" | jq -r .result.workspace.workspace_id)"
P="$(printf '%s' "$OUT" | jq -r .result.root_pane.pane_id)"
```

Then resume in `$P` with `references/resume.md` step 3, and record the new location:

```bash
python3 "<skill directory>/scripts/runs.py" relocate --root "$ROOT" --name <name> --workspace "$W" --pane "$P"
```

A resumed worker keeps its conversation: in testing it remembered what it had done before and followed the follow-up.

## 4. Wait until it is free

```bash
herdr agent get <name> | jq -r .result.agent.agent_status
```

- `blocked`: a dialog is open. **Never answer it.** Tell the user what the worker is waiting for, and deliver after they have handled it.
- `working`: wait for the current turn, so the follow-up becomes its own turn:

  ```bash
  herdr agent wait <name> --until idle --until done --timeout 600000
  ```

  If the wait times out, send anyway: a prompt sent while a worker is working is queued and runs after the current work finishes, without interrupting it (tested).
- `idle` / `done`: go on.

## 5. Send one line pointing to the file

```bash
herdr agent prompt <name> "[<name>] Follow-up: read $FOLLOWUP and follow it."
```

Check that it was taken up: `herdr agent read <name> --source recent-unwrapped --lines 40` should show the worker reading the file. Then tell the user, in one line, that `<name>` has the follow-up, and continue with SKILL.md steps 4 and 5 for that worker.
