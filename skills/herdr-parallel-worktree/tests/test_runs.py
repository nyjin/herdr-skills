"""Tests for scripts/runs.py's registry commands, with a temporary DATA_DIR and a fake `herdr` on PATH.
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
RUNS_PY = os.path.join(os.path.dirname(HERE), "scripts", "runs.py")

FAKE_HERDR = """#!/bin/sh
# pane get <id>: report a claude session whose id is derived from the pane id
if [ "$1" = pane ] && [ "$2" = get ]; then
  printf '{"id":"x","result":{"pane":{"pane_id":"%s","agent_session":{"agent":"claude","kind":"id","source":"herdr:claude","value":"sess-%s"}}}}' "$3" "$3"
  exit 0
fi
printf '{"id":"x","error":{"code":"unsupported"}}' >&2
exit 1
"""


class RunsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, "herdr"), "w") as f:
            f.write(FAKE_HERDR)
        os.chmod(os.path.join(bin_dir, "herdr"), 0o755)
        self.env = dict(os.environ, HERDR_SKILLS_DATA_HOME=os.path.join(self.tmp, "data"),
                        PATH=bin_dir + os.pathsep + os.environ["PATH"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def runs(self, *args, ok=True):
        r = subprocess.run([sys.executable, RUNS_PY, *args], capture_output=True, text=True, env=self.env)
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        self.assertEqual(r.returncode, 1)
        return r.stderr

    def add(self, name="w1", pane="w1:p1"):
        return self.runs("add", "--name", name, "--root", self.repo, "--branch", "b", "--base", "abc",
                         "--from-branch", "main", "--worktree", os.path.join(self.tmp, name), "--workspace", "w1",
                         "--pane", pane)

    def test_relocate_updates_an_open_run_whose_workspace_moved(self):
        self.add()
        r = self.runs("relocate", "--root", self.repo, "--name", "w1", "--workspace", "w24", "--pane", "w24:p1")
        self.assertEqual((r["state"], r["workspace"], r["pane"], r["session_id"]),
                         ("open", "w24", "w24:p1", "sess-w24:p1"))
        shown = self.runs("show", "--root", self.repo, "--name", "w1")
        self.assertEqual([(x["workspace"], x["pane"]) for x in shown], [("w24", "w24:p1")])

    def test_relocate_needs_an_open_run(self):
        self.assertIn("no open run named nope", self.runs("relocate", "--root", self.repo, "--name", "nope",
                                                          "--workspace", "w2", "--pane", "w2:p1", ok=False))
        self.add()
        self.runs("mark-cleaned", "--root", self.repo, "--name", "w1")
        self.assertIn("no open run named w1", self.runs("relocate", "--root", self.repo, "--name", "w1",
                                                        "--workspace", "w2", "--pane", "w2:p1", ok=False))

    def test_mark_open_still_only_reopens_cleaned_runs(self):
        self.add()
        self.assertIn("no cleaned run named w1", self.runs("mark-open", "--root", self.repo, "--name", "w1",
                                                           "--workspace", "w2", "--pane", "w2:p1", ok=False))


if __name__ == "__main__":
    unittest.main()
