# peek: WebKit viewer in one Rust binary — Design

> Current design for `herdr-plugins/peek` from 2026-11-15. It replaces the glow/bat design
> (`2026-11-13-glow-preview-design.md`, kept as the record of the earlier versions). Measurements behind it:
> `herdr-plugins/peek/evals/spike/README.md`.

## Purpose

A click on a path or link in a Claude Code pane shows it, rendered like a web page, in the pane to the right of that
Claude pane: markdown, source code, images, HTML, and Jira, Confluence and GitHub PR content. Nothing has to be
installed besides the plugin itself (the old version needed glow, bat, acli, jira-cli, cme and gh).

## User decisions (2026-11-15)

- Render inside the herdr pane; a window outside the pane is not a plugin. A light browser engine (macOS's own WebKit,
  hidden) renders; the frames are shown with Kitty graphics. Not Electron, not a terminal-text renderer.
- The whole plugin is one Rust binary. Python, glow and bat go.
- Text must stay sharp: frames use the pane's native pixels.
- Controls: keys in the viewer, herdr actions, and a top bar; hovering a top bar item shows a tooltip with its
  shortcut.
- Find works like an editor's: match case, whole word, regular expression.
- Remote images in local documents always load.
- A changed file is redrawn automatically (file change events, not polling).
- Links inside a rendered page: a local file opens in peek (with back); a web address opens in the default browser.
- File types: markdown, source, images, SVG and HTML. PDF only if it renders well (left out of 0.5.0).
- Jira, Confluence and GitHub PR content is fetched through each service's API with a token that the user registers
  with `peek auth`, and shown in the pane.
- Screenshots go under `/tmp` (layout below).
- Theme follows the system (dark/light); the page's font size follows the terminal's; zoom 50-200 % in 10 % steps,
  remembered.
- Page scripts are off; HTML inside markdown is shown but never runs. Mermaid and math show as code blocks for now.
- Scope of this round: implementation, tests and commits. No PR, merge or release.

## What goes, what stays

Goes (from the 2026-11-13 design and the README): glow, bat and the `brew install` step; acli, jira-cli, cme, gh and
the `claude -p` MCP fallback; the "do not open a browser" non-goal (there is now an open-in-browser command); the less
menu and its keys (`s`, `f`, `m`); `~/.cache/peek` documents as markdown; Python and its tests.

Stays: one viewer per Claude pane, opened with `herdr plugin pane open --placement split --target-pane <source>
--direction right --no-focus`; the state file per source pane (`~/.local/state/peek/<source>.json`) and the
`.viewer` file; nothing opens without a click; the herdr action that toggles rendered/source; path resolution
(below, moved here unchanged).

## Requirements

- macOS (WebKit through objc2). herdr ≥ 0.9.3 (`link_handlers`, `plugin pane open --env`; standard Kitty graphics
  in panes since 0.9.2). Kitty graphics are on by default in herdr 0.9.5 (`[terminal] kitty_graphics`).
- A terminal with Kitty graphics outside herdr (Ghostty).
- No other tool. Tokens for Jira/Confluence/GitHub are needed only for those links.

## Binary and plugin layout

```
herdr-plugins/peek/
  herdr-plugin.toml        panes, actions and link handlers run bin/peek
  bin/peek                 launcher: runs target/release/peek; if it is missing, prints how to build it
  Cargo.toml, src/         the crate
  tests/                   cargo integration tests (platform-neutral)
  evals/                   spike and screenshots (not shipped behaviour)
```

Subcommands: `peek link` (link handler action), `peek action <name>` (herdr actions: toggle, reload, find, zoom-in,
zoom-out, zoom-reset, screenshot, browser, back), `peek viewer` (the pane), `peek auth <service>` (token
registration).

Modules. Platform-neutral ones build and test on Linux (CI is ubuntu); macOS-only ones sit behind
`#[cfg(target_os = "macos")]` with their crates under `[target.'cfg(target_os = "macos")'.dependencies]`:

