//! The viewer pane (`peek viewer`): follows the source pane's state file and shows each item. (Tasks 5 and 6)
use std::io;

pub fn run(_source: &str) -> io::Result<()> {
    Err(io::Error::new(io::ErrorKind::Unsupported, "the viewer is not built yet"))
}
