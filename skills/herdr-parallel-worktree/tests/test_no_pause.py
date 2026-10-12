"""Once this skill is in use, workers start without a question; what the user should know comes in the report after
they start (user decision 2026-10-13). Live runs showed the old wording ("get the user's confirmation once", a
step-0 confirmation question) made the main session stop with "shall I start the workers?". These checks pin the
skill text so the pause does not creep back in.
Run from the repo root: python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import os
import re
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAUSE = re.compile(r"confirmation question|step-0 confirmation|confirms once|confirming with the user|"
                   r"get the user's confirmation|before asking for confirmation|AskUserQuestion")


def instruction_files(skill_dir):
    yield os.path.join(skill_dir, "SKILL.md")
    refs = os.path.join(skill_dir, "references")
    for f in sorted(os.listdir(refs)):
        if f.endswith(".md"):
            yield os.path.join(refs, f)


def pauses(skill_dir):
    found = []
    for path in instruction_files(skill_dir):
        with open(path, encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                if PAUSE.search(line):
                    found.append(f"{os.path.relpath(path, skill_dir)}:{n}: {PAUSE.search(line).group(0)}")
    return found


class NoPauseTest(unittest.TestCase):
    def test_no_question_before_workers_start(self):
        self.assertEqual(pauses(SKILL_DIR), [])

    def test_the_rule_and_its_report_are_stated(self):
        with open(os.path.join(SKILL_DIR, "SKILL.md"), encoding="utf-8") as f:
            text = f.read()
        self.assertIn("**Do not ask before starting.**", text)
        self.assertIn("- Ask the user anything before the workers start", text)
        self.assertIn("report in one message", text)
        self.assertIn("Template: default (say \"change the brief template\" to customize)", text)

    def test_cleanup_still_waits_for_the_user(self):
        # Removing worktrees cannot be undone, so it keeps its go-ahead
        with open(os.path.join(SKILL_DIR, "references", "cleanup.md"), encoding="utf-8") as f:
            self.assertIn("Never clean up without the user's go-ahead", f.read())


if __name__ == "__main__":
    unittest.main()
