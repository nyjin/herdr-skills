//! The viewer pane (`peek viewer`): follows the source pane's state file, builds each item's page, renders it in
//! the hidden WebKit view and shows it as Kitty tiles below a one-row top bar. Everything runs on the main queue;
//! an input thread and a state thread only post work to it.
use super::render::{after, Renderer};
use crate::kitty::{self, Geometry, TILE_BUDGET};
use crate::page::{self, Doc, PageOptions};
use crate::state::{self, Item, Mode, ViewState};
use crate::fetch::{self, Endpoints};
use crate::script::FindQuery;
use crate::term::{self, Input, Key, MouseKind};
use crate::{herdr, script, target};
use dispatch2::DispatchQueue;
use objc2::MainThreadMarker;
use objc2_app_kit::{NSApplication, NSApplicationActivationPolicy, NSScreen};
use std::cell::RefCell;
use std::collections::HashSet;
use std::fs::File;
use std::io::{self, Read, Write};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

const BAR_ROW: u16 = 1;
const FIRST_ROW: u16 = 2;
const NOTCH: i64 = 3;
const ZOOM_STEP: u32 = 10;

/// The find row, while open. Typing always goes into its query, as in an editor's find field: Enter and Down step
/// to the next match, Shift+Enter and Up to the previous one, Esc closes.
struct Find {
    q: FindQuery,
    count: i64,
    index: i64,
}

struct Viewer {
    r: Renderer,
    g: Geometry,
    dpr: f64,
    tile_rows: u32,
    css_w: f64,
    doc_h: f64,
    view_top: u64,
    generation: u32,
    marker: u64,
    ready: HashSet<u64>,
    placed: HashSet<u32>,
    busy: bool,
    dirty: bool,
    loaded: bool,
    item: Option<Item>,
    choices: Vec<Item>,
    mode: Mode,
    zoom: u32,
    dark: bool,
    /// `/tmp/peek-<uid>/<project>/<session>`: pages, browser copies and screenshots live under it.
    base: PathBuf,
    page_file: Option<PathBuf>,
    find: Option<Find>,
    history: Vec<(Item, Mode, u64)>,
    keep_top: Option<u64>,
    watcher: Option<super::watch::Watcher>,
    loaded_at: f64,
    seq: u128,
    /// The item under the pointer on row 1, an index into whichever row shows (bar, zoom row or find row).
    hover: Option<usize>,
    /// Column ranges of the items row 1 shows now.
    bar: Vec<(u16, u16)>,
    /// The zoom row (`…`) shows in place of the bar.
    menu: bool,
    /// A toast on row 1 (text, id) until its time is up or row 1 is clicked.
    toast: Option<(String, u64)>,
    /// Where the terminal cursor stands while the find field takes typing.
    caret: Option<u16>,
    title: String,
    shm_seq: u64,
    log: Option<File>,
}

thread_local! { static V: RefCell<Option<Viewer>> = const { RefCell::new(None) }; }
static START: OnceLock<Instant> = OnceLock::new();
static ORIG: OnceLock<libc::termios> = OnceLock::new();
static WINCH: AtomicBool = AtomicBool::new(false);

fn with<R>(f: impl FnOnce(&mut Viewer) -> R) -> R {
    V.with(|v| f(v.borrow_mut().as_mut().expect("viewer state")))
}

fn now_ms() -> f64 {
    START.get().map(|s| s.elapsed().as_secs_f64() * 1000.0).unwrap_or(0.0)
}

fn out(s: &str) {
    let mut o = io::stdout().lock();
    let _ = o.write_all(s.as_bytes());
    let _ = o.flush();
}

/// One JSON line to the viewer log (`$PEEK_LOG` or the session folder's `viewer.log`).
fn log(mut v: serde_json::Value) {
    v["t"] = serde_json::json!((now_ms() * 10.0).round() / 10.0);
    with(|s| {
        if let Some(f) = s.log.as_mut() {
            let _ = writeln!(f, "{v}");
        }
    });
}

/// `source` is the Claude pane this viewer serves; `path`, when given, is shown directly (for trying the viewer
/// outside the link flow).
pub fn run(source: &str, path: Option<&Path>) -> io::Result<()> {
    START.get_or_init(Instant::now);
    let mtm = MainThreadMarker::new().ok_or_else(|| io::Error::other("the viewer must run on the main thread"))?;
    let app = NSApplication::sharedApplication(mtm);
    app.setActivationPolicy(NSApplicationActivationPolicy::Accessory);
    let dpr = NSScreen::mainScreen(mtm).map(|s| s.backingScaleFactor()).unwrap_or(2.0);
    let dark = app.effectiveAppearance().name().to_string().contains("Dark");
    let base = session_base(source);
    // Timings and errors go to `$PEEK_LOG`, else to `viewer.log` in the session folder (started fresh each run).
    let log = match std::env::var_os("PEEK_LOG") {
        Some(p) => File::options().create(true).append(true).open(p).ok(),
        None => File::create(base.join("viewer.log")).ok(),
    };
    V.with(|v| {
        *v.borrow_mut() = Some(Viewer {
            r: Renderer::new(mtm),
            g: term::geometry(),
            dpr,
            tile_rows: 1,
            css_w: 0.0,
            doc_h: 0.0,
            view_top: 0,
            generation: 0,
            marker: 0,
            ready: HashSet::new(),
            placed: HashSet::new(),
            busy: false,
            dirty: false,
            loaded: false,
            item: None,
            choices: Vec::new(),
            mode: Mode::Rendered,
            zoom: state::zoom(),
            dark,
            base,
            page_file: None,
            find: None,
            history: Vec::new(),
            keep_top: None,
            watcher: None,
            loaded_at: 0.0,
            seq: 0,
            hover: None,
            bar: Vec::new(),
            menu: false,
            toast: None,
            caret: None,
            title: "peek".into(),
            shm_seq: 0,
            log,
        })
    });
    terminal_on();
    apply_geometry();
    draw_bar();
    let zoom = with(|v| v.zoom);
    with(|v| v.r.set_zoom(zoom));
    match path {
        Some(p) => open(Item { label: p.display().to_string(), path: Some(p.to_path_buf()), url: None, line: None }, Mode::Rendered, None),
        None => {
            out("\x1b[3;3HWaiting for a click in the Claude pane ...");
            follow_state(source.to_string());
        }
    }
    read_input();
    app.run();
    Ok(())
}

