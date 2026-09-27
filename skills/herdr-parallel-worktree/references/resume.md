# Resuming a worker

Use when the user asks to bring back a worker — "resume proj-101", "proj-101 다시 열어줘", "continue the payments worker". It works for workers that were cleaned up (`references/cleanup.md`) and for open workers whose claude has exited.

A Claude Code session is stored per working directory (`~/.claude/projects/<path>/<session id>.jsonl`). So a session can only be resumed from the **same worktree path** it ran in. Cleanup keeps the branch and the session log, so recreating the worktree at the recorded path and running `claude --resume <session id>` restores the full conversation.

## 1. Find the run

```bash
python3 "<skill directory>/scripts/runs.py" show --root "$ROOT" --name <name>
```

- No match: list the runs (`show` without `--name`) and ask which one.
- `state: open` and its workspace still exists: nothing to recreate. Tell the user it is in the sidebar; if claude exited there, go to step 3 with the recorded pane.
- `state: cleaned`: continue.

Check before recreating:
- The branch still exists: `git -C "$ROOT" rev-parse --verify --quiet <branch>`. If it was deleted, the worktree cannot be recreated from it; report and stop.
- Nothing occupies the recorded worktree path. If something does, stop and report; never overwrite it.
- `session_file_exists`. If false, the worktree can come back but the conversation cannot; say so and ask whether to start a fresh worker there instead.

## 2. Recreate the worktree at the same path

```bash
OUT="$(herdr worktree create --cwd "$ROOT" --branch <branch> --path <worktree> --label <name> --no-focus)"
W="$(printf '%s' "$OUT" | jq -r .result.workspace.workspace_id)"
P="$(printf '%s' "$OUT" | jq -r .result.root_pane.pane_id)"
```

The branch already exists, so herdr checks it out instead of creating it. The path must match the recorded one exactly, or `claude --resume` will not find the session.

## 3. Resume claude

A freshly created pane's shell may not be ready yet, and `agent start` then fails with `agent_pane_busy`. Wait for the prompt first:

```bash
herdr pane run "$P" "echo shell-ready"
herdr pane wait-output "$P" --match shell-ready --timeout 10000
ARGS=(); while IFS= read -r a; do ARGS+=("$a"); done < <(jq -r '.workerArgs[]' "$CONFIG")
herdr agent start <name> --kind claude --pane "$P" --timeout 20000 -- "${ARGS[@]}" --resume <session id>
```

If the user gave a follow-up instruction ("resume proj-101 and fix the failing test"), append `-- "<one-line instruction>"` after `--resume <session id>`, built like step 3's `LINE` in SKILL.md. Without it, the worker opens with its history and waits.

Handle `timeout`, `blocked` and `agent_not_ready` exactly as in SKILL.md step 3.

## 4. Record and report

```bash
python3 "<skill directory>/scripts/runs.py" mark-open --root "$ROOT" --name <name> --workspace "$W" --pane "$P"
```

Tell the user the `<name>` workspace is back in the sidebar with its previous conversation, and continue with SKILL.md steps 4 and 5 if a follow-up instruction was given.
