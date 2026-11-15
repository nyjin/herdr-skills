import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
import resolve  # noqa: E402

SID = "11111111-2222-3333-4444-555555555555"


def touch(path, text="# x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)
    return os.path.realpath(path)


class ResolveTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(self.tmp.name)
        self.home = os.path.join(root, "home")
        self.repo = os.path.join(root, "repo")
        self.tmp_root = os.path.join(root, "claude-tmp")
        self.projects = os.path.join(root, "projects")
        os.makedirs(self.home)
        os.makedirs(self.repo)
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.a = touch(os.path.join(self.repo, "docs", "a.md"))
        self.b = touch(os.path.join(self.repo, "pkg", "sub", "b.md"))

    def tearDown(self):
        self.tmp.cleanup()

    def find(self, text, sid=SID, cwd=None):
        return resolve.candidates(text, cwd or self.repo, sid, home=self.home,
                                  tmp_root=self.tmp_root, projects_root=self.projects)

    def transcript(self, *paths):
        os.makedirs(os.path.join(self.projects, "p"), exist_ok=True)
        with open(os.path.join(self.projects, "p", SID + ".jsonl"), "w") as f:
            for p in paths:
                f.write(json.dumps({"tool_input": {"file_path": p}}) + "\n")

    def test_absolute_and_home(self):
        self.assertEqual(self.find(self.a), [self.a])
        x = touch(os.path.join(self.home, "x.md"))
        self.assertEqual(self.find("~/x.md"), [x])
        self.assertEqual(self.find("/nope/missing.md"), [])

    def test_relative_to_cwd(self):
        self.assertEqual(self.find("docs/a.md"), [self.a])

    def test_scratchpad(self):
        n = touch(os.path.join(self.tmp_root, "-proj", SID, "scratchpad", "n.md"))
        self.assertEqual(self.find("scratchpad/n.md"), [n])
        self.assertEqual(self.find("n.md"), [n])

    def test_transcript_suffix(self):
        z = touch(os.path.join(self.home, "elsewhere", "deep", "z.md"))
        self.transcript(z)
        self.assertEqual(self.find("…/deep/z.md"), [z])

    def test_git_suffix(self):
        self.assertEqual(self.find("sub/b.md"), [self.b])

    def test_dedupe_same_file(self):
        self.transcript(self.a)
        self.assertEqual(self.find("docs/a.md"), [self.a])

    def test_ambiguous_order(self):
        a = touch(os.path.join(self.home, "one", "SKILL.md"))
        b = touch(os.path.join(self.home, "two", "SKILL.md"))
        self.transcript(b, a, b, a)
        self.assertEqual(self.find("SKILL.md"), [a, b])

    def test_no_session(self):
        self.assertEqual(self.find("sub/b.md", sid=None), [self.b])

    def test_resolve_any_extension(self):
        x = touch(os.path.join(self.repo, "pkg", "x.py"), "print(1)\n")
        self.assertEqual(self.find("pkg/x.py"), [x])
        z = touch(os.path.join(self.home, "far", "deep", "z.kt"))
        self.transcript(z)
        self.assertEqual(self.find("…/deep/z.kt"), [z])

    def test_normalize_suffixes(self):
        self.assertEqual(resolve.normalize("file:///x/a.md:12:3"), "/x/a.md")
        self.assertEqual(resolve.normalize("(docs/a.md),"), "docs/a.md")
        self.assertEqual(resolve.normalize("`a.md`."), "a.md")
        self.assertEqual(resolve.normalize("'~/n.markdown'"), "~/n.markdown")


if __name__ == "__main__":
    unittest.main()
