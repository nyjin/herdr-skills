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

/// Inputs in `buf` and the number of bytes consumed; an incomplete sequence at the end is left for the next read.
pub fn parse(_buf: &[u8]) -> (Vec<Input>, usize) {
    (Vec::new(), 0)
}

/// Clicks, moves (for hover) and wheel, reported in pixels.
pub const MOUSE_ON: &str = "\x1b[?1000h\x1b[?1003h\x1b[?1006h\x1b[?1016h";
pub const MOUSE_OFF: &str = "\x1b[?1016l\x1b[?1006l\x1b[?1003l\x1b[?1000l";

/// The pane's cells and pixels from `TIOCGWINSZ`; without pixels, 8 x 18 px cells.
pub fn geometry() -> Geometry {
    Geometry { cols: 80, rows: 24, cell_w: 8, cell_h: 18 }
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

/// Row-1 text (with its escape sequences) and the column range `(start, end)` of each bar item, for hit-testing.
pub fn render_bar(_title: &str, _zoom: u32, _cols: u16, _hover: Option<usize>) -> (String, Vec<(u16, u16)>) {
    (String::new(), Vec::new())
}

/// Row-1 text while finding: the query, the match case / whole word / regex toggles, and the position.
pub fn render_find(_q: &FindQuery, _count: i64, _index: i64, _cols: u16) -> String {
    String::new()
}
