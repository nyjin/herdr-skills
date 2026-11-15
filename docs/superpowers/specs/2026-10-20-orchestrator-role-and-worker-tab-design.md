# Role injection and a worker-only tab — design record

- Date: 2026-10-20
- Version: 0.7.0
- Scope: `herdr-parallel-worktree` skill, hook (`route.py`), new script `worker-pane.py`

## 1. What the problem was

In two real sessions the skill did not fire.

| Case | What happened | Cause |
|---|---|---|
| Another skill (executor) said "launch a subagent per ticket, it must be interactive so a person can type" | The main session handed off to an Agent subagent and slipped out through the "if the harness cannot provide it" clause | The session did not know it was the orchestrator inside herdr. The skill description was tuned to "several … at the same time", and "Not for single edits" pushed a single ticket away |
| The main session ran `git worktree add -b feature/<KEY>` for one ticket | The hook redirected it to `EnterWorktree`. That created `.claude/worktrees/feature+<KEY>` and branch `worktree-feature+<KEY>`, which does not match the repository convention. herdr-plus launched a separate claude in that workspace, which stayed idle | The hook message wrongly said "the same git worktree", and sent ticket work toward the main session doing it directly |

In the same run the worker path could also break. The herdr-plus layout launches claude in the root pane, so the skill's `pane run "export …; cat brief"` is typed into that claude instead of a shell, and `agent start` gives `agent_pane_busy`.

## 2. Decisions

1. **Tell the session its role at session start (SessionStart, R9).** The main session gets "You are the orchestrator. Work you hand off is a worker, even a single ticket. 'Launch a subagent' from another skill also means a worker." A worker gets its name and its boundary. Describe the role rather than list purposes (user decision). Subagents, and sessions that start inside a linked worktree without `HERDR_PW_WORKER` (such as the claude a plugin layout launches in a worker's workspace), get nothing. Every session inside herdr pays one paragraph (about 100 tokens), and the hook costs about 37ms.
2. **Change the `git worktree add` block message into role sentences.** Ticket work goes to a worker. `EnterWorktree` only when the user asks to move this session itself. State the path and branch `EnterWorktree` actually creates.
3. **The skill description accepts a single task.** "a task, even a single ticket, … that the user can watch or step into". The exclusion narrows to "quick edits done in this session". The body states the hierarchy orchestrator → worker → subagent inside a worker, and the priority when it collides with another skill.
4. **A worker always starts in its own tab.** `worker-pane.py` (1) waits for the plugin handlers that reacted to this worktree to finish, (2) creates a tab with `HERDR_PW_WORKER` set as an environment variable, and (3) waits until that shell rests at the prompt. It does not type into the tab the plugin created or the root pane. New workers, resume, and follow-up delivery all use this path.
5. **Tell the sidebar label after `EnterWorktree`.** Also that the claude a plugin launched is a separate idle session.

## 3. Measurements

All done with this repository, on herdr 0.9.3, herdr-plus 0.1.24 (`_default.toml`: claude, git, shell tabs), with persiyanov.reviewr installed.

| # | What was checked | Result |
|---|---|---|
| M1 | The root pane right after creating the worktree | For 0 to 4 seconds the shell is in the foreground, and around 8 seconds it turns into claude. The handler finished within 1 second, but the command sat in the input queue during shell initialization. **A one-moment "the shell is empty" check is no criterion** |
| M2 | Creating a tab before the handler finishes | herdr-plus log: `already has 2 panes; skipping layout`. The layout is dropped |
| M3 | Completion signal | `herdr plugin log list` keeps each handler's `status` (`running` → `succeeded`) and time per event. There is no workspace id, so filter by start time (`SINCE`) |
| M4 | `tab create --env` | The new tab's shell and the claude in it receive `HERDR_PW_WORKER` (`PW=[probe]`, the worker wrote its name to env.txt) |
| M5 | The whole flow (skill steps 1 to 3 as written) | Tabs are `claude, git, shell, <name>`. The layout is intact, and the worker follows the brief in its own tab. It copied down the sentence received through SessionStart: "You are herdr worker `e2e-role`, …" |
| M6 | Shell-ready check | Even when the foreground group is a shell, if a prompt hook (`mise`) runs in the same group, `agent start` gives `agent_pane_busy`. The check changed to "only the shell is in the foreground, twice in a row", and for the hook that runs again after `cat`, `agent_pane_busy` is retried at 1 second intervals up to three times |
| M7 | Resume | Close the workspace (keep the worktree), `worktree open` → `worker-pane.py` → `claude --resume <id>` in a new tab. It came up with the same session id and remembered the value written to env.txt earlier. The plugin also reacted to `worktree.opened`, and the wait caught it |

### Behavior check (claude -p, sonnet, once each)

With two single-ticket requests (S7: "implement on its own branch and review in that session before the PR", S8: "launch a subagent per ticket, interactively"), we checked whether the skill is used.

| Condition | S7 | S8 |
|---|---|---|
| 0.6.0 skill, no hook | Does not use the skill, handles it in this session | Uses the skill |
| New skill description, no hook | Uses the skill | Uses the skill |
| New skill description + hook (including SessionStart), `live_skill.py` | Pass | Pass |

With one run each, the evidence is weak. The description change alone changed S7, and for role injection, M5 separately confirmed that the sentence actually enters the session.

## 4. Rejected options

| Option | Why rejected |
|---|---|
| A. Turn off the claude the layout launched and use that pane | It defeats the command the user put in the layout (this repository has `JAVA_HOME=…21`) |
| C. Use the claude the layout launched as the worker (instruct with `send-text`) | The instruction was received (measured), but the environment variable cannot be set, so worker detection would have to switch to cwd, `workerArgs` and `--add-dir` are lost, and what runs in that pane differs per plugin. We would end up branching on a specific command (claude) |
| Decide by whether the root pane is a shell prompt, then use it | M1: a plugin command may still be in the queue, so it is a race |
| Block by the worktree path inside the Agent call's prompt | It conflicts with the principle that the hook does not judge by prompt wording. Role injection handles it first |

## 5. What remains

- If the main session enters a linked worktree with `EnterWorktree` and then compacts, the cwd at that point is the linked worktree, so the role paragraph is not injected again. This is rare, so we accept it.

- If the layout launches claude, an idle claude stays in that tab. It is the user's layout, so we leave it alone and write the worker's tab name in the report.
- On an old herdr without `plugin log list`, we assume there is no handler to wait for and create the tab after `--quiet-ms` (2 seconds).
- A sentence another repository's skill (executor) wrote as "subagent" is fixed in that repository. This repository resolves the conflict with role injection and the priority sentence.
