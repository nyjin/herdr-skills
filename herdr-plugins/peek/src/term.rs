//! Terminal side of the viewer: input parsing (keys, SGR pixel mouse, Kitty replies), pane geometry, the top bar
//! and the find row. (Tasks 5 and 6)
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

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct BarItem {
    pub label: &'static str,
    pub key: &'static str,
    /// One of `link::ACTIONS`.
    pub action: &'static str,
}

/// The top bar's commands, left to right.
pub fn bar_items() -> Vec<BarItem> {
    vec![
        BarItem { label: "Reload", key: "r", action: "reload" },
        BarItem { label: "Source", key: "t", action: "toggle" },
        BarItem { label: "Find", key: "/", action: "find" },
        BarItem { label: "Zoom out", key: "-", action: "zoom-out" },
        BarItem { label: "Zoom in", key: "+", action: "zoom-in" },
        BarItem { label: "Screenshot", key: "s", action: "screenshot" },
        BarItem { label: "Open in browser", key: "o", action: "browser" },
    ]
}

/// "Reload (r)": an item's name and key, shown while the pointer is over it.
pub fn tooltip(item: &BarItem) -> String {
    format!("{} ({})", item.label, item.key)
}

/// What an item shows on the bar: its word when there is room, its key when the pane is narrow.
fn bar_word(item: &BarItem, narrow: bool) -> &'static str {
    if narrow {
        return item.key;
    }
    match item.action {
        "reload" => "Reload",
        "toggle" => "Source",
        "find" => "Find",
        "zoom-out" => "-",
        "zoom-in" => "+",
        "screenshot" => "Shot",
        "browser" => "Browser",
        _ => item.key,
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

/// `s` cut to at most `width` columns, with an ellipsis when cut.
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

/// Row-1 text (with its escape sequences) and the 1-based column range `(start, end)` of each bar item, for
/// hit-testing. The title (or, while hovering, the hovered item's tooltip) sits left; the items sit right, with the
/// zoom percentage between zoom out and zoom in.
pub fn render_bar(title: &str, zoom: u32, cols: u16, hover: Option<usize>) -> (String, Vec<(u16, u16)>) {
    let items = bar_items();
    let cols = cols as usize;
    let pct = format!("{zoom}%");
    let width = |narrow: bool| items.iter().map(|i| bar_word(i, narrow).len() + 2).sum::<usize>() + pct.len() + 1;
    let narrow = width(false) + 12 > cols;
    let right = width(narrow);
    let left_room = cols.saturating_sub(right + 1);
    let left = match hover.and_then(|h| items.get(h)) {
        Some(item) => tooltip(item),
        None => title.to_string(),
    };
    let left = fit(&left, left_room);
    let mut text = format!("\x1b[1;1H\x1b[2K {left}");
    let mut col = 2 + display_width(&left);
    let start = cols.saturating_sub(right) + 1;
    text.push_str(&" ".repeat(start.saturating_sub(col)));
    col = start.max(col);
    let mut ranges = Vec::new();
    for (n, item) in items.iter().enumerate() {
        if item.action == "zoom-in" {
            text.push_str(&format!("{pct} "));
            col += pct.len() + 1;
        }
        let word = format!(" {} ", bar_word(item, narrow));
        ranges.push((col as u16, (col + word.len() - 1) as u16));
        if hover == Some(n) {
            text.push_str(&format!("\x1b[7m{word}\x1b[27m"));
        } else {
            text.push_str(&word);
        }
        col += word.len();
    }
    (text, ranges)
}

/// Row-1 text while finding: the query, the match case / whole word / regex toggles, and the position.
pub fn render_find(_q: &FindQuery, _count: i64, _index: i64, _cols: u16) -> String {
    String::new()
}
