# glow-preview Implementation Plan

> Renamed to `peek` on 2026-11-15 (`herdr-plugins/peek`). This record keeps the names it was written with.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A herdr plugin that opens a glow viewer pane to the right of a Claude Code pane. Two things trigger it: Claude working with a `.md`, and the user clicking a `.md` path on screen.

**Architecture:** One Python script (`glowp.py`) handles three entry points: `hook` (Claude Code PostToolUse), `link` (herdr link handler action) and `viewer` (the plugin pane). hook and link write the path to show into `<state>/<source-pane>.json` and open a viewer pane if there is none. viewer watches that file and restarts glow. `resolve.py` handles path resolution.

**Tech Stack:** python3 standard library, herdr 0.9.3 CLI, glow 3 (brew), unittest.

**Spec:** `docs/superpowers/specs/2026-11-13-glow-preview-design.md`

## Global Constraints

- macOS only, python3 standard library only.
- Plugin id `nyjin.glow-preview`, pane entrypoint id `viewer`, state folder `~/.local/state/glow-preview` fixed (only tests use `GLOWP_STATE_DIR`). Do not use the `HERDR_PLUGIN_STATE_DIR` that herdr gives to plugin panes, because the hook cannot see it.
- The herdr binary is `$HERDR_BIN_PATH`, else `herdr`. Tests can override it with `GLOWP_HERDR`.
- The hook always exits 0 and prints nothing to stdout.
- The viewer pane is opened with `--placement split --direction right --target-pane <source> --no-focus`.
- Never type commands into the user's shell (`pane run` and `send-text` are forbidden).

## Review Focus

1. The clicked string carries `:12`, `file://` or trailing punctuation (`.md),` `.md.`) → the file must still be found. Task 1 `test_normalize_*`.
2. A click in a pane with no session id (a shell, not claude) → resolve with the working folder and git only, no error. Task 1 `test_no_session`.
3. The user closes the viewer pane, then Claude works with a `.md` again → a new viewer must open (never reuse a dead pane id). Task 2 `test_reopens_when_viewer_gone`.
4. `.MD` or `.markdown` extension → included. `.mdx` and `.md.bak` are not targets → ignored. Task 2 `test_hook_extensions`.
5. The file changes while glow is running → the terminal must not break and the new file must show. Task 3 live check.

---

### Task 1: Path resolution (`scripts/resolve.py`)

**Files:**
- Create: `scripts/resolve.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Produces:
  - `normalize(text: str) -> str`: strips the `file://` prefix, wrapping quotes, brackets and backticks, a trailing `:line[:col]`, and punctuation stuck after `.md`.
  - `candidates(text: str, cwd: str | None, session_id: str | None, *, home: str, tmp_root: str, projects_root: str) -> list[str]`: returns the list of real files, deduplicated by realpath. Sort order: the one whose last position in the transcript is latest comes first, and those not in the transcript follow in path order. An absolute path or `~/` returns just that one if the file exists, else `[]`. `tmp_root` is `/private/tmp/claude-<uid>`, `projects_root` is `~/.claude/projects`.

- [ ] **Step 1: Write the failing tests** — set up home, repo (git init, committed files), tmp_root and projects_root in a temp folder.
  - `test_absolute_and_home`: an existing absolute path → `[that path]`, `~/x.md` → `[home/x.md]`, a missing absolute path → `[]`
  - `test_relative_to_cwd`: `docs/a.md` → `[repo/docs/a.md]`
  - `test_scratchpad`: with `tmp_root/<proj>/<sid>/scratchpad/n.md` present, both `scratchpad/n.md` and `n.md` → `[that file]`
  - `test_transcript_suffix`: when `projects_root/p/<sid>.jsonl` has a `"file_path":"/elsewhere/deep/z.md"` line and the file exists, `…/deep/z.md` → `[/elsewhere/deep/z.md]`
  - `test_git_suffix`: finds the repo's `pkg/sub/b.md` as `sub/b.md`
  - `test_dedupe_same_file`: if the same file comes from the working folder, git and the transcript, there is 1
  - `test_ambiguous_order`: `SKILL.md` in two places and the transcript shows A, B, A in that order → `[A, B]`
  - `test_no_session`: with `session_id=None`, it is still found through the working folder and git
  - `test_normalize_suffixes`: `normalize("file:///x/a.md:12:3") == "/x/a.md"`, `normalize("(docs/a.md),") == "docs/a.md"`, `normalize("`a.md`.") == "a.md"`
