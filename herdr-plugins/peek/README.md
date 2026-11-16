# peek

**English** | [한국어](README.ko.md)

A herdr plugin that shows a file or link, rendered like a web page, in a pane to the right of the pane where you **select** a path or **Ctrl+click** a link. Nothing opens without a selection or a click.

macOS's own WebKit renders the page out of sight, and the picture is shown in the herdr pane with Kitty graphics, at the pane's full resolution. Nothing else has to be installed: no glow, bat, python3 or CLI tools.

## Opening things

**Select a path**: drag over it or double-click it, in any pane (Claude Code, a shell, a log). herdr copies a mouse selection to the clipboard (`copy_on_select`, on by default); peek watches the clipboard, and when the copied text is shown in a pane of the current tab and names a file, it opens that file beside that pane.

- The text must hold a `/`, a file extension or a `:line`, so a plain word (`peek`, `LICENSE`) never opens anything.
- When the text as selected is no file, up to four characters are dropped from its end, so a Korean particle written right after a path does not get in the way (`kitty.rs:58` followed by one opens line 58). Korean folder and file names open as selected.
- Folders open nothing (yet).
- It cannot see: the same text selected twice in a row (herdr does not copy what the clipboard already holds), a path a program broke over two lines (select the part on one line, such as the file name), a herdr client attached over SSH, or `copy_on_select = false`.
- Selecting a path only to copy it opens it too, without taking focus. Turn select to open off or on with the herdr action `peek: select to open on/off`.
- The copied text is checked in memory and never stored; `~/.local/state/peek/watch.log` lists only what was opened. The watcher (`peek watch`, one per herdr server) starts with herdr or with the first peek run and stops with the server.

**Ctrl+click a link.** herdr passes a click to a plugin only while you hold **Control** (on macOS too: the mouse reports herdr gets cannot tell Command from a plain click), and only on two kinds of text:

- a web address (`http://`, `https://`) printed as plain text: Jira, Confluence and GitHub PR addresses open in peek, other addresses in the browser;
- a hyperlink (OSC 8) that a program printed, whatever its target: `file:///Users/me/a.md`, `docs/a.md`, `src/app.rs:42`.

