//! The clipboard: a PNG put on it (screenshots), and the watcher's view of it (select to open).
use objc2::rc::autoreleasepool;
use objc2_app_kit::{NSPasteboard, NSPasteboardTypePNG, NSPasteboardTypeString};
use objc2_foundation::NSData;
use std::io;
use std::path::Path;

/// The general pasteboard for `watcher::run`. Each look runs in its own autorelease pool: the watcher runs for
/// hours without an event loop to drain one.
pub struct Pasteboard;

impl crate::watcher::Clipboard for Pasteboard {
    fn change_count(&self) -> isize {
        autoreleasepool(|_| NSPasteboard::generalPasteboard().changeCount())
    }

    fn text(&self) -> Option<String> {
        autoreleasepool(|_| {
            let text = NSPasteboard::generalPasteboard().stringForType(unsafe { NSPasteboardTypeString })?;
            Some(text.to_string())
        })
    }
}

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
