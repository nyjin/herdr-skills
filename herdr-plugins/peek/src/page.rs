//! The page the viewer loads: markdown, source, image, SVG, HTML or fetched content in peek's template (theme,
//! font size, CSP, find highlight styles). (Task 3)
use crate::fetch::Fetched;
use crate::state::Mode;
use pulldown_cmark::{html, CowStr, Event, LinkType, Options, Parser, Tag};
use regex::{Captures, Regex};
use std::fmt::Write as _;
use std::fs;
use std::io;
use std::os::unix::ffi::OsStrExt;
use std::path::{Path, PathBuf};
use std::sync::LazyLock;
use syntect::easy::HighlightLines;
use syntect::highlighting::{Theme, ThemeSet};
use syntect::html::{append_highlighted_html_for_styled_line, IncludeBackground};
use syntect::parsing::{SyntaxReference, SyntaxSet};
use syntect::util::LinesWithEndings;

pub enum Doc {
    File(PathBuf),
    Fetched(Fetched),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum FileKind {
    Markdown,
    Source,
    Image,
    Svg,
    Html,
    Text,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct PageOptions {
    /// Catppuccin Mocha when true, Latte when false.
    pub dark: bool,
    /// Base font size in CSS px.
    pub font_px: f32,
    pub mode: Mode,
    /// Line to mark and scroll to (source view).
    pub line: Option<u32>,
}

/// Every page of peek's own template carries this policy. HTML files keep their own page and do without it: it
/// would block their linked stylesheets. Page scripts are off either way.
const CSP: &str = "default-src 'none'; img-src * data: file:; style-src 'unsafe-inline'; font-src data: file:";

/// Source past this line is plain text: syntect on a huge file would hold the page for seconds.
const HIGHLIGHT_LINES: usize = 20_000;

const MARKDOWN_OPTIONS: Options = Options::ENABLE_TABLES
    .union(Options::ENABLE_STRIKETHROUGH)
    .union(Options::ENABLE_TASKLISTS)
    .union(Options::ENABLE_FOOTNOTES);

/// Catppuccin colours (https://github.com/catppuccin/palette) used by the template.
struct Palette {
    scheme: &'static str,
    base: &'static str,
    mantle: &'static str,
    surface0: &'static str,
    surface1: &'static str,
    text: &'static str,
    subtext0: &'static str,
    overlay0: &'static str,
    blue: &'static str,
    /// Find marks: every match lightly, the current one strongly.
    find: &'static str,
    current: &'static str,
    current_text: &'static str,
    /// syntect's bundled theme for source pages.
    syntax_theme: &'static str,
}

const MOCHA: Palette = Palette {
    scheme: "dark",
    base: "#1e1e2e",
    mantle: "#181825",
    surface0: "#313244",
    surface1: "#45475a",
    text: "#cdd6f4",
    subtext0: "#a6adc8",
    overlay0: "#6c7086",
    blue: "#89b4fa",
    find: "rgba(249, 226, 175, .35)",
    current: "#f9e2af",
    current_text: "#11111b",
    syntax_theme: "base16-ocean.dark",
};

const LATTE: Palette = Palette {
    scheme: "light",
    base: "#eff1f5",
    mantle: "#e6e9ef",
    surface0: "#ccd0da",
    surface1: "#bcc0cc",
    text: "#4c4f69",
    subtext0: "#6c6f85",
    overlay0: "#9ca0b0",
    blue: "#1e66f5",
    find: "rgba(223, 142, 29, .3)",
    current: "#df8e1d",
    current_text: "#eff1f5",
    syntax_theme: "base16-ocean.light",
};

fn palette(dark: bool) -> &'static Palette {
    if dark {
        &MOCHA
    } else {
        &LATTE
    }
}

static SYNTAXES: LazyLock<SyntaxSet> = LazyLock::new(SyntaxSet::load_defaults_newlines);
static THEMES: LazyLock<ThemeSet> = LazyLock::new(ThemeSet::load_defaults);

fn lower_ext(path: &Path) -> String {
    path.extension().map(|e| e.to_string_lossy().to_ascii_lowercase()).unwrap_or_default()
}

/// syntect's syntax for a file, matched by file name (`Makefile`) then extension; none for plain text.
fn syntax_for(path: &Path) -> Option<&'static SyntaxReference> {
    let name = path.file_name()?.to_str()?;
    let ext = path.extension().and_then(|e| e.to_str());
    SYNTAXES
        .find_syntax_by_extension(name)
        .or_else(|| ext.and_then(|e| SYNTAXES.find_syntax_by_extension(e)))
        .filter(|s| s.name != "Plain Text")
}

