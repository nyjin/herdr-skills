//! File change events (FSEvents through `notify`) for the shown file: its folder is watched (editors and Claude
//! often save by writing a new file and renaming it over the old one), events are filtered to the file's name,
//! and `on_change` runs once things have been quiet for 300 ms.
use notify::{RecursiveMode, Watcher as _};
use std::io;
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

const QUIET: Duration = Duration::from_millis(300);

/// Keeps the subscription alive; dropping it stops watching.
pub struct Watcher {
    _inner: notify::RecommendedWatcher,
    stop: Arc<AtomicBool>,
}

impl Drop for Watcher {
    fn drop(&mut self) {
        self.stop.store(true, Ordering::SeqCst);
    }
}

pub fn watch(path: &Path, on_change: impl Fn() + Send + 'static) -> io::Result<Watcher> {
    let name = path.file_name().ok_or_else(|| io::Error::other("no file name"))?.to_os_string();
    let dir = path.parent().filter(|d| !d.as_os_str().is_empty()).unwrap_or(Path::new(".")).to_path_buf();
    let last: Arc<Mutex<Option<Instant>>> = Arc::new(Mutex::new(None));
    let seen = last.clone();
    let mut inner = notify::recommended_watcher(move |res: notify::Result<notify::Event>| {
        if let Ok(ev) = res {
            if ev.paths.iter().any(|p| p.file_name() == Some(name.as_os_str())) {
                *seen.lock().unwrap() = Some(Instant::now());
            }
        }
    })
    .map_err(io::Error::other)?;
    inner.watch(&dir, RecursiveMode::NonRecursive).map_err(io::Error::other)?;
    let stop = Arc::new(AtomicBool::new(false));
    let stopped = stop.clone();
    std::thread::spawn(move || {
        while !stopped.load(Ordering::SeqCst) {
            std::thread::sleep(Duration::from_millis(50));
            let due = {
                let mut l = last.lock().unwrap();
                match *l {
                    Some(t) if t.elapsed() >= QUIET => {
                        *l = None;
                        true
                    }
                    _ => false,
                }
            };
            if due {
                on_change();
            }
        }
    });
    Ok(Watcher { _inner: inner, stop })
}
