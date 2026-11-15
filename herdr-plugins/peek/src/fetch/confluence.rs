//! Confluence pages: `GET /wiki/api/v2/pages/<id>?body-format=view` gives the title and the rendered body
//! (`body.view.value`).
use crate::fetch::{localize, Client, FetchError};
use std::path::Path;

/// Title and body HTML.
pub(crate) fn fetch(client: &Client, site: &str, id: &str, files: &Path) -> Result<(String, String), FetchError> {
    let page = client.json(&format!("/wiki/api/v2/pages/{id}?body-format=view"))?;
    let title = page["title"].as_str().unwrap_or(id).to_string();
    let body = match page["body"]["view"]["value"].as_str().filter(|b| !b.trim().is_empty()) {
        Some(b) => b.to_string(),
        None => "<p><em>This page is empty.</em></p>".to_string(),
    };
    Ok((title, localize(&body, site, client, files)))
}
