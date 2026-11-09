---
name: herdr-parallel-worktree
license: MIT
description: >-
  Lets one Claude session hand coding work inside herdr (HERDR_ENV=1) to visible workers: each task gets its own git worktree and its own claude in the herdr sidebar, where the user can watch and step in. Use it when a task, even a single ticket, should run in its own worktree or branch that the user can watch or step into (for example to review before the PR), when several tasks or alternative fixes should run at the same time, when a subagent or hook hands back a HERDR-HANDOFF block, or to give an existing worker more work, resume it or clean up finished ones; it also manages the worker brief template and its hooks. Not for quick edits done in this session, explanations, or anything outside herdr.
---

# herdr parallel worktree

Inside herdr, the main Claude session (this one) is the **orchestrator**: every task it hands off, one or many, becomes a herdr worker. For each, it creates a worktree and starts a `claude` worker there, in a tab of its own. The worker lands under its repository's space in the sidebar: as a workspace named after the task, under this session's space or the one herdr already shows for that repository, or, when herdr shows none, as a tab in this session's space (step 1). Either way the sidebar shows its status (working, idle, …), so the user can switch between tasks and watch them directly. Do not hand a task to the built-in `Agent` subagent: its work is invisible to the user. Inside a worker, subagents are fine (for example `superpowers:subagent-driven-development`): they are how the worker does its own task. When another skill tells this session to dispatch a subagent per ticket or task (an implementer, a reviewer, a fixer) and `HERDR_ENV=1`, that dispatch runs as a herdr tab instead: follow `references/dispatch.md`, which keeps the other skill's process and uses its prompt as the brief.

