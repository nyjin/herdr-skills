//! Hidden `WKWebView` with page scripts off: load a page and tell when it is ready, capture a band of it into
//! shared memory, wait for a new width to take effect, zoom, and run peek's own scripts. Main thread only; every
//! answer comes back through a callback on the main queue.
use crate::script;
use block2::RcBlock;
use dispatch2::{DispatchQueue, DispatchTime};
use objc2::rc::Retained;
use objc2::runtime::AnyObject;
use objc2::MainThreadMarker;
use objc2_app_kit::{NSBitmapImageFileType, NSBitmapImageRep, NSImage};
use objc2_core_foundation::{CGPoint, CGRect, CGSize};
use objc2_core_graphics::{kCGColorSpaceSRGB, CGBitmapContextCreate, CGColorSpace, CGContext, CGImageAlphaInfo};
use objc2_foundation::{NSDictionary, NSError, NSNumber, NSPoint, NSRect, NSSize, NSString, NSURL};
use objc2_web_kit::{WKSnapshotConfiguration, WKWebView, WKWebViewConfiguration};
use std::cell::RefCell;
use std::rc::Rc;
use std::time::{Duration, Instant};

/// Run `f` on the main queue after `ms` milliseconds.
pub fn after(ms: u64, f: impl FnOnce() + Send + 'static) {
    let _ = DispatchQueue::main().after(DispatchTime::try_from(Duration::from_millis(ms)).unwrap(), f);
}

pub struct LoadInfo {
    pub doc_h: f64,
    /// A suggested first scroll position in CSS px (the marked source line), 0 otherwise.
    pub top_hint: f64,
}

#[derive(Clone)]
pub struct Renderer {
    web: Retained<WKWebView>,
}

impl Renderer {
    pub fn new(mtm: MainThreadMarker) -> Renderer {
        let config = unsafe { WKWebViewConfiguration::new(mtm) };
        // Page scripts never run; peek's own scripts still do (evaluateJavaScript).
        unsafe { config.defaultWebpagePreferences().setAllowsContentJavaScript(false) };
        let frame = NSRect::new(NSPoint::new(0.0, 0.0), NSSize::new(800.0, 600.0));
        let web = unsafe { WKWebView::initWithFrame_configuration(mtm.alloc(), frame, &config) };
        Renderer { web }
    }

    pub fn set_frame(&self, w_css: f64, h_css: f64) {
        self.web.setFrameSize(NSSize::new(w_css, h_css));
    }

    pub fn frame(&self) -> (f64, f64) {
        let f = self.web.frame();
        (f.size.width, f.size.height)
    }

    /// Run `js` (which evaluates to a string) and hand its result to `done`.
    pub fn eval(&self, js: &str, done: impl FnOnce(Option<String>) + 'static) {
        let done = RefCell::new(Some(done));
        let block = RcBlock::new(move |r: *mut AnyObject, _e: *mut NSError| {
            // Safety: peek's scripts all evaluate to a string, so a non-null result is an NSString.
            let s = (!r.is_null()).then(|| unsafe { &*(r as *const NSString) }.to_string());
            if let Some(f) = done.borrow_mut().take() {
                f(s)
            }
        });
        unsafe { self.web.evaluateJavaScript_completionHandler(&NSString::from_str(js), Some(&block)) };
    }

    /// Load the page at `url` (a `file://` URL carrying `?peek=<marker>`); `done` runs once the page is current and
    /// complete, or with an error after 30 s.
    pub fn load(&self, url: &str, marker: u64, done: impl FnOnce(Result<LoadInfo, String>) + 'static) {
        let Some(page) = NSURL::URLWithString(&NSString::from_str(url)) else {
            return done(Err(format!("bad page URL {url}")));
        };
        // The read-access root must cover both the page and the document's folder (relative images).
        let root = NSURL::from_file_path("/").unwrap();
        unsafe { self.web.loadFileURL_allowingReadAccessToURL(&page, &root) };
        self.poll_ready(marker, Instant::now(), Box::new(done));
    }

