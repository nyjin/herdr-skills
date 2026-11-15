//! The page the viewer loads: template (theme, font size, CSP, find styles), markdown, source, images, HTML files,
//! fetched content, URLs. Files are written to temporary folders so every path in an assertion is known.
use peek::fetch::Fetched;
use peek::page::{browser_page, build, kind_of, page_url, Doc, FileKind, PageOptions};
use peek::state::Mode;
use std::fs;
use std::path::{Path, PathBuf};

const CSP: &str = "default-src 'none'; img-src * data: file:; style-src 'unsafe-inline'; font-src data: file:";

fn opts(dark: bool, mode: Mode, line: Option<u32>) -> PageOptions {
    PageOptions { dark, font_px: 15.0, mode, line }
}

fn rendered() -> PageOptions {
    opts(true, Mode::Rendered, None)
}

/// Writes `name` with `body` into `dir` (created) and returns its path.
fn write(dir: &Path, name: &str, body: &[u8]) -> PathBuf {
    fs::create_dir_all(dir).unwrap();
    let p = dir.join(name);
    fs::write(&p, body).unwrap();
    p
}

fn page_of(path: &Path, o: &PageOptions) -> String {
    build(&Doc::File(path.to_path_buf()), o).unwrap()
}

/// The page's text without tags (highlighting splits a line into one span per token).
fn text_of(page: &str) -> String {
    regex::Regex::new("<[^>]*>").unwrap().replace_all(page, "").into_owned()
}

/// `file://` URL of a folder whose path needs no percent-encoding (temporary folders), with a trailing slash.
fn folder_url(dir: &Path) -> String {
    let s = dir.to_str().unwrap();
    assert!(s.bytes().all(|b| b.is_ascii_alphanumeric() || b"/-._~".contains(&b)), "{s} needs encoding");
    format!("file://{s}/")
}

