//! Jira, Confluence and GitHub PR content through each service's REST API, with tokens from a `TokenStore`
//! (`peek auth`), cached under `~/.cache/peek/links/`.
//!
//! `Fetched.title` is plain text; `Fetched.html` is a body fragment for peek's page template, which shows the title
//! and the fetch time itself. Every request goes to a configured base (the link's site, `Endpoints`) plus a path;
//! a URL found in fetched content never reaches the HTTP client, so the token stays on its own site.
use crate::target::Target;
use regex::{Captures, Regex};
use std::collections::HashMap;
use std::io::{self, BufRead, Read, Write};
use std::path::Path;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

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
pub fn fetch(target: &Target, tokens: &dyn TokenStore, cache: &Path, fresh: bool, ep: &Endpoints) -> Result<Fetched, FetchError> {
    let url = web_url(target)
        .ok_or_else(|| FetchError::Other(format!("{} is not a Jira, Confluence or GitHub PR link.", name(target))))?;
    if !fresh {
        if let Some(page) = cache::load(cache, &url) {
            return Ok(page);
        }
    }
    let files = cache::files_dir(cache, &url);
    let (title, html) = match target {
        Target::Jira { site, key } => jira::fetch(&atlassian(site, tokens, ep)?, site, key, &files)?,
        Target::Confluence { site, page_id: Some(id), .. } => confluence::fetch(&atlassian(site, tokens, ep)?, site, id, &files)?,
        Target::Confluence { page_id: None, .. } => {
            return Err(FetchError::Other(
                "This Confluence link does not name a page id, so peek cannot ask the API for it.".into(),
            ))
        }
        Target::GithubPr { repo, number } => github::fetch(&github_client(tokens, ep)?, repo, *number)?,
        Target::Path { .. } => unreachable!("a path has no web address"),
    };
    let page = Fetched { title, html, url, fetched_at: now() };
    // A cache that cannot be written only costs the next fetch; the page itself is fine.
    let _ = cache::store(cache, &page.url, &page);
    Ok(page)
}

/// A page that says what went wrong and how to fix it.
pub fn error_page(err: &FetchError, target: &Target) -> Fetched {
    let hint = auth_hint(target).unwrap_or_default();
    let (cause, fix) = match err {
        FetchError::NoToken { hint } => (
            "peek has no token for this service yet.".to_string(),
            format!("Run <code>{}</code> in a terminal, then press <kbd>r</kbd> here.", esc(hint)),
        ),
        FetchError::Http { status: status @ (401 | 403), .. } => (
            format!("The service refused the token (HTTP {status})."),
            format!(
                "The token may have expired or lack access. Register a new one with <code>{}</code>, then press <kbd>r</kbd>.",
                esc(&hint)
            ),
        ),
        FetchError::Http { status: 404, .. } => (
            "Not found (HTTP 404).".to_string(),
            format!(
                "Check the link. The service also answers 404 when the account behind the token cannot see it; \
                 register another with <code>{}</code> if so.",
                esc(&hint)
            ),
        ),
        FetchError::Http { status, url } => (
            format!("The service answered HTTP {status} for {url}."),
            "Press <kbd>r</kbd> to try again later.".to_string(),
        ),
        FetchError::Timeout => (
            "The service did not answer in time.".to_string(),
            "Check the network or VPN, then press <kbd>r</kbd> to try again.".to_string(),
        ),
        FetchError::Other(msg) => (msg.clone(), "Press <kbd>r</kbd> to try again.".to_string()),
    };
    let url = web_url(target).unwrap_or_default();
    let mut html = format!("<p>{}</p>\n<p>{fix}</p>\n", esc(&cause));
    if !url.is_empty() {
        let u = esc(&url);
        html += &format!("<p>Link: <a href=\"{u}\">{u}</a> (press <kbd>o</kbd> to open it in the browser)</p>\n");
    }
    Fetched { title: format!("Could not fetch {}", name(target)), html, url, fetched_at: now() }
}

/// `peek auth atlassian <site>` (email and API token) or `peek auth github` (token); secrets come from stdin.
pub fn run_auth(args: &[String], tokens: &dyn TokenStore) -> io::Result<()> {
    let usage = || io::Error::new(io::ErrorKind::InvalidInput, "Usage: peek auth atlassian <site> | peek auth github");
    let missing = || io::Error::new(io::ErrorKind::InvalidInput, "nothing was entered; nothing was saved");
    match args {
        [service, site] if service == "atlassian" => {
            let host = host_of(site);
            if host.is_empty() {
                return Err(usage());
            }
            let email = read_line(&format!("Atlassian account email for {host}: "), true)?;
            let token = read_line(
                "API token (create one at https://id.atlassian.com/manage-profile/security/api-tokens): ",
                false,
            )?;
            if email.is_empty() || token.is_empty() {
                return Err(missing());
            }
            tokens.set(&format!("atlassian:{host}"), &format!("{email}:{token}"))?;
            eprintln!("Saved the token for {host}.");
        }
        [service] if service == "github" => {
            let token = read_line("GitHub token with read access to the repositories: ", false)?;
            if token.is_empty() {
                return Err(missing());
            }
            tokens.set("github", &token)?;
            eprintln!("Saved the GitHub token.");
        }
        _ => return Err(usage()),
    }
    Ok(())
}

