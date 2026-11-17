"""scripts/release.sh picks the next skills release from the commits since the last v<semver> tag that change skills/.
Each test builds a throwaway git repository and runs the script in it, with a fake gh first on PATH that records how
it was called, so nothing is ever published.
Run from the repo root: python3 -m unittest discover -s scripts/tests -v
"""
import os
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "release.sh")


class ReleaseTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp)
        self.repo = os.path.join(tmp, "repo")
        os.makedirs(self.repo)
        bin_dir = os.path.join(tmp, "bin")
        os.makedirs(bin_dir)
        self.gh_log = os.path.join(tmp, "gh.log")
        with open(os.path.join(bin_dir, "gh"), "w") as f:
            f.write('#!/bin/sh\necho "$*" >> "%s"\n' % self.gh_log)
        os.chmod(os.path.join(bin_dir, "gh"), 0o755)
        # Neither the caller's git config (signing, hooks, default branch) nor its GIT_* variables (a hook's
        # GIT_DIR) may reach the throwaway repository; CI runners have no git identity, so set one.
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        env.update(PATH=bin_dir + os.pathsep + env.get("PATH", ""), GIT_CONFIG_GLOBAL=os.devnull,
                   GIT_CONFIG_NOSYSTEM="1", GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com",
                   GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.com")
        self.env = env
        self.git("init", "-q", "-b", "main")
        # v0.10.0 sorts before v0.9.0 as text: a script that took the wrong one would count this feat.
        self.commit("feat: first skill", "skills/a/SKILL.md")
        self.git("tag", "v0.9.0")
        self.commit("feat: second skill", "skills/b/SKILL.md")
        self.git("tag", "v0.10.0")
        self.git("tag", "not-a-release")

    def git(self, *args):
        subprocess.run(["git", *args], cwd=self.repo, env=self.env, check=True, capture_output=True)

    def commit(self, subject, path, body=None):
        full = os.path.join(self.repo, path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "a") as f:
            f.write(subject + "\n")
        self.git("add", path)
        self.git("commit", "-q", "-m", subject, *(["-m", body] if body else []))

    def release(self, *args):
        r = subprocess.run(["bash", SCRIPT, *args], cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r.stdout

    def gh_calls(self):
        if not os.path.exists(self.gh_log):
            return []
        with open(self.gh_log) as f:
            return f.read().splitlines()

    def assertNothing(self, out):
        self.assertIn("nothing to release", out)
        self.assertNotIn("next version", out)
        self.assertEqual(self.gh_calls(), [])

    def assertNext(self, out, version):
        self.assertIn("last release: v0.10.0", out)
        self.assertIn("next version: " + version, out)
        self.assertEqual(self.gh_calls(), [])  # --dry-run

    def test_no_commit_since_the_last_release(self):
        self.assertNothing(self.release("--dry-run"))

    def test_docs_change_in_skills_publishes_nothing(self):
        self.commit("docs: reword the skill", "skills/a/SKILL.md")
        self.commit("test(a): cover more", "skills/a/tests/test_a.py")
        out = self.release("--dry-run")
        self.assertIn("commits since v0.10.0 that change skills/: 2", out)
        self.assertNothing(out)

    def test_fix_is_a_patch(self):
        self.commit("fix: a typo in a command", "skills/a/SKILL.md")
        self.assertNext(self.release("--dry-run"), "v0.10.1")

    def test_perf_is_a_patch(self):
        self.commit("perf(a): faster hook", "skills/a/scripts/hook.py")
        self.assertNext(self.release("--dry-run"), "v0.10.1")

    def test_feat_is_a_minor_whatever_else_came(self):
        self.commit("fix: one", "skills/a/SKILL.md")
        self.commit("feat(b): a new option", "skills/b/SKILL.md")
        self.commit("docs: two", "skills/b/SKILL.md")
        self.assertNext(self.release("--dry-run"), "v0.11.0")

    def test_breaking_subject_is_a_major(self):
        self.commit("feat: one", "skills/a/SKILL.md")
        self.commit("refactor(a)!: rename the command", "skills/a/SKILL.md")
        self.assertNext(self.release("--dry-run"), "v1.0.0")

    def test_breaking_footer_is_a_major(self):
        self.commit("feat: new layout", "skills/a/SKILL.md", body="BREAKING CHANGE: the old path is gone")
        self.assertNext(self.release("--dry-run"), "v1.0.0")

    def test_feat_outside_skills_publishes_nothing(self):
        self.commit("feat: a herdr plugin", "herdr-plugins/p/herdr-plugin.toml")
        self.commit("feat!: a new install script", "install.sh")
        out = self.release("--dry-run")
        self.assertIn("no commit since v0.10.0 changes skills/", out)
        self.assertNothing(out)

    def test_only_the_skills_commits_count(self):
        self.commit("feat: a herdr plugin", "herdr-plugins/p/herdr-plugin.toml")
        self.commit("fix: a skill", "skills/a/SKILL.md")
        self.assertNext(self.release("--dry-run"), "v0.10.1")

    def test_commits_on_a_merged_branch_count(self):
        self.git("checkout", "-q", "-b", "topic")
        self.commit("feat: from a branch", "skills/a/SKILL.md")
        self.git("checkout", "-q", "main")
        self.commit("docs: on main", "README.md")
        self.git("merge", "-q", "--no-ff", "-m", "Merge branch 'topic'", "topic")
        self.assertNext(self.release("--dry-run"), "v0.11.0")

    def test_no_tag_publishes_nothing(self):
        for tag in ("v0.9.0", "v0.10.0", "not-a-release"):
            self.git("tag", "-d", tag)
        self.commit("feat: something", "skills/a/SKILL.md")
        out = self.release("--dry-run")
        self.assertIn("no release tag", out)
        self.assertNothing(out)

    def add_origin(self):
        origin = os.path.join(os.path.dirname(self.repo), "origin.git")
        subprocess.run(["git", "init", "-q", "--bare", origin], env=self.env, check=True, capture_output=True)
        self.git("remote", "add", "origin", origin)
        self.git("push", "-q", "origin", "main")

    def test_without_dry_run_it_publishes_with_gh(self):
        self.commit("feat: a new option", "skills/a/SKILL.md")
        self.add_origin()
        self.release()
        self.assertEqual(self.gh_calls(), ["skill publish --tag v0.11.0"])

    def test_branch_moved_on_publishes_nothing(self):
        # gh skill publish tags the branch tip on GitHub; a newer push there is not what this run counted or checked.
        self.commit("feat: a new option", "skills/a/SKILL.md")
        self.commit("fix: pushed while this run was checking", "skills/a/SKILL.md")
        self.add_origin()
        self.git("reset", "-q", "--hard", "HEAD~1")
        out = self.release()
        self.assertIn("next version: v0.11.0", out)
        self.assertIn("newer push", out)
        self.assertEqual(self.gh_calls(), [])

    def test_without_dry_run_nothing_to_release_calls_no_gh(self):
        self.commit("docs: reword", "skills/a/SKILL.md")
        self.assertIn("nothing to release", self.release())
        self.assertEqual(self.gh_calls(), [])

    def test_unknown_argument_is_refused(self):
        r = subprocess.run(["bash", SCRIPT, "--publish"], cwd=self.repo, env=self.env, capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("usage", r.stderr)
        self.assertEqual(self.gh_calls(), [])


if __name__ == "__main__":
    unittest.main()
