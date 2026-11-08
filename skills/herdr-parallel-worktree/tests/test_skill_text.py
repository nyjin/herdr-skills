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


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


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

    def test_finalize_options_documented(self):
        text = read(BRIEF_FILLING)
        for opt in ("--outside", "--then"):
            with self.subTest(option=opt):
                self.assertTrue(opt in text, f"brief-filling.md does not document {opt}")


if __name__ == "__main__":
    unittest.main()
