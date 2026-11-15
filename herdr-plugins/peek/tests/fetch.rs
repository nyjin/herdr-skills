//! Jira, Confluence and GitHub PR fetching against a local fake server (`tiny_http`) with an in-memory token store.
//! Nothing here talks to the real services or the Keychain.
use peek::fetch::{self, Endpoints, FetchError, Fetched, TokenStore};
use peek::target::Target;
use std::collections::HashMap;
use std::io::{self, Write};
use std::path::Path;
use std::process::{Command, Stdio};
use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

// ---- fake server ------------------------------------------------------------------------------

#[derive(Clone, Debug)]
struct Hit {
    path: String,
    query: String,
    headers: Vec<(String, String)>,
}

impl Hit {
    fn header(&self, name: &str) -> Option<&str> {
        self.headers.iter().find(|(k, _)| k.eq_ignore_ascii_case(name)).map(|(_, v)| v.as_str())
    }
    fn param(&self, name: &str) -> Option<&str> {
        self.query.split('&').find_map(|kv| kv.strip_prefix(name)?.strip_prefix('='))
    }
}

struct Reply {
    status: u16,
    content_type: &'static str,
    body: Vec<u8>,
    delay: Duration,
}

fn json(status: u16, body: impl Into<Vec<u8>>) -> Reply {
    Reply { status, content_type: "application/json", body: body.into(), delay: Duration::ZERO }
}

fn png(body: &[u8]) -> Reply {
    Reply { status: 200, content_type: "image/png", body: body.to_vec(), delay: Duration::ZERO }
}

