//! Put a PNG on the clipboard (screenshots).
use objc2_app_kit::{NSPasteboard, NSPasteboardTypePNG};
use objc2_foundation::NSData;
use std::io;
use std::path::Path;

pub fn copy_png(path: &Path) -> io::Result<()> {
    let bytes = std::fs::read(path)?;
    let board = NSPasteboard::generalPasteboard();
    board.clearContents();
    if board.setData_forType(Some(&NSData::with_bytes(&bytes)), unsafe { NSPasteboardTypePNG }) {
        Ok(())
    } else {
        Err(io::Error::other("the clipboard refused the image"))
    }
}
