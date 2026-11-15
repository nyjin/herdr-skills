//! Experiment: the viewer on standard Kitty graphics (herdr >= 0.9.2 renders it itself). One process: hidden WebKit
//! renders the page, frames go to the pane as Kitty graphics, keys/mouse/resize come from the terminal.
//!
//!   peekv <page.html> [--mode frame|tall] [--medium s|t|d] [--log out.jsonl]
//!
//! frame: every scroll re-captures the visible screen and transmits it.
//! tall:  one image of several screens is transmitted; scrolling inside it only moves the placement's source rect.
//! Keys: j/k a notch, space/b a screen, g/G top/bottom, q quit. Mouse clicks and Kitty replies are logged.
use std::cell::RefCell;
use std::ffi::c_void;
use std::fs::File;
use std::io::{Read, Write};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use block2::RcBlock;
use dispatch2::{DispatchQueue, DispatchTime};
use objc2::rc::Retained;
use objc2::runtime::AnyObject;
use objc2::MainThreadMarker;
use objc2_app_kit::{NSApplication, NSApplicationActivationPolicy, NSImage};
use objc2_core_foundation::{CGPoint, CGRect, CGSize};
use objc2_core_graphics::{kCGColorSpaceSRGB, CGBitmapContextCreate, CGColorSpace, CGContext, CGImageAlphaInfo};
use objc2_foundation::{NSError, NSNumber, NSPoint, NSRect, NSSize, NSString, NSURL};
use objc2_web_kit::{WKSnapshotConfiguration, WKWebView, WKWebViewConfiguration};
use serde_json::{json, Value};

static TALL: OnceLock<f64> = OnceLock::new();
static SCALE: OnceLock<f64> = OnceLock::new();
fn scale() -> f64 {
    *SCALE.get().unwrap_or(&1.0)
}
fn tall_screens() -> f64 {
    *TALL.get().unwrap_or(&2.0)
}

