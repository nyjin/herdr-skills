//! Experiment: a source file as an HTML page for the renderer, highlighted natively with syntect (no page script).
//!   srchtml <source> <out.html> [line]
use std::fmt::Write as _;
use std::time::Instant;
use syntect::easy::HighlightLines;
use syntect::highlighting::ThemeSet;
use syntect::html::{styled_line_to_highlighted_html, IncludeBackground};
use syntect::parsing::SyntaxSet;
use syntect::util::LinesWithEndings;

fn esc(s: &str) -> String {
    s.replace('&', "&amp;").replace('<', "&lt;").replace('>', "&gt;")
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let (src, out) = (&a[1], &a[2]);
    let hit: usize = a.get(3).and_then(|s| s.parse().ok()).unwrap_or(0);
    let t0 = Instant::now();
    let ss = SyntaxSet::load_defaults_newlines();
    let ts = ThemeSet::load_defaults();
    let t_load = t0.elapsed();
    let text = std::fs::read_to_string(src).unwrap();
    let syntax = ss.find_syntax_for_file(src).ok().flatten().unwrap_or_else(|| ss.find_syntax_plain_text());
    let mut h = HighlightLines::new(syntax, &ts.themes["base16-ocean.dark"]);
    let mut rows = String::new();
    for (i, line) in LinesWithEndings::from(&text).enumerate() {
        let regions = h.highlight_line(line, &ss).unwrap();
        let html = styled_line_to_highlighted_html(&regions, IncludeBackground::No).unwrap();
        let n = i + 1;
        let class = if n == hit { " class=\"hit\"" } else { "" };
        write!(rows, "<tr id=\"L{n}\"{class}><td class=\"n\">{n}</td><td class=\"c\">{}</td></tr>", html.trim_end_matches('\n')).unwrap();
    }
    let page = format!(r#"<!doctype html><html><head><meta charset="utf-8"><title>ready</title><style>
body {{ margin: 0; background: #1e1e2e; color: #cdd6f4; font: 14px/1.5 "JetBrains Mono", Menlo, monospace; }}
header {{ padding: 6px 12px; color: #89b4fa; border-bottom: 1px solid #45475a; }}
table {{ border-collapse: collapse; width: 100%; }}
td.n {{ color: #6c7086; text-align: right; padding: 0 12px; user-select: none; vertical-align: top; width: 1%; white-space: nowrap; }}
td.c {{ white-space: pre-wrap; word-break: break-all; padding-right: 12px; }}
tr.hit {{ background: #45475a; }}
</style></head><body><header>{}</header><table>{rows}</table></body></html>"#, esc(src));
    std::fs::write(out, page).unwrap();
    eprintln!("{{\"load_syntax_ms\":{},\"total_ms\":{},\"lines\":{}}}", t_load.as_millis(), t0.elapsed().as_millis(), text.lines().count());
}