| Module | Job | Platform |
|---|---|---|
| `resolve` | clicked text → candidates (rules below) | neutral |
| `target` | classify: Jira, Confluence, PR, path with `:line` | neutral |
| `state` | state files, viewer bookkeeping, zoom preference, `/tmp` layout | neutral |
| `page` | markdown/source/image/HTML/API content → page HTML (template, theme, CSP) | neutral |
| `fetch` | REST calls, attachments, link cache | neutral (HTTP client) |
| `herdr` | calls to the herdr CLI | neutral |
| `render` | hidden `WKWebView`: load, readiness, capture, zoom, find, hit-test | macOS |
| `kitty` | tiles, shared memory transmission, placements | neutral encoding, macOS shared memory |
| `term` | raw mode, keys, SGR pixel mouse, resize, top bar text | neutral |
| `viewer` | the event loop tying them together | macOS |
| `watch` | file change events (FSEvents) | macOS |
| `keychain` | token store | macOS |

Release download (a `peek-v<version>` tag never marked latest, checksum pinned in the repo) is future work; for now
the binary is built in the checkout with `cargo build --release`.

## Flow

1. A click matches a link handler → herdr runs `peek link` with `HERDR_PLUGIN_CLICKED_URL` and `HERDR_PANE_ID`.
2. `peek link` classifies the text, resolves a path (below) or keeps the URL, writes the state file and opens the
   viewer pane if the source pane has none. Focus stays on Claude.
3. The viewer sees the state change, shows `Loading <name> ...` as terminal text, builds the page, loads it in the
   hidden WebKit view, captures and shows it. Keys and clicks that arrive before the page is ready wait for it.

### Path resolution (on a link click; unchanged from the 2026-11-13 design)

The clicked string is judged after stripping `file://`, a trailing `:line[:col]`, and quotes, brackets and punctuation.

1. Absolute path or `~/`: open it right away if the file exists.
2. Any other path: collect candidates from the four sources below all at once. The order does not affect the result.
   - Working folder: join onto the `foreground_cwd` of the clicked pane (not `cwd`; in a session that moved into a
     worktree, `cwd` points at the old location).
   - scratchpad: join onto `/private/tmp/claude-<uid>/*/<session id>/scratchpad`. The session id is the pane's
     `agent_session.value`. A leading `scratchpad/` is dropped before joining.
   - Transcript: absolute paths found in `~/.claude/projects/*/<session id>.jsonl` whose tail matches.
   - git: files (tracked and untracked, ignored files excluded) of the repository that `foreground_cwd` belongs to
     whose tail matches.
   - A string that starts with `…/` is used only for tail matching.
3. Remove duplicates by real file (realpath). One candidate opens; several show a selection list in the viewer (as
   terminal text, the most recent in the transcript first); none gives a herdr notification "file not found".

## The page

- Markdown: pulldown-cmark with tables, strikethrough, task lists and footnotes. Source: syntect with the onig engine
  (line numbers; the clicked line marked and scrolled to). Images and SVG: an image element on the page background.
  HTML files: loaded as they are, scripts still off.
- Template: Catppuccin Mocha (dark) or Latte (light) by the system appearance; the base font size follows the
  terminal cell height in CSS pixels; the find highlight styles (`::highlight(peek-find)`, `::highlight(peek-cur)`)
  are in the template from the start (inserted later, the first capture misses them).
- CSP: `default-src 'none'; img-src * data: file:; style-src 'unsafe-inline'; font-src data: file:`. Page scripts
  off through `WKWebpagePreferences.allowsContentJavaScript = false`; peek's own scripts run through
  `evaluateJavaScript`.
- Page files go to `/tmp/peek-<uid>/<project>/<session>/pages/`. The read-access root given to `loadFileURL` must
  cover both the page and the document's folder (relative images fail otherwise): use `/`.
- Ready when the navigation's own marker (a query on the page URL) is current and `document.readyState` is
  `complete`. Images that finish after the first capture trigger a re-capture of the screen.

## Showing it in the pane

- Kitty graphics written to the viewer's own terminal; herdr renders them. Transmission through POSIX shared memory
  (`t=s`). Temp files are accepted only from `$TMPDIR`; inline base64 is far too slow for whole screens.
