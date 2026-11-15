# glow-preview Phase 2 Implementation Plan

> Renamed to `peek` on 2026-11-15 (`herdr-plugins/peek`). This record keeps the names it was written with.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The viewer also shows source code (bat) and links (Jira, Confluence, GitHub PR), and lets `.md` switch between rendered and raw.

**Architecture:** Use `items: [{"path": str, "line": int|None} | {"url": str}]` in place of the state file `paths`. A link click splits URL from path with `targets.classify`. The viewer writes a URL item to a cache file with `fetch.fetch_markdown`, then shows it like a `.md`. The view mode lives in `<source>.mode` (`rendered`|`source`) and is changed by a menu key and a herdr action.

**Tech Stack:** python3 standard library, glow 3 (`-p`), bat, less, acli, gh, claude CLI (MCP path only).

**Spec:** `docs/superpowers/specs/2026-11-13-glow-preview-design.md` (Phase 2 extension section)

## Global Constraints

- Every CLI call has a timeout: acli and gh 30 s, MCP (`claude -p`) 360 s.
- Do not modify `glow.yml`. Run glow with `-p -w <cols-2>` and the pager with `PAGER="less -R"`.
- Only `.md` and `.markdown` are opened automatically (by the hook).
- The cache lives in `~/.cache/glow-preview/`, and tests use `GLOWP_CACHE_DIR`.
- gh uses the `gh` on `PATH` as is. It must go through the user's wrapper so that the right account is picked.

## Review Focus

1. A URL with no page id, such as a short Confluence link (`/wiki/x/AbCd`) → a guide screen, never an error exit. `test_confluence_without_id_guides`
2. acli does not respond for over 30 seconds → a timeout guide. `test_timeout_guides`
3. A node in ADF that has not been seen before → no text is lost. `test_unknown_node_keeps_text`
4. A line break or pipe character inside a table cell → the table does not break. `test_table_cell_escapes`
5. Clicking `src/a.py:42` → jumps to line 42 and highlights it. Live check (Task 4 Step 5)

---

### Task 1: ADF → markdown (`scripts/adf.py`)

**Files:** Create `scripts/adf.py`, `tests/test_adf.py`

**Interfaces:**
- Produces: `to_markdown(doc: dict | str | None) -> str`. If it is a string, parse it as JSON.

- [ ] **Step 1: Write the tests.** Test with small hand-made ADF fragments.
  - `test_blocks`: block element conversion
    - heading 2 → `## Title`
    - two paragraphs → separated by a blank line
    - bulletList and orderedList (including nested) → `- `/`1. ` + 2-space indent
    - codeBlock(language) → fenced code block
    - blockquote → `> `
    - rule → `---`
    - panel → a quote starting with `> **ℹ️**`
    - expand(title) → `**▸ title**` followed by the body
    - taskList → `- [ ]`/`- [x]`
    - decisionList → `- ✔︎ `
  - `test_inline`: inline element conversion
    - marks strong `**`, em `_`, code `` ` ``, strike `~~`, link `[t](href)`
    - underline, textColor, backgroundColor, annotation, alignment, breakout, indentation, fontSize and border are ignored
    - hardBreak → line break
    - mention → `@name`
    - inlineCard, blockCard, embedCard → `<url>`
    - status → `` `[STATUS]` ``
    - date (timestamp ms) → `YYYY-MM-DD`
    - emoji → shortName
    - media, mediaSingle, mediaGroup, mediaInline → `[Attachment: alt|file]`
  - `test_table_cell_escapes`: the first row (tableHeader) becomes the header. A `|` inside a cell becomes `\|`, and a line break becomes `<br>`.
  - `test_unknown_node_keeps_text`: `{"type":"mystery","content":[text "abc"]}` → `abc` is kept.
  - `test_extension`: extension → `[Confluence macro: extensionKey]`
- [ ] **Step 2:** `python3 -m unittest tests.test_adf -v` → confirm it fails
- [ ] **Step 3: Implement**
- [ ] **Step 4:** Confirm it passes. Then convert all 51 documents collected from sessions (scratchpad `adf_corpus.json`) and confirm there are 0 exceptions.
- [ ] **Step 5: Commit** — `feat: convert Atlassian documents to markdown`

### Task 2: Link classification and fetching (`scripts/targets.py`, `scripts/fetch.py`)

**Files:** Create `scripts/targets.py`, `scripts/fetch.py`, `tests/test_fetch.py`, `tests/fake_cli.py` (imitates acli, gh and claude; the behavior is chosen with the environment variable `FAKE_MODE`: `ok`, `auth`, `notfound`, `hang`)

**Interfaces:**
- Consumes: `adf.to_markdown`
- Produces:
  - `targets.classify(text: str) -> dict`. The result is one of three.
    - `{"kind": "jira", "url", "key"}`
    - `{"kind": "confluence", "url", "page_id": str|None}`
    - `{"kind": "github_pr", "url", "repo": "o/r", "number": str}`
    - `{"kind": "path", "text": str, "line": int|None}` (after `resolve.normalize`, the line is read from the trailing `:line[:col]`)
  - `fetch.fetch_markdown(url: str, *, via: str = "cli", timeout: int = 30) -> tuple[str, bool]`. Returns `(markdown, success)`. On failure the markdown holds a guide for the cause. The causes are `missing`, `auth`, `notfound`, `timeout`, `noid` and `error`. The Jira and Confluence failure guides include the `m` key MCP note (3 to 4 minutes, about $0.02).
  - `via="mcp"` runs `claude -p` allowing only two Atlassian MCP tools, and uses the resulting markdown as is. The model is `claude-haiku-5-5`, with `--max-turns 6`.
  - `fetch.cache_path(url: str) -> str`: `<cache>/<sha1(url)[:12]>.md`
- [ ] **Step 1: Write the tests** (link fake_cli to the front of `PATH` under the names `acli`, `gh` and `claude`)
  - `test_classify`: the following five inputs are each classified correctly.
    - Jira browse URL
    - Confluence `/pages/123/title` and `/wiki/x/AbCd` (page_id None)
    - PR URL
    - `src/a.py:42:3` → path, line 42
  - `test_jira_ok`: the result contains `# KEY summary`, the status and assignee lines, the ADF body and `## Comments`.
  - `test_confluence_ok`: the result contains `# Title` and the body. The acli call arguments include `--body-format atlas_doc_format`.
  - `test_pr_ok`: the gh call has `-R o/r`. The result contains the title, status and author, the reviews (author, state, body), the inline comments (`path:line`) and the list of changed files.
  - `test_auth_guides`: acli authentication error → ok False and the guide contains `acli jira auth login` (for Confluence, `acli confluence auth login`).
  - `test_missing_cli_guides`: acli not on PATH → a `brew install acli` guide
  - `test_timeout_guides`: with `timeout=1` in hang mode, a "timed out" guide
  - `test_confluence_without_id_guides`: no page id → a guide, no CLI call
  - `test_pr_api_account_fallback`: `gh api` returns 404 on the first try → retry with `gh auth token --user <second account>` and get the inline comments.
