//! Calls to the herdr CLI: `$PEEK_HERDR` (may hold arguments, split on whitespace), `$HERDR_BIN_PATH` or `herdr`.
//! (Task 2)
use std::io;
use std::path::PathBuf;

#[derive(Clone, Debug, PartialEq)]
pub struct PaneInfo {
    pub pane_id: String,
    pub cwd: PathBuf,
    pub foreground_cwd: Option<PathBuf>,
    /// `agent_session.value` when a Claude session runs in the pane.
    pub session_id: Option<String>,
}

pub fn pane_get(_pane: &str) -> io::Result<PaneInfo> {
    Err(io::ErrorKind::Unsupported.into())
}

pub fn pane_ids() -> io::Result<Vec<String>> {
    Err(io::ErrorKind::Unsupported.into())
}

/// Opens the viewer pane to the right of `source` without taking focus; returns its pane id.
pub fn open_viewer(_source: &str) -> io::Result<String> {
    Err(io::ErrorKind::Unsupported.into())
}

/// A herdr notification; failures are ignored.
pub fn notify(_body: &str) {}
