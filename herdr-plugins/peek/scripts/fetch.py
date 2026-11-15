"""Fetch a Jira issue, Confluence page or GitHub PR as markdown, trying the user's tools in order.

  Jira        acli → jira-cli → Atlassian MCP
  Confluence  cme → Atlassian MCP
  GitHub PR   gh

A tool that is not installed is skipped; one that fails hands over to the next. When none works, the
result is a markdown page listing every tool, what happened with it and the command that fixes it, so
the viewer always has something to show. MCP runs through `claude -p` and is tried last: it took
15-30 seconds per page when measured, and every call costs Claude usage.
"""
import glob
import hashlib
import json
import os
import re
import shutil
import subprocess

import adf
import targets

RELATIVE_LINK = re.compile(r"(!?)\[([^\]]*)\]\((?![a-z][a-z0-9+.-]*:|#)[^)]*\)")

MCP = "Atlassian MCP"
# claude.ai names a connector's tools after the connector: "Atlassian" for the stock connector, or
# whatever an organization named its own (e.g. "Atlassian MCP"). Allowing a name that does not exist
# is harmless, so both are listed.
MCP_PREFIXES = ("mcp__claude_ai_Atlassian__", "mcp__claude_ai_Atlassian_MCP__")
MCP_TOOLS = {"jira": ["getJiraIssue"], "confluence": ["getConfluenceContent"]}
INSTALL = {
    "acli": "`brew tap atlassian/homebrew-acli && brew install acli`, then `acli jira auth login`",
    "jira-cli": "`brew install ankitpokhrel/jira-cli/jira-cli`, then `jira init` (API token in `JIRA_API_TOKEN`)",
    "cme": "`uv tool install confluence-markdown-exporter`, then Confluence login in `cme config`",
    "gh": "`brew install gh`, then `gh auth login`",
    MCP: "install Claude Code (`claude`) and connect the Atlassian connector on claude.ai",
}
LOGIN = {
    "acli": "`acli jira auth login`",
    "jira-cli": "`jira init` (API token in `JIRA_API_TOKEN`)",
    "cme": "the login settings in `cme config`",
    "gh": "`gh auth login` with an account that can see this repository (organization SSO approval may be needed)",
    MCP: "connect the Atlassian connector in claude.ai settings",
}
REASON = {"missing": "not installed", "auth": "login needed", "notfound": "not found or no access",
          "timeout": "timed out", "error": "error"}


class Failure(Exception):
    def __init__(self, reason, detail=""):
        super().__init__(reason)
        self.reason, self.detail = reason, detail


def cache_path(url):
    base = os.environ.get("PEEK_CACHE_DIR") or os.path.expanduser("~/.cache/peek")
    return os.path.join(base, hashlib.sha1(url.encode()).hexdigest()[:12] + ".md")


def run(cmd, timeout, env=None):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           env=dict(os.environ, **(env or {})))
    except FileNotFoundError:
        raise Failure("missing", cmd[0])
    except subprocess.TimeoutExpired:
        raise Failure("timeout", f"{timeout} s")
    if r.returncode != 0:
        err = (r.stderr or r.stdout).strip()
        low = err.lower()
        if any(s in low for s in ("unauthorized", "auth login", "not logged", "authenticate", "401",
                                  "jira init", "config file")):
            raise Failure("auth", err)
        if any(s in low for s in ("404", "not found", "could not resolve", "failed to fetch", "does not exist")):
            raise Failure("notfound", err)
        raise Failure("error", err)
    return r.stdout


def run_json(cmd, timeout, env=None):
    try:
        return json.loads(run(cmd, timeout, env))
    except ValueError:
        raise Failure("error", "the CLI output is not JSON")


def fetch_markdown(url, *, timeout=None):
    """Returns (markdown, ok, tool used or None). `timeout` overrides each tool's own limit."""
    t = targets.classify(url)
    chain = PROVIDERS.get(t["kind"])
    if not chain:
        return guide(t, []), False, None
    attempts = []
    for name, binary, fn, limit in chain:
        if not shutil.which(binary):
            attempts.append((name, Failure("missing")))
            continue
        try:
            return fn(t, timeout or limit), True, name
        except Failure as f:
            attempts.append((name, f))
    return guide(t, attempts), False, None


# ---- Jira -----------------------------------------------------------------------------------

def _name(obj, key="displayName"):
    return (obj or {}).get(key) or "-"


