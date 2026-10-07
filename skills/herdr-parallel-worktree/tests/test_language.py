"""The skill's own text stays in English: SKILL.md, references, assets and scripts are read by the model, and the
skill tells it to talk to the user in the user's language. Example user phrases are written in English.
Tests are exempt: some match Korean model replies on purpose.
Run from the repo root: python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import os
import re
import unittest

SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HANGUL = re.compile("[ᄀ-ᇿ㄰-㆏가-힣]")


def skill_text_files():
    yield os.path.join(SKILL_DIR, "SKILL.md")
    for sub in ("references", "assets", "scripts"):
        for root, _, files in os.walk(os.path.join(SKILL_DIR, sub)):
            for f in files:
                if f.endswith((".md", ".py", ".json", ".txt", ".sh")):
                    yield os.path.join(root, f)


class LanguageTest(unittest.TestCase):
    def test_skill_text_is_english(self):
        found = []
        for path in skill_text_files():
            with open(path, encoding="utf-8") as f:
                for n, line in enumerate(f, 1):
                    if HANGUL.search(line):
                        found.append(f"{os.path.relpath(path, SKILL_DIR)}:{n}: {line.strip()[:80]}")
        self.assertEqual(found, [], "Korean text in skill files:\n" + "\n".join(found))


if __name__ == "__main__":
    unittest.main()
