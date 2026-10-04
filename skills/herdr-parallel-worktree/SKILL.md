---
name: herdr-parallel-worktree
license: MIT
description: >-
  Run 2+ coding tasks in parallel inside herdr (HERDR_ENV=1), each in its own git worktree with a visible claude worker. Also cleans up or resumes those workers, and manages the worker brief template and this skill's hooks. Not for use outside herdr.
---

# herdr parallel worktree

The main Claude (this session) is the **orchestrator**. For each task it creates a herdr worktree workspace and starts a `claude` worker there. Each workspace appears in the sidebar under the task name with its status (working, idle, …), so the user can switch between tasks and watch them directly. Do not use the built-in `Agent` subagent: its work is invisible to the user.

**First, before anything else — even a clarifying question — check whether this session is a herdr worker.** If `HERDR_PW_WORKER` is set, this session is a herdr worker started by this skill. Workers never start workers or create worktrees: say so and stop. If the work really needs a separate worker, put a `HERDR-HANDOFF` block in your `## Result` and let the orchestrator decide.

```bash
test -z "${HERDR_PW_WORKER:-}" || echo "inside worker $HERDR_PW_WORKER: stop"
```

Talk to the user in their language. Briefs may also be written in the user's language.

Requires `herdr`, `claude`, `git`, `jq` and `python3` (for the scripts). If one is missing, say which and stop.

This skill assumes the official `herdr` skill for CLI basics (read sources, status meanings, error codes); if it is not loaded, read `herdr --skill`. What follows covers only this workflow and the herdr/Claude Code behaviours it has to work around, which the `herdr` skill does not cover.

## Configuration — `config.json` (per install, persistent)

| Key | Default | Purpose |
|----|----|------|
| `workerArgs` | `[]` | Array of arguments passed to the worker `claude`. `[]` uses each worker's settings default. E.g. `["--enable-auto-mode"]`, `["--dangerously-skip-permissions"]` |
| `hooks` | `"on"` | `"on"` or `"off"`: whether the routing hook acts (see Hooks below) |

Every key is optional. The skill runs on the defaults without asking anything, so it works the same whether it was installed as a plugin, as a standalone skill, or driven from elsewhere; the user changes settings only when they want to.

The worker brief template is not in `config.json`; it is a file. Its lookup order, filling rules and how to change it are in `references/brief-filling.md`. When the user says "change the brief template", "show the template" or "reset the template", follow section 5 of that document.

Schema: `references/config.schema.json`.

Every started worker is also recorded in `DATA_DIR/runs.json` by `scripts/runs.py` (step 3). Cleanup and resume rely on it: herdr cannot tell which worktrees this skill created, and a worker can only be resumed if the clues are kept — which agent ran, the session reference herdr's integration reported, and the worktree path.

