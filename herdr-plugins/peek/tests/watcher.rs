//! The select-to-open watcher process: one per herdr server, gone with the server. macOS only (it reads the
//! pasteboard).
#![cfg(target_os = "macos")]
use std::fs;
use std::os::unix::net::UnixListener;
use std::path::Path;
use std::process::{Child, Command};
use std::thread;
use std::time::{Duration, Instant};

const PEEK: &str = env!("CARGO_BIN_EXE_peek");

fn watch(state: &Path, socket: &Path) -> Child {
    let mut cmd = Command::new(PEEK);
    for key in ["HERDR_PANE_ID", "HERDR_BIN_PATH", "PEEK_HERDR"] {
        cmd.env_remove(key);
    }
    cmd.arg("watch")
        .env("PEEK_STATE_DIR", state)
        .env("HERDR_SOCKET_PATH", socket)
        .env("PEEK_WATCH_CHECK_MS", "200")
        .spawn()
        .unwrap()
}

fn exits_within(child: &mut Child, limit: Duration) -> bool {
    let start = Instant::now();
    while start.elapsed() < limit {
        if child.try_wait().unwrap().is_some() {
            return true;
        }
        thread::sleep(Duration::from_millis(50));
    }
    false
}

#[test]
fn one_watcher_per_server_and_it_leaves_with_the_server() {
    let tmp = tempfile::tempdir().unwrap();
    let state = tmp.path().join("state");
    fs::create_dir_all(&state).unwrap();
    // Off: the watcher must not read the clipboard of whoever runs the tests.
    fs::write(state.join("select"), "off").unwrap();
    let socket = tmp.path().join("s.sock");
    let server = UnixListener::bind(&socket).unwrap();

    let mut first = watch(&state, &socket);
    thread::sleep(Duration::from_millis(600));
    assert!(first.try_wait().unwrap().is_none(), "the first watcher should keep running");

    let mut second = watch(&state, &socket);
    assert!(exits_within(&mut second, Duration::from_secs(3)), "a second watcher for the same server should leave");

    drop(server);
    fs::remove_file(&socket).unwrap();
    let left = exits_within(&mut first, Duration::from_secs(5));
    if !left {
        let _ = first.kill();
    }
    assert!(left, "the watcher should leave once the server's socket stops answering");
    let log = fs::read_to_string(state.join("watch.log")).unwrap();
    assert!(log.contains("started") && log.contains("herdr server gone"), "{log}");
}
