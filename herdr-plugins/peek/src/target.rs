//! Sort a clicked string into a link peek fetches (Jira, Confluence, GitHub PR) or a file path.
use regex::Regex;
use std::sync::LazyLock;

static JIRA: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^(https://[^/\s]+\.atlassian\.net)/browse/([A-Z][A-Z0-9]+-[0-9]+)").unwrap());
static CONFLUENCE: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^(https://[^/\s]+\.atlassian\.net)/wiki/\S+").unwrap());
static PAGE_ID: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"/pages/([0-9]+)").unwrap());
static GITHUB_PR: LazyLock<Regex> =
    LazyLock::new(|| Regex::new(r"^https://github\.com/([^/\s]+/[^/\s]+)/pull/([0-9]+)").unwrap());

#[derive(Clone, Debug, PartialEq)]
pub enum Target {
    /// `site` is the scheme and host, e.g. `https://example.atlassian.net`.
    Jira { site: String, key: String },
    Confluence { site: String, page_id: Option<String>, url: String },
    /// `repo` is `owner/name`.
    GithubPr { repo: String, number: u64 },
    /// `text` is normalized (`resolve::normalize`); a web address that is none of the above stays a `Path` and
    /// starts with `http://` or `https://`.
    Path { text: String, line: Option<u32> },
}

impl Target {
    /// The web address of a link target; `None` for a path.
    pub fn url(&self) -> Option<String> {
        match self {
            Target::Jira { site, key } => Some(format!("{site}/browse/{key}")),
            Target::Confluence { url, .. } => Some(url.clone()),
            Target::GithubPr { repo, number } => Some(format!("https://github.com/{repo}/pull/{number}")),
            Target::Path { .. } => None,
        }
    }
}

pub fn classify(text: &str) -> Target {
    let (t, line) = crate::resolve::split_line(text);
    if let Some(m) = JIRA.captures(&t) {
        return Target::Jira { site: m[1].to_string(), key: m[2].to_string() };
    }
    if let Some(m) = CONFLUENCE.captures(&t) {
        let page_id = PAGE_ID.captures(&t).map(|p| p[1].to_string());
        return Target::Confluence { site: m[1].to_string(), page_id, url: t.clone() };
    }
    if let Some(m) = GITHUB_PR.captures(&t) {
        if let Ok(number) = m[2].parse() {
            return Target::GithubPr { repo: m[1].to_string(), number };
        }
    }
    Target::Path { text: t, line }
}