**First, before anything else — even a clarifying question — check whether this session is a herdr worker.** If `HERDR_PW_WORKER` is set, this session is a herdr worker started by this skill. Workers never start workers or create worktrees: say so and stop. Work outside your own worktree (for a worker without one, the working directory your brief gives you) and the outside paths your brief lists — another worker's worktree, a main checkout, a new worktree — is not yours either: put a `HERDR-HANDOFF` block (with its `owner:` line) in your `## Result` and let the orchestrator pass it on.

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
| `dispatchSkills` | `["superpowers:subagent-driven-development", "superpowers:dispatching-parallel-agents"]` | Array of skill names that hand each task to an agent. Loading one points the main session to `references/dispatch.md` (see Hooks below) |

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
jq -e '(type == "object") and (keys - ["workerArgs", "hooks", "dispatchSkills"] == []) and ((.workerArgs // []) | type == "array" and all(type == "string")) and ((.hooks // "on") | IN("on", "off")) and ((.dispatchSkills // []) | type == "array" and all(type == "string"))' "$CONFIG"   # step 3 on failure
```

## Hooks

This skill's description is kept short on purpose: it sits in every session's context, including sessions outside herdr where the skill is useless. Reliability comes from hooks instead, which only act inside herdr: there, each session starts with one short paragraph naming its role, and the other hooks cost nothing until they fire:

- **Each session learns its role when it starts** (SessionStart): the main session that it is the orchestrator, which hands off every task, even a single ticket, as a worker, and runs another skill's per-task dispatch as tabs (`references/dispatch.md`); a worker its name, that its brief says where it works and what it may touch outside it, and that it does not start workers or create worktrees (nested workers break herdr's tabs), write where another session works (that goes back in its `## Result`, as a handoff for code work), or send anything to the orchestrator's pane. A step its brief tells it to take, such as sending a re-review request to another tab, is its own; if the brief asks for something these rules forbid, it says so in its `## Result`. Subagents get nothing.
- **Who is calling** decides the answer. A subagent's tool calls carry an `agent_id`; a herdr worker started by this skill has `HERDR_PW_WORKER=<name>` in its environment (step 3 exports it). Everything else is the main session.
- **The main session's own worktree is not blocked, but it is rarely what is needed.** Work on a task or ticket goes to a worker, even a single one; the worker's worktree follows the repository's conventions. `EnterWorktree` is for when the user asks for this session itself to move into a worktree. Claude Code makes it the way it always does: `.claude/worktrees/<name>` on branch `worktree-<name>` (a `/` in the name becomes `+`), with `.worktreeinclude` and its own cleanup. A PostToolUse hook then opens it in the herdr sidebar under its repository's space, by step 1's rule, and tells the session the workspace label; when herdr shows no space for the repository it opens nothing, and the session simply stays in its own tab. When `ExitWorktree` removes it, the hook closes that workspace. A herdr plugin may start a claude of its own in that workspace: it is a separate, idle session, and this one keeps working where it is. A detached `git worktree add` (`--detach`, or a commit that is not a branch) is a checkout for reading and passes too. Any other `git worktree add` from the main session is denied with the same guidance. A worker's worktree in a tab placement is made by `place.py` (step 1); the hooks judge tool calls and command text, not what the skill's own scripts run. A worktree from `claude --worktree` at launch is not a tool call, so it does not appear in the sidebar.
- **Handing work to an agent in its own worktree** goes through this skill, because the user cannot watch a subagent. An `Agent` with worktree isolation from the main session is denied and sent here. A subagent that tries to create a worktree in any way is told to stop and return a `HERDR-HANDOFF` block (below). A worker is told to do the work in its own worktree. `EnterWorktree` with `path` only enters an existing worktree (for example, to inspect a worker's worktree) and is allowed for everyone.
- **The session's first task dispatch is stopped once** (PreToolUse `Agent`/`Task`, main session in a main checkout): its description, model and prompt are saved to `$BRIEFS/dispatch-<session>-<time>.md`, and the denial points to `references/dispatch.md` and tells the session to start the tab from that file and carry on without asking. Searches and questions (`Explore`, `Plan`, `claude-code-guide`) pass, a dispatch whose draft cannot be saved passes (the session stays unmarked, so the stop moves to the next dispatch), and once a draft is saved every later dispatch passes: routing those is the session's own job (`references/dispatch.md`). A worktree-isolated `Agent` keeps the denial above.
- **Loading a skill that dispatches per task** (one listed in `dispatchSkills`), by the `Skill` tool (PostToolUse) or by a prompt that starts with `/<skill>` (UserPromptSubmit), adds one line of context pointing the main session to `references/dispatch.md`. Nothing is denied.
- **Writing outside one's own worktree** is answered by the **owner** of the target: a worker recorded in `runs.json`, the main checkout, or `none` (a linked worktree nobody owns). A subagent's or worker's `Write`/`Edit`/`MultiEdit`/`NotebookEdit` there is denied before it happens. A subagent of the main session may write to the main checkout (the main session's own). The main session itself is never blocked. Two more cases stop a worker and its subagents: a tab working in a worktree that `runs.json` records under another name does not write there (so the reviewer tab cannot `Write`/`Edit` in the implementer's worktree), and another repository is writable only under a path one of the worker's briefs lists in its `## Environment` section (`- Outside path:`, written by `finalize-brief.py --outside`). Paths outside any git repository are free; the worker's own main checkout stays denied even when listed. A worker without a worktree whose directory is outside git has no checkout to compare with, so its writes are not checked ("A worker without a worktree" below).
- **A Bash command that changed another worktree** is caught after it ran (PostToolUse / PostToolUseFailure): when the command names a path in that worktree and something there changed while it ran, the subagent or worker is told to stop and hand it back, with the owner named. Reading another worktree is fine.
- **After the main session starts a subagent** (PostToolUse), one line of context tells it to handle a returned `HERDR-HANDOFF` block by its `owner:` line.

Every handoff carries `owner:`, and step 0 ("Receiving a handoff") routes by it. The hooks decide from tool calls and their effects, never from prompt wording; the one exception is whether a prompt starts with `/<skill>` for a skill in `dispatchSkills`. Outside herdr a shell guard returns before python starts; inside herdr, the hooks that fire on every edit and Bash command return before any work for the main session itself, and the one that fires on every prompt returns unless the prompt starts with `/`.

Plugin installs ship it in the plugin's `hooks/hooks.json`, active by default. Other installs leave it unregistered until the user asks for it, because registering it edits `~/.claude/settings.json`; `scripts/hooks/manage.py on` registers it there. Those registered entries are a copy, so after updating a non-plugin install run `on` again to pick up changed hook events. When the user asks to turn the hook on or off, remove it, or check it ("turn off the herdr hooks", or the same in the user's language), run:

```bash
python3 "<skill directory>/scripts/hooks/manage.py" <on|off|remove|status> --skill-dir "<skill directory>"
```

Before `on` or `remove` on a non-plugin install, tell the user it edits `~/.claude/settings.json` (a backup is written first). For plugin installs, `remove` can only silence the hook; removing it entirely means disabling the plugin. Installing the hooks was the user's decision: inside herdr, work handed to another agent runs as a visible worker. So when a hook routes something here or to `references/dispatch.md`, carry on with it; do not ask whether to bypass it, and do not suggest `! <command>` or turning the hooks off. A worktree for this session is `EnterWorktree`, which the hooks already show in the sidebar. Talk about turning the hooks off only when the user asks about the hooks themselves. When a subagent reports that it was blocked or returns a `HERDR-HANDOFF` block, take it over with this skill (step 0, "Receiving a handoff").

## 0. Preconditions

```bash
test "${HERDR_ENV:-}" = 1 && ROOT="$(git -C "<target path>" rev-parse --show-toplevel)" && echo "$ROOT"
```

On failure, say that this is not inside herdr or not a git repository, and stop. Read the config (Configuration above: a missing file means the first-run notice, an invalid one means stop).

**Decide the target repository (`ROOT`) once, here.** Unless the user names a repository, `<target path>` is this session's working directory. From then on, run every git command as `git -C "$ROOT"` instead of relying on the current directory: a `cd` or a cwd reset in between could otherwise create worktrees from the wrong repository. Shell variables do not survive between Bash calls, so remember `ROOT` and each task's `BASE`, `FROM_BRANCH`, `SINCE`, `WT`, `W`, `PLACEMENT`, `P` and `BRIEF`, and put the values directly into later commands.

**Check for uncommitted changes.** Worktrees are created from the base commit, so uncommitted files do not exist in a worker's worktree. If a task targets such a file, the worker cannot find its work or works from the wrong baseline.

```bash
git -C "$ROOT" status --porcelain --untracked-files=all
git -C "$ROOT" cat-file -e "HEAD:<path the task touches>" 2>/dev/null || echo "not in HEAD"
```

If a path the task touches is missing from HEAD or modified (` M`, `??`), start from `HEAD` anyway. Say in the brief that this path has changes in the source checkout the worker cannot see, so the worker raises it in its own pane if it needs them, and put it in the report (step 4): to include them, the user commits and you deliver a follow-up (`references/deliver.md`). The orchestrator never commits or stashes on the user's behalf. Changes unrelated to the tasks need no mention.

**Offer to clean up finished workers.** Read `references/cleanup.md` and run its scan. If there are candidates, offer them in the report after the new workers start; cleaning up removes worktrees, so never do it without the user's go-ahead.

**Receiving a handoff.** A subagent stopped by a hook ends its reply with a block like this, and a worker puts one in its `## Result`:

    HERDR-HANDOFF
    To the main session: …
    name: <suggested worker name>
    repo: <absolute path of the target repository>
    owner: <worker name | main-checkout | none>
    goal: <one line>
    branch: <suggested branch, or ->
    steps:
    - <step>
    done: <what was already done, or nothing>

Route each block by its `owner:` line. Handed-off work starts like any other task of this run, without a question first.

