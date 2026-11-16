//! Turn a clicked (possibly shortened) path into candidate files: working folder, scratchpad, transcript, git.
//! Rules: the design's "Path resolution".
//!
//! Claude Code often prints a path relative to its working folder, cut short with `…/`, or as a bare file name.
//! Candidates are gathered from every source at once and de-duplicated by real path; no source is trusted over
//! another. The caller decides what to do with zero, one or several of them.
use regex::Regex;
use std::collections::{BTreeSet, HashMap};
use std::ffi::OsStr;
use std::fs;
use std::io::{BufRead, BufReader};
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::process::Command;
use std::sync::LazyLock;
use std::time::Duration;

/// An absolute or `~/` path as it appears in a transcript line (JSON text).
static TRANSCRIPT_PATH: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r#"(?:/|~/)[^\s"'`()<>\[\]{}|,:;\\]+\.\w{1,10}\b"#).unwrap());
/// A trailing `:line` or `:line:col` after a file extension.
static LINE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(.+?\.\w+):([0-9]+)(?::[0-9]+)?$").unwrap());
static UP: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^(?:\./|\.\./)+").unwrap());

const WRAPPERS: &[char] = &['"', '\'', '`', '(', ')', '[', ']', '<', '>', '{', '}'];
const TRAILING: &[char] = &['.', ',', ';', ':', '!', '?'];
const GIT_TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Clone, Debug)]
pub struct Context {
    /// The clicked pane's `foreground_cwd` (or `cwd` when it has none).
    pub cwd: PathBuf,
    /// The Claude session id of the clicked pane (`agent_session.value`).
    pub session_id: Option<String>,
    pub home: PathBuf,
    /// The folder holding Claude's per-project temp folders, `/private/tmp/claude-<uid>`; a session's scratchpad
    /// is `<tmp_root>/*/<session id>/scratchpad`.
    pub tmp_root: PathBuf,
    /// `~/.claude/projects`.
    pub projects_root: PathBuf,
}

/// Strip `file://`, a trailing `:line[:col]`, quotes, brackets and punctuation.
pub fn normalize(text: &str) -> String {
    split_line(text).0
}

/// `normalize`, also giving the line of a `:line[:col]` suffix. A web address keeps its `:port`.
pub(crate) fn split_line(text: &str) -> (String, Option<u32>) {
    let t = text.trim();
    let mut t = t.strip_prefix("file://").unwrap_or(t);
    let mut line = None;
    loop {
        let before = t;
        t = t.trim_matches(WRAPPERS).trim_end_matches(TRAILING);
        if !(t.starts_with("http://") || t.starts_with("https://")) {
            if let Some(m) = LINE.captures(t) {
                line = line.or_else(|| m[2].parse().ok());
                t = m.get(1).unwrap().as_str();
            }
        }
        if t == before {
            return (t.to_string(), line);
        }
    }
}

/// Existing files the text may mean, without duplicates (by real path), the most recent in the transcript first.
pub fn candidates(text: &str, ctx: &Context) -> Vec<PathBuf> {
    let t = normalize(text);
    if let Some(rest) = t.strip_prefix("~/") {
        return real_file(&ctx.home.join(rest)).into_iter().collect();
    }
    if t.starts_with('/') {
        return real_file(Path::new(&t)).into_iter().collect();
    }

    let (cut, rel) = match t.strip_prefix("…/") {
        Some(rest) => (true, rest),
        None => (false, t.as_str()),
    };
    let suffix = format!("/{}", UP.replace(rel, ""));
    let mut found = BTreeSet::new();

    if ctx.cwd.is_dir() {
        if !cut {
            found.extend(real_file(&ctx.cwd.join(rel)));
        }
        found.extend(git_files(&ctx.cwd).iter().filter(|p| ends_with(p, &suffix)).filter_map(|p| real_file(p)));
    }

    let mut order = Vec::new();
    if let Some(session) = ctx.session_id.as_deref() {
        if !cut {
            let rel = rel.strip_prefix("scratchpad/").unwrap_or(rel);
            for project in subfolders(&ctx.tmp_root) {
                found.extend(real_file(&project.join(session).join("scratchpad").join(rel)));
            }
        }
        order = transcript_paths(session, &ctx.home, &ctx.projects_root, &suffix)
            .iter()
            .filter_map(|p| real_file(p))
            .collect();
        found.extend(order.iter().cloned());
    }

    // Most recent mention first; files the transcript never mentions after those, by path.
    let last_seen: HashMap<&PathBuf, usize> = order.iter().enumerate().map(|(i, p)| (p, i)).collect();
    let mut found: Vec<PathBuf> = found.into_iter().collect();
    found.sort_by_key(|p| std::cmp::Reverse(last_seen.get(p).map(|i| i + 1).unwrap_or(0)));
    found
}

fn real_file(path: &Path) -> Option<PathBuf> {
    if path.is_file() {
        fs::canonicalize(path).ok()
    } else {
        None
    }
}

fn ends_with(path: &Path, suffix: &str) -> bool {
    path.as_os_str().as_bytes().ends_with(suffix.as_bytes())
}

/// The folders directly inside `dir`, skipping hidden ones (what a shell's `dir/*` gives).
fn subfolders(dir: &Path) -> Vec<PathBuf> {
    let Ok(entries) = fs::read_dir(dir) else { return Vec::new() };
    entries
        .flatten()
        .filter(|e| !e.file_name().as_bytes().starts_with(b"."))
        .map(|e| e.path())
        .collect()
}

/// Absolute paths ending in `suffix` that the session's transcript mentions, oldest first.
fn transcript_paths(session: &str, home: &Path, projects_root: &Path, suffix: &str) -> Vec<PathBuf> {
    let mut found = Vec::new();
    for project in subfolders(projects_root) {
        let Ok(file) = fs::File::open(project.join(format!("{session}.jsonl"))) else { continue };
        for raw in BufReader::new(file).split(b'\n').map_while(Result::ok) {
            let line = String::from_utf8_lossy(&raw);
            // A path ending in the suffix holds it: skip the regex for the many lines that cannot match.
            if !line.contains(suffix) {
                continue;
            }
            let line = line.replace("\\n", " ");
            for m in TRANSCRIPT_PATH.find_iter(&line) {
                let p = m.as_str();
                let path = match p.strip_prefix("~/") {
                    Some(rest) => home.join(rest),
                    None => PathBuf::from(p),
                };
                if ends_with(&path, suffix) {
                    found.push(path);
                }
            }
        }
    }
    found
}

/// Tracked and untracked files (ignored ones excluded) of the git checkout `cwd` belongs to.
fn git_files(cwd: &Path) -> Vec<PathBuf> {
    let git = |dir: &Path, args: &[&str]| -> Option<Vec<u8>> {
        let mut cmd = Command::new("git");
        cmd.arg("-C").arg(dir).args(args);
        let out = crate::herdr::output_within(&mut cmd, GIT_TIMEOUT).ok()?;
        out.status.success().then_some(out.stdout)
    };
    let Some(top) = git(cwd, &["rev-parse", "--show-toplevel"]) else { return Vec::new() };
    let root = PathBuf::from(OsStr::from_bytes(top.strip_suffix(b"\n").unwrap_or(&top)));
    if root.as_os_str().is_empty() {
        return Vec::new();
    }
    // -z: NUL-separated and unquoted; otherwise git quotes names with non-ASCII characters.
    let Some(list) = git(&root, &["ls-files", "-z", "-co", "--exclude-standard"]) else { return Vec::new() };
    list.split(|b| *b == 0).filter(|name| !name.is_empty()).map(|name| root.join(OsStr::from_bytes(name))).collect()
}
