# glow-preview Design

> Renamed to `peek` on 2026-11-15 (`herdr-plugins/peek`). This record keeps the names it was written with.

## Purpose

When a markdown file comes up while using Claude Code in herdr, open it with the glow TUI in the pane directly to the right of that Claude pane. This lets the user read the specs, plans and docs that Claude wrote or read in rendered form, without leaving the terminal.

## Goals / Non-goals

- Goals
  - When Claude Reads, Writes, Edits or MultiEdits a `.md` file, the right-hand view switches to that file (automatic).
  - Clicking a `.md` path shown in the Claude pane opens that file in the right-hand view (secondary).
  - If glow is missing, install it and tell the user.
- Non-goals: editing markdown, keeping the scroll position, file types other than `.md`, Linux and Windows support.
- Anti-goals: silently opening the wrong file. Blocking or slowing Claude's work. Typing commands into the shell the user is using.

## Chosen approach (user choice: A)

The viewer pane watches a "current file" state file. When it changes, the viewer stops glow and starts it again on the new file. The hook and the link handler write the state file, and open a viewer pane if there is none.

Other approaches considered:
- B. Send commands to the shell with `herdr pane run`, as `review-on-focus` does: needs code to detect the process, wait for it to exit and defend against `kill -9`, and risks sending input to some other program.
- C. A dedicated Go viewer built on glamour: the smoothest, but it stops using glow and is a lot of work.

## Behavior

- There is one viewer per Claude pane. The viewer knows the id of the Claude pane that opened it (`GLOWP_SOURCE`) and watches `<state>/<source>.json`.
- The viewer pane is opened with `herdr plugin pane open --placement split --target-pane <source> --direction right --no-focus`. Focus stays on Claude.
- The viewer writes its own pane id to `<state>/<source>.viewer`. While that pane is alive, no new one is opened.

### Path resolution (on a link click)

The clicked string is judged after stripping `file://`, a trailing `:line[:col]`, and quotes, brackets and punctuation.

1. Absolute path or `~/`: open it right away if the file exists.
2. Any other path: collect candidates from the four sources below all at once. The order does not affect the result.
   - Working folder: join onto the `foreground_cwd` of the clicked pane (not `cwd`; in a session that moved into a worktree, `cwd` points at the old location).
   - scratchpad: join onto `/private/tmp/claude-<uid>/*/<session id>/scratchpad`. The session id is the pane's `agent_session.value`. A leading `scratchpad/` is dropped before joining.
   - Transcript: absolute paths found in `~/.claude/projects/*/<session id>.jsonl` whose tail matches.
   - git: files (tracked and untracked, ignored files excluded) of the repository that `foreground_cwd` belongs to whose tail matches.
   - A string that starts with `…/` is used only for tail matching.
3. Remove duplicates by real file (realpath).
   - If there is 1, open it.
   - If there are several, show a selection list in the viewer. The most recent one in the transcript comes first.
   - If there are 0, report "file not found" with a herdr notification.

Measured basis (2026-11-13, 22 open Claude panes, 169 `.md` paths): of the 70 that produced candidates, 56 were the same file whatever the lookup order. 14 had several candidates, and in 3 of those the working folder and the transcript pointed at different files. So we do not fix an order and take the first hit. When there are several candidates, the user chooses.

### Hook

Claude Code `PostToolUse`, matcher `Read|Write|Edit|MultiEdit`, `async: true`. If `tool_input.file_path` is a `.md` and `HERDR_PANE_ID` is set, open that path (always absolute). Any failure ends with exit code 0 so that Claude never sees it.

### glow

When the viewer starts and glow is missing, it announces the install with a herdr notification and runs `brew install glow` inside the viewer pane to show progress. If brew is missing, it prints the install instructions and waits.

## Constraints

- macOS, herdr ≥ 0.9.3 (`link_handlers`, `plugin pane open --env`), python3 standard library only.
- Install location: at first `~/.config/herdr-plugins/glow-preview` (`herdr plugin link`); now `herdr-plugins/glow-preview/` in this repository (`herdr plugin install nyjin/herdr-skills/herdr-plugins/glow-preview`). The hook is registered in `~/.claude/settings.json`, backed up before the change.

## Left to the implementer

- The glow TUI arguments, the viewer's screen text, the state file polling interval.
- The exact format of the link handler `pattern`. herdr has no documentation for it, so check it with the validation result of `plugin link` and with real clicks.

## Phase 2 extension (2026-11-13): source, raw view, link content

User decision: `.md` with glow, source code with bat, GitHub PRs with gh, Jira and Confluence with acli (MCP if that fails). Do not open a browser. Fetch the content with a CLI, convert it to markdown and read it in the same viewer. No button actions and no writing comments.

