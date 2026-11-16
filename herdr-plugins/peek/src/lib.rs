//! peek: show a file or link clicked or selected in a herdr pane, rendered by a hidden WebKit view, in the herdr
//! pane beside it. Design: docs/superpowers/specs/2026-11-15-peek-webkit-viewer-design.md.
//!
//! Platform-neutral modules build and test anywhere; `mac` holds the parts that need macOS (WebKit, FSEvents,
//! Keychain, clipboard).
pub mod fetch;
pub mod herdr;
pub mod kitty;
pub mod link;
pub mod page;
pub mod resolve;
pub mod script;
pub mod select;
pub mod state;
pub mod target;
pub mod term;
pub mod watcher;

#[cfg(target_os = "macos")]
pub mod mac;
