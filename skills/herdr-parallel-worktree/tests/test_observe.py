"""Unit tests for scripts/hooks/observe.py (the pure parts of R7). Run from the repo root:
python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "scripts", "hooks"))
import observe  # noqa: E402
import owners  # noqa: E402

ident = lambda p: p   # realpath stand-in for the fake layout


class WindowTest(unittest.TestCase):
    def test_start_is_floored_after_the_margin(self):
        self.assertEqual(observe.window(100.9, 2000, []), (98.0, 100.9))      # 98.9 - 0.5 = 98.4 -> 98
        self.assertEqual(observe.window(100.0, 0, []), (99.0, 100.0))

    def test_background_starts_widen_it(self):
        self.assertEqual(observe.window(100.0, 1000, [50.2, 80.0]), (49.0, 100.0))

    def test_missing_or_bad_duration(self):
        for bad in (None, "1000", True, -5, float("nan")):
            with self.subTest(bad=bad):
                self.assertIsNone(observe.window(100.0, bad, []))


class ParseStatusTest(unittest.TestCase):
    def test_record_kinds(self):
        data = ("1 .M N... 100644 100644 100644 aaa bbb dir/with space.py\0"
                "2 R. N... 100644 100644 100644 aaa bbb R100 new name.py\0old name.py\0"
                "u UU N... 100644 100644 100644 100644 a b c conflict.py\0"
                "? 한글/새 파일.txt\0"
                "! ignored.log\0"
                "# branch.oid abc\0"
                "1 .D N... 100644 100644 000000 aaa aaa gone.py\0"
                "1 D. N... 100644 000000 000000 aaa 000 staged-gone.py\0")
        self.assertEqual(observe.parse_status_v2_z(data), [
            ("dir/with space.py", False), ("new name.py", False), ("conflict.py", False),
            ("한글/새 파일.txt", False), ("gone.py", True), ("staged-gone.py", True)])

    def test_rename_consumes_its_original_path(self):
        data = "2 R. N... 100644 100644 100644 a b R100 to.py\x00from.py\x00? after.txt\x00"
        self.assertEqual(observe.parse_status_v2_z(data), [("to.py", False), ("after.txt", False)])

    def test_newline_in_path_and_empty(self):
        self.assertEqual(observe.parse_status_v2_z("? a\nb.txt\0"), [("a\nb.txt", False)])
        self.assertEqual(observe.parse_status_v2_z(""), [])

    def test_garbage_does_not_raise(self):
        self.assertEqual(observe.parse_status_v2_z("1 short\0zzz\0"), [])


class MentionedPathsTest(unittest.TestCase):
    def mp(self, cmd, cwd="/r", home="/r"):
        return observe.mentioned_paths([cmd], cwd, home, realpath=ident)

    def test_forms(self):
        cases = {
            "echo x > /w/b/f.py": ["/w/b/f.py"],
            "sed -i '' s/a/b/ '/w/b/my file.py'": ["/w/b/my file.py"],
            "D=/w/b; echo x > $D/f": ["/w/b"],
            "git --work-tree=/w/b commit -am x": ["/w/b"],
            "cp a ../w/b/": ["/w/b"],   # cwd /r -> /w/b? no: /r/../w/b = /w/b
            "npm --prefix /w/b run fmt": ["/w/b"],
        }
        for cmd, want in cases.items():
            with self.subTest(cmd=cmd):
                self.assertEqual(self.mp(cmd), want)

    def test_tilde(self):
        got = observe.mentioned_paths(["cat ~/notes.txt"], "/r", "/r", realpath=ident)
        self.assertEqual(got, [os.path.expanduser("~/notes.txt")])

    def test_home_paths_and_plain_words_are_not_mentions(self):
        self.assertEqual(self.mp("echo hi > out.txt && ls src"), [])          # relative inside home
        self.assertEqual(self.mp("cat /r/README.md"), [])                     # absolute inside home
        self.assertEqual(self.mp("git commit -m 'done'"), [])

    def test_unbalanced_quotes_fall_back(self):
        self.assertEqual(self.mp("echo it's > /w/b/f"), ["/w/b/f"])


class CandidatesTest(unittest.TestCase):
    RUNS = [{"name": "b", "worktree": "/w/b", "state": "open"}]

    def test_owner_of_each_mentioned_worktree(self):
        got = observe.candidates(["/w/b/f.py", "/w/c/x", "/tmp/y", "/w/b/g.py"], self.RUNS,
                                 writer_wts=["/w/a", "/w/b", "/w/c"], writer_main="/r", home="/w/a")
        self.assertEqual(got, [("/w/b", ("worker", "b", "/w/b")), ("/w/c", ("none", None, "/w/c"))])

    def test_main_checkout_only_when_given(self):
        args = dict(runs=[], writer_wts=["/w/a"], home="/w/a")
        self.assertEqual(observe.candidates(["/r/f"], writer_main="/r", **args),
                         [("/r", ("main-checkout", None, "/r"))])
        self.assertEqual(observe.candidates(["/r/f"], writer_main=None, **args), [])

    def test_nested_worktree_inside_main_checkout_wins(self):
        got = observe.candidates(["/r/.worktrees/x/f"], [], writer_wts=["/r/.worktrees/x"], writer_main="/r",
                                 home="/w/a")
        self.assertEqual(got, [("/r/.worktrees/x", ("none", None, "/r/.worktrees/x"))])

    def test_home_is_never_a_candidate(self):
        self.assertEqual(observe.candidates(["/w/a/f"], [], writer_wts=["/w/a"], writer_main="/r", home="/w/a"), [])


class FakeStat:
    def __init__(self, ctimes):
        self.ctimes = ctimes

    def __call__(self, path):
        if path not in self.ctimes:
            raise FileNotFoundError(path)
        return os.stat_result((0, 0, 0, 0, 0, 0, 0, 0, 0, self.ctimes[path]))


class ChangedTest(unittest.TestCase):
    WIN = (100.0, 110.0)

    def changed(self, entries, ctimes, exclude=(), git_paths=()):
        return observe.changed("/w/b", entries, FakeStat(ctimes), self.WIN, list(exclude), list(git_paths))

    def test_ctime_inside_and_outside(self):
        self.assertTrue(self.changed([("f.py", False)], {"/w/b/f.py": 105.0}))
        self.assertFalse(self.changed([("f.py", False)], {"/w/b/f.py": 99.0}))

    def test_deleted_uses_nearest_existing_ancestor(self):
        self.assertTrue(self.changed([("a/b/gone.py", True)], {"/w/b/a": 105.0}))
        self.assertFalse(self.changed([("a/b/gone.py", True)], {"/w/b/a": 50.0}))

    def test_git_state_paths(self):
        self.assertTrue(self.changed([], {"/r/.git/worktrees/b/logs/HEAD": 101.0},
                                     git_paths=["/r/.git/worktrees/b/logs/HEAD"]))
        self.assertFalse(self.changed([], {}, git_paths=["/r/.git/worktrees/b/index"]))

    def test_excluded_nested_worktree(self):
        self.assertFalse(self.changed([(".worktrees/x/f", False)], {"/w/b/.worktrees/x/f": 105.0},
                                      exclude=["/w/b/.worktrees/x"]))


class BgStoreTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.bg = observe.BgStore(self.dir)

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_add_take_once(self):
        self.bg.add("s1", "a1", "t1", 10.0, "sleep 3; echo > /w/b/f")
        self.assertEqual(self.bg.take("s1", "a1"), [{"start": 10.0, "command": "sleep 3; echo > /w/b/f"}])
        self.assertEqual(self.bg.take("s1", "a1"), [])
        self.assertEqual(self.bg.take("s1", "other"), [])

    def test_concurrent_adds_are_all_taken(self):
        threads = [threading.Thread(target=self.bg.add, args=("s", "a", f"t{i}", float(i), f"c{i}"))
                   for i in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        got = sorted(r["command"] for r in self.bg.take("s", "a"))
        self.assertEqual(got, [f"c{i}" for i in range(8)])

    def test_concurrent_takes_split_without_duplicates(self):
        for i in range(20):
            self.bg.add("s", "a", f"t{i}", float(i), f"c{i}")
        out = []
        threads = [threading.Thread(target=lambda: out.extend(self.bg.take("s", "a"))) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sorted(r["command"] for r in out), sorted(f"c{i}" for i in range(20)))

    def test_odd_ids_and_corrupt_files(self):
        self.bg.add("s/../x", "a b", "t:1", 1.0, "c")
        self.assertEqual(self.bg.take("s/../x", "a b"), [{"start": 1.0, "command": "c"}])
        d = self.bg.dir_for("s", "a")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "broken.json"), "w") as f:
            f.write("{not json")
        self.assertEqual(self.bg.take("s", "a"), [])

    def test_gc_drops_old_records(self):
        self.bg.add("s", "a", "t", 1.0, "c")
        self.bg.gc(time.time() + 7200)
        self.assertEqual(self.bg.take("s", "a"), [])

    def test_unwritable_dir_does_not_raise(self):
        bg = observe.BgStore("/nonexistent/forbidden/dir")
        bg.add("s", "a", "t", 1.0, "c")
        self.assertEqual(bg.take("s", "a"), [])
        bg.gc(time.time())


class RealGitChangedTest(unittest.TestCase):
    """Real repository + linked worktree: what each kind of write looks like to changed()."""

    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        g = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]
        self.repo, self.wt = os.path.join(self.tmp, "repo"), os.path.join(self.tmp, "wt")
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        with open(os.path.join(self.repo, "tracked.txt"), "w") as f:
            f.write("v1\n")
        subprocess.run(g + ["-C", self.repo, "add", "."], check=True)
        subprocess.run(g + ["-C", self.repo, "commit", "-q", "-m", "i"], check=True)
        subprocess.run(["git", "-C", self.repo, "worktree", "add", "-q", self.wt, "-b", "w"], check=True)
        self.g = g
        time.sleep(1.1)   # so the window below starts after the setup writes, even on 1 s timestamps

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def detect(self, action):
        start = time.time()
        action()
        win = observe.window(time.time(), (time.time() - start) * 1000, [])
        entries = observe.status_entries(self.wt, owners.git)
        return observe.changed(self.wt, entries, os.lstat, win, [], observe.git_state_paths(self.wt, owners.git))

    def sh(self, *args):
        subprocess.run(list(args), check=True, capture_output=True)

    def test_new_file(self):
        self.assertTrue(self.detect(lambda: open(os.path.join(self.wt, "new.txt"), "w").write("x")))

    def test_cp_p_keeps_old_mtime_but_is_seen(self):
        src = os.path.join(self.tmp, "src.txt")
        with open(src, "w") as f:
            f.write("from elsewhere\n")
        os.utime(src, (1_600_000_000, 1_600_000_000))
        self.assertTrue(self.detect(lambda: self.sh("cp", "-p", src, os.path.join(self.wt, "tracked.txt"))))

    def test_commit_leaves_status_clean_but_is_seen(self):
        def commit():
            with open(os.path.join(self.wt, "tracked.txt"), "a") as f:
                f.write("v2\n")
            self.sh(*self.g, "-C", self.wt, "commit", "-q", "-am", "c")
        self.assertTrue(self.detect(commit))

    def test_nothing_happened(self):
        self.assertFalse(self.detect(lambda: None))

    def test_change_before_the_window_is_not_counted(self):
        with open(os.path.join(self.wt, "early.txt"), "w") as f:
            f.write("x")
        time.sleep(1.1)
        self.assertFalse(self.detect(lambda: None))

    def test_restore_of_a_modified_file(self):
        with open(os.path.join(self.wt, "tracked.txt"), "a") as f:
            f.write("local edit\n")
        time.sleep(1.1)
        self.assertTrue(self.detect(lambda: self.sh("git", "-C", self.wt, "restore", "tracked.txt")))

    def test_missing_worktree_is_not_changed(self):
        shutil.rmtree(self.wt)
        win = observe.window(time.time(), 1000, [])
        self.assertEqual(observe.status_entries(self.wt, owners.git), [])
        self.assertFalse(observe.changed(self.wt, [], os.lstat, win, [], observe.git_state_paths(self.wt, owners.git)))


if __name__ == "__main__":
    unittest.main()
