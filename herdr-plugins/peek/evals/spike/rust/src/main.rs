//! Experiment: the resident renderer (peekd.swift) ported to Rust through objc2, to see whether the Rust WebKit path
//! works at the same speed. Same JSON-lines protocol on stdin/stdout:
//!
//!   {"cmd":"load","html":"/x.html","width":1000,"height":1300}   -> {"cmd":"load","ms","doc_h","top"}
//!   {"cmd":"size","width":800,"height":1300}                      -> {"cmd":"size","ms","doc_h","width"}
//!   {"cmd":"frame","y":0,"scale":1,"path":"/x.bgra"}              -> {"cmd":"frame","ms","snap_ms","draw_ms","px_w","px_h"}
//!   {"cmd":"quit"}
//!
//! Unlike the Swift version, `size` waits one animation frame inside the page (callAsyncJavaScript awaits the
//! promise), so its doc_h is the height after the new layout.
use std::cell::RefCell;
use std::collections::HashMap;
use std::ffi::c_void;
use std::io::{BufRead, Write};
use std::sync::OnceLock;
use std::time::{Duration, Instant};

use block2::RcBlock;
use dispatch2::{DispatchQueue, DispatchTime};
use objc2::rc::Retained;
use objc2::runtime::AnyObject;
use objc2::MainThreadMarker;
use objc2_app_kit::{NSApplication, NSApplicationActivationPolicy, NSImage};
use objc2_core_foundation::{CGPoint, CGRect, CGSize};
use objc2_core_graphics::{
    kCGColorSpaceSRGB, CGBitmapContextCreate, CGBitmapInfo, CGColorSpace, CGContext, CGImageAlphaInfo,
};
use objc2_foundation::{NSError, NSNumber, NSPoint, NSRect, NSSize, NSString, NSURL};
use objc2_web_kit::{WKContentWorld, WKSnapshotConfiguration, WKWebView, WKWebViewConfiguration};
use serde_json::{json, Value};

struct State {
    web: Retained<WKWebView>,
    width: f64,
    height: f64,
    loads: u64,
    maps: HashMap<String, (*mut c_void, usize)>,
}

thread_local! {
    static ST: RefCell<Option<State>> = const { RefCell::new(None) };
}

static START: OnceLock<Instant> = OnceLock::new();
static JSOFF: OnceLock<bool> = OnceLock::new();

fn now() -> f64 {
    START.get().unwrap().elapsed().as_secs_f64() * 1000.0
}

fn reply(v: Value) {
    let mut out = std::io::stdout().lock();
    writeln!(out, "{v}").unwrap();
    out.flush().unwrap();
}

fn with<R>(f: impl FnOnce(&mut State) -> R) -> R {
    ST.with(|s| f(s.borrow_mut().as_mut().unwrap()))
}

fn web() -> Retained<WKWebView> {
    with(|s| s.web.clone())
}

/// Runs `js` (which must evaluate to a string, e.g. JSON.stringify(...)) and hands the string to `done`.
fn eval(js: &str, done: impl FnOnce(Option<String>) + 'static) {
    let done = RefCell::new(Some(done));
    let block = RcBlock::new(move |r: *mut AnyObject, _e: *mut NSError| {
        // Safety: every script we run returns a string, so a non-null result is an NSString.
        let s = (!r.is_null()).then(|| unsafe { &*(r as *const NSString) }.to_string());
        if let Some(f) = done.borrow_mut().take() {
            f(s)
        }
    });
    unsafe { web().evaluateJavaScript_completionHandler(&NSString::from_str(js), Some(&block)) };
}

/// Like `eval`, but `body` is an async function body: its returned promise is awaited.
fn call_async(body: &str, done: impl FnOnce(Option<String>) + 'static) {
    let mtm = MainThreadMarker::new().unwrap();
    let done = RefCell::new(Some(done));
    let block = RcBlock::new(move |r: *mut AnyObject, _e: *mut NSError| {
        let s = (!r.is_null()).then(|| unsafe { &*(r as *const NSString) }.to_string());
        if let Some(f) = done.borrow_mut().take() {
            f(s)
        }
    });
    unsafe {
        web().callAsyncJavaScript_arguments_inFrame_inContentWorld_completionHandler(
            &NSString::from_str(body),
            None,
            None,
            &WKContentWorld::pageWorld(mtm),
            Some(&block),
        )
    };
}

