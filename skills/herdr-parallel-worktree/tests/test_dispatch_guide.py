"""The guide the dispatch hooks point to (references/dispatch.md): it exists where route.GUIDE says, names the
contract (tab names, shared folder, finalize-brief options, pull-based waiting, what was not verified), shows only
one tab-to-tab send (fix -> re-review), and every finalize-brief option it uses exists.
Run from the repo root: python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import importlib.util
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
GUIDE = os.path.join(SKILL_DIR, "references", "dispatch.md")
FINALIZE = os.path.join(SKILL_DIR, "scripts", "finalize-brief.py")
ROUTE_PATH = os.path.join(SKILL_DIR, "scripts", "hooks", "route.py")

spec = importlib.util.spec_from_file_location("route", ROUTE_PATH)
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)

FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
# A line that runs `herdr agent prompt`: indentation, an inline-code backtick or a shell `$ ` may come first
SEND = re.compile(r"^[\s`$]*herdr agent prompt\b")
OPTION = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
FINALIZE_OPTIONS = ("--role", "--worktree", "--branch", "--outside", "--then")


def read_guide():
    with open(GUIDE, encoding="utf-8") as f:
        return f.read()


def fenced_lines(text):
    """Lines inside fenced code blocks (``` or ~~~), fences themselves excluded."""
    out, mark = [], None
    for line in text.splitlines():
        m = FENCE.match(line)
        if m and (mark is None or (m.group(1)[0] == mark[0] and len(m.group(1)) >= len(mark))):
            mark = None if mark else m.group(1)
            continue
        if mark:
            out.append(line)
    return out


def commands(lines):
    """Join backslash-continued lines into whole commands."""
    out, cur = [], ""
    for line in lines:
        if line.rstrip().endswith("\\"):
            cur += line.rstrip()[:-1] + " "
        else:
            out.append(cur + line)
            cur = ""
    if cur:
        out.append(cur)
    return out


class DispatchGuideTest(unittest.TestCase):
    def test_guide_is_where_the_hooks_point(self):
        self.assertEqual(os.path.realpath(route.GUIDE), os.path.realpath(GUIDE))
        self.assertTrue(os.path.isfile(route.GUIDE), route.GUIDE)

    def test_names_the_contract(self):
        text = read_guide()
        for word in ("<plan>-impl", "<plan>-rev", "$BRIEFS/<plan>/", "finalize-brief.py", "--outside", "--then",
                     "--role", "agent wait", "run_in_background", "Not verified", "agent_blocked"):
            with self.subTest(word=word):
                self.assertIn(word, text)

    def test_only_one_direct_hop(self):
        # Prose may name `herdr agent prompt` (never send to the orchestrator's pane); code shows only the hop
        sends = [l for l in fenced_lines(read_guide()) if SEND.match(l)]
        self.assertTrue(sends, "the fix -> re-review send is missing from the guide's code")
        for line in sends:
            with self.subTest(line=line.strip()):
                self.assertIn("Re-review request", line)

    def test_finalize_options_in_the_guide_exist(self):
        text = read_guide()
        r = subprocess.run([sys.executable, FINALIZE, "--help"], capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        offered = set(OPTION.findall(r.stdout))
        for opt in FINALIZE_OPTIONS:
            with self.subTest(option=opt):
                self.assertIn(opt, text)
                self.assertIn(opt, offered)
        used = {o for c in commands(fenced_lines(text)) if "finalize-brief.py" in c
                for o in OPTION.findall(c.split("finalize-brief.py", 1)[1])}
        self.assertTrue(used, "no finalize-brief.py command in the guide")
        self.assertEqual(used - offered, set(), "finalize-brief.py options the script does not have")


if __name__ == "__main__":
    unittest.main()
