//! Put a PNG on the clipboard (screenshots). (Task 6)
use std::io;
use std::path::Path;

pub fn copy_png(_path: &Path) -> io::Result<()> {
    Err(io::ErrorKind::Unsupported.into())
}
