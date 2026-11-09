#!/usr/bin/env python3
"""Finalize a filled worker brief.

Usage: finalize-brief.py BRIEF [--role TEXT] [--worktree PATH] [--branch NAME] [--workdir PATH]
                         [--outside PATH REASON]... [--then FILE]

1. Strip HTML comments (guidance) outside code blocks.
2. Fail on leftover placeholders ({{...}}), [NEEDS CLARIFICATION ...] markers, or sections with no content.
3. Remove any existing closing paragraph and append it exactly once at the end. A brief whose Environment names a
   working directory (--workdir: a worker without a worktree) gets the closing paragraph that says not to commit.
4. With --role, --worktree, --branch, --workdir or --outside, write (or replace) the "## Environment" section right
   after the title. With --then, write (or replace) the "## On completion" section from that file, just before the
   closing paragraph.

On success, rewrite the file and print its path. On failure, leave the file untouched, print the reasons to stderr, and exit 1.
"""
import argparse
import os
import re
import sys

TAIL = (
    "When the work is done, commit any changes you made to this branch, and end your final response "
    "with a `## Result` heading that covers the change summary, test results and open issues. "
    "Do not push or open a pull request."
)
# For a worker without a worktree (--workdir). Its last sentence is TAIL's: SKILL.md step 3 waits for it.
NO_BRANCH_TAIL = (
    "When the work is done, end your final response with a `## Result` heading that covers what you did, "
    "test results and open issues. You have no branch of your own: do not commit, and change no file git tracks. "
    "Do not push or open a pull request."
)
WORKDIR_LINE = "- Working directory: "
FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")


def strip_comments(text):
    """Remove <!-- ... --> outside code blocks, including multi-line comments."""
    out, in_fence, fence_mark, in_comment = [], False, "", False
    for line in text.splitlines():
        if not in_comment:
            m = FENCE.match(line)
            if m:
                mark = m.group(1)
                if not in_fence:
                    in_fence, fence_mark = True, mark
                elif mark[0] == fence_mark[0] and len(mark) >= len(fence_mark):
                    in_fence = False
                out.append(line)
                continue
            if in_fence:
                out.append(line)
                continue
        buf, rest = "", line
        while rest:
            if in_comment:
                end = rest.find("-->")
                if end < 0:
                    rest = ""
                else:
                    rest, in_comment = rest[end + 3:], False
            else:
                start = rest.find("<!--")
                if start < 0:
                    buf, rest = buf + rest, ""
                else:
                    buf, rest, in_comment = buf + rest[:start], rest[start + 4:], True
        if buf != line:
            # drop comment-only lines; trim whitespace left where a comment was
            buf = buf.strip() if line.lstrip().startswith("<!--") else buf.rstrip()
            if buf:
                out.append(buf)
        else:
            out.append(line.rstrip())
    if in_comment:
        raise ValueError("unclosed HTML comment")
    return "\n".join(out)


def check(text):
    problems = []
    for n, line in enumerate(text.splitlines(), 1):
        if re.search(r"\{\{[^}]*\}\}", line):
            problems.append(f"line {n}: unfilled placeholder: {line.strip()}")
        if "[NEEDS CLARIFICATION" in line:
            problems.append(f"line {n}: unresolved clarification: {line.strip()}")
    # empty section: a heading followed directly by a same-or-higher heading or end of file
    lines = [l for l in text.splitlines()]
    heads = [(i, len(m.group(1))) for i, l in enumerate(lines) if (m := re.match(r"^(#{2,6})\s", l))]
    for idx, (i, level) in enumerate(heads):
        j = len(lines)
        for k, lv in heads[idx + 1:]:
            if lv <= level:
                j = k
                break
        if not any(l.strip() for l in lines[i + 1:j]):
            problems.append(f"line {i + 1}: empty section: {lines[i].strip()} (fill or delete it)")
    return problems


def drop_section(lines, title):
    """Remove the level-2 section `title` (up to the next heading of level 1-2)."""
    while title in lines:
        i = lines.index(title)
        j = next((k for k in range(i + 1, len(lines)) if re.match(r"^#{1,2}\s", lines[k])), len(lines))
        del lines[i:j]
    return lines


def environment_block(args):
    out = ["## Environment", ""]
    if args.role:
        out.append(f"- Role: {args.role}")
    if args.workdir:
        out.append(f"{WORKDIR_LINE}`{args.workdir}` (no worktree or branch of its own)")
    elif args.worktree:
        out.append(f"- Worktree: `{args.worktree}`" + (f" (branch `{args.branch}`)" if args.branch else ""))
    elif args.branch:
        out.append(f"- Branch: `{args.branch}`")
    for p, reason in args.outside or []:
        out.append(f"- Outside path: `{p}` \u2014 {reason}")
    return out if len(out) > 2 else []


def parse_args():
    ap = argparse.ArgumentParser(prog="finalize-brief.py", description=__doc__.strip().split("\n")[0])
    ap.add_argument("brief", metavar="BRIEF", help="the filled brief file (rewritten in place)")
    ap.add_argument("--role", help="the worker's role, written to the Environment section")
    ap.add_argument("--worktree", metavar="PATH", help="the worker's worktree path")
    ap.add_argument("--branch", metavar="NAME", help="the worker's branch, written after the worktree path")
    ap.add_argument("--workdir", metavar="PATH",
                    help="for a worker without a worktree: the directory it works in; the closing paragraph then "
                         "tells it not to commit (kept on later runs)")
    ap.add_argument("--outside", nargs=2, action="append", metavar=("PATH", "REASON"),
                    help="an absolute path outside the worktree the worker may use, and why (repeatable)")
    ap.add_argument("--then", metavar="FILE",
                    help="file whose content becomes the On completion section, placed before the closing paragraph")
    return ap.parse_args()


def main():
    args = parse_args()
    path = args.brief
    if args.workdir and (args.worktree or args.branch):
        print(f"{path}: --workdir is for a worker without a worktree; it does not go with --worktree or --branch",
              file=sys.stderr)
        return 1
    for p, _ in args.outside or []:
        if not os.path.isabs(p):
            print(f"{path}: --outside path must be absolute: {p}", file=sys.stderr)
            return 1
    then = None
    if args.then:
        try:
            with open(args.then, encoding="utf-8") as f:
                then = f.read().rstrip("\n")
        except OSError as e:
            print(f"{args.then}: cannot read --then file: {e.strerror}", file=sys.stderr)
            return 1
        if not then.strip():
            print(f"{args.then}: --then file is empty", file=sys.stderr)
            return 1
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read()
    except OSError as e:
        print(f"{path}: cannot read brief: {e.strerror}", file=sys.stderr)
        return 1
    try:
        body = strip_comments(text)
    except ValueError as e:
        print(f"{path}: {e}", file=sys.stderr)
        return 1
    body = "\n".join(l for l in body.splitlines() if l.strip() not in (TAIL, NO_BRANCH_TAIL))
    lines = body.splitlines()
    env = environment_block(args)
    if env:
        drop_section(lines, "## Environment")
        at = next((i + 1 for i, l in enumerate(lines) if l.startswith("# ")), 0)
        lines[at:at] = ([""] if at else []) + env + [""]
    if then is not None:
        drop_section(lines, "## On completion")
        lines += ["", "## On completion", "", then]
    body = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    problems = check(body)
    if problems:
        print(f"{path}: not finalized", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    tail = NO_BRANCH_TAIL if any(l.startswith(WORKDIR_LINE) for l in lines) else TAIL
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(body + "\n\n" + tail + "\n")
    except OSError as e:
        print(f"{path}: cannot write brief: {e.strerror}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