// ---- targets ----------------------------------------------------------------------------------

/// The link's web address (what `o` opens and what the cache is keyed by).
fn web_url(target: &Target) -> Option<String> {
    match target {
        Target::Jira { site, key } => Some(format!("{}/browse/{key}", site.trim_end_matches('/'))),
        Target::Confluence { url, .. } => Some(url.clone()),
        Target::GithubPr { repo, number } => Some(format!("https://github.com/{repo}/pull/{number}")),
        Target::Path { .. } => None,
    }
}

fn name(target: &Target) -> String {
    match target {
        Target::Jira { key, .. } => key.clone(),
        Target::Confluence { page_id: Some(id), .. } => format!("Confluence page {id}"),
        Target::Confluence { page_id: None, .. } => "this Confluence page".into(),
        Target::GithubPr { repo, number } => format!("{repo}#{number}"),
        Target::Path { text, .. } => text.clone(),
    }
}

fn auth_hint(target: &Target) -> Option<String> {
    match target {
        Target::Jira { site, .. } | Target::Confluence { site, .. } => Some(format!("peek auth atlassian {}", host_of(site))),
        Target::GithubPr { .. } => Some("peek auth github".into()),
        Target::Path { .. } => None,
    }
}

/// `https://Example.atlassian.net/wiki` → `example.atlassian.net`.
fn host_of(site: &str) -> String {
    let rest = site.strip_prefix("https://").or_else(|| site.strip_prefix("http://")).unwrap_or(site);
    rest.split(['/', '?', '#']).next().unwrap_or("").to_ascii_lowercase()
}

fn atlassian(site: &str, tokens: &dyn TokenStore, ep: &Endpoints) -> Result<Client, FetchError> {
    let host = host_of(site);
    let secret = tokens
        .get(&format!("atlassian:{host}"))
        .filter(|t| !t.is_empty())
        .ok_or_else(|| FetchError::NoToken { hint: format!("peek auth atlassian {host}") })?;
    let base = ep.atlassian_base.as_deref().unwrap_or(site);
    Ok(Client::new(ep, base, format!("Basic {}", base64(secret.as_bytes())), "application/json", None))
}

fn github_client(tokens: &dyn TokenStore, ep: &Endpoints) -> Result<Client, FetchError> {
    let token = tokens
        .get("github")
        .filter(|t| !t.is_empty())
        .ok_or_else(|| FetchError::NoToken { hint: "peek auth github".into() })?;
    Ok(Client::new(
        ep,
        &ep.github_api,
        format!("Bearer {token}"),
        "application/vnd.github.html+json",
        Some(("X-GitHub-Api-Version", "2022-11-28")),
    ))
}

// ---- HTTP -------------------------------------------------------------------------------------

/// One service: requests go to `base` + a path, with its token and media type.
pub(crate) struct Client {
    agent: ureq::Agent,
    base: String,
    auth: String,
    accept: &'static str,
    extra: Option<(&'static str, &'static str)>,
}

impl Client {
    fn new(ep: &Endpoints, base: &str, auth: String, accept: &'static str, extra: Option<(&'static str, &'static str)>) -> Client {
        let agent = ureq::AgentBuilder::new()
            .timeout(ep.timeout)
            .user_agent("peek")
            // A redirect (Jira attachments go to a signed media URL) never carries the token on.
            .redirect_auth_headers(ureq::RedirectAuthHeaders::Never)
            .build();
        Client { agent, base: base.trim_end_matches('/').to_string(), auth, accept, extra }
    }

    /// `path` starts with `/` and may hold a query.
    pub(crate) fn json(&self, path: &str) -> Result<serde_json::Value, FetchError> {
        let (body, _) = self.get(path, self.accept)?;
        serde_json::from_slice(&body)
            .map_err(|e| FetchError::Other(format!("Unexpected answer from {}{path}: {e}", self.base)))
    }

