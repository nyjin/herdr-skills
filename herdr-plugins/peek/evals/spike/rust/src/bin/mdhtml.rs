//! Experiment: a markdown file as the page peek would ship: rendered natively, no script, a CSP, find highlight
//! styles in the template, the document's folder as base for relative links and images.
//!   mdhtml <file.md> <out.html>
use pulldown_cmark::{html, Options, Parser};

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let src = std::fs::canonicalize(&a[1]).unwrap();
    let text = std::fs::read_to_string(&src).unwrap();
    let opts = Options::ENABLE_TABLES | Options::ENABLE_STRIKETHROUGH | Options::ENABLE_TASKLISTS | Options::ENABLE_FOOTNOTES;
    let mut body = String::new();
    html::push_html(&mut body, Parser::new_ext(&text, opts));
    let base = format!("file://{}/", src.parent().unwrap().display());
    let page = format!(r#"<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src * data: file:; style-src 'unsafe-inline'; font-src data: file:">
<base href="{base}"><style>
:root {{ color-scheme: dark; }}
html, body {{ margin: 0; background: #1e1e2e; color: #cdd6f4; }}
body {{ font: 14px/1.6 -apple-system, "Apple SD Gothic Neo", sans-serif; padding: 0 14px; }}
h1, h2, h3, h4 {{ color: #89b4fa; line-height: 1.3; margin: 1.2em 0 .5em; }}
h1 {{ font-size: 1.6em; border-bottom: 1px solid #313244; padding-bottom: .3em; }}
h2 {{ font-size: 1.35em; border-bottom: 1px solid #313244; padding-bottom: .25em; }}
a {{ color: #89b4fa; }}
code {{ font-family: "JetBrains Mono", Menlo, monospace; font-size: .92em; background: #313244; padding: .1em .35em; border-radius: 4px; }}
pre {{ background: #181825; padding: .8em 1em; border-radius: 6px; }}
pre code {{ background: none; padding: 0; white-space: pre-wrap; word-break: break-all; }}
table {{ border-collapse: collapse; margin: .8em 0; }}
th, td {{ border: 1px solid #313244; padding: .3em .6em; vertical-align: top; }}
img {{ max-width: 100%; }}
blockquote {{ margin: .8em 0; padding: 0 1em; color: #a6adc8; border-left: 3px solid #6c7086; }}
::highlight(peek-find) {{ background-color: rgba(249,226,175,.35); }}
::highlight(peek-cur) {{ background-color: #f9e2af; color: #11111b; }}
</style></head><body>{body}</body></html>"#);
    std::fs::write(&a[2], page).unwrap();
}
