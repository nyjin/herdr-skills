# peek rendering spike (2026-11-15)

Kept as the reference for the WebKit viewer: whether a hidden WebKit view can render peek's pages and show them inside
a herdr pane fast enough, and what the pieces cost. Not part of the plugin. Screenshots are in `../screens/` (ignored
by git: they show real, partly private documents).

## What is here

| Path | What it is |
|---|---|
| `rust/src/main.rs` | Resident renderer (`peekd-rs`): hidden `WKWebView` through objc2; JSON lines on stdin (`load`, `size`, `frame`, `zoom`, `find`, `eval`); `--jsoff` turns page scripts off |
| `rust/src/bin/peekv.rs` | Viewer in a pane: renders, sends Kitty graphics, reads keys, mouse and resize (`--mode frame\|tall`, `--medium s\|t\|d`, `--scale`, `--screens`) |
| `rust/src/bin/mdhtml.rs` | Markdown to the page peek would ship: pulldown-cmark, no script, a CSP, find highlight styles |
| `rust/src/bin/srchtml.rs` | Source file to a page highlighted by syntect (onig), line numbers, the clicked line marked |
| `tools/latency2.swift` | Key-to-screen time for one window: grab it, send the key, grab until its pixels change |
| `tools/winlist.swift` | Window ids and bounds, to find the experiment window |

The runs below were driven by throwaway Python scripts over the renderer's JSON lines and the tools above; they were
removed on 2026-11-17 (the repository keeps no Python for peek) and are in the history before that date.

Build: `cargo build --release` in `rust/`; `swiftc -O -o latency2 tools/latency2.swift`. herdr 0.9.5 for the pane runs:
`gh release download v0.9.5 -R herdrdev/herdr -p herdr-macos-aarch64`, run as a separate session so the herdr in use
is untouched.

## Results

Machine: Apple Silicon, macOS 15, Retina display (pane cells 17 x 37 px), Ghostty. Materials: four markdown files
(a short Korean report with tables, a long Korean plan, an English README with many images, a very large table) and
four source files (82 to 3,430 lines).

### Renderer (Rust through objc2, against the earlier Swift version; median ms)

| | Swift | Rust |
|---|---|---|
| start | 87 | 77 |
| open a page | 73 | 75 |
| capture one screen | 12 | 16 |
| scroll and capture | 11 | 12 |
| resize, then capture | 22 | 22 |
| binary | 0.1 MB | 0.4 MB |

Frames match: the 2x capture is byte-identical; the 1x capture differs in about 4 % of bytes (scaling filter).
Swift's resize returned height 0; the Rust one waits until the page reports the new width
(`requestAnimationFrame` never fires in a view that is not in a window).

### Features in the renderer

| | Result |
|---|---|
| find | first search 11-23 ms, next match about 2 ms; CSS Custom Highlight API, so the DOM is untouched and it works with page scripts off. The `::highlight` styles must be in the page from the start: inserted at the first search, the first capture does not show them |
| zoom | `pageZoom` re-layout 38-40 ms + capture 16-19 ms |
| source view | syntect with the onig engine: 3,430-line Python 118 ms, others 5-17 ms (the fancy-regex engine took about 300 ms for Python) |
| page as shipped (scripts off, CSP) | ready detected by `readyState`; a `<script>` and an `onerror` in the markdown did not run; find highlight shows; `elementFromPoint` returns the right link for a click |
| images | all https images load; relative images load only when the read-access root of `loadFileURL` covers the document's folder (15 of 35 failed with the page's own folder, 35 of 35 with a wider root) |

### In a herdr 0.9.5 pane (standard Kitty graphics)

herdr 0.9.2 removed the herdr-only `pane.graphics.*` API that the first runs (herdr 0.9.0) used; those numbers no
longer apply. On 0.9.5 the viewer writes Kitty graphics to its own terminal.

Key-to-screen, median of 12, measured on the experiment window while another window covered it (Ghostty kept
drawing it); the trigger is a `herdr pane send-text` call, about 14 ms of it:

| Setup | ms |
|---|---|
| text baseline: `less`, one page | 38 |
| capture every scroll, full pane at native pixels (21.5 MB) | 318 |
| capture every scroll, 0.75 scale (12.1 MB) | 91 |
| capture every scroll, 0.5 scale (5.4 MB) | 69 |
| one tall image sent once, scroll moves the placement's source rect | 34-40 |

- Transmission: shared memory (`t=s`) works; a temp file (`t=t`) is accepted only from the system temp dir
  (`$TMPDIR`), not `/tmp`; inline base64 (`t=d`) takes 0.8-1.9 s to write a 22 MB frame.
- Size: the jump between 12 MB and 21.5 MB per image rests on these two points only. A 67 MB image was refused
  (`ENOMEM`).
- Quality: 0.75 scale is close to native; 0.5 is visibly soft. The user found 0.75 blurry: keep native pixels.
- A placement whose source rect runs past the image's end stretches the picture.
- Resize and keys can arrive before the page has loaded; the first capture can come before images have loaded.
- Two viewers side by side: both draw, no errors. Pane resize: re-layout 7 ms, redraw 30 ms.
- Mouse with SGR pixel reports (`?1000h ?1003h ?1006h ?1016h`): moves (for hover), clicks and wheel events all
  reach the viewer with pixel coordinates.
