"""Tests for scripts/place.py, with a scripted fake `herdr` on PATH and a real git repository.
Run from the repo root: python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "place.py")

# Answers come from $FAKE/plan.json: {"keys": {ws: repo_key}, "source": ws or null, "fail": ["worktree list", ...]}.
# Every call is appended to $FAKE/calls.jsonl.
FAKE = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(args) + "\n")
with open(os.path.join(d, "plan.json")) as f:
    plan = json.load(f)
cmd = " ".join(args[:2])
def opt(name):
    return args[args.index(name) + 1] if name in args[:-1] else None
if cmd in plan.get("fail", []):
    print(json.dumps({"error": {"code": "server_unavailable", "message": "no server"}}), file=sys.stderr); sys.exit(1)
if cmd == "worktree list":
    src = {"repo_key": plan["repo_key"], "repo_name": "repo", "repo_root": opt("--cwd")}
    if plan.get("source"):
        src["source_workspace_id"] = plan["source"]
    print(json.dumps({"result": {"source": src, "worktrees": []}})); sys.exit(0)
if cmd == "workspace get":
    ws = {"workspace_id": args[2]}
    if args[2] in plan.get("keys", {}):
        ws["worktree"] = {"repo_key": plan["keys"][args[2]]}
    print(json.dumps({"result": {"workspace": ws}})); sys.exit(0)
if cmd == "worktree create":
    path = opt("--path") or "/herdr/default/" + opt("--branch").replace("/", "-")
    print(json.dumps({"result": {"workspace": {"workspace_id": "w9"}, "worktree": {"path": path}}})); sys.exit(0)
if cmd == "worktree open":
    print(json.dumps({"result": {"workspace": {"workspace_id": "w9"}, "already_open": False}})); sys.exit(0)
print(json.dumps({"error": {"code": "not_supported"}}), file=sys.stderr); sys.exit(1)
'''


class PlaceTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", "-b", "main", self.repo], check=True)
        subprocess.run(["git", "-C", self.repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q",
                        "--allow-empty", "-m", "init"], check=True)
        self.sha = self.git("rev-parse", "HEAD")
        self.key = os.path.join(self.repo, ".git")
        self.fake = os.path.join(self.tmp, "fake")
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(self.fake)
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, "herdr"), "w") as f:
            f.write(FAKE.replace("/usr/bin/env python3", sys.executable, 1))
        os.chmod(os.path.join(bin_dir, "herdr"), 0o755)
        self.home = os.path.join(self.tmp, "home")
        self.env = dict(os.environ, FAKE=self.fake, HOME=self.home, HERDR_WORKSPACE_ID="w1",
                        PATH=bin_dir + os.pathsep + os.environ["PATH"])
        self.plan()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True, check=True).stdout.strip()

    def plan(self, keys=None, source=None, fail=()):
        with open(os.path.join(self.fake, "plan.json"), "w") as f:
            json.dump({"repo_key": self.key, "keys": keys or {}, "source": source, "fail": list(fail)}, f)

    def calls(self):
        path = os.path.join(self.fake, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]

    def place(self, *args, ok=True, env=None):
        r = subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True, env=env or self.env)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        self.assertEqual(r.returncode, 1, r.stdout)
        return r.stderr

    def new(self, *extra, ok=True):
        return self.place("worktree", "--root", self.repo, "--name", "n1", "--branch", "b1", "--base", self.sha,
                          *extra, ok=ok)

    def worktrees(self):
        return self.git("worktree", "list", "--porcelain")

    def creates(self):
        return [c for c in self.calls() if c[:2] == ["worktree", "create"]]

    def test_worktree_in_the_current_space(self):
        self.plan(keys={"w1": self.key})
        out = self.new()
        self.assertEqual(self.creates(), [["worktree", "create", "--workspace", "w1", "--branch", "b1", "--base",
                                           self.sha, "--label", "n1", "--no-focus"]])
        self.assertEqual((out["placement"], out["space"], out["workspace"], out["why"]),
                         ("workspace", "w1", "w9", "current"))
        self.assertEqual(out["worktree"], "/herdr/default/b1")
        self.assertIsInstance(out["since"], int)

    def test_worktree_under_the_space_herdr_knows(self):
        self.plan(keys={"w1": "/other/.git"}, source="w7")
        out = self.new()
        self.assertEqual(self.creates()[0][2:4], ["--workspace", "w7"])
        self.assertEqual((out["placement"], out["space"], out["why"]), ("workspace", "w7", "repo-space"))

    def test_worktree_as_a_tab_when_no_space(self):
        self.plan(keys={"w1": "/other/.git"})
        wt = os.path.join(self.tmp, "wt-b1")
        out = self.new("--path", wt)
        self.assertEqual(self.creates(), [])
        self.assertIn(f"worktree {wt}\n", self.worktrees())
        self.assertIn("branch refs/heads/b1", self.worktrees())
        self.assertEqual((out["placement"], out["space"], out["workspace"], out["worktree"], out["why"]),
                         ("tab", "w1", "w1", wt, "none"))

    def test_tab_default_path_follows_herdr(self):
        out = self.place("worktree", "--root", self.repo, "--name", "n1", "--branch", "feat/x", "--base", self.sha)
        self.assertEqual(out["worktree"], os.path.join(self.home, ".herdr", "worktrees", "repo", "feat-x"))
        self.assertTrue(os.path.isdir(out["worktree"]))

    def test_tab_existing_branch_is_checked_out(self):
        self.git("branch", "b2")
        wt = os.path.join(self.tmp, "wt-b2")
        out = self.place("worktree", "--root", self.repo, "--name", "n2", "--branch", "b2", "--existing",
                         "--path", wt)
        self.assertEqual(out["placement"], "tab")
        self.assertEqual(self.git("-C", wt, "branch", "--show-current"), "b2")
        self.assertEqual(self.git("for-each-ref", "--format=%(refname:short)", "refs/heads/"), "b2\nmain")

    def test_existing_branch_in_a_space_passes_no_base(self):
        self.git("branch", "b2")
        self.plan(source="w7")
        self.place("worktree", "--root", self.repo, "--name", "n2", "--branch", "b2", "--existing",
                   "--path", os.path.join(self.tmp, "wt-b2"))
        self.assertNotIn("--base", self.creates()[0])

    def test_an_existing_branch_is_refused_in_a_space_too(self):
        # herdr would check the old branch out; a new worker must not start on an old branch's commits
        self.git("branch", "b1")
        self.plan(source="w7")
        self.assertIn("b1", self.new(ok=False))
        self.assertEqual(self.creates(), [])

    def test_existing_needs_the_branch(self):
        for source in ("w7", None):
            with self.subTest(source=source):
                self.plan(source=source)
                self.assertIn("nope", self.place("worktree", "--root", self.repo, "--name", "n1", "--branch", "nope",
                                                 "--existing", ok=False))
                self.assertEqual(self.creates(), [])
                self.assertEqual(self.git("for-each-ref", "--format=%(refname:short)", "refs/heads/"), "main")

    def test_occupied_path_is_refused(self):
        wt = os.path.join(self.tmp, "busy")
        os.makedirs(wt)
        open(os.path.join(wt, "keep.txt"), "w").close()
        self.assertIn(wt, self.new("--path", wt, ok=False))
        self.assertNotIn(wt, self.worktrees())
        self.assertEqual(self.git("branch", "--list", "b1"), "")

    def test_relative_path_resolves_against_root(self):
        out = self.new("--path", ".worktrees/b1")
        self.assertEqual(out["worktree"], os.path.join(self.repo, ".worktrees", "b1"))
        self.plan(source="w7")
        self.place("worktree", "--root", self.repo, "--name", "n3", "--branch", "b3", "--base", self.sha,
                   "--path", ".worktrees/b3")
        self.assertIn(os.path.join(self.repo, ".worktrees", "b3"), self.creates()[0])

    def test_herdr_error_creates_nothing(self):
        self.plan(fail=["worktree list"])
        before = self.worktrees()
        self.assertIn("herdr", self.new(ok=False))
        self.assertEqual(self.worktrees(), before)
        self.assertEqual(self.git("branch", "--list", "b1"), "")

    def test_herdr_create_error_is_reported(self):
        self.plan(source="w7", fail=["worktree create"])
        self.assertIn("server_unavailable", self.new(ok=False))

    def test_trust_repository_is_passed_only_when_asked(self):
        self.plan(source="w7")
        self.new("--trust-repository")
        self.assertIn("--trust-repository", self.creates()[0])

    def test_reopen_tab_opens_nothing(self):
        wt = os.path.join(self.tmp, "wt")
        os.makedirs(wt)
        out = self.place("reopen", "--root", self.repo, "--name", "n1", "--worktree", wt)
        self.assertEqual([c for c in self.calls() if c[:2] == ["worktree", "open"]], [])
        self.assertEqual((out["placement"], out["workspace"], out["worktree"]), ("tab", "w1", wt))

    def test_reopen_workspace_opens_under_the_space(self):
        self.plan(source="w7")
        wt = os.path.join(self.tmp, "wt")
        os.makedirs(wt)
        out = self.place("reopen", "--root", self.repo, "--name", "n1", "--worktree", wt)
        self.assertIn(["worktree", "open", "--workspace", "w7", "--path", wt, "--label", "n1", "--no-focus"],
                      self.calls())
        self.assertEqual((out["placement"], out["space"], out["workspace"]), ("workspace", "w7", "w9"))

    def test_reopen_needs_the_worktree(self):
        self.place("reopen", "--root", self.repo, "--name", "n1", "--worktree", os.path.join(self.tmp, "gone"),
                   ok=False)

    def test_where_outside_git_is_a_tab_here(self):
        outside = os.path.join(self.tmp, "plain")
        os.makedirs(outside)
        self.assertEqual(self.place("where", "--dir", outside),
                         {"placement": "tab", "space": "w1", "why": "outside git"})

    def test_where_inside_a_repository(self):
        self.plan(source="w7")
        sub = os.path.join(self.repo, "sub")
        os.makedirs(sub)
        self.assertEqual(self.place("where", "--dir", sub), {"placement": "workspace", "space": "w7",
                                                            "why": "repo-space"})
        self.plan()
        self.assertEqual(self.place("where", "--dir", sub)["placement"], "tab")

    def test_missing_workspace_id_fails(self):
        env = dict(self.env)
        del env["HERDR_WORKSPACE_ID"]
        self.assertIn("HERDR_WORKSPACE_ID", self.place("where", "--dir", self.repo, ok=False, env=env))
        self.assertEqual(self.calls(), [])


if __name__ == "__main__":
    unittest.main()
