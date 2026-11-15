//! The `peek` command: link handler action, herdr actions, the viewer pane and token registration.
use std::process::ExitCode;

const USAGE: &str = "Usage: peek link | action <name> | viewer | auth atlassian <site> | auth github";

fn main() -> ExitCode {
    let args: Vec<String> = std::env::args().skip(1).collect();
    let pane = std::env::var("HERDR_PANE_ID").unwrap_or_default();
    let result = match args.first().map(String::as_str) {
        Some("link") => peek::link::run_link(&std::env::var("HERDR_PLUGIN_CLICKED_URL").unwrap_or_default(), &pane),
        Some("action") if args.len() == 2 => peek::link::run_action(&args[1], &pane),
        Some("viewer") => viewer(),
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

#[cfg(target_os = "macos")]
fn viewer() -> std::io::Result<()> {
    peek::mac::viewer::run(&std::env::var("PEEK_SOURCE").unwrap_or_default())
}

#[cfg(not(target_os = "macos"))]
fn viewer() -> std::io::Result<()> {
    Err(std::io::Error::new(std::io::ErrorKind::Unsupported, "the viewer needs macOS"))
}

#[cfg(target_os = "macos")]
fn auth(args: &[String]) -> std::io::Result<()> {
    peek::fetch::run_auth(args, &peek::mac::keychain::Keychain)
}

#[cfg(not(target_os = "macos"))]
fn auth(_args: &[String]) -> std::io::Result<()> {
    Err(std::io::Error::new(std::io::ErrorKind::Unsupported, "token storage needs macOS"))
}
