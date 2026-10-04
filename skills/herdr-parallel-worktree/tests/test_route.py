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


import subprocess
import tempfile
from unittest import mock


class OtherWorktreeTest(unittest.TestCase):
    def test_decisions(self):
        cases = [
            ("/w/b/f.py", "/r", "/w/b"),       # linked worktree, session in main checkout
            ("/w/b/f.py", "/w/a", "/w/b"),     # another worker's worktree
            ("/w/a/f.py", "/w/a", None),       # own worktree
            ("/w/a/sub/f.py", "/w/a/sub", None),
            ("/r/f.py", "/w/a", None),         # main checkout is not a linked worktree
            ("/x/f.py", "/r", None),           # not in git
        ]
        for path, cwd, expected in cases:
            with self.subTest(path=path, cwd=cwd):
                self.assertEqual(route.other_worktree(path, cwd, fake_probe), expected)

    def test_relative_path_resolves_against_cwd(self):
        self.assertEqual(route.other_worktree("../b/f.py", "/w/a", fake_probe), "/w/b")


class DirTargetsTest(unittest.TestCase):
    def test_reads_plain_and_quoted_targets(self):
        self.assertEqual(route.dir_targets("cd /w/b && make"), ["/w/b"])
        self.assertEqual(route.dir_targets("git -C /w/b commit -am x"), ["/w/b"])
        self.assertEqual(route.dir_targets("true; cd '/w/b' && git -C \"/w/a\" status"), ["/w/b", "/w/a"])

    def test_quoted_cd_target(self):
        self.assertEqual(route.dir_targets('cd "/p with spaces/wt" && ls'), ["/p with spaces/wt"])

    def test_variable_cd_target_ignored(self):
        for cmd in ("cd $WT && ls", 'cd "$WT"', "cd foo$bar", "cd $(git rev-parse --show-toplevel)",
                    "git -C `pwd` status"):
            with self.subTest(cmd=cmd):
                self.assertEqual(route.dir_targets(cmd), [])

    def test_cd_inside_commit_message_ignored(self):
        self.assertEqual(route.dir_targets('git commit -m "cd into the wt first"'), [])
        self.assertEqual(route.dir_targets("echo 'then git -C /w/b status'"), [])

    def test_home_shortcut_is_expanded(self):
        self.assertEqual(route.dir_targets("cd ~/w"), [os.path.expanduser("~/w")])


class WriteRuleTest(unittest.TestCase):
    def test_sub_write_into_other_worktree_is_denied(self):
        for tool, key in (("Write", "file_path"), ("Edit", "file_path"), ("MultiEdit", "file_path"),
                          ("NotebookEdit", "notebook_path")):
            with self.subTest(tool=tool):
                out = route.decide(event(tool, sub=True, **{key: "/w/b/f.py"}), MAIN_ENV, fake_probe)
                self.assertEqual(reason(out), route.DENY_SUB)

    def test_sub_bash_into_other_worktree_is_denied(self):
        out = route.decide(event("Bash", sub=True, command="cd /w/b && sed -i s/a/b/ f.py"), MAIN_ENV, fake_probe)
        self.assertEqual(reason(out), route.DENY_SUB)

    def test_allowed_writes(self):
        allowed = [
            (event("Write", sub=False, file_path="/w/b/f.py"), MAIN_ENV),                 # main may write anywhere
            (event("Write", sub=True, file_path="/r/f.py"), MAIN_ENV),                    # main checkout
            (event("Write", sub=True, file_path="/x/f.py"), MAIN_ENV),                    # outside git
            (event("Write", cwd="/w/a", file_path="/w/b/f.py"), WORKER_ENV),              # worker itself
            (event("Write", sub=True, cwd="/w/a", file_path="/w/a/f.py"), WORKER_ENV),    # worker-sub, own worktree
            (event("Bash", sub=True, command="cd $WT && make"), MAIN_ENV),                # unreadable target
            (event("Bash", sub=True, command="ls /w/b"), MAIN_ENV),                       # no cd / git -C
        ]
        for e, env in allowed:
            with self.subTest(e=e["tool_input"], env=env):
                self.assertIsNone(route.decide(e, env, fake_probe))

    def test_worker_sub_write_into_other_worktree_is_denied(self):
        out = route.decide(event("Edit", sub=True, cwd="/w/a", file_path="/w/b/f.py"), WORKER_ENV, fake_probe)
        self.assertEqual(reason(out), route.DENY_SUB)


class GitProbeTest(unittest.TestCase):
    """Real git: a main checkout and one linked worktree in a temp directory."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()            # on macOS this is under the /var -> /private/var symlink
        cls.repo = os.path.join(cls.tmp, "repo")
        cls.wt = os.path.join(cls.tmp, "wt")
        git = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]
        subprocess.run(["git", "init", "-q", cls.repo], check=True)
        subprocess.run(git + ["-C", cls.repo, "commit", "-q", "--allow-empty", "-m", "init"], check=True)
        subprocess.run(["git", "-C", cls.repo, "worktree", "add", "-q", cls.wt, "-b", "probe"], check=True)

    @classmethod
    def tearDownClass(cls):
        subprocess.run(["rm", "-rf", cls.tmp], check=False)

    def test_main_checkout_is_not_linked(self):
        git_dir, common, top = route.git_probe(os.path.join(self.repo, "f.py"))
        self.assertEqual(git_dir, common)
        self.assertEqual(top, os.path.realpath(self.repo))

    def test_linked_worktree(self):
        git_dir, common, top = route.git_probe(os.path.join(self.wt, "f.py"))
        self.assertNotEqual(git_dir, common)
        self.assertEqual(top, os.path.realpath(self.wt))

    def test_symlinked_path_is_resolved(self):
        cwd = os.path.realpath(self.repo)
        self.assertEqual(route.other_worktree(os.path.join(self.wt, "f.py"), cwd, route.git_probe),
                         os.path.realpath(self.wt))
        self.assertIsNone(route.other_worktree(os.path.join(self.wt, "f.py"), os.path.realpath(self.wt),
                                               route.git_probe))

    def test_new_file_in_missing_dir_of_other_worktree(self):
        path = os.path.join(self.wt, "new", "deeper", "f.py")
        self.assertEqual(route.other_worktree(path, self.repo, route.git_probe), os.path.realpath(self.wt))

    def test_outside_git_is_none(self):
        self.assertIsNone(route.git_probe(os.path.join(self.tmp, "f.py")))

    def test_git_timeout_allows(self):
        with mock.patch.object(route.subprocess, "run", side_effect=subprocess.TimeoutExpired("git", 2)):
            self.assertIsNone(route.git_probe(self.wt))
            out = route.decide(event("Write", sub=True, cwd=self.repo, file_path=os.path.join(self.wt, "f")),
                               MAIN_ENV)
            self.assertIsNone(out)

    def test_missing_git_allows(self):
        with mock.patch.object(route.subprocess, "run", side_effect=FileNotFoundError("git")):
            self.assertIsNone(route.git_probe(self.wt))


if __name__ == "__main__":
    unittest.main()