- **`owner: <worker name>`** — the work belongs in that worker's worktree. Do not start a new worker for it. Follow `references/deliver.md`: it hands the block to that worker, waiting if it is busy and resuming it first if it was cleaned up or its session ended.
- **`owner: main-checkout`** — something changed (or was about to change) in the user's own checkout. Tell the user plainly what and where (`done:` and `steps:`) in the report, after any workers of this run have started, and ask what they want. Do not apply, revert, commit or move it yourself, and do not start a worker for it on your own: the user's checkout is theirs to decide about. Continuing the work in a worker is a fine choice to offer, as long as the user picks it; it needs the change committed first, because a worker starts from `HEAD` and would not see an uncommitted change.
- **`owner: none`** (or no `owner:` line) — a new task for this run: `repo` is its `<target path>` for `ROOT`, `name` and `branch` are suggestions that the repository's conventions (below) override, and `goal` and `steps` go into the brief.

If `done:` lists changes already made somewhere, they are uncommitted changes there: in the source checkout, handle them with the uncommitted-changes check above; in a worker's worktree, mention them when you deliver.

**Do not ask before starting.** By the time this skill runs, the user has already chosen to run the work as visible workers: they asked for it, or they installed the hooks that route it here. A question at this point cuts the flow for something the user can watch and change in the sidebar a moment later. So decide every task yourself, start the workers, and put whatever the user should know or decide into the report after they start (step 4). For each task decide:

- Name: `[a-z][a-z0-9_-]{0,31}`, unique. Used as the worker name and as the label of its workspace or tab in the sidebar (e.g. `proj-101`)
- Branch: follow the repository's branch convention (e.g. `feature/PROJ-101`)
- Base: defaults to `ROOT`'s current `HEAD`
- Worktree path: follow the repository's convention (below)
- Brief: pick a template and fill it with the goal, references, steps and rules taken from the user's request (step 2). The worker must be able to finish from the brief alone

**The repository's conventions come first; herdr only builds what they describe.** Where worktrees live, how branches are named and what they are based on belong to the repository, not to the development tool. Look for the repository's own answer before falling back to any default:

- Where worktrees go: a location stated in the repository's docs (`CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, README), a worktree directory already listed in `.gitignore` (e.g. `.worktrees/`), or where existing worktrees already live (`git -C "$ROOT" worktree list`).
- How branches are named: the same docs, and the pattern of existing branches (`git -C "$ROOT" branch -a`).

If the user named a path, use it. If the repository has a worktree convention, pass the resulting path to `place.py` with `--path` (step 1). Only when the repository shows no worktree convention at all, leave `--path` out: the worktree then goes to herdr's default path (`~/.herdr/worktrees/<repo>/<branch>`), whether herdr or `place.py` creates it. If the convention puts worktrees inside the repository but that directory is not in `.gitignore`, point it out in the report rather than editing `.gitignore` yourself.

More tasks means more concurrent claude sessions, which hit usage limits sooner. With five or more, say so in the report.

## 1. Create the worktree in its place

```bash
BASE="$(git -C "$ROOT" rev-parse HEAD)"
FROM_BRANCH="$(git -C "$ROOT" symbolic-ref --short -q HEAD || echo "$BASE")"   # cleanup checks whether the work was merged back here
PATH_ARG=(--path "<absolute path from the repository's convention>")   # relative conventions resolve against ROOT; PATH_ARG=() when there is none
OUT="$(python3 "<skill directory>/scripts/place.py" worktree --root "$ROOT" --name <name> --branch <branch> --base "$BASE" "${PATH_ARG[@]}")"
WT="$(printf '%s' "$OUT" | jq -r .worktree)"
W="$(printf '%s' "$OUT" | jq -r .workspace)"
PLACEMENT="$(printf '%s' "$OUT" | jq -r .placement)"
SINCE="$(printf '%s' "$OUT" | jq -r .since)"   # herdr plugins that react to this worktree start after it (step 3)
```

