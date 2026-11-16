//! Path resolution and link classification: the Python cases of tests/test_resolve.py, ported, plus names with
//! spaces and Korean characters.
use peek::resolve::{candidates, normalize, Context};
use peek::target::{classify, Target};
use std::fs;
use std::path::{Path, PathBuf};
use std::process::Command;

const SID: &str = "11111111-2222-3333-4444-555555555555";

struct Fixture {
    _tmp: tempfile::TempDir,
    home: PathBuf,
    repo: PathBuf,
    tmp_root: PathBuf,
    projects: PathBuf,
    a: PathBuf,
    b: PathBuf,
}

/// Creates the file (and its folders) and returns its real path.
fn touch(path: &Path, text: &str) -> PathBuf {
    fs::create_dir_all(path.parent().unwrap()).unwrap();
    fs::write(path, text).unwrap();
    fs::canonicalize(path).unwrap()
}

fn fixture() -> Fixture {
    let tmp = tempfile::tempdir().unwrap();
    // Real path: on macOS the temp folder sits behind the /var -> /private/var link.
    let root = fs::canonicalize(tmp.path()).unwrap();
    let (home, repo) = (root.join("home"), root.join("repo"));
    fs::create_dir_all(&home).unwrap();
    fs::create_dir_all(&repo).unwrap();
    let ok = Command::new("git").args(["init", "-q"]).arg(&repo).status().unwrap().success();
    assert!(ok, "git init failed");
    let a = touch(&repo.join("docs/a.md"), "# x\n");
    let b = touch(&repo.join("pkg/sub/b.md"), "# x\n");
    Fixture { home, repo, tmp_root: root.join("claude-tmp"), projects: root.join("projects"), a, b, _tmp: tmp }
}

impl Fixture {
    fn ctx(&self, session: Option<&str>) -> Context {
        Context {
            cwd: self.repo.clone(),
            session_id: session.map(String::from),
            home: self.home.clone(),
            tmp_root: self.tmp_root.clone(),
            projects_root: self.projects.clone(),
        }
    }

    fn find(&self, text: &str) -> Vec<PathBuf> {
        candidates(text, &self.ctx(Some(SID)))
    }

    /// A session transcript that mentions `paths` in this order, one tool call per line.
    fn transcript(&self, paths: &[&Path]) {
        let dir = self.projects.join("p");
        fs::create_dir_all(&dir).unwrap();
        let lines: Vec<String> = paths
            .iter()
            .map(|p| serde_json::json!({"tool_input": {"file_path": p.to_str().unwrap()}}).to_string())
            .collect();
        fs::write(dir.join(format!("{SID}.jsonl")), lines.join("\n") + "\n").unwrap();
    }
}

#[test]
fn absolute_and_home() {
    let f = fixture();
    assert_eq!(f.find(f.a.to_str().unwrap()), vec![f.a.clone()]);
    let x = touch(&f.home.join("x.md"), "# x\n");
    assert_eq!(f.find("~/x.md"), vec![x]);
    assert!(f.find("/nope/missing.md").is_empty());
}

#[test]
fn relative_to_cwd() {
    let f = fixture();
    assert_eq!(f.find("docs/a.md"), vec![f.a.clone()]);
}

#[test]
fn scratchpad() {
    let f = fixture();
    let n = touch(&f.tmp_root.join("-proj").join(SID).join("scratchpad/n.md"), "# n\n");
    assert_eq!(f.find("scratchpad/n.md"), vec![n.clone()]);
    assert_eq!(f.find("n.md"), vec![n]);
}

#[test]
fn transcript_suffix() {
    let f = fixture();
    let z = touch(&f.home.join("elsewhere/deep/z.md"), "# z\n");
    f.transcript(&[&z]);
    assert_eq!(f.find("…/deep/z.md"), vec![z]);
}

#[test]
fn git_suffix() {
    let f = fixture();
    assert_eq!(f.find("sub/b.md"), vec![f.b.clone()]);
}

#[test]
fn dedupe_same_file() {
    let f = fixture();
    f.transcript(&[&f.a]);
    assert_eq!(f.find("docs/a.md"), vec![f.a.clone()]);
}