pub fn kind_of(path: &Path) -> FileKind {
    match lower_ext(path).as_str() {
        "md" | "markdown" | "mdown" | "mkd" | "mkdn" => FileKind::Markdown,
        "png" | "jpg" | "jpeg" | "gif" | "webp" | "bmp" | "ico" | "tif" | "tiff" | "avif" | "heic" => FileKind::Image,
        "svg" => FileKind::Svg,
        "html" | "htm" | "xhtml" => FileKind::Html,
        _ if syntax_for(path).is_some() => FileKind::Source,
        _ => FileKind::Text,
    }
}

pub fn build(doc: &Doc, opts: &PageOptions) -> io::Result<String> {
    page(doc, opts, false)
}

/// The same page for a browser: absolute `file://` references instead of a base inside the viewer's pages folder.
/// A `<base>` would send the page's own `#...` links to the document's folder.
pub fn browser_page(doc: &Doc, opts: &PageOptions) -> io::Result<String> {
    page(doc, opts, true)
}

/// `file://` URL of a page file, percent-encoded, with `?peek=<marker>` so readiness can tell loads apart.
pub fn page_url(path: &Path, marker: u64) -> String {
    let path = std::path::absolute(path).unwrap_or_else(|_| path.to_path_buf());
    format!("{}?peek={marker}", file_url(&path))
}