/// The session folder (`/tmp/peek-<uid>/<project>/<session>`) for the source pane, or a private folder under the
/// temp dir when it cannot be made; `pages/`, `browser/` and `screenshots/` are created in it.
fn session_base(source: &str) -> PathBuf {
    let dir = herdr::pane_get(source).ok().and_then(|p| {
        let project = state::project_name(p.foreground_cwd.as_deref().unwrap_or(&p.cwd));
        let session = p.session_id.unwrap_or_else(|| format!("pane-{}", source.replace(':', "-")));
        state::session_dir(&project, &session).ok()
    });
    let dir = dir.unwrap_or_else(|| std::env::temp_dir().join(format!("peek-{}", std::process::id())));
    for sub in ["pages", "browser", "screenshots"] {
        let _ = std::fs::create_dir_all(dir.join(sub));
    }
    dir
}

fn terminal_on() {
    unsafe {
        let mut t: libc::termios = std::mem::zeroed();
        if libc::tcgetattr(0, &mut t) == 0 {
            let _ = ORIG.set(t);
            libc::cfmakeraw(&mut t);
            libc::tcsetattr(0, libc::TCSANOW, &t);
        }
        libc::signal(libc::SIGWINCH, on_winch as *const () as libc::sighandler_t);
    }
    out(&format!("\x1b[?1049h\x1b[?25l\x1b[2J{}", term::MOUSE_ON));
}

fn quit() -> ! {
    out(&format!("{}{}\x1b[0 q\x1b[?25h\x1b[?1049l", kitty::delete_all(), term::MOUSE_OFF));
    if let Some(t) = ORIG.get() {
        unsafe { libc::tcsetattr(0, libc::TCSANOW, t) };
    }
    std::process::exit(0)
}

extern "C" fn on_winch(_: libc::c_int) {
    WINCH.store(true, Ordering::SeqCst);
}

/// Re-measure the pane and size the web view: as wide as the pane, as tall as one tile.
fn apply_geometry() {
    let g = term::geometry();
    with(|v| {
        v.g = g;
        v.tile_rows = kitty::tile_rows(&g, TILE_BUDGET);
        v.css_w = (g.cols as f64 * g.cell_w as f64 / v.dpr).floor();
        v.r.set_frame(v.css_w, v.tile_rows as f64 * g.cell_h as f64 / v.dpr);
    });
    log(serde_json::json!({"ev": "measure", "cols": g.cols, "rows": g.rows, "cell": [g.cell_w, g.cell_h]}));
}

/// Row 1: the find row while finding, a toast while one shows, the zoom row while `…` is open, else the bar; the
/// cursor stands in the find field or is hidden.
fn draw_bar() {
    let (text, caret) = with(|v| {
        let (text, ranges, caret) = if let Some(f) = &v.find {
            let row = term::render_find(&f.q, f.count, f.index, v.g.cols, v.hover);
            (row.text, row.buttons, row.caret)
        } else if let Some((text, _)) = &v.toast {
            (term::render_toast(text, v.g.cols), Vec::new(), None)
        } else if v.menu {
            let (text, ranges) = term::render_more(&v.title, v.zoom, v.g.cols, v.hover);
            (text, ranges, None)
        } else {
            let (text, ranges) = term::render_bar(&v.title, v.mode == Mode::Source, v.g.cols, v.hover);
            (text, ranges, None)
        };
        v.bar = ranges;
        v.caret = caret;
        (text, caret)
    });
    out(&format!("{text}{}", term::caret(caret)));
}

fn doc_rows(v: &Viewer) -> u64 {
    (v.doc_h * v.dpr / v.g.cell_h as f64).ceil() as u64
}

fn view_rows(v: &Viewer) -> u32 {
    v.g.rows.saturating_sub(FIRST_ROW - 1).max(1) as u32
}

fn page_options(v: &Viewer, line: Option<u32>) -> PageOptions {
    // Text about as tall as the terminal's: a cell is about 1.35 times the font size.
    let font_px = (v.g.cell_h as f64 / v.dpr / 1.35).clamp(10.0, 28.0) as f32;
    PageOptions { dark: v.dark, font_px, mode: v.mode, line }
}

fn background(v: &Viewer) -> [u8; 3] {
    if v.dark { [0x1e, 0x1e, 0x2e] } else { [0xef, 0xf1, 0xf5] }
}

