//! Link cache: `~/.cache/peek/links/<sha256 of the URL>.json` holds the fetched page with its fetch time; the
//! page's attachments sit next to it in `<sha256 of the URL>/`.
use crate::fetch::Fetched;
use sha2::{Digest, Sha256};
use std::fs;
use std::io;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};

/// `~/.cache/peek/links`.
pub fn links_dir() -> PathBuf {
    let home = std::env::var_os("HOME").map(PathBuf::from).unwrap_or_else(|| PathBuf::from("/"));
    home.join(".cache/peek/links")
}

/// Hex SHA-256 of `text`.
pub fn key(text: &str) -> String {
    format!("{:x}", Sha256::digest(text.as_bytes()))
}

pub fn load(dir: &Path, url: &str) -> Option<Fetched> {
    let v: serde_json::Value = serde_json::from_slice(&fs::read(page_file(dir, url)).ok()?).ok()?;
    let field = |k: &str| v[k].as_str().map(String::from);
    Some(Fetched { title: field("title")?, html: field("html")?, url: field("url")?, fetched_at: field("fetched_at")? })
}

/// Written atomically, so a reader never sees half a page.
pub fn store(dir: &Path, url: &str, page: &Fetched) -> io::Result<()> {
    make_dir(dir)?;
    let json = serde_json::json!({ "title": page.title, "html": page.html, "url": page.url, "fetched_at": page.fetched_at });
    let file = page_file(dir, url);
    let tmp = dir.join(format!(".{}.{}.tmp", key(url), std::process::id()));
    fs::write(&tmp, json.to_string())?;
    fs::rename(&tmp, file)
}

/// Where the page's attachments go.
pub fn files_dir(dir: &Path, url: &str) -> PathBuf {
    dir.join(key(url))
}

/// The cache holds private content: folders it creates are the user's only.
pub(crate) fn make_dir(path: &Path) -> io::Result<()> {
    fs::DirBuilder::new().recursive(true).mode(0o700).create(path)
}

fn page_file(dir: &Path, url: &str) -> PathBuf {
    dir.join(format!("{}.json", key(url)))
}
