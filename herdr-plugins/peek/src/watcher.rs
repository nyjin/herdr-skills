//! `peek watch`: the background process behind select to open, one per herdr server. Rules: the design's "Select to
//! open".
//!
//! herdr gives plugins no selection event, but `copy_on_select` puts a selection on the clipboard. The watcher
//! looks at the clipboard's change count every 150 ms and, after a change, hands the text to
//! `link::run_select`. The text stays in memory: only opened paths and errors reach `watch.log`.
//!
//! herdr reads a plugin command's stdout and stderr to the end, so the watcher is started with both on
//! `/dev/null`, in a process group of its own, by `peek watch --spawn`; that returns at once, from a `[[startup]]`
//! hook or from any other peek run that finds no watcher (`ensure_running`). It exits when the server's socket
//! stops answering, or when the peek binary is replaced (the next peek run starts the new one).
use crate::{link, state};
use sha2::{Digest, Sha256};
use std::fs::{self, File, OpenOptions};
use std::io::{self, Write};
use std::os::fd::AsRawFd;
use std::os::unix::net::UnixStream;
use std::os::unix::process::CommandExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Stdio};
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

const TICK: Duration = Duration::from_millis(150);
/// How often the watcher checks the server and its binary; `$PEEK_WATCH_CHECK_MS` (tests) shortens it.
const CHECK_EVERY: Duration = Duration::from_secs(5);
/// Failed socket checks in a row before the watcher decides the server is gone.
const MISSES: u32 = 2;

/// The system clipboard as the watcher sees it.
pub trait Clipboard {
    /// Goes up with every write to the clipboard; reading it does not read the contents.
    fn change_count(&self) -> isize;
    fn text(&self) -> Option<String>;
}

/// Tells a clipboard change from the previous look; what was there when it started does not count.
pub struct Poll {
    last: isize,
}

impl Poll {
    pub fn new(clip: &impl Clipboard) -> Self {
        Poll { last: clip.change_count() }
    }

    pub fn changed(&mut self, clip: &impl Clipboard) -> bool {
        let now = clip.change_count();
        let changed = now != self.last;
        self.last = now;
        changed
    }
}

/// Runs until the herdr server behind `$HERDR_SOCKET_PATH` goes away. Returns at once when another watcher holds
/// this server's lock.
pub fn run(clip: &impl Clipboard) -> io::Result<()> {
    let socket = socket_path().ok_or_else(|| {
        io::Error::new(io::ErrorKind::InvalidInput, "HERDR_SOCKET_PATH is not set: peek watch runs under herdr")
    })?;
    let Some(_lock) = try_lock(&lock_path(&socket))? else { return Ok(()) };
    let exe = std::env::current_exe()?;
    let built = modified(&exe);
    let mut log = Log::open();
    log.line("started");

    let every = std::env::var("PEEK_WATCH_CHECK_MS")
        .ok()
        .and_then(|ms| ms.parse().ok())
        .map_or(CHECK_EVERY, Duration::from_millis);
    let mut poll = Poll::new(clip);
    let mut misses = 0;
    let mut next_check = Instant::now() + every;
    loop {
        thread::sleep(TICK);
        if poll.changed(clip) && state::select_enabled() {
            let seen = Instant::now();
            if let Some(text) = clip.text() {
                match link::run_select(&text) {
                    Ok(Some(opened)) => log.line(&format!("opened {opened} ({} ms)", seen.elapsed().as_millis())),
                    Ok(None) => {}
                    Err(e) => log.line(&format!("error: {e}")),
                }
            }
        }
        if Instant::now() >= next_check {
            next_check = Instant::now() + every;
            misses = if UnixStream::connect(&socket).is_ok() { 0 } else { misses + 1 };
            if misses >= MISSES {
                log.line("herdr server gone; exiting");
                return Ok(());
            }
            if modified(&exe) != built {
                log.line("peek binary replaced; exiting");
                return Ok(());
            }
        }
    }
}

/// Starts the watcher detached (stdin, stdout and stderr on `/dev/null`, its own process group) and returns.
pub fn spawn() -> io::Result<()> {
    Command::new(std::env::current_exe()?)
        .arg("watch")
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .process_group(0)
        .spawn()
        .map(|_| ())
}

/// Starts a watcher for this herdr server when none runs. Through `peek watch --spawn`, which returns at once, so
/// the watcher is no child of a long-lived caller. Does nothing outside herdr; failures are ignored.
pub fn ensure_running() {
    let Some(socket) = socket_path() else { return };
    // Free lock: no watcher. Let go of it at once; the new watcher takes it (and of two racing, one exits).
    if !matches!(try_lock(&lock_path(&socket)), Ok(Some(_))) {
        return;
    }
    let Ok(exe) = std::env::current_exe() else { return };
    let _ = Command::new(exe)
        .args(["watch", "--spawn"])
        .stdin(Stdio::null())
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status();
}

fn socket_path() -> Option<PathBuf> {
    std::env::var_os("HERDR_SOCKET_PATH").filter(|s| !s.is_empty()).map(PathBuf::from)
}

/// `<state dir>/watch-<hash of the socket path>.lock`: one watcher per herdr server.
pub fn lock_path(socket: &Path) -> PathBuf {
    let hash = Sha256::digest(socket.as_os_str().as_encoded_bytes());
    let hex: String = hash.iter().take(6).map(|b| format!("{b:02x}")).collect();
    state::state_dir().join(format!("watch-{hex}.lock"))
}

/// An exclusive `flock` on `path`, held while the returned file is open; `None` when another process holds it.
pub fn try_lock(path: &Path) -> io::Result<Option<File>> {
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir)?;
    }
    let file = OpenOptions::new().create(true).truncate(false).write(true).open(path)?;
    // SAFETY: flock(2) on a descriptor this function owns; no pointers.
    let held = unsafe { libc::flock(file.as_raw_fd(), libc::LOCK_EX | libc::LOCK_NB) } == 0;
    Ok(held.then_some(file))
}

fn modified(path: &Path) -> Option<SystemTime> {
    fs::metadata(path).and_then(|m| m.modified()).ok()
}

/// `<state dir>/watch.log`, started afresh by each watcher. Never holds clipboard text, only what was opened.
struct Log(Option<File>);

impl Log {
    fn open() -> Self {
        Log(File::create(state::state_dir().join("watch.log")).ok())
    }

    fn line(&mut self, text: &str) {
        let ms = SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |d| d.as_millis());
        if let Some(file) = &mut self.0 {
            let _ = writeln!(file, "{ms} {text}");
        }
    }
}