#[test]
fn ambiguous_order() {
    let f = fixture();
    let a = touch(&f.home.join("one/SKILL.md"), "# a\n");
    let b = touch(&f.home.join("two/SKILL.md"), "# b\n");
    f.transcript(&[&b, &a, &b, &a]);
    assert_eq!(f.find("SKILL.md"), vec![a, b]);
}

#[test]
fn no_session() {
    let f = fixture();
    assert_eq!(candidates("sub/b.md", &f.ctx(None)), vec![f.b.clone()]);
}

#[test]
fn resolve_any_extension() {
    let f = fixture();
    let x = touch(&f.repo.join("pkg/x.py"), "print(1)\n");
    assert_eq!(f.find("pkg/x.py"), vec![x]);
    let z = touch(&f.home.join("far/deep/z.kt"), "fun main() {}\n");
    f.transcript(&[&z]);
    assert_eq!(f.find("…/deep/z.kt"), vec![z]);
}

#[test]
fn normalize_suffixes() {
    assert_eq!(normalize("file:///x/a.md:12:3"), "/x/a.md");
    assert_eq!(normalize("(docs/a.md),"), "docs/a.md");
    assert_eq!(normalize("`a.md`."), "a.md");
    assert_eq!(normalize("'~/n.markdown'"), "~/n.markdown");
    assert_eq!(normalize("src/x.py:7:2"), "src/x.py");
    // A web address keeps its port: only a file path has a line suffix.
    assert_eq!(normalize("https://example.com:8080"), "https://example.com:8080");
}

#[test]
fn resolves_path_with_space_and_korean() {
    let f = fixture();
    // Korean file and folder names on purpose: the review focus is paths with spaces and Korean names.
    let doc = touch(&f.repo.join("my docs/보고/회의록.md"), "# notes\n");
    assert_eq!(f.find(doc.to_str().unwrap()), vec![doc.clone()]);
    assert_eq!(f.find("my docs/보고/회의록.md"), vec![doc.clone()]);
    assert_eq!(f.find("\"my docs/보고/회의록.md\","), vec![doc.clone()]);
    // Only the git checkout's file list holds this tail. git quotes non-ASCII names by default; pin that default
    // here, whatever the user's global config says.
    let quote = Command::new("git").arg("-C").arg(&f.repo).args(["config", "core.quotePath", "true"]).status();
    assert!(quote.unwrap().success());
    assert_eq!(f.find("보고/회의록.md"), vec![doc.clone()]);
    let far = touch(&f.home.join("문서/요약.md"), "# far\n");
    f.transcript(&[&far]);
    assert_eq!(f.find("…/문서/요약.md"), vec![far]);
}

#[test]
fn classify_targets() {
    let jira = classify("https://example.atlassian.net/browse/ABC-12?focusedCommentId=5).");
    assert_eq!(jira, Target::Jira { site: "https://example.atlassian.net".into(), key: "ABC-12".into() });
    assert_eq!(jira.url().as_deref(), Some("https://example.atlassian.net/browse/ABC-12"));

    let page = "https://example.atlassian.net/wiki/spaces/X/pages/12345/Title";
    let conf = classify(page);
    assert_eq!(
        conf,
        Target::Confluence { site: "https://example.atlassian.net".into(), page_id: Some("12345".into()), url: page.into() }
    );
    assert_eq!(conf.url().as_deref(), Some(page));
    let no_id = classify("https://example.atlassian.net/wiki/x/AbCd");
    assert!(matches!(no_id, Target::Confluence { page_id: None, .. }));

    let pr = classify("https://github.com/o/r/pull/12/files");
    assert_eq!(pr, Target::GithubPr { repo: "o/r".into(), number: 12 });
    assert_eq!(pr.url().as_deref(), Some("https://github.com/o/r/pull/12"));

    assert_eq!(classify("docs/b.py:7"), Target::Path { text: "docs/b.py".into(), line: Some(7) });
    assert_eq!(classify("(docs/a.md:3:1)"), Target::Path { text: "docs/a.md".into(), line: Some(3) });
    assert_eq!(classify("a.rs:99999999999"), Target::Path { text: "a.rs".into(), line: None });
    let blob = "https://github.com/o/r/blob/main/README.md";
    assert_eq!(classify(blob), Target::Path { text: blob.into(), line: None });
    assert_eq!(classify(blob).url(), None);
}
