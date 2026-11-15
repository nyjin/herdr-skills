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
            {"type": "heading", "attrs": {"level": 2}, "content": [t("Title")]},
            p(t("First paragraph")), p(t("Second paragraph")),
            {"type": "bulletList", "content": [
                li(p(t("a")), {"type": "orderedList", "content": [li(p(t("a1")))]}),
                li(p(t("b")))]},
            {"type": "codeBlock", "attrs": {"language": "sql"}, "content": [t("select 1;")]},
            {"type": "blockquote", "content": [p(t("Quote"))]},
            {"type": "rule"},
            {"type": "panel", "attrs": {"panelType": "info"}, "content": [p(t("Panel"))]},
            {"type": "expand", "attrs": {"title": "More"}, "content": [p(t("Hidden"))]},
            {"type": "taskList", "content": [
                {"type": "taskItem", "attrs": {"state": "TODO"}, "content": [t("To do")]},
                {"type": "taskItem", "attrs": {"state": "DONE"}, "content": [t("Done")]}]},
            {"type": "decisionList", "content": [
                {"type": "decisionItem", "attrs": {"state": "DECIDED"}, "content": [t("Decision")]}]},
        ))
        for expected in ["## Title", "First paragraph\n\nSecond paragraph", "- a\n  1. a1\n- b", "```sql\nselect 1;\n```",
                         "> Quote", "\n---\n", "> **ℹ️** Panel", "**▸ More**\n\nHidden",
                         "- [ ] To do\n- [x] Done", "- ✔︎ Decision"]:
            self.assertIn(expected, md)

    def test_inline(self):
        md = to_markdown(doc(p(
            t("bold", "strong"), t(" "), t("italic", "em"), t(" "), t("code", "code"), t(" "),
            t("struck", "strike"), t(" "), t("link", {"type": "link", "attrs": {"href": "https://x"}}), t(" "),
            t("underlined", "underline", {"type": "textColor", "attrs": {"color": "#f00"}}),
            {"type": "hardBreak"},
            {"type": "mention", "attrs": {"text": "@Jane Doe"}}, t(" "),
            {"type": "inlineCard", "attrs": {"url": "https://card"}}, t(" "),
            {"type": "status", "attrs": {"text": "DONE"}}, t(" "),
            {"type": "date", "attrs": {"timestamp": "1794528000000"}}, t(" "),
            {"type": "emoji", "attrs": {"shortName": ":smile:"}}),
            {"type": "mediaSingle", "content": [{"type": "media", "attrs": {"alt": "shot.png"}}]},
        ))
        for expected in ["**bold**", "_italic_", "`code`", "~~struck~~", "[link](https://x)", "underlined\n",
                         "@Jane Doe", "<https://card>", "`[DONE]`", "2026-11-13", ":smile:", "[Attachment: shot.png]"]:
            self.assertIn(expected, md)

    def test_table_cell_escapes(self):
        cell = lambda kind, *inl: {"type": kind, "content": [p(*inl)]}
        md = to_markdown(doc({"type": "table", "content": [
            {"type": "tableRow", "content": [cell("tableHeader", t("Name")), cell("tableHeader", t("Value"))]},
            {"type": "tableRow", "content": [cell("tableCell", t("a|b")),
                                             {"type": "tableCell", "content": [p(t("line 1")), p(t("line 2"))]}]},
        ]}))
        self.assertIn("| Name | Value |\n| --- | --- |\n| a\\|b | line 1<br>line 2 |", md)

    def test_unknown_node_keeps_text(self):
        self.assertIn("abc", to_markdown(doc({"type": "mystery", "content": [t("abc")]})))

    def test_extension(self):
        md = to_markdown(doc({"type": "extension", "attrs": {"extensionKey": "toc"}}))
        self.assertIn("[Confluence macro: toc]", md)

    def test_string_and_none(self):
        self.assertEqual(to_markdown(None), "")
        self.assertIn("x", to_markdown('{"type":"doc","content":[{"type":"paragraph","content":[{"type":"text","text":"x"}]}]}'))


if __name__ == "__main__":
    unittest.main()
