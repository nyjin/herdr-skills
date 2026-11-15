"""Turn a file path as Claude Code printed it into the files it may mean.

Claude Code often prints a path relative to its working folder, cut short with "…/", or as a bare
file name. Candidates are gathered from every source at once (working folder, session scratchpad,
session transcript, git checkout) and de-duplicated by real path. The caller decides what to do
with zero, one or several of them; no source is trusted over another.
"""
import glob
import os
import re
import subprocess

TRANSCRIPT_PATH = re.compile(r"(?:/|~/)[^\s\"'`()<>\[\]{}|,:;\\]+\.\w{1,10}\b")
WRAPPERS = "\"'`()[]<>{}"
TRAILING = ".,;:!?"


def normalize(text):
    t = text.strip()
    if t.startswith("file://"):
        t = t[len("file://"):]
    prev = None
    while prev != t:
        prev = t
        t = t.strip(WRAPPERS).rstrip(TRAILING)
        t = re.sub(r"(\.(?:md|markdown))(?::\d+){1,2}$", r"\1", t, flags=re.IGNORECASE)
    return t


def _file(path):
    return os.path.realpath(path) if os.path.isfile(path) else None


def _transcript_paths(session_id, home, projects_root):
    """Absolute markdown paths the session mentioned, oldest first."""
    found = []
    for f in glob.glob(os.path.join(projects_root, "*", session_id + ".jsonl")):
        try:
            with open(f, errors="ignore") as fh:
                for line in fh:
                    for m in TRANSCRIPT_PATH.finditer(line.replace("\\n", " ")):
                        p = m.group(0)
                        found.append(os.path.join(home, p[2:]) if p.startswith("~/") else p)
        except OSError:
            continue
    return found


def _git_files(cwd):
    def git(*args):
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=10)
        return r.stdout if r.returncode == 0 else ""
    root = git("rev-parse", "--show-toplevel").strip()
    if not root:
        return []
    return [os.path.join(root, line) for line in git("-C", root, "ls-files", "-co", "--exclude-standard").splitlines()]


def candidates(text, cwd, session_id, *, home, tmp_root, projects_root):
    t = normalize(text)
    if t.startswith("/") or t.startswith("~/"):
        f = _file(os.path.join(home, t[2:]) if t.startswith("~/") else t)
        return [f] if f else []

    cut = t.startswith("…/")
    rel = t[2:] if cut else t
    suffix = "/" + re.sub(r"^(\./|\.\./)+", "", rel)
    found = set()

    if cwd and os.path.isdir(cwd):
        if not cut:
            found.add(_file(os.path.join(cwd, rel)))
        found.update(_file(p) for p in _git_files(cwd) if p.endswith(suffix))

    order = []
    if session_id:
        if not cut:
            for pad in glob.glob(os.path.join(tmp_root, "*", session_id, "scratchpad")):
                found.add(_file(os.path.join(pad, re.sub(r"^scratchpad/", "", rel))))
        order = [_file(p) for p in _transcript_paths(session_id, home, projects_root) if p.endswith(suffix)]
        found.update(order)

    found.discard(None)
    last_seen = {p: i for i, p in enumerate(order) if p}
    return sorted(found, key=lambda p: (-last_seen.get(p, -1), p))
