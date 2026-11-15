//! The viewer pane (`peek viewer`): follows the source pane's state file, builds each item's page, renders it in
//! the hidden WebKit view and shows it as Kitty tiles below a one-row top bar. Everything runs on the main queue;
//! an input thread and a state thread only post work to it.
use super::render::{after, Renderer};
use crate::kitty::{self, Geometry, TILE_BUDGET};
use crate::page::{self, Doc, PageOptions};
use crate::state::{self, Item, Mode, ViewState};
use crate::term::{self, Input, Key, MouseKind};
use crate::{herdr, script};
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

struct Viewer {
    source: String,
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
    pages: PathBuf,
    page_file: Option<PathBuf>,
    seq: u128,
    hover: Option<usize>,
    bar: Vec<(u16, u16)>,
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

/// One JSON line to `$PEEK_LOG` when it is set (timings for evals).
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
    let pages = pages_dir(source);
    let log = std::env::var_os("PEEK_LOG").and_then(|p| File::options().create(true).append(true).open(p).ok());
    V.with(|v| {
        *v.borrow_mut() = Some(Viewer {
            source: source.to_string(),
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
            pages,
            page_file: None,
            seq: 0,
            hover: None,
            bar: Vec::new(),
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
        Some(p) => open(Item { label: p.display().to_string(), path: Some(p.to_path_buf()), url: None, line: None }, Mode::Rendered),
        None => {
            out("\x1b[3;3HWaiting for a click in the Claude pane ...");
            follow_state(source.to_string());
        }
    }
    read_input();
    app.run();
    Ok(())
}

/// `<session dir>/pages`, or a folder under the temp dir when the session folder cannot be made.
fn pages_dir(source: &str) -> PathBuf {
    let dir = herdr::pane_get(source).ok().and_then(|p| {
        let project = state::project_name(p.foreground_cwd.as_deref().unwrap_or(&p.cwd));
        let session = p.session_id.unwrap_or_else(|| format!("pane-{}", source.replace(':', "-")));
        state::session_dir(&project, &session).ok()
    });
    let dir = dir.unwrap_or_else(|| std::env::temp_dir().join("peek-pages")).join("pages");
    let _ = std::fs::create_dir_all(&dir);
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
    out(&format!("{}{}\x1b[?25h\x1b[?1049l", kitty::delete_all(), term::MOUSE_OFF));
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

fn draw_bar() {
    let (text, ranges) = with(|v| term::render_bar(&v.title, v.zoom, v.g.cols, v.hover));
    with(|v| v.bar = ranges);
    out(&text);
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

/// Show `item`: build its page, load it, draw it.
fn open(item: Item, mode: Mode) {
    let name = Path::new(&item.label).file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or(item.label.clone());
    with(|v| {
        v.loaded = false;
        v.generation += 1;
        v.ready.clear();
        v.mode = mode;
        v.title = name.clone();
        v.choices.clear();
        v.item = Some(item.clone());
    });
    draw_bar();
    message(&[format!("Loading {name} ...")]);
    let Some(path) = item.path.clone() else {
        // Jira, Confluence and PR links are fetched in the next step of the plan.
        return message(&[format!("Cannot show {} yet", item.url.unwrap_or_default())]);
    };
    let (opts, pages, marker) = with(|v| {
        v.marker += 1;
        (page_options(v, item.line), v.pages.clone(), v.marker)
    });
    let html = match page::build(&Doc::File(path.clone()), &opts) {
        Ok(h) => h,
        Err(e) => return message(&[format!("Cannot show {}: {e}", path.display())]),
    };
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
            let still_current = with(|v| v.marker == marker);
            if !still_current {
                return;
            }
            with(|v| {
                v.doc_h = info.doc_h;
                v.loaded = true;
                v.view_top = (info.top_hint * v.dpr / v.g.cell_h as f64) as u64;
            });
            log(serde_json::json!({"ev": "loaded", "ms": now_ms() - t0, "doc_h": info.doc_h}));
            message(&[]);
            draw(now_ms());
            watch_images(marker, 0, false);
        }
        Err(e) => message(&[e]),
    });
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
        let (r, css_w) = with(|v| (v.r.clone(), v.css_w));
        r.wait_width(css_w, move |doc_h| {
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
    let t = now_ms();
    match action {
        "reload" => {
            if let Some(item) = with(|v| v.item.clone()) {
                let mode = with(|v| v.mode);
                open(item, mode);
            }
        }
        "toggle" => {
            if let Some(item) = with(|v| v.item.clone()) {
                let mode = with(|v| if v.mode == Mode::Rendered { Mode::Source } else { Mode::Rendered });
                open(item, mode);
            }
        }
        _ => log(serde_json::json!({"ev": "action", "action": action, "t_key": t})),
    }
}

fn on_key(k: Key, t: f64) {
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
        Key::Char(c) if c.is_ascii_digit() => {
            let choice = with(|v| v.choices.get((c as usize).wrapping_sub('1' as usize)).cloned());
            if let Some(item) = choice {
                open(item, Mode::Rendered);
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
        MouseKind::Press if on_bar => {
            if let Some(n) = item {
                act(term::bar_items()[n].action);
            }
        }
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

/// Watch the source pane's state file (every 150 ms; it is tiny) and act on each new `seq`.
fn follow_state(source: String) {
    std::thread::spawn(move || {
        let mut last: Option<u128> = None;
        loop {
            if let Some(st) = state::read_state(&source) {
                if last != Some(st.seq) {
                    last = Some(st.seq);
                    DispatchQueue::main().exec_async(move || on_state(st));
                }
            }
            std::thread::sleep(Duration::from_millis(150));
        }
    });
}

fn on_state(st: ViewState) {
    with(|v| v.seq = st.seq);
    if let Some(cmd) = st.command.as_deref() {
        return act(cmd);
    }
    match st.items.len() {
        0 => {}
        1 => open(st.items[0].clone(), st.mode),
        _ => {
            let mut lines = vec!["Several files match. Press a number:".to_string(), String::new()];
            for (n, item) in st.items.iter().take(9).enumerate() {
                lines.push(format!("{}  {}", n + 1, item.label));
            }
            message(&lines);
            with(|v| v.choices = st.items.clone());
        }
    }
}
