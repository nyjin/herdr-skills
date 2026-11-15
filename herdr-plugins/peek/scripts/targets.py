"""Sort a clicked string into a link the viewer can fetch (Jira, Confluence, GitHub PR) or a file path."""
import re

import resolve

JIRA = re.compile(r"^(https://[^/\s]+\.atlassian\.net)/browse/([A-Z][A-Z0-9]+-\d+)")
CONFLUENCE = re.compile(r"^https://[^/\s]+\.atlassian\.net/wiki/\S+")
PAGE_ID = re.compile(r"/pages/(\d+)")
GITHUB_PR = re.compile(r"^https://github\.com/([^/\s]+/[^/\s]+)/pull/(\d+)")
LINE = re.compile(r"^(.+?\.\w+):(\d+)(?::\d+)?$")


def classify(text):
    t = resolve.normalize(text)
    m = JIRA.match(t)
    if m:
        return {"kind": "jira", "url": f"{m.group(1)}/browse/{m.group(2)}", "key": m.group(2)}
    if CONFLUENCE.match(t):
        m = PAGE_ID.search(t)
        return {"kind": "confluence", "url": t, "page_id": m.group(1) if m else None}
    m = GITHUB_PR.match(t)
    if m:
        return {"kind": "github_pr", "url": f"https://github.com/{m.group(1)}/pull/{m.group(2)}",
                "repo": m.group(1), "number": m.group(2)}
    m = LINE.match(t)
    if m:
        return {"kind": "path", "text": m.group(1), "line": int(m.group(2))}
    return {"kind": "path", "text": t, "line": None}