struct V {
    web: Retained<WKWebView>,
    html: String,
    mode: String,
    medium: String,
    log: File,
    cols: u16,
    rows: u16,
    cell_w: f64,
    cell_h: f64,
    dpr: f64,
    css_w: f64,
    css_h: f64,
    y: f64,
    doc_h: f64,
    seq: u64,
    tall_top: Option<f64>,
    busy: bool,
    pending: Option<(f64, f64, &'static str)>, // (dy or absolute marker, key time, why)
}

thread_local! { static ST: RefCell<Option<V>> = const { RefCell::new(None) }; }
static START: OnceLock<Instant> = OnceLock::new();
static ORIG: OnceLock<libc::termios> = OnceLock::new();
static WINCH: AtomicBool = AtomicBool::new(false);
static LOADED: AtomicBool = AtomicBool::new(false);

fn now() -> f64 {
    START.get().unwrap().elapsed().as_secs_f64() * 1000.0
}
fn with<R>(f: impl FnOnce(&mut V) -> R) -> R {
    ST.with(|s| f(s.borrow_mut().as_mut().unwrap()))
}
fn log(mut v: Value) {
    v["t"] = json!((now() * 10.0).round() / 10.0);
    v["epoch_ms"] = json!(std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_millis() as u64);
    with(|s| writeln!(s.log, "{v}").ok());
}
fn out(bytes: &[u8]) {
    let mut o = std::io::stdout().lock();
    o.write_all(bytes).ok();
    o.flush().ok();
}
fn after(ms: u64, f: impl FnOnce() + Send + 'static) {
    let _ = DispatchQueue::main().after(DispatchTime::try_from(Duration::from_millis(ms)).unwrap(), f);
}

fn b64(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut s = String::with_capacity(data.len().div_ceil(3) * 4);
    for c in data.chunks(3) {
        let n = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
        for i in 0..4 {
            s.push(if i <= c.len() { T[(n >> (18 - 6 * i) & 63) as usize] as char } else { '=' });
        }
    }
    s
}

fn eval(js: &str, done: impl FnOnce(Option<String>) + 'static) {
    let done = RefCell::new(Some(done));
    let block = RcBlock::new(move |r: *mut AnyObject, _e: *mut NSError| {
        let s = (!r.is_null()).then(|| unsafe { &*(r as *const NSString) }.to_string());
        if let Some(f) = done.borrow_mut().take() {
            f(s)
        }
    });
    let web = with(|s| s.web.clone());
    unsafe { web.evaluateJavaScript_completionHandler(&NSString::from_str(js), Some(&block)) };
}

/// Pane geometry from the pty: cells and pixels; falls back to 8x18 cells if the pty reports no pixels.
fn measure() -> (u16, u16, f64, f64) {
    let mut ws: libc::winsize = unsafe { std::mem::zeroed() };
    unsafe { libc::ioctl(1, libc::TIOCGWINSZ, &mut ws) };
    let (cw, ch) = if ws.ws_xpixel > 0 && ws.ws_col > 0 {
        (ws.ws_xpixel as f64 / ws.ws_col as f64, ws.ws_ypixel as f64 / ws.ws_row as f64)
    } else {
        (8.0, 18.0)
    };
    (ws.ws_col, ws.ws_row, cw.floor(), ch.floor())
}

fn apply_geometry() {
    let (cols, rows, cw, ch) = measure();
    with(|s| {
        s.cols = cols;
        s.rows = rows;
        s.cell_w = cw;
        s.cell_h = ch;
        s.dpr = if ch >= 26.0 { 2.0 } else { 1.0 };
        s.css_w = (cols as f64 * cw / s.dpr).floor();
        s.css_h = (rows as f64 * ch / s.dpr).floor();
        let h = if s.mode == "tall" { s.css_h * tall_screens() } else { s.css_h };
        s.web.setFrameSize(NSSize::new(s.css_w, h));
        s.tall_top = None;
    });
    let (cols, rows, cw, ch, css_w, css_h) = with(|s| (s.cols, s.rows, s.cell_w, s.cell_h, s.css_w, s.css_h));
    log(json!({"ev": "measure", "cols": cols, "rows": rows, "cell": [cw, ch], "css": [css_w, css_h]}));
}

fn load() {
    let t0 = now();
    let html = with(|s| s.html.clone());
    let path = std::fs::canonicalize(&html).unwrap();
    let url = NSURL::from_file_path(&path).unwrap();
    let dir = NSURL::from_file_path(path.parent().unwrap()).unwrap();
    let web = with(|s| s.web.clone());
    unsafe { web.loadFileURL_allowingReadAccessToURL(&url, &dir) };
    poll_ready(t0);
}

fn poll_ready(t0: f64) {
    let js = "JSON.stringify([document.readyState, document.title, document.documentElement.scrollHeight, window.peekTop || (document.querySelector('.hit') ? Math.max(0, document.querySelector('.hit').offsetTop - 80) : 0), window.innerWidth])";
    eval(js, move |s| {
        let v: Value = s.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null);
        let css_w = with(|s| s.css_w);
        if v[1] == "ready" && v[4].as_f64() == Some(css_w) {
            with(|s| {
                s.doc_h = v[2].as_f64().unwrap_or(0.0);
                s.y = v[3].as_f64().unwrap_or(0.0);
            });
            with(|s| s.tall_top = None);
            LOADED.store(true, Ordering::SeqCst);
            log(json!({"ev": "loaded", "ms": now() - t0, "doc_h": v[2]}));
            draw("open", t0);
        } else {
            after(2, move || poll_ready(t0));
        }
    });
}

