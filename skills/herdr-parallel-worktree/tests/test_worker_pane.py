"""Tests for scripts/worker-pane.py, with a scripted fake `herdr` on PATH.
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
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "worker-pane.py")

# Answers come from $FAKE/plan.json: {"logs": [[...], [...]], "ready": [false, true]}. Each `plugin log list`
# pops the next logs snapshot (the last one repeats), each `pane process-info` the next readiness.
FAKE = r'''#!/usr/bin/env python3
import json, os, sys
d = os.environ["FAKE"]
args = sys.argv[1:]
with open(os.path.join(d, "calls.jsonl"), "a") as f:
    f.write(json.dumps(args) + "\n")
with open(os.path.join(d, "plan.json")) as f:
    plan = json.load(f)
def pop(key):
    seq = plan[key]
    v = seq.pop(0) if len(seq) > 1 else seq[0]
    with open(os.path.join(d, "plan.json"), "w") as f:
        json.dump(plan, f)
    return v
if args[:3] == ["plugin", "log", "list"]:
    logs = pop("logs")
    if logs == "unsupported":   # an older herdr without plugin logs: clap rejects the subcommand
        print("error: unrecognized subcommand 'plugin'", file=sys.stderr); sys.exit(2)
    if logs == "error":
        print(json.dumps({"error": {"code": "server_unavailable"}}), file=sys.stderr); sys.exit(1)
    print(json.dumps({"result": {"logs": logs}})); sys.exit(0)
if args[:2] == ["tab", "create"]:
    if plan.get("tab_error"):
        print(json.dumps({"error": {"code": "workspace_not_found"}}), file=sys.stderr); sys.exit(1)
    print(json.dumps({"result": {"tab": {"tab_id": "w1:t9"}, "root_pane": {"pane_id": "w1:p9"}}})); sys.exit(0)
if args[:2] == ["pane", "process-info"]:
    ready = pop("ready")   # true: only the shell; "hook": a prompt hook in the shell's group; false: a program
    procs = [{"pid": 10, "name": "zsh"}] + ([{"pid": 12, "name": "mise"}] if ready == "hook" else [])
    print(json.dumps({"result": {"process_info": {"shell_pid": 10, "foreground_process_group_id": 11 if ready is False else 10,
                                                  "foreground_processes": procs if ready is not False else [{"pid": 11, "name": "claude"}]}}}))
    sys.exit(0)
print(json.dumps({"error": {"code": "unsupported"}}), file=sys.stderr); sys.exit(1)
'''


def log(plugin, status, started=2000, event="worktree.created"):
    return {"plugin_id": plugin, "event": event, "status": status, "started_unix_ms": started,
            "finished_unix_ms": None if status == "running" else started + 500}


class WorkerPaneTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, "herdr"), "w") as f:
            f.write(FAKE)
        os.chmod(os.path.join(bin_dir, "herdr"), 0o755)
        self.env = dict(os.environ, FAKE=self.tmp, PATH=bin_dir + os.pathsep + os.environ["PATH"])

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_script(self, logs, ready=(True,), tab_error=False):
        with open(os.path.join(self.tmp, "plan.json"), "w") as f:
            json.dump({"logs": logs, "ready": list(ready), "tab_error": tab_error}, f)
        r = subprocess.run([sys.executable, SCRIPT, "--workspace", "w1", "--worktree", "/wt", "--name", "proj-1",
                            "--since", "1000", "--poll-ms", "10", "--quiet-ms", "50", "--timeout-ms", "400"],
                           capture_output=True, text=True, env=self.env)
        return r.returncode, json.loads(r.stdout) if r.stdout.strip() else None, r.stderr

    def calls(self):
        with open(os.path.join(self.tmp, "calls.jsonl")) as f:
            return [json.loads(line) for line in f]

    def tab_create(self):
        return [c for c in self.calls() if c[:2] == ["tab", "create"]]

    def test_waits_for_running_handlers_then_creates_the_tab(self):
        rc, out, err = self.run_script([[log("a", "running"), log("b", "running")],
                                        [log("a", "succeeded"), log("b", "running")],
                                        [log("a", "succeeded"), log("b", "failed")]])
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["settled"])
        self.assertEqual(out["pane"], "w1:p9")
        self.assertEqual(sorted(h["plugin"] for h in out["handlers"]), ["a", "b"])
        names = [c[:3] if c[0] == "plugin" else c[:2] for c in self.calls()]
        self.assertLess(max(i for i, c in enumerate(names) if c == ["plugin", "log", "list"]),
                        names.index(["tab", "create"]))

    def test_a_handler_that_appears_after_another_finished_is_waited_for(self):
        # two plugins: the first finishes before the second shows up in the log
        rc, out, err = self.run_script([[log("a", "succeeded")],
                                        [log("a", "succeeded"), log("b", "running")],
                                        [log("a", "succeeded"), log("b", "running")],
                                        [log("a", "succeeded"), log("b", "succeeded")]])
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["settled"])
        self.assertEqual(sorted(h["plugin"] for h in out["handlers"]), ["a", "b"])

    def test_older_herdr_without_plugin_logs_has_nothing_to_wait_for(self):
        rc, out, err = self.run_script(["unsupported"])
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["settled"])
        self.assertEqual(out["handlers"], [])

    def test_a_failing_log_query_is_not_read_as_no_plugins(self):
        rc, out, err = self.run_script(["error"])
        self.assertEqual(rc, 0, err)
        self.assertFalse(out["settled"])
        self.assertIn("server_unavailable", out["log_error"])
        self.assertEqual(len(self.tab_create()), 1)

    def test_a_passing_log_error_does_not_stick(self):
        rc, out, err = self.run_script(["error", [log("a", "succeeded")]])
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["settled"])
        self.assertIsNone(out["log_error"])

    def test_tab_carries_the_worker_variable_cwd_and_label(self):
        rc, out, err = self.run_script([[log("a", "succeeded")]])
        self.assertEqual(rc, 0, err)
        tab = self.tab_create()[0]
        self.assertIn("HERDR_PW_WORKER=proj-1", tab)
        self.assertEqual(tab[tab.index("--workspace") + 1], "w1")
        self.assertEqual(tab[tab.index("--cwd") + 1], "/wt")
        self.assertEqual(tab[tab.index("--label") + 1], "proj-1")
        self.assertIn("--no-focus", tab)

    def test_no_plugins_settles_after_the_quiet_window(self):
        rc, out, err = self.run_script([[]])
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["settled"])
        self.assertEqual(out["handlers"], [])

    def test_ignores_handlers_from_before_since_and_other_events(self):
        rc, out, err = self.run_script([[log("old", "running", started=500), log("x", "running", event="tab.focused")]])
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["handlers"], [])

    def test_counts_worktree_opened_too(self):
        rc, out, err = self.run_script([[log("a", "running", event="worktree.opened")],
                                        [log("a", "succeeded", event="worktree.opened")]])
        self.assertEqual(rc, 0, err)
        self.assertEqual([h["plugin"] for h in out["handlers"]], ["a"])

    def test_timeout_still_creates_the_tab_and_names_the_running_handler(self):
        rc, out, err = self.run_script([[log("slow", "running")]])
        self.assertEqual(rc, 0, err)
        self.assertFalse(out["settled"])
        self.assertEqual(out["still_running"], ["slow"])
        self.assertEqual(len(self.tab_create()), 1)

    def test_waits_until_the_new_shell_is_idle_twice_in_a_row(self):
        rc, out, err = self.run_script([[]], (False, True, False, True, True))
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["shell_ready"])
        self.assertEqual(sum(c[:2] == ["pane", "process-info"] for c in self.calls()), 5)

    def test_a_prompt_hook_in_the_shells_group_is_not_idle(self):
        # measured: `mise` from the prompt hook shares the shell's group, and herdr then answers agent_pane_busy
        rc, out, err = self.run_script([[]], ("hook", "hook", True, True))
        self.assertEqual(rc, 0, err)
        self.assertTrue(out["shell_ready"])
        self.assertEqual(sum(c[:2] == ["pane", "process-info"] for c in self.calls()), 4)

    def test_shell_never_ready_is_reported_not_hidden(self):
        rc, out, err = self.run_script([[]], (False,))
        self.assertEqual(rc, 0, err)
        self.assertFalse(out["shell_ready"])

    def test_herdr_error_on_tab_create_fails(self):
        rc, out, err = self.run_script([[]], tab_error=True)
        self.assertEqual(rc, 1)
        self.assertIn("workspace_not_found", err)


if __name__ == "__main__":
    unittest.main()