    /// The body and its content type.
    pub(crate) fn get(&self, path: &str, accept: &str) -> Result<(Vec<u8>, String), FetchError> {
        let url = format!("{}{path}", self.base);
        if !path.starts_with('/') || path.starts_with("//") {
            return Err(FetchError::Other(format!("Refused to request {url}")));
        }
        let mut req = self.agent.get(&url).set("Authorization", &self.auth).set("Accept", accept);
        if let Some((k, v)) = self.extra {
            req = req.set(k, v);
        }
        let resp = req.call().map_err(|e| match e {
            ureq::Error::Status(status, _) => FetchError::Http { status, url: url.clone() },
            ureq::Error::Transport(t) if timed_out(&t) => FetchError::Timeout,
            ureq::Error::Transport(t) => FetchError::Other(format!("Could not reach {} ({t}).", host_of(&url))),
        })?;
        let content_type = resp.content_type().to_string();
        let mut body = Vec::new();
        resp.into_reader().read_to_end(&mut body).map_err(|e| match e.kind() {
            io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock => FetchError::Timeout,
            _ => FetchError::Other(format!("Could not read the answer from {url}: {e}")),
        })?;
        Ok((body, content_type))
    }
}

fn timed_out(t: &ureq::Transport) -> bool {
    let mut source = std::error::Error::source(t);
    while let Some(e) = source {
        if let Some(io) = e.downcast_ref::<io::Error>() {
            if matches!(io.kind(), io::ErrorKind::TimedOut | io::ErrorKind::WouldBlock) {
                return true;
            }
        }
        source = e.source();
    }
    false
}

// ---- Atlassian HTML ---------------------------------------------------------------------------

/// Images on the site are downloaded with the token into `files` and referenced as file URLs (the page cannot send
/// the token); links relative to the site become absolute so they open in the browser.
pub(crate) fn localize(html: &str, site: &str, client: &Client, files: &Path) -> String {
    let host = host_of(site);
    let img = Regex::new(r#"(?i)(<img\b[^>]*?\ssrc\s*=\s*)(?:"([^"]*)"|'([^']*)')"#).unwrap();
    let src_of = |c: &Captures| unescape(c.get(2).or_else(|| c.get(3)).map_or("", |m| m.as_str()));
    let mut wanted: Vec<(String, String)> = Vec::new();
    for c in img.captures_iter(html) {
        let src = src_of(&c);
        if let Some(path) = site_path(&src, &host) {
            if !wanted.iter().any(|(s, _)| *s == src) {
                wanted.push((src, path));
            }
        }
    }
    let local = if wanted.is_empty() || cache::make_dir(files).is_err() { HashMap::new() } else { download(&wanted, client, files) };
    let html = img.replace_all(html, |c: &Captures| match local.get(&src_of(c)) {
        Some(url) => format!("{}\"{url}\"", &c[1]),
        None => c[0].to_string(),
    });
    let href = Regex::new(r#"(?i)(<a\b[^>]*?\shref\s*=\s*)"(/[^"]*)""#).unwrap();
    href.replace_all(&html, |c: &Captures| {
        if c[2].starts_with("//") {
            c[0].to_string()
        } else {
            format!("{}\"{}{}\"", &c[1], site.trim_end_matches('/'), &c[2])
        }
    })
    .into_owned()
}

/// The path (with query) of an image on the site itself, or `None` for anything elsewhere.
fn site_path(src: &str, host: &str) -> Option<String> {
    if src.starts_with('/') && !src.starts_with("//") {
        return Some(src.to_string());
    }
    let rest = src.strip_prefix("https://").or_else(|| src.strip_prefix("http://")).or_else(|| src.strip_prefix("//"))?;
    let end = rest.find(['/', '?', '#']).unwrap_or(rest.len());
    if !rest[..end].eq_ignore_ascii_case(host) {
        return None;
    }
    let path = &rest[end..];
    Some(if path.starts_with('/') { path.to_string() } else { format!("/{path}") })
}

/// Downloads a few at a time; an image that fails keeps its original address.
fn download(wanted: &[(String, String)], client: &Client, files: &Path) -> HashMap<String, String> {
    let per_thread = wanted.len().div_ceil(6);
    std::thread::scope(|s| {
        let workers: Vec<_> = wanted
            .chunks(per_thread)
            .map(|chunk| {
                s.spawn(move || {
                    chunk.iter().filter_map(|(src, path)| Some((src.clone(), save(client, path, files)?))).collect::<Vec<_>>()
                })
            })
            .collect();
        workers.into_iter().flat_map(|w| w.join().unwrap_or_default()).collect()
    })
}

fn save(client: &Client, path: &str, files: &Path) -> Option<String> {
    let path = path.split('#').next().unwrap_or(path);
    let (body, content_type) = client.get(path, "*/*").ok()?;
    let file = files.join(format!("{}.{}", &cache::key(path)[..16], extension(&content_type, path)));
    std::fs::write(&file, body).ok()?;
    Some(file_url(&file))
}

/// WebKit needs the extension to show an SVG from a file.
fn extension(content_type: &str, path: &str) -> String {
    let mime = content_type.split(';').next().unwrap_or("").trim().to_ascii_lowercase();
    let known = match mime.as_str() {
        "image/png" => "png",
        "image/jpeg" | "image/jpg" => "jpg",
        "image/gif" => "gif",
        "image/webp" => "webp",
        "image/svg+xml" => "svg",
        "image/bmp" => "bmp",
        _ => "",
    };
    if !known.is_empty() {
        return known.into();
    }
    let file = path.split('?').next().unwrap_or("").rsplit('/').next().unwrap_or("");
    match file.rsplit_once('.') {
        Some((_, ext)) if (1..=5).contains(&ext.len()) && ext.bytes().all(|b| b.is_ascii_alphanumeric()) => ext.to_ascii_lowercase(),
        _ => "bin".into(),
    }
}

fn file_url(path: &Path) -> String {
    use std::os::unix::ffi::OsStrExt;
    let mut url = String::from("file://");
    for &b in path.as_os_str().as_bytes() {
        if b.is_ascii_alphanumeric() || b"/-._~".contains(&b) {
            url.push(b as char);
        } else {
            url += &format!("%{b:02X}");
        }
    }
    url
}

// ---- text -------------------------------------------------------------------------------------

pub(crate) fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;").replace('"', "&quot;").replace('\'', "&#39;")
}

