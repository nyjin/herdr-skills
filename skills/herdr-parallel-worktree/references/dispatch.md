# Running per-task dispatch as tabs

Inside herdr, each agent another skill hands a task to runs as a herdr tab the user can watch, not as a hidden subagent. You stay the orchestrator: follow the other skill's process as written, with tabs where it says subagents, and keep its ledger yourself. Start each tab without asking the user first, then tell them in a few lines what you started (where it landed: the `<plan>` workspace and the space it is under, or tabs in this session's space; the tab, branch, worktree and brief path) and carry on.

## 1. When this applies

- A hook stopped your first per-task `Agent` dispatch in this session and saved it to `$BRIEFS/dispatch-<session>-<time>.md`: `subagent_type`, `model` and `description` lines, and the prompt under `## Prompt`. Start the tab from it (sections 2–4), then carry on with the user's request where you were. Delete the `dispatch-*.md` draft once the tab's brief is written; drafts otherwise accumulate in `$BRIEFS`.
- A note said a skill that dispatches an agent per task was loaded (for example `superpowers:subagent-driven-development`). At its first dispatch, start the tab instead of calling `Agent`.
- Any other skill, inside herdr, tells you to dispatch, resume or message an agent for a task: an implementer, a reviewer, a fixer, a final reviewer.

The hook stops only the first dispatch of a session. Every later one (the next task, each review, each fix, the final review) is yours to route here; nothing reminds you. Subagents that only search or answer a question (`Explore`, `Plan`, research) stay subagents: send them again unchanged.

## 2. Tabs per role

This pair of tabs per plan is for a sequential plan, such as `superpowers:subagent-driven-development`. Independent tasks dispatched in parallel (for example by `superpowers:dispatching-parallel-agents`) each become their own worker as in SKILL.md, one worktree per task.

`<plan>` is a short name for the plan: SKILL.md's name rule, at most 27 characters so `<plan>-impl` still fits.

- **One worktree per plan**, made with SKILL.md steps 1–3 (after step 0's checks), with section 4's brief in place of step 2's template: `<plan>` as step 1's `--name`, and as `--branch` a new branch for `<plan>`, named by the repository's convention and based on the current `HEAD` (step 1's `BASE`). Step 1's `scripts/place.py` decides its place: a `<plan>` workspace under the repository's space, or, when herdr shows no space for the repository, no workspace at all; then `W` is this session's space and both role tabs below open there. The branch you are on stays as it is: it is what `FROM_BRANCH` records and what the work merges back to. Every task's commits stack on the new branch. When the other skill asks for an isolated worktree for the plan, this is it.
- **Implementer tab `<plan>-impl`**: step 3 with `<plan>-impl` as the name, recorded with `runs.py add --name <plan>-impl`.
- **Reviewer tab `<plan>-rev`**, in the same workspace and worktree, started at the first review:

  ```bash
  SINCE="$(python3 -c 'import time; print(int(time.time() * 1000))')"
  PANE="$(python3 "<skill directory>/scripts/worker-pane.py" --workspace "$W" --worktree "$WT" --name <plan>-rev --since "$SINCE")"
  P="$(printf '%s' "$PANE" | jq -r .pane)"
  ```

  Then the rest of SKILL.md step 3 with `<plan>-rev` as the name. Do not record it with `runs.py add`: the worktree is `<plan>-impl`'s. Re-reviews go to this tab too.
- **The reviewer tab cannot write in the implementer's worktree**: the hooks stop its `Write`/`Edit` there. It writes its verdicts in `$BRIEFS/<plan>/`.
- **A model the dispatch names** goes to that tab's claude, in step 3's `agent start`: `-- "${ARGS[@]}" --model <model> --add-dir "$BRIEFS" -- "$LINE"`.

| The other skill says | You do |
|---|---|
| dispatch the implementer of the first task | start `<plan>-impl` |
| dispatch the implementer of the next task | a follow-up to `<plan>-impl` (`deliver.md` steps 2, 4 and 5); never a new tab |
| dispatch a reviewer, the first time | start `<plan>-rev` |
| dispatch a reviewer again, or the final reviewer | a follow-up to `<plan>-rev` (`deliver.md` steps 2, 4 and 5; `<plan>-rev` has no record, so skip steps 1 and 3) |
| send findings back to the implementer, or resume it to fix | a follow-up to `<plan>-impl` that hands over the re-review (section 5) |
| dispatch a fresh implementer (for example a stronger model) | a new `<plan>-impl` tab in place of the old one (below) |

