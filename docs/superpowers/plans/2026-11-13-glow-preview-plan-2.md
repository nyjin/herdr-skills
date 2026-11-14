# glow-preview 2차 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 뷰어가 소스코드(bat)와 링크(Jira·Confluence·GitHub PR)도 보여 주고, `.md`를 렌더링과 원문 사이에서 전환할 수 있게 한다.

**Architecture:** 상태 파일 `paths` 대신 `items: [{"path": str, "line": int|None} | {"url": str}]`를 쓴다. 링크 클릭은 `targets.classify`로 URL과 경로를 나눈다. 뷰어는 URL 항목을 `fetch.fetch_markdown`으로 캐시 파일에 쓴 뒤 `.md`처럼 보여 준다. 보기 방식은 `<source>.mode`(`rendered`|`source`)에 담고, 메뉴 키와 herdr 액션으로 바꾼다.

**Tech Stack:** python3 표준 라이브러리, glow 3 (`-p`), bat, less, acli, gh, claude CLI(MCP 경로만).

**Spec:** `docs/superpowers/specs/2026-11-13-glow-preview-design.md` (2차 확장 절)

## Global Constraints

- CLI 호출은 모두 제한 시간을 둔다: acli·gh 30초, MCP(`claude -p`) 360초.
- `glow.yml`은 수정하지 않는다. glow는 `-p -w <cols-2>`로, pager는 `PAGER="less -R"`로 실행한다.
- 자동(훅)으로 여는 것은 `.md`·`.markdown`뿐이다.
- 캐시 위치는 `~/.cache/glow-preview/`, 테스트에서는 `GLOWP_CACHE_DIR`.
- gh는 `PATH`의 `gh`를 그대로 쓴다. 사용자 래퍼를 거쳐야 계정이 맞게 골라진다.

## Review Focus

1. Confluence 짧은 링크(`/wiki/x/AbCd`)처럼 page id가 없는 URL → 안내 화면, 오류 종료 금지. `test_confluence_without_id_guides`
2. acli가 30초 넘게 응답하지 않음 → 시간 초과 안내. `test_timeout_guides`
3. ADF에 처음 보는 노드 → 텍스트를 잃지 않음. `test_unknown_node_keeps_text`
4. 표 셀 안의 줄바꿈·파이프 문자 → 표가 깨지지 않음. `test_table_cell_escapes`
5. `src/a.py:42` 클릭 → 42번째 줄로 이동하고 강조. 실측 (Task 4 Step 5)

---

### Task 1: ADF → 마크다운 (`scripts/adf.py`)

**Files:** Create `scripts/adf.py`, `tests/test_adf.py`

**Interfaces:**
- Produces: `to_markdown(doc: dict | str | None) -> str`. 문자열이면 JSON으로 파싱한다.

