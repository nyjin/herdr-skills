"""Tests for scripts/finalize-brief.py, run as a subprocess. Run from the repo root:
python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SCRIPT = os.path.join(os.path.dirname(HERE), "scripts", "finalize-brief.py")
TAIL = (
    "When the work is done, commit any changes you made to this branch, and end your final response "
    "with a `## Result` heading that covers the change summary, test results and open issues. "
    "Do not push or open a pull request."
)
NO_BRANCH_TAIL = (
    "When the work is done, end your final response with a `## Result` heading that covers what you did, "
    "test results and open issues. You have no branch of your own: do not commit, and change no file git tracks. "
    "Do not push or open a pull request."
)
BRIEF = "# [t] x\n\n## Goal\ndone\n"
ENV_ARGS = ["--role", "reviewer", "--worktree", "/w/a", "--branch", "b", "--outside", "/o/data", "shared output"]
ENV_BLOCK = (
    "## Environment\n\n"
    "- Role: reviewer\n"
    "- Worktree: `/w/a` (branch `b`)\n"
    "- Outside path: `/o/data` — shared output\n"
)


class FinalizeTest(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        self.brief = os.path.join(self.dir.name, "brief.md")

    def write(self, name, text):
        path = os.path.join(self.dir.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)
        return path

    def read(self, path=None):
        with open(path or self.brief, encoding="utf-8") as f:
            return f.read()

    def run_script(self, *args):
        return subprocess.run([sys.executable, SCRIPT, self.brief, *args], capture_output=True, text=True)

    def test_environment_follows_the_title(self):
        self.write("brief.md", BRIEF)
        r = self.run_script(*ENV_ARGS)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(), "# [t] x\n\n" + ENV_BLOCK + "\n## Goal\ndone\n\n" + TAIL + "\n")

    def test_rerun_replaces_sections(self):
        self.write("brief.md", BRIEF)
        then = self.write("then.md", "Run the tests.\n")
        for _ in range(2):
            r = self.run_script(*ENV_ARGS, "--then", then)
            self.assertEqual(r.returncode, 0, r.stderr)
        text = self.read()
        self.assertEqual(text.count("## Environment"), 1)
        self.assertEqual(text.count("## On completion"), 1)
        self.assertEqual(text.count(TAIL), 1)

    def test_on_completion_sits_before_the_closing_paragraph(self):
        self.write("brief.md", BRIEF)
        then = self.write("then.md", "Run the tests.\nThen report.\n\n")
        r = self.run_script("--then", then)
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.read()
        self.assertEqual(text.splitlines()[-1], TAIL)
        self.assertTrue(text.endswith("## On completion\n\nRun the tests.\nThen report.\n\n" + TAIL + "\n"), text)

    def test_relative_outside_path_fails(self):
        self.write("brief.md", BRIEF)
        r = self.run_script("--outside", "rel", "x")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(self.read(), BRIEF)

    def test_missing_or_empty_then_fails(self):
        self.write("brief.md", BRIEF)
        empty = self.write("empty.md", "\n")
        for then in (os.path.join(self.dir.name, "absent.md"), empty):
            r = self.run_script("--then", then)
            self.assertEqual(r.returncode, 1)
            self.assertEqual(self.read(), BRIEF)

    def test_no_options_keeps_todays_output(self):
        self.write("brief.md", "# [t] x\n\n<!-- guide -->\n## Goal\ndone\n\n\n## Notes\nmore\n\n" + TAIL + "\n")
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout, self.brief + "\n")
        self.assertEqual(self.read(), "# [t] x\n\n## Goal\ndone\n\n## Notes\nmore\n\n" + TAIL + "\n")

    def test_help_lists_every_option(self):
        r = subprocess.run([sys.executable, SCRIPT, "--help"], capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)
        for opt in ("--role", "--worktree", "--branch", "--workdir", "--outside", "--then"):
            self.assertIn(opt, r.stdout)

    def test_workdir_writes_the_line_and_the_no_commit_tail(self):
        self.write("brief.md", BRIEF)
        r = self.run_script("--role", "evaluator", "--workdir", "/w/eval")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.read(), "# [t] x\n\n## Environment\n\n- Role: evaluator\n"
                         "- Working directory: `/w/eval` (no worktree or branch of its own)\n\n## Goal\ndone\n\n"
                         + NO_BRANCH_TAIL + "\n")
        self.assertTrue(NO_BRANCH_TAIL.endswith("Do not push or open a pull request."))   # step 3's wait-output

    def test_rerun_keeps_one_no_commit_tail(self):
        self.write("brief.md", BRIEF)
        self.assertEqual(self.run_script("--workdir", "/w/eval").returncode, 0)
        r = self.run_script()
        self.assertEqual(r.returncode, 0, r.stderr)
        text = self.read()
        self.assertEqual(text.count(NO_BRANCH_TAIL), 1)
        self.assertNotIn(TAIL, text)

    def test_rerun_with_other_options_keeps_the_workdir(self):
        # dispatch.md adds outside paths on a rerun; the Environment is rewritten, the working directory stays
        self.write("brief.md", BRIEF)
        self.assertEqual(self.run_script("--workdir", "/w/eval").returncode, 0)
        for extra in (["--outside", "/o/x", "shared"], ["--role", "reviewer"]):
            with self.subTest(extra=extra):
                r = self.run_script(*extra)
                self.assertEqual(r.returncode, 0, r.stderr)
                text = self.read()
                self.assertIn("- Working directory: `/w/eval`", text)
                self.assertEqual(text.count(NO_BRANCH_TAIL), 1)
                self.assertNotIn(TAIL, text)

    def test_only_the_environment_section_marks_a_workdir_brief(self):
        self.write("brief.md", "# [t] x\n\n## Goal\ndone\n\n## Notes\n- Working directory: `/elsewhere` is mentioned\n")
        r = self.run_script("--worktree", "/w/a", "--branch", "b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.read().endswith(TAIL + "\n"))

    def test_a_branch_tail_gives_way_to_workdir(self):
        self.write("brief.md", BRIEF + "\n" + TAIL + "\n")
        self.assertEqual(self.run_script("--workdir", "/w/eval").returncode, 0)
        self.assertNotIn(TAIL, self.read())
        self.assertEqual(self.read().count(NO_BRANCH_TAIL), 1)

    def test_workdir_with_worktree_is_refused(self):
        self.write("brief.md", BRIEF)
        for extra in (["--worktree", "/w/a"], ["--branch", "b"]):
            with self.subTest(extra=extra):
                r = self.run_script("--workdir", "/w/eval", *extra)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(self.read(), BRIEF)

    def test_replacement_keeps_the_next_section(self):
        self.write("brief.md", "# [t] x\n\n## Environment\n\n- Role: old\n\n## Goal\ndone\n\n## On completion\nold\n\n## Notes\nn\n")
        then = self.write("then.md", "new")
        r = self.run_script("--role", "new", "--then", then)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(
            self.read(),
            "# [t] x\n\n## Environment\n\n- Role: new\n\n## Goal\ndone\n\n## Notes\nn\n\n## On completion\n\nnew\n\n" + TAIL + "\n",
        )


if __name__ == "__main__":
    unittest.main()
