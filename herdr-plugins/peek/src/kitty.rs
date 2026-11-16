//! Kitty graphics for the viewer. The document is measured in terminal rows (device pixels / cell height) and
//! captured in tiles of whole rows, each image at most `TILE_BUDGET` bytes of RGBA, sent through POSIX shared
//! memory. The screen is one placement per visible tile, with a source rect inside that tile: a rect past an
//! image's end would stretch the picture. Whole rows everywhere mean placements need no pixel offsets.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Geometry {
    pub cols: u16,
    /// All rows of the pane, the top bar included.
    pub rows: u16,
    pub cell_w: u32,
    pub cell_h: u32,
}

/// Above about 12 MiB per image herdr gets much slower (spike: 91 ms at 12 MB, 318 ms at 21.5 MB; 67 MB refused).
pub const TILE_BUDGET: usize = 12 * 1024 * 1024;

/// Whole cell rows per tile within `budget` bytes of RGBA, at least 1.
pub fn tile_rows(g: &Geometry, budget: usize) -> u32 {
    let row_bytes = (g.cols as usize * g.cell_w as usize * 4).max(1) * (g.cell_h as usize).max(1);
    ((budget / row_bytes) as u32).max(1)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Placement {
    pub image: u32,
    /// First row of the tile shown, and how many rows; `src_row + rows` never exceeds the tile's rows.
    pub src_row: u32,
    pub rows: u32,
    /// 1-based terminal row where the placement starts.
    pub row: u16,
}

/// Placements that show `view_rows` rows of the document from `view_top_row`, starting at terminal row
/// `first_screen_row`: `(tile index, placement)` per visible tile, top to bottom.
pub fn layout(view_top_row: u64, view_rows: u32, tile_rows: u32, first_screen_row: u16, generation: u32) -> Vec<(u64, Placement)> {
    let tile_rows = tile_rows.max(1) as u64;
    let mut out = Vec::new();
    let (mut doc_row, mut screen_row, end) = (view_top_row, first_screen_row as u64, view_top_row + view_rows as u64);
    while doc_row < end {
        let tile = doc_row / tile_rows;
        let src_row = doc_row % tile_rows;
        let rows = (tile_rows - src_row).min(end - doc_row);
        out.push((tile, Placement { image: image_id(generation, tile), src_row: src_row as u32, rows: rows as u32, row: screen_row as u16 }));
        doc_row += rows;
        screen_row += rows;
    }
    out
}

/// Image id for a tile of one document layout (`generation`), so a new layout never shows an old image. Never 0.
pub fn image_id(generation: u32, tile: u64) -> u32 {
    (((generation % 65_535) + 1) << 15) | (tile % 32_768) as u32
}

/// Transmit an RGBA image held in shared memory `shm_name` (the terminal reads and unlinks it). Errors are
/// reported (`q=1`): an image too large comes back as `ENOMEM`.
pub fn transmit_shm(image: u32, shm_name: &str, w: u32, h: u32) -> String {
    format!("\x1b_Ga=t,i={image},f=32,s={w},v={h},t=s,S={},q=1;{}\x1b\\", w as u64 * h as u64 * 4, base64(shm_name.as_bytes()))
}

/// Show `p` at its row, full width, without moving the cursor. Placing the same image again moves it.
pub fn place(p: &Placement, width_px: u32, cell_h: u32) -> String {
    format!(
        "\x1b[{};1H\x1b_Ga=p,i={},p=1,x=0,y={},w={width_px},h={},C=1,q=2\x1b\\",
        p.row,
        p.image,
        p.src_row * cell_h,
        p.rows * cell_h
    )
}

/// Remove an image's placements, keep its data.
pub fn unplace(image: u32) -> String {
    format!("\x1b_Ga=d,d=i,i={image},q=2\x1b\\")
}

/// Free an image's data.
pub fn delete_image(image: u32) -> String {
    format!("\x1b_Ga=d,d=I,i={image},q=2\x1b\\")
}

pub fn delete_all() -> String {
    "\x1b_Ga=d,d=A,q=2\x1b\\".to_string()
}

fn base64(data: &[u8]) -> String {
    const T: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut s = String::with_capacity(data.len().div_ceil(3) * 4);
    for c in data.chunks(3) {
        let n = (c[0] as u32) << 16 | (*c.get(1).unwrap_or(&0) as u32) << 8 | *c.get(2).unwrap_or(&0) as u32;
        for i in 0..4 {
            s.push(if i <= c.len() { T[(n >> (18 - 6 * i) & 63) as usize] as char } else { '=' });
        }
    }
    s
}
