"""The skill's own text stays in step with its code: SKILL.md's config check and table name exactly the keys of
references/config.schema.json, SKILL.md points to the dispatch guide and names both ways a dispatching skill is
loaded (the `Skill` tool and a `/name` prompt), and brief-filling.md documents the finalize-brief.py options that
write a brief's Environment and On completion sections.
Run from the repo root: python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import json
import os
import re
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SKILL_MD = os.path.join(SKILL_DIR, "SKILL.md")
SCHEMA = os.path.join(SKILL_DIR, "references", "config.schema.json")
BRIEF_FILLING = os.path.join(SKILL_DIR, "references", "brief-filling.md")
REFS = os.path.join(SKILL_DIR, "references")
RESUME = os.path.join(REFS, "resume.md")
DELIVER = os.path.join(REFS, "deliver.md")
PLACE = os.path.join(SKILL_DIR, "scripts", "place.py")
OPTION = re.compile(r"(?<![\w-])--[a-z][a-z-]*")
# `place.py <sub> <args>` up to the end of that command: a closing `)`, a pipe, `;`, `&&` or the end of the line
PLACE_CALL = re.compile(r'place\.py"?\s+([a-z]+)\b([^\n`)|;&]*)')


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def doc_paths():
    yield SKILL_MD
    for f in sorted(os.listdir(REFS)):
        if f.endswith(".md"):
            yield os.path.join(REFS, f)


def help_text(script, sub):
    import subprocess
    import sys
    r = subprocess.run([sys.executable, script, sub, "--help"], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return r.stdout


def section(text, heading):
    """The body of the level-2 section whose heading starts with `heading`, up to the next level-2 heading."""
    m = re.search(r"^## " + re.escape(heading) + r".*?$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1) if m else ""


def schema_keys():
    return set(json.loads(read(SCHEMA))["properties"])


class SkillTextTest(unittest.TestCase):
    def test_config_keys_match_the_schema(self):
        m = re.search(r"keys - \[([^\]]*)\]", read(SKILL_MD))
        self.assertIsNotNone(m, "SKILL.md has no `keys - [...]` in its config check")
        self.assertEqual(set(re.findall(r'"([^"]+)"', m.group(1))), schema_keys())

    def test_config_table_lists_every_key(self):
        rows = set(re.findall(r"^\| `(\w+)` \|", section(read(SKILL_MD), "Configuration"), re.M))
        self.assertEqual(rows, schema_keys())

    def test_skill_points_to_the_guide(self):
        self.assertTrue("references/dispatch.md" in read(SKILL_MD), "SKILL.md does not point to references/dispatch.md")

    def test_hooks_section_names_both_load_paths(self):
        hooks = section(read(SKILL_MD), "Hooks")
        self.assertTrue(hooks, "SKILL.md has no Hooks section")
        for word in ("`Skill`", "UserPromptSubmit"):
            with self.subTest(word=word):
                self.assertTrue(word in hooks, f"the Hooks section does not name {word}")

    def test_docs_place_workers_with_place_py(self):
        for path in (SKILL_MD, *(os.path.join(REFS, f) for f in ("resume.md", "deliver.md", "dispatch.md"))):
            with self.subTest(doc=os.path.basename(path)):
                self.assertIn("scripts/place.py", read(path))

    def test_no_doc_lets_herdr_make_a_space(self):
        # `--cwd` lets herdr make a new top-level space for the repository; place.py decides the space instead
        for path in doc_paths():
            text = read(path)
            for bad in ("worktree create --cwd", "worktree open --cwd", "LOC=("):
                with self.subTest(doc=os.path.basename(path), text=bad):
                    self.assertNotIn(bad, text)

    def test_place_py_calls_in_docs_exist(self):
        subs = {"where", "worktree", "reopen"}
        offered = {s: set(OPTION.findall(help_text(PLACE, s))) for s in subs}
        used = 0
        for path in doc_paths():
            for sub, rest in PLACE_CALL.findall(read(path)):
                used += 1
                with self.subTest(doc=os.path.basename(path), call=f"place.py {sub}{rest}"):
                    self.assertIn(sub, subs)
                    self.assertEqual(set(OPTION.findall(rest)) - offered[sub], set())
        self.assertTrue(used, "no place.py call in the docs")

    def test_runs_py_records_placement(self):
        for path, cmd in ((SKILL_MD, "add"), (RESUME, "mark-open"), (RESUME, "relocate"), (DELIVER, "relocate")):
            # lines that run the command (they pass --name), not prose that mentions it
            lines = [l for l in read(path).splitlines() if re.search(r'runs\.py"? ' + cmd + r"\b.*--name", l)]
            with self.subTest(doc=os.path.basename(path), cmd=cmd):
                self.assertTrue(lines, f"no runs.py {cmd} line")
                for line in lines:
                    self.assertIn("--placement", line)

    def test_finalize_options_documented(self):
        text = read(BRIEF_FILLING)
        for opt in ("--outside", "--then", "--workdir"):
            with self.subTest(option=opt):
                self.assertTrue(opt in text, f"brief-filling.md does not document {opt}")


if __name__ == "__main__":
    unittest.main()