/// Draw the screen at the current y. Requests that arrive while a draw is running are folded into one.
fn draw(why: &'static str, t_key: f64) {
    if with(|s| std::mem::replace(&mut s.busy, true)) {
        return;
    }
    let (mode, y, css_h, doc_h) = with(|s| (s.mode.clone(), s.y, s.css_h, s.doc_h));
    let y = y.clamp(0.0, (doc_h - css_h).max(0.0));
    with(|s| s.y = y);
    if mode == "tall" {
        let top = with(|s| s.tall_top);
        if let Some(top) = top.filter(|t| y >= *t && y + css_h <= *t + css_h * tall_screens()) {
            place(top, y, why, t_key, false, 0.0, 0);
            return;
        }
        // Centre the screen in the tall image (equal margin above and below), kept inside the document.
        let tall_h = css_h * tall_screens();
        let top = (y - (tall_h - css_h) / 2.0).clamp(0.0, (doc_h - tall_h).max(0.0));
        capture(top, move |rgba_name, bytes, render_ms| {
            with(|s| s.tall_top = Some(top));
            transmit(&rgba_name, bytes, false);
            place(top, y, why, t_key, true, render_ms, bytes);
        });
    } else {
        capture(y, move |name, bytes, render_ms| {
            let tw = now();
            transmit(&name, bytes, true);
            finish(json!({"ev": "draw", "why": why, "y": y, "recapture": true, "render_ms": render_ms, "write_ms": now() - tw,
                          "bytes": bytes, "key_to_written": now() - t_key}));
        });
    }
}

fn finish(v: Value) {
    log(v);
    with(|s| s.busy = false);
    if let Some((target, t_key, why)) = with(|s| s.pending.take()) {
        with(|s| s.y = target);
        draw(why, t_key);
    }
}

/// Put the tall image's slice for y on screen: a placement with a source rect, no pixels sent.
fn place(top: f64, y: f64, why: &'static str, t_key: f64, recapture: bool, render_ms: f64, bytes: usize) {
    let tw = now();
    // image pixels per css px: the screen is rows*cell_h pixels tall and css_h css px tall
    let (px_per_css, w, h, cols, rows) = with(|s| (s.rows as f64 * s.cell_h * scale() / s.css_h, s.cols as f64 * s.cell_w * scale(), s.rows as f64 * s.cell_h * scale(), s.cols, s.rows));
    let src_y = ((y - top) * px_per_css).round() as i64;
    let cmd = format!("\x1b[H\x1b_Ga=p,i=1,p=1,x=0,y={src_y},w={},h={},c={cols},r={rows},C=1,q=1\x1b\\", w as i64, h as i64);
    out(cmd.as_bytes());
    finish(json!({"ev": "draw", "why": why, "y": y, "recapture": recapture, "render_ms": render_ms, "bytes": bytes,
                  "write_ms": now() - tw, "src_y": src_y, "key_to_written": now() - t_key}));
}

/// Snapshot the view with the page scrolled to y, into an RGBA buffer handed to `done` as a medium name.
fn capture(y: f64, done: impl FnOnce(String, usize, f64) + 'static) {
    let t0 = now();
    eval(&format!("window.scrollTo(0, {y}); JSON.stringify(window.scrollY)"), move |_| {
        let mtm = MainThreadMarker::new().unwrap();
        let (vw, vh) = with(|s| {
            let f = s.web.frame();
            (f.size.width, f.size.height)
        });
        let (pw, ph) = with(|s| ((s.cols as f64 * s.cell_w * scale()) as usize, ((vh / s.css_h) * s.rows as f64 * s.cell_h * scale()) as usize));
        let cfg = unsafe { WKSnapshotConfiguration::new(mtm) };
        unsafe {
            cfg.setRect(CGRect::new(CGPoint::new(0.0, 0.0), CGSize::new(vw, vh)));
            cfg.setSnapshotWidth(Some(&NSNumber::new_f64(vw)));
            cfg.setAfterScreenUpdates(true);
        }
        let done = RefCell::new(Some(done));
        let block = RcBlock::new(move |img: *mut NSImage, _e: *mut NSError| {
            if img.is_null() {
                return log(json!({"ev": "error", "what": "snapshot"}));
            }
            let image = unsafe { &*img };
            let Some(cg) = (unsafe { image.CGImageForProposedRect_context_hints(std::ptr::null_mut(), None, None) }) else { return };
            let (name, ptr, len) = buffer(pw * ph * 4);
            let space = CGColorSpace::with_name(Some(unsafe { kCGColorSpaceSRGB }));
            let ctx = unsafe { CGBitmapContextCreate(ptr, pw, ph, 8, pw * 4, space.as_deref(), CGImageAlphaInfo::PremultipliedLast.0) }.unwrap();
            CGContext::draw_image(Some(&ctx), CGRect::new(CGPoint::new(0.0, 0.0), CGSize::new(pw as f64, ph as f64)), Some(&cg));
            drop(ctx);
            release(&name, ptr, len, pw, ph);
            if let Some(f) = done.borrow_mut().take() {
                f(name, pw * ph * 4, now() - t0);
            }
            with(|s| s.seq += 1);
        });
        let web = with(|s| s.web.clone());
        unsafe { web.takeSnapshotWithConfiguration_completionHandler(Some(&cfg), &block) };
    });
}

