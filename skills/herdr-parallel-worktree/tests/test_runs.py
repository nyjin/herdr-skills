"""Tests for scripts/runs.py's registry commands, with a temporary DATA_DIR, throwaway git repositories and a fake
`herdr` on PATH. Nothing here touches the real registry or a real worktree.
Run from the repo root: python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
RUNS_PY = os.path.join(os.path.dirname(HERE), "scripts", "runs.py")

# A fake herdr: logs every call to $CALLS; `pane get` reports a claude session whose id comes from the pane id and
# the tab `<ws>:t<n>` for pane `<ws>:p<n>` (pane_not_found for panes listed in $CLOSED); `tab get` reports
# focused for tabs listed in $FOCUSED_TABS; `workspace get` a workspace whose status is $WS_STATUS (default idle),
# focused when listed in $FOCUSED_WS; $WS_STATUS_MAP ({workspace: status or null}) sets it per workspace.
# $HERDR_DOWN makes every call print something that is not JSON.
FAKE_HERDR = r'''#!/usr/bin/env python3
import json, os, sys
args = sys.argv[1:]
with open(os.environ["CALLS"], "a") as f:
    f.write(json.dumps(args) + "\n")
if os.environ.get("HERDR_DOWN"):
    print("herdr: cannot connect to the server"); sys.exit(1)
def out(result):
    print(json.dumps({"id": "x", "result": result})); sys.exit(0)
def err(code):
    print(json.dumps({"id": "x", "error": {"code": code}}), file=sys.stderr); sys.exit(1)
cmd = args[:2]
if cmd == ["pane", "get"]:
    pane = args[2]
    if pane in os.environ.get("CLOSED", "").split():
        err("pane_not_found")
    ws, _, n = pane.partition(":p")
    out({"pane": {"pane_id": pane, "tab_id": f"{ws}:t{n}", "workspace_id": ws,
                  "agent_session": {"agent": "claude", "kind": "id", "source": "herdr:claude", "value": f"sess-{pane}"}}})
# $TABS: more tabs in the space, [{"tab_id", "label", "cwd", "agent_status", "focused"}], one pane each
tabs = json.loads(os.environ.get("TABS") or "[]")
if cmd == ["tab", "get"]:   # a tab not in $TABS is labelled $DEFAULT_LABEL (default "t1": tab_worker's name)
    t = next((t for t in tabs if t["tab_id"] == args[2]), {})
    out({"tab": {"tab_id": args[2], "label": t.get("label", os.environ.get("DEFAULT_LABEL", "t1")),
                 "agent_status": t.get("agent_status", "idle"),
                 "focused": t.get("focused", args[2] in os.environ.get("FOCUSED_TABS", "").split())}})
if cmd == ["tab", "list"]:
    out({"tabs": [{"tab_id": t["tab_id"], "label": t["label"]} for t in tabs]})
if cmd == ["pane", "list"]:
    out({"panes": [{"pane_id": t["tab_id"].replace(":t", ":p"), "tab_id": t["tab_id"], "cwd": t["cwd"]} for t in tabs]})
if cmd == ["workspace", "get"]:
    by_ws = json.loads(os.environ.get("WS_STATUS_MAP") or "{}")
    status = by_ws[args[2]] if args[2] in by_ws else os.environ.get("WS_STATUS", "idle")
    out({"workspace": {"workspace_id": args[2], "agent_status": status,
                       "focused": args[2] in os.environ.get("FOCUSED_WS", "").split()}})
if cmd == ["worktree", "list"]:   # $WORKTREES: [{"path", "branch"}], every one a linked worktree
    out({"worktrees": [{"is_linked_worktree": True, "open_workspace_id": None, **w}
                       for w in json.loads(os.environ.get("WORKTREES") or "[]")]})
err("unsupported")
'''


class RunsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp())
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        with open(os.path.join(bin_dir, "herdr"), "w") as f:
            f.write(FAKE_HERDR.replace("/usr/bin/env python3", sys.executable, 1))
        os.chmod(os.path.join(bin_dir, "herdr"), 0o755)
        self.calls_file = os.path.join(self.tmp, "calls.jsonl")
        empty = os.path.join(self.tmp, "gitconfig")
        open(empty, "w").close()
        self.env = dict(os.environ, HERDR_SKILLS_DATA_HOME=os.path.join(self.tmp, "data"), CALLS=self.calls_file,
                        PATH=bin_dir + os.pathsep + os.environ["PATH"], GIT_CONFIG_GLOBAL=empty,
                        GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
                        GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
        for k in ("HERDR_DOWN", "WS_STATUS", "WS_STATUS_MAP", "FOCUSED_WS", "FOCUSED_TABS", "TABS", "CLOSED", "WORKTREES"):
            self.env.pop(k, None)
        self.repo = self.make_repo("repo")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    # --- helpers -------------------------------------------------------------------------------------------------

    def runs(self, *args, ok=True, **env):
        r = subprocess.run([sys.executable, RUNS_PY, *args], capture_output=True, text=True,
                           env=dict(self.env, **env))
        if ok:
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)
        self.assertNotEqual(r.returncode, 0)
        return r.stderr

    def git(self, *args, cwd=None, **env):
        return subprocess.run(["git", "-C", cwd or self.repo, *args], capture_output=True, text=True, check=True,
                              env=dict(self.env, **env)).stdout.strip()

    def make_repo(self, name):
        path = os.path.join(self.tmp, name)
        subprocess.run(["git", "init", "-q", "-b", "main", path], check=True, env=self.env)
        self.write(path, "a", "a\n")
        self.git("add", "a", cwd=path)
        self.git("commit", "-q", "-m", "init", cwd=path)
        return path

    def write(self, cwd, path, text):
        with open(os.path.join(cwd, path), "w") as f:
            f.write(text)

    def commit(self, cwd, path, text, msg=None, **env):
        self.write(cwd, path, text)
        self.git("add", path, cwd=cwd)
        self.git("commit", "-q", "-m", msg or f"change {path}", cwd=cwd, **env)
        return self.git("rev-parse", "HEAD", cwd=cwd)

    def worker(self, name="w", repo=None, placement="workspace", workspace="w1", pane=None, extra=()):
        """A linked worktree on a new branch `name` from main, recorded as an open run."""
        repo = repo or self.repo
        base = self.git("rev-parse", "main", cwd=repo)
        wt = os.path.join(self.tmp, f"{os.path.basename(repo)}-{name}")
        self.git("worktree", "add", "-q", "-b", name, wt, base, cwd=repo)
        self.runs("add", "--name", name, "--root", repo, "--branch", name, "--base", base, "--from-branch", "main",
                  "--worktree", wt, "--workspace", workspace, "--pane", pane or f"{workspace}:p1",
                  "--placement", placement, *extra)
        return wt

    def add(self, name="w1", pane="w1:p1", placement="workspace"):
        """A record only: its worktree and branch `b` do not exist."""
        return self.runs("add", "--name", name, "--root", self.repo, "--branch", "b", "--base", "abc",
                         "--from-branch", "main", "--worktree", os.path.join(self.tmp, name), "--workspace", "w1",
                         "--pane", pane, "--placement", placement)

    def tab_worker(self, name="t1", pane="w1:p5"):
        """A clean linked worktree with no commits of its own, recorded as a tab worker in workspace w1."""
        return self.worker(name, placement="tab", pane=pane)

    def scan(self, *args, **env):
        return self.runs("scan", *(args or ("--root", self.repo)), **env)

    def entry(self, name="w", *args, **env):
        out = self.scan(*args, **env)
        hits = [w for w in out["workers"] if w["name"] == name]
        self.assertEqual(len(hits), 1, out)
        return hits[0]

    def called(self, *prefix):
        if not os.path.exists(self.calls_file):
            return []
        with open(self.calls_file) as f:
            calls = [json.loads(line) for line in f if line.strip()]
        return [c for c in calls if c[:len(prefix)] == list(prefix)]

    def registry(self):
        with open(os.path.join(self.tmp, "data", "herdr-parallel-worktree", "runs.json")) as f:
            return json.load(f)

    # --- add -----------------------------------------------------------------------------------------------------

    def test_add_requires_placement(self):
        # a dropped flag would record a tab worker as a workspace one, and cleanup would aim at the host space
        r = subprocess.run([sys.executable, RUNS_PY, "add", "--name", "w1", "--root", self.repo, "--branch", "b",
                            "--base", "abc", "--from-branch", "main", "--worktree", os.path.join(self.tmp, "w1"),
                            "--workspace", "w1", "--pane", "w1:p1"], capture_output=True, text=True, env=self.env)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--placement", r.stderr)
        self.assertEqual(self.add()["placement"], "workspace")

    def test_add_records_tab_placement(self):
        self.assertEqual(self.add("w1", "w1:p1", "tab")["placement"], "tab")
        self.assertEqual(self.runs("show", "--root", self.repo, "--name", "w1")[0]["placement"], "tab")

    # --- which repositories --------------------------------------------------------------------------------------

    def test_scan_needs_root_or_all(self):
        self.assertIn("--root", self.runs("scan", ok=False))
        self.assertIn("not allowed with", self.runs("scan", "--root", self.repo, "--all", ok=False))

    def test_scan_root_lists_its_repository_and_counts_the_others(self):
        other = self.make_repo("other")
        self.worker("a1")
        self.worker("b1", repo=other)
        self.worker("b2", repo=other)
        self.worker("b3", repo=other)
        self.runs("mark-cleaned", "--root", other, "--name", "b3")       # cleaned runs are not open
        out = self.scan()
        self.assertEqual([w["name"] for w in out["workers"]], ["a1"])
        self.assertEqual(out["open_elsewhere"], 2)
        out = self.scan("--all")
        self.assertEqual([(w["name"], w["root"]) for w in out["workers"]],
                         [("a1", self.repo), ("b1", other), ("b2", other)])
        self.assertEqual(out["open_elsewhere"], 0)
        # cleaning up takes each entry's own root
        self.runs("mark-cleaned", "--root", out["workers"][1]["root"], "--name", "b1")
        self.assertEqual([w["name"] for w in self.scan("--all")["workers"]], ["a1", "b2"])

    def test_scan_all_survives_a_repository_that_is_gone(self):
        other = self.make_repo("other")
        self.worker("b1", repo=other)
        self.worker("a1")
        shutil.rmtree(other)
        shutil.rmtree(os.path.join(self.tmp, "other-b1"))
        out = self.scan("--all")
        b1 = next(w for w in out["workers"] if w["name"] == "b1")
        self.assertEqual((b1["work"]["state"], b1["work"]["text"]), ("unknown", "unknown: repository not found"))
        self.assertFalse(b1["worktree_exists"])
        self.assertEqual([w["name"] for w in out["workers"]], ["b1", "a1"])

    # --- where the work stands -----------------------------------------------------------------------------------

    def work(self, name="w", *args):
        return self.entry(name, *args)["work"]

    def test_work_no_commits(self):
        self.worker()
        e = self.entry()
        self.assertEqual((e["work"]["state"], e["work"]["text"], e["work"]["commits"]), ("no_commits", "no commits", 0))
        self.assertEqual(e["last_activity"], e["created_at"])
        self.assertTrue(e["cleanable"])

    def test_work_merged(self):
        wt = self.worker()
        self.commit(wt, "f", "1\n")
        self.git("merge", "-q", "--no-ff", "--no-edit", "w")
        w = self.work()
        self.assertEqual((w["state"], w["into"], w["text"]), ("merged", "main", "merged into main"))

    def test_work_merged_into_origin_only(self):
        origin = os.path.join(self.tmp, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", origin], check=True, env=self.env)
        self.git("remote", "add", "origin", origin)
        self.git("push", "-q", "origin", "main")
        wt = self.worker()
        self.commit(wt, "f", "1\n")
        self.git("push", "-q", "origin", "w:main")                     # merged on the remote; local main is behind
        w = self.work()
        self.assertEqual((w["state"], w["into"], w["pushed"]), ("merged", "origin/main", False))

    def test_work_cherry_picked(self):
        wt = self.worker()
        self.commit(wt, "f1", "1\n")
        self.commit(wt, "f2", "2\n")
        self.commit(self.repo, "z", "z\n")                             # main moved on
        self.git("cherry-pick", "w~1", "w")
        w = self.work()
        self.assertEqual((w["state"], w["into"], w["text"], w["commits"]),
                         ("same_patches", "main", "in main by patch (cherry-pick or rebase)", 2))

    def test_work_one_commit_squash_is_by_patch(self):
        wt = self.worker()
        self.commit(wt, "f1", "1\n")
        self.git("merge", "-q", "--squash", "w")
        self.git("commit", "-q", "-m", "squash")
        self.assertEqual(self.work()["state"], "same_patches")

    def squash(self):
        wt = self.worker()
        self.commit(wt, "f1", "1\n")
        self.commit(wt, "f2", "2\n")
        self.commit(self.repo, "z", "z\n")
        self.git("merge", "-q", "--squash", "w")
        self.git("commit", "-q", "-m", "squash")
        return wt

    def test_work_squash_merged_is_by_content(self):
        self.squash()
        w = self.work()
        self.assertEqual((w["state"], w["into"], w["text"]),
                         ("same_content", "main", "in main by content (squash merge)"))

    def test_work_squash_then_main_changed_the_file(self):
        self.squash()
        self.commit(self.repo, "f1", "changed later\n")
        w = self.work()
        self.assertEqual((w["state"], w["text"]), ("not_merged", "not merged (2 commits)"))

    def test_work_cherry_picked_then_main_merged_back(self):
        # git cherry sees the picked copies on the branch side now and prints "+"; the content still matches
        wt = self.worker()
        self.commit(wt, "f1", "1\n")
        self.commit(wt, "f2", "2\n")
        self.commit(self.repo, "z", "z\n")
        self.git("cherry-pick", "w~1", "w")
        self.git("merge", "-q", "--no-edit", "main", cwd=wt)
        self.assertEqual(self.work()["state"], "same_content")

    def test_work_empty_commits_are_not_claimed_by_content(self):
        wt = self.worker()
        self.git("commit", "-q", "--allow-empty", "-m", "nothing", cwd=wt)
        w = self.work()
        self.assertEqual((w["state"], w["text"]), ("not_merged", "not merged (1 commit)"))

    def test_work_pushed_not_merged(self):
        origin = os.path.join(self.tmp, "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", origin], check=True, env=self.env)
        self.git("remote", "add", "origin", origin)
        wt = self.worker()
        self.commit(wt, "f", "1\n")
        self.git("push", "-q", "origin", "w")
        w = self.work()
        self.assertEqual((w["state"], w["text"], w["pushed"]), ("pushed", "pushed, not merged", True))
        self.commit(wt, "g", "2\n")                                     # one commit not pushed
        w = self.work()
        self.assertEqual((w["state"], w["text"], w["pushed"]), ("not_merged", "not merged (2 commits)", False))

    def test_work_not_merged_is_cleanable(self):
        wt = self.worker()
        self.commit(wt, "f1", "1\n", GIT_COMMITTER_DATE="2026-10-12T10:00:00+09:00")
        self.commit(wt, "f2", "2\n", GIT_COMMITTER_DATE="2026-10-12T11:30:00+09:00")
        e = self.entry()
        self.assertEqual((e["work"]["state"], e["work"]["commits"], e["work"]["text"]),
                         ("not_merged", 2, "not merged (2 commits)"))
        self.assertEqual(e["last_activity"], "2026-10-12T11:30:00+09:00")
        self.assertEqual((e["cleanable"], e["blockers"]), (True, []))
        self.assertEqual(e["remove_command"], "herdr worktree remove --workspace w1")

    def test_work_partly_cherry_picked_is_not_merged(self):
        wt = self.worker()
        self.commit(wt, "f1", "1\n")
        self.commit(wt, "f2", "2\n")
        self.commit(self.repo, "z", "z\n")                             # so the pick is a new commit, not w~1
        self.git("cherry-pick", "w~1")
        self.assertEqual(self.work()["text"], "not merged (2 commits)")

    def test_branch_and_worktree_gone(self):
        wt = self.worker()
        self.git("worktree", "remove", wt)
        self.git("branch", "-D", "w")
        e = self.entry()
        self.assertEqual((e["work"]["state"], e["work"]["text"]), ("unknown", "unknown: branch not found"))
        self.assertEqual((e["worktree_exists"], e["remove_command"], e["cleanable"]), (False, None, True))
        self.assertEqual(e["last_activity"], e["created_at"])

    # --- what blocks cleanup -------------------------------------------------------------------------------------

    def test_working_or_blocked_worker_is_not_cleanable(self):
        self.worker()
        for status in ("working", "blocked"):
            with self.subTest(status=status):
                e = self.entry(WS_STATUS=status)
                self.assertEqual((e["cleanable"], e["blockers"], e["agent_status"]), (False, [status], status))

    def test_viewed_workspace_is_not_cleanable(self):
        self.worker()
        e = self.entry(FOCUSED_WS="w1")
        self.assertEqual(e["blockers"], ["user is viewing its workspace"])

    def test_uncommitted_changes_block(self):
        wt = self.worker()
        self.write(wt, "a", "edited\n")
        self.write(wt, "new", "x\n")
        self.assertEqual(self.entry()["blockers"], ["2 uncommitted changes"])
        os.remove(os.path.join(wt, "new"))
        self.assertEqual(self.entry()["blockers"], ["1 uncommitted change"])

    def test_git_status_failure_blocks(self):
        plain = os.path.join(self.tmp, "plain")                        # a directory git does not know
        os.makedirs(plain)
        self.runs("add", "--name", "w", "--root", self.repo, "--branch", "main", "--base", "main", "--from-branch",
                  "main", "--worktree", plain, "--workspace", "w1", "--pane", "w1:p1", "--placement", "workspace")
        self.assertEqual(self.entry()["blockers"], ["git status failed"])

    def test_commits_on_a_detached_head_block(self):
        wt = self.worker()
        self.git("checkout", "-q", "--detach", cwd=wt)
        self.commit(wt, "f", "1\n")
        e = self.entry()
        self.assertEqual(e["blockers"], ["1 commit on no branch (detached HEAD)"])
        self.assertEqual(e["work"]["state"], "no_commits")              # the branch itself has none

    def test_herdr_unavailable_blocks(self):
        self.worker()
        e = self.entry(HERDR_DOWN="1")
        self.assertEqual(e["blockers"], ["herdr could not be queried (herdr_unavailable)"])
        self.assertEqual((e["cleanable"], e["remove_command"]), (False, None))
        self.assertEqual(e["work"]["state"], "no_commits")              # git facts are still reported

    def test_worktree_gone_is_only_a_record(self):
        wt = self.worker()
        self.git("worktree", "remove", wt)
        e = self.entry()
        self.assertEqual((e["worktree_exists"], e["remove_command"], e["cleanable"]), (False, None, True))
        self.assertEqual(e["work"]["state"], "no_commits")              # the branch is still there
        # a live worker still blocks, though nothing would be deleted (the old `stale` skipped this)
        e = self.entry(WS_STATUS="working")
        self.assertEqual((e["cleanable"], e["blockers"]), (False, ["working"]))

    def test_untracked_worktrees_are_listed_with_their_root(self):
        wt = self.worker()
        out = self.scan(WORKTREES=json.dumps([{"path": wt, "branch": "w"},
                                              {"path": "/elsewhere/hand-made", "branch": "x"}]))
        self.assertEqual(out["untracked_worktrees"],
                         [{"root": self.repo, "path": "/elsewhere/hand-made", "branch": "x", "workspace": None}])

    def test_scan_sorts_by_status(self):
        # the cleanup list shows done first, then working, then idle, then anything else; registry order within one
        statuses = {"a": "idle", "b": "blocked", "c": "done", "d": "working", "e": None, "f": "done", "g": "idle"}
        for name in statuses:
            self.worker(name, workspace=f"ws-{name}")
        out = self.scan(WS_STATUS_MAP=json.dumps({f"ws-{n}": s for n, s in statuses.items()}))
        self.assertEqual([(w["name"], w["agent_status"]) for w in out["workers"]],
                         [("c", "done"), ("f", "done"), ("d", "working"), ("a", "idle"), ("g", "idle"),
                          ("b", "blocked"), ("e", None)])

    def test_scan_all_sorts_across_repositories(self):
        other = self.make_repo("other")
        self.worker("a1", workspace="wa")
        self.worker("b1", repo=other, workspace="wb")
        out = self.scan("--all", WS_STATUS_MAP=json.dumps({"wa": "idle", "wb": "done"}))
        self.assertEqual([w["name"] for w in out["workers"]], ["b1", "a1"])

    # --- what the worker is for ----------------------------------------------------------------------------------

    def test_summary_from_add(self):
        self.worker(extra=("--summary", "Fix the `flaky` test"))
        self.assertEqual(self.registry()[0]["summary"], "Fix the `flaky` test")
        self.assertEqual(self.entry()["summary"], "Fix the `flaky` test")

    def test_summary_of_an_older_run_comes_from_its_brief(self):
        brief = os.path.join(self.tmp, "w-brief.md")
        self.write(self.tmp, brief, "# [w] Make the list pickable\n\n## Goal\nx\n")
        self.worker(extra=("--brief", brief))
        runs = self.registry()
        del runs[0]["summary"]                                         # a record written before --summary
        with open(os.path.join(self.tmp, "data", "herdr-parallel-worktree", "runs.json"), "w") as f:
            json.dump(runs, f)
        self.assertEqual(self.entry()["summary"], "Make the list pickable")
        self.write(self.tmp, brief, "# Some other title\n")
        self.assertIsNone(self.entry()["summary"])
        os.remove(brief)
        self.assertIsNone(self.entry()["summary"])

    def test_no_summary_and_no_brief(self):
        self.worker()
        self.assertIsNone(self.entry()["summary"])

    # --- tab workers ---------------------------------------------------------------------------------------------

    def test_scan_tab_worker_is_judged_by_its_tab(self):
        wt = self.tab_worker()
        c = self.entry("t1")
        self.assertTrue(c["cleanable"], c)
        self.assertEqual(c["remove_command"], f"git -C {self.repo} worktree remove {wt} && herdr tab close w1:t5")
        self.assertEqual((c["placement"], c["tab"], c["tab_open"]), ("tab", "w1:t5", True))
        self.assertEqual(self.called("workspace", "get"), [])

    def test_scan_closed_tab_removes_only_the_worktree(self):
        wt = self.tab_worker()
        c = self.entry("t1", CLOSED="w1:p5")
        self.assertEqual(c["remove_command"], f"git -C {self.repo} worktree remove {wt}")
        self.assertFalse(c["tab_open"])

    def test_scan_never_closes_a_tab_that_is_no_longer_the_workers(self):
        # the recorded pane's tab now carries another label (an id reused after a herdr restart, or a tab the
        # user took over): it is not the worker's tab any more, so it is neither judged nor closed
        wt = self.tab_worker()
        c = self.entry("t1", DEFAULT_LABEL="notes", FOCUSED_TABS="w1:t5")
        self.assertEqual(c["remove_command"], f"git -C {self.repo} worktree remove {wt}")
        self.assertFalse(c["tab_open"])
        self.assertTrue(c["cleanable"])

    def test_scan_focused_tab_is_kept(self):
        self.tab_worker()
        c = self.entry("t1", FOCUSED_TABS="w1:t5")
        self.assertEqual((c["cleanable"], c["blockers"]), (False, ["user is viewing its tab"]))

    def plan_tabs(self, wt, status="idle", focused=False):
        return json.dumps([
            {"tab_id": "w1:t7", "label": "p-rev", "cwd": os.path.join(wt, "sub"), "agent_status": status,
             "focused": focused},                                                  # the plan's reviewer tab
            {"tab_id": "w1:t8", "label": "notes", "cwd": wt, "agent_status": "idle"},   # the user's own tab
            {"tab_id": "w1:t9", "label": "p-rev", "cwd": self.tmp, "agent_status": "idle"},  # elsewhere
        ])

    def test_scan_tab_plan_keeps_a_working_reviewer_tab(self):
        wt = self.tab_worker("p-impl")
        for status, focused, reason in (("working", False, "p-rev is working"),
                                        ("blocked", False, "p-rev is blocked"),
                                        ("idle", True, "user is viewing p-rev")):
            with self.subTest(status=status, focused=focused):
                c = self.entry("p-impl", TABS=self.plan_tabs(wt, status, focused), DEFAULT_LABEL="p-impl")
                self.assertEqual((c["cleanable"], c["blockers"]), (False, [reason]))

    def test_scan_tab_plan_closes_its_reviewer_tab_too(self):
        wt = self.tab_worker("p-impl")
        c = self.entry("p-impl", TABS=self.plan_tabs(wt), DEFAULT_LABEL="p-impl")
        self.assertEqual(c["remove_command"],
                         f"git -C {self.repo} worktree remove {wt} && herdr tab close w1:t5 && herdr tab close w1:t7")

    def test_record_without_placement_scans_as_workspace(self):
        self.tab_worker()
        runs = self.registry()
        del runs[0]["placement"]                                       # a record written before 0.9.0
        with open(os.path.join(self.tmp, "data", "herdr-parallel-worktree", "runs.json"), "w") as f:
            json.dump(runs, f)
        c = self.entry("t1")
        self.assertTrue(c["remove_command"].startswith("herdr worktree remove --workspace w1"), c)
        self.assertEqual(c["placement"], "workspace")
        self.assertTrue(self.called("workspace", "get"))

    # --- mark-open / relocate ------------------------------------------------------------------------------------

    def test_relocate_and_mark_open_take_placement(self):
        self.add()
        self.assertEqual(self.runs("relocate", "--root", self.repo, "--name", "w1", "--workspace", "w2", "--pane",
                                   "w2:p1", "--placement", "tab")["placement"], "tab")
        self.assertEqual(self.runs("relocate", "--root", self.repo, "--name", "w1", "--workspace", "w2", "--pane",
                                   "w2:p1")["placement"], "tab")                      # kept when not given
        self.runs("mark-cleaned", "--root", self.repo, "--name", "w1")
        self.assertEqual(self.runs("mark-open", "--root", self.repo, "--name", "w1", "--workspace", "w3", "--pane",
                                   "w3:p2", "--placement", "workspace")["placement"], "workspace")

    def test_relocate_updates_an_open_run_whose_workspace_moved(self):
        self.add()
        r = self.runs("relocate", "--root", self.repo, "--name", "w1", "--workspace", "w24", "--pane", "w24:p1")
        self.assertEqual((r["state"], r["workspace"], r["pane"], r["session_id"]),
                         ("open", "w24", "w24:p1", "sess-w24:p1"))
        shown = self.runs("show", "--root", self.repo, "--name", "w1")
        self.assertEqual([(x["workspace"], x["pane"]) for x in shown], [("w24", "w24:p1")])

    def test_relocate_needs_an_open_run(self):
        self.assertIn("no open run named nope", self.runs("relocate", "--root", self.repo, "--name", "nope",
                                                          "--workspace", "w2", "--pane", "w2:p1", ok=False))
        self.add()
        self.runs("mark-cleaned", "--root", self.repo, "--name", "w1")
        self.assertIn("no open run named w1", self.runs("relocate", "--root", self.repo, "--name", "w1",
                                                        "--workspace", "w2", "--pane", "w2:p1", ok=False))

    def test_mark_open_still_only_reopens_cleaned_runs(self):
        self.add()
        self.assertIn("no cleaned run named w1", self.runs("mark-open", "--root", self.repo, "--name", "w1",
                                                           "--workspace", "w2", "--pane", "w2:p1", ok=False))


if __name__ == "__main__":
    unittest.main()
