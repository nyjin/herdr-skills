"""hooks/hooks.json (plugin installs) and manage.py hook_entries() (other installs) must register the same hooks."""
import importlib.util
import json
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SKILL_DIR))

spec = importlib.util.spec_from_file_location("manage", os.path.join(SKILL_DIR, "scripts", "hooks", "manage.py"))
manage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manage)

PLUGIN_ROUTE = '"${CLAUDE_PLUGIN_ROOT}/skills/herdr-parallel-worktree/scripts/hooks/route.py"'
GUARD = '[ "$HERDR_ENV" = 1 ] || exit 0; '


def normalise(hooks, route_ref):
    return json.loads(json.dumps(hooks).replace(json.dumps(route_ref)[1:-1], "ROUTE"))


class RegistrationTest(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(REPO, "hooks", "hooks.json"), encoding="utf-8") as f:
            self.plugin = json.load(f)["hooks"]
        self.standalone = manage.hook_entries("/SKILL")

    def test_same_set(self):
        self.assertEqual(normalise(self.plugin, PLUGIN_ROUTE),
                         normalise(self.standalone, '"/SKILL/scripts/hooks/route.py"'))

    def test_every_command_is_guarded_and_names_its_event(self):
        for event, groups in self.plugin.items():
            arg = {"PreToolUse": "pre-tool-use", "PostToolUse": "post-tool-use"}[event]
            for g in groups:
                for h in g["hooks"]:
                    with self.subTest(event=event, matcher=g["matcher"], cmd=h["command"]):
                        self.assertTrue(h["command"].startswith(GUARD))
                        self.assertTrue(h["command"].endswith(" " + arg))

    def test_expected_matchers(self):
        pre = [(g["matcher"], g["hooks"][0].get("if")) for g in self.plugin["PreToolUse"]]
        self.assertEqual(pre, [
            ("Bash", "Bash(*worktree add*)"),
            ("Bash", "Bash(*git -C *)"),
            ("Bash", "Bash(cd *)"),   # also matches `… && cd x`: rules match each subcommand (spec §11 V2)
            ("EnterWorktree|Agent|Task", None),
            ("Write|Edit|MultiEdit|NotebookEdit", None),
        ])
        self.assertEqual([g["matcher"] for g in self.plugin["PostToolUse"]], ["Agent|Task"])

    def test_manage_marker_still_finds_every_group(self):
        # strip_ours() finds our groups by MARK ("herdr-parallel-worktree/scripts/hooks/route.py"), so use a
        # skill directory shaped like a real install.
        entries = manage.hook_entries("/home/u/.claude/skills/herdr-parallel-worktree")
        groups = [g for gs in entries.values() for g in gs]
        settings = {"hooks": json.loads(json.dumps(entries))}
        self.assertEqual(manage.strip_ours(settings), len(groups))
        self.assertNotIn("hooks", settings)


if __name__ == "__main__":
    unittest.main()