- Native pixels (scale 1.0) always.
- Byte budget per image, not a fixed size: one image costs about 91 ms on screen at 12 MB and 318 ms at 21.5 MB
  (two data points; 67 MB was refused). So the document is captured in tiles of at most 12 MB (tile height =
  budget / (pane pixel width × 4)), possibly less than a screen. The visible screen is shown as one placement per
  visible tile, each with a source rect inside its tile (a source rect past an image's end stretches the picture).
- Scrolling moves placements only (measured 34-40 ms key-to-screen, the same as terminal text). Tiles around the view
  are captured ahead while idle; tiles far away are deleted (`a=d`).
- Resize: re-measure (cells and pixels from `TIOCGWINSZ`), re-lay out, keep the reading position by the element at
  the top of the screen, drop and rebuild the tiles.
- The top row is terminal text (the top bar); images start on the second row.

## Input

- Raw mode. Mouse reports in SGR pixels: `?1000h ?1003h ?1006h ?1016h` (clicks, moves for hover, wheel).
- Wheel scrolls. A click on the page maps the pixel to page coordinates; `elementFromPoint(...).closest('a')` gives
  the link: a local file opens in the same viewer and pushes history; a web address goes to `open`.
- Default keys: `j`/`k`/↑/↓ a few lines, `space`/`b`/PgDn/PgUp a screen, `g`/`G` top/bottom, `/` find, `n`/`N` next
  and previous match, `r` reload, `t` rendered/source, `+`/`-`/`0` zoom in/out/reset, `s` screenshot, `o` open in
  browser, `h`/Backspace back, `q` close.
- The same commands exist as herdr actions, so they work from the Claude pane too.

## Top bar

One text row: file name · Reload · Source · Find · − 100 % + · Screenshot · Browser. Hovering an item shows a tooltip
with its name and key (`Reload (r)`). Clicking runs it. While finding, the row becomes the find field with toggles
for match case, whole word and regex, and the position (`3/22`); `Esc` closes it.

## Find

App-injected script, so it works with page scripts off. Matches are marked with the CSS Custom Highlight API (the
DOM is untouched): all matches lightly, the current one strongly. Options: match case, whole word, regular
expression (JavaScript syntax). Measured 11-23 ms for a search, about 2 ms to step.

## Zoom

`pageZoom`, 50-200 % in 10 % steps, remembered in the state folder; the element at the top of the screen stays at the
top. Measured re-layout 38-40 ms plus capture.

## Screenshot

The current screen as PNG, also copied to the clipboard; a herdr notification gives the path.

```
/tmp/peek-<uid>/                         0700, created and checked to be ours (not a link, owned by the user)
└── <project>/                           Claude's project name for the folder (as in ~/.claude/projects)
    └── <session>/                       the Claude session id of the source pane; pane-<id> if it has none
        ├── screenshots/<YYYYMMDD-HHMMSS>-<document>-L<line>.png
        ├── browser/<document>.html      the page handed to the browser by "open in browser"
        └── pages/                       pages the viewer loads
```

`/tmp` may be emptied on restart; that is accepted.

## Open in browser

A local document: write its page with absolute `file://` references to `browser/` and run `open`. A Jira,
Confluence or PR view: open the original URL.

## File changes

Subscribe to file change events (FSEvents) for the shown file's folder; react to the file (writes, atomic renames).
Debounce 300 ms; reload and keep the reading position.

## Jira, Confluence, GitHub PR

| Link | Call | Page |
|---|---|---|
| `https://<site>.atlassian.net/browse/KEY` | `GET /rest/api/3/issue/KEY?expand=renderedFields&fields=summary,status,assignee,description,comment` | summary, status, assignee, rendered description and comments |
| `https://<site>.atlassian.net/wiki/.../pages/<id>` | `GET /wiki/api/v2/pages/<id>?body-format=view` | title and rendered body |
| `https://github.com/<o>/<r>/pull/<n>` | `GET /repos/<o>/<r>/pulls/<n>`, issue and review comments, `Accept: application/vnd.github.html+json` | title, state, `body_html`, comments |

- Tokens: `peek auth atlassian <site>` (email and API token, Basic auth), `peek auth github` (token, Bearer), stored in
  the macOS Keychain. peek does not read other tools' credentials.
- Images that need the token (Jira and Confluence attachments) are downloaded with it and referenced as local files.
- Fetched pages are cached in `~/.cache/peek/links/` with the fetch time; `r` fetches again.
- Failures show a page with the cause and the fix: no token (`peek auth ...`), 401/403, 404, timeout.

## Tests

- `cargo test` covers the platform-neutral modules: resolution (the old Python cases ported), classification, page
  building, find query building, tile and placement arithmetic, Kitty command encoding, REST requests against a local
  fake server, state and `/tmp` layout.
- `scripts/check.sh unit` runs `cargo test` in `herdr-plugins/peek` (Python units elsewhere as before); CI on ubuntu
  builds the neutral modules only.
- The viewer is checked by hand and with the spike's harness in a herdr 0.9.5 session (key-to-screen, two viewers,
  resize, mouse); results go to `evals/`.

