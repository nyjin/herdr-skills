//! `peek link` (the link handler action) and `peek action <name>` (herdr actions). (Task 2)
use std::io;

/// Commands a herdr action can send to a viewer through `ViewState.command`.
pub const ACTIONS: [&str; 9] =
    ["toggle", "reload", "find", "zoom-in", "zoom-out", "zoom-reset", "screenshot", "browser", "back"];

/// Classify and resolve the clicked text from pane `pane`, write the state, open the viewer if needed.
pub fn run_link(_clicked: &str, _pane: &str) -> io::Result<()> {
    Err(io::ErrorKind::Unsupported.into())
}

/// Send `name` (one of `ACTIONS`) to the viewer that belongs to `pane` (a Claude pane or the viewer itself).
pub fn run_action(_name: &str, _pane: &str) -> io::Result<()> {
    Err(io::ErrorKind::Unsupported.into())
}