def jira_markdown(d, t):
    """acli --json and jira-cli --raw both return the Jira REST issue (fields, ADF bodies)."""
    f = d.get("fields") or {}
    lines = [f"# {d.get('key', t['key'])} {f.get('summary', '')}", "",
             f"- {_name(f.get('issuetype'), 'name')} · **{_name(f.get('status'), 'name')}** · priority {_name(f.get('priority'), 'name')}",
             f"- assignee {_name(f.get('assignee'))} · reporter {_name(f.get('reporter'))}"]
    parent = f.get("parent")
    if parent:
        lines.append(f"- parent {parent.get('key')} {((parent.get('fields') or {}).get('summary') or '')}")
    if f.get("labels"):
        lines.append("- labels " + ", ".join(f["labels"]))
    lines += [f"- created {str(f.get('created', ''))[:16]} · updated {str(f.get('updated', ''))[:16]}", f"- <{t['url']}>",
              "", "## Description", "", adf.to_markdown(f.get("description")) or "_(none)_"]
    comments = (f.get("comment") or {}).get("comments") or []
    if comments:
        lines += ["", f"## Comments ({len(comments)})"]
        for c in comments:
            lines += ["", f"### {_name(c.get('author'))} · {str(c.get('created', ''))[:16]}", "", adf.to_markdown(c.get("body"))]
    return "\n".join(lines) + "\n"


def jira_acli(t, timeout):
    return jira_markdown(run_json(
        ["acli", "jira", "workitem", "view", t["key"], "--json", "--fields",
         "key,summary,status,issuetype,priority,assignee,reporter,parent,labels,created,updated,description,comment"],
        timeout), t)


def jira_cli(t, timeout):
    return jira_markdown(run_json(["jira", "issue", "view", t["key"], "--raw"], timeout), t)


# ---- Confluence -----------------------------------------------------------------------------

def confluence_cme(t, timeout):
    """cme writes into its configured export folder; point it at a folder of our own per page."""
    out = cache_path(t["url"])[:-3] + ".cme"
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    log = run(["cme", "pages", t["url"]], timeout,
              env={"CME_EXPORT__OUTPUT_PATH": out, "CME_EXPORT__SKIP_UNCHANGED": "false",
                   # the viewer shows text only; attachments would only fill the cache
                   "CME_EXPORT__ATTACHMENTS_EXPORT": "disabled"})
    pages = sorted(glob.glob(os.path.join(out, "**", "*.md"), recursive=True), key=os.path.getmtime)
    if not pages:  # cme exits 0 for a page it could not find
        raise Failure("notfound", log.strip()[-600:])
    with open(pages[-1]) as f:
        md = f.read()
    # Links between exported files (breadcrumb, sibling pages, attachments) point into cme's folder
    # layout, which glow would show as local paths: keep their text only.
    md = RELATIVE_LINK.sub(lambda m: "" if m.group(1) == "!" else m.group(2), md)
    return md + f"\n\n---\n\n- <{t['url']}>\n"


# ---- GitHub ---------------------------------------------------------------------------------

def _gh_api(path, timeout):
    """`gh api` takes no -R, so a gh wrapper that picks the account by repo cannot help here.
    On a 404, retry with each logged-in account's token."""
    try:
        return run_json(["gh", "api", "--paginate", path], timeout)
    except Failure as first:
        if first.reason != "notfound":
            raise
        try:
            hosts = run_json(["gh", "auth", "status", "--json", "hosts"], timeout)
        except Failure:
            raise first
        for acct in (hosts.get("hosts") or {}).get("github.com", []):
            try:
                token = run(["gh", "auth", "token", "--user", acct["login"]], timeout).strip()
                return run_json(["gh", "api", "--paginate", path], timeout, env={"GH_TOKEN": token})
            except Failure:
                continue
        raise first


