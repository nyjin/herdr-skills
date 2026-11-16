//! File change events: a burst of saves (including a save by rename) becomes one callback.
#![cfg(target_os = "macos")]
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;

#[test]
fn burst_of_saves_is_one_change() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("doc.md");
    std::fs::write(&file, "one").unwrap();
    let hits = Arc::new(AtomicUsize::new(0));
    let h = hits.clone();
    let _w = peek::mac::watch::watch(&file, move || {
        h.fetch_add(1, Ordering::SeqCst);
    })
    .unwrap();
    std::thread::sleep(Duration::from_millis(300)); // FSEvents needs a moment to start
    std::fs::write(&file, "two").unwrap();
    std::thread::sleep(Duration::from_millis(50));
    let tmp = dir.path().join(".doc.md.tmp");
    std::fs::write(&tmp, "three").unwrap();
    std::fs::rename(&tmp, &file).unwrap(); // the way editors and Claude save
    std::thread::sleep(Duration::from_millis(1500));
    assert_eq!(hits.load(Ordering::SeqCst), 1);
}

#[test]
fn other_files_in_the_folder_are_ignored() {
    let dir = tempfile::tempdir().unwrap();
    let file = dir.path().join("doc.md");
    std::fs::write(&file, "one").unwrap();
    let hits = Arc::new(AtomicUsize::new(0));
    let h = hits.clone();
    let _w = peek::mac::watch::watch(&file, move || {
        h.fetch_add(1, Ordering::SeqCst);
    })
    .unwrap();
    std::thread::sleep(Duration::from_millis(300));
    std::fs::write(dir.path().join("other.md"), "x").unwrap();
    std::thread::sleep(Duration::from_millis(1200));
    assert_eq!(hits.load(Ordering::SeqCst), 0);
}