fn load(c: &Value) {
    let t0 = now();
    let path = std::fs::canonicalize(c["html"].as_str().unwrap()).unwrap();
    let (w, h) = (c["width"].as_f64().unwrap_or(1000.0), c["height"].as_f64().unwrap_or(1300.0));
    let n = with(|s| {
        s.width = w;
        s.height = h;
        s.loads += 1;
        s.web.setFrameSize(NSSize::new(w, h));
        s.loads
    });
    // A query marks this navigation, so polling cannot mistake the previous page (also titled "ready") for it.
    let spec = format!("file://{}?peek={n}", path.display().to_string().replace(' ', "%20"));
    let url = NSURL::URLWithString(&NSString::from_str(&spec)).unwrap();
    // PEEK_READ_ROOT widens what the page may read (the document's own folder can differ from the page's).
    let root = std::env::var("PEEK_READ_ROOT").map(std::path::PathBuf::from).unwrap_or_else(|_| path.parent().unwrap().to_path_buf());
    let dir = NSURL::from_file_path(&root).unwrap();
    unsafe { web().loadFileURL_allowingReadAccessToURL(&url, &dir) };
    poll_ready(t0, format!("?peek={n}"));
}

fn poll_ready(t0: f64, search: String) {
    let js = "JSON.stringify([location.search, document.title, document.documentElement.scrollHeight, window.peekTop || (document.querySelector('.hit') ? Math.max(0, document.querySelector('.hit').offsetTop - 80) : 0), document.readyState])";
    eval(js, move |s| {
        let v: Value = s.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null);
        let jsoff = *JSOFF.get().unwrap_or(&false);
        if v[0] == search.as_str() && (v[1] == "ready" || (jsoff && v[4] == "complete")) {
            reply(json!({"cmd": "load", "ms": (now() - t0) as i64, "doc_h": v[2], "top": v[3]}));
        } else if now() - t0 > 30000.0 {
            reply(json!({"error": "not ready"}));
        } else {
            let when = DispatchTime::try_from(Duration::from_millis(2)).unwrap();
            let _ = DispatchQueue::main().after(when, move || poll_ready(t0, search));
        }
    });
}

fn size(c: &Value) {
    let t0 = now();
    let w = with(|s| {
        s.width = c["width"].as_f64().unwrap_or(s.width);
        s.height = c["height"].as_f64().unwrap_or(s.height);
        s.web.setFrameSize(NSSize::new(s.width, s.height));
        s.width
    });
    poll_size(t0, w);
}

/// requestAnimationFrame never fires in a view that is not in a window, so wait until the page itself reports the
/// new width; reading scrollHeight then forces the layout at that width.
fn poll_size(t0: f64, w: f64) {
    eval("JSON.stringify([window.innerWidth, document.documentElement.scrollHeight])", move |s| {
        let v: Value = s.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null);
        if v[0].as_f64() == Some(w) {
            reply(json!({"cmd": "size", "ms": (now() - t0) as i64, "doc_h": v[1], "width": w as i64}));
        } else if now() - t0 > 5000.0 {
            reply(json!({"error": "size not applied", "inner_width": v[0]}));
        } else {
            let when = DispatchTime::try_from(Duration::from_millis(1)).unwrap();
            let _ = DispatchQueue::main().after(when, move || poll_size(t0, w));
        }
    });
}

