//! Select to open: a selection herdr copied to the clipboard (`copy_on_select`), matched to the pane that shows it
//! and resolved like a click. Rules: the design's "Select to open".
//!
//! A selection has no link handler pattern in front of it, so the text must look like a path, and nothing is judged
//! by script: when the text as selected resolves to nothing, characters are dropped from its end (a Korean particle
//! written right after a path) and the file system decides.
use crate::page::{kind_of, FileKind};
use crate::resolve::{self, Context};
use regex::Regex;
use std::fs::File;
use std::io::Read;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;

/// The longest clipboard text that is looked at, in characters.
pub const MAX_CHARS: usize = 1024;
/// How many characters may be dropped from the end of a selection.
pub const MAX_TRIM: usize = 4;
/// How much of a file is read to tell text from binary.
const SNIFF: usize = 8 * 1024;

static EXTENSION: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"\.\w{1,10}$").unwrap());

/// A pane on screen and the text it shows (`herdr pane read --source visible`).
pub struct Screen<'a> {
    pub pane: &'a str,
    pub focused: bool,
    pub text: &'a str,
}

/// The clipboard text when it can be a selected path: one line of 1 to `MAX_CHARS` characters without control
/// characters, trimmed.
pub fn usable(text: &str) -> Option<&str> {
    let t = text.trim();
    let ok = !t.is_empty() && t.chars().count() <= MAX_CHARS && !t.chars().any(char::is_control);
    ok.then_some(t)
}

/// Whether `text` is on `screen`: in one row, or in the rows joined without line breaks (a wrapped long line).
pub fn on_screen(text: &str, screen: &str) -> bool {
    screen.lines().any(|row| row.contains(text)) || screen.lines().collect::<String>().contains(text)
}

/// The pane the selection was made in: of the panes showing `text`, the focused one, else the first.
pub fn source_pane<'a>(text: &str, screens: &[Screen<'a>]) -> Option<&'a str> {
    let showing: Vec<&Screen<'a>> = screens.iter().filter(|s| on_screen(text, s.text)).collect();
    showing.iter().find(|s| s.focused).or(showing.first()).map(|s| s.pane)
}

/// The text as selected, then with 1 to `MAX_TRIM` characters dropped from its end.
pub fn forms(text: &str) -> Vec<&str> {
    let ends: Vec<usize> = text.char_indices().map(|(i, _)| i).chain([text.len()]).collect();
    ends.iter().rev().take(MAX_TRIM + 1).map(|&end| &text[..end]).filter(|f| !f.is_empty()).collect()
}

/// Whether a form looks like a path: it holds a `/`, ends in a file extension, or ends in a `:line`.
pub fn path_shaped(form: &str) -> bool {
    let (t, line) = resolve::split_line(form);
    line.is_some() || t.contains('/') || EXTENSION.is_match(&t)
}

/// What a selection opens: the files of the first form that is path-shaped and resolves for `ctx` (binary files
/// other than images left out), with its `:line`. `None` for a web address (that is Ctrl+click's) and for
/// anything else that is not a file.
pub fn resolve(text: &str, ctx: &Context) -> Option<(Vec<PathBuf>, Option<u32>)> {
    for form in forms(text) {
        let (t, line) = resolve::split_line(form);
        if t.starts_with("http://") || t.starts_with("https://") {
            return None;
        }
        if !path_shaped(form) {
            continue;
        }
        let found: Vec<PathBuf> = resolve::candidates(form, ctx).into_iter().filter(|p| !is_binary(p)).collect();
        if !found.is_empty() {
            return Some((found, line));
        }
    }
    None
}

/// A file that is not an image and has a NUL byte in its first 8 KiB.
pub fn is_binary(path: &Path) -> bool {
    if matches!(kind_of(path), FileKind::Image | FileKind::Svg) {
        return false;
    }
    let Ok(file) = File::open(path) else { return false };
    let mut head = Vec::with_capacity(SNIFF);
    file.take(SNIFF as u64).read_to_end(&mut head).is_ok() && head.contains(&0)
}
