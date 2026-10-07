"""Unit tests for scripts/hooks/owners.py. Run from the repo root:
python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
HOOKS = os.path.join(os.path.dirname(HERE), "scripts", "hooks")
sys.path.insert(0, HOOKS)
import owners  # noqa: E402

# A fake layout: repo R (main checkout /r, linked worktrees /w/a /w/b /w/ab), repo S (main /s, linked /x/s1).
PROBE = {
    "/r": ("/r/.git", "/r/.git", "/r"),
    "/w/a": ("/r/.git/worktrees/a", "/r/.git", "/w/a"),
    "/w/ab": ("/r/.git/worktrees/ab", "/r/.git", "/w/ab"),
    "/w/b": ("/r/.git/worktrees/b", "/r/.git", "/w/b"),
    "/w/b/sub": ("/r/.git/modules/sub", "/r/.git/modules/sub", "/w/b/sub"),   # a submodule inside /w/b
    "/s": ("/s/.git", "/s/.git", "/s"),
    "/x/s1": ("/s/.git/worktrees/s1", "/s/.git", "/x/s1"),
}


def fake_probe(path):
    best = None
    for top, info in PROBE.items():
        if path == top or path.startswith(top + "/"):
            if best is None or len(top) > len(best[0]):
                best = (top, info)
    return best[1] if best else None


RUNS = [{"name": "b", "worktree": "/w/b", "state": "open"}]


def owner(path, runs=RUNS):
    return owners.owner_of(path, runs, fake_probe, writer_common="/r/.git", writer_main="/r", realpath=lambda p: p)


class OwnerTest(unittest.TestCase):
    def test_four_kinds(self):
        self.assertEqual(owner("/w/b/f.py"), ("worker", "b", "/w/b"))
        self.assertEqual(owner("/w/a/f.py"), ("none", None, "/w/a"))
        self.assertEqual(owner("/r/f.py"), ("main-checkout", None, "/r"))
        self.assertIsNone(owner("/tmp/f.py"))

    def test_path_boundary(self):
        self.assertEqual(owner("/w/ab/f.py"), ("none", None, "/w/ab"))   # not worker b, not worktree a

    def test_longest_worktree_wins(self):
        runs = [{"name": "outer", "worktree": "/w", "state": "open"},
                {"name": "b", "worktree": "/w/b", "state": "open"}]
        self.assertEqual(owner("/w/b/f.py", runs), ("worker", "b", "/w/b"))
        self.assertEqual(owner("/w/c.py", runs), ("worker", "outer", "/w"))

    def test_submodule_inside_a_worker_worktree_belongs_to_that_worker(self):
        self.assertEqual(owner("/w/b/sub/f.c"), ("worker", "b", "/w/b"))

    def test_other_repos_are_out_of_scope_unless_recorded(self):
        self.assertIsNone(owner("/s/f.py"))       # another repo's main checkout
        self.assertIsNone(owner("/x/s1/f.py"))    # another repo's linked worktree, not in runs.json
        runs = RUNS + [{"name": "s1", "worktree": "/x/s1", "state": "open"}]
        self.assertEqual(owner("/x/s1/f.py", runs), ("worker", "s1", "/x/s1"))

    def test_new_file_path_is_normalised(self):
        self.assertEqual(owner("/w/a/../b/new/f.py"), ("worker", "b", "/w/b"))


class ReadOpenRunsTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "runs.json")

    def tearDown(self):
        subprocess.run(["rm", "-rf", self.dir], check=False)

    def write(self, text):
        with open(self.path, "w") as f:
            f.write(text)

    def test_never_raises(self):
        self.assertEqual(owners.read_open_runs(os.path.join(self.dir, "missing.json")), [])
        for text in ("not json", "{}", '"x"', "[1, null, \"a\"]", '[{"state": "open"}]', ""):
            with self.subTest(text=text):
                self.write(text)
                self.assertEqual(owners.read_open_runs(self.path), [])

    def test_keeps_open_runs_only_and_resolves_paths(self):
        real = os.path.realpath(self.dir)   # on macOS /var/... -> /private/var/...
        self.write(json.dumps([
            {"name": "a", "worktree": os.path.join(self.dir, "a"), "state": "open"},
            {"name": "b", "worktree": os.path.join(self.dir, "b"), "state": "cleaned"},
        ]))
        runs = owners.read_open_runs(self.path)
        self.assertEqual([(r["name"], r["worktree"]) for r in runs], [("a", os.path.join(real, "a"))])


class WorktreeListTest(unittest.TestCase):
    def test_parse_porcelain_z(self):
        data = ("worktree /r\0HEAD 1111\0branch refs/heads/main\0\0"
                "worktree /w/a\0HEAD 2222\0detached\0locked\0\0"
                "worktree /w/gone\0HEAD 3333\0branch refs/heads/g\0prunable gitdir file points to non-existent location\0\0")
        got = owners.parse_worktree_list_z(data)
        self.assertEqual([e["path"] for e in got], ["/r", "/w/a", "/w/gone"])
        self.assertTrue(got[2]["prunable"])
        self.assertFalse(got[0]["bare"])

    def test_parse_bare(self):
        got = owners.parse_worktree_list_z("worktree /bare.git\0bare\0\0worktree /w/a\0HEAD 1\0branch refs/heads/a\0\0")
        self.assertTrue(got[0]["bare"])

    def test_empty_or_garbage(self):
        self.assertEqual(owners.parse_worktree_list_z(""), [])
        self.assertEqual(owners.parse_worktree_list_z("\0\0junk\0"), [])


class RealGitTest(unittest.TestCase):
    """Real repositories: plain, --separate-git-dir, and a bare repository with a linked worktree."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()   # unresolved /var/... on macOS on purpose
        g = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]

        def sh(*args):
            subprocess.run(list(args), check=True, capture_output=True)

        cls.repo, cls.wt = os.path.join(cls.tmp, "repo"), os.path.join(cls.tmp, "wt")
        sh("git", "init", "-q", cls.repo)
        sh(*g, "-C", cls.repo, "commit", "-q", "--allow-empty", "-m", "i")
        sh("git", "-C", cls.repo, "worktree", "add", "-q", cls.wt, "-b", "w")
        cls.sep, cls.sepdir = os.path.join(cls.tmp, "sep"), os.path.join(cls.tmp, "sep.gitdir")
        sh("git", "init", "-q", "--separate-git-dir", cls.sepdir, cls.sep)
        sh(*g, "-C", cls.sep, "commit", "-q", "--allow-empty", "-m", "i")
        cls.sepwt = os.path.join(cls.tmp, "sepwt")
        sh("git", "-C", cls.sep, "worktree", "add", "-q", cls.sepwt, "-b", "s")
        cls.bare, cls.bwt = os.path.join(cls.tmp, "bare.git"), os.path.join(cls.tmp, "bwt")
        sh("git", "clone", "-q", "--bare", cls.repo, cls.bare)
        sh("git", "-C", cls.bare, "worktree", "add", "-q", cls.bwt, "w")

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["rm", "-rf", cls.tmp], check=False)

    def real(self, p):
        return os.path.realpath(p)

    def test_main_checkout_of_plain_repo_from_either_checkout(self):
        self.assertEqual(owners.main_checkout_of(self.repo, owners.git), self.real(self.repo))
        self.assertEqual(owners.main_checkout_of(os.path.join(self.wt, "x.py"), owners.git), self.real(self.repo))

    def test_main_checkout_of_separate_git_dir(self):
        self.assertEqual(owners.main_checkout_of(self.sep, owners.git), self.real(self.sep))

    def test_separate_git_dir_seen_from_a_linked_worktree_is_unknown(self):
        # git lists the git directory, not the checkout, as the main worktree here; unknown is the safe answer
        self.assertIsNone(owners.main_checkout_of(self.sepwt, owners.git))

    def test_bare_repository_has_no_main_checkout(self):
        self.assertIsNone(owners.main_checkout_of(self.bwt, owners.git))

    def test_outside_git(self):
        self.assertIsNone(owners.main_checkout_of(self.tmp, owners.git))

    def test_owner_of_with_real_probe(self):
        import route   # noqa: E402  (route.git_probe is the real probe)
        common = self.real(os.path.join(self.repo, ".git"))
        main = self.real(self.repo)
        own = lambda p, runs=(): owners.owner_of(p, list(runs), route.git_probe, common, main)
        self.assertEqual(own(os.path.join(self.wt, "f.py")), ("none", None, self.real(self.wt)))
        self.assertEqual(own(os.path.join(self.repo, "f.py")), ("main-checkout", None, main))
        runs = [{"name": "w", "worktree": self.real(self.wt), "state": "open"}]
        self.assertEqual(own(os.path.join(self.wt, "new", "f.py"), runs), ("worker", "w", self.real(self.wt)))
        self.assertIsNone(own(os.path.join(self.sep, "f.py")))   # another repository


if __name__ == "__main__":
    unittest.main()
