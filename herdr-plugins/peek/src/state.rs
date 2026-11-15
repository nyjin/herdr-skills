//! What each viewer shows (one state file per source pane), viewer bookkeeping, the zoom preference and the
//! private `/tmp` folders. (Task 2)
use serde::{Deserialize, Serialize};
use std::io;
use std::path::{Path, PathBuf};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub enum Mode {
    Rendered,
    Source,
}

#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Item {
    pub label: String,
    pub path: Option<PathBuf>,
    pub url: Option<String>,
    pub line: Option<u32>,
}

/// Written by `peek link` / `peek action`, read by the viewer. A new `seq` means "look again".
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ViewState {
    pub seq: u128,
    pub items: Vec<Item>,
    pub mode: Mode,
    /// One of `link::ACTIONS`, set by a herdr action for the viewer to run once.
    pub command: Option<String>,
}

/// `$PEEK_STATE_DIR` or `~/.local/state/peek`.
pub fn state_dir() -> PathBuf {
    PathBuf::new()
}

pub fn read_state(_source: &str) -> Option<ViewState> {
    None
}

/// Atomic write (temp file + rename).
pub fn write_state(_source: &str, _st: &ViewState) -> io::Result<()> {
    Err(io::ErrorKind::Unsupported.into())
}

pub fn viewer_of(_source: &str) -> Option<String> {
    None
}

pub fn set_viewer(_source: &str, _pane: &str) -> io::Result<()> {
    Err(io::ErrorKind::Unsupported.into())
}

/// The source pane whose viewer is `pane`, if `pane` is a viewer.
pub fn source_of_viewer(_pane: &str) -> Option<String> {
    None
}

/// Claude's project folder name for a directory: every character outside `[A-Za-z0-9]` becomes `-`.
pub fn project_name(_dir: &Path) -> String {
    String::new()
}

/// `/tmp/peek-<uid>/<project>/<session>`, created 0700; refused if any part is a link or not ours.
pub fn session_dir(_project: &str, _session: &str) -> io::Result<PathBuf> {
    Err(io::ErrorKind::Unsupported.into())
}

/// Page zoom in percent, 50..=200, default 100.
pub fn zoom() -> u32 {
    100
}

pub fn set_zoom(_percent: u32) -> io::Result<()> {
    Err(io::ErrorKind::Unsupported.into())
}
