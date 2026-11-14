"""scripts/check.sh gives the same answer inside a herdr worker tab as outside it: the hook checks build their own
callers, so the worker variable the tab's shell carries must not leak into them.
Run from the repo root: python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import os
import subprocess
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


class CheckScriptTest(unittest.TestCase):
    def test_hooks_check_passes_inside_a_worker(self):
        env = dict(os.environ, HERDR_PW_WORKER="probe", HERDR_WORKSPACE_ID="w1")
        r = subprocess.run(["bash", os.path.join(REPO, "scripts", "check.sh"), "hooks"], capture_output=True,
                           text=True, env=env, cwd=REPO)
        self.assertEqual(r.returncode, 0, r.stdout[-500:] + r.stderr[-500:])


if __name__ == "__main__":
    unittest.main()
