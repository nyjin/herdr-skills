//! The `peek` command: link handler action, herdr actions, the viewer pane, the select-to-open watcher and token
//! registration.
use std::process::ExitCode;

const USAGE: &str = "Usage: peek link | action <name> | viewer [<file>] | watch [--spawn] | select <text> \
                     | auth atlassian <site> | auth github";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let pane = std::env::var("HERDR_PANE_ID").unwrap_or_default();
    // Any run inside herdr makes sure select to open has its watcher, so a fresh `herdr plugin link` needs no restart.
    if matches!(args.first().map(String::as_str), Some("link" | "action" | "viewer")) {
        peek::watcher::ensure_running();
    }
    let result = match args.first().map(String::as_str) {
        Some("link") => peek::link::run_link(&std::env::var("HERDR_PLUGIN_CLICKED_URL").unwrap_or_default(), &pane),
        Some("action") if args.len() == 2 && args[1] == "select-to-open" => peek::link::toggle_select(),
        Some("action") if args.len() == 2 => peek::link::run_action(&args[1], &pane),
        Some("viewer") => viewer(args.get(1).map(std::path::Path::new)),
        Some("watch") if args.get(1).is_some_and(|a| a == "--spawn") => peek::watcher::spawn(),
        Some("watch") if args.len() == 1 => watch(),
        // One selection through select to open, as the watcher would; for tests and by hand.
        Some("select") if args.len() == 2 => peek::link::run_select(&args[1]).map(|opened| {
            if let Some(opened) = opened {
                println!("opened {opened}");
            }
        }),
        Some("auth") => auth(&args[1..]),
        _ => {
            eprintln!("{USAGE}");
            return ExitCode::from(2);
        }
    };
    match result {
        Ok(()) => ExitCode::SUCCESS,
        Err(e) => {
            eprintln!("peek: {e}");
            ExitCode::FAILURE
        }
    }
}

/// The viewer pane for the Claude pane in `PEEK_SOURCE`; with a file, that file is shown directly.
#[cfg(target_os = "macos")]
fn viewer(path: Option<&std::path::Path>) -> std::io::Result<()> {
    peek::mac::viewer::run(&std::env::var("PEEK_SOURCE").unwrap_or_default(), path)
}

#[cfg(not(target_os = "macos"))]
fn viewer(_path: Option<&std::path::Path>) -> std::io::Result<()> {
    Err(std::io::Error::new(std::io::ErrorKind::Unsupported, "the viewer needs macOS"))
}

#[cfg(target_os = "macos")]
fn watch() -> std::io::Result<()> {
    peek::watcher::run(&peek::mac::clipboard::Pasteboard)
}

#[cfg(not(target_os = "macos"))]
fn watch() -> std::io::Result<()> {
    Err(std::io::Error::new(std::io::ErrorKind::Unsupported, "the clipboard watcher needs macOS"))
}

#[cfg(target_os = "macos")]
fn auth(args: &[String]) -> std::io::Result<()> {
    peek::fetch::run_auth(args, &peek::mac::keychain::Keychain)
}

#[cfg(not(target_os = "macos"))]
fn auth(_args: &[String]) -> std::io::Result<()> {
    Err(std::io::Error::new(std::io::ErrorKind::Unsupported, "token storage needs macOS"))
}