/// Clear the page area and say something there (loading, errors, the choice list).
fn message(lines: &[String]) {
    let mut s = format!("{}\x1b[{FIRST_ROW};1H\x1b[J", kitty::delete_all());
    for (n, l) in lines.iter().enumerate() {
        s.push_str(&format!("\x1b[{};3H{l}", FIRST_ROW as usize + 1 + n));
    }
    with(|v| v.placed.clear());
    out(&s);
}

/// Show `item`: build its page (fetching a link first), load it, draw it. `keep_top` puts the view back where it
/// was (reload, back, file changes).
fn open(item: Item, mode: Mode, keep_top: Option<u64>) {
    open_when_measured(item, mode, keep_top, 0);
}

/// The page's font size comes from the cell size, which herdr reports a moment after the pane starts: wait for
/// it (up to a second) before the first page is built.
fn open_when_measured(item: Item, mode: Mode, keep_top: Option<u64>, tries: u32) {
    if !term::pixel_size_known() && tries < 20 {
        return after(50, move || open_when_measured(item, mode, keep_top, tries + 1));
    }
    // The size may have arrived since the viewer measured at start: measure again before building the page.
    if with(|v| v.g) != term::geometry() {
        apply_geometry();
        draw_bar();
    }
    open_now(item, mode, keep_top);
}

fn open_now(item: Item, mode: Mode, keep_top: Option<u64>) {
    let name = Path::new(&item.label).file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or(item.label.clone());
    with(|v| {
        v.loaded = false;
        v.mode = mode;
        v.title = name.clone();
        v.choices.clear();
        v.find = None;
        v.keep_top = keep_top;
        v.item = Some(item.clone());
        v.watcher = None;
    });
    draw_bar();
    if keep_top.is_none() {
        message(&[format!("Loading {name} ...")]);
    }
    if let Some(path) = item.path.clone() {
        let opts = with(|v| page_options(v, item.line));
        let built = page::build(&Doc::File(path.clone()), &opts);
        let watched = path.clone();
        let w = super::watch::watch(&path, move || {
            let p = watched.clone();
            DispatchQueue::main().exec_async(move || file_changed(&p));
        });
        with(|v| v.watcher = w.ok());
        return match built {
            Ok(html) => load_page(html),
            Err(e) => message(&[format!("Cannot show {}: {e}", path.display())]),
        };
    }
    let Some(url) = item.url.clone() else { return message(&["Nothing to show".into()]) };
    fetch_link(url, false);
}

/// Fetch a Jira, Confluence or PR link off the main thread, then show it (an error page when it fails).
fn fetch_link(url: String, fresh: bool) {
    let cache = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_default().join(".cache/peek/links");
    let _ = std::fs::create_dir_all(&cache);
    std::thread::spawn(move || {
        let t = target::classify(&url);
        let fetched = match fetch::fetch(&t, &super::keychain::Keychain, &cache, fresh, &Endpoints::default()) {
            Ok(f) => f,
            Err(e) => fetch::error_page(&e, &t),
        };
        DispatchQueue::main().exec_async(move || {
            // the bar names the issue, page or PR rather than the last part of its address
            with(|v| v.title = fetched.title.clone());
            draw_bar();
            let opts = with(|v| page_options(v, None));
            match page::build(&Doc::Fetched(fetched), &opts) {
                Ok(html) => load_page(html),
                Err(e) => message(&[format!("Cannot show {url}: {e}")]),
            }
        });
    });
}

/// Write `html` as the next page file and load it.
fn load_page(html: String) {
    let (pages, marker) = with(|v| {
        v.marker += 1;
        (v.base.join("pages"), v.marker)
    });
    let file = pages.join(format!("{marker}.html"));
    if let Err(e) = std::fs::write(&file, html) {
        return message(&[format!("Cannot write {}: {e}", file.display())]);
    }
    if let Some(old) = with(|v| v.page_file.replace(file.clone())) {
        let _ = std::fs::remove_file(old);
    }
    let t0 = now_ms();
    let r = with(|v| v.r.clone());
    r.load(&page::page_url(&file, marker), marker, move |res| match res {
        Ok(info) => {
            if with(|v| v.marker != marker) {
                return;
            }
            with(|v| {
                v.doc_h = info.doc_h;
                v.loaded = true;
                v.loaded_at = now_ms();
                v.generation += 1;
                v.ready.clear();
                v.view_top = v.keep_top.take().unwrap_or((info.top_hint * v.dpr / v.g.cell_h as f64) as u64);
            });
            log(serde_json::json!({"ev": "loaded", "ms": now_ms() - t0, "doc_h": info.doc_h}));
            message(&[]);
            draw(now_ms());
            watch_images(marker, 0, false);
        }
        Err(e) => message(&[e]),
    });
}

/// The shown file changed on disk: show it again where the reader was; a removed file keeps its last picture.
fn file_changed(path: &Path) {
    if with(|v| v.item.as_ref().and_then(|i| i.path.as_deref()) != Some(path)) {
        return;
    }
    if !path.exists() {
        with(|v| v.title = "File was removed".into());
        return draw_bar();
    }
    let (item, mode, top) = with(|v| (v.item.clone(), v.mode, v.view_top));
    if let Some(item) = item {
        open(item, mode, Some(top));
    }
}