`place.py` decides where the worker goes, by one rule it shares with the hooks (`scripts/hooks/spaces.py`), so that every worker lands under its repository's space:

- **Under this session's space**, when that space is bound to `ROOT`'s repository: herdr opens the worktree as a workspace under it (`placement: workspace`).
- **Under the space herdr already shows for the repository**, when this session's space belongs to something else (for example, this session runs in a tab of another repository's space with its cwd in `ROOT`): the same, under that space.
- **As a tab in this session's space**, when herdr shows no space for the repository. herdr would otherwise make a new top-level space for it. Instead `place.py` creates the worktree with git, at the convention's path or herdr's default path (`~/.herdr/worktrees/<repo>/<branch>`), and the worker gets a tab here (`placement: tab`; `W` is this session's space). herdr's sidebar does not list that worktree as a workspace. Do not open it from herdr's worktree view while the worker runs there, or herdr makes a workspace for the same checkout.

- Always take `WT`, `W` and `PLACEMENT` from the output, whichever path was used. herdr and git both create missing parent directories for `--path`, inside or outside the repository.
- `SINCE` is taken just before the worktree is made. herdr plugins may now fill a new workspace with their own tabs and start programs in them, the root pane included; step 3 waits for them and gives the worker a tab of its own. A tab placement fires no plugin.
- If the branch already exists, the path is occupied or herdr or git fails, `place.py` creates nothing, prints the reason and exits 1. Stop and report.
- Add `--trust-repository` to `place.py` only when herdr asks for Git trust and the user has checked the repository. Never use it as a retry to get past a failure.

## 2. Write the brief

Instructions go to the worker as a file. The two alternatives each have a problem:

- `herdr agent prompt` with multi-line text arrives as pasted content: the worker receives the instructions wrapped in `<pasted_content>`, may treat them as not coming from the user, and in testing sometimes refused them. A single line arrives as a plain user message (tested, 6 of 6). That is why later instructions go as a file plus one line pointing to it (`references/deliver.md`).
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
3. Finalize with `python3 "<skill directory>/scripts/finalize-brief.py" "$BRIEF"`. It strips guidance comments, catches leftover placeholders, `[NEEDS CLARIFICATION` markers and empty sections, and appends the closing paragraph. When the task writes in another repository, add `--outside <absolute path> "<why>"` for each such path (`references/brief-filling.md` section 4): without it, the hooks stop that write. On failure, fix the reported lines and run it again.

The skill does not prescribe tools or procedures. If the user says to read an issue tracker, that becomes a step; if they say to run a particular review before committing, that becomes a step too. Keep briefs outside the worktree, or the worker may commit them.

## 3. Start claude

```bash
PANE="$(python3 "<skill directory>/scripts/worker-pane.py" --workspace "$W" --worktree "$WT" --name <name> --since "$SINCE")"
P="$(printf '%s' "$PANE" | jq -r .pane)"
herdr pane run "$P" "cat $(printf '%q' "$BRIEF")"
herdr pane wait-output "$P" --match "Do not push or open a pull request." --source recent-unwrapped --timeout 15000
ARGS=(); while IFS= read -r a; do ARGS+=("$a"); done < <(jq -r '(.workerArgs // [])[]' "$CONFIG")
SUMMARY="$(cat <<'EOF'
<one-line task summary>
EOF
)"
LINE="$(printf '[%s] %s. Read the brief at %s and follow it.' "<name>" "$(printf '%s' "$SUMMARY" | tr '\n\t' '  ')" "$BRIEF")"
herdr agent start <name> --kind claude --pane "$P" --timeout 20000 -- "${ARGS[@]}" --add-dir "$BRIEFS" -- "$LINE"
```

