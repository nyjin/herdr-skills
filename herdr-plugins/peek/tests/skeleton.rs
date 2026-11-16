//! The fixed interfaces hold together: every herdr action is reachable, and the binary explains its usage.
use std::process::Command;

#[test]
fn every_action_has_a_bar_item_or_key() {
    let rows = peek::term::bar_items(false).into_iter().chain(peek::term::bar_items(true)).chain(peek::term::more_items());
    let clickable: Vec<&str> = rows.map(|b| b.action).collect();
    for action in peek::link::ACTIONS {
        // back (`h`, Backspace) is a key only
        assert!(clickable.contains(&action) || action == "back", "{action} unreachable");
    }
}

#[test]
fn binary_prints_usage() {
    let out = Command::new(env!("CARGO_BIN_EXE_peek")).output().unwrap();
    assert_eq!(out.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&out.stderr).contains("Usage: peek"));
}
