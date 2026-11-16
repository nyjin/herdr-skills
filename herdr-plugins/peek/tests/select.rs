//! Select to open: which clipboard texts count, which pane a selection came from, and what it opens.
//!
//! Korean appears here on purpose: Korean attaches particles to the word before them without a space, so herdr's
//! double-click copies a path together with its particle, and Korean folder and file names must still open as
//! selected. The strings are the sample content those rules are about.
use peek::resolve::Context;
use peek::select::{forms, path_shaped, resolve, source_pane, usable, Screen};
use peek::watcher::{Clipboard, Poll};
use std::cell::{Cell, RefCell};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

struct Repo {
    _tmp: tempfile::TempDir,
    root: PathBuf,
}

impl Repo {
    fn new() -> Self {
        let tmp = tempfile::tempdir().unwrap();
        // Real path: on macOS the temp folder sits behind the /var -> /private/var link.
        let root = fs::canonicalize(tmp.path()).unwrap();
        let ok = Command::new("git").args(["init", "-q"]).arg(&root).status().unwrap().success();
        assert!(ok, "git init failed");
        Repo { _tmp: tmp, root }
    }

    /// Creates the file (and its folders) with `bytes` and returns its real path.
    fn file(&self, rel: &str, bytes: &[u8]) -> PathBuf {
        let path = self.root.join(rel);
        fs::create_dir_all(path.parent().unwrap()).unwrap();
        fs::write(&path, bytes).unwrap();
        fs::canonicalize(path).unwrap()
    }

    fn ctx(&self) -> Context {
        Context {
            cwd: self.root.clone(),
            session_id: None,
            home: self.root.join("home"),
            tmp_root: self.root.join("claude-tmp"),
            projects_root: self.root.join("projects"),
        }
    }

    fn open(&self, text: &str) -> Option<(Vec<PathBuf>, Option<u32>)> {
        resolve(text, &self.ctx())
    }
}

fn one(found: Option<(Vec<PathBuf>, Option<u32>)>) -> (PathBuf, Option<u32>) {
    let (paths, line) = found.expect("the selection should open something");
    assert_eq!(paths.len(), 1, "{paths:?}");
    (paths[0].clone(), line)
}

#[test]
fn usable_takes_one_trimmed_line() {
    assert_eq!(usable("docs/a.md"), Some("docs/a.md"));
    assert_eq!(usable("  docs/a.md \n"), Some("docs/a.md"));
    assert_eq!(usable(""), None);
    assert_eq!(usable("   "), None);
    assert_eq!(usable("docs/a.md\ndocs/b.md"), None);
    assert_eq!(usable("\u{1b}[31mdocs/a.md"), None);
    assert_eq!(usable(&"a".repeat(1025)), None);
    assert!(usable(&"a".repeat(1024)).is_some());
}

#[test]
fn screen_match_by_row_and_across_wrapped_rows() {
    let screens = [Screen { pane: "w1:p1", focused: false, text: "$ ls\ndocs/a.md\n$\n" }];
    assert_eq!(source_pane("docs/a.md", &screens), Some("w1:p1"));
    assert_eq!(source_pane("docs/b.md", &screens), None);
    // A long line the terminal wrapped: the selection holds it whole.
    let wrapped = [Screen { pane: "w1:p2", focused: false, text: "see docs/super\npowers/a.md now\n" }];
    assert_eq!(source_pane("docs/superpowers/a.md", &wrapped), Some("w1:p2"));
}

#[test]
fn focused_pane_wins_when_several_show_the_text() {
    let screens = [
        Screen { pane: "w1:p1", focused: false, text: "docs/a.md" },
        Screen { pane: "w1:p2", focused: true, text: "docs/a.md" },
    ];
    assert_eq!(source_pane("docs/a.md", &screens), Some("w1:p2"));
    let unfocused = [
        Screen { pane: "w1:p1", focused: false, text: "docs/a.md" },
        Screen { pane: "w1:p2", focused: false, text: "docs/a.md" },
    ];
    assert_eq!(source_pane("docs/a.md", &unfocused), Some("w1:p1"));
}

#[test]
fn forms_drop_up_to_four_characters_from_the_end() {
    assert_eq!(forms("abc.md를"), vec!["abc.md를", "abc.md", "abc.m", "abc.", "abc"]);
    assert_eq!(forms("ab"), vec!["ab", "a"]);
}

#[test]
fn path_shape_needs_a_slash_an_extension_or_a_line() {
    for text in ["bin/peek", "a.md", "kitty.rs:58", "docs/", "./run"] {
        assert!(path_shaped(text), "{text}");
    }
    for text in ["peek", "LICENSE", "README", "peeking", "kitty.rs:58에서"] {
        assert!(!path_shaped(text), "{text}");
    }
}