/// A frame file for herdr's file-frame stream: 0600, created exclusively, exact length, mapped once.
fn mapped(path: &str, len: usize) -> Option<*mut c_void> {
    if let Some(&(p, l)) = with(|s| s.maps.get(path).copied()).as_ref() {
        if l == len {
            return Some(p);
        }
    }
    let cpath = std::ffi::CString::new(path).ok()?;
    unsafe {
        libc::unlink(cpath.as_ptr());
        let fd = libc::open(cpath.as_ptr(), libc::O_RDWR | libc::O_CREAT | libc::O_EXCL, 0o600);
        if fd < 0 || libc::ftruncate(fd, len as libc::off_t) != 0 {
            return None;
        }
        let p = libc::mmap(std::ptr::null_mut(), len, libc::PROT_READ | libc::PROT_WRITE, libc::MAP_SHARED, fd, 0);
        libc::close(fd);
        if p == libc::MAP_FAILED {
            return None;
        }
        with(|s| s.maps.insert(path.to_string(), (p, len)));
        Some(p)
    }
}

fn frame(c: &Value) {
    let t0 = now();
    let y = c["y"].as_f64().unwrap_or(0.0);
    let scale = c["scale"].as_f64().unwrap_or(1.0);
    let path = c["path"].as_str().unwrap().to_string();
    eval(&format!("window.scrollTo(0, {y}); JSON.stringify(window.scrollY)"), move |_| {
        let mtm = MainThreadMarker::new().unwrap();
        let (w, h) = with(|s| (s.width, s.height));
        let cfg = unsafe { WKSnapshotConfiguration::new(mtm) };
        unsafe {
            cfg.setRect(CGRect::new(CGPoint::new(0.0, 0.0), CGSize::new(w, h)));
            cfg.setSnapshotWidth(Some(&NSNumber::new_f64(w)));
            cfg.setAfterScreenUpdates(true);
        }
        let block = RcBlock::new(move |img: *mut NSImage, _err: *mut NSError| {
            let t1 = now();
            if img.is_null() {
                return reply(json!({"error": "snapshot"}));
            }
            let image = unsafe { &*img };
            let (pw, ph) = ((w * scale) as usize, (h * scale) as usize);
            let Some(cg) = (unsafe { image.CGImageForProposedRect_context_hints(std::ptr::null_mut(), None, None) })
            else {
                return reply(json!({"error": "cgimage"}));
            };
            let Some(ptr) = mapped(&path, pw * ph * 4) else {
                return reply(json!({"error": format!("frame file {path}")}));
            };
            let space = CGColorSpace::with_name(Some(unsafe { kCGColorSpaceSRGB }));
            let info = CGImageAlphaInfo::PremultipliedFirst.0 | CGBitmapInfo::ByteOrder32Little.bits();
            let Some(ctx) = (unsafe { CGBitmapContextCreate(ptr, pw, ph, 8, pw * 4, space.as_deref(), info) }) else {
                return reply(json!({"error": "context"}));
            };
            // A bitmap context's first row is the image's top row, so the image goes in as it is: no flip.
            CGContext::draw_image(
                Some(&ctx),
                CGRect::new(CGPoint::new(0.0, 0.0), CGSize::new(pw as f64, ph as f64)),
                Some(&cg),
            );
            reply(json!({"cmd": "frame", "y": y, "ms": (now() - t0) as i64, "snap_ms": (t1 - t0) as i64,
                         "draw_ms": (now() - t1) as i64, "px_w": pw, "px_h": ph, "path": path}));
        });
        unsafe { web().takeSnapshotWithConfiguration_completionHandler(Some(&cfg), &block) };
    });
}

/// Page zoom: re-lays the page out at width / z css px. Done once the page reports the new inner width.
fn zoom(c: &Value) {
    let t0 = now();
    let z = c["z"].as_f64().unwrap_or(1.0);
    let w = with(|s| {
        unsafe { s.web.setPageZoom(z) };
        s.width
    });
    poll_zoom(t0, (w / z).round());
}

fn poll_zoom(t0: f64, inner: f64) {
    eval("JSON.stringify([window.innerWidth, document.documentElement.scrollHeight])", move |s| {
        let v: Value = s.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null);
        let got = v[0].as_f64().unwrap_or(0.0);
        if (got - inner).abs() <= 1.0 {
            reply(json!({"cmd": "zoom", "ms": (now() - t0) as i64, "doc_h": v[1], "inner_width": got}));
        } else if now() - t0 > 5000.0 {
            reply(json!({"error": "zoom not applied", "inner_width": got}));
        } else {
            let when = DispatchTime::try_from(Duration::from_millis(1)).unwrap();
            let _ = DispatchQueue::main().after(when, move || poll_zoom(t0, inner));
        }
    });
}

