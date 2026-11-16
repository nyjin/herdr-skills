//! Terminal side of the viewer: input parsing (keys, SGR pixel mouse, Kitty replies), pane geometry, and row 1:
//! the top bar, the zoom row behind its `…`, and the find row.
use crate::kitty::Geometry;
use crate::script::FindQuery;

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Key {
    Char(char),
    Up,
    Down,
    PageUp,
    PageDown,
    Home,
    End,
    Backspace,
    Esc,
    Enter,
    /// Shift+Enter, from terminals that tell it apart (`CSI 13;2u` or `CSI 27;2;13~`).
    ShiftEnter,
    Tab,
    Alt(char),
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum MouseKind {
    Press,
    Release,
    Move,
    WheelUp,
    WheelDown,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Mouse {
    pub kind: MouseKind,
    pub button: u8,
    pub x_px: u32,
    pub y_px: u32,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum Input {
    Key(Key),
    Mouse(Mouse),
    /// A Kitty graphics reply (`ESC _G ... ESC \`), without the framing.
    Reply(String),
}

/// Inputs in `buf` and the number of bytes consumed; an incomplete sequence at the end (a lone escape included) is
/// left for the next read. The caller turns a lone escape that stays alone into `Key::Esc`.
pub fn parse(buf: &[u8]) -> (Vec<Input>, usize) {
    let mut out = Vec::new();
    let mut i = 0;
    while i < buf.len() {
        let rest = &buf[i..];
        let used = match rest[0] {
            0x1b => match escape(rest) {
                Some((input, n)) => {
                    out.extend(input);
                    n
                }
                None => break,
            },
            0x7f | 0x08 => {
                out.push(Input::Key(Key::Backspace));
                1
            }
            b'\r' | b'\n' => {
                out.push(Input::Key(Key::Enter));
                1
            }
            b'\t' => {
                out.push(Input::Key(Key::Tab));
                1
            }
            b => {
                let n = utf8_len(b);
                if rest.len() < n {
                    break;
                }
                if let Some(c) = std::str::from_utf8(&rest[..n]).ok().and_then(|s| s.chars().next()) {
                    if !c.is_control() {
                        out.push(Input::Key(Key::Char(c)));
                    }
                }
                n
            }
        };
        i += used;
    }
    (out, i)
}

fn utf8_len(b: u8) -> usize {
    match b {
        0xf0..=0xf7 => 4,
        0xe0..=0xef => 3,
        0xc0..=0xdf => 2,
        _ => 1,
    }
}

/// One escape sequence at the start of `s`: `None` when it is incomplete.
fn escape(s: &[u8]) -> Option<(Option<Input>, usize)> {
    match *s.get(1)? {
        b'[' => {
            if s.get(2) == Some(&b'<') {
                let end = s.iter().position(|&b| b == b'M' || b == b'm')?;
                return Some((mouse(&s[3..end], s[end] == b'M'), end + 1));
            }
            let end = 2 + s[2..].iter().position(|b| (0x40..=0x7e).contains(b))?;
            let key = match (&s[2..end], s[end]) {
                (b"", b'A') => Some(Key::Up),
                (b"", b'B') => Some(Key::Down),
                (b"", b'H') | (b"1", b'~') => Some(Key::Home),
                (b"", b'F') | (b"4", b'~') => Some(Key::End),
                (b"5", b'~') => Some(Key::PageUp),
                (b"6", b'~') => Some(Key::PageDown),
                (b"13;2", b'u') | (b"27;2;13", b'~') => Some(Key::ShiftEnter),
                _ => None,
            };
            Some((key.map(Input::Key), end + 1))
        }
        b'_' => {
            let end = s.windows(2).position(|w| w == b"\x1b\\")?;
            let body = String::from_utf8_lossy(&s[2..end]);
            Some((body.strip_prefix('G').map(|b| Input::Reply(b.to_string())), end + 2))
        }
        b'\x1b' => Some((Some(Input::Key(Key::Esc)), 1)),
        b => Some((Some(Input::Key(Key::Alt(b as char))), 2)),
    }
}

fn mouse(params: &[u8], press: bool) -> Option<Input> {
    let text = std::str::from_utf8(params).ok()?;
    let mut n = text.split(';').map(|v| v.parse::<u32>().ok());
    let (b, x, y) = (n.next()??, n.next()??, n.next()??);
    let kind = if b & 64 != 0 {
        if b & 1 == 0 { MouseKind::WheelUp } else { MouseKind::WheelDown }
    } else if b & 32 != 0 {
        MouseKind::Move
    } else if press {
        MouseKind::Press
    } else {
        MouseKind::Release
    };
    Some(Input::Mouse(Mouse { kind, button: (b & 3) as u8, x_px: x, y_px: y }))
}

/// Clicks, moves (for hover) and wheel, reported in pixels.
pub const MOUSE_ON: &str = "\x1b[?1000h\x1b[?1003h\x1b[?1006h\x1b[?1016h";
pub const MOUSE_OFF: &str = "\x1b[?1016l\x1b[?1006l\x1b[?1003l\x1b[?1000l";

/// The pane's cells and pixels from `TIOCGWINSZ`; without pixels, 8 x 18 px cells; without a size, 80 x 24.
pub fn geometry() -> Geometry {
    let mut ws: libc::winsize = unsafe { std::mem::zeroed() };
    let ok = unsafe { libc::ioctl(libc::STDOUT_FILENO, libc::TIOCGWINSZ, &mut ws) } == 0;
    let (cols, rows) = if ok && ws.ws_col > 0 && ws.ws_row > 0 { (ws.ws_col, ws.ws_row) } else { (80, 24) };
    let (cell_w, cell_h) = if ok && ws.ws_xpixel > 0 && ws.ws_ypixel > 0 {
        (ws.ws_xpixel as u32 / cols as u32, ws.ws_ypixel as u32 / rows as u32)
    } else {
        (8, 18)
    };
    Geometry { cols, rows, cell_w: cell_w.max(1), cell_h: cell_h.max(1) }
}

/// Whether the pane reports its size in pixels yet. herdr sends it a moment after the pane starts; until then
/// `geometry` falls back to 8 x 18 px cells.
pub fn pixel_size_known() -> bool {
    let mut ws: libc::winsize = unsafe { std::mem::zeroed() };
    (unsafe { libc::ioctl(libc::STDOUT_FILENO, libc::TIOCGWINSZ, &mut ws) } == 0) && ws.ws_xpixel > 0 && ws.ws_ypixel > 0
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BarItem {
    /// The name in the tooltip.
    pub label: &'static str,
    /// The key that does the same, `""` when there is none.
    pub key: &'static str,
    /// One of `link::ACTIONS`, or a row's own: `more` (open the zoom row), `close` (leave the row),
    /// `case`, `word`, `regex`, `prev`, `next` (find row).
    pub action: &'static str,
    /// What the item shows on its row: a symbol or a short word.
    pub glyph: &'static str,
}

/// The top bar's commands, left to right. Zoom sits behind `…` (`more_items`).
pub fn bar_items() -> Vec<BarItem> {
    vec![
        BarItem { label: "Reload", key: "r", action: "reload", glyph: "\u{27f3}" },
        BarItem { label: "Source", key: "t", action: "toggle", glyph: "Source" },
        BarItem { label: "Find", key: "/", action: "find", glyph: "\u{2315}" },
        BarItem { label: "Screenshot", key: "s", action: "screenshot", glyph: "Shot" },
        BarItem { label: "Open in browser", key: "o", action: "browser", glyph: "\u{2197}" },
        BarItem { label: "More: zoom", key: "", action: "more", glyph: "\u{2026}" },
    ]
}

/// The row `…` opens in place of the bar: zoom out, zoom in (the percentage between them), reset, close.
pub fn more_items() -> Vec<BarItem> {
    vec![
        BarItem { label: "Zoom out", key: "-", action: "zoom-out", glyph: "\u{2212}" },
        BarItem { label: "Zoom in", key: "+", action: "zoom-in", glyph: "+" },
        BarItem { label: "Reset zoom", key: "0", action: "zoom-reset", glyph: "Reset" },
        BarItem { label: "Close", key: "Esc", action: "close", glyph: "\u{2715}" },
    ]
}

/// The find row's buttons, after the query field: the options, then previous, next and close.
pub fn find_items() -> Vec<BarItem> {
    vec![
        BarItem { label: "Match case", key: "Alt-c", action: "case", glyph: "Aa" },
        BarItem { label: "Whole word", key: "Alt-w", action: "word", glyph: "ab" },
        BarItem { label: "Regular expression", key: "Alt-r", action: "regex", glyph: ".*" },
        BarItem { label: "Previous match", key: "Shift-Enter", action: "prev", glyph: "\u{2191}" },
        BarItem { label: "Next match", key: "Enter", action: "next", glyph: "\u{2193}" },
        BarItem { label: "Close", key: "Esc", action: "close", glyph: "\u{2715}" },
    ]
}

/// "Reload (r)": an item's name and key, shown while the pointer is over it.
pub fn tooltip(item: &BarItem) -> String {
    if item.key.is_empty() {
        item.label.to_string()
    } else {
        format!("{} ({})", item.label, item.key)
    }
}

/// What an item shows on the bar: its glyph when there is room, its key when the pane is narrow.
fn bar_word(item: &BarItem, narrow: bool) -> &'static str {
    if narrow && !item.key.is_empty() {
        item.key
    } else {
        item.glyph
    }
}

/// Terminal columns a string takes: East Asian wide characters (Hangul, CJK, full-width forms) count two.
pub fn display_width(s: &str) -> usize {
    s.chars()
        .map(|c| match c as u32 {
            0x1100..=0x115f | 0x2e80..=0xa4cf | 0xac00..=0xd7a3 | 0xf900..=0xfaff | 0xfe30..=0xfe4f | 0xff00..=0xff60 | 0xffe0..=0xffe6 => 2,
            _ => 1,
        })
        .sum()
}

/// `s` cut to at most `width` columns, with a mark when cut.
fn fit(s: &str, width: usize) -> String {
    if display_width(s) <= width {
        return s.to_string();
    }
    let mut out = String::new();
    for c in s.chars() {
        if display_width(&out) + display_width(&c.to_string()) + 1 > width {
            break;
        }
        out.push(c);
    }
    if width > 0 {
        out.push('~');
    }
    out
}

/// The end of `s` in at most `width` columns, with `…` in front when cut: what a text field shows of a long entry.
fn fit_tail(s: &str, width: usize) -> String {
    if display_width(s) <= width {
        return s.to_string();
    }
    let mut tail: Vec<char> = Vec::new();
    for c in s.chars().rev() {
        if display_width(&tail.iter().collect::<String>()) + display_width(&c.to_string()) + 1 > width {
            break;
        }
        tail.push(c);
    }
    let kept: String = tail.into_iter().rev().collect();
    if width > 0 {
        format!("\u{2026}{kept}")
    } else {
        kept
    }
}

/// `items` laid out right-aligned on a `cols`-wide row after `left` (the title, or the hovered item's tooltip),
/// with `extra` text right before item `extra_before`: the row text and each item's 1-based column range.
fn render_row(
    items: &[BarItem],
    left: &str,
    cols: u16,
    hover: Option<usize>,
    extra: Option<(usize, &str)>,
) -> (String, Vec<(u16, u16)>) {
    let cols = cols as usize;
    let extra_w = extra.map_or(0, |(_, e)| display_width(e) + 1);
    let width = |narrow: bool| items.iter().map(|i| display_width(bar_word(i, narrow)) + 2).sum::<usize>() + extra_w;
    let narrow = width(false) + 12 > cols;
    let right = width(narrow);
    let left = match hover.and_then(|h| items.get(h)) {
        Some(item) => tooltip(item),
        None => left.to_string(),
    };
    let left = fit(&left, cols.saturating_sub(right + 2));
    let mut text = format!("\x1b[1;1H\x1b[2K {left}");
    let mut col = 2 + display_width(&left);
    let start = cols.saturating_sub(right) + 1;
    text.push_str(&" ".repeat(start.saturating_sub(col)));
    col = start.max(col);
    let mut ranges = Vec::new();
    for (n, item) in items.iter().enumerate() {
        if let Some((before, e)) = extra {
            if before == n {
                text.push_str(&format!("{e} "));
                col += display_width(e) + 1;
            }
        }
        let word = format!(" {} ", bar_word(item, narrow));
        let w = display_width(&word);
        ranges.push((col as u16, (col + w - 1) as u16));
        if hover == Some(n) {
            text.push_str(&format!("\x1b[7m{word}\x1b[27m"));
        } else {
            text.push_str(&word);
        }
        col += w;
    }
    (text, ranges)
}

/// Row-1 text (with its escape sequences) and the 1-based column range `(start, end)` of each bar item, for
/// hit-testing. The title (or, while hovering, the hovered item's tooltip) sits left; the items sit right.
pub fn render_bar(title: &str, cols: u16, hover: Option<usize>) -> (String, Vec<(u16, u16)>) {
    render_row(&bar_items(), title, cols, hover, None)
}

/// The zoom row `…` opens: `more_items`, with the zoom percentage between zoom out and zoom in.
pub fn render_more(title: &str, zoom: u32, cols: u16, hover: Option<usize>) -> (String, Vec<(u16, u16)>) {
    let pct = format!("{zoom}%");
    render_row(&more_items(), title, cols, hover, Some((1, &pct)))
}

/// The find row: its text, the column range of each `find_items` button, and where the caret goes (`None` while
/// a tooltip fills the field).
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct FindRow {
    pub text: String,
    pub buttons: Vec<(u16, u16)>,
    pub caret: Option<u16>,
}

/// The find row: `⌕`, the query field (underlined; `Find` in dim when empty; the hovered button's tooltip in its
/// place while hovering), the options (inverted when on), the position (`3/22`, `No results`, `Bad regex`), and
/// previous, next and close.
pub fn render_find(q: &FindQuery, count: i64, index: i64, cols: u16, hover: Option<usize>) -> FindRow {
    let items = find_items();
    let status = match count {
        c if c < 0 => "Bad regex".to_string(),
        0 if q.text.is_empty() => String::new(),
        0 => "No results".to_string(),
        c => format!("{}/{c}", index.rem_euclid(c) + 1),
    };
    let on = |action: &str| match action {
        "case" => q.case,
        "word" => q.word,
        "regex" => q.regex,
        _ => false,
    };
    // " ⌕ " + field + " " + options (3 x 4) + " " + status (10) + " " + buttons (3 x 3)
    let cols_n = cols as usize;
    let right_w = 12 + 1 + 10 + 1 + 9;
    let field_w = cols_n.saturating_sub(3 + 1 + right_w).max(1);
    let (field, caret) = match hover.and_then(|h| items.get(h)) {
        Some(item) => (format!("\x1b[2m{}\x1b[22m", pad(&fit(&tooltip(item), field_w), field_w)), None),
        None if q.text.is_empty() => (format!("\x1b[2m{}\x1b[22m", pad(&fit("Find", field_w), field_w)), Some(4)),
        None => {
            let shown = fit_tail(&q.text, field_w.saturating_sub(1));
            let caret = 4 + display_width(&shown) as u16;
            (pad(&shown, field_w), Some(caret))
        }
    };
    let mut text = format!("\x1b[1;1H\x1b[2K \u{2315} \x1b[4m{field}\x1b[24m ");
    let mut col = 3 + field_w + 2;
    let mut buttons = Vec::new();
    for (n, item) in items.iter().enumerate() {
        if n == 3 {
            text.push_str(&format!(" {status:<10} "));
            col += 12;
        }
        let word = format!(" {} ", item.glyph);
        let w = display_width(&word);
        buttons.push((col as u16, (col + w - 1) as u16));
        let lit = on(item.action) || hover == Some(n);
        text.push_str(&if lit { format!("\x1b[7m{word}\x1b[27m") } else { word });
        col += w;
    }
    FindRow { text, buttons, caret }
}

/// `s` padded with spaces to `width` columns.
fn pad(s: &str, width: usize) -> String {
    format!("{s}{}", " ".repeat(width.saturating_sub(display_width(s))))
}

/// The terminal cursor for row 1: a blinking bar at `caret` (the find field), or hidden.
pub fn caret(caret: Option<u16>) -> String {
    match caret {
        Some(col) => format!("\x1b[1;{col}H\x1b[5 q\x1b[?25h"),
        None => "\x1b[?25l".to_string(),
    }
}
