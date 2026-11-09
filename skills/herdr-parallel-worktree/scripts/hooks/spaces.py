"""Which herdr space a worktree of a repository belongs under. The one place this rule lives: scripts/place.py
(workers) and route.py (a worktree the main session made with EnterWorktree) both ask here.

1. The session's own space, when it is bound to the repository.
2. Otherwise the space herdr knows for the repository (`herdr worktree list` reports it as the source
   checkout's `source_workspace_id`, bound or not).
3. Otherwise none: the caller must not let herdr make a new top-level space for it.
"""
import os


def _result(reply):
    return reply.get("result") if isinstance(reply, dict) and isinstance(reply.get("result"), dict) else None


def repo_space(root, current, herdr):
    """Return (workspace id or None, why); why is "current", "repo-space", "none" or "herdr-error".

    root: the repository's checkout. current: this session's workspace id ($HERDR_WORKSPACE_ID) or None.
    herdr: callable(list of arguments) -> herdr's parsed JSON, or None when herdr could not be run.
    A failed herdr call is "herdr-error", never "none": the caller must not mistake an outage for an empty sidebar.
    """
    listed = _result(herdr(["worktree", "list", "--cwd", root]))
    if listed is None:
        return None, "herdr-error"
    source = listed.get("source") or {}
    known, key = source.get("source_workspace_id"), source.get("repo_key")
    if current:
        if current == known:
            return current, "current"
        info = _result(herdr(["workspace", "get", current]))
        if info is None:
            return None, "herdr-error"
        cur_key = ((info.get("workspace") or {}).get("worktree") or {}).get("repo_key")
        if isinstance(cur_key, str) and isinstance(key, str) and os.path.realpath(cur_key) == os.path.realpath(key):
            return current, "current"
    if isinstance(known, str) and known:
        return known, "repo-space"
    return None, "none"
