#!/usr/bin/env python3
"""Finalize a filled worker brief.

Usage: finalize-brief.py <brief file>

1. Strip HTML comments (guidance) outside code blocks.
2. Fail on leftover placeholders ({{...}}), [NEEDS CLARIFICATION ...] markers, or sections with no content.
3. Remove any existing closing paragraph and append it exactly once at the end.

On success, rewrite the file and print its path. On failure, leave the file untouched, print the reasons to stderr, and exit 1.
"""
import re
import sys

TAIL = (
    "When the work is done, commit any changes you made to this branch, and end your final response "
    "with a `## Result` heading that covers the change summary, test results and open issues. "
    "Do not push or open a pull request."
)
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


def main():
    if len(sys.argv) != 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path = sys.argv[1]
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
    body = "\n".join(l for l in body.splitlines() if l.strip() != TAIL)
    body = re.sub(r"\n{3,}", "\n\n", body).strip()
    problems = check(body)
    if problems:
        print(f"{path}: not finalized", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(body + "\n\n" + TAIL + "\n")
    except OSError as e:
        print(f"{path}: cannot write brief: {e.strerror}", file=sys.stderr)
        return 1
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