- **Why a tab of its own**: herdr plugins react to a new worktree and may lay out their own tabs and start programs in them, the root pane included (a layout that starts claude there, for example). Whether a pane is free cannot be told from a moment's look: a plugin's command can still be waiting in the shell's input. So the worker never types into those panes. `worker-pane.py` waits until the plugin handlers for this worktree have finished (`herdr plugin log list`; a tab created earlier makes some plugins skip their layout), creates a tab labelled `<name>` with `HERDR_PW_WORKER=<name>` in its environment, and waits until its shell is at the prompt. Leave the plugins' tabs as they are, even an idle claude one of them started; the report says which tab the worker is in. In a tab placement, `W` is this session's space, so that tab sits next to this session's own.
- **`worker-pane.py` output**: `settled: false` means a plugin was still running after 15 seconds (`still_running`), or the plugin log could not be read (`log_error`): carry on and mention it in the report. `shell_ready: false` means the new tab's shell did not reach its prompt: look at it with `herdr pane read "$P" --source visible --lines 20`, report what it shows, and stop. A non-zero exit means the tab could not be created: report herdr's error and stop.
- **Why `cat` the brief first**: so the user sees the task as soon as they open the worker's tab. Asking the worker to "echo the full brief in your reply" is unreliable; workers often summarize or skip it. So the orchestrator prints it in the tab's shell before claude starts, and it stays just above claude's start screen. `wait-output` waits until the output is done and the shell prompt is back before `agent start`; it matches the brief's last line (the closing paragraph). If `wait-output` times out, run `herdr pane read "$P" --source recent-unwrapped --lines 5`: if the brief's last line is there, the shell is just slow to report it, so carry on; if it is not, report what the pane shows and stop.
- **One-line summary**: it stays at the top of the screen as the first user message. Take it through a `<<'EOF'` heredoc: written straight inside double quotes, `` `code` `` (common in ticket titles) would be run by bash as a command and `$VAR` replaced with its value. herdr rejects newlines and tabs, so `tr` turns them into spaces.
- **`--add-dir "$BRIEFS"`**: the brief lives outside the worktree. This lets the worker read it whatever its permission settings.
- **The final `--`**: `--add-dir` takes multiple values. Without the `--` right after it, the instruction line is swallowed as another path and the worker starts with no instructions at all.
- **`HERDR_PW_WORKER=<name>`**: marks the worker. `herdr agent start` has no environment option, but it starts claude from this tab's shell, and herdr put the variable into that shell's environment (`tab create --env`), so claude, its subagents and its hooks inherit it. The hooks and step 0 use it to stop a worker from starting workers. It stays set in that tab, so a claude the user later starts there by hand is treated as that worker too, which is right for that worktree.

Workers start working immediately, so doing this step task by task still runs them all concurrently. Handle the result like this, then record the worker (below):

- **`idle` or `done`**: the first turn finished within 20 seconds. A short task may already be done; check in step 4.
- **`timeout`**: usually fine. `agent start` reports success only once the worker's turn has finished (`idle` or `done`), but the worker starts working at once and stays `working` for a long time. herdr then does not assign the worker name, so check the pane status and assign it yourself.

  ```bash
  S="$(herdr pane get "$P" | jq -r '.result.pane.agent_status // empty')"
  ```

  - `working`, `idle`, `done`: `herdr agent rename "$P" <name>`
  - `blocked`: assign the name, then handle the dialog as below
  - empty (claude not detected): look at the screen with `herdr pane read "$P" --source visible --lines 40`, report to the user, and stop
