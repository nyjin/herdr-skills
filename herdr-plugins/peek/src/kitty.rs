//! Kitty graphics for the viewer: the document is captured in tiles of whole cell rows, each image at most
//! `TILE_BUDGET` bytes, sent through shared memory; the screen is placements with source rects. (Task 5)

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Geometry {
    pub cols: u16,
    /// All rows of the pane, the top bar included.
    pub rows: u16,
    pub cell_w: u32,
    pub cell_h: u32,
}

/// Above about 12 MiB per image herdr gets much slower (spike: 91 ms at 12 MB, 318 ms at 21.5 MB).
pub const TILE_BUDGET: usize = 12 * 1024 * 1024;

/// Whole cell rows per tile within `budget` bytes of RGBA, at least 1.
pub fn tile_rows(_g: &Geometry, _budget: usize) -> u32 {
    1
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Placement {
    pub image: u32,
    /// Source rect top and height in image pixels; never past the tile's end.
    pub src_y: u32,
    pub src_h: u32,
    /// 1-based terminal row where the placement starts.
    pub row: u16,
}

/// Placements that show `view_rows` rows of the document from `view_top_row`, starting at terminal row
/// `first_screen_row`, with `(tile index, placement)` per visible tile.
pub fn layout(_view_top_row: u64, _view_rows: u32, _tile_rows: u32, _first_screen_row: u16, _generation: u32) -> Vec<(u64, Placement)> {
    Vec::new()
}

/// Image id for a tile of a document load (`generation`), so a new load never reuses an old image.
pub fn image_id(_generation: u32, _tile: u64) -> u32 {
    0
}

pub fn transmit_shm(_image: u32, _shm_name: &str, _w: u32, _h: u32) -> String {
    String::new()
}

pub fn place(_p: &Placement, _width_px: u32) -> String {
    String::new()
}

/// Remove an image's placements, keep its data.
pub fn unplace(_image: u32) -> String {
    String::new()
}

/// Free an image's data.
pub fn delete_image(_image: u32) -> String {
    String::new()
}

pub fn delete_all() -> String {
    String::new()
}
