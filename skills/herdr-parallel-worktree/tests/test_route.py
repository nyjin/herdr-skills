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

# HERDR_SKILLS_DATA_HOME points nowhere, so decide() never reads the real runs.json
NO_DATA = "/nonexistent/herdr-skills-test"
MAIN_ENV = {"HERDR_ENV": "1", "HERDR_SKILLS_DATA_HOME": NO_DATA}
WORKER_ENV = {"HERDR_ENV": "1", "HERDR_PW_WORKER": "w1", "HERDR_SKILLS_DATA_HOME": NO_DATA}

# A fake repository: main checkout /r, linked worktrees /w/a and /w/b, and /x outside git.
FAKE = {
    "/r": ("/r/.git", "/r/.git", "/r"),
    "/w/a": ("/r/.git/worktrees/a", "/r/.git", "/w/a"),
    "/w/b": ("/r/.git/worktrees/b", "/r/.git", "/w/b"),
    "/w/c": ("/r/.git/worktrees/c", "/r/.git", "/w/c"),
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


def decide_fake(e, env, runs=()):
    """decide() in the fake layout: /r is the main checkout of every fake worktree."""
    return route.decide(e, env, fake_probe, runs=list(runs), main_of=lambda p: "/r")


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
                self.assertEqual(r, route.deny_worker_create("w1", "/w/a"))

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
        self.assertIn("by its `owner:` line", route.HANDOFF.splitlines()[1])
        fields = [l.split(":")[0] for l in route.HANDOFF.splitlines()[2:] if not l.startswith("- ")]
        self.assertEqual(fields, ["name", "repo", "owner", "goal", "branch", "steps", "done"])

    def test_handoff_owner_line(self):
        self.assertIn("\nowner: b\n", route.handoff(("worker", "b", "/w/b")))
        self.assertIn("\nowner: main-checkout\n", route.handoff(("main-checkout", None, "/r")))
        self.assertIn("\nowner: none\n", route.handoff(("none", None, "/w/c")))
        self.assertIn("\nowner: <worker name | main-checkout | none>\n", route.handoff(None))

    def test_owner_specific_wording(self):
        m = route.deny_sub(("worker", "b", "/w/b"))
        self.assertIn("worker `b`", m)
        self.assertIn("/w/b", m)
        self.assertIn("ask the user", route.deny_sub(("main-checkout", None, "/r")))
        w = route.deny_worker_write("w1", "/w/a", ("worker", "b", "/w/b"))
        self.assertIn("`w1`", w)
        self.assertIn("## Result", w)
        self.assertIn("\nowner: b\n", w)
        self.assertNotEqual(w, route.deny_worker_create("w1", "/w/a"))
        self.assertIn("by the block's `owner:` line", route.NOTE_HANDOFF)

    def test_messages_never_suggest_bang_to_subagents(self):
        self.assertIn("Do not suggest", route.DENY_SUB)
        self.assertIn("Do not tell the user", route.NOTE_HANDOFF)

    def test_main_exception_is_limited_to_the_user_in_this_conversation(self):
        self.assertIn("the user, in this conversation, explicitly asked", route.DENY_MAIN)

    def test_worker_message_names_worker_and_home(self):
        m = route.deny_worker_create("w1", "/w/a")
        self.assertIn("`w1`", m)
        self.assertIn("/w/a", m)
        self.assertIn("HERDR-HANDOFF", m)


import subprocess
import tempfile
from unittest import mock


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
                self.assertEqual(reason(out), route.deny_sub(("none", None, "/w/b")))

    def test_sub_bash_into_other_worktree_is_denied(self):
        out = route.decide(event("Bash", sub=True, command="cd /w/b && sed -i s/a/b/ f.py"), MAIN_ENV, fake_probe)
        self.assertEqual(reason(out), route.DENY_SUB)

    def test_allowed_writes(self):
        allowed = [
            (event("Write", sub=False, file_path="/w/b/f.py"), MAIN_ENV),                 # main may write anywhere
            (event("Write", sub=True, file_path="/r/f.py"), MAIN_ENV),                    # main checkout
            (event("Write", sub=True, file_path="/x/f.py"), MAIN_ENV),                    # outside git
            (event("Write", sub=True, cwd="/w/a", file_path="/w/a/f.py"), WORKER_ENV),    # worker-sub, own worktree
            (event("Bash", sub=True, command="cd $WT && make"), MAIN_ENV),                # unreadable target
            (event("Bash", sub=True, command="ls /w/b"), MAIN_ENV),                       # no cd / git -C
        ]
        for e, env in allowed:
            with self.subTest(e=e["tool_input"], env=env):
                self.assertIsNone(route.decide(e, env, fake_probe))

    def test_worker_sub_write_into_other_worktree_is_denied(self):
        out = route.decide(event("Edit", sub=True, cwd="/w/a", file_path="/w/b/f.py"), WORKER_ENV, fake_probe)
        self.assertEqual(reason(out), route.deny_sub(("none", None, "/w/b")))


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
        # file_path through /var (unresolved) while cwd is resolved, and the other way round
        wt_real = os.path.realpath(self.wt)
        out = route.decide(event("Write", sub=True, cwd=os.path.realpath(self.repo),
                                 file_path=os.path.join(self.wt, "f.py")), MAIN_ENV)
        self.assertEqual(reason(out), route.deny_sub(("none", None, wt_real)))
        self.assertIsNone(route.decide(event("Write", sub=True, cwd=wt_real,
                                             file_path=os.path.join(self.wt, "f.py")), MAIN_ENV))

    def test_new_file_in_missing_dir_of_other_worktree(self):
        path = os.path.join(self.wt, "new", "deeper", "f.py")
        out = route.decide(event("Write", sub=True, cwd=self.repo, file_path=path), MAIN_ENV)
        self.assertEqual(reason(out), route.deny_sub(("none", None, os.path.realpath(self.wt))))

    def test_worker_write_into_real_main_checkout(self):
        out = route.decide(event("Write", cwd=self.wt, file_path=os.path.join(self.repo, "f.py")), WORKER_ENV)
        self.assertEqual(reason(out), route.deny_worker_write(
            "w1", os.path.realpath(self.wt), ("main-checkout", None, os.path.realpath(self.repo))))

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


import json as _json
import sys as _sys


class PostToolUseTest(unittest.TestCase):
    # Shape measured on Claude Code 2.1.289: PostToolUse(Agent) fires at launch with an async status.
    RESPONSE = {"isAsync": True, "status": "async_launched", "agentId": "a17c", "description": "probe"}

    def post(self, tool="Agent", sub=False):
        e = event(tool, sub=sub, hook="PostToolUse", prompt="x", subagent_type="general-purpose")
        e["tool_response"] = self.RESPONSE
        return e

    def test_main_gets_the_note(self):
        for tool in ("Agent", "Task"):
            with self.subTest(tool=tool):
                out = route.decide(self.post(tool), MAIN_ENV, fake_probe)
                self.assertEqual(out, {"hookSpecificOutput": {"hookEventName": "PostToolUse",
                                                              "additionalContext": route.NOTE_HANDOFF}})

    def test_no_note_for_sub_worker_or_other_tools(self):
        self.assertIsNone(route.decide(self.post(sub=True), MAIN_ENV, fake_probe))
        self.assertIsNone(route.decide(self.post(), WORKER_ENV, fake_probe))
        e = event("Bash", hook="PostToolUse", command="ls")
        self.assertIsNone(route.decide(e, MAIN_ENV, fake_probe))


class EntryPointTest(unittest.TestCase):
    """Run route.py as Claude Code does: JSON on stdin, decision on stdout, always exit 0."""

    def run_route(self, arg, payload, env_extra, data_home):
        env = {k: v for k, v in os.environ.items() if k not in ("HERDR_ENV", "HERDR_PW_WORKER")}
        env.update(env_extra)
        env["HERDR_SKILLS_DATA_HOME"] = data_home
        r = subprocess.run([_sys.executable, ROUTE_PATH, arg], input=payload, capture_output=True,
                           text=True, env=env, timeout=10)
        self.assertEqual(r.returncode, 0)
        return r.stdout

    def setUp(self):
        self.data = tempfile.mkdtemp()
        self.payload = _json.dumps(event("Bash", command="git worktree add ../x"))

    def tearDown(self):
        subprocess.run(["rm", "-rf", self.data], check=False)

    def test_denies_inside_herdr(self):
        out = self.run_route("pre-tool-use", self.payload, {"HERDR_ENV": "1"}, self.data)
        self.assertEqual(_json.loads(out)["hookSpecificOutput"]["permissionDecision"], "deny")

    def test_silent_outside_herdr(self):
        self.assertEqual(self.run_route("pre-tool-use", self.payload, {}, self.data), "")

    def test_silent_when_hooks_off(self):
        os.makedirs(os.path.join(self.data, "herdr-parallel-worktree"))
        with open(os.path.join(self.data, "herdr-parallel-worktree", "config.json"), "w") as f:
            f.write('{"hooks": "off"}')
        self.assertEqual(self.run_route("pre-tool-use", self.payload, {"HERDR_ENV": "1"}, self.data), "")

    def test_silent_on_bad_input_or_argument(self):
        self.assertEqual(self.run_route("pre-tool-use", "not json", {"HERDR_ENV": "1"}, self.data), "")
        self.assertEqual(self.run_route("bogus", self.payload, {"HERDR_ENV": "1"}, self.data), "")
        self.assertEqual(self.run_route("pre-tool-use", "[]", {"HERDR_ENV": "1"}, self.data), "")

    def test_post_tool_use_note(self):
        payload = _json.dumps(event("Agent", hook="PostToolUse", prompt="x"))
        out = self.run_route("post-tool-use", payload, {"HERDR_ENV": "1"}, self.data)
        self.assertEqual(_json.loads(out)["hookSpecificOutput"]["additionalContext"], route.NOTE_HANDOFF)


class SpecMatrixTest(unittest.TestCase):
    """Spec §5.3, cell by cell: every rule R1–R6 for every caller. Keep this table identical to the spec's."""
    RULES = {
        "R1": lambda sub, cwd: event("Bash", sub=sub, cwd=cwd, command="git worktree add ../x -b x"),
        "R2": lambda sub, cwd: event("EnterWorktree", sub=sub, cwd=cwd),
        "R3": lambda sub, cwd: event("Agent", sub=sub, cwd=cwd, prompt="p", isolation="worktree"),
        "R4": lambda sub, cwd: event("Write", sub=sub, cwd=cwd, file_path="/w/b/f.py"),
        "R5": lambda sub, cwd: event("Bash", sub=sub, cwd=cwd, command="cd /w/b && make"),
        "R6": lambda sub, cwd: event("Agent", sub=sub, cwd=cwd, hook="PostToolUse", prompt="p"),
    }
    ACTORS = {"main": (False, "/r", MAIN_ENV), "sub": (True, "/r", MAIN_ENV),
              "worker": (False, "/w/a", WORKER_ENV), "worker-sub": (True, "/w/a", WORKER_ENV)}
    #          main     sub    worker    worker-sub
    TABLE = {
        "R1": ("MAIN", "SUB", "WORKER", "SUB"),
        "R2": ("MAIN", "SUB", "WORKER", "SUB"),
        "R3": ("MAIN", "SUB", "WORKER", "SUB"),
        "R4": (None, "SUB", "WORKER_WRITE", "SUB"),
        "R5": (None, "SUB", None, "SUB"),
        "R6": ("NOTE", None, None, None),
    }

    @staticmethod
    def outcome(out):
        if out is None:
            return None
        hso = out["hookSpecificOutput"]
        if hso.get("additionalContext") == route.NOTE_HANDOFF:
            return "NOTE"
        own = ("none", None, "/w/b")
        return {route.DENY_MAIN: "MAIN", route.DENY_SUB: "SUB", route.deny_sub(own): "SUB",
                route.deny_worker_create("w1", "/w/a"): "WORKER",
                route.deny_worker_write("w1", "/w/a", own): "WORKER_WRITE"}.get(hso.get("permissionDecisionReason"), "OTHER")

    def test_every_cell(self):
        for rule, expected in self.TABLE.items():
            for (who, (sub, cwd, env)), want in zip(self.ACTORS.items(), expected):
                with self.subTest(rule=rule, caller=who):
                    got = self.outcome(route.decide(self.RULES[rule](sub, cwd), env, fake_probe))
                    self.assertEqual(got, want)


class ReviewFixTest(unittest.TestCase):
    """Findings of the final branch review: quoted or heredoc text is not a command; a failed probe allows."""

    def test_worktree_add_inside_quotes_is_not_a_command(self):
        for cmd in ('git commit -m "fix; git worktree add docs"',
                    "echo 'a | git worktree add b'",
                    "python3 - <<'EOF'\nprint(\"echo hi && git worktree add x\")\nEOF",
                    "cat <<EOF > notes.md\ngit worktree add ../x\nEOF"):
            with self.subTest(cmd=cmd):
                self.assertIsNone(route.decide(event("Bash", command=cmd), MAIN_ENV, fake_probe))

    def test_heredoc_body_is_not_a_cd(self):
        cmd = "cat <<'EOF' > notes.md\ncd /w/b\nEOF"
        self.assertEqual(route.dir_targets(cmd), [])

    def test_commands_after_a_heredoc_still_count(self):
        cmd = "cat <<'EOF' > notes.md\nhello\nEOF\ngit worktree add ../x"
        self.assertEqual(reason(route.decide(event("Bash", command=cmd), MAIN_ENV, fake_probe)), route.DENY_MAIN)

    def test_quoted_global_option_with_space_is_still_creation(self):
        for cmd in ('git -C "/Users/x/my repo" worktree add ../wt -b t',
                    "git -C '/Users/x/my repo' worktree add ../wt -b t"):
            with self.subTest(cmd=cmd):
                self.assertEqual(reason(route.decide(event("Bash", command=cmd), MAIN_ENV, fake_probe)),
                                 route.DENY_MAIN)

    def test_failed_probe_of_cwd_allows(self):
        def probe(path):   # the target resolves, the session's own directory does not (timeout, deleted cwd)
            return fake_probe(path) if path.startswith("/w/b") else None
        self.assertIsNone(route.decide(event("Write", sub=True, cwd="/w/a", file_path="/w/b/f.py"), MAIN_ENV, probe))


class R4OwnerMatrixTest(unittest.TestCase):
    """Plan R4 table (spec §13.2), all 20 cells: writer x owner of the written file, exact messages."""
    RUNS = [{"name": "b", "worktree": "/w/b", "state": "open"}]
    WORKER, MAIN_CO, NONE = ("worker", "b", "/w/b"), ("main-checkout", None, "/r"), ("none", None, "/w/c")
    WRITERS = {"main": (False, "/r", MAIN_ENV), "sub": (True, "/r", MAIN_ENV),
               "worker": (False, "/w/a", WORKER_ENV), "worker-sub": (True, "/w/a", WORKER_ENV)}

    def expected(self, who, target):
        sub_deny = lambda own: route.deny_sub(own)
        wk_deny = lambda own: route.deny_worker_write("w1", "/w/a", own)
        table = {
            "main":       {"home": None, "worker": None, "main": None, "none": None, "out": None},
            "sub":        {"home": None, "worker": sub_deny(self.WORKER), "main": None,
                           "none": sub_deny(self.NONE), "out": None},
            "worker":     {"home": None, "worker": wk_deny(self.WORKER), "main": wk_deny(self.MAIN_CO),
                           "none": wk_deny(self.NONE), "out": None},
            "worker-sub": {"home": None, "worker": sub_deny(self.WORKER), "main": sub_deny(self.MAIN_CO),
                           "none": sub_deny(self.NONE), "out": None},
        }
        return table[who][target]

    def test_every_cell(self):
        for who, (sub, cwd, env) in self.WRITERS.items():
            targets = {"home": cwd + "/h.py", "worker": "/w/b/f.py", "main": "/r/m.py",
                       "none": "/w/c/f.py", "out": "/x/f.py"}
            for target, path in targets.items():
                for tool, key in (("Write", "file_path"), ("NotebookEdit", "notebook_path")):
                    with self.subTest(writer=who, target=target, tool=tool):
                        out = decide_fake(event(tool, sub=sub, cwd=cwd, **{key: path}), env, self.RUNS)
                        want = self.expected(who, target)
                        self.assertEqual(None if out is None else reason(out), want)

    def test_relative_path_resolves_against_cwd(self):
        out = decide_fake(event("Edit", cwd="/w/a", file_path="../b/f.py"), WORKER_ENV, self.RUNS)
        self.assertEqual(reason(out), route.deny_worker_write("w1", "/w/a", self.WORKER))


if __name__ == "__main__":
    unittest.main()