thread_local! { static LAST: RefCell<(usize, usize, Vec<u8>)> = const { RefCell::new((0, 0, Vec::new())) }; }

/// Memory for one frame: POSIX shared memory (s), a temp file (t), or a plain buffer sent inline (d).
fn buffer(len: usize) -> (String, *mut c_void, usize) {
    let (medium, seq) = with(|s| (s.medium.clone(), s.seq));
    let pid = std::process::id();
    match medium.as_str() {
        "s" => {
            let name = format!("/pkv{pid}_{seq}");
            let c = std::ffi::CString::new(name.clone()).unwrap();
            unsafe {
                let fd = libc::shm_open(c.as_ptr(), libc::O_CREAT | libc::O_RDWR | libc::O_EXCL, 0o600);
                libc::ftruncate(fd, len as libc::off_t);
                let p = libc::mmap(std::ptr::null_mut(), len, libc::PROT_READ | libc::PROT_WRITE, libc::MAP_SHARED, fd, 0);
                libc::close(fd);
                (name, p, len)
            }
        }
        "t" => {
            // The terminal only accepts temp files from the system temp dir ($TMPDIR), not /tmp.
            let name = std::env::temp_dir().join(format!("tty-graphics-protocol-peekv-{pid}-{seq}.rgba")).display().to_string();
            let c = std::ffi::CString::new(name.clone()).unwrap();
            unsafe {
                let fd = libc::open(c.as_ptr(), libc::O_CREAT | libc::O_RDWR | libc::O_EXCL, 0o600);
                libc::ftruncate(fd, len as libc::off_t);
                let p = libc::mmap(std::ptr::null_mut(), len, libc::PROT_READ | libc::PROT_WRITE, libc::MAP_SHARED, fd, 0);
                libc::close(fd);
                (name, p, len)
            }
        }
        _ => {
            let p = unsafe { libc::malloc(len) };
            ("inline".into(), p, len)
        }
    }
}

fn release(name: &str, ptr: *mut c_void, len: usize, w: usize, h: usize) {
    if name == "inline" {
        let data = unsafe { std::slice::from_raw_parts(ptr as *const u8, len) }.to_vec();
        unsafe { libc::free(ptr) };
        LAST.with(|l| *l.borrow_mut() = (w, h, data));
    } else {
        unsafe { libc::munmap(ptr, len) };
        LAST.with(|l| {
            let mut l = l.borrow_mut();
            l.0 = w;
            l.1 = h;
            l.2.clear();
        });
    }
}

