# peek WebKit Viewer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace peek's Python + glow/bat viewer with one Rust binary that renders pages in a hidden WebKit view and shows them in the herdr pane with Kitty graphics.

**Architecture:** One crate in `herdr-plugins/peek`: platform-neutral modules (link handling, page building, REST fetch, Kitty and terminal encoding) tested with `cargo test` on any OS, and macOS-only modules (`src/mac/`: WebKit renderer, viewer loop, file watch, Keychain, clipboard) behind `cfg(target_os = "macos")`. Task 1 fixes every module's interface so Tasks 2-4 run in parallel workers; the viewer (Tasks 5-6) is one sequential stream because it can only be verified in a herdr ≥ 0.9.2 pane.

**Tech Stack:** Rust 2021; pulldown-cmark 0.12, syntect 5 (onig), ureq 2, serde/serde_json, regex, libc; macOS: objc2 0.6, objc2-web-kit/app-kit/foundation/core-graphics/core-foundation 0.3, block2 0.6, dispatch2 0.3, security-framework 3, notify 8; dev: tiny_http 0.12, tempfile 3.

**Spec:** `docs/superpowers/specs/2026-11-15-peek-webkit-viewer-design.md` (numbers: `herdr-plugins/peek/evals/spike/README.md`; working reference code: `herdr-plugins/peek/evals/spike/rust/`).

## Global Constraints

- Everything in the repository is English (code, comments, UI strings, commit messages); Korean only in tests where it does a job, with an English comment saying why (`scripts/check.sh language`).
- `scripts/check.sh` passes before every commit. Commit only: no push, no PR, no merge to `main`, no release.
- macOS only at run time; the platform-neutral modules must build and test on Linux (CI is ubuntu).
- herdr ≥ 0.9.3 (`min_herdr_version = "0.9.3"` stays).
- Frames at the pane's native pixels; each Kitty image ≤ 12 MiB (`TILE_BUDGET = 12 * 1024 * 1024`); transmission through POSIX shared memory (`t=s`).
- Page scripts off (`allowsContentJavaScript = false`); CSP exactly `default-src 'none'; img-src * data: file:; style-src 'unsafe-inline'; font-src data: file:`; `loadFileURL` read-access root `/`.
- State: `$PEEK_STATE_DIR` or `~/.local/state/peek`. Temp: `/tmp/peek-<uid>/<project>/<session>/{pages,browser,screenshots}`, 0700, refused if a link or not owned by the user.
- herdr CLI: `$PEEK_HERDR` (may hold arguments, split on whitespace) or `$HERDR_BIN_PATH` or `herdr`.
- UI strings: `Loading <name> ...`; bar items `Reload (r)`, `Source (t)`, `Find (/)`, `Zoom out (-)`, `Zoom in (+)`, `Screenshot (s)`, `Open in browser (o)`.

## Review Focus

- A huge file (60,000-line log or source): the page is built and shown, highlighting stops at 20,000 lines with a visible note, the rest is plain text — Task 3 test `source_page_caps_highlighting`.
- Invalid UTF-8 or binary content in a clicked text file: shown lossily, never a panic — Task 3 test `invalid_utf8_is_shown_lossily`.
- Paths with spaces and Korean names: resolved, loaded (URL-encoded) and named in screenshots — Task 2 test `resolves_path_with_space_and_korean`, Task 3 test `page_file_url_is_encoded`.
- A tiny pane or a pty that reports no pixel size: no panic; cells fall back to 8 x 18 px and tiles hold at least one row — Task 5 tests `tile_rows_at_least_one`, `geometry_without_pixels_falls_back`.
- API unreachable, slow or token expired: an error page with the cause and fix, the viewer stays usable — Task 4 tests `timeout_gives_error_page`, `unauthorized_points_to_peek_auth`.

---

### Task 1: Crate skeleton, launcher and checks (this session, before any worker)