## Left to the implementer

The exact keys for the find toggles, tooltip placement, tile budget tuning, the font size formula, error page wording,
and the HTTP client crate.

## Select to open (0.6.0, decided 2026-11-16)

herdr hands plugins no click on a path printed as plain text (see "What shipped" below), and no selection or copy
event either (`src/api/schema/events.rs` lists pane, tab, workspace and worktree events only). What herdr does do: when
a mouse selection ends, by drag or double-click, it copies the text to the system clipboard (`[ui] copy_on_select`, on
by default; `pbcopy` on macOS). peek uses that copy as its signal.

User decisions: web addresses and hyperlinks keep Ctrl+click; paths open by selecting them (drag or double-click).
Nothing changes what agents or programs print, and nothing sits between herdr and the pane's shell. When herdr starts
matching link handler patterns against plain text (herdr discussion #609), paths open by Ctrl+click through the
existing link handlers with no change in peek; select to open is then reconsidered (off by default or removed).

Checked by hand in a herdr 0.9.5 session (2026-11-16): a drag copied `2026-11-15-repo-layout-and-language-design.md`
from a shell pane; a double-click copied `docs/superpowers/specs/` plus the Korean particle U+C5D0 written right after
it, from a Claude Code pane (herdr's word selection splits at spaces, and Korean attaches particles without one). In
both cases the system clipboard changed and the text was on that pane's screen. herdr did not move focus to the pane
the selection was made in. `copy_on_select` and `[[startup]]` hooks exist in herdr 0.9.3, so the minimum stays.

### The watcher

`peek watch` is a background process, one per herdr server.

- Started detached by a `[[startup]]` hook (`peek watch --spawn`, which forks and returns) and, so that a fresh
  `herdr plugin link` needs no restart, by every `peek link`, `peek action` and `peek viewer` run when none is running.
  One per server: a lock file in `~/.local/state/peek/` keyed by `HERDR_SOCKET_PATH`. It exits when the server's
  socket stops answering twice in a row, 5 s apart (a live handoff reruns the startup hook under the new server).
- Every 150 ms it reads the pasteboard's change count (`NSPasteboard.changeCount`), not its contents. Only when the
  count changed does it read the string, and only when select to open is on.
- The text is kept in memory for the checks below and never written anywhere; `viewer.log` records an opened path
  only.

### Which pane, which file

1. The text is one line, 1 to 1024 characters, without control characters.
2. The panes of the tab shown in the focused workspace (`herdr pane list`), except peek's viewer panes, are read
   (`herdr pane read --source visible`). A pane matches when the text is in one of its rows, or in its rows joined
   without line breaks (a path wrapped over two rows). The focused pane wins when several match, otherwise the first.
   No match: the copy came from elsewhere (a browser, an editor) and nothing happens.
3. The text is resolved for the matched pane like a click (path resolution above), with two additions:
   - **Trailing characters.** When the text as selected resolves to nothing, up to 4 characters are dropped from its
     end, one at a time, and the longest form that resolves wins. Nothing is judged by script, so Korean folder and
     file names open as selected; a path followed by a one- or two-syllable particle opens without it (`kitty.rs:58`
     plus a particle opens line 58); a file whose name really ends in what looks like a particle still opens as
     selected.
   - **Folders.** A folder (absolute, `~/`, or joined onto the pane's working folder or its git root) opens as a
     folder page.
   Binary files other than images (a NUL byte in the first 8 KiB) are skipped. Nothing found: nothing happens, no
   notification (most selections are not paths).
4. One result opens in the viewer beside the matched pane without taking focus, as a click does; several show the
   numbered list.

### Folder page

A new page kind: folders first, then files, each sorted by name, with size and modification time; a `..` entry for
the parent; at most 500 entries, then "N more". Entries are local links, so clicking one opens a file in peek or
another folder page, and `h` goes back. FSEvents on the folder (not recursive) redraw it when entries change.

### Turning it off

On by default. The herdr action `peek: select to open on/off` (`select-to-open`) toggles it; the choice is kept with
the zoom in `~/.local/state/peek/`. The README says what it relies on and what it cannot see:

- `copy_on_select` must stay on.
- Selecting the same text twice in a row opens nothing the second time: herdr does not copy text the clipboard
  already holds.
- A client attached over SSH copies to its own machine's clipboard, which peek cannot see.
- Selecting a path only to copy it also opens it (without focus).

### Tests

- Neutral (`select` module): the text filter; pane matching (row, wrapped rows, several panes, focus preference, no
  match); trailing-character trimming; resolution against temporary folders with Korean folder and file names in
  both NFC and NFD form, particles after files, lines and folders; binary skip; the watcher's decision loop driven by
  a fake clipboard (change count and string) and fake screens.
- Folder page: order, the 500 cap, links, `..`.
- macOS: the pasteboard reader; the lock and the exit on a dead socket.
- Integration in a separate herdr 0.9.5 session: a selection by drag and by double-click opens the viewer beside the
  pane it was made in (made by hand, as no API makes a herdr selection), plus `pbcopy` of on-screen and off-screen
  text for the timing (copy to first change) and the no-op cases.

## What shipped (0.5.0, 2026-11-15)

Built as designed, in the order of `docs/superpowers/plans/2026-11-15-peek-webkit-viewer-plan.md` (Tasks 2-4 by
three workers in parallel, the viewer in one stream). Integration test and timings: `herdr-plugins/peek/evals/results.md`
(key to screen 44-52 ms against 38 ms for terminal text; click to the viewer's first change about 120 ms).

Differences from the design above:

- HTML files get `script-src 'none'; object-src 'none'` instead of the page CSP, so their own stylesheets, images and
  fonts load; scripts stay off (also in the browser copy).
- Markdown headings get GitHub-style ids (`#the-end`), so in-page links work.
- Jira comments come from a second call (`/rest/api/3/issue/<KEY>/comment?expand=renderedBody`), paged; GitHub
  comments are paged too. GitHub needs a token for public repositories as well.
- Images on the same Atlassian site are downloaded with the token, attachments or not.
- The first page waits for the pane's pixel size (herdr reports it a moment after the pane starts); the page's font
  size is the cell height in CSS px / 1.35.
- The viewer checks the state file's modification time every 30 ms; a command already in the file when the viewer
  starts is skipped.
- The file watch reacts only when the file's modification time or size differs.
- In a narrow pane the top bar shows the keys instead of the words. `Enter` in the find field also steps to the next
  match. `=` zooms in as well as `+`.
- Each viewer writes `viewer.log` (timings, errors) in its session folder.
- PDF is not handled (it shows as text); no time was spent on it in this round.
- Clicks reach peek only as herdr hands them over (checked against herdr 0.9.5 on 2026-11-16, `src/app/actions.rs`
  `url_from_link_target`): with Control held, on OSC 8 hyperlinks (any target) and on `http(s)` addresses in plain
  text. A path printed as plain text, which is how Claude Code prints paths in a herdr pane, is not clickable; herdr
  does not detect paths in plain text (herdr discussion #609). Ways around it that change what agents print or put a
  relay between herdr and the shell were rejected: the first changes the user's output, the second hides the pane's
  foreground process from herdr's agent detection and working-folder tracking. Paths open by selection instead:
  "Select to open" above.
