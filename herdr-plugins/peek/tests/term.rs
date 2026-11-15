//! Input parsing, pane geometry and the top bar.
use peek::term::*;

#[test]
fn parses_keys_and_arrows() {
    let (inputs, used) = parse(b"jk \x1b[A\x1b[B\x1b[5~\x1b[6~\x7f\r\x1bc");
    assert_eq!(used, 21);
    assert_eq!(
        inputs,
        vec![
            Input::Key(Key::Char('j')),
            Input::Key(Key::Char('k')),
            Input::Key(Key::Char(' ')),
            Input::Key(Key::Up),
            Input::Key(Key::Down),
            Input::Key(Key::PageUp),
            Input::Key(Key::PageDown),
            Input::Key(Key::Backspace),
            Input::Key(Key::Enter),
            Input::Key(Key::Alt('c')),
        ]
    );
}

#[test]
fn parses_utf8_text() {
    // a Korean syllable typed into the find field arrives as three UTF-8 bytes
    let (inputs, used) = parse("\u{d55c}".as_bytes());
    assert_eq!((inputs, used), (vec![Input::Key(Key::Char('\u{d55c}'))], 3));
}

#[test]
fn parses_sgr_pixel_mouse() {
    let (inputs, _) = parse(b"\x1b[<0;534;689M\x1b[<0;534;689m\x1b[<35;1165;1447M\x1b[<64;44;498M\x1b[<65;44;498M");
    let kinds: Vec<_> = inputs
        .iter()
        .map(|i| match i {
            Input::Mouse(m) => (m.kind, m.x_px, m.y_px),
            other => panic!("{other:?}"),
        })
        .collect();
    assert_eq!(
        kinds,
        vec![
            (MouseKind::Press, 534, 689),
            (MouseKind::Release, 534, 689),
            (MouseKind::Move, 1165, 1447),
            (MouseKind::WheelUp, 44, 498),
            (MouseKind::WheelDown, 44, 498),
        ]
    );
}

#[test]
fn keeps_partial_sequence() {
    let (inputs, used) = parse(b"j\x1b[<0;53");
    assert_eq!((inputs, used), (vec![Input::Key(Key::Char('j'))], 1));
    // a lone escape at the end may be the start of a sequence: left for the next read
    let (inputs, used) = parse(b"k\x1b");
    assert_eq!((inputs, used), (vec![Input::Key(Key::Char('k'))], 1));
}

#[test]
fn parses_kitty_reply() {
    let (inputs, used) = parse(b"\x1b_Gi=1;ENOMEM: out of memory\x1b\\j");
    assert_eq!(used, 31);
    assert_eq!(inputs, vec![Input::Reply("i=1;ENOMEM: out of memory".into()), Input::Key(Key::Char('j'))]);
}

#[test]
fn geometry_without_pixels_falls_back() {
    // under cargo test stdout is not a terminal: no size at all
    let g = geometry();
    assert_eq!((g.cell_w, g.cell_h), (8, 18));
    assert!(g.cols > 0 && g.rows > 0);
}

#[test]
fn bar_layout_and_hover() {
    let (text, ranges) = render_bar("plan.md", 110, 120, None);
    assert_eq!(ranges.len(), bar_items().len());
    for w in ranges.windows(2) {
        assert!(w[0].1 < w[1].0, "{ranges:?}");
    }
    assert!(ranges.last().unwrap().1 <= 120);
    assert!(text.contains("plan.md") && text.contains("110%"));
    // hovering an item shows its tooltip (name and key) and marks the item
    let (hover, _) = render_bar("plan.md", 100, 120, Some(0));
    assert!(hover.contains("Reload (r)") && hover.contains("\x1b[7m"));
}

#[test]
fn bar_fits_a_narrow_pane() {
    let (_, ranges) = render_bar("a-very-long-document-name-that-does-not-fit.md", 100, 40, None);
    assert!(ranges.last().unwrap().1 <= 40, "{ranges:?}");
}

#[test]
fn tooltips_name_the_key() {
    let tips: Vec<String> = bar_items().iter().map(tooltip).collect();
    assert!(tips.contains(&"Open in browser (o)".to_string()));
    assert!(tips.contains(&"Zoom in (+)".to_string()));
}