/// Images that finish after the first capture: once none is pending, capture the tiles again.
fn watch_images(marker: u64, tries: u32, had_pending: bool) {
    if tries > 40 || with(|v| v.marker != marker) {
        return;
    }
    let r = with(|v| v.r.clone());
    r.eval(&script::images_pending(), move |s| {
        let pending: u64 = s.and_then(|s| s.trim().parse().ok()).unwrap_or(0);
        if pending > 0 {
            return after(250, move || watch_images(marker, tries + 1, true));
        }
        if had_pending && with(|v| v.marker == marker) {
            invalidate();
            draw(now_ms());
        }
    });
}

/// Drop every tile (new layout, new images); the screen keeps its picture until the next draw replaces it.
fn invalidate() {
    with(|v| {
        v.generation += 1;
        v.ready.clear();
    });
}

/// Put the view on screen, capturing missing tiles first. Requests while a capture runs are folded into one.
fn draw(t_key: f64) {
    let go = with(|v| {
        if !v.loaded || v.busy {
            v.dirty = true;
            return false;
        }
        let max_top = doc_rows(v).saturating_sub(view_rows(v) as u64);
        v.view_top = v.view_top.min(max_top);
        true
    });
    if !go {
        return;
    }
    let (lay, missing) = with(|v| {
        let rows = (view_rows(v) as u64).min(doc_rows(v).saturating_sub(v.view_top)).max(1) as u32;
        let lay = kitty::layout(v.view_top, rows, v.tile_rows, FIRST_ROW, v.generation);
        let missing = lay.iter().map(|(t, _)| *t).find(|t| !v.ready.contains(t));
        (lay, missing)
    });
    if let Some(tile) = missing {
        with(|v| v.busy = true);
        return capture(tile, move |_| {
            with(|v| v.busy = false);
            draw(t_key);
        });
    }
    let mut s = String::new();
    let (shown, captured) = with(|v| {
        let new: HashSet<u32> = lay.iter().map(|(_, p)| p.image).collect();
        for gone in v.placed.difference(&new) {
            s.push_str(&kitty::unplace(*gone));
        }
        let w = v.g.cols as u32 * v.g.cell_w;
        for (_, p) in &lay {
            s.push_str(&kitty::place(p, w, v.g.cell_h));
        }
        v.placed = new;
        // placing tiles moves the cursor: put it back in the find field (or keep it hidden)
        s.push_str(&term::caret(v.caret));
        (v.view_top, v.ready.len())
    });
    out(&s);
    log(serde_json::json!({"ev": "draw", "top": shown, "tiles": lay.len(), "ready": captured, "key_to_written": now_ms() - t_key}));
    let again = with(|v| std::mem::replace(&mut v.dirty, false));
    if again {
        after(0, move || draw(t_key));
    } else {
        after(40, prefetch);
    }
}

/// Capture tile `tile` of the current layout and transmit it; `done(ok)` afterwards.
fn capture(tile: u64, done: impl FnOnce(bool) + 'static) {
    let (r, generation, top_css, w, h, bg, name) = with(|v| {
        v.shm_seq += 1;
        (
            v.r.clone(),
            v.generation,
            tile as f64 * v.tile_rows as f64 * v.g.cell_h as f64 / v.dpr,
            v.g.cols as u32 * v.g.cell_w,
            v.tile_rows * v.g.cell_h,
            background(v),
            format!("/pk{}_{}", std::process::id(), v.shm_seq),
        )
    });
    let t0 = now_ms();
    r.capture(top_css, w, h, bg, name.clone(), move |res| {
        let current = with(|v| v.generation == generation);
        let ok = match res {
            Ok(()) if current => {
                out(&kitty::transmit_shm(kitty::image_id(generation, tile), &name, w, h));
                with(|v| v.ready.insert(tile));
                true
            }
            Ok(()) => {
                // A newer layout replaced this one while capturing: the terminal never reads it, so free it.
                if let Ok(c) = std::ffi::CString::new(name.clone()) {
                    unsafe { libc::shm_unlink(c.as_ptr()) };
                }
                false
            }
            Err(e) => {
                log(serde_json::json!({"ev": "error", "what": "capture", "error": e}));
                false
            }
        };
        log(serde_json::json!({"ev": "capture", "tile": tile, "ms": now_ms() - t0, "bytes": w as u64 * h as u64 * 4}));
        done(ok)
    });
}

/// While idle, capture the tiles around the view (a screen above, two below) and free the ones far away.
fn prefetch() {
    let todo = with(|v| {
        if v.busy || !v.loaded {
            return None;
        }
        let rows = view_rows(v) as u64;
        let t = v.tile_rows as u64;
        let first = v.view_top.saturating_sub(rows) / t;
        let last = (v.view_top + 3 * rows).min(doc_rows(v).max(1) - 1) / t;
        let far: Vec<u64> = v.ready.iter().copied().filter(|x| *x + 2 < first || *x > last + 2).collect();
        let mut s = String::new();
        for x in far {
            v.ready.remove(&x);
            s.push_str(&kitty::delete_image(kitty::image_id(v.generation, x)));
        }
        if !s.is_empty() {
            out(&s);
        }
        let below = (v.view_top / t..=last).find(|x| !v.ready.contains(x));
        below.or_else(|| (first..v.view_top / t).rev().find(|x| !v.ready.contains(x)))
    });
    if let Some(tile) = todo {
        with(|v| v.busy = true);
        capture(tile, |_| {
            with(|v| v.busy = false);
            let dirty = with(|v| std::mem::replace(&mut v.dirty, false));
            if dirty {
                draw(now_ms());
            } else {
                after(10, prefetch);
            }
        });
    }
}

