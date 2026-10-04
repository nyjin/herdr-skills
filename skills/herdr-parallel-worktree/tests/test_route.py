"""Unit tests for scripts/hooks/route.py. Run from the repo root:
python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import importlib.util
import os
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(HERE)
ROUTE_PATH = os.path.join(SKILL_DIR, "scripts", "hooks", "route.py")

spec = importlib.util.spec_from_file_location("route", ROUTE_PATH)
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)

MAIN_ENV = {"HERDR_ENV": "1"}
WORKER_ENV = {"HERDR_ENV": "1", "HERDR_PW_WORKER": "w1"}

# A fake repository: main checkout /r, linked worktrees /w/a and /w/b, and /x outside git.
FAKE = {
    "/r": ("/r/.git", "/r/.git", "/r"),
    "/w/a": ("/r/.git/worktrees/a", "/r/.git", "/w/a"),
    "/w/b": ("/r/.git/worktrees/b", "/r/.git", "/w/b"),
}


def fake_probe(path):
    for top, info in FAKE.items():
        if path == top or path.startswith(top + "/"):
            return info
    return None


def event(tool, sub=False, cwd="/r", hook="PreToolUse", **tool_input):
    e = {"session_id": "s", "cwd": cwd, "permission_mode": "default", "prompt_id": "p",
         "hook_event_name": hook, "tool_name": tool, "tool_input": tool_input,
         "tool_use_id": "t", "transcript_path": "/tmp/t.jsonl"}
    if sub:
        e["agent_id"] = "a1"
        e["agent_type"] = "general-purpose"
    return e


def reason(out):
    assert out is not None, "expected a deny, got no output"
    hso = out["hookSpecificOutput"]
    assert hso["hookEventName"] == "PreToolUse"
    assert hso["permissionDecision"] == "deny"
    return hso["permissionDecisionReason"]


class ActorTest(unittest.TestCase):
    def test_four_actors(self):
        self.assertEqual(route.actor(event("Bash"), MAIN_ENV), "main")
        self.assertEqual(route.actor(event("Bash", sub=True), MAIN_ENV), "sub")
        self.assertEqual(route.actor(event("Bash"), WORKER_ENV), "worker")
        self.assertEqual(route.actor(event("Bash", sub=True), WORKER_ENV), "worker-sub")

    def test_empty_worker_var_is_not_a_worker(self):
        self.assertEqual(route.actor(event("Bash"), {"HERDR_ENV": "1", "HERDR_PW_WORKER": ""}), "main")


class CreationTest(unittest.TestCase):
    CASES = [
        ("Bash", {"command": "git worktree add ../fix -b fix/x"}),
        ("Bash", {"command": "cd /r && git -C /r worktree add /w/c"}),
        ("EnterWorktree", {}),
        ("Agent", {"prompt": "fix it", "subagent_type": "general-purpose", "isolation": "worktree"}),
        ("Task", {"prompt": "fix it", "isolation": "worktree"}),
    ]

    def decide(self, tool, args, sub, env):
        return route.decide(event(tool, sub=sub, **args), env, fake_probe)

    def test_main_is_sent_to_the_skill(self):
        for tool, args in self.CASES:
            with self.subTest(tool=tool, args=args):
                self.assertEqual(reason(self.decide(tool, args, False, MAIN_ENV)), route.DENY_MAIN)

    def test_sub_is_told_to_hand_off(self):
        for tool, args in self.CASES:
            with self.subTest(tool=tool, args=args):
                self.assertEqual(reason(self.decide(tool, args, True, MAIN_ENV)), route.DENY_SUB)

    def test_worker_is_told_to_do_it_itself(self):
        for tool, args in self.CASES:
            with self.subTest(tool=tool, args=args):
                r = reason(route.decide(event(tool, cwd="/w/a", **args), WORKER_ENV, fake_probe))
                self.assertEqual(r, route.deny_worker("w1", "/w/a"))

    def test_worker_sub_is_told_to_hand_off(self):
        for tool, args in self.CASES:
            with self.subTest(tool=tool, args=args):
                r = reason(route.decide(event(tool, sub=True, cwd="/w/a", **args), WORKER_ENV, fake_probe))
                self.assertEqual(r, route.DENY_SUB)

    def test_incident_command_from_the_saju_session(self):
        cmd = "git worktree add ../kb-skills-fix-normalize -b fix/normalize-alias"
        self.assertEqual(reason(route.decide(event("Bash", sub=True, command=cmd), MAIN_ENV, fake_probe)),
                         route.DENY_SUB)

    def test_allowed_creation_lookalikes(self):
        allowed = [
            ("Bash", {"command": 'git commit -m "explain git worktree add"'}),
            ("Bash", {"command": "grep -rn 'worktree add' docs"}),
            ("Bash", {"command": "git worktree list"}),
            ("EnterWorktree", {"path": "/w/a"}),
            ("Agent", {"prompt": "run git worktree add ../x", "subagent_type": "general-purpose"}),
        ]
        for tool, args in allowed:
            for sub in (False, True):
                with self.subTest(tool=tool, args=args, sub=sub):
                    self.assertIsNone(self.decide(tool, args, sub, MAIN_ENV))


class MessageTest(unittest.TestCase):
    def test_sub_message_carries_the_handoff_block(self):
        self.assertIn("\nHERDR-HANDOFF\n", "\n" + route.DENY_SUB + "\n")
        self.assertTrue(route.HANDOFF.startswith("HERDR-HANDOFF\nTo the main session:"))
        for field in ("name:", "repo:", "goal:", "branch:", "steps:", "done:"):
            self.assertIn("\n" + field, route.HANDOFF)

    def test_messages_never_suggest_bang_to_subagents(self):
        self.assertIn("Do not suggest", route.DENY_SUB)
        self.assertIn("Do not tell the user", route.NOTE_HANDOFF)

    def test_main_exception_is_limited_to_the_user_in_this_conversation(self):
        self.assertIn("the user, in this conversation, explicitly asked", route.DENY_MAIN)

    def test_worker_message_names_worker_and_home(self):
        m = route.deny_worker("w1", "/w/a")
        self.assertIn("`w1`", m)
        self.assertIn("/w/a", m)
        self.assertIn("HERDR-HANDOFF", m)


if __name__ == "__main__":
    unittest.main()
