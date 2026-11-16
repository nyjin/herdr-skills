//! `peek link` and `peek action` against a fake herdr (tests/fixtures/fake_herdr.sh, through PEEK_HERDR), plus the
//! state folder and the private /tmp layout. The Python cases of tests/test_peek.py, ported.
//!
//! The commands run as child processes with their own environment: herdr's variables of the session running the
//! tests (HERDR_PANE_ID, HERDR_BIN_PATH) must never reach them, and environment variables are shared by every
//! test thread of this process.
use peek::state::{Item, Mode, ViewState};
use std::fs;
use std::os::unix::fs::PermissionsExt;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::Mutex;

const SRC: &str = "w1:p1";
const PEEK: &str = env!("CARGO_BIN_EXE_peek");

struct Fixture {
    _tmp: tempfile::TempDir,
    root: PathBuf,
    state: PathBuf,
    log: PathBuf,
    repo: PathBuf,
    doc: PathBuf,
    env: Vec<(String, String)>,
}

fn fixture() -> Fixture {
    let tmp = tempfile::tempdir().unwrap();
    let root = fs::canonicalize(tmp.path()).unwrap();
    let repo = root.join("repo");
    fs::create_dir_all(repo.join("docs")).unwrap();
    let doc = repo.join("docs/a.md");
    fs::write(&doc, "").unwrap();
    // A copy beside the test data: PEEK_HERDR is split on whitespace, and the checkout's path may hold spaces.
    let fake = root.join("fake_herdr.sh");
    fs::copy(Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/fake_herdr.sh"), &fake).unwrap();
    let (state, log) = (root.join("state"), root.join("calls.log"));
    let env = vec![
        ("PEEK_HERDR".into(), format!("sh {}", fake.display())),
        ("PEEK_OPEN".into(), format!("sh {}", fake.display())),
        ("FAKE_LOG".into(), log.display().to_string()),
        ("PEEK_STATE_DIR".into(), state.display().to_string()),
        ("HOME".into(), root.join("home").display().to_string()),
        ("HERDR_PANE_ID".into(), SRC.into()),
        ("FAKE_PANE_IDS".into(), String::new()),
        ("FAKE_PANE".into(), serde_json::json!({"pane_id": SRC, "foreground_cwd": repo}).to_string()),
    ];
    Fixture { _tmp: tmp, root, state, log, repo, doc, env }
}

impl Fixture {
    fn set(&mut self, key: &str, value: &str) {
        self.env.retain(|(k, _)| k != key);
        self.env.push((key.into(), value.into()));
    }

    fn unset(&mut self, key: &str) {
        self.env.retain(|(k, _)| k != key);
    }

    fn command(&self, args: &[&str]) -> Command {
        let mut cmd = Command::new(PEEK);
        cmd.args(args);
        // HERDR_SOCKET_PATH too: with it, a peek run would start a clipboard watcher for the herdr running the tests.
        for key in ["HERDR_PANE_ID", "HERDR_BIN_PATH", "HERDR_SOCKET_PATH", "HERDR_PLUGIN_CLICKED_URL", "PEEK_HERDR", "PEEK_OPEN"] {
            cmd.env_remove(key);
        }
        cmd.envs(self.env.iter().map(|(k, v)| (k.as_str(), v.as_str())));
        cmd
    }

    fn peek(&self, args: &[&str]) -> Output {
        self.command(args).output().unwrap()
    }

    fn click(&self, text: &str) -> Output {
        self.command(&["link"]).env("HERDR_PLUGIN_CLICKED_URL", text).output().unwrap()
    }

    fn calls(&self) -> Vec<Vec<String>> {
        let Ok(text) = fs::read_to_string(&self.log) else { return Vec::new() };
        text.lines()
            .map(|line| line.split('\u{1f}').filter(|a| !a.is_empty()).map(String::from).collect())
            .collect()
    }

    fn called(&self, prefix: &[&str]) -> Vec<Vec<String>> {
        self.calls().into_iter().filter(|c| c.len() >= prefix.len() && c[..prefix.len()] == *prefix).collect()
    }

    fn opens(&self) -> Vec<Vec<String>> {
        self.called(&["plugin", "pane", "open"])
    }

    fn state_file(&self, ext: &str) -> PathBuf {
        self.state.join(format!("{SRC}{ext}"))
    }

    fn view(&self) -> Option<ViewState> {
        let bytes = fs::read(self.state_file(".json")).ok()?;
        Some(serde_json::from_slice(&bytes).unwrap())
    }

    fn shown(&self) -> Option<Vec<String>> {
        let st = self.view()?;
        Some(st.items.iter().map(|i| i.url.clone().unwrap_or_else(|| i.path.clone().unwrap().display().to_string())).collect())
    }

    fn write_viewer(&self, pane: &str) {
        fs::create_dir_all(&self.state).unwrap();
        fs::write(self.state_file(".viewer"), pane).unwrap();
    }
}

fn path_item(path: &Path, line: Option<u32>) -> Item {
    Item { label: path.display().to_string(), path: Some(path.to_path_buf()), url: None, line }
}

#[test]
fn click_opens_viewer() {
    let f = fixture();
    let out = f.click(f.doc.to_str().unwrap());
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    assert_eq!(f.view().unwrap().items, vec![path_item(&f.doc, None)]);
    let opens = f.opens();
    assert_eq!(opens.len(), 1);
    let call = &opens[0];
    let value = |flag: &str| call[call.iter().position(|a| a == flag).unwrap() + 1].clone();
    assert_eq!(value("--plugin"), "nyjin.peek");
    assert_eq!(value("--entrypoint"), "viewer");
    assert_eq!(value("--placement"), "split");
    assert_eq!(value("--target-pane"), SRC);
    assert_eq!(value("--direction"), "right");
    assert_eq!(value("--env"), format!("PEEK_SOURCE={SRC}"));
    assert!(call.contains(&"--no-focus".to_string()));
    let viewer = fs::read_to_string(f.state_file(".viewer")).unwrap();
    assert!(viewer.starts_with("w1:v"), "{viewer}");
}

#[test]
fn click_outside_herdr_does_nothing() {
    let mut f = fixture();
    f.unset("HERDR_PANE_ID");
    f.click(f.doc.to_str().unwrap());
    assert!(f.calls().is_empty());
    assert!(f.view().is_none());
}

#[test]
fn reuses_live_viewer() {
    let mut f = fixture();
    f.write_viewer("w1:p9");
    f.set("FAKE_PANE_IDS", "w1:p1 w1:p9");
    f.click(f.doc.to_str().unwrap());
    assert!(f.opens().is_empty());
    assert_eq!(f.shown().unwrap(), vec![f.doc.display().to_string()]);
}

#[test]
fn reopens_when_viewer_gone() {
    let mut f = fixture();
    f.write_viewer("w1:p9");
    f.set("FAKE_PANE_IDS", "w1:p1");
    f.click(f.doc.to_str().unwrap());
    assert_eq!(f.opens().len(), 1);
}

#[test]
fn concurrent_clicks_open_one_viewer() {
    let f = fixture();
    let mut children: Vec<_> = (0..4)
        .map(|_| f.command(&["link"]).env("HERDR_PLUGIN_CLICKED_URL", f.doc.to_str().unwrap()).spawn().unwrap())
        .collect();
    for child in &mut children {
        assert!(child.wait().unwrap().success());
    }
    assert_eq!(f.opens().len(), 1);
    assert!(fs::read_to_string(f.state_file(".viewer")).unwrap().starts_with("w1:v"));
}

#[test]
fn link_not_found_notifies() {
    let f = fixture();
    let out = f.click("nowhere/missing.md");
    assert!(out.status.success());
    let notes = f.called(&["notification", "show"]);
    assert_eq!(notes.len(), 1);
    assert!(notes[0].iter().any(|a| a.contains("nowhere/missing.md")), "{notes:?}");
    assert!(f.view().is_none());
    assert!(f.opens().is_empty());
}

#[test]
fn link_resolves_relative() {
    let f = fixture();
    f.click("docs/a.md:3");
    assert_eq!(f.view().unwrap().items, vec![path_item(&f.doc, Some(3))]);
}

#[test]
fn link_url_item() {
    let f = fixture();
    for (clicked, url) in [
        ("https://example.atlassian.net/browse/ABC-1?focusedCommentId=2", "https://example.atlassian.net/browse/ABC-1"),
        ("https://example.atlassian.net/wiki/spaces/X/pages/123/T", "https://example.atlassian.net/wiki/spaces/X/pages/123/T"),
        ("https://github.com/o/r/pull/7/files", "https://github.com/o/r/pull/7"),
    ] {
        let out = f.click(clicked);
        assert!(out.status.success());
        let item = Item { label: url.into(), path: None, url: Some(url.into()), line: None };
        assert_eq!(f.view().unwrap().items, vec![item]);
    }
    assert!(f.called(&["pane", "get"]).is_empty());
}

#[test]
fn link_other_web_url_is_not_resolved() {
    let f = fixture();
    let url = "https://github.com/o/r/blob/main/README.md";
    let out = f.click(url);
    assert!(out.status.success());
    assert!(f.view().is_none());
    assert!(f.called(&["pane", "get"]).is_empty());
    assert!(f.called(&["notification", "show"]).is_empty());
    // PEEK_OPEN points at the fake too, so the hand-off to the browser is logged as a call with the URL alone.
    assert_eq!(f.called(&[url]).len(), 1);
}

#[test]
fn link_source_line() {
    let f = fixture();
    let src = f.repo.join("docs/b.py");
    fs::write(&src, "").unwrap();
    f.click("docs/b.py:7");
    assert_eq!(f.view().unwrap().items, vec![path_item(&src, Some(7))]);
}

#[test]
fn path_label_uses_tilde() {
    let f = fixture();
    let note = f.root.join("home/notes/n.md");
    fs::create_dir_all(note.parent().unwrap()).unwrap();
    fs::write(&note, "").unwrap();
    f.click("~/notes/n.md");
    assert_eq!(f.view().unwrap().items[0].label, "~/notes/n.md");
}

#[test]
fn action_from_viewer_pane() {
    let mut f = fixture();
    f.click(f.doc.to_str().unwrap());
    let before = f.view().unwrap();
    f.write_viewer("w1:p9");
    f.set("HERDR_PANE_ID", "w1:p9");
    let out = f.peek(&["action", "toggle"]);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    let after = f.view().unwrap();
    assert_eq!(after.command.as_deref(), Some("toggle"));
    assert!(after.seq > before.seq);
    // The viewer runs the command; the action itself leaves what is shown and how alone.
    assert_eq!((&after.items, after.mode), (&before.items, before.mode));

    // From the Claude pane the action reaches the same viewer.
    f.set("HERDR_PANE_ID", SRC);
    assert!(f.peek(&["action", "reload"]).status.success());
    let again = f.view().unwrap();
    assert_eq!(again.command.as_deref(), Some("reload"));
    assert!(again.seq > after.seq);

    assert!(!f.peek(&["action", "explode"]).status.success());
    assert_eq!(f.view().unwrap(), again);
}

#[test]
fn action_without_state_does_nothing() {
    let f = fixture();
    assert!(f.peek(&["action", "reload"]).status.success());
    assert!(f.view().is_none());
    assert!(f.calls().is_empty());
}

#[test]
fn click_keeps_mode_and_clears_command() {
    let f = fixture();
    f.click(f.doc.to_str().unwrap());
    let mut st = f.view().unwrap();
    st.mode = Mode::Source;
    st.command = Some("find".into());
    fs::write(f.state_file(".json"), serde_json::to_vec(&st).unwrap()).unwrap();
    f.click("docs/a.md");
    let after = f.view().unwrap();
    assert_eq!(after.mode, Mode::Source);
    assert_eq!(after.command, None);
    assert!(after.seq > st.seq);
}

#[test]
fn link_ambiguous_writes_all() {
    let f = fixture();
    let other = f.repo.join("other/a.md");
    fs::create_dir_all(other.parent().unwrap()).unwrap();
    fs::write(&other, "").unwrap();
    assert!(Command::new("git").args(["init", "-q"]).arg(&f.repo).status().unwrap().success());
    f.click("a.md");
    let mut shown = f.shown().unwrap();
    shown.sort();
    assert_eq!(shown, vec![f.doc.display().to_string(), other.display().to_string()]);
}

/// A folder name no other test run uses, removed again by the guard.
struct TmpProject(String, PathBuf);

impl TmpProject {
    fn new(tag: &str) -> Self {
        let nanos = std::time::SystemTime::now().duration_since(std::time::UNIX_EPOCH).unwrap().as_nanos();
        let name = format!("peek-test-{tag}-{}-{nanos}", std::process::id());
        let uid = unsafe { libc::getuid() };
        let dir = PathBuf::from(format!("/tmp/peek-{uid}")).join(&name);
        TmpProject(name, dir)
    }
}

impl Drop for TmpProject {
    fn drop(&mut self) {
        let _ = fs::remove_file(&self.1);
        let _ = fs::remove_dir_all(&self.1);
    }
}

fn mode_of(path: &Path) -> u32 {
    fs::symlink_metadata(path).unwrap().permissions().mode() & 0o777
}

#[test]
fn session_dir_is_private() {
    let project = TmpProject::new("ok");
    let dir = peek::state::session_dir(&project.0, "s1").unwrap();
    assert_eq!(dir, project.1.join("s1"));
    for path in [dir.parent().unwrap().parent().unwrap(), &project.1, &dir] {
        assert_eq!(mode_of(path), 0o700, "{}", path.display());
    }
    for sub in ["pages", "browser", "screenshots"] {
        assert_eq!(mode_of(&dir.join(sub)), 0o700, "{sub}");
    }
    // Again, with a folder someone loosened: still fine, tightened back.
    fs::set_permissions(&dir, fs::Permissions::from_mode(0o755)).unwrap();
    assert_eq!(peek::state::session_dir(&project.0, "s1").unwrap(), dir);
    assert_eq!(mode_of(&dir), 0o700);

    let elsewhere = tempfile::tempdir().unwrap();
    let linked = TmpProject::new("link");
    fs::create_dir_all(&linked.1).unwrap();
    std::os::unix::fs::symlink(elsewhere.path(), linked.1.join("s1")).unwrap();
    assert!(peek::state::session_dir(&linked.0, "s1").is_err());
    let whole = TmpProject::new("whole");
    std::os::unix::fs::symlink(elsewhere.path(), &whole.1).unwrap();
    assert!(peek::state::session_dir(&whole.0, "s1").is_err());
    assert!(fs::read_dir(elsewhere.path()).unwrap().next().is_none(), "wrote through a link");

    assert!(peek::state::session_dir("..", "s1").is_err());
    assert!(peek::state::session_dir(&project.0, "a/b").is_err());
}

#[test]
fn project_name_matches_claude() {
    assert_eq!(peek::state::project_name(Path::new("/Users/a/src/x.y")), "-Users-a-src-x-y");
    assert_eq!(peek::state::project_name(Path::new("/Users/a/my_dir 2")), "-Users-a-my-dir-2");
}

/// The tests below set PEEK_STATE_DIR in this process; they take turns.
static STATE_ENV: Mutex<()> = Mutex::new(());

fn with_state_dir(run: impl FnOnce(&Path)) {
    let _turn = STATE_ENV.lock().unwrap_or_else(|e| e.into_inner());
    let tmp = tempfile::tempdir().unwrap();
    let dir = tmp.path().join("state");
    std::env::set_var("PEEK_STATE_DIR", &dir);
    run(&dir);
    std::env::remove_var("PEEK_STATE_DIR");
}

#[test]
fn zoom_is_remembered_and_clamped() {
    with_state_dir(|_| {
        assert_eq!(peek::state::zoom(), 100);
        peek::state::set_zoom(130).unwrap();
        assert_eq!(peek::state::zoom(), 130);
        peek::state::set_zoom(500).unwrap();
        assert_eq!(peek::state::zoom(), 200);
        peek::state::set_zoom(10).unwrap();
        assert_eq!(peek::state::zoom(), 50);
    });
}

#[test]
fn state_and_viewer_files() {
    with_state_dir(|dir| {
        use peek::state::*;
        assert_eq!(state_dir(), dir);
        assert_eq!(read_state(SRC), None);
        let st = ViewState { seq: 1_800_000_000_000_000_000, items: vec![], mode: Mode::Source, command: Some("back".into()) };
        write_state(SRC, &st).unwrap();
        assert_eq!(read_state(SRC), Some(st));
        let leftovers: Vec<_> = fs::read_dir(dir).unwrap().map(|e| e.unwrap().file_name()).collect();
        assert_eq!(leftovers, vec![std::ffi::OsString::from(format!("{SRC}.json"))]);

        assert_eq!(viewer_of(SRC), None);
        assert_eq!(source_of_viewer("w1:p9"), None);
        set_viewer(SRC, "w1:p9").unwrap();
        assert_eq!(viewer_of(SRC).as_deref(), Some("w1:p9"));
        assert_eq!(source_of_viewer("w1:p9").as_deref(), Some(SRC));
        assert_eq!(source_of_viewer(SRC), None);
    });
    // Without PEEK_STATE_DIR: under the home folder.
    let _turn = STATE_ENV.lock().unwrap_or_else(|e| e.into_inner());
    let home = std::env::var("HOME").unwrap();
    assert_eq!(peek::state::state_dir(), Path::new(&home).join(".local/state/peek"));
}

/// Panes of a fake herdr for select to open: `(pane id, tab id, focused, what it shows)`.
fn on_screen(f: &mut Fixture, panes: &[(&str, &str, bool, &str)]) {
    let dir = f.root.join("screens");
    fs::create_dir_all(&dir).unwrap();
    let mut list = Vec::new();
    for (id, tab, focused, text) in panes {
        fs::write(dir.join(id.replace(':', "_")), text).unwrap();
        list.push(serde_json::json!({"pane_id": id, "tab_id": tab, "focused": focused}));
    }
    f.set("FAKE_SCREENS", dir.to_str().unwrap());
    f.set("FAKE_PANES_JSON", &serde_json::Value::Array(list).to_string());
}

#[test]
fn select_opens_beside_the_pane_showing_it() {
    let mut f = fixture();
    // herdr leaves focus where it was when a selection is made in another pane.
    on_screen(&mut f, &[(SRC, "w1:t1", false, "$ ls docs\ndocs/a.md\n"), ("w1:p9", "w1:t1", true, "claude\n")]);
    let out = f.peek(&["select", "docs/a.md"]);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    assert!(String::from_utf8_lossy(&out.stdout).starts_with("opened "), "{}", String::from_utf8_lossy(&out.stdout));
    assert_eq!(f.view().unwrap().items, vec![path_item(&f.doc, None)]);
    let opens = f.opens();
    assert_eq!(opens.len(), 1);
    let target = &opens[0][opens[0].iter().position(|a| a == "--target-pane").unwrap() + 1];
    assert_eq!(target, SRC);
}

#[test]
fn select_ignores_text_not_on_screen() {
    let mut f = fixture();
    // Copied in a browser or an editor: no pane shows it.
    on_screen(&mut f, &[(SRC, "w1:t1", true, "$ echo hi\nhi\n")]);
    let out = f.peek(&["select", "docs/a.md"]);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    assert!(f.view().is_none());
    assert!(f.opens().is_empty());
}

#[test]
fn select_looks_only_at_the_shown_tab_and_not_at_viewers() {
    let mut f = fixture();
    f.write_viewer("w1:v1");
    on_screen(
        &mut f,
        &[(SRC, "w1:t1", true, "$\n"), ("w1:v1", "w1:t1", false, "docs/a.md\n"), ("w2:p1", "w2:t1", false, "docs/a.md\n")],
    );
    let out = f.peek(&["select", "docs/a.md"]);
    assert!(out.status.success(), "{}", String::from_utf8_lossy(&out.stderr));
    assert!(f.view().is_none());
    assert!(f.opens().is_empty());
}

#[test]
fn select_to_open_action_toggles_and_says_so() {
    let f = fixture();
    let switch = || fs::read_to_string(f.state.join("select")).unwrap();
    assert!(f.peek(&["action", "select-to-open"]).status.success());
    assert_eq!(switch(), "off");
    assert!(f.peek(&["action", "select-to-open"]).status.success());
    assert_eq!(switch(), "on");
    let notes: Vec<String> = f.called(&["notification", "show"]).into_iter().map(|c| c.join(" ")).collect();
    assert_eq!(notes.len(), 2);
    assert!(notes[0].ends_with("Select to open: off"), "{notes:?}");
    assert!(notes[1].ends_with("Select to open: on"), "{notes:?}");
}