/// The entities an attribute value commonly holds; `&amp;` last so `&amp;lt;` stays `&lt;`.
fn unescape(s: &str) -> String {
    s.replace("&quot;", "\"").replace("&#39;", "'").replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
}

/// `2026-11-01T10:00:00.000+0900` → `2026-11-01 10:00`.
pub(crate) fn short_time(iso: &str) -> String {
    iso.chars().take(16).collect::<String>().replace('T', " ")
}

fn base64(data: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(data.len().div_ceil(3) * 4);
    for chunk in data.chunks(3) {
        let n = (chunk[0] as u32) << 16 | (*chunk.get(1).unwrap_or(&0) as u32) << 8 | *chunk.get(2).unwrap_or(&0) as u32;
        for i in 0..4 {
            out.push(if i <= chunk.len() { ALPHABET[(n >> (18 - 6 * i) & 63) as usize] as char } else { '=' });
        }
    }
    out
}

/// Now in UTC, RFC 3339 to the second.
fn now() -> String {
    let secs = SystemTime::now().duration_since(UNIX_EPOCH).map_or(0, |d| d.as_secs()) as i64;
    let (days, rest) = (secs.div_euclid(86_400), secs.rem_euclid(86_400));
    // Civil date from days since 1970-01-01 (Howard Hinnant's algorithm).
    let z = days + 719_468;
    let (era, doe) = (z.div_euclid(146_097), z.rem_euclid(146_097));
    let yoe = (doe - doe / 1460 + doe / 36_524 - doe / 146_096) / 365;
    let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
    let mp = (5 * doy + 2) / 153;
    let day = doy - (153 * mp + 2) / 5 + 1;
    let month = if mp < 10 { mp + 3 } else { mp - 9 };
    let year = yoe + era * 400 + i64::from(month <= 2);
    format!("{year:04}-{month:02}-{day:02}T{:02}:{:02}:{:02}Z", rest / 3600, rest % 3600 / 60, rest % 60)
}

/// One line from stdin after a prompt on stderr; without echo when `echo` is false and stdin is a terminal.
fn read_line(prompt: &str, echo: bool) -> io::Result<String> {
    eprint!("{prompt}");
    io::stderr().flush()?;
    let quiet = if echo { None } else { NoEcho::on_stdin() };
    let mut line = String::new();
    io::stdin().lock().read_line(&mut line)?;
    if quiet.is_some() {
        eprintln!();
    }
    Ok(line.trim().to_string())
}

/// Terminal echo off on stdin until dropped.
struct NoEcho(libc::termios);

impl NoEcho {
    fn on_stdin() -> Option<NoEcho> {
        // SAFETY: termios calls on fd 0 with a zeroed struct that tcgetattr fills before use.
        unsafe {
            if libc::isatty(0) != 1 {
                return None;
            }
            let mut t: libc::termios = std::mem::zeroed();
            if libc::tcgetattr(0, &mut t) != 0 {
                return None;
            }
            let saved = t;
            t.c_lflag &= !libc::ECHO;
            libc::tcsetattr(0, libc::TCSANOW, &t);
            Some(NoEcho(saved))
        }
    }
}

impl Drop for NoEcho {
    fn drop(&mut self) {
        // SAFETY: restores the settings read in `on_stdin`.
        unsafe {
            libc::tcsetattr(0, libc::TCSANOW, &self.0);
        }
    }
}
