//! Turn a clicked (possibly shortened) path into candidate files: working folder, scratchpad, transcript, git.
//! Rules: the design's "Path resolution". (Task 2)
use std::path::PathBuf;

#[derive(Clone, Debug)]
pub struct Context {
    /// The clicked pane's `foreground_cwd` (or `cwd` when it has none).
    pub cwd: PathBuf,
    /// The Claude session id of the clicked pane (`agent_session.value`).
    pub session_id: Option<String>,
    pub home: PathBuf,
    /// Where Claude's scratchpads live: `/private/tmp`.
    pub tmp_root: PathBuf,
    /// `~/.claude/projects`.
    pub projects_root: PathBuf,
}

/// Strip `file://`, a trailing `:line[:col]`, quotes, brackets and punctuation.
pub fn normalize(text: &str) -> String {
    text.to_string()
}

/// Existing files the text may mean, without duplicates (by real path), the most recent in the transcript first.
pub fn candidates(_text: &str, _ctx: &Context) -> Vec<PathBuf> {
    Vec::new()
}
