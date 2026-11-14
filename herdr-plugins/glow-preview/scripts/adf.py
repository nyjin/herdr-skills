"""Atlassian Document Format (Jira descriptions/comments, Confluence atlas_doc_format) to markdown.

Covers the node and mark types seen across the user's live Jira and Confluence links. Styling
marks markdown cannot express (colour, underline, alignment, …) are dropped; an unknown node keeps
its children's text, so nothing readable is lost.
"""
import datetime
import json

PANEL_ICON = {"info": "ℹ️", "note": "📝", "warning": "⚠️", "error": "⛔", "success": "✅", "tip": "💡"}


def to_markdown(doc):
    if not doc:
        return ""
    if isinstance(doc, str):
        doc = json.loads(doc)
    return _blocks(doc.get("content") or [], "").strip() + "\n"


def _blocks(nodes, indent):
    out = []
    for n in nodes:
        md = _block(n, indent)
        if md.strip():
            out.append(md.rstrip("\n"))
    return "\n\n".join(out)


def _prefix(text, first, rest):
    lines = text.split("\n")
    return "\n".join([first + lines[0]] + [(rest + l if l else l) for l in lines[1:]])


def _list(n, indent, ordered):
    items = []
    for i, item in enumerate(n.get("content") or [], 1):
        marker = f"{i}. " if ordered else "- "
        body = _blocks(item.get("content") or [], "").replace("\n\n", "\n")
        items.append(_prefix(body, marker, " " * len(marker)))
    return "\n".join(items)


def _block(n, indent):
    kind = n.get("type")
    attrs = n.get("attrs") or {}
    content = n.get("content") or []
    if kind == "paragraph":
        return _inline(content)
    if kind == "heading":
        return "#" * int(attrs.get("level", 1)) + " " + _inline(content)
    if kind in ("bulletList", "orderedList"):
        return _list(n, indent, kind == "orderedList")
    if kind == "codeBlock":
        return f"```{attrs.get('language') or ''}\n{''.join(c.get('text', '') for c in content)}\n```"
    if kind == "blockquote":
        return _prefix(_blocks(content, ""), "> ", "> ")
    if kind == "rule":
        return "---"
    if kind == "panel":
        icon = PANEL_ICON.get(attrs.get("panelType"), "ℹ️")
        return _prefix(f"**{icon}** " + _blocks(content, ""), "> ", "> ")
    if kind in ("expand", "nestedExpand"):
        return f"**▸ {attrs.get('title') or '펼치기'}**\n\n" + _blocks(content, "")
    if kind == "taskList":
        return "\n".join(_block(c, indent) for c in content)
    if kind == "taskItem":
        return ("- [x] " if attrs.get("state") == "DONE" else "- [ ] ") + _inline(content)
    if kind == "decisionList":
        return "\n".join("- ✔︎ " + _inline(c.get("content") or []) for c in content)
    if kind == "table":
        return _table(content)
    if kind in ("mediaSingle", "mediaGroup"):
        return " ".join(_media(c) for c in content)
    if kind in ("media", "mediaInline"):
        return _media(n)
    if kind in ("blockCard", "embedCard"):
        return f"<{attrs.get('url', '')}>"
    if kind in ("extension", "bodiedExtension"):
        return f"[Confluence 매크로: {attrs.get('extensionKey', '?')}]" + (
            "\n\n" + _blocks(content, "") if content else "")
    if any("text" in c for c in content):  # unknown inline container
        return _inline(content)
    return _blocks(content, indent)


def _media(n):
    a = n.get("attrs") or {}
    return f"[첨부: {a.get('alt') or a.get('id') or '파일'}]"


def _cell(c):
    body = _blocks(c.get("content") or [], "")
    return body.replace("|", "\\|").replace("\n\n", "<br>").replace("\n", "<br>").strip() or " "


def _table(rows):
    lines = []
    for i, row in enumerate(rows):
        cells = [_cell(c) for c in row.get("content") or []]
        lines.append("| " + " | ".join(cells) + " |")
        if i == 0:
            lines.append("|" + " --- |" * len(cells))
    return "\n".join(lines)


def _inline(nodes):
    return "".join(_inline_node(n) for n in nodes)


def _inline_node(n):
    kind = n.get("type")
    a = n.get("attrs") or {}
    if kind == "text":
        return _marked(n.get("text", ""), n.get("marks") or [])
    if kind == "hardBreak":
        return "\n"
    if kind == "mention":
        text = a.get("text") or a.get("id", "")
        return text if text.startswith("@") else "@" + text
    if kind in ("inlineCard", "blockCard", "embedCard"):
        return f"<{a.get('url', '')}>"
    if kind == "status":
        return f"`[{a.get('text', '')}]`"
    if kind == "date":
        try:
            ts = int(a.get("timestamp")) / 1000
            return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).strftime("%Y-%m-%d")
        except (TypeError, ValueError):
            return ""
    if kind == "emoji":
        return a.get("text") or a.get("shortName", "")
    if kind in ("media", "mediaInline"):
        return _media(n)
    return _inline(n.get("content") or [])


def _marked(text, marks):
    if not text:
        return ""
    kinds = {m.get("type"): m for m in marks}
    if "code" in kinds:
        text = f"`{text}`"
    else:
        if "strong" in kinds:
            text = f"**{text}**"
        if "em" in kinds:
            text = f"_{text}_"
        if "strike" in kinds:
            text = f"~~{text}~~"
    if "link" in kinds:
        text = f"[{text}]({(kinds['link'].get('attrs') or {}).get('href', '')})"
    return text