fn scroll(rows: i64, t_key: f64) {
    with(|v| {
        let max_top = doc_rows(v).saturating_sub(view_rows(v) as u64) as i64;
        v.view_top = (v.view_top as i64 + rows).clamp(0, max_top.max(0)) as u64;
    });
    draw(t_key);
}

/// The pane changed size: keep the element at the top of the screen at the top.
fn resized() {
    let loaded = with(|v| v.loaded);
    let old = with(|v| (v.view_top, doc_rows(v)));
    if !loaded {
        apply_geometry();
        draw_bar();
        return;
    }
    let (r, top_css) = with(|v| (v.r.clone(), v.view_top as f64 * v.g.cell_h as f64 / v.dpr));
    let t0 = now_ms();
    r.eval(&format!("window.scrollTo(0, {top_css}); {}", script::anchor()), move |anchor| {
        apply_geometry();
        // with page zoom the page's own width is the frame width divided by the zoom
        let (r, inner) = with(|v| (v.r.clone(), (v.css_w * 100.0 / v.zoom as f64).round()));
        r.wait_width(inner, move |doc_h| {
            with(|v| v.doc_h = doc_h);
            let r = with(|v| v.r.clone());
            r.eval(&script::restore(anchor.as_deref().unwrap_or("null")), move |y| {
                with(|v| {
                    v.view_top = match y.and_then(|y| y.trim().parse::<f64>().ok()) {
                        Some(y) => (y * v.dpr / v.g.cell_h as f64).round() as u64,
                        None if old.1 > 0 => old.0 * doc_rows(v) / old.1,
                        None => 0,
                    };
                });
                invalidate();
                message(&[]);
                draw_bar();
                log(serde_json::json!({"ev": "relayout", "ms": now_ms() - t0}));
                draw(t0);
            });
        });
    });
}

fn act(action: &str) {
    let (item, mode, top) = with(|v| (v.item.clone(), v.mode, v.view_top));
    match action {
        "reload" => match item {
            Some(i) if i.url.is_some() && i.path.is_none() => {
                with(|v| v.keep_top = Some(top));
                fetch_link(i.url.unwrap(), true)
            }
            Some(i) => open(i, mode, Some(top)),
            None => {}
        },
        "toggle" => {
            if let Some(i) = item {
                open(i, if mode == Mode::Rendered { Mode::Source } else { Mode::Rendered }, None);
            }
        }
        "find" => {
            with(|v| {
                if v.find.is_none() {
                    v.find = Some(Find { q: FindQuery::default(), count: 0, index: 0 });
                    v.hover = None;
                }
            });
            draw_bar();
        }
        "more" => {
            with(|v| {
                v.menu = true;
                v.hover = None;
            });
            draw_bar();
        }
        "zoom-in" => zoom(|z| (z + ZOOM_STEP).min(200)),
        "zoom-out" => zoom(|z| z.saturating_sub(ZOOM_STEP).max(50)),
        "zoom-reset" => zoom(|_| 100),
        "screenshot" => screenshot(),
        "browser" => browser(),
        "back" => {
            if let Some((i, m, t)) = with(|v| v.history.pop()) {
                open(i, m, Some(t));
            }
        }
        _ => {}
    }
}

/// Run the find query again and move to the current match; highlights change the page, so tiles are recaptured.
fn run_find() {
    let Some((q, index)) = with(|v| v.find.as_ref().map(|f| (f.q.clone(), f.index))) else { return };
    let r = with(|v| v.r.clone());
    let t0 = now_ms();
    r.eval(&script::find(&q, index), move |s| {
        let v: serde_json::Value = s.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
        let (count, index, y) = (v[0].as_i64().unwrap_or(0), v[1].as_i64().unwrap_or(0), v[2].as_f64().unwrap_or(-1.0));
        with(|w| {
            if let Some(f) = w.find.as_mut() {
                f.count = count;
                f.index = index;
            }
            if y >= 0.0 {
                // the match a third of the way down the screen
                let row = (y * w.dpr / w.g.cell_h as f64) as u64;
                w.view_top = row.saturating_sub(view_rows(w) as u64 / 3);
            }
        });
        invalidate();
        draw_bar();
        draw(t0);
        // WebKit paints highlights set in the first half second after a load only later: capture again then.
        let (since, marker) = with(|w| (now_ms() - w.loaded_at, w.marker));
        if since < 700.0 {
            after((700.0 - since) as u64, move || {
                if with(|w| w.marker == marker && w.find.is_some()) {
                    invalidate();
                    draw(now_ms());
                }
            });
        }
    });
}

fn close_find() {
    with(|v| {
        v.find = None;
        v.hover = None;
    });
    draw_bar();
    let r = with(|v| v.r.clone());
    r.eval(&script::find_clear(), |_| {
        invalidate();
        draw_bar();
        draw(now_ms());
    });
}

/// Change the page zoom, keep the element at the top of the screen at the top, remember the zoom.
fn zoom(f: impl FnOnce(u32) -> u32) {
    let (old, new) = with(|v| (v.zoom, f(v.zoom)));
    if old == new || !with(|v| v.loaded) {
        return;
    }
    let _ = state::set_zoom(new);
    let (r, top_css) = with(|v| {
        v.zoom = new;
        (v.r.clone(), v.view_top as f64 * v.g.cell_h as f64 / v.dpr)
    });
    let t0 = now_ms();
    r.eval(&format!("window.scrollTo(0, {top_css}); {}", script::anchor()), move |anchor| {
        let (r, inner) = with(|v| (v.r.clone(), (v.css_w * 100.0 / new as f64).round()));
        r.set_zoom(new);
        r.wait_width(inner, move |doc_h| {
            with(|v| v.doc_h = doc_h);
            restore_and_draw(anchor, t0);
        });
    });
}