**Files:**
- Create: `herdr-plugins/peek/Cargo.toml`, `herdr-plugins/peek/src/{main.rs,lib.rs,target.rs,resolve.rs,state.rs,herdr.rs,link.rs,page.rs,script.rs,kitty.rs,term.rs}`, `herdr-plugins/peek/src/fetch/{mod.rs,jira.rs,confluence.rs,github.rs,cache.rs}`, `herdr-plugins/peek/src/mac/{mod.rs,render.rs,viewer.rs,watch.rs,keychain.rs,clipboard.rs}`, `herdr-plugins/peek/bin/peek`, `herdr-plugins/peek/.gitignore` (`target/`)
- Modify: `scripts/check.sh` (`check_unit`)
- Test: `herdr-plugins/peek/tests/skeleton.rs`

**Interfaces (Produces — every later task codes against these; bodies are stubs until their task):**

```rust
// target.rs
pub enum Target { Jira { site: String, key: String }, Confluence { site: String, page_id: Option<String>, url: String },
                  GithubPr { repo: String, number: u64 }, Path { text: String, line: Option<u32> } }
impl Target { pub fn url(&self) -> Option<String> }
pub fn classify(text: &str) -> Target;
// resolve.rs
pub struct Context { pub cwd: PathBuf, pub session_id: Option<String>, pub home: PathBuf, pub tmp_root: PathBuf, pub projects_root: PathBuf }
pub fn normalize(text: &str) -> String;
pub fn candidates(text: &str, ctx: &Context) -> Vec<PathBuf>;          // most recent in the transcript first
// state.rs  (serde JSON, written atomically)
pub enum Mode { Rendered, Source }
pub struct Item { pub label: String, pub path: Option<PathBuf>, pub url: Option<String>, pub line: Option<u32> }
pub struct ViewState { pub seq: u128, pub items: Vec<Item>, pub mode: Mode, pub command: Option<String> }
pub fn state_dir() -> PathBuf;
pub fn read_state(source: &str) -> Option<ViewState>;
pub fn write_state(source: &str, st: &ViewState) -> io::Result<()>;
pub fn viewer_of(source: &str) -> Option<String>;
pub fn set_viewer(source: &str, pane: &str) -> io::Result<()>;
pub fn source_of_viewer(pane: &str) -> Option<String>;
pub fn project_name(dir: &Path) -> String;                              // every char outside [A-Za-z0-9] becomes '-'
pub fn session_dir(project: &str, session: &str) -> io::Result<PathBuf>;
pub fn zoom() -> u32;                                                    // 50..=200, default 100
pub fn set_zoom(percent: u32) -> io::Result<()>;
// herdr.rs
pub struct PaneInfo { pub pane_id: String, pub cwd: PathBuf, pub foreground_cwd: Option<PathBuf>, pub session_id: Option<String> }
pub fn pane_get(pane: &str) -> io::Result<PaneInfo>;
pub fn pane_ids() -> io::Result<Vec<String>>;
pub fn open_viewer(source: &str) -> io::Result<String>;                 // new pane id
pub fn notify(body: &str);
// link.rs
pub fn run_link(clicked: &str, pane: &str) -> io::Result<()>;           // `peek link`
pub fn run_action(name: &str, pane: &str) -> io::Result<()>;           // `peek action <name>`
pub const ACTIONS: [&str; 9] = ["toggle", "reload", "find", "zoom-in", "zoom-out", "zoom-reset", "screenshot", "browser", "back"];
// fetch/mod.rs
pub struct Fetched { pub title: String, pub html: String, pub url: String, pub fetched_at: String }
pub enum FetchError { NoToken { hint: String }, Http { status: u16, url: String }, Timeout, Other(String) }
pub trait TokenStore { fn get(&self, key: &str) -> Option<String>; fn set(&self, key: &str, value: &str) -> io::Result<()>; }
pub struct Endpoints { pub atlassian_base: Option<String>, pub github_api: String, pub timeout: Duration }
pub fn fetch(target: &Target, tokens: &dyn TokenStore, cache: &Path, fresh: bool, ep: &Endpoints) -> Result<Fetched, FetchError>;
pub fn error_page(err: &FetchError, target: &Target) -> Fetched;
pub fn run_auth(args: &[String], tokens: &dyn TokenStore) -> io::Result<()>;   // `peek auth atlassian <site>` | `peek auth github`
// page.rs
pub enum Doc { File(PathBuf), Fetched(Fetched) }
pub enum FileKind { Markdown, Source, Image, Svg, Html, Text }
pub struct PageOptions { pub dark: bool, pub font_px: f32, pub mode: Mode, pub line: Option<u32> }
pub fn kind_of(path: &Path) -> FileKind;
pub fn build(doc: &Doc, opts: &PageOptions) -> io::Result<String>;              // the page the viewer loads
pub fn browser_page(doc: &Doc, opts: &PageOptions) -> io::Result<String>;       // absolute file:// references
pub fn page_url(path: &Path, marker: u64) -> String;                              // file:// URL, percent-encoded, ?peek=<marker>
// script.rs  (strings for evaluateJavaScript; each evaluates to a JSON string)
pub struct FindQuery { pub text: String, pub case: bool, pub word: bool, pub regex: bool }
pub fn find(q: &FindQuery, index: i64) -> String;   // [count, index, y]; no match [0,0,-1]; bad regex [-1,0,-1]
pub fn find_clear() -> String;
pub fn hit(x_css: f64, y_css: f64) -> String;       // href of the link under the viewport point, or null
pub fn anchor() -> String;                          // [element index, offset] of the element at the viewport top
pub fn restore(anchor_json: &str) -> String;        // y that puts that element back at the top
pub fn ready(marker: u64) -> String;                // [is current and readyState complete, scrollHeight, top hint]
pub fn images_pending() -> String;                  // count of images not complete
// kitty.rs
pub struct Geometry { pub cols: u16, pub rows: u16, pub cell_w: u32, pub cell_h: u32 }
pub const TILE_BUDGET: usize = 12 * 1024 * 1024;
pub fn tile_rows(g: &Geometry, budget: usize) -> u32;
pub struct Placement { pub image: u32, pub src_y: u32, pub src_h: u32, pub row: u16 }
pub fn layout(view_top_row: u64, view_rows: u32, tile_rows: u32, first_screen_row: u16, generation: u32) -> Vec<(u64, Placement)>;
pub fn image_id(generation: u32, tile: u64) -> u32;
pub fn transmit_shm(image: u32, shm_name: &str, w: u32, h: u32) -> String;
pub fn place(p: &Placement, width_px: u32) -> String;
pub fn unplace(image: u32) -> String;     // remove placements, keep data
pub fn delete_image(image: u32) -> String; // free data
pub fn delete_all() -> String;
// term.rs
pub enum Key { Char(char), Up, Down, PageUp, PageDown, Home, End, Backspace, Esc, Enter, Tab, Alt(char) }
pub enum MouseKind { Press, Release, Move, WheelUp, WheelDown }
pub struct Mouse { pub kind: MouseKind, pub button: u8, pub x_px: u32, pub y_px: u32 }
pub enum Input { Key(Key), Mouse(Mouse), Reply(String) }
pub fn parse(buf: &[u8]) -> (Vec<Input>, usize);   // consumed bytes; a partial sequence stays for the next read
pub const MOUSE_ON: &str = "\x1b[?1000h\x1b[?1003h\x1b[?1006h\x1b[?1016h";
pub const MOUSE_OFF: &str = "\x1b[?1016l\x1b[?1006l\x1b[?1003l\x1b[?1000l";
pub fn geometry() -> kitty::Geometry;              // TIOCGWINSZ; no pixels → 8 x 18 px cells
pub struct BarItem { pub label: &'static str, pub key: &'static str, pub action: &'static str }
pub fn bar_items() -> Vec<BarItem>;
pub fn render_bar(title: &str, zoom: u32, cols: u16, hover: Option<usize>) -> (String, Vec<(u16, u16)>); // row-1 text, column range per item
pub fn render_find(q: &script::FindQuery, count: i64, index: i64, cols: u16) -> String;
// mac/  (cfg macOS)
pub fn mac::viewer::run(source: &str) -> io::Result<()>;   // `peek viewer`
pub struct mac::keychain::Keychain;                          // impl fetch::TokenStore, service "peek"
pub fn mac::clipboard::copy_png(path: &Path) -> io::Result<()>;
pub fn mac::watch::watch(path: &Path, on_change: impl Fn() + Send + 'static) -> io::Result<mac::watch::Watcher>;
```