- **`agent_pane_busy`**: herdr found something besides the shell in the foreground, usually a prompt hook (mise, direnv, …) that runs again after `cat`. Wait a second and run the same `agent start` again, up to three times. If it persists, read the pane with `herdr pane read "$P" --source visible --lines 20`, report what it shows, and stop.
- **`agent_not_ready` or `blocked`**: a dialog is open on the worker's screen. Check it with `herdr agent read <name> --source visible --lines 40` and **never answer it yourself.** Tell the user what the screen shows and let them handle it in the worker's tab, from the sidebar. Once the dialog closes, confirm the worker picks up its positional instructions with `herdr agent wait <name> --until working --until idle --until done --timeout 120000` (herdr reports a finished turn as either `idle` or `done`) and `agent read`.
  - **Folder trust dialog** ("Is this a project you trust?"): Claude Code does not yet trust the source repository. It does not appear for worktrees of trusted repositories, and `--dangerously-skip-permissions` does not skip it
  - **Permission mode warning**: shown once to users running `--dangerously-skip-permissions` for the first time

Once the worker is running and named, record it. This stores the agent and the session reference herdr reports for the pane, which is what lets the user resume it after cleanup:

```bash
python3 "<skill directory>/scripts/runs.py" add --name <name> --root "$ROOT" --branch <branch> --base "$BASE" --from-branch "$FROM_BRANCH" --worktree "$WT" --workspace "$W" --pane "$P" --placement "$PLACEMENT" --brief "$BRIEF"
```

If `session_id` in the output is `null` (not reported yet), that is fine: cleanup re-reads it from the pane before removing anything. If `add` fails because an open run with the same name exists, a previous worker still holds that name: handle it with the cleanup scan (`references/cleanup.md`) or pick another name.

## 4. Wait and watch

Once all workers are started, report in one message, then wait on each. The report is where the user checks your decisions while the workers already run, so it must stand on its own:

- First line, the template: `Template: default (say "change the brief template" to customize)` for the default, otherwise `Template: <path>`. This line is how the user learns the template can be changed.
- The target repository (`ROOT`) and, per task: where it landed in the sidebar (the `<name>` workspace and which space it is under, or a tab in this session's space because herdr shows no space for that repository: step 1's `why`), the `<name>` tab the worker runs in (name the plugins that laid out the workspace, if any, and one still running), branch, base, worktree path (with the convention it came from, or "herdr default"), worker arguments, the brief's path and its steps section, so the user can see that every step they asked for made it in.
- Everything that would once have been a question: assumptions written into a brief, uncommitted changes a worker cannot see, a worktree directory missing from `.gitignore`, five or more workers, cleanup candidates, a `main-checkout` handoff.
- How to change course: tell you, and you deliver it to the running worker (`references/deliver.md`); or step into its tab directly.

```bash
herdr agent wait <name> --timeout 1800000
```

- `idle` / `done`: finished → step 5. But if the screen has no `## Result` and shows background work still running (e.g. `1 shell still running`), it is not done yet. Wait again.
- `blocked`: the worker is waiting for an approval or an answer. **Never approve on its behalf.** Check what it is asking with `agent read` and tell the user "`<name>` is waiting for approval of …" in its tab. Let the user answer.
- `timeout`: report progress from `agent read` and ask the user whether to keep waiting.

## 5. Collect results

```bash
herdr agent read <name> --source recent-unwrapped --lines 200
git -C "$WT" log --oneline "$BASE"..HEAD
git -C "$WT" diff --stat "$BASE"
```

Report a table per task: `name | branch | commits | change summary | tests | open issues`. If `## Result` is cut off on screen, raise `--lines`. If it still does not show, ask the worker to write its result to a temp file and reply with only the path, then read that file.

If a `## Result` contains `HERDR-HANDOFF` blocks, route them exactly as in step 0, "Receiving a handoff", asking the user once for all of them.

## 6. Clean up and resume

The default is to **leave everything in place**: the user decides on push, PR and merge after reviewing each worker's worktree.

- **Cleaning up** finished workers — offered in the report of the next run, or when the user asks: follow `references/cleanup.md`. It only removes workers that are recorded, not `working` or `blocked`, clean, and whose work is merged, pushed or empty, always after confirmation, and reports how to resume each one.
- **Resuming** a worker by name ("resume proj-101"): follow `references/resume.md`. It recreates the worktree at the recorded path, works out the agent's native resume option from the recorded clues (the same session reference herdr uses to restore agents), and checks that the conversation came back.