    fn poll_ready(&self, marker: u64, t0: Instant, done: Box<dyn FnOnce(Result<LoadInfo, String>)>) {
        let me = self.clone();
        self.eval(&script::ready(marker), move |s| {
            let v: serde_json::Value = s.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
            if v[0] == true {
                return done(Ok(LoadInfo { doc_h: v[1].as_f64().unwrap_or(0.0), top_hint: v[2].as_f64().unwrap_or(0.0) }));
            }
            if t0.elapsed() > Duration::from_secs(30) {
                return done(Err("the page did not finish loading in 30 s".into()));
            }
            let me = SendBox(me);
            let done = SendBox(done);
            after(3, move || {
                let (me, done) = (me.get(), done.get());
                me.poll_ready(marker, t0, done)
            });
        });
    }

    /// After a frame or zoom change: `done(doc_h)` once the page reports `inner_width` CSS px.
    pub fn wait_width(&self, inner_width: f64, done: impl FnOnce(f64) + 'static) {
        self.poll_width(inner_width, Instant::now(), Box::new(done));
    }

    fn poll_width(&self, inner_width: f64, t0: Instant, done: Box<dyn FnOnce(f64)>) {
        let me = self.clone();
        self.eval("JSON.stringify([window.innerWidth, document.documentElement.scrollHeight])", move |s| {
            let v: serde_json::Value = s.and_then(|s| serde_json::from_str(&s).ok()).unwrap_or_default();
            let w = v[0].as_f64().unwrap_or(-1.0);
            if (w - inner_width).abs() <= 1.0 || t0.elapsed() > Duration::from_secs(5) {
                return done(v[1].as_f64().unwrap_or(0.0));
            }
            let me = SendBox(me);
            let done = SendBox(done);
            after(1, move || {
                let (me, done) = (me.get(), done.get());
                me.poll_width(inner_width, t0, done)
            });
        });
    }

    pub fn set_zoom(&self, percent: u32) {
        unsafe { self.web.setPageZoom(percent as f64 / 100.0) };
    }

    /// Capture the band of the page from `top_css` (as tall as the view's frame) into a new POSIX shared memory
    /// object `shm_name` of `w_px` x `h_px` RGBA, the page background `bg` where the document has ended.
    pub fn capture(&self, top_css: f64, w_px: u32, h_px: u32, bg: [u8; 3], shm_name: String, done: impl FnOnce(Result<(), String>) + 'static) {
        let me = self.clone();
        let done = Rc::new(RefCell::new(Some(Box::new(done) as Box<dyn FnOnce(Result<(), String>)>)));
        self.eval(&format!("window.scrollTo(0, {top_css}); JSON.stringify(window.scrollY)"), move |s| {
            let scroll_y: f64 = s.and_then(|s| s.parse().ok()).unwrap_or(top_css);
            let (vw, vh) = me.frame();
            // Near the document's end the view cannot scroll as far as asked: take the part below the offset.
            let offset = (top_css - scroll_y).clamp(0.0, vh);
            let band_h = vh - offset;
            let mtm = MainThreadMarker::new().unwrap();
            let cfg = unsafe { WKSnapshotConfiguration::new(mtm) };
            unsafe {
                cfg.setRect(CGRect::new(CGPoint::new(0.0, offset), CGSize::new(vw, band_h.max(1.0))));
                cfg.setSnapshotWidth(Some(&NSNumber::new_f64(vw)));
                cfg.setAfterScreenUpdates(true);
            }
            let image_h_px = ((band_h / vh) * h_px as f64).round() as usize;
            let finish = done.clone();
            let block = RcBlock::new(move |img: *mut NSImage, _e: *mut NSError| {
                let result = if img.is_null() {
                    Err("snapshot failed".to_string())
                } else {
                    draw_into_shm(unsafe { &*img }, &shm_name, w_px as usize, h_px as usize, image_h_px, bg)
                };
                if let Some(f) = finish.borrow_mut().take() {
                    f(result)
                }
            });
            unsafe { me.web.takeSnapshotWithConfiguration_completionHandler(Some(&cfg), &block) };
        });
    }
}

