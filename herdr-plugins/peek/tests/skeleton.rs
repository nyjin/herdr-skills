//! The fixed interfaces hold together: every herdr action is reachable, and the binary explains its usage.
use std::process::Command;

#[test]
fn every_action_has_a_bar_item_or_key() {
    let bar: Vec<&str> = peek::term::bar_items().iter().map(|b| b.action).collect();
    for action in peek::link::ACTIONS {
        // zoom-reset (`0`) and back (`h`, Backspace) are keys only
        assert!(bar.contains(&action) || ["zoom-reset", "back"].contains(&action), "{action} unreachable");
    }
}

#[test]
fn binary_prints_usage() {
    let out = Command::new(env!("CARGO_BIN_EXE_peek")).output().unwrap();
    assert_eq!(out.status.code(), Some(2));
    assert!(String::from_utf8_lossy(&out.stderr).contains("Usage: peek"));
}
