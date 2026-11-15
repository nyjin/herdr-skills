# peek 0.5.0: integration test (2026-11-15)

The built plugin, linked into a separate herdr 0.9.5 session (`XDG_CONFIG_HOME=/tmp/pkx`, so the herdr in daily use
and its plugin list were untouched), shown in its own Ghostty window on a Retina display (pane cells 17 x 37 px).
Clicks were made through `plugin.action.invoke` with the clicked URL, the path herdr itself takes for a link click;
keys through `herdr pane send-text`; mouse moves, clicks and the wheel as the SGR pixel reports a terminal sends.
Screenshots of each step are in `screens/` (local only).

## What was checked

| Area | Result |
|---|---|
| Click on a markdown path | viewer pane opens to the right without focus; page rendered at native resolution, sharp |
| Markdown | headings, table, relative image from the document's folder, code block |
| Links in the page | local file opens in the viewer, `h` goes back, `#anchor` scrolls (after adding heading ids) |
| Source with `:40` | line 40 marked and scrolled to, highlighting and line numbers |
| Several matches (`README.md`) | numbered list, a digit opens the choice |
| Image, HTML file | image shown; the HTML file's own styles apply and its script does not run |
| Find | 4 matches case-insensitive, 3 with `Aa`; `Enter`/`n` steps; `Esc` clears |
| Zoom | `+` to 120 %, re-laid out; remembered; a herdr action from the Claude pane zooms the viewer |
| Rendered ↔ source | `t` and the bar's Source item |
| Top bar | hovering Reload shows `Reload (r)`; narrow panes show keys only |
| Screenshot | PNG in the session folder, PNG on the clipboard |
| File saved | page redrawn where it was |
| Pane resize | re-laid out, reading position kept |
| Two viewers | two Claude-side panes, two viewers, both drawing |
| Jira / PR without a token | a page with `peek auth …` and how to retry |
| `q` | the viewer pane closes; the next click opens a new one |

Not checked here: open in browser and clicks on web addresses (they open the user's browser), fetching with real
tokens (none registered), PDF (no PDF handling: it shows as text).

## Timings (median)

| | ms |
|---|---|
| key `j` to screen (text baseline in the same window: 38) | 44 |
| key `k` to screen | 52 |
| click to the viewer's first change (includes about 60 ms of the test's own trigger) | 122 (173 before the 30 ms state check) |
| page load in WebKit, small documents | 6 (the design doc: 392) |
| one tile captured (12.5 MB) | 8-36 |

## Found and fixed during the test

- Headings had no ids, so `#anchor` links went nowhere: GitHub-style ids are added.
- The first page was built before herdr reported the pane's pixel size, with a fallback font size: the first open
  waits for it.
- The bar showed the previous document's name over the choice list, and the last part of a link's address for
  fetched pages: it shows "Choose a file" and the fetched page's title.
- The viewer polled the state file every 150 ms: it checks the file's time every 30 ms instead.
- The file watch counted an event from a write made just before the watch started: it compares the file's time and
  size.
- Test detail, not a fix: an action invoked through the API runs for the pane herdr has focused, not the pane named
  in the call's context, so the test focused the clicking pane first.