fn page(doc: &Doc, opts: &PageOptions, absolute: bool) -> io::Result<String> {
    let path = match doc {
        Doc::Fetched(f) => {
            return Ok(match opts.mode {
                Mode::Source => source_page(&f.html, SYNTAXES.find_syntax_by_extension("html"), &f.title, opts),
                Mode::Rendered => fetched_page(f, opts, absolute),
            });
        }
        Doc::File(path) => std::path::absolute(path)?,
    };
    let name = path.file_name().map(|n| n.to_string_lossy().into_owned()).unwrap_or_else(|| path.display().to_string());
    let folder = folder_url(path.parent().unwrap_or(Path::new("/")));
    match (kind_of(&path), opts.mode) {
        (FileKind::Image, _) | (FileKind::Svg, Mode::Rendered) => {
            fs::metadata(&path)?;
            let body = format!(r#"<img src="{}" alt="{}">"#, file_url(&path), esc(&name));
            Ok(template(opts, &name, "", IMAGE_CSS, "image", &body))
        }
        (FileKind::Markdown, Mode::Rendered) => {
            let body = markdown(&read_text(&path)?, absolute.then_some(folder.as_str()));
            let head = if absolute { String::new() } else { format!(r#"<base href="{folder}">"#) };
            Ok(template(opts, &name, &head, PROSE_CSS, "prose", &body))
        }
        (FileKind::Html, Mode::Rendered) => Ok(html_file_page(&read_text(&path)?, &folder, opts, absolute)),
        _ => Ok(source_page(&read_text(&path)?, syntax_for(&path), &name, opts)),
    }
}

/// The file's text, invalid UTF-8 replaced (a clicked file may be binary), a byte-order mark dropped.
fn read_text(path: &Path) -> io::Result<String> {
    let bytes = fs::read(path)?;
    let text = String::from_utf8_lossy(&bytes);
    Ok(text.strip_prefix('\u{feff}').unwrap_or(&text).to_string())
}

fn template(opts: &PageOptions, title: &str, head: &str, css: &str, class: &str, body: &str) -> String {
    let p = palette(opts.dark);
    format!(
        "<!doctype html>\n<html><head><meta charset=\"utf-8\">\n\
         <meta http-equiv=\"Content-Security-Policy\" content=\"{CSP}\">\n{head}<title>{title}</title>\n\
         <style>\n{common}{css}{find}</style></head>\n<body class=\"{class}\">{body}</body></html>\n",
        title = esc(title),
        common = common_css(p, opts.font_px),
        find = find_css(p),
    )
}

fn common_css(p: &Palette, font_px: f32) -> String {
    format!(
        ":root {{ color-scheme: {scheme}; --base: {base}; --mantle: {mantle}; --surface0: {surface0}; \
         --surface1: {surface1}; --text: {text}; --subtext0: {subtext0}; --overlay0: {overlay0}; --blue: {blue}; }}\n\
         html, body {{ margin: 0; background: var(--base); color: var(--text); }}\n\
         body {{ font: {font_px}px/1.6 -apple-system, \"Apple SD Gothic Neo\", sans-serif; }}\n\
         a {{ color: var(--blue); }}\n\
         code, pre, body.source {{ font-family: \"JetBrains Mono\", Menlo, monospace; }}\n",
        scheme = p.scheme,
        base = p.base,
        mantle = p.mantle,
        surface0 = p.surface0,
        surface1 = p.surface1,
        text = p.text,
        subtext0 = p.subtext0,
        overlay0 = p.overlay0,
        blue = p.blue,
    )
}

/// In the page from the start: added at the first search, the first capture after it misses them.
fn find_css(p: &Palette) -> String {
    format!(
        "::highlight(peek-find) {{ background-color: {}; }}\n\
         ::highlight(peek-cur) {{ background-color: {}; color: {}; }}\n",
        p.find, p.current, p.current_text
    )
}

const PROSE_CSS: &str = "\
body.prose { padding: .2em 1em 2em; }
h1, h2, h3, h4, h5, h6 { color: var(--blue); line-height: 1.3; margin: 1.2em 0 .5em; }
h1 { font-size: 1.6em; border-bottom: 1px solid var(--surface0); padding-bottom: .3em; }
h2 { font-size: 1.35em; border-bottom: 1px solid var(--surface0); padding-bottom: .25em; }
code { font-size: .92em; background: var(--surface0); padding: .1em .35em; border-radius: 4px; }
pre { background: var(--mantle); padding: .8em 1em; border-radius: 6px; }
pre code { background: none; padding: 0; white-space: pre-wrap; word-break: break-all; }
table { border-collapse: collapse; margin: .8em 0; }
th, td { border: 1px solid var(--surface0); padding: .3em .6em; vertical-align: top; }
img { max-width: 100%; }
blockquote { margin: .8em 0; padding: 0 1em; color: var(--subtext0); border-left: 3px solid var(--overlay0); }
hr { border: none; border-top: 1px solid var(--surface0); }
.footnote-definition { font-size: .9em; color: var(--subtext0); }
header.fetched { margin: 1em 0; padding-bottom: .4em; border-bottom: 1px solid var(--surface0); }
header.fetched h1 { margin: 0 0 .3em; padding: 0; border: none; }
header.fetched p { margin: 0; font-size: .85em; color: var(--subtext0); }
";

const SOURCE_CSS: &str = "\
body.source { line-height: 1.5; tab-size: 4; }
table.source { border-collapse: collapse; width: 100%; }
td.n { color: var(--overlay0); text-align: right; padding: 0 1em 0 .6em; user-select: none; vertical-align: top; \
width: 1%; white-space: nowrap; }
td.c { white-space: pre-wrap; word-break: break-all; padding-right: .6em; }
tr.hit { background: var(--surface1); }
tr.note td.c { color: var(--subtext0); font-style: italic; font-family: -apple-system, sans-serif; padding: .4em 0; }
";

const IMAGE_CSS: &str = "\
body.image { display: flex; justify-content: center; align-items: flex-start; box-sizing: border-box; \
min-height: 100vh; padding: 1em; }
body.image img { max-width: 100%; height: auto; }
";

fn markdown(text: &str, absolute_base: Option<&str>) -> String {
    let parser = Parser::new_ext(text, MARKDOWN_OPTIONS);
    let mut out = String::with_capacity(text.len() * 3 / 2);
    match absolute_base {
        None => html::push_html(&mut out, parser),
        Some(base) => html::push_html(&mut out, parser.map(|ev| rebase_event(ev, base))),
    }
    out
}

fn rebase_event<'a>(ev: Event<'a>, base: &str) -> Event<'a> {
    match ev {
        // An email autolink's destination is an address; the HTML writer adds `mailto:` to it.
        Event::Start(Tag::Link { link_type, dest_url, title, id }) if link_type != LinkType::Email => {
            Event::Start(Tag::Link { link_type, dest_url: absolutize(&dest_url, base).into(), title, id })
        }
        Event::Start(Tag::Image { link_type, dest_url, title, id }) => {
            Event::Start(Tag::Image { link_type, dest_url: absolutize(&dest_url, base).into(), title, id })
        }
        Event::Html(s) => Event::Html(CowStr::from(rebase_attrs(&s, base))),
        Event::InlineHtml(s) => Event::InlineHtml(CowStr::from(rebase_attrs(&s, base))),
        ev => ev,
    }
}

/// `src` and `href` attributes in raw HTML, made absolute against `base`.
fn rebase_attrs(html: &str, base: &str) -> String {
    static ATTR: LazyLock<Regex> = LazyLock::new(|| {
        Regex::new(r#"(?i)(\s(?:src|href)\s*=\s*)(?:"([^"]*)"|'([^']*)'|([^\s"'>]+))"#).unwrap()
    });
    ATTR.replace_all(html, |c: &Captures| match (c.get(2), c.get(3), c.get(4)) {
        (_, Some(v), _) => format!("{}'{}'", &c[1], absolutize(v.as_str(), base)),
        (Some(v), _, _) | (_, _, Some(v)) => format!("{}\"{}\"", &c[1], absolutize(v.as_str(), base)),
        _ => c[0].to_string(),
    })
    .into_owned()
}

/// A reference resolved against `base` (a page or folder URL). In-page links (`#...`) and anything with a scheme
/// stay as written.
fn absolutize(r: &str, base: &str) -> String {
    static SCHEME: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"^[A-Za-z][A-Za-z0-9+.-]*:").unwrap());
    if r.is_empty() || r.starts_with('#') || SCHEME.is_match(r) {
        return r.to_string();
    }
    let scheme = base.split(':').next().unwrap_or("file");
    if r.starts_with("//") {
        return format!("{scheme}:{r}");
    }
    if r.starts_with('/') {
        let after = base.find("://").map_or(0, |i| i + 3);
        let origin = base[after..].find('/').map_or(base, |i| &base[..after + i]);
        return format!("{origin}{r}");
    }
    let page = base.split(['?', '#']).next().unwrap_or(base);
    format!("{}{r}", &page[..page.rfind('/').map_or(page.len(), |i| i + 1)])
}