def github_pr(t, timeout):
    d = run_json(["gh", "pr", "view", t["number"], "-R", t["repo"], "--json",
                  "number,title,body,author,state,isDraft,url,baseRefName,headRefName,additions,deletions,comments,reviews,files"],
                 timeout)
    try:
        inline = _gh_api(f"repos/{t['repo']}/pulls/{t['number']}/comments", timeout)
    except Failure:
        inline = None
    state = d.get("state", "") + (" (draft)" if d.get("isDraft") else "")
    lines = [f"# {d.get('title', '')} (#{d.get('number', t['number'])})", "",
             f"- **{state}** · {_name(d.get('author'), 'login')} · {d.get('baseRefName')} ← {d.get('headRefName')}"
             f" · +{d.get('additions', 0)}/-{d.get('deletions', 0)}",
             f"- <{d.get('url', t['url'])}>", "", d.get("body") or "_(no description)_"]
    reviews = [r for r in d.get("reviews") or [] if r.get("body") or r.get("state") != "COMMENTED"]
    if reviews:
        lines += ["", f"## Reviews ({len(reviews)})"]
        for r in reviews:
            lines += ["", f"### {_name(r.get('author'), 'login')} · {r.get('state')} · {str(r.get('submittedAt', ''))[:10]}"]
            if r.get("body"):
                lines += ["", r["body"]]
    if inline is None:
        lines += ["", "## Inline comments", "", "_Could not be fetched (gh api permissions)._"]
    elif inline:
        lines += ["", f"## Inline comments ({len(inline)})"]
        for c in inline:
            where = f"{c.get('path')}:{c.get('line') or c.get('original_line') or ''}"
            reply = "↳ " if c.get("in_reply_to_id") else ""
            lines += ["", f"### {reply}`{where}` · {_name(c.get('user'), 'login')}", "", c.get("body", "")]
    if d.get("comments"):
        lines += ["", f"## Comments ({len(d['comments'])})"]
        for c in d["comments"]:
            lines += ["", f"### {_name(c.get('author'), 'login')} · {str(c.get('createdAt', ''))[:10]}", "", c.get("body", "")]
    files = d.get("files") or []
    if files:
        lines += ["", f"## Files changed ({len(files)})", ""]
        lines += [f"- {f.get('path')} (+{f.get('additions', 0)}/-{f.get('deletions', 0)})" for f in files]
    return "\n".join(lines) + "\n"


# ---- MCP ------------------------------------------------------------------------------------

def fetch_mcp(t, timeout):
    tools = MCP_TOOLS[t["kind"]]
    prompt = (f"Fetch {t['url']} with the Atlassian MCP tools (the cloudId can be the site host). Ask only for "
              "what is needed: for a Jira issue use view \"compact\", responseContentFormat \"markdown\" and the fields "
              "summary,status,issuetype,assignee,description,comment. If a result is saved to a file because it is "
              "large, read that file with Read. Print ONLY the content as markdown: a H1 title, then for a Jira issue "
              "a short list of type/status/assignee followed by the description and comments; for a Confluence page "
              "the body. No commentary.")
    # 12 turns: loading the deferred MCP tools takes one, a large result read back from file takes a few.
    out = run(["claude", "-p", prompt, "--model", "claude-haiku-5-5", "--max-turns", "12",
               "--allowedTools", ",".join([p + tool for p in MCP_PREFIXES
                                           for tool in tools + ["getAccessibleAtlassianResources"]] + ["Read"])],
              timeout)
    if not out.strip():
        raise Failure("error", "the MCP answer was empty")
    return out + f"\n\n---\n\n- <{t['url']}>\n"


PROVIDERS = {  # (name, executable, fetcher, minimum timeout in seconds)
    "jira": [("acli", "acli", jira_acli, 30), ("jira-cli", "jira", jira_cli, 30), (MCP, "claude", fetch_mcp, 360)],
    # cme: 1.7-6s for most pages, 64s measured for a long one; 180 keeps it from falling to MCP.
    "confluence": [("cme", "cme", confluence_cme, 180), (MCP, "claude", fetch_mcp, 360)],
    "github_pr": [("gh", "gh", github_pr, 30)],
}


# ---- guide ----------------------------------------------------------------------------------

def guide(t, attempts):
    url = t.get("url") or t.get("text", "")
    if not attempts:
        return f"# Unsupported link\n\n- <{url}>\n\n---\n\n**o**: open in the browser\n"
    none_installed = all(f.reason == "missing" for _, f in attempts)
    lines = ["# " + ("None of the tools for this link is installed" if none_installed else "Could not fetch this link"),
             "", f"- Link: <{url}>", "", "Tried in this order:", "", "| Tool | Result | Fix |", "| --- | --- | --- |"]
    for name, f in attempts:
        fix = {"missing": INSTALL[name], "auth": LOGIN[name],
               "notfound": "check the link and the logged-in account" + (" (`gh auth status`)" if name == "gh" else ""),
               "timeout": f"no answer within {f.detail}; press **f** to try again"}.get(f.reason, "see the error below")
        lines.append(f"| {name} | {REASON[f.reason]} | {fix} |")
    details = [(n, f) for n, f in attempts if f.detail and f.reason in ("auth", "notfound", "error")]
    for name, f in details:
        lines += ["", f"**{name}**", "", "```", f.detail[:600], "```"]
    lines += ["", "---", "", "**o**: open in the browser · **f**: try again"]
    return "\n".join(lines) + "\n"