- [ ] **Step 2: Run and confirm it fails** — `python3 -m unittest tests.test_resolve -v` → `ModuleNotFoundError`
- [ ] **Step 3: Implement** — build the git file list with `git -C <cwd> ls-files -co --exclude-standard --full-name` and `rev-parse --show-toplevel`. The regex that extracts absolute paths from the transcript is `(?:/|~/)[^\s"'`()<>\[\]{}|,:;\\]+\.md`. Tail matching compares against `"/" + the cleaned string`.
- [ ] **Step 4: Confirm it passes** — same command → OK
- [ ] **Step 5: Commit** — `git add scripts/resolve.py tests/test_resolve.py && git commit -m "feat: resolve clicked markdown paths to files"`

### Task 2: Hook, link, state (`scripts/glowp.py` hook / link / show)

**Files:**
- Create: `scripts/glowp.py`
- Test: `tests/test_glowp.py`, `tests/fake_herdr.py` (a fake herdr that records calls as JSON lines and answers `pane get` and `pane list` with JSON taken from environment variables)

**Interfaces:**
- Consumes: `resolve.normalize`, `resolve.candidates`
- Produces:
  - `is_markdown(path: str) -> bool`: true if it ends with `.md` or `.markdown`, case-insensitive
  - `state_dir() -> str`
  - `show(source: str, paths: list[str]) -> None`: atomically writes `{"paths": [...], "seq": <time_ns>}` to `<state>/<source>.json`. If the pane named in `<state>/<source>.viewer` is not in `pane list`, calls `plugin pane open --plugin nyjin.glow-preview --entrypoint viewer --placement split --target-pane <source> --direction right --no-focus --env GLOWP_SOURCE=<source>`.
  - `main(argv)`: `hook` uses `tool_input.file_path` from the stdin JSON and `$HERDR_PANE_ID`, swallows every exception and returns 0. `link` uses `$HERDR_PLUGIN_CLICKED_URL` and `$HERDR_PANE_ID`. It reads `foreground_cwd` (else `cwd`) and `agent_session.value` from `pane get <id>`, and with 0 candidates calls `notification show "glow-preview" --body "File not found: <text>"`.

- [ ] **Step 1: Write the failing tests**
  - `test_hook_opens_viewer`: hook input with a `.md` path → the path is in the state file, and a `plugin pane open … --target-pane <src> --direction right` call is recorded in the fake herdr
  - `test_hook_extensions`: `.MD` and `.markdown` are handled, and `.mdx`, `.md.bak` and `.py` do not write a state file
  - `test_hook_silent_outside_herdr`: with no `HERDR_PANE_ID`, it does nothing and returns 0
  - `test_hook_never_fails`: broken JSON → exit code 0, stdout empty
  - `test_reuses_live_viewer`: if the pane named in `.viewer` is in `pane list`, `plugin pane open` is not called again
  - `test_reopens_when_viewer_gone`: if the pane named in `.viewer` is not in the list, it opens again
  - `test_concurrent_hooks_open_one_viewer`: even with 4 hooks running at once, `plugin pane open` runs once (a per-source-pane lock, plus writing the pane id from the open response straight into `.viewer`)
  - `test_link_not_found_notifies`: 0 candidates → `notification show` is called, no state file
  - `test_link_ambiguous_writes_all`: 2 candidates → state file `paths` has length 2
- [ ] **Step 2: Run and confirm it fails** — `python3 -m unittest tests.test_glowp -v`
- [ ] **Step 3: Implement**
- [ ] **Step 4: Confirm it passes** — `python3 -m unittest discover -s tests -v` all OK
- [ ] **Step 5: Commit** — `feat: open the viewer from the Claude hook and herdr link clicks`

### Task 3: Viewer pane, manifest, install

**Files:**
- Modify: `scripts/glowp.py` (`viewer` subcommand)
- Create: `herdr-plugin.toml`, `install.sh`, `README.md`

**Interfaces:**
- Consumes: the state file format and `state_dir()` from Task 2
- Produces: `viewer` checks the state file of `$GLOWP_SOURCE` every 0.3 seconds.
  - At start it writes its own `$HERDR_PANE_ID` to `<source>.viewer`.
  - If glow is missing, it announces with `notification show` and runs `brew install glow` inside this pane.
  - With 1 entry in `paths`, it starts the glow TUI as a child process. When `seq` changes, it sends the child SIGTERM, restores the screen state (`stty sane`, leave the alternate screen `\x1b[?1049l`, show the cursor `\x1b[?25h`) and starts again.
  - With several entries in `paths`, it prints a numbered list and takes a digit key to choose. It also detects state file changes while waiting for input.
  - When glow ends on its own, it shows "r reopen · q close".

- [ ] **Step 1: Write the manifest** — id `nyjin.glow-preview`, `min_herdr_version = "0.9.3"`, `platforms = ["macos"]`. `[[panes]]` id `viewer`, placement `split`, command `["sh","-c","exec python3 \"$HERDR_PLUGIN_ROOT/scripts/glowp.py\" viewer"]`. `[[actions]]` id `open-link`, command `["python3","scripts/glowp.py","link"]`. `[[link_handlers]]` id `markdown`, `pattern` is a regex matching strings that end in `.md`/`.markdown`, action `open-link`.
- [ ] **Step 2: Write `install.sh`** — `herdr plugin link "$PWD"` (skip if already linked). Back up `~/.claude/settings.json`, and add exactly one group to `PostToolUse` with matcher `Read|Write|Edit|MultiEdit`, `async: true`, command `[ "$HERDR_ENV" = 1 ] || exit 0; python3 "<root>/scripts/glowp.py" hook` (do not add it if the same group exists).
- [ ] **Step 3: Implement the viewer**
- [ ] **Step 4: Live check — install** — `sh install.sh` → `herdr plugin list` shows `nyjin.glow-preview` as enabled, and settings.json has 1 group
- [ ] **Step 5: Live check — hook path** — Read one `.md` in this Claude pane → a pane appears on the right, `pane process-info` shows glow, and focus stays put. If glow was missing, the install notification and the install process appear in that pane
- [ ] **Step 6: Live check — file swap** — Read another `.md` → in the same pane glow restarts on the new file (check with `pane read`). No new pane appears
- [ ] **Step 7: Live check — reopen after close** — close the viewer pane and Read a `.md` → a new viewer opens
- [ ] **Step 8: Link path** — `HERDR_PLUGIN_CLICKED_URL=README.md HERDR_PANE_ID=<this> python3 scripts/glowp.py link` → shown in the viewer. A real mouse click is left as an item for the user to confirm
- [ ] **Step 9: README and commit** — write install, behavior and removal in the README and commit: `feat: glow viewer pane, manifest and installer`