/// An HTML file as it is (its own styles, no CSP of ours), with what the viewer needs added at the top of its head:
/// the charset (the text was read as UTF-8), the document folder as base, and the find styles. A browser gets
/// absolute references instead of the base.
fn html_file_page(text: &str, folder: &str, opts: &PageOptions, absolute: bool) -> String {
    static HAS_BASE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)<base[\s>]").unwrap());
    static HEAD: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)<head(\s[^>]*)?>").unwrap());
    static HTML: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)<html(\s[^>]*)?>").unwrap());
    static DOCTYPE: LazyLock<Regex> = LazyLock::new(|| Regex::new(r"(?i)^\s*<!doctype[^>]*>").unwrap());
    let (text, mut add) = if absolute {
        (rebase_attrs(text, folder), String::from(r#"<meta charset="utf-8">"#))
    } else {
        let mut add = String::from(r#"<meta charset="utf-8">"#);
        if !HAS_BASE.is_match(text) {
            write!(add, r#"<base href="{folder}">"#).unwrap();
        }
        (text.to_string(), add)
    };
    if !absolute {
        write!(add, "<style>\n{}</style>", find_css(palette(opts.dark))).unwrap();
    }
    // After <head>, else <html>, else the doctype: anything before the doctype puts the page in quirks mode.
    let at = [&*HEAD, &*HTML, &*DOCTYPE].iter().find_map(|re| re.find(&text)).map_or(0, |m| m.end());
    format!("{}{add}{}", &text[..at], &text[at..])
}

fn fetched_page(f: &Fetched, opts: &PageOptions, absolute: bool) -> String {
    let url = esc(&f.url);
    let header = format!(
        "<header class=\"fetched\"><h1>{}</h1><p><a href=\"{url}\">{url}</a> &middot; \
         Fetched <time datetime=\"{at}\">{at}</time></p></header>",
        esc(&f.title),
        at = esc(&f.fetched_at),
    );
    let (head, body) = if absolute {
        (String::new(), rebase_attrs(&f.html, &f.url))
    } else {
        (format!(r#"<base href="{url}">"#), f.html.clone())
    };
    template(opts, &f.title, &head, PROSE_CSS, "prose", &format!("{header}\n{body}"))
}

/// Line numbers and code in a table, one row per line (`id="L<n>"`, the marked line `class="hit"`); highlighted
/// with syntect up to `HIGHLIGHT_LINES`, plain text after that.
fn source_page(text: &str, syntax: Option<&SyntaxReference>, title: &str, opts: &PageOptions) -> String {
    let theme: &Theme = &THEMES.themes[palette(opts.dark).syntax_theme];
    let mut hl = syntax.map(|s| HighlightLines::new(s, theme));
    let mark = opts.line.map(|l| l as usize);
    let mut rows = String::with_capacity(text.len() * 4 + 1024);
    let mut cell = String::new();
    for (i, line) in LinesWithEndings::from(text).enumerate() {
        let n = i + 1;
        if n == HIGHLIGHT_LINES + 1 && hl.take().is_some() {
            write!(
                rows,
                "<tr class=\"note\"><td class=\"n\"></td><td class=\"c\">Highlighting stops at line {}; \
                 the lines after it are plain text.</td></tr>",
                thousands(HIGHLIGHT_LINES)
            )
            .unwrap();
        }
        cell.clear();
        let highlighted = hl.as_mut().is_some_and(|h| highlight_line(h, line, &mut cell).is_ok());
        if !highlighted {
            // A syntect error ends highlighting for the rest of the file; the line itself is shown plain.
            hl = None;
            cell.clear();
            cell.push_str(&esc(line.trim_end_matches(['\n', '\r'])));
        }
        let hit = if mark == Some(n) { r#" class="hit""# } else { "" };
        write!(rows, r#"<tr id="L{n}"{hit}><td class="n">{n}</td><td class="c">{cell}</td></tr>"#).unwrap();
    }
    let body = format!(r#"<table class="source"><tbody>{rows}</tbody></table>"#);
    template(opts, title, "", SOURCE_CSS, "source", &body)
}

fn highlight_line(h: &mut HighlightLines, line: &str, out: &mut String) -> Result<(), syntect::Error> {
    let mut regions = h.highlight_line(line, &SYNTAXES)?;
    if let Some(last) = regions.last_mut() {
        last.1 = last.1.trim_end_matches(['\n', '\r']);
    }
    append_highlighted_html_for_styled_line(&regions, IncludeBackground::No, out)
}

/// `20000` -> `20,000`.
fn thousands(n: usize) -> String {
    let digits = n.to_string();
    let mut out = String::new();
    for (i, c) in digits.chars().enumerate() {
        if i > 0 && (digits.len() - i).is_multiple_of(3) {
            out.push(',');
        }
        out.push(c);
    }
    out
}

fn esc(s: &str) -> String {
    let mut out = String::with_capacity(s.len());
    for c in s.chars() {
        match c {
            '&' => out.push_str("&amp;"),
            '<' => out.push_str("&lt;"),
            '>' => out.push_str("&gt;"),
            '"' => out.push_str("&quot;"),
            '\'' => out.push_str("&#39;"),
            c => out.push(c),
        }
    }
    out
}

/// `file://` URL of an absolute path: every byte outside `A-Za-z0-9-._~/` percent-encoded.
fn file_url(path: &Path) -> String {
    let mut url = String::from("file://");
    for &b in path.as_os_str().as_bytes() {
        if b.is_ascii_alphanumeric() || b"-._~/".contains(&b) {
            url.push(b as char);
        } else {
            write!(url, "%{b:02X}").unwrap();
        }
    }
    url
}

/// `file://` URL of a folder, ending in `/` (the base for its documents' relative references).
fn folder_url(dir: &Path) -> String {
    let mut url = file_url(dir);
    if !url.ends_with('/') {
        url.push('/');
    }
    url
}
