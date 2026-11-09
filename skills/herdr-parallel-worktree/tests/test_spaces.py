"""Tests for scripts/hooks/spaces.py: which herdr space a worktree of a repository belongs under.
Run from the repo root: python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts", "hooks"))
import spaces  # noqa: E402

KEY = "/r/.git"


class Herdr:
    """Answers like the herdr CLI (shapes from herdr 0.9.0). `keys` maps a workspace id to its repo_key (absent:
    the workspace is not bound to a repository); `source` is the space herdr knows for the repository, or None;
    `fail` names commands ("worktree list", "workspace get") that return None or an error object."""

    def __init__(self, keys=None, source=None, fail=None):
        self.keys, self.source, self.fail, self.calls = keys or {}, source, fail or {}, []

    def __call__(self, args):
        self.calls.append(list(args))
        cmd = " ".join(args[:2])
        if cmd in self.fail:
            return self.fail[cmd]
        if cmd == "worktree list":
            src = {"repo_key": KEY, "repo_name": "r", "repo_root": "/r"}
            if self.source:
                src["source_workspace_id"] = self.source
            return {"result": {"source": src, "worktrees": []}}
        if cmd == "workspace get":
            ws = {"workspace_id": args[2]}
            if args[2] in self.keys:
                ws["worktree"] = {"repo_key": self.keys[args[2]]}
            return {"result": {"workspace": ws}}
        return {"error": {"code": "not_supported"}}


class RepoSpaceTest(unittest.TestCase):
    def test_current_bound_to_the_repository(self):
        self.assertEqual(spaces.repo_space("/r", "w1", Herdr(keys={"w1": KEY}, source="w7")), ("w1", "current"))

    def test_current_is_the_source_space_even_unbound(self):
        h = Herdr(source="w1")
        self.assertEqual(spaces.repo_space("/r", "w1", h), ("w1", "current"))
        self.assertNotIn("workspace get", [" ".join(c[:2]) for c in h.calls])

    def test_another_space_herdr_knows(self):
        self.assertEqual(spaces.repo_space("/r", "w1", Herdr(keys={"w1": "/other/.git"}, source="w7")),
                         ("w7", "repo-space"))

    def test_no_current_uses_the_source_space(self):
        self.assertEqual(spaces.repo_space("/r", None, Herdr(source="w7")), ("w7", "repo-space"))

    def test_none_when_herdr_knows_no_space(self):
        self.assertEqual(spaces.repo_space("/r", "w1", Herdr(keys={"w1": "/other/.git"})), (None, "none"))
        self.assertEqual(spaces.repo_space("/r", None, Herdr()), (None, "none"))

    def test_herdr_failure_is_an_error_not_none(self):
        for fail in ({"worktree list": None}, {"worktree list": {"error": {"code": "server_unavailable"}}},
                     {"workspace get": None}, {"workspace get": {"error": {"code": "workspace_not_found"}}}):
            with self.subTest(fail=fail):
                self.assertEqual(spaces.repo_space("/r", "w1", Herdr(source="w7", fail=fail)), (None, "herdr-error"))


if __name__ == "__main__":
    unittest.main()