/// Send the frame's pixels. `show` also places it at the top-left (frame mode); tall mode places separately.
fn transmit(name: &str, _bytes: usize, show: bool) {
    let (w, h, data) = LAST.with(|l| {
        let l = l.borrow();
        (l.0, l.1, if name == "inline" { l.2.clone() } else { Vec::new() })
    });
    let (cols, rows) = with(|s| (s.cols, s.rows));
    let place_cr = format!("a=T,p=1,C=1,c={cols},r={rows},");
    let action = if show { place_cr.as_str() } else { "a=t," };
    let mut cmd = Vec::new();
    if show {
        cmd.extend_from_slice(b"\x1b[H");
    }
    match with(|s| s.medium.clone()).as_str() {
        "s" | "t" => {
            let t = with(|s| s.medium.clone());
            cmd.extend_from_slice(
                format!("\x1b_G{action}i=1,f=32,s={w},v={h},t={t},S={},q=1;{}\x1b\\", w * h * 4, b64(name.as_bytes())).as_bytes(),
            );
        }
        _ => {
            let enc = b64(&data);
            let chunks: Vec<&[u8]> = enc.as_bytes().chunks(4096).collect();
            for (i, c) in chunks.iter().enumerate() {
                let more = if i + 1 < chunks.len() { 1 } else { 0 };
                if i == 0 {
                    cmd.extend_from_slice(format!("\x1b_G{action}i=1,f=32,s={w},v={h},q=1,m={more};").as_bytes());
                } else {
                    cmd.extend_from_slice(format!("\x1b_Gm={more};").as_bytes());
                }
                cmd.extend_from_slice(c);
                cmd.extend_from_slice(b"\x1b\\");
            }
        }
    }
    out(&cmd);
}

fn scroll(dy: f64, t_key: f64, why: &'static str) {
    let busy = with(|s| s.busy);
    if busy {
        with(|s| {
            let base = s.pending.map(|p| p.0).unwrap_or(s.y);
            s.pending = Some((base + dy, t_key, why));
        });
        return;
    }
    with(|s| s.y += dy);
    draw(why, t_key);
}

fn on_key(c: u8, t_key: f64) {
    let (notch, page, doc_h) = with(|s| (3.0 * s.cell_h / s.dpr, s.css_h, s.doc_h));
    log(json!({"ev": "key", "key": (c as char).to_string()}));
    match c {
        b'j' => scroll(notch, t_key, "key"),
        b'k' => scroll(-notch, t_key, "key"),
        b' ' => scroll(page, t_key, "key"),
        b'b' => scroll(-page, t_key, "key"),
        b'g' => scroll(-doc_h, t_key, "key"),
        b'G' => scroll(doc_h, t_key, "key"),
        b'q' => quit(),
        _ => {}
    }
}

fn on_resize(t_key: f64) {
    let (old_doc, y) = with(|s| (s.doc_h, s.y));
    apply_geometry();
    if !LOADED.load(Ordering::SeqCst) {
        return; // the load's own first draw uses the new geometry
    }
    let css_w = with(|s| s.css_w);
    poll_resized(t_key, css_w, old_doc, y);
}

fn poll_resized(t0: f64, css_w: f64, old_doc: f64, y: f64) {
    eval("JSON.stringify([window.innerWidth, document.documentElement.scrollHeight])", move |s| {
        let v: Value = s.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null);
        if v[0].as_f64() == Some(css_w) {
            let doc_h = v[1].as_f64().unwrap_or(old_doc);
            with(|s| {
                s.doc_h = doc_h;
                s.y = if old_doc > 0.0 { y * doc_h / old_doc } else { 0.0 };
            });
            log(json!({"ev": "relayout", "ms": now() - t0, "doc_h": doc_h}));
            out(b"\x1b_Ga=d,d=A,q=2\x1b\\\x1b[2J");
            draw("resize", t0);
        } else if now() - t0 < 5000.0 {
            after(1, move || poll_resized(t0, css_w, old_doc, y));
        }
    });
}

fn quit() {
    out(b"\x1b_Ga=d,d=A,q=2\x1b\\\x1b[?1006l\x1b[?1016l\x1b[?1003l\x1b[?1000l\x1b[?25h\x1b[?1049l");
    if let Some(t) = ORIG.get() {
        unsafe { libc::tcsetattr(0, libc::TCSANOW, t) };
    }
    log(json!({"ev": "quit"}));
    std::process::exit(0);
}