#[test]
fn opens_as_selected() {
    let repo = Repo::new();
    let a = repo.file("docs/a.md", b"# a\n");
    assert_eq!(one(repo.open("docs/a.md")), (a.clone(), None));
    // A shortened path resolves like a click: the git checkout's files by tail.
    assert_eq!(one(repo.open("a.md")), (a, None));
}

#[test]
fn korean_names_open_as_selected() {
    let repo = Repo::new();
    let minutes = repo.file("회의록/3월.md", b"# minutes\n");
    assert_eq!(one(repo.open("회의록/3월.md")), (minutes, None));
}

#[test]
fn a_particle_after_the_path_is_dropped() {
    let repo = Repo::new();
    let minutes = repo.file("회의록/3월.md", b"# minutes\n");
    let kitty = repo.file("src/kitty.rs", b"fn main() {}\n");
    assert_eq!(one(repo.open("회의록/3월.md를")), (minutes, None));
    assert_eq!(one(repo.open("src/kitty.rs:58에서")), (kitty, Some(58)));
}

#[test]
fn a_name_that_really_ends_in_a_particle_opens_as_selected() {
    let repo = Repo::new();
    repo.file("notes/x.md", b"short\n");
    let real = repo.file("notes/x.md를", b"the file with the particle in its name\n");
    assert_eq!(one(repo.open("notes/x.md를")), (real, None));
}

#[test]
fn folders_open_nothing() {
    let repo = Repo::new();
    repo.file("docs/superpowers/specs/a.md", b"# a\n");
    assert_eq!(repo.open("docs/superpowers/specs/"), None);
    assert_eq!(repo.open("docs/superpowers/specs/에"), None);
}

#[test]
fn words_that_name_a_file_by_its_tail_open_nothing() {
    let repo = Repo::new();
    repo.file("herdr-plugins/peek/bin/peek", b"#!/bin/sh\n");
    repo.file("LICENSE", b"MIT\n");
    for word in ["peek", "peeking", "LICENSE"] {
        assert_eq!(repo.open(word), None, "{word}");
    }
    // With a slash it is a path.
    assert!(repo.open("bin/peek").is_some());
}

#[test]
fn binary_files_are_skipped_but_images_are_not() {
    let repo = Repo::new();
    repo.file("data/blob.bin", b"\x00\x01\x02");
    let png = repo.file("img/a.png", b"\x89PNG\r\n\x1a\n\x00\x00");
    assert_eq!(repo.open("data/blob.bin"), None);
    assert_eq!(one(repo.open("img/a.png")), (png, None));
}

#[test]
fn web_addresses_are_left_to_ctrl_click() {
    let repo = Repo::new();
    repo.file("a.md", b"# a\n");
    assert_eq!(repo.open("https://example.com/a.md"), None);
}

/// macOS file systems find a decomposed (NFD) name by its composed (NFC) spelling; the screen shows NFC. Linux file
/// systems compare bytes, so this holds on macOS only.
#[cfg(target_os = "macos")]
#[test]
fn a_decomposed_korean_name_opens_by_its_composed_spelling() {
    let repo = Repo::new();
    // "한글" written as conjoining jamo (NFD), the way some macOS tools save names.
    let nfd = "\u{1112}\u{1161}\u{11ab}\u{1100}\u{1173}\u{11af}";
    let path = repo.file(&format!("문서/{nfd}.md"), b"# nfd\n");
    let (found, _) = one(repo.open("문서/한글.md"));
    assert_eq!(fs::canonicalize(found).unwrap(), fs::canonicalize(Path::new(&path)).unwrap());
}

/// A clipboard whose change count and text the test sets.
struct FakeClipboard {
    count: Cell<isize>,
    text: RefCell<Option<String>>,
    reads: Cell<usize>,
}

impl FakeClipboard {
    fn new(count: isize, text: &str) -> Self {
        FakeClipboard { count: Cell::new(count), text: RefCell::new(Some(text.into())), reads: Cell::new(0) }
    }

    fn copy(&self, text: &str) {
        self.count.set(self.count.get() + 1);
        *self.text.borrow_mut() = Some(text.into());
    }
}

impl Clipboard for FakeClipboard {
    fn change_count(&self) -> isize {
        self.count.get()
    }

    fn text(&self) -> Option<String> {
        self.reads.set(self.reads.get() + 1);
        self.text.borrow().clone()
    }
}

#[test]
fn poll_ignores_what_was_there_and_reads_only_after_a_change() {
    let clip = FakeClipboard::new(7, "copied before peek started");
    let mut poll = Poll::new(&clip);
    assert!(!poll.changed(&clip));
    assert!(!poll.changed(&clip));
    clip.copy("docs/a.md");
    assert!(poll.changed(&clip));
    assert!(!poll.changed(&clip));
    // Polling looks at the count only; the text is read by the caller, once per change.
    assert_eq!(clip.reads.get(), 0);
}