/// Find in page with app-injected script (works with page JavaScript off): every match is marked through the CSS
/// Custom Highlight API, so the DOM is not touched; the n-th match is the current one. Replies count and its y.
fn find(c: &Value) {
    let t0 = now();
    let q = serde_json::to_string(c["q"].as_str().unwrap_or("")).unwrap();
    let n = c["n"].as_i64().unwrap_or(0);
    let js = format!(r#"(() => {{
  if (!document.getElementById('peek-find-style')) {{
    const st = document.createElement('style'); st.id = 'peek-find-style';
    st.textContent = '::highlight(peek-find){{background-color:rgba(249,226,175,.35)}} ::highlight(peek-cur){{background-color:#f9e2af;color:#11111b}}';
    document.head.appendChild(st);
  }}
  const q = {q}.toLowerCase(); const ranges = [];
  if (q) {{
    const w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    for (let t = w.nextNode(); t; t = w.nextNode()) {{
      const s = t.data.toLowerCase(); let i = s.indexOf(q);
      while (i >= 0) {{ const r = new Range(); r.setStart(t, i); r.setEnd(t, i + q.length); ranges.push(r); i = s.indexOf(q, i + q.length); }}
    }}
  }}
  CSS.highlights.set('peek-find', new Highlight(...ranges));
  if (!ranges.length) {{ CSS.highlights.delete('peek-cur'); return JSON.stringify([0, -1]); }}
  const cur = ranges[(({n} % ranges.length) + ranges.length) % ranges.length];
  CSS.highlights.set('peek-cur', new Highlight(cur));
  return JSON.stringify([ranges.length, Math.round(cur.getBoundingClientRect().top + window.scrollY)]);
}})()"#);
    eval(&js, move |s| {
        let v: Value = s.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or(Value::Null);
        reply(json!({"cmd": "find", "ms": (now() - t0) as i64, "count": v[0], "y": v[1]}));
    });
}

fn handle(c: Value) {
    match c["cmd"].as_str() {
        Some("load") => load(&c),
        Some("size") => size(&c),
        Some("frame") => frame(&c),
        Some("zoom") => zoom(&c),
        Some("find") => find(&c),
        Some("eval") => {
            let js = format!("JSON.stringify((() => {{ {} }})())", c["js"].as_str().unwrap_or(""));
            eval(&js, |s| reply(json!({"cmd": "eval", "result": s})));
        }
        Some("quit") => std::process::exit(0),
        _ => reply(json!({"error": "unknown command"})),
    }
}

fn main() {
    START.set(Instant::now()).unwrap();
    let mtm = MainThreadMarker::new().unwrap();
    let app = NSApplication::sharedApplication(mtm);
    app.setActivationPolicy(NSApplicationActivationPolicy::Accessory);
    let frame = NSRect::new(NSPoint::new(0.0, 0.0), NSSize::new(1000.0, 1300.0));
    let jsoff = std::env::args().any(|a| a == "--jsoff");
    JSOFF.set(jsoff).ok();
    let config = unsafe { WKWebViewConfiguration::new(mtm) };
    if jsoff {
        unsafe { config.defaultWebpagePreferences().setAllowsContentJavaScript(false) };
    }
    let web = unsafe { WKWebView::initWithFrame_configuration(mtm.alloc(), frame, &config) };
    ST.with(|s| *s.borrow_mut() = Some(State { web, width: 1000.0, height: 1300.0, loads: 0, maps: HashMap::new() }));
    std::thread::spawn(|| {
        for line in std::io::stdin().lock().lines() {
            let Ok(line) = line else { break };
            let Ok(c) = serde_json::from_str::<Value>(&line) else { continue };
            DispatchQueue::main().exec_async(move || handle(c));
        }
        DispatchQueue::main().exec_async(|| std::process::exit(0));
    });
    reply(json!({"cmd": "start", "pid": std::process::id()}));
    app.run();
}