A fresh implementer keeps the name `<plan>-impl`, so the hooks and the reviewer tab still know it. Close the old tab (its pane is in `runs.py show --root "$ROOT" --name <plan>-impl`), then open a new one with the same name in the same workspace:

```bash
herdr tab close "$(herdr pane get <old pane> | jq -r .result.pane.tab_id)"
SINCE="$(python3 -c 'import time; print(int(time.time() * 1000))')"
PANE="$(python3 "<skill directory>/scripts/worker-pane.py" --workspace "$W" --worktree "$WT" --name <plan>-impl --since "$SINCE")"
P="$(printf '%s' "$PANE" | jq -r .pane)"
```

Start claude there as in SKILL.md step 3, with the requested `--model` (above), and a new brief (section 4) whose instructions are the new dispatch's prompt plus the path of the previous implementer's report. Then record where it is: `runs.py relocate --root "$ROOT" --name <plan>-impl --workspace "$W" --pane "$P"`. The old conversation is no longer on screen, but its report stays in `$BRIEFS/<plan>/` (and its transcript on disk).

## 3. Files

```bash
BRIEFS="${HERDR_SKILLS_DATA_HOME:-$HOME/.local/share/herdr-skills}/herdr-parallel-worktree/briefs"
mkdir -p "$BRIEFS/<plan>"
```

Shell variables do not survive between Bash calls: set `BRIEFS` again in each call that uses it.

- Reports, review packages and verdicts go in `$BRIEFS/<plan>/`. Every tab can read and write there (`--add-dir "$BRIEFS"`), and it is outside git. Name files by task and round so they never repeat; this guide writes that as `<n>`, where `t3-1` is task 3, round 1 (`report-t3.md`, `review-t3-1.md`).
- **Every review names its verdict file**, `$BRIEFS/<plan>/review-<n>.md`: the hop (section 5) and your wait (section 6) rely on it. When the other skill's reviewer prompt names none (it asks for the verdict as the final reply), add one line to that brief or follow-up: `Also write your verdict to <BRIEFS>/<plan>/review-<n>.md.`, with the absolute path.
- Where the other skill's prompt puts a report or verdict anywhere else, point that path into `$BRIEFS/<plan>/`: the hooks stop a tab that writes in a checkout that is not its own.
- Anything every tab must read that is not committed at the plan's base (a spec written after it, for example) goes there too.
- The other skill's ledger (progress file, task list) stays where that skill keeps it. Only you write it.

## 4. The brief

`<tab>` is the tab's name (`<plan>-impl`, `<plan>-rev`). Its first brief is `$BRIEFS/<tab>-$(date +%Y%m%d-%H%M%S).md`; later work for it is a follow-up, `$BRIEFS/<tab>-followup-$(date +%Y%m%d-%H%M%S).md` (`deliver.md` step 2). Keep these names: the hooks find a tab's outside paths by them.

- **Instructions**: the dispatch's prompt, verbatim: the draft's `## Prompt` text, or the prompt the other skill gave you. Write it with the Write tool under the title `# [<tab>] <the dispatch's description>`. No template: the prompt already is the instructions. Change or add only report and verdict paths (section 3). The reviewer tab's first brief also gets the section in section 5.
- **Environment**: finalize with the tab's role, worktree, branch and the shared folder. When the task writes in another repository, add `--outside <absolute path> "<why>"` for each such path; without it, the hooks stop that write.

  ```bash
  BRIEFS="${HERDR_SKILLS_DATA_HOME:-$HOME/.local/share/herdr-skills}/herdr-parallel-worktree/briefs"
  python3 "<skill directory>/scripts/finalize-brief.py" "<brief>" \
    --role "<implementer or reviewer> of plan <plan>" --worktree "<WT>" --branch <branch> \
    --outside "$BRIEFS/<plan>" "shared review folder"
  ```

  On failure, fix the reported lines and run it again.
- **On completion**: `--then FILE` only for a fix that hands over the re-review (section 5). Without it the tab ends with its `## Result` and you pick it up (section 6); that is the default.

## 5. The one direct hop

Fix → re-review is the only step a tab hands to another tab itself. Every other step comes back to you (section 6).