- [ ] **Step 2:** Confirm it fails
- [ ] **Step 3: Implement**
- [ ] **Step 4:** Confirm it passes. Then fetch 3 Jira, 3 Confluence and 3 PR links from real session links with `fetch_markdown` and check the rendered result by eye.
- [ ] **Step 5: Commit** — `feat: fetch Jira, Confluence and PR content as markdown`

### Task 3: State format, link entry point, toggle action (`glowp.py`)

**Files:** Modify `scripts/glowp.py`, `scripts/resolve.py`, `tests/test_glowp.py`, `tests/test_resolve.py`, `herdr-plugin.toml`

**Interfaces:**
- Produces:
  - State file `{"items": [...], "seq": int}`
  - `show(source: str, items: list[dict])`
  - `resolve.candidates(…)` works regardless of extension. The transcript regex is widened to "a file name with a dot".
  - `glowp.py toggle`: if `$HERDR_PANE_ID` is the pane of some `<src>.viewer`, that src is the source, else it treats itself as the source. It flips `<src>.mode` and raises seq.
- [ ] **Step 1: Change and add tests**
  - Change `paths` to `items` in the existing tests.
  - `test_link_url_item`: clicking a Jira URL → state `items == [{"url": …}]`, resolve is not called.
  - `test_link_source_line`: `docs/b.py:7` → `items == [{"path": …/b.py, "line": 7}]`
  - `test_toggle_from_viewer_pane`: toggle from the viewer pane → `<src>.mode` becomes `source` and seq changes. Once more and it becomes `rendered`.
  - `test_resolve_any_extension`: finds `pkg/x.py` by git tail matching.
- [ ] **Step 2:** Confirm it fails → **Step 3:** Implement
- [ ] **Step 3b: Change the manifest**
  - Add `[[actions]] toggle-view` (contexts pane).
  - Add `[[link_handlers]]`. All have the action `open-link`.
    - `source`: extension list `py|java|kt|kts|ts|tsx|js|jsx|go|rs|sh|sql|ya?ml|toml|json|xml|gradle|rb|swift|c|h|cpp|hpp`
    - `jira`: `https://[^/\s]+\.atlassian\.net/browse/[A-Z][A-Z0-9]+-\d+`
    - `confluence`: `https://[^/\s]+\.atlassian\.net/wiki/\S+`
    - `github-pr`: `https://github\.com/[^/\s]+/[^/\s]+/pull/\d+`
- [ ] **Step 4:** Confirm it passes → **Step 5:** Commit `feat: link items for source files and URLs; toggle action`

### Task 4: Viewer (pager, bat, URL, menu)

**Files:** Modify `scripts/glowp.py` (`viewer`), `README.md`

- [ ] **Step 1: Implement**
  - The width is `shutil.get_terminal_size().columns - 2`.
  - How things are shown:
    - `.md` in rendered mode: `glow -p -w W -s auto <file>`, `PAGER="less -R"`
    - Raw mode or source code: `bat --paging=always --pager "less -R +<n>g -j.3" --highlight-line <n>`. n is adjusted by the number of bat header lines (decided by live check in Step 5).
    - URL item: first print "Fetching…" and build the cache file with `fetch_markdown`. Then show it as a `.md`.
  - After leaving the pager, show a menu.
    - `r` view again
    - `s` toggle rendered/raw (only for `.md`)
    - `o` browser (only for URLs)
    - `m` fetch through MCP (only when Atlassian failed)
    - `q` close
  - If bat is missing, announce it as with glow and install it with `brew install bat`.
- [ ] **Step 2: Live check — Korean paragraph.** In a 170-column pane, the end of the "Measured basis" paragraph of the design document ("so the user chooses") must be on screen.
- [ ] **Step 3: Live check — toggle.** Running the `toggle` action switches to raw (bat) even with the pager up, and running it again returns to rendered.
- [ ] **Step 4: Live check — links.** Open one Jira, one Confluence and one PR link through the link entry point and check the content. With acli hidden from PATH, the guide and the `m` menu must appear.
- [ ] **Step 5: Live check — jump to line.** Opening `scripts/glowp.py:120` shows line 120 on screen, highlighted.
- [ ] **Step 6:** Update the README and commit: `feat: pager viewer with bat, toggle and link previews`