#[test]
fn markdown_page_has_csp_and_no_script_tag_of_ours() {
    let t = tempfile::tempdir().unwrap();
    let page = page_of(&write(t.path(), "doc.md", b"# Title\n\nHello *there*\n"), &rendered());
    assert!(page.contains(&format!(r#"<meta http-equiv="Content-Security-Policy" content="{CSP}">"#)));
    assert!(page.contains("<h1>Title</h1>"));
    assert!(page.contains("<em>there</em>"));
    assert!(!page.to_ascii_lowercase().contains("<script"), "the template must not add a script");
}

#[test]
fn raw_html_is_kept_but_inert() {
    let t = tempfile::tempdir().unwrap();
    let md = b"Before\n\n<script>alert(1)</script>\n\n<img src=\"x.png\" onerror=\"alert(2)\">\n";
    let page = page_of(&write(t.path(), "doc.md", md), &rendered());
    assert!(page.contains("<script>alert(1)</script>"));
    assert!(page.contains(r#"onerror="alert(2)""#));
    assert!(page.contains(CSP));
}

#[test]
fn find_styles_in_template() {
    let t = tempfile::tempdir().unwrap();
    let docs = [
        Doc::File(write(t.path(), "a.md", b"text\n")),
        Doc::File(write(t.path(), "a.rs", b"fn main() {}\n")),
        Doc::File(write(t.path(), "a.png", b"\x89PNG")),
        Doc::File(write(t.path(), "a.html", b"<!doctype html><html><head></head><body>x</body></html>")),
        Doc::Fetched(fetched()),
    ];
    for doc in &docs {
        let page = build(doc, &rendered()).unwrap();
        assert!(page.contains("::highlight(peek-find)"), "{page}");
        assert!(page.contains("::highlight(peek-cur)"), "{page}");
    }
}

#[test]
fn relative_image_uses_document_base() {
    let t = tempfile::tempdir().unwrap();
    let folder = t.path().join("doc-folder");
    let page = page_of(&write(&folder, "doc.md", b"![shot](img/a.png)\n"), &rendered());
    assert!(page.contains(&format!(r#"<base href="{}">"#, folder_url(&folder))), "{page}");
    assert!(page.contains(r#"src="img/a.png""#));
}

#[test]
fn source_page_marks_line() {
    let t = tempfile::tempdir().unwrap();
    let src: String = (1..=200).map(|n| format!("let v{n} = {n};\n")).collect();
    let page = page_of(&write(t.path(), "main.rs", src.as_bytes()), &opts(true, Mode::Rendered, Some(120)));
    assert!(page.contains(r#"id="L120" class="hit""#));
    assert!(page.contains(r#"<tr id="L119">"#));
    assert!(page.contains(r#"<tr id="L200">"#));
    assert_eq!(page.matches("class=\"hit\"").count(), 1);
    assert!(page.contains("<span"), "a .rs file is highlighted");
}

#[test]
fn source_page_caps_highlighting() {
    let t = tempfile::tempdir().unwrap();
    let page = page_of(&write(t.path(), "big.py", "x = 1\n".repeat(60_000).as_bytes()), &rendered());
    assert!(page.contains(r#"<tr id="L1">"#));
    assert!(page.contains(r#"<tr id="L60000">"#));
    assert!(page.contains("Highlighting stops at line 20,000"));
    let cut = page.find(r#"id="L20001""#).unwrap();
    let last_highlighted = &page[page.find(r#"id="L20000""#).unwrap()..cut];
    assert!(last_highlighted.contains("<span"), "line 20,000 is still highlighted");
    assert!(!page[cut..].contains("<span"), "no highlighting after line 20,000");
}

#[test]
fn invalid_utf8_is_shown_lossily() {
    let t = tempfile::tempdir().unwrap();
    let bytes = b"ok\xff\xfe\x00 end\n";
    for name in ["bad.txt", "bad.rs", "bad.md", "bad.html", "no-extension"] {
        let text = text_of(&page_of(&write(t.path(), name, bytes), &rendered()));
        assert!(text.contains("ok\u{fffd}\u{fffd}"), "{name}: {text}");
        assert!(text.contains(" end"), "{name}");
    }
    let text = text_of(&page_of(&write(t.path(), "bad.md", bytes), &opts(true, Mode::Source, None)));
    assert!(text.contains("ok\u{fffd}\u{fffd}"));
}

#[test]
fn theme_follows_flag() {
    let t = tempfile::tempdir().unwrap();
    for path in [write(t.path(), "a.md", b"# x\n"), write(t.path(), "a.rs", b"fn x() {}\n")] {
        let dark = page_of(&path, &opts(true, Mode::Rendered, None));
        let light = page_of(&path, &opts(false, Mode::Rendered, None));
        // Catppuccin Mocha and Latte base colours
        assert!(dark.contains("#1e1e2e") && !dark.contains("#eff1f5"), "{}", path.display());
        assert!(light.contains("#eff1f5") && !light.contains("#1e1e2e"), "{}", path.display());
        assert!(dark.contains("color-scheme: dark") && light.contains("color-scheme: light"));
    }
}

#[test]
fn font_size_from_options() {
    let t = tempfile::tempdir().unwrap();
    for path in [write(t.path(), "a.md", b"x\n"), write(t.path(), "a.rs", b"fn x() {}\n")] {
        let big = page_of(&path, &PageOptions { font_px: 17.5, ..rendered() });
        let small = page_of(&path, &PageOptions { font_px: 11.25, ..rendered() });
        assert!(big.contains("17.5px") && !big.contains("11.25px"), "{big}");
        assert!(small.contains("11.25px") && !small.contains("17.5px"));
    }
}

#[test]
fn image_and_svg_pages() {
    let t = tempfile::tempdir().unwrap();
    let base = folder_url(t.path());
    let png = write(t.path(), "a b.png", b"\x89PNG");
    let page = page_of(&png, &rendered());
    assert!(page.contains(&format!(r#"<img src="{base}a%20b.png""#)), "{page}");
    // A raster image has no source view: the image page again.
    assert!(page_of(&png, &opts(true, Mode::Source, None)).contains("<img src="));

    let svg = write(t.path(), "d.svg", b"<svg xmlns=\"http://www.w3.org/2000/svg\"><circle r=\"4\"/></svg>\n");
    assert!(page_of(&svg, &rendered()).contains(&format!(r#"<img src="{base}d.svg""#)));
    let source = page_of(&svg, &opts(true, Mode::Source, None));
    assert!(source.contains(r#"<tr id="L1">"#) && source.contains("&lt;"), "{source}");
    assert!(!source.contains("<img"));
}

#[test]
fn page_file_url_is_encoded() {
    // A Korean file name (U+D55C U+AE00) and a space: each UTF-8 byte is percent-encoded.
    assert_eq!(
        page_url(Path::new("/tmp/peek-501/my docs/한글.html"), 7),
        "file:///tmp/peek-501/my%20docs/%ED%95%9C%EA%B8%80.html?peek=7"
    );
    assert_eq!(page_url(Path::new("/tmp/a#b/c?d%e.html"), 1), "file:///tmp/a%23b/c%3Fd%25e.html?peek=1");

    // The document base of a markdown file in a folder with a space and a Korean name is encoded the same way.
    let t = tempfile::tempdir().unwrap();
    let page = page_of(&write(&t.path().join("my 한글"), "doc.md", b"x\n"), &rendered());
    assert!(page.contains(&format!(r#"<base href="{}my%20%ED%95%9C%EA%B8%80/">"#, folder_url(t.path()))), "{page}");
}

#[test]
fn browser_page_uses_absolute_urls() {
    let t = tempfile::tempdir().unwrap();
    let folder = t.path().join("doc folder");
    let md = b"![i](img/a.png) [o](other.md) [f](#top) [w](https://example.com/x) [r](/etc/hosts) <me@example.com>\n\n\
               <img src=\"raw.png\">\n";
    let doc = Doc::File(write(&folder, "doc.md", md));
    let page = browser_page(&doc, &rendered()).unwrap();
    let base = format!("{}doc%20folder/", folder_url(t.path()));
    assert!(page.contains(&format!(r#"src="{base}img/a.png""#)), "{page}");
    assert!(page.contains(&format!(r#"href="{base}other.md""#)));
    assert!(page.contains(&format!(r#"src="{base}raw.png""#)));
    assert!(page.contains(r##"href="#top""##), "in-page links stay in the page");
    assert!(page.contains(r#"href="https://example.com/x""#));
    assert!(page.contains(r#"href="file:///etc/hosts""#));
    assert!(page.contains(r#"href="mailto:me@example.com""#), "an email autolink is not a path");
    assert!(!page.contains("<base"));
    assert!(page.contains(CSP), "the CSP keeps raw HTML inert in a browser too");
}

fn fetched() -> Fetched {
    Fetched {
        title: "PROJ-1 Fix the <parser>".into(),
        html: "<p>The body</p>".into(),
        url: "https://acme.atlassian.net/browse/PROJ-1".into(),
        fetched_at: "2026-11-15T22:14:43+09:00".into(),
    }
}

#[test]
fn fetched_doc_page_shows_title_and_fetch_time() {
    let page = build(&Doc::Fetched(fetched()), &rendered()).unwrap();
    assert!(page.contains("PROJ-1 Fix the &lt;parser&gt;"), "{page}");
    assert!(page.contains("2026-11-15T22:14:43+09:00"));
    assert!(page.contains("<p>The body</p>"));
    assert!(page.contains("https://acme.atlassian.net/browse/PROJ-1"));
    assert!(page.contains(CSP));

    let source = build(&Doc::Fetched(fetched()), &opts(true, Mode::Source, None)).unwrap();
    assert!(source.contains(r#"<tr id="L1">"#) && source.contains("&lt;"), "{source}");
    assert!(!source.contains("<p>The body</p>"));
}

#[test]
fn source_mode_shows_markdown_as_source() {
    let t = tempfile::tempdir().unwrap();
    let page = page_of(&write(t.path(), "doc.md", b"# Title\n\ntext\n"), &opts(true, Mode::Source, Some(3)));
    assert!(page.contains(r#"<tr id="L1">"#));
    assert!(page.contains(r#"id="L3" class="hit""#));
    assert!(text_of(&page).contains("# Title"), "{page}");
    assert!(!page.contains("<h1>"));
}

#[test]
fn html_file_keeps_its_own_page() {
    let t = tempfile::tempdir().unwrap();
    let folder = t.path().join("site");
    let html = b"<!DOCTYPE html>\n<html lang=\"en\"><head><link rel=\"stylesheet\" href=\"s.css\"></head>\
                 <body><p>hi</p></body></html>";
    let page = page_of(&write(&folder, "index.html", html), &rendered());
    assert!(page.starts_with("<!DOCTYPE html>"), "nothing before the doctype (quirks mode)");
    let head = page.find("<head>").unwrap();
    let base = page.find(&format!(r#"<base href="{}">"#, folder_url(&folder))).unwrap();
    assert!(head < base && base < page.find("<link").unwrap(), "{page}");
    assert!(page.contains(r#"<link rel="stylesheet" href="s.css">"#));
    // Linked stylesheets of the file still load: our CSP for HTML files only stops scripts and plugins.
    assert!(!page.contains("default-src"));

    // A file with its own base keeps it.
    let own_base = b"<html><head><base href=\"https://x.org/\"></head></html>";
    let own = page_of(&write(&folder, "own.html", own_base), &rendered());
    assert_eq!(own.matches("<base").count(), 1);
    assert!(own.contains("https://x.org/"));
}

#[test]
fn kind_by_name_and_extension() {
    let cases = [
        ("README.md", FileKind::Markdown),
        ("notes.MARKDOWN", FileKind::Markdown),
        ("main.rs", FileKind::Source),
        ("Makefile", FileKind::Source),
        ("x.PNG", FileKind::Image),
        ("x.jpeg", FileKind::Image),
        ("x.svg", FileKind::Svg),
        ("x.htm", FileKind::Html),
        ("notes.txt", FileKind::Text),
        ("server.log", FileKind::Text),
        ("blob.unknownext", FileKind::Text),
        ("LICENSE", FileKind::Text),
    ];
    for (name, kind) in cases {
        assert_eq!(kind_of(Path::new(name)), kind, "{name}");
    }
}

#[test]
fn missing_file_is_an_error() {
    let t = tempfile::tempdir().unwrap();
    for name in ["gone.md", "gone.rs", "gone.png"] {
        assert!(build(&Doc::File(t.path().join(name)), &rendered()).is_err(), "{name}");
    }
}

#[test]
fn html_file_blocks_scripts_but_keeps_its_styles() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("report.html");
    std::fs::write(&file, "<!doctype html><html><head><link rel=\"stylesheet\" href=\"style.css\"></head><body><script>x()</script>hi</body></html>").unwrap();
    let opts = peek::page::PageOptions { dark: true, font_px: 14.0, mode: peek::state::Mode::Rendered, line: None };
    for page in [peek::page::build(&peek::page::Doc::File(file.clone()), &opts).unwrap(), peek::page::browser_page(&peek::page::Doc::File(file.clone()), &opts).unwrap()] {
        assert!(page.contains("script-src 'none'; object-src 'none'"), "{page}");
        assert!(!page.contains("default-src 'none'")); // its own stylesheet must still load
        assert!(page.contains("style.css"));
    }
}
