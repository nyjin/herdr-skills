import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
from adf import to_markdown  # noqa: E402


def t(text, *marks):
    n = {"type": "text", "text": text}
    if marks:
        n["marks"] = [m if isinstance(m, dict) else {"type": m} for m in marks]
    return n


def p(*inline):
    return {"type": "paragraph", "content": list(inline)}


def doc(*blocks):
    return {"type": "doc", "version": 1, "content": list(blocks)}


def li(*blocks):
    return {"type": "listItem", "content": list(blocks)}


class AdfTest(unittest.TestCase):
    def test_blocks(self):
        md = to_markdown(doc(
            {"type": "heading", "attrs": {"level": 2}, "content": [t("제목")]},
            p(t("첫 문단")), p(t("둘째 문단")),
            {"type": "bulletList", "content": [
                li(p(t("a")), {"type": "orderedList", "content": [li(p(t("a1")))]}),
                li(p(t("b")))]},
            {"type": "codeBlock", "attrs": {"language": "sql"}, "content": [t("select 1;")]},
            {"type": "blockquote", "content": [p(t("인용"))]},
            {"type": "rule"},
            {"type": "panel", "attrs": {"panelType": "info"}, "content": [p(t("패널"))]},
            {"type": "expand", "attrs": {"title": "더보기"}, "content": [p(t("숨김"))]},
            {"type": "taskList", "content": [
                {"type": "taskItem", "attrs": {"state": "TODO"}, "content": [t("할 일")]},
                {"type": "taskItem", "attrs": {"state": "DONE"}, "content": [t("한 일")]}]},
            {"type": "decisionList", "content": [
                {"type": "decisionItem", "attrs": {"state": "DECIDED"}, "content": [t("결정")]}]},
        ))
        for expected in ["## 제목", "첫 문단\n\n둘째 문단", "- a\n  1. a1\n- b", "```sql\nselect 1;\n```",
                         "> 인용", "\n---\n", "> **ℹ️** 패널", "**▸ 더보기**\n\n숨김",
                         "- [ ] 할 일\n- [x] 한 일", "- ✔︎ 결정"]:
            self.assertIn(expected, md)

    def test_inline(self):
        md = to_markdown(doc(p(
            t("굵게", "strong"), t(" "), t("기울임", "em"), t(" "), t("코드", "code"), t(" "),
            t("취소", "strike"), t(" "), t("링크", {"type": "link", "attrs": {"href": "https://x"}}), t(" "),
            t("밑줄", "underline", {"type": "textColor", "attrs": {"color": "#f00"}}),
            {"type": "hardBreak"},
            {"type": "mention", "attrs": {"text": "@홍길동"}}, t(" "),
            {"type": "inlineCard", "attrs": {"url": "https://card"}}, t(" "),
            {"type": "status", "attrs": {"text": "DONE"}}, t(" "),
            {"type": "date", "attrs": {"timestamp": "1794528000000"}}, t(" "),
            {"type": "emoji", "attrs": {"shortName": ":smile:"}}),
            {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"alt": "shot.png"}}]},
        ))
        for expected in ["**굵게**", "_기울임_", "`코드`", "~~취소~~", "[링크](https://x)", "밑줄\n",
                         "@홍길동", "<https://card>", "`[DONE]`", "2026-11-13", ":smile:", "[첨부: shot.png]"]:
            self.assertIn(expected, md)

    def test_table_cell_escapes(self):
        cell = lambda kind, *inl: {"type": kind, "content": [p(*inl)]}
        md = to_markdown(doc({"type": "table", "content": [
            {"type": "tableRow", "content": [cell("tableHeader", t("이름")), cell("tableHeader", t("값"))]},
            {"type": "tableRow", "content": [cell("tableCell", t("a|b")),
                                             {"type": "tableCell", "content": [p(t("줄1")), p(t("줄2"))]}]},
        ]}))
        self.assertIn("| 이름 | 값 |\n| --- | --- |\n| a\\|b | 줄1<br>줄2 |", md)

    def test_unknown_node_keeps_text(self):
        self.assertIn("abc", to_markdown(doc({"type": "mystery", "content": [t("abc")]})))

    def test_extension(self):
        md = to_markdown(doc({"type": "extension", "attrs": {"extensionKey": "toc"}}))
        self.assertIn("[Confluence 매크로: toc]", md)

    def test_string_and_none(self):
        self.assertEqual(to_markdown(None), "")
        self.assertIn("x", to_markdown('{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"x"}]}]}'))


if __name__ == "__main__":
    unittest.main()
