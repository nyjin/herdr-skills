//! Calls to the herdr CLI: `$PEEK_HERDR` (may hold arguments, split on whitespace), `$HERDR_BIN_PATH` or `herdr`.
use serde_json::Value;
use std::io;
use std::path::PathBuf;
use std::process::{Command, Output, Stdio};
use std::sync::mpsc;
use std::thread;
use std::time::Duration;

const PLUGIN_ID: &str = "nyjin.peek";
/// A click must not hang on a herdr (or git) that does not answer.
const TIMEOUT: Duration = Duration::from_secs(10);

#[derive(Clone, Debug, PartialEq)]
pub struct PaneInfo {
    pub pane_id: String,
    pub cwd: PathBuf,
    pub foreground_cwd: Option<PathBuf>,
    /// `agent_session.value` when a Claude session runs in the pane.
    pub session_id: Option<String>,
}

pub fn pane_get(pane: &str) -> io::Result<PaneInfo> {
    let result = call(&["pane", "get", pane])?;
    let p = &result["pane"];
    if !p.is_object() {
        return Err(bad_reply("pane get", &result));
    }
    let text = |v: &Value| v.as_str().filter(|s| !s.is_empty()).map(String::from);
    Ok(PaneInfo {
        pane_id: text(&p["pane_id"]).unwrap_or_else(|| pane.to_string()),
        cwd: text(&p["cwd"]).map(PathBuf::from).unwrap_or_default(),
        foreground_cwd: text(&p["foreground_cwd"]).map(PathBuf::from),
        session_id: text(&p["agent_session"]["value"]),
    })
}

/// A pane in `herdr pane list`.
#[derive(Clone, Debug, PartialEq)]
pub struct PaneEntry {
    pub pane_id: String,
    pub tab_id: String,
    pub focused: bool,
}

pub fn panes() -> io::Result<Vec<PaneEntry>> {
    let result = call(&["pane", "list"])?;
    let panes = result["panes"].as_array().ok_or_else(|| bad_reply("pane list", &result))?;
    Ok(panes
        .iter()
        .filter_map(|p| {
            Some(PaneEntry {
                pane_id: p["pane_id"].as_str()?.to_string(),
                tab_id: p["tab_id"].as_str().unwrap_or_default().to_string(),
                focused: p["focused"].as_bool().unwrap_or(false),
            })
        })
        .collect())
}

/// The rows the pane shows now (`herdr pane read --source visible`), as text.
pub fn pane_text(pane: &str) -> io::Result<String> {
    let args = ["pane", "read", pane, "--source", "visible", "--lines", "500"];
    let out = output_within(&mut command(&args), TIMEOUT)?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        return Err(io::Error::other(format!("herdr pane read failed: {}", err.trim())));
    }
    Ok(String::from_utf8_lossy(&out.stdout).into_owned())
}

pub fn pane_ids() -> io::Result<Vec<String>> {
    let result = call(&["pane", "list"])?;
    let panes = result["panes"].as_array().ok_or_else(|| bad_reply("pane list", &result))?;
    Ok(panes.iter().filter_map(|p| p["pane_id"].as_str().map(String::from)).collect())
}

/// Opens the viewer pane to the right of `source` without taking focus; returns its pane id.
pub fn open_viewer(source: &str) -> io::Result<String> {
    let env = format!("PEEK_SOURCE={source}");
    let args = [
        "plugin", "pane", "open", "--plugin", PLUGIN_ID, "--entrypoint", "viewer", "--placement", "split",
        "--target-pane", source, "--direction", "right", "--no-focus", "--env", &env,
    ];
    let result = call(&args)?;
    result["plugin_pane"]["pane"]["pane_id"]
        .as_str()
        .map(String::from)
        .ok_or_else(|| bad_reply("plugin pane open", &result))
}

/// A herdr notification; failures are ignored.
pub fn notify(body: &str) {
    let _ = output_within(&mut command(&["notification", "show", "peek", "--body", body]), TIMEOUT);
}

fn command(args: &[&str]) -> Command {
    let words: Vec<String> = match std::env::var("PEEK_HERDR") {
        Ok(v) if !v.trim().is_empty() => v.split_whitespace().map(String::from).collect(),
        _ => vec![std::env::var("HERDR_BIN_PATH").ok().filter(|p| !p.is_empty()).unwrap_or_else(|| "herdr".into())],
    };
    let mut cmd = Command::new(&words[0]);
    cmd.args(&words[1..]).args(args);
    cmd
}

/// Runs herdr and returns the `result` of its JSON reply.
fn call(args: &[&str]) -> io::Result<Value> {
    let out = output_within(&mut command(args), TIMEOUT)?;
    if !out.status.success() {
        let err = String::from_utf8_lossy(&out.stderr);
        return Err(io::Error::other(format!("herdr {} failed: {}", args[..2].join(" "), err.trim())));
    }
    let reply: Value = serde_json::from_slice(&out.stdout)
        .map_err(|e| io::Error::new(io::ErrorKind::InvalidData, format!("herdr {}: {e}", args[..2].join(" "))))?;
    Ok(reply["result"].clone())
}

fn bad_reply(what: &str, result: &Value) -> io::Error {
    io::Error::new(io::ErrorKind::InvalidData, format!("herdr {what}: unexpected reply {result}"))
}

/// `cmd.output()` that gives up (and kills the process) after `timeout`. Used for herdr and git.
pub(crate) fn output_within(cmd: &mut Command, timeout: Duration) -> io::Result<Output> {
    let child = cmd.stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped()).spawn()?;
    let pid = child.id() as libc::pid_t;
    let (tx, rx) = mpsc::channel();
    thread::spawn(move || {
        let _ = tx.send(child.wait_with_output());
    });
    match rx.recv_timeout(timeout) {
        Ok(out) => out,
        Err(_) => {
            // SAFETY: kill(2) takes no pointers. Should the child have exited at this very moment, its pid is not
            // reused that fast.
            unsafe { libc::kill(pid, libc::SIGKILL) };
            Err(io::Error::new(io::ErrorKind::TimedOut, format!("{:?} did not finish in {timeout:?}", cmd.get_program())))
        }
    }
}