- [ ] **Step 1: Write `tests/skeleton.rs`**: `fn every_action_has_a_bar_item_or_key()` asserts each of `link::ACTIONS` is the `action` of a `term::bar_items()` entry or one of `toggle`, `find`, `back`; `fn binary_prints_usage()` runs `env!("CARGO_BIN_EXE_peek")` with no arguments and asserts exit code 2 and `Usage: peek` on stderr.
- [ ] **Step 2: Run `cargo test` in `herdr-plugins/peek`.** Expected: FAIL (no crate).
- [ ] **Step 3: Create the crate.** `Cargo.toml` with every dependency above (macOS ones under `[target.'cfg(target_os = "macos")'.dependencies]`, `notify` with its default FSEvents backend), `[profile.release] lto = true, strip = true`. Stub bodies return empty values or `Err(io::ErrorKind::Unsupported)`; `term::bar_items()` and `link::ACTIONS` are real. `main.rs` dispatches `link`, `action <name>`, `viewer`, `auth ...`; anything else prints `Usage: peek link | action <name> | viewer | auth atlassian <site> | auth github` and exits 2.
- [ ] **Step 4: `bin/peek` launcher** (sh): `exec "$(dirname "$0")/../target/release/peek" "$@"` if it exists, else print `peek is not built: run cargo build --release in <plugin dir>` and exit 1.
- [ ] **Step 5: `scripts/check.sh` `check_unit`**: for each `herdr-plugins/*/` with a `Cargo.toml`, run `cargo test --quiet` in it (fail the check on failure); keep the Python unittest run for units that have `tests/*.py`.
- [ ] **Step 6: Verify.** `cargo test` passes; `scripts/check.sh` prints `all passed`.
- [ ] **Step 7: Commit** `feat(peek): Rust crate skeleton with fixed module interfaces`.

