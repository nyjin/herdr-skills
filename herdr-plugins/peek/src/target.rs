//! Sort a clicked string into a link peek fetches (Jira, Confluence, GitHub PR) or a file path. (Task 2)

#[derive(Clone, Debug, PartialEq)]
pub enum Target {
    /// `site` is the scheme and host, e.g. `https://example.atlassian.net`.
    Jira { site: String, key: String },
    Confluence { site: String, page_id: Option<String>, url: String },
    /// `repo` is `owner/name`.
    GithubPr { repo: String, number: u64 },
    Path { text: String, line: Option<u32> },
}

impl Target {
    /// The web address of a link target; `None` for a path.
    pub fn url(&self) -> Option<String> {
        None
    }
}

pub fn classify(text: &str) -> Target {
    Target::Path { text: text.to_string(), line: None }
}