Cleanup keeps branches. Delete a branch only when the user asks, after merging.

## A worker without a worktree

Coding work in a repository always gets a worktree (steps 1–3). Some work still has to be visible in the sidebar but must not, or need not, have a worktree: the user or the repository's rules forbid a worktree or branch for it, or it changes no repository at all (an evaluation, or a research or review session that writes its findings to a work folder). Start it as a worker without a worktree, working in a directory `DIR` that is outside git or ignored by it. It changes no file git tracks and never commits.

```bash
PLACE="$(python3 "<skill directory>/scripts/place.py" where --dir "<DIR>")"
SPACE="$(printf '%s' "$PLACE" | jq -r .space)"
SINCE="$(python3 -c 'import time; print(int(time.time() * 1000))')"
PANE="$(python3 "<skill directory>/scripts/worker-pane.py" --workspace "$SPACE" --worktree "<DIR>" --name <name> --since "$SINCE")"
P="$(printf '%s' "$PANE" | jq -r .pane)"
```

- `place.py where` applies step 1's rule to the repository `DIR` is in: the tab opens in that repository's space when herdr shows one (this session's or another), else in this session's space. `DIR` outside git means this session's space. No workspace is made.
- `worker-pane.py` gives it a tab of its own with `HERDR_PW_WORKER=<name>`, so the hooks treat it as a worker: it gets the worker role, may use subagents of its own, and cannot create worktrees or start workers. Never start such a session with a bare `herdr tab create`: without that variable it is taken for an orchestrator.
- The brief: step 2, without the template's commit or branch steps, finalized with `--workdir "<DIR>"` in place of `--worktree` and `--branch` (`references/brief-filling.md` section 4), so its closing paragraph says not to commit. Then step 3 from `cat` on, without `runs.py add`.
- The hooks check a worker's writes against its home, the checkout its directory is in. When `DIR` is outside git there is no home to compare with, so nothing stops its writes (or its subagents') anywhere: its brief must say where it writes. When `DIR` is a git-ignored folder in a checkout, the hooks treat that checkout as its home.
- Its name must differ from every recorded or running worker's: the hooks read a worker's outside paths from its briefs by name.
- It is not recorded in `runs.json`: it has no worktree to clean up, and this skill cannot resume it once its tab is gone. Follow it by name (steps 4 and 5). Give it more work with `references/deliver.md` steps 2, 4 and 5, finalizing the follow-up with `--workdir` too. When the user asks to clean it up, close its tab: `herdr tab close "$(herdr agent get <name> | jq -r .result.agent.tab_id)"`.

## Never

- Close panes, tabs or workspaces this skill did not create. Never use `workspace close --group`: it also closes the source workspace
- Close the space a tab worker runs in: cleanup closes only the worker's own tab
- Let herdr make a new top-level space for a worker by handing it the repository with `--cwd`: `place.py` places every worker
- `herdr server stop`, or killing herdr processes
- Answer a worker's approval or confirmation dialog
- Substitute an `Agent` subagent for a worker
- Type into a pane this skill did not create, the workspace's root pane included: a plugin's or the user's program may be running there or about to start
- Send the first instructions with `agent prompt`. Multi-line text arrives as pasted content and the worker may refuse it; a single line arrives as a plain user message (tested). So the first instructions are the brief file plus `agent start`'s one-line argument (step 3), and later instructions go as a file plus one line pointing to it (`references/deliver.md`)
- Have workers push or open pull requests
- Start workers or create worktrees from inside a worker (`HERDR_PW_WORKER` set)
- Ask the user anything before the workers start; it goes in the report after they start (step 4)
- Suggest `!` or turning the hooks off to get around them, or ask whether to: installing them was the user's choice
- Start a new worker for work whose handoff names an existing worker as `owner:`; deliver it to that worker