### Task 2: Link handling — classify, resolve, state, herdr, `peek link`/`peek action` (worker)

**Files:** Modify `src/target.rs`, `src/resolve.rs`, `src/state.rs`, `src/herdr.rs`, `src/link.rs`. Test: `tests/resolve.rs`, `tests/link.rs` (a fake herdr script under `tests/fixtures/` recording calls, set through `PEEK_HERDR`).

**Interfaces:** Consumes Task 1 signatures. Produces their real behaviour; reference: `scripts/targets.py`, `scripts/resolve.py`, `scripts/peek.py` (`cmd_link`, `cmd_toggle`, `show`, `source_lock`), and the spec's "Path resolution".

- [ ] **Step 1: Port the Python cases as failing tests.** `tests/resolve.rs`: `absolute_and_home`, `relative_to_cwd`, `scratchpad`, `transcript_suffix`, `git_suffix`, `dedupe_same_file`, `ambiguous_order`, `no_session`, `resolve_any_extension`, `normalize_suffixes`, plus `resolves_path_with_space_and_korean`. `tests/link.rs`: `click_opens_viewer`, `click_outside_herdr_does_nothing`, `reuses_live_viewer`, `reopens_when_viewer_gone`, `concurrent_clicks_open_one_viewer`, `link_not_found_notifies`, `link_resolves_relative`, `link_url_item` (Jira, Confluence, PR become one `Item` with `url`), `link_other_web_url_is_not_resolved`, `link_source_line`, `action_from_viewer_pane` (writes `command` to the viewer's source state with a new `seq`), `link_ambiguous_writes_all`, `session_dir_is_private` (mode 0700; a pre-made symlink in its place is refused), `project_name_matches_claude` (`/Users/a/src/x.y` → `-Users-a-src-x-y`).
- [ ] **Step 2: Run** `cargo test --test resolve --test link`. Expected: FAIL.
- [ ] **Step 3: Implement** the five modules. `herdr.rs` calls `<herdr> pane get <id>`, `pane list`, `plugin pane open --plugin nyjin.peek --entrypoint viewer --placement split --target-pane <source> --direction right --no-focus --env PEEK_SOURCE=<source>`, `notification` as the Python did; the source lock is an `O_EXCL` file in the state folder.
- [ ] **Step 4: Run** `cargo test`. Expected: PASS. Then `scripts/check.sh`.
- [ ] **Step 5: Commit** `feat(peek): link handling in Rust`.

### Task 3: Pages — markdown, source, images, HTML, scripts (worker)

**Files:** Modify `src/page.rs`, `src/script.rs`. Test: `tests/page.rs`, `tests/script.rs`, fixtures under `tests/fixtures/`.

**Interfaces:** Consumes `state::Mode`, `fetch::Fetched` (struct only). Produces `page::*`, `script::*` as declared. Reference: `evals/spike/rust/src/bin/mdhtml.rs`, `srchtml.rs`, and the `find` script in `evals/spike/rust/src/main.rs`.

- [ ] **Step 1: Failing tests.** `tests/page.rs`: `markdown_page_has_csp_and_no_script_tag_of_ours` (the exact CSP string; the template adds no `<script>`), `raw_html_is_kept_but_inert` (a `<script>` in markdown is in the page text; CSP present), `find_styles_in_template` (`::highlight(peek-find)` and `::highlight(peek-cur)`), `relative_image_uses_document_base` (`<base href="file:///…/doc-folder/">`), `source_page_marks_line` (`id="L120" class="hit"`), `source_page_caps_highlighting` (60,000 lines: rows exist for all, highlight spans stop at 20,000, the note `Highlighting stops at line 20,000` is present), `invalid_utf8_is_shown_lossily`, `theme_follows_flag` (Mocha `#1e1e2e` when dark, Latte `#eff1f5` when light), `font_size_from_options`, `image_and_svg_pages`, `page_file_url_is_encoded` (space and Korean in the path; `?peek=7`), `browser_page_uses_absolute_urls`, `fetched_doc_page_shows_title_and_fetch_time`, `source_mode_shows_markdown_as_source`. `tests/script.rs`: `find_escapes_query` (quotes and backslashes in the text stay literal), `find_word_and_case_flags`, `find_regex_flag_and_bad_regex_reply`, `hit_returns_closest_anchor_href`, `ready_checks_marker_and_ready_state`.
- [ ] **Step 2: Run** `cargo test --test page --test script`. Expected: FAIL.
- [ ] **Step 3: Implement.** Markdown with `ENABLE_TABLES | ENABLE_STRIKETHROUGH | ENABLE_TASKLISTS | ENABLE_FOOTNOTES`. Source with syntect's default (onig) syntax set, matched by file name then extension, plain text otherwise. Themes: Catppuccin Mocha and Latte colour sets from the spike template. The find script uses the CSS Custom Highlight API over text nodes (`TreeWalker`), whole word as a Unicode-aware boundary, regex through `new RegExp(text, flags)` inside `try`.
- [ ] **Step 4: Run** `cargo test`. Expected: PASS. Then `scripts/check.sh`.
- [ ] **Step 5: Commit** `feat(peek): page building and page scripts`.

### Task 4: Jira, Confluence, GitHub PR through REST; tokens (worker)

**Files:** Modify `src/fetch/{mod.rs,jira.rs,confluence.rs,github.rs,cache.rs}`, `src/mac/keychain.rs`. Test: `tests/fetch.rs` with a `tiny_http` fake server.

**Interfaces:** Consumes `target::Target`. Produces `fetch::*` and `mac::keychain::Keychain`. Token keys: `atlassian:<host>` → `<email>:<api token>` (Basic), `github` → token (Bearer).

- [ ] **Step 1: Failing tests** against a local server (`Endpoints { atlassian_base: Some(<server>), github_api: <server>, timeout: 500 ms }`, an in-memory `TokenStore`): `jira_requests_rendered_fields` (path `/rest/api/3/issue/KEY`, query has `expand=renderedFields` and `fields=summary,status,assignee,description,comment`, header `Authorization: Basic …`; page holds the summary, status, assignee, rendered description and comments), `confluence_requests_view_body` (`/wiki/api/v2/pages/<id>?body-format=view`), `confluence_without_page_id_is_an_error_page`, `github_requests_html_bodies` (`Accept: application/vnd.github.html+json`; PR, issue comments and review comments), `attachments_are_downloaded_with_the_token` (an `<img src="/rest/api/3/attachment/content/1">` becomes a local `file://` under the cache), `cache_is_used_unless_fresh`, `no_token_points_to_peek_auth` (hint `peek auth atlassian <site>` / `peek auth github`), `unauthorized_points_to_peek_auth` (401/403), `not_found_page`, `timeout_gives_error_page`, `auth_reads_secret_from_stdin`.
- [ ] **Step 2: Run** `cargo test --test fetch`. Expected: FAIL.
- [ ] **Step 3: Implement** with `ureq` (per-request timeout from `Endpoints`); cache file name is the SHA-256 of the URL under `~/.cache/peek/links/`, with the fetch time; `Keychain` uses `security-framework` generic passwords, service `peek`, account = key; `peek auth` prompts on stderr and reads the secret from stdin without echo when stdin is a terminal.
- [ ] **Step 4: Run** `cargo test`. Expected: PASS. Then `scripts/check.sh`.
- [ ] **Step 5: Commit** `feat(peek): fetch Jira, Confluence and PR pages through their APIs`.

### Task 5: Viewer core — renderer, Kitty tiles, input, resize (this session, sequential)

**Files:** Modify `src/kitty.rs`, `src/term.rs`, `src/mac/render.rs`, `src/mac/viewer.rs`. Test: `tests/kitty.rs`, `tests/term.rs`; by hand in a herdr 0.9.5 session with `evals/spike/tools/latency2`.

**Interfaces:** Consumes Tasks 1-3 (`page::build`, `script::ready/anchor/restore/images_pending`). Produces `mac::viewer::run`, `mac::render::Renderer { new, load, resize, capture, eval, set_zoom }`.

Coordinates: the document is measured in terminal rows (device px / `cell_h`); the view top and every tile boundary are whole rows, so placements need no pixel offsets. Row 1 is the bar; the page starts at row 2.

- [ ] **Step 1: Failing tests.** `tests/kitty.rs`: `tile_rows_from_budget` (176 x 51 cells of 17 x 37 px → `12 MiB / (176·17·4) / 37` rows), `tile_rows_at_least_one`, `layout_single_tile`, `layout_spans_two_tiles` (src rects inside each tile; rows continue), `source_rect_never_past_tile_end`, `image_ids_change_with_generation`, `transmit_shm_command` (exact `\x1b_Ga=t,i=…,f=32,s=…,v=…,t=s,S=…,q=2;<base64 name>\x1b\\`), `place_command` (cursor to the row, `a=p,i,p=1,x=0,y,w,h,C=1,q=2`). `tests/term.rs`: `parses_keys_and_arrows`, `parses_sgr_pixel_mouse` (press, release, move with button 35, wheel 64/65), `keeps_partial_sequence`, `parses_kitty_reply`, `geometry_without_pixels_falls_back`, `bar_layout_and_hover`.
- [ ] **Step 2: Run** `cargo test --test kitty --test term`. Expected: FAIL.
- [ ] **Step 3: Implement `kitty.rs` and `term.rs`;** run the tests to PASS.
- [ ] **Step 4: Implement `render.rs`** from the spike (`evals/spike/rust/src/main.rs`): page scripts off, readiness by `script::ready`, capture of a CSS-px band into a shared-memory RGBA buffer (`CGImageAlphaInfo::PremultipliedLast`), resize that waits until `innerWidth` matches, zoom by `setPageZoom`.
- [ ] **Step 5: Implement `viewer.rs`:** raw mode, alternate screen, `MOUSE_ON`; `Loading <name> ...` first; `PageOptions.dark` from the system appearance, `font_px` from the cell height in CSS px (tune by eye against the terminal's text); state-file changes load the item (a selection list as terminal text for several items); keys and wheel scroll by rows; tiles captured on demand and around the view when idle (keep the tiles within two screens, delete the rest); resize keeps the anchor; input before readiness waits; recapture once `images_pending` reaches 0; `q` restores the terminal and deletes all images.
- [ ] **Step 6: Verify in a herdr 0.9.5 session:** key-to-screen median within 15 ms of the `less` baseline on the same window; two viewers side by side; resize redraw; sharp text at native pixels. Save screenshots to `evals/screens/` and the numbers to `evals/results.md`.
- [ ] **Step 7: Commit** `feat(peek): WebKit viewer core with Kitty tiles`.

### Task 6: Viewer features (this session, after Tasks 2-5 are merged)

**Files:** Modify `src/mac/viewer.rs`, `src/term.rs` (find bar), `src/mac/watch.rs`, `src/mac/clipboard.rs`. Test: `tests/term.rs` (`render_find`), by hand in the 0.9.5 session.

**Interfaces:** Consumes everything above.

- [ ] **Step 1: Failing test** `render_find_shows_toggles_and_position` (`Aa`, `ab`, `.*` marked when on; `3/22`; `no matches`; `bad regex`). Run, FAIL; implement; PASS.
- [ ] **Step 2: Top bar:** hover shows the tooltip (`Reload (r)` …) on row 2 over the image; click runs the action; zoom shows the percentage.
- [ ] **Step 3: Find:** `/` opens the find row; typing searches; toggles by `Alt-c`, `Alt-w`, `Alt-r` and by clicking them; `Enter`/`n` next, `N` previous; `Esc` clears.
- [ ] **Step 4: Zoom** `+`/`-`/`0` in 10 % steps within 50-200, saved with `state::set_zoom`, anchor kept.
- [ ] **Step 5: Screenshot** `s`: PNG of the screen to `session_dir(..)/screenshots/<YYYYMMDD-HHMMSS>-<document>-L<line>.png` (session from `herdr::pane_get(source).session_id`, else `pane-<id>` with `:` replaced by `-`), copied with `clipboard::copy_png`, a herdr notification with the path.
- [ ] **Step 6: Open in browser** `o`: local document → `page::browser_page` to `session_dir(..)/browser/<document>.html`, then `open`; fetched view → `open <url>`.
- [ ] **Step 7: Links in the page:** click → `script::hit` → local file opens in the viewer with history (`h`/Backspace back); web address → `open`.
- [ ] **Step 8: Watch:** `watch::watch` on the shown file (FSEvents on its folder, filtered to the file), 300 ms debounce, reload with the anchor kept; a removed file shows `File was removed` in the bar and keeps the last frame.
- [ ] **Step 9: Web links:** an item with `url` → `fetch::fetch` with `Keychain`, errors through `fetch::error_page`; `r` fetches again (`fresh = true`).
- [ ] **Step 10: herdr actions** from the Claude pane reach the viewer through `ViewState.command`.
- [ ] **Step 10b: PDF:** load a PDF in the renderer and capture it; if it renders, add `FileKind::Pdf` handling and the `pdf` link pattern in Task 7, else record why in `evals/results.md`.
- [ ] **Step 11: Verify** each feature by hand in the 0.9.5 session (screenshots to `evals/screens/`), then `scripts/check.sh`.
- [ ] **Step 12: Commit** `feat(peek): find, zoom, screenshot, browser, links, file watch, web links`.

### Task 7: Switch over and documents (this session)

**Files:** Modify `herdr-plugins/peek/herdr-plugin.toml`, `README.md`, `README.ko.md`, the root `README.md`/`README.ko.md` peek rows, `docs/superpowers/specs/2026-11-15-peek-webkit-viewer-design.md` ("What shipped"). Delete `herdr-plugins/peek/scripts/`, `herdr-plugins/peek/tests/*.py`.

- [ ] **Step 1: Manifest:** every pane, action and link handler runs `bin/peek …`; version `0.5.0`; description without glow/bat; add link handlers for images (`png jpe?g gif webp svg`) and `html?`; one action per `link::ACTIONS` entry.
- [ ] **Step 2: Remove** the Python scripts and tests; drop the Python run for peek from `check_unit` if nothing else needs it.
- [ ] **Step 3: READMEs** (English and Korean): what it shows, requirements (macOS, herdr ≥ 0.9.3 with Kitty graphics, build with `cargo build --release`), keys, top bar, `peek auth`, the `/tmp` layout, the herdr action key binding example.
- [ ] **Step 4: Spec "What shipped"** with any differences from the design and the final numbers from `evals/results.md`.
- [ ] **Step 5: Verify** `scripts/check.sh` passes; a click in the 0.9.5 session opens a file through the manifest path.
- [ ] **Step 6: Commit** `feat(peek): switch to the Rust WebKit viewer; drop glow, bat and Python`.
