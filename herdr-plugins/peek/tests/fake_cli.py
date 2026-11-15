#!/usr/bin/env python3
"""Stand-in for acli, jira (jira-cli), cme, gh and claude, picked by the name it is linked as. $FAKE_MODE picks the
outcome (ok, auth, notfound, hang, api404first, empty); FAKE_MODE_<tool> sets it for one tool; every call is logged to $FAKE_LOG."""
import json
import os
import sys
import time

name = os.path.basename(sys.argv[0])
args = sys.argv[1:]
mode = os.environ.get("FAKE_MODE_" + name.replace("-", "_"), os.environ.get("FAKE_MODE", "ok"))
with open(os.environ["FAKE_LOG"], "a") as f:
    f.write(json.dumps([name] + args) + "\n")

ADF = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Body text"}]}]}
# Korean on purpose: the Jira comment checks that non-ASCII text comes through the CLI's JSON unchanged.
COMMENT = "코멘트 하나"

if mode == "hang":
    time.sleep(5)
if mode == "auth":
    sys.stderr.write("✗ Error: unauthorized: use 'acli %s auth login' to authenticate\n" % args[0])
    sys.exit(1)
if mode == "notfound":
    sys.stderr.write("✗ Error: failed to fetch work item details\n" if name == "acli" else "GraphQL: Could not resolve to a PullRequest\n")
    sys.exit(1)

if name == "cme":
    out = os.environ["CME_EXPORT__OUTPUT_PATH"]
    if mode != "empty":
        os.makedirs(os.path.join(out, "Space", "Parent"), exist_ok=True)
        with open(os.path.join(out, "Space", "Parent", "Page.md"), "w") as f:
            f.write("[Parent](../Parent.md)\n\n# Page title\n\nBody text\n")
    print("Exported 1" if mode != "empty" else "Exported 0")
elif (name == "acli" and args[0] == "jira") or (name == "jira" and args[:2] == ["issue", "view"]):
    print(json.dumps({"key": "ABC-1", "fields": {
        "summary": "Issue summary", "status": {"name": "In Progress"}, "issuetype": {"name": "Task"},
        "assignee": {"displayName": "Jane Doe"}, "reporter": {"displayName": "John Roe"},
        "priority": {"name": "Medium"}, "created": "2026-11-01T10:00:00.000+0900",
        "updated": "2026-11-02T10:00:00.000+0900", "description": ADF,
        "comment": {"comments": [{"author": {"displayName": "Ann Lee"}, "created": "2026-11-03T09:00:00.000+0900",
                                  "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": COMMENT}]}]}}]}}}))
elif name == "gh" and args[:2] == ["pr", "view"]:
    print(json.dumps({"number": 7, "title": "PR title", "body": "PR description", "author": {"login": "alice"},
                      "state": "OPEN", "isDraft": False, "url": "https://github.com/o/r/pull/7",
                      "baseRefName": "main", "headRefName": "feat", "additions": 3, "deletions": 1,
                      "comments": [{"author": {"login": "c1"}, "body": "A general comment", "createdAt": "2026-11-01T00:00:00Z"}],
                      "reviews": [{"author": {"login": "rev"}, "state": "APPROVED", "body": "Looks good", "submittedAt": "2026-11-02T00:00:00Z"}],
                      "files": [{"path": "src/a.py", "additions": 3, "deletions": 1}]}))
elif name == "gh" and args[:2] == ["auth", "status"]:
    print(json.dumps({"hosts": {"github.com": [{"login": "a"}, {"login": "b"}]}}))
elif name == "gh" and args[:2] == ["auth", "token"]:
    print("tok-" + args[-1])
elif name == "gh" and args[0] == "api":
    if mode == "api404first" and os.environ.get("GH_TOKEN") != "tok-b":
        sys.stderr.write("gh: Not Found (HTTP 404)\n")
        sys.exit(1)
    print(json.dumps([{"user": {"login": "rev"}, "path": "src/a.py", "line": 12, "original_line": 12,
                       "body": "This name reads oddly", "id": 1, "in_reply_to_id": None}]))
elif name == "claude":
    print("# Fetched through MCP\n\nContent")
