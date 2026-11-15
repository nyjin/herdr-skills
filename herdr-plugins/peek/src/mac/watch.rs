//! File change events (FSEvents through `notify`) for the shown file. (Task 6)
use std::io;
use std::path::Path;

/// Keeps the subscription alive; dropping it stops watching.
pub struct Watcher;

pub fn watch(_path: &Path, _on_change: impl Fn() + Send + 'static) -> io::Result<Watcher> {
    Err(io::ErrorKind::Unsupported.into())
}
