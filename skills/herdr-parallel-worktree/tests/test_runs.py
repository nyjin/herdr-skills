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

# A fake herdr: logs every call to $CALLS; `pane get` reports a claude session whose id comes from the pane id and
# the tab `<ws>:t<n>` for pane `<ws>:p<n>` (pane_not_found for panes listed in $CLOSED); `tab get` reports
# focused for tabs listed in $FOCUSED_TABS; `workspace get` an unfocused, idle workspace.
FAKE_HERDR = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps(args) + "\n")
def out(result):
    print(json.dumps({"id": "x", "result": result})); sys.exit(0)
def err(code):
    print(json.dumps({"id": "x", "error": {"code": code}}), file=sys.stderr); sys.exit(1)
cmd = args[:2]
if cmd == ["pane", "get"]:
    pane = args[2]
    if pane in os.environ.get("CLOSED", "").split():
        err("pane_not_found")
    ws, _, n = pane.partition(":p")
    out({"pane": {"pane_id": pane, "tab_id": f"{ws}:t{n}", "workspace_id": ws,
                  "agent_session": {"agent": "claude", "kind": "id", "source": "herdr:claude", "value": f"sess-{pane}"}}})
if cmd == ["tab", "get"]:
    out({"tab": {"tab_id": args[2], "agent_status": "idle",
                 "focused": args[2] in os.environ.get("FOCUSED_TABS", "").split()}})
if cmd == ["workspace", "get"]:
    out({"workspace": {"workspace_id": args[2], "agent_status": "idle", "focused": False}})
if cmd == ["worktree", "list"]:
    out({"worktrees": []})
err("unsupported")
'''


class RunsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.repo = os.path.join(self.tmp, "repo")
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, "herdr"), "w") as f:
            f.write(FAKE_HERDR.replace("/usr/bin/env python3", sys.executable, 1))
        os.chmod(os.path.join(bin_dir, "herdr"), 0o755)
        self.calls_file = os.path.join(self.tmp, "calls.jsonl")
        self.env = dict(os.environ, HERDR_SKILLS_DATA_HOME=os.path.join(self.tmp, "data"), CALLS=self.calls_file,
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

    def add(self, name="w1", pane="w1:p1", *extra):
        return self.runs("add", "--name", name, "--root", self.repo, "--branch", "b", "--base", "abc",
                         "--from-branch", "main", "--worktree", os.path.join(self.tmp, name), "--workspace", "w1",
                         "--pane", pane, *extra)

    def git(self, *args):
        return subprocess.run(["git", "-C", self.repo, *args], capture_output=True, text=True, check=True).stdout.strip()

    def tab_worker(self, name="t1", pane="w1:p5"):
        """A clean linked worktree with no commits of its own, recorded as a tab worker in workspace w1."""
        self.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
        base = self.git("rev-parse", "HEAD")
        wt = os.path.join(self.tmp, name)
        self.git("worktree", "add", "-q", "-b", name, wt, base)
        self.runs("add", "--name", name, "--root", self.repo, "--branch", name, "--base", base, "--from-branch",
                  "main", "--worktree", wt, "--workspace", "w1", "--pane", pane, "--placement", "tab")
        return wt

    def scan(self, **env):
        r = subprocess.run([sys.executable, RUNS_PY, "scan", "--root", self.repo], capture_output=True, text=True,
                           env=dict(self.env, **env))
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)

    def called(self, *prefix):
        if not os.path.exists(self.calls_file):
            return []
        with open(self.calls_file) as f:
            calls = [json.loads(line) for line in f if line.strip()]
        return [c for c in calls if c[:len(prefix)] == list(prefix)]

    def test_add_records_placement_default_workspace(self):
        self.assertEqual(self.add()["placement"], "workspace")

    def test_add_records_tab_placement(self):
        self.assertEqual(self.add("w1", "w1:p1", "--placement", "tab")["placement"], "tab")
        self.assertEqual(self.runs("show", "--root", self.repo, "--name", "w1")[0]["placement"], "tab")

    def test_scan_tab_worker_is_judged_by_its_tab(self):
        wt = self.tab_worker()
        out = self.scan()
        self.assertEqual([c["name"] for c in out["candidates"]], ["t1"], out)
        c = out["candidates"][0]
        root = self.git("rev-parse", "--show-toplevel")
        self.assertEqual(c["remove_command"], f"git -C {root} worktree remove {wt} && herdr tab close w1:t5")
        self.assertEqual((c["placement"], c["tab"], c["tab_open"]), ("tab", "w1:t5", True))
        self.assertEqual(self.called("workspace", "get"), [])

    def test_scan_closed_tab_removes_only_the_worktree(self):
        wt = self.tab_worker()
        c = self.scan(CLOSED="w1:p5")["candidates"][0]
        root = self.git("rev-parse", "--show-toplevel")
        self.assertEqual(c["remove_command"], f"git -C {root} worktree remove {wt}")
        self.assertFalse(c["tab_open"])

    def test_scan_focused_tab_is_kept(self):
        self.tab_worker()
        out = self.scan(FOCUSED_TABS="w1:t5")
        self.assertEqual(out["candidates"], [])
        self.assertIn("user is viewing this tab", out["keep"][0]["reasons"])

    def test_record_without_placement_scans_as_workspace(self):
        self.tab_worker()
        path = os.path.join(self.tmp, "data", "herdr-parallel-worktree", "runs.json")
        with open(path) as f:
            runs = json.load(f)
        del runs[0]["placement"]                                       # a record written before 0.9.0
        with open(path, "w") as f:
            json.dump(runs, f)
        c = self.scan()["candidates"][0]
        self.assertTrue(c["remove_command"].startswith("herdr worktree remove --workspace w1"), c)
        self.assertEqual(c["placement"], "workspace")
        self.assertTrue(self.called("workspace", "get"))

    def test_relocate_and_mark_open_take_placement(self):
        self.add()
        self.assertEqual(self.runs("relocate", "--root", self.repo, "--name", "w1", "--workspace", "w2", "--pane",
                                   "w2:p1", "--placement", "tab")["placement"], "tab")
        self.assertEqual(self.runs("relocate", "--root", self.repo, "--name", "w1", "--workspace", "w2", "--pane",
                                   "w2:p1")["placement"], "tab")                      # kept when not given
        self.runs("mark-cleaned", "--root", self.repo, "--name", "w1")
        self.assertEqual(self.runs("mark-open", "--root", self.repo, "--name", "w1", "--workspace", "w3", "--pane",
                                   "w3:p2", "--placement", "workspace")["placement"], "workspace")

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