A path printed as plain text is not clickable, because herdr does not look for paths in plain text (requested in [herdr discussion #609](https://github.com/herdrdev/herdr/discussions/609)); select it instead. Clicks also need herdr's mouse capture (`ui.mouse_capture`, on by default).

| Opens | Shown as |
|---|---|
| a `.md` / `.markdown` path | rendered markdown (tables, task lists, footnotes, images); `t` switches to the source |
| a source path (`.py` `.java` `.kt` `.ts` `.rs` …); a trailing `:line` jumps to and marks that line | highlighted source with line numbers |
| an image (`.png` `.jpg` `.gif` `.webp` `.svg`) or an `.html` file | the image, or the page with its own styles |
| Jira `…atlassian.net/browse/KEY` | summary, status, assignee, description and comments |
| Confluence `…atlassian.net/wiki/…/pages/<id>` | the page body |
| GitHub PR `github.com/<o>/<r>/pull/<n>` | title, state, description and comments |

- A shortened path (`docs/a.md`, `…/deep/a.md`, `a.md`) is looked up in four places at once: the pane's working folder, the session scratchpad, the session transcript and the git checkout. One candidate opens directly; several show a numbered list; none gives a herdr notification.
- There is one viewer per pane you select or click in, opened without taking focus. It follows the shown file: when Claude (or you) saves it, the page is redrawn where you were reading.
- Page scripts never run. HTML inside markdown is shown but inert; HTML files keep their stylesheets, scripts stay off. Remote images load. Mermaid and math show as code.

## Keys and the top bar

The top row of the viewer is a bar: the document's name, then `⟳` (reload), `Source`, `⌕` (find), `Shot`, `↗` (open in the browser) and `…`, which turns the row into the zoom row (`−` 100% `+` `Reset` `✕`). Hovering an item shows its name and key; clicking runs it. In a narrow pane the bar shows the keys instead of the symbols.

`/` or `⌕` opens the find row in place of the bar: a field with the caret in it, `Aa` (match case), `ab` (whole word), `.*` (regular expression), the position (`3/12`), `↑` `↓` and `✕`. While it is open, typing goes into the field, as in an editor: `Enter` or `↓` goes to the next match, `Shift-Enter` or `↑` to the previous one, `Esc` or `✕` closes it, PgUp/PgDn and the wheel still scroll. `Alt-c`, `Alt-w` and `Alt-r` switch the options; whole word and regular expression exclude each other (turning one on turns the other off), match case goes with either.

| Key | Does |
|---|---|
| `j` `k` ↑ ↓, the wheel | scroll a few lines |
| `space` `b` PgDn PgUp | scroll a screen |
| `g` `G` | top, bottom |
| `/` | find (above) |
| `r` | reload (fetches a link again) |
| `t` | rendered ↔ source |
| `+` `-` `0` | zoom in, out, reset (50-200 %, remembered) |
| `s` | screenshot of the screen, also copied to the clipboard |
| `o` | open in the browser (a local document as a page with its images; a link at its address) |
| a click on a link | a local file opens here, a web address in the browser, `#anchor` scrolls |
| `h` Backspace | back |
| `q` | close the viewer |

Every command is also a herdr action (`peek: reload`, `peek: zoom in` …), usable from the Claude pane too. To bind one to a key, add this to `~/.config/herdr/config.toml` (the format passes `herdr config check`):

```toml
[[keys.command]]
key = "prefix+v"
type = "plugin_action"
command = "nyjin.peek:toggle-view"
```

## Jira, Confluence and GitHub tokens

Links are fetched through each service's API, so peek needs a token once per service. It is kept in the macOS Keychain (service `peek`).

```sh
peek auth atlassian <site>.atlassian.net   # your email, then an API token (id.atlassian.com → Security → API tokens)
peek auth github                           # a GitHub token (public repositories need one too)
```

Run them with the plugin's binary: `<plugin folder>/bin/peek auth …`. Without a token the viewer shows the command to run; press `r` after running it.

## Where things go

```
/tmp/peek-<uid>/<project>/<session>/      private (0700); <session> is the Claude session of the pane, or pane-<id>
  screenshots/<YYYYMMDD-HHMMSS>-<document>[-L<line>].png
  browser/<document>.html                 the page handed to the browser
  pages/                                  pages the viewer loads
  viewer.log                              timings and errors of the last viewer run
~/.local/state/peek/                      what each viewer shows, the zoom, the select-to-open switch, watch.log
~/.cache/peek/links/                      fetched Jira, Confluence and PR pages and their images
```

`/tmp` may be emptied on restart: copy screenshots you want to keep.

## Install / remove

```sh
git clone https://github.com/nyjin/herdr-skills && cd herdr-skills/herdr-plugins/peek
cargo build --release                       # needs a Rust toolchain; release downloads are planned
herdr plugin link "$PWD"                    # install
herdr plugin uninstall nyjin.peek           # remove
```

Requires macOS and herdr 0.9.3 or later in a terminal with Kitty graphics (Ghostty); pictures in panes need herdr's standard Kitty graphics, which herdr 0.9.5 turns on by default.

Up to 0.3.0 the plugin was called glow-preview (`nyjin.glow-preview`). If you installed it, remove it with `herdr plugin uninstall nyjin.glow-preview`, then install peek.

## Layout

- `src/`: one crate. Platform-neutral modules (`target`, `resolve`, `state`, `herdr`, `link`, `page`, `script`, `fetch`, `kitty`, `term`) build and test anywhere; `src/mac/` (WebKit renderer, viewer, file watch, Keychain, clipboard) needs macOS.
- `bin/peek`: runs the binary built in this folder.
- `tests/`: `cargo test` (`scripts/check.sh unit` runs it).
- `evals/`: the rendering spike and the measured results (`evals/results.md`); screenshots stay local.
- Design: `docs/superpowers/specs/2026-11-15-peek-webkit-viewer-design.md`.