extern "C" fn on_winch(_: libc::c_int) {
    WINCH.store(true, Ordering::SeqCst);
}

fn main() {
    START.set(Instant::now()).unwrap();
    let a: Vec<String> = std::env::args().collect();
    let opt = |k: &str, d: &str| a.iter().position(|x| x == k).and_then(|i| a.get(i + 1).cloned()).unwrap_or(d.into());
    let html = a[1].clone();
    TALL.set(opt("--screens", "2").parse().unwrap_or(2.0)).ok();
    SCALE.set(opt("--scale", "1").parse().unwrap_or(1.0)).ok();
    let mtm = MainThreadMarker::new().unwrap();
    let app = NSApplication::sharedApplication(mtm);
    app.setActivationPolicy(NSApplicationActivationPolicy::Accessory);
    let web = unsafe {
        WKWebView::initWithFrame_configuration(
            mtm.alloc(),
            NSRect::new(NSPoint::new(0.0, 0.0), NSSize::new(800.0, 600.0)),
            &WKWebViewConfiguration::new(mtm),
        )
    };
    let log_path = opt("--log", "peekv-log.jsonl");
    ST.with(|s| {
        *s.borrow_mut() = Some(V {
            web, html: html.clone(), mode: opt("--mode", "frame"), medium: opt("--medium", "s"),
            log: File::options().create(true).append(true).open(log_path).unwrap(),
            cols: 0, rows: 0, cell_w: 0.0, cell_h: 0.0, dpr: 1.0, css_w: 0.0, css_h: 0.0, y: 0.0, doc_h: 0.0,
            seq: 0, tall_top: None, busy: false, pending: None,
        })
    });
    // Terminal: raw input, alternate screen, no cursor, mouse reports in SGR pixels; a loading line until the first frame.
    unsafe {
        let mut t: libc::termios = std::mem::zeroed();
        libc::tcgetattr(0, &mut t);
        ORIG.set(t).ok();
        libc::cfmakeraw(&mut t);
        libc::tcsetattr(0, libc::TCSANOW, &t);
        libc::signal(libc::SIGWINCH, on_winch as *const () as libc::sighandler_t);
    }
    let name = std::path::Path::new(&html).file_name().unwrap().to_string_lossy().to_string();
    out(format!("\x1b[?1049h\x1b[?25l\x1b[2J\x1b[2;3HLoading {name} ...\x1b[?1000h\x1b[?1003h\x1b[?1006h\x1b[?1016h").as_bytes());
    log(json!({"ev": "start", "mode": with(|s| s.mode.clone()), "medium": with(|s| s.medium.clone()), "html": html}));
    apply_geometry();
    load();
    std::thread::spawn(|| {
        let mut stdin = std::io::stdin();
        let mut buf = [0u8; 4096];
        loop {
            let mut pfd = libc::pollfd { fd: 0, events: libc::POLLIN, revents: 0 };
            let ready = unsafe { libc::poll(&mut pfd, 1, 20) };
            if WINCH.swap(false, Ordering::SeqCst) {
                let t = now();
                DispatchQueue::main().exec_async(move || on_resize(t));
            }
            if ready <= 0 {
                continue;
            }
            let Ok(n) = stdin.read(&mut buf) else { break };
            if n == 0 {
                break;
            }
            let t = now();
            let data = buf[..n].to_vec();
            DispatchQueue::main().exec_async(move || {
                let text = String::from_utf8_lossy(&data).to_string();
                if text.contains("\x1b_G") {
                    return log(json!({"ev": "kitty-reply", "raw": text.replace('\x1b', "ESC")}));
                }
                if text.starts_with("\x1b[<") {
                    return log(json!({"ev": "mouse", "raw": text.replace('\x1b', "ESC")}));
                }
                for c in data {
                    on_key(c, t);
                }
            });
        }
    });
    app.run();
}