/// After a re-layout: put the anchored element back at the top, drop the tiles and draw.
fn restore_and_draw(anchor: Option<String>, t0: f64) {
    let r = with(|v| v.r.clone());
    r.eval(&script::restore(anchor.as_deref().unwrap_or("null")), move |y| {
        with(|v| {
            if let Some(y) = y.and_then(|y| y.trim().parse::<f64>().ok()) {
                v.view_top = (y * v.dpr / v.g.cell_h as f64).round() as u64;
            }
        });
        invalidate();
        message(&[]);
        draw_bar();
        log(serde_json::json!({"ev": "relayout", "ms": now_ms() - t0}));
        draw(t0);
    });
}

/// The screen as a PNG under `screenshots/`, copied to the clipboard; a notification says where it went.
fn screenshot() {
    if !with(|v| v.loaded) {
        return;
    }
    let (r, top_css, h_css, doc) = with(|v| {
        let doc = v.item.as_ref().map(|i| Path::new(&i.label).file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default()).unwrap_or_default();
        (v.r.clone(), v.view_top as f64 * v.g.cell_h as f64 / v.dpr, view_rows(v) as f64 * v.g.cell_h as f64 / v.dpr, doc)
    });
    let line_js = format!("window.scrollTo(0, {top_css}); (() => {{ const e = document.elementFromPoint(40, 4); const tr = e && e.closest('tr[id^=L]'); return JSON.stringify(tr ? tr.id.slice(1) : null); }})()");
    r.eval(&line_js, move |line| {
        let line = line.and_then(|l| serde_json::from_str::<Option<String>>(&l).ok()).flatten();
        let stamp = timestamp();
        let name = match line {
            Some(n) => format!("{stamp}-{doc}-L{n}.png"),
            None => format!("{stamp}-{doc}.png"),
        };
        let (r, path) = with(|v| (v.r.clone(), v.base.join("screenshots").join(name.replace('/', "_"))));
        let shown = path.clone();
        r.snapshot_png(top_css, h_css, path, move |res| match res {
            Ok(()) => {
                let copied = super::clipboard::copy_png(&shown).is_ok();
                let (head, tail) = ("\u{25cf} Screenshot saved to ", if copied { " \u{b7} copied to clipboard" } else { "" });
                let room = with(|v| v.g.cols as usize).saturating_sub(2 + term::display_width(head) + term::display_width(tail));
                toast(format!("{head}{}{tail}", term::shorten_path(&shown.to_string_lossy(), room)));
                log(serde_json::json!({"ev": "screenshot", "path": shown}));
            }
            Err(e) => toast(format!("\u{2715} Screenshot failed: {e}")),
        });
    });
}

/// How long a toast stays on row 1.
const TOAST_MS: u64 = 5000;

/// Show `text` on row 1 for `TOAST_MS`; a click on row 1 takes it away sooner.
fn toast(text: String) {
    let id = with(|v| {
        let id = v.toast.as_ref().map_or(0, |(_, id)| id + 1);
        v.toast = Some((text, id));
        id
    });
    draw_bar();
    after(TOAST_MS, move || {
        if with(|v| v.toast.as_ref().is_some_and(|(_, shown)| *shown == id)) {
            with(|v| v.toast = None);
            draw_bar();
        }
    });
}

/// `YYYYMMDD-HHMMSS` in local time.
fn timestamp() -> String {
    let now = unsafe { libc::time(std::ptr::null_mut()) };
    let mut tm: libc::tm = unsafe { std::mem::zeroed() };
    unsafe { libc::localtime_r(&now, &mut tm) };
    format!("{:04}{:02}{:02}-{:02}{:02}{:02}", tm.tm_year + 1900, tm.tm_mon + 1, tm.tm_mday, tm.tm_hour, tm.tm_min, tm.tm_sec)
}

/// A local document: its page with absolute references under `browser/`, opened in the default browser. A link:
/// the original address.
fn browser() {
    let Some(item) = with(|v| v.item.clone()) else { return };
    let target = match (&item.path, &item.url) {
        (Some(path), _) => {
            let opts = with(|v| page_options(v, item.line));
            let name = path.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or("page".into());
            let file = with(|v| v.base.join("browser").join(format!("{name}.html")));
            match page::browser_page(&Doc::File(path.clone()), &opts).and_then(|h| std::fs::write(&file, h)) {
                Ok(()) => file.display().to_string(),
                Err(e) => return herdr::notify(&format!("Cannot open in the browser: {e}")),
            }
        }
        (None, Some(url)) => url.clone(),
        _ => return,
    };
    let _ = std::process::Command::new("open").arg(&target).spawn();
}

/// A click on the page: a link to a local file opens here (with history), a web address in the browser, an
/// anchor in the same document scrolls to it.
fn click(x_px: u32, y_px: u32) {
    if !with(|v| v.loaded) {
        return;
    }
    let (r, top_css, x_css, y_css) = with(|v| {
        let y_in_view = y_px.saturating_sub((FIRST_ROW as u32 - 1) * v.g.cell_h);
        (v.r.clone(), v.view_top as f64 * v.g.cell_h as f64 / v.dpr, x_px as f64 / v.dpr, y_in_view as f64 / v.dpr)
    });
    r.eval(&format!("window.scrollTo(0, {top_css}); {}", script::hit(x_css, y_css)), |href| {
        let Some(href) = href.and_then(|h| serde_json::from_str::<Option<String>>(&h).ok()).flatten() else { return };
        follow(&href);
    });
}

