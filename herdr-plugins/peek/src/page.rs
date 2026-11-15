//! The page the viewer loads: markdown, source, image, SVG, HTML or fetched content in peek's template (theme,
//! font size, CSP, find highlight styles). (Task 3)
use crate::fetch::Fetched;
use crate::state::Mode;
use std::io;
use std::path::{Path, PathBuf};

pub enum Doc {
    File(PathBuf),
    Fetched(Fetched),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FileKind {
    Markdown,
    Source,
    Image,
    Svg,
    Html,
    Text,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PageOptions {
    /// Catppuccin Mocha when true, Latte when false.
    pub dark: bool,
    /// Base font size in CSS px.
    pub font_px: f32,
    pub mode: Mode,
    /// Line to mark and scroll to (source view).
    pub line: Option<u32>,
}

pub fn kind_of(_path: &Path) -> FileKind {
    FileKind::Text
}

pub fn build(_doc: &Doc, _opts: &PageOptions) -> io::Result<String> {
    Err(io::ErrorKind::Unsupported.into())
}

/// The same page for a browser: absolute `file://` references instead of a base inside the viewer's pages folder.
pub fn browser_page(_doc: &Doc, _opts: &PageOptions) -> io::Result<String> {
    Err(io::ErrorKind::Unsupported.into())
}

/// `file://` URL of a page file, percent-encoded, with `?peek=<marker>` so readiness can tell loads apart.
pub fn page_url(_path: &Path, _marker: u64) -> String {
    String::new()
}
