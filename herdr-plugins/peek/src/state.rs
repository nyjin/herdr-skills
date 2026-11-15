//! What each viewer shows (one state file per source pane), viewer bookkeeping, the zoom preference and the
//! private `/tmp` folders.
//!
//! The state folder holds, per source pane `<source>` (a pane id, `/` written as `_`): `<source>.json` (the
//! `ViewState`), `<source>.viewer` (the viewer's pane id) and, while `peek link` checks for a viewer,
//! `<source>.lock`. `zoom` holds the zoom preference.
use serde::{Deserialize, Serialize};
use std::fs::{self, DirBuilder};
use std::io;
use std::os::unix::fs::{DirBuilderExt, MetadataExt, PermissionsExt};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicU64, Ordering};

const ZOOM_MIN: u32 = 50;
const ZOOM_MAX: u32 = 200;
const ZOOM_DEFAULT: u32 = 100;

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Mode {
    Rendered,
    Source,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Item {
    /// The path with the home folder as `~`, or the web address.
    pub label: String,
    pub path: Option<PathBuf>,
    pub url: Option<String>,
    pub line: Option<u32>,
}

/// Written by `peek link` / `peek action`, read by the viewer. A new `seq` means "look again".
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ViewState {
    /// Nanoseconds since the epoch, always larger than the previous state's.
    pub seq: u128,
    pub items: Vec<Item>,
    /// A click keeps the mode the state already holds; `peek action toggle` does not change it (the viewer runs
    /// the command).
    pub mode: Mode,
    /// One of `link::ACTIONS`, set by a herdr action for the viewer to run once: when it sees a new `seq`, not
    /// from the state it starts with. A click clears it.
    pub command: Option<String>,
}

/// `$PEEK_STATE_DIR` or `~/.local/state/peek`.
///
/// Fixed on purpose rather than herdr's per-plugin state folder: the link handler and the viewer pane must meet
/// in one folder.
pub fn state_dir() -> PathBuf {
    match std::env::var_os("PEEK_STATE_DIR") {
        Some(dir) if !dir.is_empty() => PathBuf::from(dir),
        _ => PathBuf::from(std::env::var_os("HOME").unwrap_or_default()).join(".local/state/peek"),
    }
}

/// `<state dir>/<source><ext>`.
pub(crate) fn state_file(source: &str, ext: &str) -> PathBuf {
    state_dir().join(format!("{}{ext}", source.replace('/', "_")))
}

pub fn read_state(source: &str) -> Option<ViewState> {
    serde_json::from_slice(&fs::read(state_file(source, ".json")).ok()?).ok()
}

/// Atomic write (temp file + rename).
pub fn write_state(source: &str, st: &ViewState) -> io::Result<()> {
    write_atomic(&state_file(source, ".json"), &serde_json::to_vec(st)?)
}

pub fn viewer_of(source: &str) -> Option<String> {
    let pane = fs::read_to_string(state_file(source, ".viewer")).ok()?;
    Some(pane.trim().to_string()).filter(|p| !p.is_empty())
}

pub fn set_viewer(source: &str, pane: &str) -> io::Result<()> {
    write_atomic(&state_file(source, ".viewer"), pane.as_bytes())
}

/// The source pane whose viewer is `pane`, if `pane` is a viewer.
pub fn source_of_viewer(pane: &str) -> Option<String> {
    if pane.is_empty() {
        return None;
    }
    fs::read_dir(state_dir()).ok()?.flatten().find_map(|entry| {
        let name = entry.file_name().into_string().ok()?;
        let source = name.strip_suffix(".viewer")?;
        let viewer = fs::read_to_string(entry.path()).ok()?;
        (viewer.trim() == pane).then(|| source.to_string())
    })
}

/// Claude's project folder name for a directory: every character outside `[A-Za-z0-9]` becomes `-`.
pub fn project_name(dir: &Path) -> String {
    dir.to_string_lossy().chars().map(|c| if c.is_ascii_alphanumeric() { c } else { '-' }).collect()
}

/// `/tmp/peek-<uid>/<project>/<session>` with `pages/`, `browser/` and `screenshots/` in it, all created 0700;
/// refused if any part is a link or not ours.
pub fn session_dir(project: &str, session: &str) -> io::Result<PathBuf> {
    for part in [project, session] {
        if part.is_empty() || part == "." || part == ".." || part.contains('/') {
            return Err(io::Error::new(io::ErrorKind::InvalidInput, format!("not a folder name: {part:?}")));
        }
    }
    // SAFETY: getuid(2) cannot fail and touches no memory.
    let uid = unsafe { libc::getuid() };
    let root = PathBuf::from(format!("/tmp/peek-{uid}"));
    let dir = root.join(project).join(session);
    for d in [root.clone(), root.join(project), dir.clone(), dir.join("pages"), dir.join("browser"), dir.join("screenshots")]
    {
        private_dir(&d, uid)?;
    }
    Ok(dir)
}

/// Creates `dir` 0700 or checks the one there: a real folder (not a link), ours, tightened to 0700.
fn private_dir(dir: &Path, uid: u32) -> io::Result<()> {
    match DirBuilder::new().mode(0o700).create(dir) {
        Ok(()) => {}
        Err(e) if e.kind() == io::ErrorKind::AlreadyExists => {}
        Err(e) => return Err(e),
    }
    let meta = fs::symlink_metadata(dir)?;
    if !meta.file_type().is_dir() {
        let what = if meta.file_type().is_symlink() { "a link" } else { "not a folder" };
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, format!("{} is {what}", dir.display())));
    }
    if meta.uid() != uid {
        return Err(io::Error::new(io::ErrorKind::PermissionDenied, format!("{} is not ours", dir.display())));
    }
    if meta.mode() & 0o777 != 0o700 {
        fs::set_permissions(dir, fs::Permissions::from_mode(0o700))?;
    }
    Ok(())
}

/// Page zoom in percent, 50..=200, default 100.
pub fn zoom() -> u32 {
    fs::read_to_string(state_dir().join("zoom"))
        .ok()
        .and_then(|text| text.trim().parse::<u32>().ok())
        .map_or(ZOOM_DEFAULT, |z| z.clamp(ZOOM_MIN, ZOOM_MAX))
}

/// Saves the zoom preference, held within 50..=200.
pub fn set_zoom(percent: u32) -> io::Result<()> {
    write_atomic(&state_dir().join("zoom"), percent.clamp(ZOOM_MIN, ZOOM_MAX).to_string().as_bytes())
}

/// Writes through a temp file in the same folder and renames it over `path`, so a reader never sees half a file.
fn write_atomic(path: &Path, bytes: &[u8]) -> io::Result<()> {
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    if let Some(dir) = path.parent() {
        fs::create_dir_all(dir)?;
    }
    let n = COUNTER.fetch_add(1, Ordering::Relaxed);
    let mut tmp = path.as_os_str().to_owned();
    tmp.push(format!(".{}.{n}.tmp", std::process::id()));
    fs::write(&tmp, bytes).and_then(|()| fs::rename(&tmp, path)).inspect_err(|_| {
        let _ = fs::remove_file(&tmp);
    })
}
