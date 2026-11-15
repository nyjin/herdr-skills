//! `peek link` (the link handler action) and `peek action <name>` (herdr actions).
//!
//! Nothing opens without a click: `peek link` writes the source pane's state file and opens the viewer pane when
//! the source pane has none. The viewer follows the state file.
use crate::herdr;
use crate::resolve::{self, Context};
use crate::state::{self, Item, Mode, ViewState};
use crate::target::{classify, Target};
use std::fs::{self, OpenOptions};
use std::io;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::thread;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

/// Commands a herdr action can send to a viewer through `ViewState.command`.
pub const ACTIONS: [&str; 9] =
    ["toggle", "reload", "find", "zoom-in", "zoom-out", "zoom-reset", "screenshot", "browser", "back"];

/// How long a click waits for another click on the same pane to finish opening the viewer.
const LOCK_WAIT: Duration = Duration::from_secs(10);
/// A lock this old was left by a killed process.
const LOCK_STALE: Duration = Duration::from_secs(15);

/// Classify and resolve the clicked text from pane `pane`, write the state, open the viewer if needed.
pub fn run_link(clicked: &str, pane: &str) -> io::Result<()> {
    if pane.is_empty() {
        return Err(not_in_herdr("HERDR_PANE_ID"));
    }
    if clicked.trim().is_empty() {
        return Err(not_in_herdr("HERDR_PLUGIN_CLICKED_URL"));
    }
    let items = match classify(clicked) {
        // A web address that only looks like a file (…/blob/main/README.md) goes to the browser.
        Target::Path { text, .. } if text.starts_with("http://") || text.starts_with("https://") => {
            return open_in_browser(&text);
        }
        Target::Path { text, line } => {
            let ctx = context(&herdr::pane_get(pane)?);
            let found = resolve::candidates(&text, &ctx);
            if found.is_empty() {
                herdr::notify(&format!("File not found: {text}"));
                return Ok(());
            }
            found.into_iter().map(|p| Item { label: label(&p, &ctx.home), path: Some(p), url: None, line }).collect()
        }
        link => {
            let url = link.url().expect("a link target has a web address");
            vec![Item { label: url.clone(), path: None, url: Some(url), line: None }]
        }
    };
    show(pane, items)
}

/// Send `name` (one of `ACTIONS`) to the viewer that belongs to `pane` (a Claude pane or the viewer itself).
pub fn run_action(name: &str, pane: &str) -> io::Result<()> {
    if !ACTIONS.contains(&name) {
        let msg = format!("unknown action {name:?}; one of: {}", ACTIONS.join(", "));
        return Err(io::Error::new(io::ErrorKind::InvalidInput, msg));
    }
    if pane.is_empty() {
        return Err(not_in_herdr("HERDR_PANE_ID"));
    }
    let source = state::source_of_viewer(pane).unwrap_or_else(|| pane.to_string());
    let Some(mut st) = state::read_state(&source) else { return Ok(()) };
    st.seq = next_seq(Some(&st));
    st.command = Some(name.to_string());
    state::write_state(&source, &st)
}

fn not_in_herdr(var: &str) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidInput, format!("{var} is not set: peek link runs from a herdr link handler"))
}

fn context(pane: &herdr::PaneInfo) -> Context {
    let home = PathBuf::from(std::env::var_os("HOME").unwrap_or_default());
    // SAFETY: getuid(2) cannot fail and touches no memory.
    let uid = unsafe { libc::getuid() };
    Context {
        // foreground_cwd, not cwd: a session that moved into a worktree still has its old cwd.
        cwd: pane.foreground_cwd.clone().unwrap_or_else(|| pane.cwd.clone()),
        session_id: pane.session_id.clone(),
        tmp_root: PathBuf::from(format!("/private/tmp/claude-{uid}")),
        projects_root: home.join(".claude/projects"),
        home,
    }
}

fn label(path: &Path, home: &Path) -> String {
    match path.strip_prefix(home) {
        Ok(rest) if !home.as_os_str().is_empty() => format!("~/{}", rest.display()),
        _ => path.display().to_string(),
    }
}

/// `$PEEK_OPEN` (split on whitespace) or `open`, with the address.
fn open_in_browser(url: &str) -> io::Result<()> {
    let words: Vec<String> = match std::env::var("PEEK_OPEN") {
        Ok(v) if !v.trim().is_empty() => v.split_whitespace().map(String::from).collect(),
        _ => vec!["open".into()],
    };
    Command::new(&words[0]).args(&words[1..]).arg(url).status().map(|_| ())
}

fn show(source: &str, items: Vec<Item>) -> io::Result<()> {
    let prev = state::read_state(source);
    let st = ViewState {
        seq: next_seq(prev.as_ref()),
        items,
        mode: prev.map_or(Mode::Rendered, |p| p.mode),
        command: None,
    };
    state::write_state(source, &st)?;
    // Check and open under the lock, and record the new pane before letting go, so a click right behind this one
    // sees the viewer and does not open a second one.
    let _lock = SourceLock::take(source);
    if let Some(viewer) = state::viewer_of(source) {
        if herdr::pane_ids()?.contains(&viewer) {
            return Ok(());
        }
    }
    let pane = herdr::open_viewer(source)?;
    state::set_viewer(source, &pane)
}

/// Now in nanoseconds, and always past the previous state's `seq`.
fn next_seq(prev: Option<&ViewState>) -> u128 {
    let now = SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |d| d.as_nanos());
    prev.map_or(now, |p| now.max(p.seq + 1))
}

/// An `O_EXCL` file per source pane that serialises check-and-open; removed when dropped. Waits up to
/// `LOCK_WAIT`, then goes on without it rather than lose the click.
struct SourceLock(Option<PathBuf>);

impl SourceLock {
    fn take(source: &str) -> Self {
        let path = state::state_file(source, ".lock");
        let deadline = Instant::now() + LOCK_WAIT;
        loop {
            match OpenOptions::new().write(true).create_new(true).open(&path) {
                Ok(_) => return SourceLock(Some(path)),
                Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {
                    let age = fs::metadata(&path).and_then(|m| m.modified()).ok().and_then(|t| t.elapsed().ok());
                    if age.is_some_and(|a| a > LOCK_STALE) {
                        let _ = fs::remove_file(&path);
                        continue;
                    }
                }
                Err(_) => return SourceLock(None),
            }
            if Instant::now() > deadline {
                return SourceLock(None);
            }
            thread::sleep(Duration::from_millis(50));
        }
    }
}

impl Drop for SourceLock {
    fn drop(&mut self) {
        if let Some(path) = &self.0 {
            let _ = fs::remove_file(path);
        }
    }
}
