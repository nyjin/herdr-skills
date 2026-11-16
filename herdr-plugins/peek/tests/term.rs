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
fn parses_shift_enter() {
    let (inputs, _) = parse(b"\x1b[13;2u\x1b[27;2;13~");
    assert_eq!(inputs, vec![Input::Key(Key::ShiftEnter), Input::Key(Key::ShiftEnter)]);
}

#[test]
fn bar_layout_and_hover() {
    let (text, ranges) = render_bar("plan.md", 120, None);
    assert_eq!(ranges.len(), bar_items().len());
    for w in ranges.windows(2) {
        assert!(w[0].1 < w[1].0, "{ranges:?}");
    }
    assert!(ranges.last().unwrap().1 <= 120);
    for glyph in ["plan.md", "\u{27f3}", "\u{2315}", "\u{2197}", "\u{2026}", "Source", "Shot"] {
        assert!(text.contains(glyph), "{glyph} missing from {text:?}");
    }
    // zoom moved behind `…`
    assert!(!text.contains('%'));
    // hovering an item shows its tooltip (name and key) and marks the item
    let (hover, _) = render_bar("plan.md", 120, Some(0));
    assert!(hover.contains("Reload (r)") && hover.contains("\x1b[7m"));
}

#[test]
fn a_symbol_takes_one_column() {
    let (_, ranges) = render_bar("plan.md", 120, None);
    // " ⟳ " is three columns although "⟳" is three bytes
    assert_eq!(ranges[0].1 - ranges[0].0 + 1, 3);
}

#[test]
fn bar_fits_a_narrow_pane() {
    let (_, ranges) = render_bar("a-very-long-document-name-that-does-not-fit.md", 30, None);
    assert!(ranges.last().unwrap().1 <= 30, "{ranges:?}");
}

#[test]
fn tooltips_name_the_key() {
    let tips: Vec<String> = bar_items().iter().chain(&more_items()).chain(&find_items()).map(tooltip).collect();
    for tip in ["Open in browser (o)", "More: zoom", "Zoom in (+)", "Zoom out (-)", "Next match (Enter)", "Close (Esc)"] {
        assert!(tips.contains(&tip.to_string()), "{tip} missing from {tips:?}");
    }
}

#[test]
fn more_row_puts_the_zoom_between_its_buttons() {
    let (text, ranges) = render_more("plan.md", 110, 120, None);
    assert_eq!(ranges.len(), more_items().len());
    let at = |col: u16| {
        // column of "110%" on the row, counted the way the row is laid out
        let plain: String = text.replace("\x1b[1;1H\x1b[2K", "");
        plain.chars().skip(col as usize - 1).take(4).collect::<String>()
    };
    assert_eq!(at(ranges[0].1 + 1), "110%");
    assert!(ranges[0].1 + 5 < ranges[1].0 + 1, "{ranges:?}");
    assert!(ranges.last().unwrap().1 <= 120);
}

#[test]
fn find_row_shows_the_query_options_position_and_caret() {
    use peek::script::FindQuery;
    let q = FindQuery { text: "agent".into(), case: true, word: false, regex: true };
    let row = render_find(&q, 22, 2, 100, None);
    assert!(row.text.contains("agent") && row.text.contains("3/22"));
    // an option that is on is drawn inverted; one that is off is not
    assert!(row.text.contains("\x1b[7m Aa \x1b[27m") && row.text.contains("\x1b[7m .* \x1b[27m"));
    assert!(!row.text.contains("\x1b[7m ab \x1b[27m"));
    for glyph in ["\u{2315}", "\u{2191}", "\u{2193}", "\u{2715}"] {
        assert!(row.text.contains(glyph), "{glyph}");
    }
    assert_eq!(row.buttons.len(), find_items().len());
    for w in row.buttons.windows(2) {
        assert!(w[0].1 < w[1].0, "{:?}", row.buttons);
    }
    assert_eq!(row.buttons.last().unwrap().1, 100);
    // the caret stands right after the query: " ⌕ " is three columns, so "agent" ends at column 8
    assert_eq!(row.caret, Some(9));
    assert!(render_find(&q, 0, 0, 100, None).text.contains("No results"));
    assert!(render_find(&q, -1, 0, 100, None).text.contains("Bad regex"));
}

#[test]
fn an_empty_find_field_says_find_and_takes_the_caret() {
    let row = render_find(&peek::script::FindQuery::default(), 0, 0, 80, None);
    assert!(row.text.contains("\x1b[2mFind"));
    assert_eq!(row.caret, Some(4));
}

#[test]
fn hovering_a_find_button_shows_its_tooltip_in_the_field() {
    let q = peek::script::FindQuery { text: "agent".into(), ..Default::default() };
    let next = find_items().iter().position(|i| i.action == "next").unwrap();
    let row = render_find(&q, 3, 0, 100, Some(next));
    assert!(row.text.contains("Next match (Enter)"));
    assert_eq!(row.caret, None);
}

#[test]
fn a_long_query_shows_its_end() {
    let q = peek::script::FindQuery { text: format!("{}tail", "x".repeat(200)), ..Default::default() };
    let row = render_find(&q, 1, 0, 80, None);
    assert!(row.text.contains("\u{2026}") && row.text.contains("tail"));
    let caret = row.caret.unwrap();
    assert!(caret < row.buttons[0].0, "caret {caret} past the field: {:?}", row.buttons);
}

#[test]
fn caret_shows_or_hides_the_cursor() {
    assert_eq!(caret(Some(9)), "\x1b[1;9H\x1b[5 q\x1b[?25h");
    assert_eq!(caret(None), "\x1b[?25l");
}
