# Resuming a worker

Use when the user asks to bring back a worker — "resume proj-101", "proj-101 다시 열어줘", "continue the payments worker". It works for workers that were cleaned up (`references/cleanup.md`) and for open workers whose agent has exited.

This document gives clues and a way of working, not a per-agent recipe. Agents and their options change faster than any table could be kept current, so work out how to resume the agent in front of you, confirm it on the installed version, and check that it actually worked.

## 1. Gather the clues

```bash
python3 "<skill directory>/scripts/runs.py" show --root "$ROOT" --name <name>
```

- No match: list the runs (`show` without `--name`) and ask which one.
- `state: open` and its workspace still exists: nothing to recreate. Tell the user it is in the sidebar; if the agent exited there, go to step 3 with the recorded pane.
- `state: open` but `herdr workspace get <workspace>` says `workspace_not_found`, and the worktree directory is still there: the workspace was closed and the worktree kept. Do not recreate anything. Reopen it with `herdr worktree open --cwd "$ROOT" --path <worktree> --label <name> --no-focus`, take `W` and `P` from its output as in step 2, go to step 3, and record the new location with `runs.py relocate --root "$ROOT" --name <name> --workspace "$W" --pane "$P"` (not `mark-open`, which is for cleaned runs).

The record holds facts herdr reported, not instructions:

| Field | What it tells you |
|---|---|
| `agent` | which agent herdr detected in the pane (e.g. `claude`, `codex`) — also the `--kind` for `herdr agent start` |
| `session_id`, `session_source` | the native session reference the agent's herdr integration reported. herdr itself uses this same reference to resume agents after a server restart |
| `worktree` | the exact path the agent ran in. Many agents store or look up sessions per working directory, so recreate this path exactly |
| `branch` | what to check out there |

If you can tell where this agent keeps its sessions (its documentation or `--help` usually says), check that the reference still exists before recreating anything; if it does not, say the conversation cannot come back and ask whether to start a fresh session there instead.

If `session_id` is missing, the agent's herdr integration did not report one (not installed, or too old). The conversation may still be recoverable through the agent's own "continue the latest session in this directory" option, if it has one.

## 2. Recreate the worktree at the same path

Check first: the branch still exists (`git -C "$ROOT" rev-parse --verify --quiet <branch>`), and nothing occupies the recorded path. If the branch is gone, the worktree cannot come back; report and stop. Never overwrite an occupied path.

Choose where to attach it exactly as in SKILL.md step 1 (`--workspace "$HERDR_WORKSPACE_ID"` when the current workspace is bound to `ROOT`, otherwise `--cwd "$ROOT"`):

```bash
OUT="$(herdr worktree create "${LOC[@]}" --branch <branch> --path <worktree> --label <name> --no-focus)"
W="$(printf '%s' "$OUT" | jq -r .result.workspace.workspace_id)"
P="$(printf '%s' "$OUT" | jq -r .result.root_pane.pane_id)"
```

The branch already exists, so herdr checks it out instead of creating it.

## 3. Work out how to resume this agent

Find the agent's native way to resume a session by its reference, starting from the most authoritative source:

1. **herdr's own restore behaviour.** herdr resumes agents after a server restart with each agent's native resume command; its session-state documentation (https://herdr.dev/docs/session-state/, or `herdr --skill`) describes how. What herdr does is the best hint, because it uses the same session reference you have.
2. **The installed agent.** `<agent> --help` (and subcommand help) shows what this version actually supports. Confirm the option exists here before relying on it; documentation may describe a newer or older version.
3. **The agent's documentation**, when the first two leave it unclear.

Then start it in the recreated pane. A freshly created pane's shell may not be ready yet, and `agent start` then fails with `agent_pane_busy`, so wait for the prompt first:

```bash
herdr pane run "$P" "export HERDR_PW_WORKER=<name>; echo shell-ready"
herdr pane wait-output "$P" --match shell-ready --timeout 10000
BRIEFS="${HERDR_SKILLS_DATA_HOME:-$HOME/.local/share/herdr-skills}/herdr-parallel-worktree/briefs"
herdr agent start <name> --kind <agent> --pane "$P" --timeout 20000 -- <worker args, if they apply to this agent> --add-dir "$BRIEFS" <resume arguments you found>
```

The `export` marks the resumed claude as worker `<name>`, exactly as step 3 of the skill does for a new worker. `--add-dir "$BRIEFS"` lets it read follow-up files (`references/deliver.md`); drop it for an agent that has no such option.

`config.json`'s `workerArgs` were written for the agent the worker was started with; pass them only if they belong to this agent. If there is a follow-up instruction ("resume proj-101 and fix the failing test", or a handoff for this worker), resume without it first, then deliver it with `references/deliver.md` steps 2, 4 and 5: a file plus one line, which a resumed worker follows with its earlier conversation intact (tested). Handle `timeout`, `blocked` and `agent_not_ready` exactly as in SKILL.md step 3.

## 4. Verify, record and report

Check that the conversation really came back: `herdr agent read <name> --source recent-unwrapped --lines 60` should show the earlier turns. If the agent started fresh instead, say so plainly — the worktree and branch are back, but the history is not — and offer to continue as a new session there.

```bash
python3 "<skill directory>/scripts/runs.py" mark-open --root "$ROOT" --name <name> --workspace "$W" --pane "$P"
```

`mark-open` re-reads the agent and session reference from the pane, so a fresh session started in place of the old one replaces the stale clues.

Tell the user the `<name>` workspace is back in the sidebar, and which command resumed it, so they can reuse it themselves. Continue with SKILL.md steps 4 and 5 if a follow-up instruction was given.
