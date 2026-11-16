//! macOS-only parts: the hidden WebKit renderer, the viewer loop, file change events, Keychain and clipboard
//! (screenshots, and the pasteboard the select-to-open watcher reads).
pub mod clipboard;
pub mod keychain;
pub mod render;
pub mod viewer;
pub mod watch;