- [ ] **Step 1: 테스트 작성.** 손으로 만든 작은 ADF 조각으로 테스트한다.
  - `test_blocks`: 블록 요소 변환
    - heading 2 → `## 제목`
    - paragraph 두 개 → 빈 줄로 구분
    - bulletList·orderedList(중첩 포함) → `- `/`1. ` + 들여쓰기 2칸
    - codeBlock(language) → 펜스 코드 블록
    - blockquote → `> `
    - rule → `---`
    - panel → `> **ℹ️**`로 시작하는 인용
    - expand(title) → `**▸ title**` 뒤에 본문
    - taskList → `- [ ]`/`- [x]`
    - decisionList → `- ✔︎ `
  - `test_inline`: 인라인 요소 변환
    - 마크 strong `**`, em `_`, code `` ` ``, strike `~~`, link `[t](href)`
    - underline·textColor·backgroundColor·annotation·alignment·breakout·indentation·fontSize·border는 무시
    - hardBreak → 줄바꿈
    - mention → `@이름`
    - inlineCard·blockCard·embedCard → `<url>`
    - status → `` `[STATUS]` ``
    - date(timestamp ms) → `YYYY-MM-DD`
    - emoji → shortName
    - media·mediaSingle·mediaGroup·mediaInline → `[첨부: alt|파일]`
  - `test_table_cell_escapes`: 첫 행(tableHeader)이 헤더가 된다. 셀 안의 `|`는 `\|`로, 줄바꿈은 `<br>`로 바꾼다.
  - `test_unknown_node_keeps_text`: `{"type":"mystery","content":[text "abc"]}` → `abc`가 남는다.
  - `test_extension`: extension → `[Confluence 매크로: extensionKey]`
- [ ] **Step 2:** `python3 -m unittest tests.test_adf -v` → 실패 확인
- [ ] **Step 3: 구현**
- [ ] **Step 4:** 통과 확인. 그다음 세션에서 모은 문서 51개(scratchpad `adf_corpus.json`)를 모두 변환해 예외 0건인지 확인한다.
- [ ] **Step 5: 커밋** — `feat: convert Atlassian documents to markdown`

### Task 2: 링크 분류와 가져오기 (`scripts/targets.py`, `scripts/fetch.py`)

**Files:** Create `scripts/targets.py`, `scripts/fetch.py`, `tests/test_fetch.py`, `tests/fake_cli.py` (acli·gh·claude 흉내. 동작은 환경변수 `FAKE_MODE`로 고른다: `ok`, `auth`, `notfound`, `hang`)

**Interfaces:**
- Consumes: `adf.to_markdown`
- Produces:
  - `targets.classify(text: str) -> dict`. 결과는 셋 중 하나다.
    - `{"kind": "jira", "url", "key"}`
    - `{"kind": "confluence", "url", "page_id": str|None}`
    - `{"kind": "github_pr", "url", "repo": "o/r", "number": str}`
    - `{"kind": "path", "text": str, "line": int|None}` (`resolve.normalize` 뒤 끝의 `:줄[:열]`에서 줄을 읽는다)
  - `fetch.fetch_markdown(url: str, *, via: str = "cli", timeout: int = 30) -> tuple[str, bool]`. `(마크다운, 성공 여부)`를 돌려준다. 실패하면 마크다운에 원인별 안내를 담는다. 원인은 `missing`·`auth`·`notfound`·`timeout`·`noid`·`error`다. Jira·Confluence 실패 안내에는 `m` 키 MCP 안내(3~4분, 약 $0.02)를 넣는다.
  - `via="mcp"`는 `claude -p`에 Atlassian MCP 도구 두 개만 허용해 실행하고, 결과 마크다운을 그대로 쓴다. 모델은 `claude-haiku-5-5`, `--max-turns 6`이다.
  - `fetch.cache_path(url: str) -> str`: `<cache>/<sha1(url)[:12]>.md`
- [ ] **Step 1: 테스트 작성** (fake_cli를 `PATH` 맨 앞에 `acli`·`gh`·`claude` 이름으로 링크한다)
  - `test_classify`: 다음 다섯 입력이 각각 올바르게 분류된다.
    - Jira browse URL
    - Confluence `/pages/123/title`와 `/wiki/x/AbCd`(page_id None)
    - PR URL
    - `src/a.py:42:3` → path, line 42
  - `test_jira_ok`: 결과에 `# KEY 요약`, 상태·담당자 줄, ADF 본문, `## 코멘트`가 들어간다.
  - `test_confluence_ok`: 결과에 `# 제목`과 본문이 들어간다. acli 호출 인자에 `--body-format atlas_doc_format`이 있다.
  - `test_pr_ok`: gh 호출에 `-R o/r`가 있다. 결과에 제목·상태·작성자, 리뷰(작성자·상태·본문), 인라인 코멘트(`path:line`), 바뀐 파일 목록이 들어간다.
  - `test_auth_guides`: acli 인증 오류 → ok False이고 안내에 `acli jira auth login`이 들어간다(Confluence는 `acli confluence auth login`).
  - `test_missing_cli_guides`: acli가 PATH에 없음 → `brew install acli` 안내
  - `test_timeout_guides`: hang 모드에서 `timeout=1`이면 "시간 초과" 안내
  - `test_confluence_without_id_guides`: page id 없음 → 안내, CLI 호출 없음
  - `test_pr_api_account_fallback`: `gh api`가 첫 시도에 404 → `gh auth token --user <두 번째 계정>`으로 다시 시도해 인라인 코멘트를 얻는다.
- [ ] **Step 2:** 실패 확인
- [ ] **Step 3: 구현**
- [ ] **Step 4:** 통과 확인. 그다음 세션 링크 실물로 Jira 3·Confluence 3·PR 3건을 `fetch_markdown`으로 가져와 렌더링 결과를 눈으로 확인한다.
- [ ] **Step 5: 커밋** — `feat: fetch Jira, Confluence and PR content as markdown`

### Task 3: 상태 형식·링크 진입점·전환 액션 (`glowp.py`)

**Files:** Modify `scripts/glowp.py`, `scripts/resolve.py`, `tests/test_glowp.py`, `tests/test_resolve.py`, `herdr-plugin.toml`

