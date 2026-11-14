# glow-preview

**English** | [한국어](README.ko.md)

A herdr plugin that shows a file or link from a Claude Code pane in a pane to its right, **when you click it**. Nothing opens without a click.

| You click | Fetched with (tried in order) | Shown with |
|---|---|---|
| a `.md` / `.markdown` path | the file itself | [glow](https://github.com/charmbracelet/glow) (rendered) ↔ [bat](https://github.com/sharkdp/bat) (source) |
| a source path (`.py` `.java` `.kt` `.ts` …); a trailing `:line` jumps to and highlights that line | the file itself | bat |
| Jira `…atlassian.net/browse/KEY` | [acli](https://developer.atlassian.com/cloud/acli/reference/commands/) → [jira-cli](https://github.com/ankitpokhrel/jira-cli) → Atlassian MCP | glow |
| Confluence `…atlassian.net/wiki/…` | [cme](https://github.com/Spenhouet/confluence-markdown-exporter) → Atlassian MCP | glow |
| GitHub PR `github.com/<o>/<r>/pull/<n>` | gh | glow |

- A tool that is not installed is skipped; one that fails hands over to the next.
- When none works, the viewer shows a table with each tool, what happened (not installed, login needed, not found or no access, timed out) and the command that fixes it.
- Atlassian MCP runs `claude -p` with Claude's Atlassian connector. It took 13 s for a Jira issue and 27 s for a Confluence page when measured, and every call costs Claude usage, so it is tried last.
- Fetched documents are cached by URL hash. Clicking the link again shows the cached copy at once. The bottom line of less shows the link, the tool used and when it was fetched; `f` in the menu fetches again.
- A shortened path (`docs/a.md`, `…/deep/a.md`, `a.md`) is looked up in four places at once: the pane's working folder (`foreground_cwd`), the session scratchpad, the session transcript and the git checkout.
  - One candidate opens directly.
  - Several show a numbered list, most recently used first.
  - None shows a herdr notification.
- Other web URLs are not intercepted; they open in the browser.
- There is one viewer per Claude pane, and it opens without taking focus. When glow or bat is missing, the viewer says so in a notification and installs it with `brew install`.

## Tools: install and log in

| Tool | Install | Log in |
|---|---|---|
| acli | `brew tap atlassian/homebrew-acli && brew install acli` | `acli jira auth login` |
| jira-cli | `brew install ankitpokhrel/jira-cli/jira-cli` | `jira init` (API token in `JIRA_API_TOKEN`) |
| cme | `uv tool install confluence-markdown-exporter` | `cme config` |
| gh | `brew install gh` | `gh auth login` |
| Atlassian MCP | Claude Code (`claude`) | connect the Atlassian connector on claude.ai |

PRs are fetched with `gh pr view <n> -R <o>/<r>`, so a gh wrapper that picks the account per repository sees the repository. `gh api`, used for inline review comments, takes no `-R`; on a 404 it is retried with the token of each account in `gh auth status`.

## Menu (`q` in less)

- `r` show again
- `s` rendered ↔ source (markdown)
- `f` fetch again (links)
- `o` open in the browser (links)
- `q` close the viewer

The herdr action **glow preview: 렌더링/원문 전환** also switches rendered ↔ source, from the viewer pane or its Claude pane, even while less is open. To bind it to a key, add this to `~/.config/herdr/config.toml` (the format passes `herdr config check`):

```toml
[[keys.command]]
key = "prefix+v"
type = "plugin_action"
command = "nyjin.glow-preview:toggle-view"
```

## Install / remove

```sh
herdr plugin install nyjin/herdr-skills/herdr-plugins/glow-preview   # install
herdr plugin uninstall nyjin.glow-preview                            # remove
```

From a checkout of this repository, `sh herdr-plugins/glow-preview/install.sh` links the plugin with `herdr plugin link` and removes the Claude Code hook that versions 0.1–0.2 registered, after backing up `~/.claude/settings.json`.

Requires macOS, herdr 0.9.3 or later and python3. The viewer's text is in Korean.

## Layout

- `scripts/glowp.py`: three entry points
  - `link`: the link handler
  - `toggle`: the switch action
  - `viewer`: the plugin pane; files and links both go through `load()` and are paged with less
- `scripts/resolve.py`: clicked path → candidate files
- `scripts/targets.py`: clicked text → link kind, or path (+ line)
- `scripts/fetch.py`: link → markdown, trying the tools in order and writing the guide when none works
- `scripts/adf.py`: Atlassian Document Format → markdown, used for acli and jira-cli output
- State (`~/.local/state/glow-preview/`):
  - `<claude-pane>.json`: what to show
  - `.viewer`: the viewer pane id
  - `.mode`: rendered or source
- Cache (`~/.cache/glow-preview/`):
  - `<hash>.md`: the fetched document
  - `.tool`: the tool used
  - `.cme/`: cme's export folder
- Tests: `python3 -m unittest discover -s tests`
- Design and plans: `docs/superpowers/specs/2026-11-13-glow-preview-design.md`, `docs/superpowers/plans/2026-11-13-glow-preview-plan*.md`
