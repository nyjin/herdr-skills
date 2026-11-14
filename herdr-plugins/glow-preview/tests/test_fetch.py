import json
import os
import sys
import tempfile
import unittest
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "scripts"))
import fetch  # noqa: E402
import targets  # noqa: E402

JIRA = "https://example.atlassian.net/browse/ABC-1"
CONF = "https://example.atlassian.net/wiki/spaces/SPACE/pages/123/Title"
PR = "https://github.com/o/r/pull/7"


class ClassifyTest(unittest.TestCase):
    def test_classify(self):
        self.assertEqual(targets.classify(JIRA), {"kind": "jira", "url": JIRA, "key": "ABC-1"})
        self.assertEqual(targets.classify(CONF)["page_id"], "123")
        self.assertIsNone(targets.classify("https://example.atlassian.net/wiki/x/AbCd")["page_id"])
        self.assertEqual(targets.classify(PR + "/files"),
                         {"kind": "github_pr", "url": PR, "repo": "o/r", "number": "7"})
        self.assertEqual(targets.classify("(src/a.py:42:3)"), {"kind": "path", "text": "src/a.py", "line": 42})
        self.assertEqual(targets.classify("docs/a.md"), {"kind": "path", "text": "docs/a.md", "line": None})


TOOLS = ("acli", "jira", "cme", "gh", "claude")


class FetchTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.bin = os.path.join(self.tmp.name, "bin")
        os.makedirs(self.bin)
        for name in TOOLS:
            os.symlink(os.path.join(HERE, "fake_cli.py"), os.path.join(self.bin, name))
        self.log = os.path.join(self.tmp.name, "log")
        self.env = mock.patch.dict(os.environ, {"PATH": f"{self.bin}:/usr/bin:/bin", "FAKE_LOG": self.log,
                                                "FAKE_MODE": "ok", "GLOWP_CACHE_DIR": self.tmp.name})
        self.env.start()
        for k in [k for k in os.environ if k.startswith("FAKE_MODE_")] + ["GH_TOKEN"]:
            os.environ.pop(k, None)

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def calls(self):
        if not os.path.exists(self.log):
            return []
        with open(self.log) as f:
            return [json.loads(line) for line in f]

    def tools_called(self):
        return [c[0] for c in self.calls()]

    def uninstall(self, *names):
        for n in names:
            os.remove(os.path.join(self.bin, n))

    def test_jira_acli_first(self):
        md, ok, used = fetch.fetch_markdown(JIRA)
        self.assertEqual((ok, used), (True, "acli"))
        for s in ["# ABC-1 요약 제목", "진행 중", "홍길동", "본문 내용", "## 코멘트", "박영희", "코멘트 하나"]:
            self.assertIn(s, md)
        self.assertEqual(self.tools_called(), ["acli"])

    def test_jira_falls_to_jira_cli(self):
        os.environ["FAKE_MODE_acli"] = "auth"
        md, ok, used = fetch.fetch_markdown(JIRA)
        self.assertEqual((ok, used), (True, "jira-cli"))
        self.assertIn(["jira", "issue", "view", "ABC-1", "--raw"], self.calls())
        self.assertIn("# ABC-1 요약 제목", md)

    def test_jira_skips_missing_tools_to_mcp(self):
        self.uninstall("acli", "jira")
        md, ok, used = fetch.fetch_markdown(JIRA)
        self.assertEqual((ok, used), (True, "Atlassian MCP"))
        self.assertEqual(self.tools_called(), ["claude"])
        allowed = self.calls()[0][self.calls()[0].index("--allowedTools") + 1].split(",")
        self.assertIn("mcp__claude_ai_Atlassian__getJiraIssue", allowed)  # stock claude.ai connector
        self.assertIn("mcp__claude_ai_Atlassian_MCP__getJiraIssue", allowed)  # a connector named "Atlassian MCP"

    def test_confluence_cme(self):
        md, ok, used = fetch.fetch_markdown(CONF)
        self.assertEqual((ok, used), (True, "cme"))
        self.assertIn("# 페이지 제목", md)
        self.assertIn(CONF, md)
        self.assertEqual(self.calls()[0][:2], ["cme", "pages"])
        self.assertIn("Parent\n", md)  # breadcrumb link to ../Parent.md keeps its text only
        self.assertNotIn("../Parent.md", md)

    def test_confluence_cme_exports_nothing_then_mcp(self):
        os.environ["FAKE_MODE_cme"] = "empty"
        md, ok, used = fetch.fetch_markdown(CONF)
        self.assertEqual((ok, used), (True, "Atlassian MCP"))
        self.assertEqual(self.tools_called(), ["cme", "claude"])

    def test_nothing_installed_guides_every_install(self):
        self.uninstall("acli", "jira", "claude")
        md, ok, used = fetch.fetch_markdown(JIRA)
        self.assertEqual((ok, used), (False, None))
        self.assertIn("설치되어 있지 않습니다", md)
        for s in ["brew install acli", "jira-cli/jira-cli", "Atlassian 커넥터"]:
            self.assertIn(s, md)
        self.uninstall("cme")
        md, _, _ = fetch.fetch_markdown(CONF)
        self.assertIn("uv tool install confluence-markdown-exporter", md)

    def test_all_fail_lists_each_tool(self):
        os.environ["FAKE_MODE"] = "auth"
        md, ok, _ = fetch.fetch_markdown(JIRA)
        self.assertFalse(ok)
        for s in ["| acli | 로그인 필요 | `acli jira auth login` |", "| jira-cli | 로그인 필요", "| Atlassian MCP |"]:
            self.assertIn(s, md)

    def test_pr_ok(self):
        md, ok, used = fetch.fetch_markdown(PR)
        self.assertEqual((ok, used), (True, "gh"))
        view = next(c for c in self.calls() if c[1:3] == ["pr", "view"])
        self.assertEqual(view[view.index("-R") + 1], "o/r")
        for s in ["# PR 제목 (#7)", "OPEN", "alice", "PR 설명", "rev", "APPROVED", "좋아요",
                  "src/a.py:12", "여기 이름이 어색해요", "일반 코멘트", "src/a.py (+3/-1)"]:
            self.assertIn(s, md)

    def test_pr_notfound_guides(self):
        os.environ["FAKE_MODE"] = "notfound"
        md, ok, _ = fetch.fetch_markdown(PR)
        self.assertFalse(ok)
        self.assertIn("gh auth status", md)

    def test_timeout_moves_on(self):
        os.environ["FAKE_MODE_acli"] = "hang"
        md, ok, used = fetch.fetch_markdown(JIRA, timeout=1)
        self.assertEqual((ok, used), (True, "jira-cli"))

    def test_pr_api_account_fallback(self):
        os.environ["FAKE_MODE"] = "api404first"
        md, ok, _ = fetch.fetch_markdown(PR)
        self.assertTrue(ok)
        self.assertIn("여기 이름이 어색해요", md)
        self.assertIn(["gh", "auth", "token", "--user", "b"], self.calls())

    def test_cache_path(self):
        self.assertTrue(fetch.cache_path(JIRA).startswith(self.tmp.name))
        self.assertTrue(fetch.cache_path(JIRA).endswith(".md"))
        self.assertNotEqual(fetch.cache_path(JIRA), fetch.cache_path(CONF))


if __name__ == "__main__":
    unittest.main()