**Interfaces:**
- Produces:
  - 상태 파일 `{"items": [...], "seq": int}`
  - `show(source: str, items: list[dict])`
  - `resolve.candidates(…)`가 확장자와 상관없이 동작한다. 대화 기록 정규식을 "점이 있는 파일명"으로 넓힌다.
  - `glowp.py toggle`: `$HERDR_PANE_ID`가 어떤 `<src>.viewer`의 pane이면 그 src, 아니면 자기 자신을 source로 본다. `<src>.mode`를 뒤집고 seq를 올린다.
- [ ] **Step 1: 테스트 수정·추가**
  - 기존 테스트의 `paths`를 `items`로 바꾼다.
  - `test_link_url_item`: Jira URL 클릭 → 상태 `items == [{"url": …}]`, resolve를 부르지 않는다.
  - `test_link_source_line`: `docs/b.py:7` → `items == [{"path": …/b.py, "line": 7}]`
  - `test_toggle_from_viewer_pane`: 뷰어 pane에서 toggle → `<src>.mode`가 `source`가 되고 seq가 바뀐다. 한 번 더 하면 `rendered`가 된다.
  - `test_resolve_any_extension`: `pkg/x.py`를 git 끝부분 일치로 찾는다.
- [ ] **Step 2:** 실패 확인 → **Step 3:** 구현
- [ ] **Step 3b: 매니페스트 수정**
  - `[[actions]] toggle-view`(contexts pane)을 추가한다.
  - `[[link_handlers]]`를 추가한다. 모두 action은 `open-link`다.
    - `source`: 확장자 목록 `py|java|kt|kts|ts|tsx|js|jsx|go|rs|sh|sql|ya?ml|toml|json|xml|gradle|rb|swift|c|h|cpp|hpp`
    - `jira`: `https://[^/\s]+\.atlassian\.net/browse/[A-Z][A-Z0-9]+-\d+`
    - `confluence`: `https://[^/\s]+\.atlassian\.net/wiki/\S+`
    - `github-pr`: `https://github\.com/[^/\s]+/[^/\s]+/pull/\d+`
- [ ] **Step 4:** 통과 확인 → **Step 5:** 커밋 `feat: link items for source files and URLs; toggle action`

### Task 4: 뷰어 (pager·bat·URL·메뉴)

**Files:** Modify `scripts/glowp.py` (`viewer`), `README.md`

- [ ] **Step 1: 구현**
  - 폭은 `shutil.get_terminal_size().columns - 2`로 정한다.
  - 보여 주는 방식:
    - `.md`이고 렌더링 모드: `glow -p -w W -s auto <file>`, `PAGER="less -R"`
    - 원문 모드나 소스코드: `bat --paging=always --pager "less -R +<n>g -j.3" --highlight-line <n>`. n은 bat의 머리줄 수만큼 보정한다(Step 5에서 실측으로 정한다).
    - URL 항목: 먼저 "가져오는 중…"을 출력하고 `fetch_markdown`으로 캐시 파일을 만든다. 그다음 `.md`로 보여 준다.
  - pager에서 나오면 메뉴를 보여 준다.
    - `r` 다시 보기
    - `s` 렌더링/원문 전환(`.md`일 때만)
    - `o` 브라우저(URL일 때만)
    - `m` MCP로 가져오기(Atlassian 실패일 때만)
    - `q` 닫기
  - bat이 없으면 glow처럼 알리고 `brew install bat`으로 설치한다.
- [ ] **Step 2: 실측 — 한글 문단.** 170칸 pane에서 설계 문서의 "실측 근거" 문단 끝("고르게 한다")이 화면에 있어야 한다.
- [ ] **Step 3: 실측 — 전환.** `toggle` 액션을 실행하면 pager가 떠 있는 상태에서도 원문(bat)으로 바뀌고, 다시 실행하면 렌더링으로 돌아온다.
- [ ] **Step 4: 실측 — 링크.** Jira·Confluence·PR 링크 각 1건을 link 진입점으로 열어 내용을 확인한다. acli를 PATH에서 숨기면 안내와 `m` 메뉴가 나와야 한다.
- [ ] **Step 5: 실측 — 줄 이동.** `scripts/glowp.py:120`을 열면 화면에 120번째 줄이 보이고 강조되어 있다.
- [ ] **Step 6:** README를 갱신하고 커밋한다: `feat: pager viewer with bat, toggle and link previews`