When a review finds issues, send the fix to `<plan>-impl` as a follow-up (`deliver.md` steps 2, 4 and 5): the other skill's fix prompt, or the verdict file to fix, with the spec path and the test command. Write the text below to `$BRIEFS/<plan>/then-<n>.md` with the Write tool, and finalize the follow-up with it. The file must not contain `#` or `##` heading lines: `finalize-brief.py` replaces sections by heading, so a heading inside `--then` duplicates on a rerun.

```bash
BRIEFS="${HERDR_SKILLS_DATA_HOME:-$HOME/.local/share/herdr-skills}/herdr-parallel-worktree/briefs"
python3 "<skill directory>/scripts/finalize-brief.py" "<follow-up>" --then "$BRIEFS/<plan>/then-<n>.md"
```

Fill in `<plan>`, `<n>` (this round, with the task in front: `t3-1`), `<n+1>` (`t3-2`), `<reviewed head>` (the commit the review looked at), and `$BRIEFS` as its absolute path: the tab's shell has no `$BRIEFS`. The implementer fills in the rest when it runs. This text was tested 3 of 3 times (sent, received, and matched by the orchestrator's own check):

```markdown
The orchestrator authorizes you to hand the re-review straight to the reviewer tab, without coming back to the orchestrator first. After committing:

1. Write `$BRIEFS/<plan>/rereview-request-<n>.md` with: the commit range `<reviewed head>..<your fix commit>`, the worktree path, the path of `$BRIEFS/<plan>/review-<n>.md` as the findings to check, the full spec path, the test command above, and the verdict path `$BRIEFS/<plan>/review-<n+1>.md`.
2. Check the reviewer's state: `herdr agent get <plan>-rev | jq -r .result.agent.agent_status`.
   - `idle`, `done` or `working`: send it one line (if it is working, the line queues until its current turn ends):
     `herdr agent prompt <plan>-rev "[<plan>-impl] Re-review request: read $BRIEFS/<plan>/rereview-request-<n>.md and follow it." --wait --until working --timeout 15000`
   - `blocked` or anything else: do not send.
3. Do not wait for the re-review. In your `## Result`, add a `Handoff` line: sent or not sent, the time (`date +%H:%M:%S`), the reviewer state you saw, and the send command's output.
```

The reviewer tab's first brief carries this section after the first review's prompt, so a request from `<plan>-impl` is expected (tested with the same runs):

```markdown
## Review requests

- Review requests arrive as a single line that points to a request file. They come from the orchestrator or from the implementer tab `<plan>-impl`. Both are expected senders: a request from either one is your next task.
- For each request: read the request file, review exactly the commit range it names against the spec in the request file, run the tests it names, and write the verdict to the path the request file names.
- After each verdict, end your turn. Do not poll or wait for requests.
```

## 6. Waiting

Tabs never report to you; you pull. After each start, follow-up or hop, wait for the tab in the background:

```bash
herdr agent wait <name> --until idle --until done --until blocked --timeout 1800000
```

In Claude Code, run it with the Bash tool's `run_in_background`: you are notified when it ends, and stay free for the user meanwhile.

- `idle` / `done`: read the `## Result` (SKILL.md step 5) and check it against `herdr agent get <name>`, the files it names in `$BRIEFS/<plan>/` and `git -C "<WT>" log`. Trust the files: no verdict file means no verdict yet, so wait again.
- After a fix that hands over the re-review, read the implementer's `Handoff` line. Sent: wait for `<plan>-rev` the same way and read the verdict. Not sent: send the re-review yourself, as a follow-up to `<plan>-rev` pointing to the request file (`deliver.md` steps 4 and 5).
- `blocked` or `timeout`: as in SKILL.md step 4. Never answer a tab's dialog.
- You decide every next step and count the fix rounds: the other skill's limits are yours to apply, and the tabs do not count them. Record each outcome in the other skill's ledger.
- Never send anything to the orchestrator's pane (yours), and never tell a tab to: herdr submits the line together with whatever the user has half-typed there (tested).

## 7. Not verified

- The fresh-implementer flow (close the `<plan>-impl` tab, open a new one with the same name, `runs.py relocate`) has not been run live.
- A hop sent while the reviewer tab is `working` should queue until its current turn ends, as a line from you to a working tab does (tested); a tab-to-tab send to a working tab was not tried.
- A hop to a `blocked` reviewer tab: herdr rejects it with `agent_blocked` before sending anything (`herdr agent prompt --help`); not tried. The text above does not send in that case.