fn fixture(name: &str) -> String {
    std::fs::read_to_string(Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fetch").join(name)).unwrap()
}

struct Fake {
    base: String,
    hits: Arc<Mutex<Vec<Hit>>>,
}

impl Fake {
    fn start(handler: impl Fn(&Hit) -> Reply + Send + Sync + 'static) -> Fake {
        let server = tiny_http::Server::http("127.0.0.1:0").unwrap();
        let port = server.server_addr().to_ip().unwrap().port();
        let hits = Arc::new(Mutex::new(Vec::new()));
        let handler = Arc::new(handler);
        let recorded = hits.clone();
        std::thread::spawn(move || {
            for req in server.incoming_requests() {
                let url = req.url().to_string();
                let (path, query) = match url.split_once('?') {
                    Some((p, q)) => (p.to_string(), q.to_string()),
                    None => (url.clone(), String::new()),
                };
                let headers =
                    req.headers().iter().map(|h| (h.field.as_str().as_str().to_string(), h.value.as_str().to_string())).collect();
                let hit = Hit { path, query, headers };
                recorded.lock().unwrap().push(hit.clone());
                let handler = handler.clone();
                std::thread::spawn(move || {
                    let reply = handler(&hit);
                    std::thread::sleep(reply.delay);
                    let ct = tiny_http::Header::from_bytes("Content-Type", reply.content_type).unwrap();
                    let _ = req.respond(tiny_http::Response::from_data(reply.body).with_status_code(reply.status).with_header(ct));
                });
            }
        });
        Fake { base: format!("http://127.0.0.1:{port}"), hits }
    }

    fn hits(&self) -> Vec<Hit> {
        self.hits.lock().unwrap().clone()
    }

    fn hits_to(&self, path: &str) -> Vec<Hit> {
        self.hits().into_iter().filter(|h| h.path == path).collect()
    }

    fn endpoints(&self) -> Endpoints {
        Endpoints { atlassian_base: Some(self.base.clone()), github_api: self.base.clone(), timeout: Duration::from_millis(500) }
    }
}

// ---- tokens and targets -----------------------------------------------------------------------

#[derive(Default)]
struct Mem(Mutex<HashMap<String, String>>);

impl Mem {
    fn with(pairs: &[(&str, &str)]) -> Mem {
        Mem(Mutex::new(pairs.iter().map(|(k, v)| (k.to_string(), v.to_string())).collect()))
    }
}

impl TokenStore for Mem {
    fn get(&self, key: &str) -> Option<String> {
        self.0.lock().unwrap().get(key).cloned()
    }
    fn set(&self, key: &str, value: &str) -> io::Result<()> {
        self.0.lock().unwrap().insert(key.to_string(), value.to_string());
        Ok(())
    }
}

fn tokens() -> Mem {
    Mem::with(&[("atlassian:example.atlassian.net", "me@example.com:secret-token1"), ("github", "gh-token")])
}

/// `printf 'me@example.com:secret-token1' | base64` (28 bytes: the encoding ends in padding)
const BASIC: &str = "Basic bWVAZXhhbXBsZS5jb206c2VjcmV0LXRva2VuMQ==";
const SCREEN_PNG: &[u8] = b"\x89PNG\r\n\x1a\nscreen";
const DIAGRAM_PNG: &[u8] = b"\x89PNG\r\n\x1a\ndiagram";

fn jira() -> Target {
    Target::Jira { site: "https://example.atlassian.net".into(), key: "ABC-1".into() }
}

fn confluence() -> Target {
    Target::Confluence {
        site: "https://example.atlassian.net".into(),
        page_id: Some("123456".into()),
        url: "https://example.atlassian.net/wiki/spaces/OPS/pages/123456/Deploy+runbook".into(),
    }
}

fn pr() -> Target {
    Target::GithubPr { repo: "acme/app".into(), number: 42 }
}

fn atlassian(hit: &Hit) -> Reply {
    match hit.path.as_str() {
        "/rest/api/3/issue/ABC-1" => json(200, fixture("jira_issue.json")),
        "/rest/api/3/issue/ABC-1/comment" => json(200, fixture("jira_comments.json")),
        "/wiki/api/v2/pages/123456" => json(200, fixture("confluence_page.json")),
        "/rest/api/3/attachment/content/1" => png(SCREEN_PNG),
        "/wiki/download/attachments/123456/diagram.png" => png(DIAGRAM_PNG),
        _ => json(404, r#"{"errorMessages":["Issue does not exist or you do not have permission to see it."],"errors":{}}"#),
    }
}

fn github(hit: &Hit) -> Reply {
    let first = hit.param("page").unwrap_or("1") == "1";
    match hit.path.as_str() {
        "/repos/acme/app/pulls/42" => json(200, fixture("github_pr.json")),
        "/repos/acme/app/issues/42/comments" if first => json(200, fixture("github_issue_comments.json")),
        "/repos/acme/app/pulls/42/comments" if first => json(200, fixture("github_review_comments.json")),
        "/repos/acme/app/issues/42/comments" | "/repos/acme/app/pulls/42/comments" => json(200, "[]"),
        _ => json(404, r#"{"message":"Not Found","documentation_url":"https://docs.github.com/rest","status":"404"}"#),
    }
}

fn get(target: &Target, fake: &Fake, cache: &Path) -> Result<Fetched, FetchError> {
    fetch::fetch(target, &tokens(), cache, false, &fake.endpoints())
}

/// The `src` values of the page's `<img>` elements.
fn img_srcs(html: &str) -> Vec<String> {
    let re = regex::Regex::new(r#"<img\b[^>]*?\ssrc="([^"]*)""#).unwrap();
    re.captures_iter(html).map(|c| c[1].to_string()).collect()
}

fn percent_decode(s: &str) -> String {
    let b = s.as_bytes();
    let mut out = Vec::new();
    let mut i = 0;
    while i < b.len() {
        if b[i] == b'%' && i + 2 < b.len() {
            out.push(u8::from_str_radix(&s[i + 1..i + 3], 16).unwrap());
            i += 3;
        } else {
            out.push(b[i]);
            i += 1;
        }
    }
    String::from_utf8(out).unwrap()
}

// ---- Jira -------------------------------------------------------------------------------------

#[test]
fn jira_requests_rendered_fields() {
    let fake = Fake::start(atlassian);
    let cache = tempfile::tempdir().unwrap();
    let page = get(&jira(), &fake, cache.path()).unwrap();

    let issue = fake.hits_to("/rest/api/3/issue/ABC-1");
    assert_eq!(issue.len(), 1);
    assert_eq!(issue[0].param("expand"), Some("renderedFields"));
    assert_eq!(issue[0].param("fields"), Some("summary,status,assignee,description,comment"));
    assert_eq!(issue[0].header("Authorization"), Some(BASIC));
    // v3 leaves comment bodies in ADF under renderedFields; the comment endpoint renders them.
    let comments = fake.hits_to("/rest/api/3/issue/ABC-1/comment");
    assert_eq!(comments.len(), 1);
    assert_eq!(comments[0].param("expand"), Some("renderedBody"));
    assert_eq!(comments[0].header("Authorization"), Some(BASIC));

    assert_eq!(page.title, "ABC-1 Login fails for <SSO> users");
    assert_eq!(page.url, "https://example.atlassian.net/browse/ABC-1");
    assert!(page.html.contains("In Progress"), "{}", page.html);
    assert!(page.html.contains("Dana Kim (QA &amp; Ops)"), "{}", page.html);
    assert!(page.html.contains("Steps to <strong>reproduce</strong>"), "{}", page.html);
    assert!(page.html.contains("Lee Park"), "{}", page.html);
    assert!(page.html.contains("<p>Seen on <em>staging</em> too</p>"), "{}", page.html);
    assert!(regex::Regex::new(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$").unwrap().is_match(&page.fetched_at), "{}", page.fetched_at);
}

#[test]
fn jira_comments_past_the_first_page_are_fetched() {
    let fake = Fake::start(|hit: &Hit| {
        if hit.path != "/rest/api/3/issue/ABC-1/comment" {
            return atlassian(hit);
        }
        let start: usize = hit.param("startAt").unwrap_or("0").parse().unwrap();
        let comments: Vec<_> = if start == 0 {
            (0..100).map(|i| serde_json::json!({"id": i.to_string(), "author": {"displayName": "Bot"}, "created": "2026-11-01T10:00:00.000+0900", "renderedBody": format!("<p>comment {i}</p>")})).collect()
        } else {
            vec![serde_json::json!({"id": "100", "author": {"displayName": "Bot"}, "created": "2026-11-02T10:00:00.000+0900", "renderedBody": "<p>the last one</p>"})]
        };
        json(200, serde_json::json!({"startAt": start, "maxResults": 100, "total": 101, "comments": comments}).to_string())
    });
    let cache = tempfile::tempdir().unwrap();
    let page = get(&jira(), &fake, cache.path()).unwrap();
    let starts: Vec<String> =
        fake.hits_to("/rest/api/3/issue/ABC-1/comment").iter().map(|h| h.param("startAt").unwrap_or("0").to_string()).collect();
    assert_eq!(starts, ["0", "100"]);
    assert!(page.html.contains("<p>comment 99</p>"));
    assert!(page.html.contains("<p>the last one</p>"));
}

// ---- Confluence -------------------------------------------------------------------------------

#[test]
fn confluence_requests_view_body() {
    let fake = Fake::start(atlassian);
    let cache = tempfile::tempdir().unwrap();
    let page = get(&confluence(), &fake, cache.path()).unwrap();

    let hits = fake.hits_to("/wiki/api/v2/pages/123456");
    assert_eq!(hits.len(), 1);
    assert_eq!(hits[0].param("body-format"), Some("view"));
    assert_eq!(hits[0].header("Authorization"), Some(BASIC));
    assert_eq!(page.title, "Deploy runbook");
    assert_eq!(page.url, "https://example.atlassian.net/wiki/spaces/OPS/pages/123456/Deploy+runbook");
    assert!(page.html.contains("<h2>Before you start</h2>"), "{}", page.html);
}

#[test]
fn confluence_without_page_id_is_an_error_page() {
    let fake = Fake::start(atlassian);
    let cache = tempfile::tempdir().unwrap();
    let target = Target::Confluence {
        site: "https://example.atlassian.net".into(),
        page_id: None,
        url: "https://example.atlassian.net/wiki/x/QOIB".into(),
    };
    let err = get(&target, &fake, cache.path()).unwrap_err();
    assert!(matches!(err, FetchError::Other(_)), "{err:?}");
    assert!(fake.hits().is_empty());
    let page = fetch::error_page(&err, &target);
    assert_eq!(page.url, "https://example.atlassian.net/wiki/x/QOIB");
    assert!(page.html.contains("page id"), "{}", page.html);
}

// ---- GitHub -----------------------------------------------------------------------------------

#[test]
fn github_requests_html_bodies() {
    let fake = Fake::start(github);
    let cache = tempfile::tempdir().unwrap();
    let page = get(&pr(), &fake, cache.path()).unwrap();

    for path in ["/repos/acme/app/pulls/42", "/repos/acme/app/issues/42/comments", "/repos/acme/app/pulls/42/comments"] {
        let hits = fake.hits_to(path);
        assert_eq!(hits.len(), 1, "{path}");
        assert_eq!(hits[0].header("Accept"), Some("application/vnd.github.html+json"), "{path}");
        assert_eq!(hits[0].header("Authorization"), Some("Bearer gh-token"), "{path}");
    }
    assert_eq!(page.title, "acme/app#42 Add retry to uploads");
    assert_eq!(page.url, "https://github.com/acme/app/pull/42");
    assert!(page.html.contains("Open"), "{}", page.html);
    assert!(page.html.contains("octo"), "{}", page.html);
    assert!(page.html.contains("by retrying <code>put</code>"), "{}", page.html);
    assert!(page.html.contains("<p>Looks good to me</p>"), "{}", page.html);
    assert!(page.html.contains("src/upload.rs:12"), "{}", page.html);
    assert!(page.html.contains("<p>Use a constant for the retry count</p>"), "{}", page.html);
}

#[test]
fn github_comments_past_the_first_page_are_fetched() {
    let fake = Fake::start(|hit: &Hit| {
        if hit.path != "/repos/acme/app/issues/42/comments" {
            return github(hit);
        }
        let comments: Vec<_> = match hit.param("page").unwrap_or("1") {
            "1" => (0..100).map(|i| serde_json::json!({"id": i, "user": {"login": "bot"}, "created_at": "2026-11-02T09:00:00Z", "body_html": format!("<p>note {i}</p>")})).collect(),
            "2" => vec![serde_json::json!({"id": 100, "user": {"login": "bot"}, "created_at": "2026-11-03T09:00:00Z", "body_html": "<p>the last note</p>"})],
            _ => vec![],
        };
        json(200, serde_json::Value::Array(comments).to_string())
    });
    let cache = tempfile::tempdir().unwrap();
    let page = get(&pr(), &fake, cache.path()).unwrap();
    let pages: Vec<String> =
        fake.hits_to("/repos/acme/app/issues/42/comments").iter().map(|h| h.param("page").unwrap_or("1").to_string()).collect();
    assert_eq!(pages, ["1", "2"]);
    assert!(fake.hits_to("/repos/acme/app/issues/42/comments").iter().all(|h| h.param("per_page") == Some("100")));
    assert!(page.html.contains("<p>note 99</p>"));
    assert!(page.html.contains("<p>the last note</p>"));
}

#[test]
fn github_body_without_html_is_shown_as_text() {
    // An endpoint that ignores the html media type answers with the markdown source in `body` only.
    let fake = Fake::start(|hit: &Hit| {
        let raw = |v: serde_json::Value| json(200, v.to_string());
        match hit.path.as_str() {
            "/repos/acme/app/pulls/42" => {
                let mut pr: serde_json::Value = serde_json::from_str(&fixture("github_pr.json")).unwrap();
                pr.as_object_mut().unwrap().remove("body_html");
                pr["body"] = "PR <b>source</b>".into();
                raw(pr)
            }
            "/repos/acme/app/issues/42/comments" => raw(serde_json::json!([{"id": 1, "user": {"login": "a"}, "created_at": "2026-11-02T09:00:00Z", "body": "issue & comment"}])),
            "/repos/acme/app/pulls/42/comments" => raw(serde_json::json!([{"id": 2, "user": {"login": "b"}, "path": "x.rs", "line": 3, "created_at": "2026-11-02T10:00:00Z", "body": "line one\nline <two>"}])),
            _ => github(hit),
        }
    });
    let cache = tempfile::tempdir().unwrap();
    let page = get(&pr(), &fake, cache.path()).unwrap();
    assert!(page.html.contains("PR &lt;b&gt;source&lt;/b&gt;"), "{}", page.html);
    assert!(page.html.contains("issue &amp; comment"), "{}", page.html);
    assert!(page.html.contains("line one<br>\nline &lt;two&gt;"), "{}", page.html);
}

#[test]
fn closed_draft_pr_shows_closed() {
    let fake = Fake::start(|hit: &Hit| {
        if hit.path != "/repos/acme/app/pulls/42" {
            return github(hit);
        }
        let mut pr: serde_json::Value = serde_json::from_str(&fixture("github_pr.json")).unwrap();
        pr["state"] = "closed".into();
        pr["draft"] = true.into();
        json(200, pr.to_string())
    });
    let cache = tempfile::tempdir().unwrap();
    let page = get(&pr(), &fake, cache.path()).unwrap();
    assert!(page.html.contains("<strong>Closed</strong>"), "{}", page.html);
}

// ---- attachments and links --------------------------------------------------------------------

#[test]
fn attachments_are_downloaded_with_the_token() {
    let fake = Fake::start(atlassian);
    let dir = tempfile::tempdir().unwrap();
    // A space and Korean in the cache path: the file URLs in the page must be percent-encoded.
    let cache = dir.path().join("cache 캐시");
    let cases = [
        (jira(), "/rest/api/3/attachment/content/1", "", SCREEN_PNG),
        (confluence(), "/wiki/download/attachments/123456/diagram.png", "version=1&api=v2", DIAGRAM_PNG),
    ];
    for (target, path, query, bytes) in cases {
        let page = get(&target, &fake, &cache).unwrap();
        let hits = fake.hits_to(path);
        assert_eq!(hits.len(), 1, "{path}");
        assert_eq!(hits[0].header("Authorization"), Some(BASIC), "{path}");
        assert_eq!(hits[0].query, query, "{path}");

        let local: Vec<String> = img_srcs(&page.html).into_iter().filter(|s| s.starts_with("file://")).collect();
        assert_eq!(local.len(), 1, "{}", page.html);
        assert!(!local[0].contains(' '), "{}", local[0]);
        let file = percent_decode(local[0].strip_prefix("file://").unwrap());
        assert!(file.starts_with(cache.to_str().unwrap()) && file.ends_with(".png"), "{file}");
        assert_eq!(std::fs::read(&file).unwrap(), bytes);
    }
}

#[test]
fn off_site_images_keep_their_address() {
    let fake = Fake::start(atlassian);
    let cache = tempfile::tempdir().unwrap();
    let page = get(&jira(), &fake, cache.path()).unwrap();
    let srcs = img_srcs(&page.html);
    assert!(srcs.contains(&"https://cdn.example.invalid/logo.png".to_string()), "{srcs:?}");
    assert!(srcs.contains(&"https://example.atlassian.net.invalid/steal.png".to_string()), "{srcs:?}");
    assert!(fake.hits_to("/logo.png").is_empty());
    assert!(fake.hits_to("/steal.png").is_empty());
}

#[test]
fn relative_links_point_at_the_site() {
    let fake = Fake::start(atlassian);
    let cache = tempfile::tempdir().unwrap();
    let issue = get(&jira(), &fake, cache.path()).unwrap();
    assert!(issue.html.contains(r#"href="https://example.atlassian.net/browse/ABC-2""#), "{}", issue.html);
    let wiki = get(&confluence(), &fake, cache.path()).unwrap();
    assert!(wiki.html.contains(r#"href="https://example.atlassian.net/wiki/spaces/OPS/pages/123000/Checklist""#), "{}", wiki.html);
}

// ---- cache ------------------------------------------------------------------------------------

#[test]
fn cache_is_used_unless_fresh() {
    let fake = Fake::start(atlassian);
    let cache = tempfile::tempdir().unwrap();
    let ep = fake.endpoints();
    let first = fetch::fetch(&confluence(), &tokens(), cache.path(), false, &ep).unwrap();
    let again = fetch::fetch(&confluence(), &tokens(), cache.path(), false, &ep).unwrap();
    assert_eq!(fake.hits_to("/wiki/api/v2/pages/123456").len(), 1);
    assert_eq!(again, first);
    fetch::fetch(&confluence(), &tokens(), cache.path(), true, &ep).unwrap();
    assert_eq!(fake.hits_to("/wiki/api/v2/pages/123456").len(), 2);
}

#[test]
fn unwritable_cache_does_not_fail_the_fetch() {
    let fake = Fake::start(atlassian);
    let dir = tempfile::tempdir().unwrap();
    let cache = dir.path().join("a-file");
    std::fs::write(&cache, "not a folder").unwrap();
    let page = get(&confluence(), &fake, &cache).unwrap();
    assert_eq!(page.title, "Deploy runbook");
}

// ---- errors -----------------------------------------------------------------------------------

#[test]
fn no_token_points_to_peek_auth() {
    let fake = Fake::start(|hit: &Hit| if hit.path.starts_with("/repos/") { github(hit) } else { atlassian(hit) });
    let cache = tempfile::tempdir().unwrap();
    let cases = [(jira(), "peek auth atlassian example.atlassian.net"), (pr(), "peek auth github")];
    for (target, hint) in cases {
        let err = fetch::fetch(&target, &Mem::default(), cache.path(), false, &fake.endpoints()).unwrap_err();
        assert_eq!(err, FetchError::NoToken { hint: hint.into() });
        assert!(fetch::error_page(&err, &target).html.contains(hint));
    }
    assert!(fake.hits().is_empty());
}

#[test]
fn unauthorized_points_to_peek_auth() {
    let fake = Fake::start(|hit: &Hit| json(if hit.path.starts_with("/repos/") { 403 } else { 401 }, "{}"));
    let cache = tempfile::tempdir().unwrap();
    let cases = [(jira(), 401, "peek auth atlassian example.atlassian.net"), (pr(), 403, "peek auth github")];
    for (target, code, hint) in cases {
        let err = get(&target, &fake, cache.path()).unwrap_err();
        assert!(matches!(err, FetchError::Http { status, .. } if status == code), "{err:?}");
        let page = fetch::error_page(&err, &target);
        assert!(page.html.contains(hint), "{}", page.html);
        assert!(page.html.contains(&code.to_string()), "{}", page.html);
    }
}

#[test]
fn not_found_page() {
    let fake = Fake::start(|_: &Hit| json(404, r#"{"errorMessages":["Issue does not exist or you do not have permission to see it."]}"#));
    let cache = tempfile::tempdir().unwrap();
    let err = get(&jira(), &fake, cache.path()).unwrap_err();
    assert!(matches!(err, FetchError::Http { status: 404, .. }), "{err:?}");
    let page = fetch::error_page(&err, &jira());
    assert!(page.title.contains("ABC-1"), "{}", page.title);
    assert!(page.html.to_lowercase().contains("not found"), "{}", page.html);
    assert_eq!(page.url, "https://example.atlassian.net/browse/ABC-1");
}

#[test]
fn timeout_gives_error_page() {
    let fake = Fake::start(|hit: &Hit| Reply { delay: Duration::from_secs(3), ..atlassian(hit) });
    let cache = tempfile::tempdir().unwrap();
    let start = Instant::now();
    let err = get(&jira(), &fake, cache.path()).unwrap_err();
    assert!(start.elapsed() < Duration::from_secs(2), "{:?}", start.elapsed());
    assert_eq!(err, FetchError::Timeout);
    let page = fetch::error_page(&err, &jira());
    assert!(page.html.contains("in time"), "{}", page.html);
}

#[test]
fn unreachable_gives_error_page() {
    // Port 1 (tcpmux) has no listener; a freed ephemeral port could be taken by another test's fake server.
    let base = "http://127.0.0.1:1".to_string();
    let ep = Endpoints { atlassian_base: Some(base.clone()), github_api: base, timeout: Duration::from_millis(500) };
    let cache = tempfile::tempdir().unwrap();
    let err = fetch::fetch(&jira(), &tokens(), cache.path(), false, &ep).unwrap_err();
    assert!(matches!(err, FetchError::Other(_)), "{err:?}");
    assert!(fetch::error_page(&err, &jira()).html.contains("Could not reach"));
}

// ---- peek auth --------------------------------------------------------------------------------

/// Runs this test binary again as a child that calls `run_auth` with real stdin (a pipe) and writes what it stored.
fn auth_child(args: &str, stdin: &str) -> (String, String) {
    let dir = tempfile::tempdir().unwrap();
    let out = dir.path().join("stored");
    let mut child = Command::new(std::env::current_exe().unwrap())
        .args(["auth_reads_secret_from_stdin", "--exact", "--nocapture", "--test-threads=1"])
        .env("PEEK_TEST_AUTH_ARGS", args)
        .env("PEEK_TEST_AUTH_OUT", &out)
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .spawn()
        .unwrap();
    child.stdin.take().unwrap().write_all(stdin.as_bytes()).unwrap();
    let res = child.wait_with_output().unwrap();
    assert!(res.status.success(), "{}", String::from_utf8_lossy(&res.stderr));
    (std::fs::read_to_string(&out).unwrap(), String::from_utf8_lossy(&res.stderr).into_owned())
}

#[test]
fn auth_reads_secret_from_stdin() {
    if let (Ok(args), Ok(out)) = (std::env::var("PEEK_TEST_AUTH_ARGS"), std::env::var("PEEK_TEST_AUTH_OUT")) {
        let store = Mem::default();
        let args: Vec<String> = args.split_whitespace().map(String::from).collect();
        let report = match fetch::run_auth(&args, &store) {
            Ok(()) => {
                let mut stored: Vec<String> = store.0.lock().unwrap().iter().map(|(k, v)| format!("{k}={v}")).collect();
                stored.sort();
                format!("ok {}", stored.join(" "))
            }
            Err(e) => format!("err {} stored={}", e.kind() == io::ErrorKind::InvalidInput, store.0.lock().unwrap().len()),
        };
        std::fs::write(out, report).unwrap();
        return;
    }

    let (stored, stderr) = auth_child("github", "ghp-secret-1\n");
    assert_eq!(stored, "ok github=ghp-secret-1");
    assert!(stderr.contains("token"), "{stderr}");
    assert!(!stderr.contains("ghp-secret-1"), "{stderr}");

    let (stored, stderr) = auth_child("atlassian https://example.atlassian.net/", "me@example.com\nat-secret-2\n");
    assert_eq!(stored, "ok atlassian:example.atlassian.net=me@example.com:at-secret-2");
    assert!(!stderr.contains("at-secret-2"), "{stderr}");

    let (stored, _) = auth_child("github", "\n");
    assert_eq!(stored, "err true stored=0");
}
