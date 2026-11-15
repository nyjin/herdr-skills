//! Jira, Confluence and GitHub PR content through each service's REST API, with tokens from a `TokenStore`
//! (`peek auth`), cached under `~/.cache/peek/links/`. (Task 4)
use crate::target::Target;
use std::io;
use std::path::Path;
use std::time::Duration;

pub mod cache;
pub mod confluence;
pub mod github;
pub mod jira;

#[derive(Clone, Debug, PartialEq)]
pub struct Fetched {
    pub title: String,
    /// Body HTML (what goes inside peek's page template).
    pub html: String,
    pub url: String,
    /// RFC 3339.
    pub fetched_at: String,
}

#[derive(Clone, Debug, PartialEq)]
pub enum FetchError {
    /// No token stored; `hint` is the `peek auth ...` command to run.
    NoToken { hint: String },
    Http { status: u16, url: String },
    Timeout,
    Other(String),
}

/// Keys: `atlassian:<host>` holds `<email>:<api token>`; `github` holds a token.
pub trait TokenStore {
    fn get(&self, key: &str) -> Option<String>;
    fn set(&self, key: &str, value: &str) -> io::Result<()>;
}

#[derive(Clone, Debug)]
pub struct Endpoints {
    /// Replaces the site taken from the link (tests point it at a local server).
    pub atlassian_base: Option<String>,
    /// `https://api.github.com` in use.
    pub github_api: String,
    pub timeout: Duration,
}

impl Default for Endpoints {
    fn default() -> Self {
        Endpoints { atlassian_base: None, github_api: "https://api.github.com".into(), timeout: Duration::from_secs(20) }
    }
}

/// The page content for a link target; the cached copy unless `fresh`.
pub fn fetch(_target: &Target, _tokens: &dyn TokenStore, _cache: &Path, _fresh: bool, _ep: &Endpoints) -> Result<Fetched, FetchError> {
    Err(FetchError::Other("not implemented".into()))
}

/// A page that says what went wrong and how to fix it.
pub fn error_page(_err: &FetchError, _target: &Target) -> Fetched {
    Fetched { title: String::new(), html: String::new(), url: String::new(), fetched_at: String::new() }
}

/// `peek auth atlassian <site>` (email and API token) or `peek auth github` (token); secrets come from stdin.
pub fn run_auth(_args: &[String], _tokens: &dyn TokenStore) -> io::Result<()> {
    Err(io::ErrorKind::Unsupported.into())
}
