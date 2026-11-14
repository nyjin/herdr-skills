import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
GLOWP = os.path.join(HERE, "..", "scripts", "glowp.py")
FAKE = os.path.join(HERE, "fake_herdr.py")
SRC = "w1:p1"


class GlowpTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = os.path.realpath(self.tmp.name)
        self.state = os.path.join(root, "state")
        self.log = os.path.join(root, "calls.jsonl")
        self.repo = os.path.join(root, "repo")
        os.makedirs(os.path.join(self.repo, "docs"))
        self.doc = os.path.join(self.repo, "docs", "a.md")
        open(self.doc, "w").close()
        self.env = dict(os.environ, GLOWP_HERDR=f"{sys.executable} {FAKE}", FAKE_LOG=self.log,
                        GLOWP_STATE_DIR=self.state, HERDR_PANE_ID=SRC,
                        HOME=os.path.join(root, "home"), FAKE_PANES="[]",
                        FAKE_PANE=json.dumps({"pane_id": SRC, "foreground_cwd": self.repo}))
        self.env.pop("HERDR_PLUGIN_CLICKED_URL", None)

    def tearDown(self):
        self.tmp.cleanup()

    def run_glowp(self, *args, env_extra=None):
        return subprocess.run([sys.executable, GLOWP, *args], env=dict(self.env, **(env_extra or {})),
                              capture_output=True, text=True, timeout=30)

    def click(self, text):
        return self.run_glowp("link", env_extra={"HERDR_PLUGIN_CLICKED_URL": text})

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def opens(self):
        return [c for c in self.calls() if c[:3] == ["plugin", "pane", "open"]]

    def state_paths(self):
        p = os.path.join(self.state, SRC + ".json")
        if not os.path.exists(p):
            return None
        with open(p) as f:
            return [i.get("path") or i.get("url") for i in json.load(f)["items"]]

    def test_click_opens_viewer(self):
        r = self.click(self.doc)
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.state_paths(), [self.doc])
        [call] = self.opens()
        for flag, value in [("--target-pane", SRC), ("--direction", "right"), ("--placement", "split"),
                            ("--env", f"GLOWP_SOURCE={SRC}")]:
            self.assertEqual(call[call.index(flag) + 1], value)
        self.assertIn("--no-focus", call)

    def test_no_hook_entry_point(self):
        r = self.run_glowp("hook")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(self.calls(), [])

    def test_click_outside_herdr_does_nothing(self):
        del self.env["HERDR_PANE_ID"]
        self.click(self.doc)
        self.assertEqual(self.calls(), [])

    def test_reuses_live_viewer(self):
        os.makedirs(self.state)
        with open(os.path.join(self.state, SRC + ".viewer"), "w") as f:
            f.write("w1:p9")
        self.env["FAKE_PANES"] = json.dumps([{"pane_id": SRC}, {"pane_id": "w1:p9"}])
        self.click(self.doc)
        self.assertEqual(self.opens(), [])
        self.assertEqual(self.state_paths(), [self.doc])

    def test_reopens_when_viewer_gone(self):
        os.makedirs(self.state)
        with open(os.path.join(self.state, SRC + ".viewer"), "w") as f:
            f.write("w1:p9")
        self.env["FAKE_PANES"] = json.dumps([{"pane_id": SRC}])
        self.click(self.doc)
        self.assertEqual(len(self.opens()), 1)

    def test_concurrent_clicks_open_one_viewer(self):
        env = dict(self.env, HERDR_PLUGIN_CLICKED_URL=self.doc)
        procs = [subprocess.Popen([sys.executable, GLOWP, "link"], env=env) for _ in range(4)]
        for p in procs:
            p.wait()
        self.assertEqual(len(self.opens()), 1)
        with open(os.path.join(self.state, SRC + ".viewer")) as f:
            self.assertTrue(f.read().startswith("w1:v"))

    def test_link_not_found_notifies(self):
        self.env["HERDR_PLUGIN_CLICKED_URL"] = "nowhere/missing.md"
        r = self.run_glowp("link")
        self.assertEqual(r.returncode, 0)
        self.assertTrue(any(c[:2] == ["notification", "show"] for c in self.calls()))
        self.assertIsNone(self.state_paths())

    def test_link_resolves_relative(self):
        self.env["HERDR_PLUGIN_CLICKED_URL"] = "docs/a.md:3"
        self.run_glowp("link")
        self.assertEqual(self.state_paths(), [self.doc])

    def test_link_url_item(self):
        url = "https://example.atlassian.net/browse/ABC-1"
        self.env["HERDR_PLUGIN_CLICKED_URL"] = url
        self.run_glowp("link")
        self.assertEqual(self.state_paths(), [url])
        self.assertFalse(any(c[:2] == ["pane", "get"] for c in self.calls()))

    def test_link_other_web_url_is_not_resolved(self):
        self.env["GLOWP_OPEN"] = "true"
        self.env["HERDR_PLUGIN_CLICKED_URL"] = "https://github.com/o/r/blob/main/README.md"
        r = self.run_glowp("link")
        self.assertEqual(r.returncode, 0)
        self.assertIsNone(self.state_paths())
        self.assertFalse(any(c[:2] in (["pane", "get"], ["notification", "show"]) for c in self.calls()))

    def test_link_source_line(self):
        src = os.path.join(self.repo, "docs", "b.py")
        open(src, "w").close()
        self.env["HERDR_PLUGIN_CLICKED_URL"] = "docs/b.py:7"
        self.run_glowp("link")
        with open(os.path.join(self.state, SRC + ".json")) as f:
            self.assertEqual(json.load(f)["items"], [{"path": src, "line": 7}])

    def test_toggle_from_viewer_pane(self):
        self.click(self.doc)
        with open(os.path.join(self.state, SRC + ".viewer"), "w") as f:
            f.write("w1:p9")
        mode = os.path.join(self.state, SRC + ".mode")
        with open(os.path.join(self.state, SRC + ".json")) as f:
            seq = json.load(f)["seq"]
        self.env["HERDR_PANE_ID"] = "w1:p9"
        self.run_glowp("toggle")
        with open(mode) as f:
            self.assertEqual(f.read(), "source")
        with open(os.path.join(self.state, SRC + ".json")) as f:
            st = json.load(f)
        self.assertNotEqual(st["seq"], seq)
        self.assertTrue(st["toggle"])
        self.run_glowp("toggle")
        with open(mode) as f:
            self.assertEqual(f.read(), "rendered")

    def test_link_ambiguous_writes_all(self):
        other = os.path.join(self.repo, "other")
        os.makedirs(other)
        open(os.path.join(other, "a.md"), "w").close()
        subprocess.run(["git", "init", "-q", self.repo], check=True)
        self.env["HERDR_PLUGIN_CLICKED_URL"] = "a.md"
        self.run_glowp("link")
        self.assertEqual(len(self.state_paths()), 2)


if __name__ == "__main__":
    unittest.main()
