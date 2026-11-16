//! GitHub PRs: the PR, issue comments and review comments with `Accept: application/vnd.github.html+json`, which
//! puts the rendered markdown in `body_html`. Comments are read 100 to a page until a short page.
use crate::fetch::{esc, short_time, Client, FetchError};

const PAGE: usize = 100;
const MAX_PAGES: usize = 20;

/// Title and body HTML.
pub(crate) fn fetch(client: &Client, repo: &str, number: u64) -> Result<(String, String), FetchError> {
    let pr = client.json(&format!("/repos/{repo}/pulls/{number}"))?;
    let comments = list(client, &format!("/repos/{repo}/issues/{number}/comments"))?;
    let reviews = list(client, &format!("/repos/{repo}/pulls/{number}/comments"))?;

    let state = if pr["merged"].as_bool() == Some(true) {
        "Merged"
    } else if pr["state"].as_str() == Some("closed") {
        "Closed"
    } else if pr["draft"].as_bool() == Some(true) {
        "Draft"
    } else {
        "Open"
    };
    let text = |v: &serde_json::Value| esc(v.as_str().unwrap_or("-"));
    let mut html = format!(
        "<p><strong>{state}</strong> · {} · {} ← {} · +{} −{} · {} files</p>\n",
        text(&pr["user"]["login"]),
        text(&pr["base"]["ref"]),
        text(&pr["head"]["ref"]),
        pr["additions"].as_u64().unwrap_or(0),
        pr["deletions"].as_u64().unwrap_or(0),
        pr["changed_files"].as_u64().unwrap_or(0),
    );
    match body(&pr) {
        Some(b) => html += &b,
        None => html += "<p><em>No description</em></p>",
    }
    if !comments.is_empty() {
        html += &format!("\n<h2>Comments ({})</h2>\n", comments.len());
        for c in &comments {
            let when = esc(&short_time(c["created_at"].as_str().unwrap_or("")));
            html += &format!("<h3>{} · {when}</h3>\n{}\n", text(&c["user"]["login"]), body(c).unwrap_or_default());
        }
    }
    if !reviews.is_empty() {
        html += &format!("\n<h2>Review comments ({})</h2>\n", reviews.len());
        for c in &reviews {
            let line = c["line"].as_u64().or_else(|| c["original_line"].as_u64()).map_or(String::new(), |l| format!(":{l}"));
            html += &format!(
                "<h3><code>{}{line}</code> · {}</h3>\n{}\n",
                text(&c["path"]),
                text(&c["user"]["login"]),
                body(c).unwrap_or_default()
            );
        }
    }
    let title = format!("{repo}#{number} {}", pr["title"].as_str().unwrap_or(""));
    Ok((title.trim_end().to_string(), html))
}

/// `body_html`, or the markdown source in `body` as escaped text when an endpoint left the HTML out.
fn body(v: &serde_json::Value) -> Option<String> {
    if let Some(html) = v["body_html"].as_str().filter(|b| !b.trim().is_empty()) {
        return Some(html.to_string());
    }
    let raw = v["body"].as_str().filter(|b| !b.trim().is_empty())?;
    Some(format!("<p>{}</p>", esc(raw).replace('\n', "<br>\n")))
}

fn list(client: &Client, path: &str) -> Result<Vec<serde_json::Value>, FetchError> {
    let mut all = Vec::new();
    for page in 1..=MAX_PAGES {
        let batch = client.json(&format!("{path}?per_page={PAGE}&page={page}"))?.as_array().cloned().unwrap_or_default();
        let short = batch.len() < PAGE;
        all.extend(batch);
        if short {
            break;
        }
    }
    Ok(all)
}
