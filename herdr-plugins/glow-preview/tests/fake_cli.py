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

ADF = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "본문 내용"}]}]}

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
            f.write("[Parent](../Parent.md)\n\n# 페이지 제목\n\n본문 내용\n")
    print("Exported 1" if mode != "empty" else "Exported 0")
elif (name == "acli" and args[0] == "jira") or (name == "jira" and args[:2] == ["issue", "view"]):
    print(json.dumps({"key": "ABC-1", "fields": {
        "summary": "요약 제목", "status": {"name": "진행 중"}, "issuetype": {"name": "작업"},
        "assignee": {"displayName": "홍길동"}, "reporter": {"displayName": "김철수"},
        "priority": {"name": "Medium"}, "created": "2026-11-01T10:00:00.000+0900",
        "updated": "2026-11-02T10:00:00.000+0900", "description": ADF,
        "comment": {"comments": [{"author": {"displayName": "박영희"}, "created": "2026-11-03T09:00:00.000+0900",
                                  "body": {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "코멘트 하나"}]}]}}]}}}))
elif name == "gh" and args[:2] == ["pr", "view"]:
    print(json.dumps({"number": 7, "title": "PR 제목", "body": "PR 설명", "author": {"login": "alice"},
                      "state": "OPEN", "isDraft": False, "url": "https://github.com/o/r/pull/7",
                      "baseRefName": "main", "headRefName": "feat", "additions": 3, "deletions": 1,
                      "comments": [{"author": {"login": "c1"}, "body": "일반 코멘트", "createdAt": "2026-11-01T00:00:00Z"}],
                      "reviews": [{"author": {"login": "rev"}, "state": "APPROVED", "body": "좋아요", "submittedAt": "2026-11-02T00:00:00Z"}],
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
                       "body": "여기 이름이 어색해요", "id": 1, "in_reply_to_id": None}]))
elif name == "claude":
    print("# MCP로 가져온 문서\n\n내용")
