//! Jira issues: `GET /rest/api/3/issue/<KEY>?expand=renderedFields&fields=summary,status,assignee,description,comment`
//! for the issue and its rendered description. API v3 leaves comment bodies in ADF even under `renderedFields`, so
//! when the issue has comments they come rendered from `GET /rest/api/3/issue/<KEY>/comment?expand=renderedBody`.
use crate::fetch::{esc, localize, short_time, Client, FetchError};
use std::path::Path;

const PAGE: usize = 100;
const MAX_PAGES: usize = 20;

/// Title and body HTML.
pub(crate) fn fetch(client: &Client, site: &str, key: &str, files: &Path) -> Result<(String, String), FetchError> {
    let issue = client.json(&format!(
        "/rest/api/3/issue/{key}?expand=renderedFields&fields=summary,status,assignee,description,comment"
    ))?;
    let (fields, rendered) = (&issue["fields"], &issue["renderedFields"]);
    let summary = fields["summary"].as_str().unwrap_or("");
    let status = fields["status"]["name"].as_str().unwrap_or("-");
    let assignee = fields["assignee"]["displayName"].as_str().unwrap_or("Unassigned");

    let mut html = format!("<p><strong>{}</strong> · Assignee: {}</p>\n<h2>Description</h2>\n", esc(status), esc(assignee));
    match rendered["description"].as_str().filter(|d| !d.trim().is_empty()) {
        Some(d) => html += d,
        None => html += "<p><em>No description</em></p>",
    }
    let total = fields["comment"]["total"]
        .as_u64()
        .unwrap_or_else(|| fields["comment"]["comments"].as_array().map_or(0, |a| a.len() as u64));
    if total > 0 {
        let comments = comments(client, key)?;
        html += &format!("\n<h2>Comments ({})</h2>\n", comments.len());
        for c in &comments {
            let author = c["author"]["displayName"].as_str().unwrap_or("-");
            let when = short_time(c["created"].as_str().unwrap_or(""));
            html += &format!("<h3>{} · {}</h3>\n{}\n", esc(author), esc(&when), c["renderedBody"].as_str().unwrap_or(""));
        }
    }
    Ok((format!("{key} {summary}").trim_end().to_string(), localize(&html, site, client, files)))
}

fn comments(client: &Client, key: &str) -> Result<Vec<serde_json::Value>, FetchError> {
    let mut all = Vec::new();
    for _ in 0..MAX_PAGES {
        let page = client.json(&format!(
            "/rest/api/3/issue/{key}/comment?expand=renderedBody&startAt={}&maxResults={PAGE}",
            all.len()
        ))?;
        let batch = page["comments"].as_array().cloned().unwrap_or_default();
        let total = page["total"].as_u64().unwrap_or(0) as usize;
        if batch.is_empty() {
            break;
        }
        all.extend(batch);
        if all.len() >= total {
            break;
        }
    }
    Ok(all)
}