fn follow(href: &str) {
    if let Some(frag) = href.strip_prefix('#') {
        return scroll_to_anchor(frag);
    }
    if href.starts_with("http://") || href.starts_with("https://") || href.starts_with("mailto:") {
        let _ = std::process::Command::new("open").arg(href).spawn();
        return;
    }
    let Some(rest) = href.strip_prefix("file://") else { return };
    let (path, fragment) = match rest.split_once('#') {
        Some((p, f)) => (percent_decode(p), Some(f.to_string())),
        None => (percent_decode(rest), None),
    };
    let path = PathBuf::from(path);
    let same_doc = with(|v| v.item.as_ref().and_then(|i| i.path.as_ref()).and_then(|p| p.parent()) == Some(path.as_path()) || v.item.as_ref().and_then(|i| i.path.as_ref()) == Some(&path));
    if let (Some(frag), true) = (fragment.as_ref(), same_doc || path.is_dir()) {
        return scroll_to_anchor(frag);
    }
    if path.is_file() {
        let (item, mode, top) = with(|v| (v.item.clone(), v.mode, v.view_top));
        if let Some(i) = item {
            with(|v| v.history.push((i, mode, top)));
        }
        open(Item { label: path.display().to_string(), path: Some(path), url: None, line: None }, Mode::Rendered, None);
    }
}

/// Scroll to the element with id `frag` in the shown page.
fn scroll_to_anchor(frag: &str) {
    let r = with(|v| v.r.clone());
    let id = serde_json::to_string(&percent_decode(frag)).unwrap();
    let js = format!("(() => {{ const e = document.getElementById({id}); return JSON.stringify(e ? e.getBoundingClientRect().top + window.scrollY : -1); }})()");
    r.eval(&js, |y| {
        if let Some(y) = y.and_then(|y| y.parse::<f64>().ok()).filter(|y| *y >= 0.0) {
            with(|v| v.view_top = (y * v.dpr / v.g.cell_h as f64) as u64);
            draw(now_ms());
        }
    });
}

fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::with_capacity(b.len());
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            if let Ok(v) = u8::from_str_radix(&s[i + 1..i + 3], 16) {
                out.push(v);
                i += 3;
                continue;
            }
        }
        out.push(b[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// Keys while the find row is open; returns true when the key was used. Typing goes into the query; page keys
/// (PageUp, PageDown, Home, End) and anything else fall through to the page.
fn on_find_key(k: &Key) -> bool {
    if with(|v| v.find.is_none()) {
        return false;
    }
    match k {
        Key::Esc => close_find(),
        Key::Alt('c') => find_option("case"),
        Key::Alt('w') => find_option("word"),
        Key::Alt('r') => find_option("regex"),
        Key::Enter | Key::Down => find_step(1),
        Key::ShiftEnter | Key::Up => find_step(-1),
        Key::Backspace => find_edit(|text| {
            text.pop();
        }),
        Key::Char(c) => find_edit(|text| text.push(*c)),
        _ => return false,
    }
    true
}

/// Turn a find option on or off (`FindQuery::toggle`: whole word and regular expression exclude each other).
fn find_option(name: &str) {
    with(|v| v.find.as_mut().map(|f| f.q.toggle(name)));
    draw_bar();
    run_find();
}

fn find_step(by: i64) {
    with(|v| v.find.as_mut().map(|f| f.index += by));
    draw_bar();
    run_find();
}

fn find_edit(change: impl FnOnce(&mut String)) {
    with(|v| {
        if let Some(f) = v.find.as_mut() {
            change(&mut f.q.text);
            f.index = 0;
        }
    });
    draw_bar();
    run_find();
}

/// Leave the zoom row for the bar.
fn close_menu() {
    with(|v| {
        v.menu = false;
        v.hover = None;
    });
    draw_bar();
}

/// A click on item `n` of the row 1 shows now.
fn row_click(n: usize) {
    let (finding, menu, source) = with(|v| (v.find.is_some(), v.menu, v.mode == Mode::Source));
    if finding {
        match term::find_items().get(n).map(|i| i.action) {
            Some(option @ ("case" | "word" | "regex")) => find_option(option),
            Some("prev") => find_step(-1),
            Some("next") => find_step(1),
            Some("close") => close_find(),
            _ => {}
        }
    } else if menu {
        match term::more_items().get(n).map(|i| i.action) {
            Some("close") => close_menu(),
            Some(action) => act(action),
            None => {}
        }
    } else if let Some(item) = term::bar_items(source).get(n) {
        act(item.action);
    }
}

fn on_key(k: Key, t: f64) {
    if on_find_key(&k) {
        return;
    }
    if k == Key::Esc && with(|v| v.menu) {
        return close_menu();
    }
    let page = with(|v| view_rows(v) as i64 - 2).max(1);
    match k {
        Key::Char('q') => quit(),
        Key::Char('j') | Key::Down => scroll(NOTCH, t),
        Key::Char('k') | Key::Up => scroll(-NOTCH, t),
        Key::Char(' ') | Key::PageDown => scroll(page, t),
        Key::Char('b') | Key::PageUp => scroll(-page, t),
        Key::Char('g') | Key::Home => scroll(i64::MIN / 2, t),
        Key::Char('G') | Key::End => scroll(i64::MAX / 2, t),
        Key::Char('r') => act("reload"),
        Key::Char('t') => act("toggle"),
        Key::Char('/') => act("find"),
        Key::Char('+') | Key::Char('=') => act("zoom-in"),
        Key::Char('-') => act("zoom-out"),
        Key::Char('0') => act("zoom-reset"),
        Key::Char('s') => act("screenshot"),
        Key::Char('o') => act("browser"),
        Key::Char('h') | Key::Backspace => act("back"),
        Key::Char(c) if c.is_ascii_digit() => {
            let choice = with(|v| v.choices.get((c as usize).wrapping_sub('1' as usize)).cloned());
            if let Some(item) = choice {
                open(item, Mode::Rendered, None);
            }
        }
        _ => {}
    }
}

fn on_mouse(m: term::Mouse, t: f64) {
    let (cell_w, cell_h) = with(|v| (v.g.cell_w.max(1), v.g.cell_h.max(1)));
    let row = (m.y_px / cell_h) as u16 + 1;
    let col = (m.x_px / cell_w) as u16 + 1;
    let on_bar = row == BAR_ROW;
    let item = if on_bar { with(|v| v.bar.iter().position(|(a, b)| (*a..=*b).contains(&col))) } else { None };
    match m.kind {
        MouseKind::WheelUp => scroll(-NOTCH, t),
        MouseKind::WheelDown => scroll(NOTCH, t),
        MouseKind::Move => {
            if with(|v| std::mem::replace(&mut v.hover, item) != item) {
                draw_bar();
            }
        }
        MouseKind::Press if on_bar && with(|v| v.toast.is_some() && v.find.is_none()) => {
            with(|v| v.toast = None);
            draw_bar();
        }
        MouseKind::Press if on_bar => {
            if let Some(n) = item {
                row_click(n);
            }
        }
        MouseKind::Press if m.button == 0 => click(m.x_px, m.y_px),
        _ => {}
    }
}

/// Raw input on a thread of its own; parsed input goes to the main queue. A lone escape that stays alone for
/// 30 ms is the Esc key.
fn read_input() {
    std::thread::spawn(|| {
        let mut stdin = io::stdin();
        let mut pending: Vec<u8> = Vec::new();
        let mut buf = [0u8; 4096];
        loop {
            let mut pfd = libc::pollfd { fd: 0, events: libc::POLLIN, revents: 0 };
            let ready = unsafe { libc::poll(&mut pfd, 1, 30) };
            if WINCH.swap(false, Ordering::SeqCst) {
                DispatchQueue::main().exec_async(resized);
            }
            if ready <= 0 {
                if pending == [0x1b] {
                    pending.clear();
                    let t = now_ms();
                    DispatchQueue::main().exec_async(move || on_key(Key::Esc, t));
                }
                continue;
            }
            match stdin.read(&mut buf) {
                Ok(0) | Err(_) => DispatchQueue::main().exec_async(|| quit()),
                Ok(n) => pending.extend_from_slice(&buf[..n]),
            }
            let (inputs, used) = term::parse(&pending);
            pending.drain(..used);
            if inputs.is_empty() {
                continue;
            }
            let t = now_ms();
            DispatchQueue::main().exec_async(move || {
                for input in inputs {
                    match input {
                        Input::Key(k) => on_key(k, t),
                        Input::Mouse(m) => on_mouse(m, t),
                        Input::Reply(r) => log(serde_json::json!({"ev": "kitty-reply", "reply": r})),
                    }
                }
            });
        }
    });
}

/// Watch the source pane's state file and act on each new `seq`. Its modification time is checked every 30 ms
/// (a click should show at once) and the file is read only when that changes.
fn follow_state(source: String) {
    std::thread::spawn(move || {
        let path = state::state_file(&source, ".json");
        let mut last: Option<u128> = None;
        let mut stamp = None;
        loop {
            let now = std::fs::metadata(&path).and_then(|m| m.modified()).ok();
            if now == stamp && last.is_some() {
                std::thread::sleep(Duration::from_millis(30));
                continue;
            }
            stamp = now;
            if let Some(st) = state::read_state(&source) {
                if last != Some(st.seq) {
                    let first = last.is_none();
                    last = Some(st.seq);
                    DispatchQueue::main().exec_async(move || on_state(st, first));
                }
            }
            std::thread::sleep(Duration::from_millis(30));
        }
    });
}

/// A new state: run its command, or show its items. On the viewer's first read a command is skipped: it was
/// meant for an earlier viewer.
fn on_state(st: ViewState, first: bool) {
    with(|v| v.seq = st.seq);
    if let Some(cmd) = st.command.as_deref() {
        if !first {
            return act(cmd);
        }
    }
    match st.items.len() {
        0 => {}
        1 => open(st.items[0].clone(), st.mode, None),
        _ => {
            let mut lines = vec!["Several files match. Press a number:".to_string(), String::new()];
            for (n, item) in st.items.iter().take(9).enumerate() {
                lines.push(format!("{}  {}", n + 1, item.label));
            }
            with(|v| {
                v.choices = st.items.clone();
                v.title = "Choose a file".into();
            });
            draw_bar();
            message(&lines);
        }
    }
}