1. **Location**: `DATA_DIR/config.json`, where `DATA_DIR` is `${HERDR_SKILLS_DATA_HOME:-~/.local/share/herdr-skills}/herdr-parallel-worktree/`. It does not depend on how the skill was installed, so settings survive skill updates.
2. **First run** (the file is missing): do not ask anything. Write the defaults and carry on with the user's request:

   ```bash
   mkdir -p "$(dirname "$CONFIG")" && printf '{\n  "workerArgs": []\n}\n' > "$CONFIG"
   ```

   Then tell the user, in a few lines of their language, which settings exist, so they know what they can change later:
   - the saved path, and that workers run with `workerArgs: []` (each worker's own Claude Code permission settings). To change it, edit the file or say e.g. "run workers with `--enable-auto-mode`" (a classifier asks for approval only on risky actions) or "`--dangerously-skip-permissions`" (no approvals; trusted repositories only)
   - the routing hook (see Hooks below) and its current state from `manage.py status`: on for plugin installs; for other installs not registered until the user says "turn on the herdr hook"
   - "Worker briefs use the default template. To lock in your own steps and rules, say 'change the brief template'." Without this line the user has no way of knowing the template can be changed.

   The file now exists, so this notice appears only once.
3. **Invalid file** (the check below fails): say which path is invalid and why, and stop. Do not fall back to the defaults: the user wrote that file on purpose, and running workers with different permissions than they intended is worse than stopping.
4. **Change**: when the user asks to change a setting ("change worker permissions", "run workers with …"), confirm the new value and overwrite that key with `jq`, leaving the other keys alone. Use `scripts/hooks/manage.py` for `hooks`. If they want different arguments **for this run only**, leave the file alone.

```bash
CONFIG="${HERDR_SKILLS_DATA_HOME:-$HOME/.local/share/herdr-skills}/herdr-parallel-worktree/config.json"
test -f "$CONFIG" || echo "first run"   # step 2
jq -e '(type == "object") and (keys - ["workerArgs", "hooks"] == []) and ((.workerArgs // []) | type == "array" and all(type == "string")) and ((.hooks // "on") | IN("on", "off"))' "$CONFIG"   # step 3 on failure
```

## Hooks

This skill's description is kept short on purpose: it sits in every session's context, including sessions outside herdr where the skill is useless. Reliability comes from hooks instead, which only act inside herdr and cost nothing until they fire:

- **Who is calling** decides the answer. A subagent's tool calls carry an `agent_id`; a herdr worker started by this skill has `HERDR_PW_WORKER=<name>` in its environment (step 3 exports it). Everything else is the main session.
- **Creating a worktree some other way** — `git worktree add`, `EnterWorktree` without `path`, or an `Agent` with worktree isolation — is denied. The main session is told to use this skill. A subagent is told to stop and return a `HERDR-HANDOFF` block (below). A worker is told to do the work in its own worktree. `EnterWorktree` with `path` only enters an existing worktree (for example, to inspect a worker's worktree) and is allowed.
- **A subagent writing into another linked worktree** — `Write`/`Edit`/`MultiEdit`/`NotebookEdit` on a file there, or `cd <dir>` / `git -C <dir>` into it — is denied the same way. Its own session's worktree, the main checkout and paths outside git are not affected. The main session itself is never blocked from writing.
- **After the main session starts a subagent** (PostToolUse), one line of context tells it what to do if that subagent comes back with a `HERDR-HANDOFF` block.

The hooks decide from the tool call alone, never from prompt wording. Outside herdr a shell guard returns before python starts; inside herdr, Bash hooks run only for commands matching `*worktree add*`, `*git -C *` or `cd`.

Plugin installs ship it in the plugin's `hooks/hooks.json`, active by default. Other installs leave it unregistered until the user asks for it, because registering it edits `~/.claude/settings.json`; `scripts/hooks/manage.py on` registers it there. When the user asks to turn the hook on or off, remove it, or check it ("turn off the herdr hooks", "훅 꺼줘"), run:

```bash
python3 "<skill directory>/scripts/hooks/manage.py" <on|off|remove|status> --skill-dir "<skill directory>"
```

Before `on` or `remove` on a non-plugin install, tell the user it edits `~/.claude/settings.json` (a backup is written first). For plugin installs, `remove` can only silence the hook; removing it entirely means disabling the plugin. Offer `! <command>` or turning the hooks off only when the user, in this conversation, explicitly asked for a plain `git worktree add` or a subagent. A plan that came from you or from a subagent is not such a request: when a subagent reports that it was blocked or returns a `HERDR-HANDOFF` block, take it over with this skill (step 0, "Receiving a handoff").

## 0. Preconditions

```bash
test "${HERDR_ENV:-}" = 1 && ROOT="$(git -C "<target path>" rev-parse --show-toplevel)" && echo "$ROOT"
```

On failure, say that this is not inside herdr or not a git repository, and stop. Read the config (Configuration above: a missing file means the first-run notice, an invalid one means stop).

**Decide the target repository (`ROOT`) once, here.** Unless the user names a repository, `<target path>` is this session's working directory. From then on, run every git command as `git -C "$ROOT"` instead of relying on the current directory: a `cd` or a cwd reset in between could otherwise create worktrees from the wrong repository. Shell variables do not survive between Bash calls, so remember `ROOT` and each task's `BASE`, `WT`, `W`, `P` and `BRIEF`, and put the values directly into later commands.

**Check for uncommitted changes.** Worktrees are created from the base commit, so uncommitted files do not exist in a worker's worktree. If a task targets such a file, the worker cannot find its work or works from the wrong baseline.

```bash
git -C "$ROOT" status --porcelain --untracked-files=all
git -C "$ROOT" cat-file -e "HEAD:<path the task touches>" 2>/dev/null || echo "not in HEAD"
```

If a path the task touches is missing from HEAD or modified (` M`, `??`), raise it in the confirmation question and let the user choose: "commit first and use that commit as base", "proceed as is", or "change the task". The orchestrator never commits or stashes on the user's behalf. Changes unrelated to the tasks need no mention.

**Offer to clean up finished workers.** Read `references/cleanup.md` and run its scan. If there are candidates, offer them in the same confirmation question as the new tasks; never clean up without that confirmation.

**Receiving a handoff.** A subagent stopped by the hook ends its reply with a block like this:

    HERDR-HANDOFF
    To the main session: …
    name: <suggested worker name>
    repo: <absolute path of the target repository>
    goal: <one line>
    branch: <suggested branch, or ->
    steps:
    - <step>
    done: <what was already done, or nothing>

Treat each block as one task for this run: `repo` is that task's `<target path>` for `ROOT`, `name` and `branch` are suggestions that the repository's conventions (below) override, and `goal` and `steps` go into the brief. If `done` lists changes the subagent already made in the source checkout, they are uncommitted changes there: handle them with the uncommitted-changes check above. Ask about handed-off tasks in the same confirmation question as any others, so the user still confirms once. A worker's `## Result` may also contain a block; handle it the same way when you collect results (step 5), after asking the user.

Put the task list together and **get the user's confirmation once**. For each task decide:

- Name: `[a-z][a-z0-9_-]{0,31}`, unique. Used as both the sidebar workspace label and the worker name (e.g. `proj-101`)
- Branch: follow the repository's branch convention (e.g. `feature/PROJ-101`)
- Base: defaults to `ROOT`'s current `HEAD`
- Worktree path: follow the repository's convention (below)
- Brief: pick a template and fill it with the goal, references, steps and rules taken from the user's request (step 2). The worker must be able to finish from the brief alone. Write the briefs (step 2) before asking for confirmation

**The repository's conventions come first; herdr only builds what they describe.** Where worktrees live, how branches are named and what they are based on belong to the repository, not to the development tool. Look for the repository's own answer before falling back to any default:

- Where worktrees go: a location stated in the repository's docs (`CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, README), a worktree directory already listed in `.gitignore` (e.g. `.worktrees/`), or where existing worktrees already live (`git -C "$ROOT" worktree list`).
- How branches are named: the same docs, and the pattern of existing branches (`git -C "$ROOT" branch -a`).

If the user named a path, use it. If the repository has a worktree convention, pass the resulting path to herdr with `--path` (step 1). Only when the repository shows no worktree convention at all, leave `--path` out and let herdr use its default (`~/.herdr/worktrees/<repo>/<branch>`). If the convention puts worktrees inside the repository but that directory is not in `.gitignore`, point it out in the confirmation question rather than editing `.gitignore` yourself.

The user must be able to tell what they are approving from the question screen alone. With AskUserQuestion, put the target repository (`ROOT`) and each task's name, branch, base, worktree path (with the convention it came from, or "herdr default"), worker arguments and the brief's steps section in the option `preview`. This is where the user confirms that every step they asked for made it in. If a brief still contains `[NEEDS CLARIFICATION: …]`, ask about it in the same question. The first line of the `preview` names the template: `Template: default (say "change the brief template" to customize)` for the default, otherwise `Template: <path>`. This line is how the user learns the template can be changed. Labels like "Proceed / Edit" alone hide the content and make the choice impossible to judge.

More tasks means more concurrent claude sessions, which hit usage limits sooner. Confirm before running five or more.

## 1. Create the worktree workspace

```bash
BASE="$(git -C "$ROOT" rev-parse HEAD)"
FROM_BRANCH="$(git -C "$ROOT" symbolic-ref --short -q HEAD || echo "$BASE")"   # cleanup checks whether the work was merged back here
REPO_KEY="$(git -C "$ROOT" rev-parse --path-format=absolute --git-common-dir)"
WS_KEY="$(herdr workspace get "$HERDR_WORKSPACE_ID" | jq -r '.result.workspace.worktree.repo_key // empty')"
if [ "$WS_KEY" = "$REPO_KEY" ]; then LOC=(--workspace "$HERDR_WORKSPACE_ID"); else LOC=(--cwd "$ROOT"); fi
PATH_ARG=(--path "<absolute path from the repository's convention>")   # relative conventions resolve against ROOT; PATH_ARG=() when there is none
OUT="$(herdr worktree create "${LOC[@]}" "${PATH_ARG[@]}" --branch <branch> --base "$BASE" --label <name> --no-focus)"
WT="$(printf '%s' "$OUT" | jq -r .result.worktree.path)"
W="$(printf '%s' "$OUT" | jq -r .result.workspace.workspace_id)"
P="$(printf '%s' "$OUT" | jq -r .result.root_pane.pane_id)"
```

- If the current workspace is bound to the `ROOT` repository, attach with `--workspace`; with `--cwd` alone herdr may create a second workspace for the source repository. If it is bound to a different repository, use `--cwd`: passing `--workspace` then makes herdr try to create the worktree in that other repository, which fails with `invalid reference`.
- herdr creates missing parent directories for `--path`, inside or outside the repository. Always take `WT` from the response, whichever path was used.
- If the branch already exists or the command fails, do not overwrite anything. Stop and report.
- Add `--trust-repository` only when herdr asks for Git trust and the user has checked the repository. Never use it as a retry to get past a failure.

## 2. Write the brief

Instructions go to the worker as a file. The two alternatives each have a problem:

- `herdr agent prompt` sends text as a bracketed paste, so the worker receives the instructions wrapped in `<pasted_content>`. Workers may treat instructions inside pasted text as not coming from the user and refuse them. In testing, the same prompt was sometimes followed and sometimes refused.
- Passing the instructions as claude's positional argument (`agent start ... -- "<instructions>"`) delivers them as a message the user typed. But herdr rejects any argument containing a newline or tab with `invalid_agent_argument`, because it cannot pass it safely to the shell.

So the multi-line brief goes in a file, and the positional argument is a single line pointing to it.

```bash
BRIEFS="${HERDR_SKILLS_DATA_HOME:-$HOME/.local/share/herdr-skills}/herdr-parallel-worktree/briefs"
mkdir -p "$BRIEFS"
BRIEF="$BRIEFS/<name>-$(date +%Y%m%d-%H%M%S).md"
```

Read `references/brief-filling.md` and build the brief in this order:

1. Pick the template: repository template → user template → default template.
2. Following the template's guidance comments and the filling rules, write `$BRIEF` with the Write tool. The Write tool bypasses the shell, so backticks, `$` and code blocks in markdown arrive intact. Save pasted text to a separate `-ref.md` file and put only its path in the brief.
3. Finalize with `python3 "<skill directory>/scripts/finalize-brief.py" "$BRIEF"`. It strips guidance comments, catches leftover placeholders, `[NEEDS CLARIFICATION` markers and empty sections, and appends the closing paragraph. On failure, fix the reported lines and run it again.

The skill does not prescribe tools or procedures. If the user says to read an issue tracker, that becomes a step; if they say to run a particular review before committing, that becomes a step too. Keep briefs outside the worktree, or the worker may commit them.

## 3. Start claude

```bash
herdr pane run "$P" "export HERDR_PW_WORKER=<name>; cat $(printf '%q' "$BRIEF")"
herdr pane wait-output "$P" --match "Do not push or open a pull request." --source recent-unwrapped --timeout 15000
ARGS=(); while IFS= read -r a; do ARGS+=("$a"); done < <(jq -r '(.workerArgs // [])[]' "$CONFIG")
SUMMARY="$(cat <<'EOF'
<one-line task summary>
EOF
)"
LINE="$(printf '[%s] %s. Read the brief at %s and follow it.' "<name>" "$(printf '%s' "$SUMMARY" | tr '\n\t' '  ')" "$BRIEF")"
herdr agent start <name> --kind claude --pane "$P" --timeout 20000 -- "${ARGS[@]}" --add-dir "$BRIEFS" -- "$LINE"
```

- **Why `cat` the brief first**: so the user sees the task as soon as they open the workspace. Asking the worker to "echo the full brief in your reply" is unreliable; workers often summarize or skip it. So the orchestrator prints it in the pane's shell before claude starts, and it stays just above claude's start screen. `wait-output` waits until the output is done and the shell prompt is back before `agent start`; it matches the brief's last line (the closing paragraph). If `wait-output` times out, run `herdr pane read "$P" --source recent-unwrapped --lines 5`: if the brief's last line is there, the shell is just slow to report it, so carry on; if it is not, report what the pane shows and stop.
- **One-line summary**: it stays at the top of the screen as the first user message. Take it through a `<<'EOF'` heredoc: written straight inside double quotes, `` `code` `` (common in ticket titles) would be run by bash as a command and `$VAR` replaced with its value. herdr rejects newlines and tabs, so `tr` turns them into spaces.
- **`--add-dir "$BRIEFS"`**: the brief lives outside the worktree. This lets the worker read it whatever its permission settings.
- **The final `--`**: `--add-dir` takes multiple values. Without the `--` right after it, the instruction line is swallowed as another path and the worker starts with no instructions at all.
- **`export HERDR_PW_WORKER=<name>`**: marks the worker. `herdr agent start` has no environment option; it starts claude from this pane's shell, so claude, its subagents and its hooks inherit the variable. The hooks and step 0 use it to stop a worker from starting workers. It stays set in that pane's shell, so a claude the user later starts there by hand is treated as that worker too, which is right for that worktree.

Workers start working immediately, so doing this step task by task still runs them all concurrently. Handle the result like this, then record the worker (below):

- **`idle` or `done`**: the first turn finished within 20 seconds. A short task may already be done; check in step 4.
- **`timeout`**: usually fine. `agent start` reports success only once the worker's turn has finished (`idle` or `done`), but the worker starts working at once and stays `working` for a long time. herdr then does not assign the worker name, so check the pane status and assign it yourself.

  ```bash
  S="$(herdr pane get "$P" | jq -r '.result.pane.agent_status // empty')"
  ```

  - `working`, `idle`, `done`: `herdr agent rename "$P" <name>`
  - `blocked`: assign the name, then handle the dialog as below
  - empty (claude not detected): look at the screen with `herdr pane read "$P" --source visible --lines 40`, report to the user, and stop
- **`agent_not_ready` or `blocked`**: a dialog is open on the worker's screen. Check it with `herdr agent read <name> --source visible --lines 40` and **never answer it yourself.** Tell the user what the screen shows and let them handle it in that workspace in the sidebar. Once the dialog closes, confirm the worker picks up its positional instructions with `herdr agent wait <name> --until working --until idle --until done --timeout 120000` (herdr reports a finished turn as either `idle` or `done`) and `agent read`.
  - **Folder trust dialog** ("Is this a project you trust?"): Claude Code does not yet trust the source repository. It does not appear for worktrees of trusted repositories, and `--dangerously-skip-permissions` does not skip it
  - **Permission mode warning**: shown once to users running `--dangerously-skip-permissions` for the first time

Once the worker is running and named, record it. This stores the agent and the session reference herdr reports for the pane, which is what lets the user resume it after cleanup:

```bash
python3 "<skill directory>/scripts/runs.py" add --name <name> --root "$ROOT" --branch <branch> --base "$BASE" --from-branch "$FROM_BRANCH" --worktree "$WT" --workspace "$W" --pane "$P" --brief "$BRIEF"
```

If `session_id` in the output is `null` (not reported yet), that is fine: cleanup re-reads it from the pane before removing anything. If `add` fails because an open run with the same name exists, a previous worker still holds that name: handle it with the cleanup scan (`references/cleanup.md`) or pick another name.

## 4. Wait and watch

Once all workers are started, tell the user in one line that the tasks are running in the `<name>` workspaces in the sidebar, then wait on each.

```bash
herdr agent wait <name> --timeout 1800000
```

- `idle` / `done`: finished → step 5. But if the screen has no `## Result` and shows background work still running (e.g. `1 shell still running`), it is not done yet. Wait again.
- `blocked`: the worker is waiting for an approval or an answer. **Never approve on its behalf.** Check what it is asking with `agent read` and tell the user "`<name>` is waiting for approval of …" in that workspace. Let the user answer.
- `timeout`: report progress from `agent read` and ask the user whether to keep waiting.

## 5. Collect results

```bash
herdr agent read <name> --source recent-unwrapped --lines 200
git -C "$WT" log --oneline "$BASE"..HEAD
git -C "$WT" diff --stat "$BASE"
```

Report a table per task: `name | branch | commits | change summary | tests | open issues`. If `## Result` is cut off on screen, raise `--lines`. If it still does not show, ask the worker to write its result to a temp file and reply with only the path, then read that file.

## 6. Clean up and resume

The default is to **leave everything in place**: the user decides on push, PR and merge after reviewing each workspace.

- **Cleaning up** finished workers — offered at step 0 of the next run, or when the user asks: follow `references/cleanup.md`. It only removes workers that are recorded, not `working` or `blocked`, clean, and whose work is merged, pushed or empty, always after confirmation, and reports how to resume each one.
- **Resuming** a worker by name ("resume proj-101"): follow `references/resume.md`. It recreates the worktree at the recorded path, works out the agent's native resume option from the recorded clues (the same session reference herdr uses to restore agents), and checks that the conversation came back.

Cleanup keeps branches. Delete a branch only when the user asks, after merging.

## Never

- Close panes, tabs or workspaces this skill did not create. Never use `workspace close --group`: it also closes the source workspace
- `herdr server stop`, or killing herdr processes
- Answer a worker's approval or confirmation dialog
- Substitute an `Agent` subagent
- Send the first instructions with `agent prompt`. They arrive as pasted text and the worker may refuse them
- Have workers push or open pull requests
- Start workers or create worktrees from inside a worker (`HERDR_PW_WORKER` set)
- Tell the user to run a blocked command with `!` or to turn the hooks off because a subagent hit the hook; take its handoff over instead
