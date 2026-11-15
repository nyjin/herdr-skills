//! Tile and placement arithmetic and the Kitty commands the viewer writes.
use peek::kitty::*;

const RETINA: Geometry = Geometry { cols: 176, rows: 51, cell_w: 17, cell_h: 37 };

#[test]
fn tile_rows_from_budget() {
    // 12 MiB / (176 cells * 17 px * 4 bytes) / 37 px per row
    assert_eq!(tile_rows(&RETINA, TILE_BUDGET), (TILE_BUDGET / (176 * 17 * 4) / 37) as u32);
    assert_eq!(tile_rows(&RETINA, TILE_BUDGET), 28);
}

#[test]
fn tile_rows_at_least_one() {
    let wide = Geometry { cols: 2000, rows: 5, cell_w: 40, cell_h: 90 };
    assert_eq!(tile_rows(&wide, TILE_BUDGET), 1);
    let tiny = Geometry { cols: 1, rows: 1, cell_w: 1, cell_h: 1 };
    assert!(tile_rows(&tiny, 0) >= 1);
}

#[test]
fn layout_single_tile() {
    let l = layout(3, 10, 28, 2, 1);
    assert_eq!(l.len(), 1);
    let (tile, p) = l[0];
    assert_eq!(tile, 0);
    assert_eq!((p.src_row, p.rows, p.row), (3, 10, 2));
    assert_eq!(p.image, image_id(1, 0));
}

#[test]
fn layout_spans_two_tiles() {
    // view rows 20..50 with 28-row tiles: rows 20..28 of tile 0, then 0..22 of tile 1
    let l = layout(20, 30, 28, 2, 1);
    assert_eq!(l.len(), 2);
    assert_eq!((l[0].0, l[0].1.src_row, l[0].1.rows, l[0].1.row), (0, 20, 8, 2));
    assert_eq!((l[1].0, l[1].1.src_row, l[1].1.rows, l[1].1.row), (1, 0, 22, 10));
}

#[test]
fn source_rect_never_past_tile_end() {
    for top in 0..200u64 {
        for (_, p) in layout(top, 49, 7, 2, 3) {
            assert!(p.src_row + p.rows <= 7, "top {top}: {p:?}");
        }
    }
}

#[test]
fn image_ids_change_with_generation() {
    assert_ne!(image_id(1, 0), image_id(2, 0));
    assert_ne!(image_id(1, 0), image_id(1, 1));
    assert_ne!(image_id(0, 0), 0); // Kitty image id 0 means "none"
}

#[test]
fn transmit_shm_command() {
    // the shared memory name travels base64-encoded; S is the byte size
    let c = transmit_shm(7, "/pk1_2", 10, 3);
    assert_eq!(c, "\x1b_Ga=t,i=7,f=32,s=10,v=3,t=s,S=120,q=1;L3BrMV8y\x1b\\");
}

#[test]
fn place_command() {
    let p = Placement { image: 9, src_row: 2, rows: 4, row: 5 };
    assert_eq!(place(&p, 300, 37), "\x1b[5;1H\x1b_Ga=p,i=9,p=1,x=0,y=74,w=300,h=148,C=1,q=2\x1b\\");
}

#[test]
fn delete_commands() {
    assert_eq!(unplace(4), "\x1b_Ga=d,d=i,i=4,q=2\x1b\\");
    assert_eq!(delete_image(4), "\x1b_Ga=d,d=I,i=4,q=2\x1b\\");
    assert_eq!(delete_all(), "\x1b_Ga=d,d=A,q=2\x1b\\");
}