### View mode
- The viewer does not use the TUI (`glow -t`). The TUI ignores the `-w` value and cuts long Korean paragraphs at the pane width, so content disappears (measured: in a 170-column pane, the config at 80, `-w 0` and `-w 60` all cut). So it uses `glow -p -w <pane width-2>` (less). `glow.yml` also applies to the user's ordinary glow use, so we do not touch it.
- Source code is shown with `bat --paging=always`. A trailing `:line` on the clicked string jumps to that line and highlights it.
- `.md` (and documents fetched from links) can switch between rendered (glow) and raw (bat). There are two ways to switch.
  - Quit the pager with `q`, then press `s` in the menu.
  - Use the herdr action `glow preview: toggle rendered/source`. This action works even while the pager is up.
  - The switched state is kept in that viewer.
- Only `.md` is still opened automatically. Source code and links are opened only on click.

### Links
| Link | Fetch | Measured (all session links) |
|---|---|---|
| `https://*.atlassian.net/browse/KEY` | `acli jira workitem view KEY --json` (summary, status, assignee, body, comments) | 27 of 28 succeeded, average 9.9 s, max 242 s → timeout 30 s |
| `https://*.atlassian.net/wiki/.../pages/<id>` | `acli confluence page view --id <id> --body-format atlas_doc_format --json` | all 23 succeeded after authentication, average 1.7 s |
| `https://github.com/<o>/<r>/pull/<n>` | `gh pr view <n> -R <o>/<r>` + `gh api .../pulls/<n>/comments` | with `-R`, all 43 succeeded, average 0.9 s |

- Jira and Confluence bodies arrive in the same format (ADF), so one converter turns them into markdown. It handles every node and mark used in the 51 session links. For an unknown node it keeps only the child text.
- gh: a gh wrapper that picks the account per repository usually looks at `-R` or the origin of the current folder to pick the account, and does not look at the URL. So `pr view` gets `-R`. `gh api` does not accept `-R`, so on a 404 it retries with the account tokens listed in `gh auth status --json hosts`, one after another.
- On failure, build a guide for the cause as markdown and show it in the viewer.
  - CLI missing: the install command
  - Authentication error: `acli … auth login`, `gh auth login`
  - 404: an account or permission problem
  - Timeout
- If Jira or Confluence fails, pressing `m` on the guide screen fetches it through MCP (`claude -p`, Atlassian connector). Measured 3 min 35 s, about $0.016. It is slow and costs money, so it runs only when the user chooses it, and the guide screen shows these numbers alongside.
- Pressing `o` on a link screen opens it in the browser (`open`).
- Fetched documents are stored in `~/.cache/glow-preview/`. Reopen (`r`) and raw view use the stored file. A fresh fetch happens when the link is clicked again.

### Non-goals
Reproducing the web screen, writing comments, approving, changing status, opening source code automatically.

### Change (2026-11-13, after measurement)
- MCP: the first attempt failed with `Reached max turns (6)`. There were two causes. Loading the MCP tools (ToolSearch) took one turn, and the Jira response was 75,000 characters, saved to a file, and reading it in pieces with Bash used up the turns. So we made it request the compact view and only the needed fields, made it read the saved result with Read, and raised the turn limit to 12. After that, Jira took 13 s and Confluence 27 s.
- Link cache: clicking again shows the cache stored by URL hash right away (user request). The line under less shows the fetch time, and menu `f` fetches anew. Failed results are not cached. MCP results are stored in the same cache.

## Phase 3 change (2026-11-13): open on click only, tool order

User decisions:
- **Nothing opens unless clicked.** The Claude Code `PostToolUse` hook is removed. Because of this hook, even work notes that other sessions use (`/tmp/<agent-workdir>/…/handoff/*.md`, scratchpad) were opened in the viewer. `install.sh` backs up settings.json and removes the hook that an earlier version left behind. With this decision the "Goal: automatic" of the phase 1 design is cancelled.
- **Jira** is tried in the order acli → jira-cli (`jira issue view KEY --raw`) → Atlassian MCP, and **Confluence** in the order cme → Atlassian MCP. A tool that is not installed is skipped, and on failure it moves on to the next tool. If all fail, a table shows the result and the fix for each tool. MCP is now tried automatically, so the `m` key is removed.
- cme: success is judged by whether a result file was created (it ends with rc 0 even for a page that does not exist). Attachment download is turned off (`CME_EXPORT__ATTACHMENTS_EXPORT=disabled`). Relative links between exported files keep only their text. The timeout is 180 s. One long page took 64 s, and 63 s even with attachments off.
- Measured (session links): of 23 Confluence links, 22 went through cme, and 1 went over to MCP because cme exceeded the 60 s limit (121 s). After that we raised the limit to 180 s. All 5 Jira links used acli, average 1.1 s. jira-cli is not installed, so it was checked only with a fake CLI test.
- The viewer opens files and links through a single `load(item)`. This function checks the cache first, records the tool it used in `<hash>.md.tool`, and shows it on the line under less.

### Cleanup before release
- MCP tool names come from the claude.ai connector name. Both the default connector (`mcp__claude_ai_Atlassian__…`) and a connector that an organization registered under the name "Atlassian MCP" (`mcp__claude_ai_Atlassian_MCP__…`) are allowed.