impl Renderer {
    /// Write the band of the page from `top_css`, `h_css` tall, as a PNG at `path` (screen pixels).
    pub fn snapshot_png(&self, top_css: f64, h_css: f64, path: std::path::PathBuf, done: impl FnOnce(Result<(), String>) + 'static) {
        let me = self.clone();
        let done = RefCell::new(Some(done));
        self.eval(&format!("window.scrollTo(0, {top_css}); JSON.stringify(window.scrollY)"), move |s| {
            let scroll_y: f64 = s.and_then(|s| s.parse().ok()).unwrap_or(top_css);
            let (vw, vh) = me.frame();
            let offset = (top_css - scroll_y).clamp(0.0, vh);
            let mtm = MainThreadMarker::new().unwrap();
            let cfg = unsafe { WKSnapshotConfiguration::new(mtm) };
            unsafe {
                cfg.setRect(CGRect::new(CGPoint::new(0.0, offset), CGSize::new(vw, h_css.min(vh - offset).max(1.0))));
                cfg.setSnapshotWidth(Some(&NSNumber::new_f64(vw)));
                cfg.setAfterScreenUpdates(true);
            }
            let block = RcBlock::new(move |img: *mut NSImage, _e: *mut NSError| {
                let result = if img.is_null() { Err("snapshot failed".to_string()) } else { write_png(unsafe { &*img }, &path) };
                if let Some(f) = done.borrow_mut().take() {
                    f(result)
                }
            });
            unsafe { me.web.takeSnapshotWithConfiguration_completionHandler(Some(&cfg), &block) };
        });
    }
}

fn write_png(image: &NSImage, path: &std::path::Path) -> Result<(), String> {
    let tiff = image.TIFFRepresentation().ok_or("no image data")?;
    let rep = NSBitmapImageRep::imageRepWithData(&tiff).ok_or("no bitmap")?;
    let png = unsafe { rep.representationUsingType_properties(NSBitmapImageFileType::PNG, &NSDictionary::new()) }.ok_or("PNG encoding failed")?;
    std::fs::write(path, png.to_vec()).map_err(|e| e.to_string())
}

/// Values handed to `dispatch` closures, which must be `Send`. Only ever used on the main thread.
struct SendBox<T>(T);
unsafe impl<T> Send for SendBox<T> {}

impl<T> SendBox<T> {
    /// Taking the whole box (not its field) keeps closures capturing the `Send` wrapper.
    fn get(self) -> T {
        self.0
    }
}

/// Fill a new shared memory object with the page background, then draw the snapshot over its top `image_h` rows.
fn draw_into_shm(image: &NSImage, name: &str, w: usize, h: usize, image_h: usize, bg: [u8; 3]) -> Result<(), String> {
    let Some(cg) = (unsafe { image.CGImageForProposedRect_context_hints(std::ptr::null_mut(), None, None) }) else {
        return Err("no image in the snapshot".into());
    };
    let len = w * h * 4;
    let c = std::ffi::CString::new(name).map_err(|e| e.to_string())?;
    unsafe {
        let fd = libc::shm_open(c.as_ptr(), libc::O_CREAT | libc::O_RDWR | libc::O_EXCL, 0o600);
        if fd < 0 {
            return Err(format!("shm_open {name}: {}", std::io::Error::last_os_error()));
        }
        let ok = libc::ftruncate(fd, len as libc::off_t) == 0;
        let p = if ok { libc::mmap(std::ptr::null_mut(), len, libc::PROT_READ | libc::PROT_WRITE, libc::MAP_SHARED, fd, 0) } else { libc::MAP_FAILED };
        libc::close(fd);
        if p == libc::MAP_FAILED {
            libc::shm_unlink(c.as_ptr());
            return Err(format!("mapping {name} failed"));
        }
        let px = std::slice::from_raw_parts_mut(p as *mut u8, len);
        for chunk in px.chunks_exact_mut(4) {
            chunk.copy_from_slice(&[bg[0], bg[1], bg[2], 255]);
        }
        let space = CGColorSpace::with_name(Some(kCGColorSpaceSRGB));
        if let Some(ctx) = CGBitmapContextCreate(p, w, h, 8, w * 4, space.as_deref(), CGImageAlphaInfo::PremultipliedLast.0) {
            // Bitmap context y grows upwards: the top `image_h` rows of the buffer are y = h - image_h .. h.
            let rect = CGRect::new(CGPoint::new(0.0, (h - image_h.min(h)) as f64), CGSize::new(w as f64, image_h.min(h) as f64));
            CGContext::draw_image(Some(&ctx), rect, Some(&cg));
        }
        libc::munmap(p, len);
    }
    Ok(())
}
