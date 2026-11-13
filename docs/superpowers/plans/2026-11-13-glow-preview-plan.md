# glow-preview Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Claude Code pane 오른쪽에 glow 뷰어 pane을 띄우는 herdr 플러그인. 띄우는 계기는 두 가지로, Claude가 `.md`를 다룰 때와 사용자가 화면의 `.md` 경로를 클릭할 때다.

**Architecture:** Python 스크립트 하나(`glowp.py`)가 세 진입점을 맡는다: `hook`(Claude Code PostToolUse), `link`(herdr link handler action), `viewer`(플러그인 pane). hook과 link는 `<state>/<source-pane>.json`에 보여줄 경로를 쓰고 뷰어 pane이 없으면 연다. viewer는 그 파일을 지켜보며 glow를 다시 띄운다. 경로 찾기는 `resolve.py`가 맡는다.

**Tech Stack:** python3 표준 라이브러리, herdr 0.9.3 CLI, glow 3 (brew), unittest.

**Spec:** `docs/superpowers/specs/2026-11-13-glow-preview-design.md`

## Global Constraints

- macOS 전용, python3 표준 라이브러리만.
- plugin id `nyjin.glow-preview`, pane entrypoint id `viewer`, 상태 폴더 `~/.local/state/glow-preview` 고정 (테스트만 `GLOWP_STATE_DIR`). herdr가 plugin pane에 주는 `HERDR_PLUGIN_STATE_DIR`은 훅에서 보이지 않으므로 쓰지 않는다.
- herdr 실행 파일은 `$HERDR_BIN_PATH`, 없으면 `herdr`. 테스트에서는 `GLOWP_HERDR`로 바꿀 수 있다.
- 훅은 언제나 종료 코드 0, stdout 출력 없음.
- 뷰어 pane은 `--placement split --direction right --target-pane <source> --no-focus`로 연다.
- 사용자 셸에 명령을 타이핑하지 않는다 (`pane run`, `send-text` 금지).

## Review Focus

1. 클릭 문자열에 `:12`, `file://`, 끝 구두점(`.md),` `.md.`)이 붙는 경우 → 파일을 찾아야 한다. Task 1 `test_normalize_*`.
2. 세션 id가 없는 pane(claude가 아닌 셸)에서 클릭 → 작업 폴더·git만으로 찾고 오류 없이 동작. Task 1 `test_no_session`.
3. 뷰어 pane을 사용자가 닫은 뒤 다시 `.md`를 다룸 → 새 뷰어가 열려야 한다 (죽은 pane id를 재사용하지 않는다). Task 2 `test_reopens_when_viewer_gone`.
4. `.MD`나 `.markdown` 확장자 → 대상에 포함. 대상이 아닌 `.mdx`·`.md.bak` → 무시. Task 2 `test_hook_extensions`.
5. glow가 실행 중일 때 파일이 바뀜 → 터미널이 깨지지 않고 새 파일이 보여야 한다. Task 3 실측.

---

### Task 1: 경로 찾기 (`scripts/resolve.py`)

**Files:**
- Create: `scripts/resolve.py`
- Test: `tests/test_resolve.py`

**Interfaces:**
- Produces:
  - `normalize(text: str) -> str`: `file://` 접두어, 감싼 따옴표·괄호·백틱, 끝의 `:줄[:열]`, `.md` 뒤에 붙은 구두점을 떼어 낸다.
  - `candidates(text: str, cwd: str | None, session_id: str | None, *, home: str, tmp_root: str, projects_root: str) -> list[str]`: realpath 기준으로 중복을 지운 실제 파일 목록을 돌려준다. 정렬 기준은 대화 기록에서 마지막으로 나온 위치가 늦은 것이 먼저이고, 대화 기록에 없는 것은 그 뒤에 경로 사전순으로 둔다. 절대경로와 `~/`는 파일이 있으면 그 하나만, 없으면 `[]`. `tmp_root`는 `/private/tmp/claude-<uid>`, `projects_root`는 `~/.claude/projects`.

- [ ] **Step 1: 실패하는 테스트 작성** — 임시 폴더에 home·repo(git init, 파일 커밋)·tmp_root·projects_root를 꾸민다.
  - `test_absolute_and_home`: 존재하는 절대경로 → `[그 경로]`, `~/x.md` → `[home/x.md]`, 없는 절대경로 → `[]`
  - `test_relative_to_cwd`: `docs/a.md` → `[repo/docs/a.md]`
  - `test_scratchpad`: `tmp_root/<proj>/<sid>/scratchpad/n.md`가 있을 때 `scratchpad/n.md`와 `n.md` 모두 → `[그 파일]`
  - `test_transcript_suffix`: `projects_root/p/<sid>.jsonl`에 `"file_path":"/elsewhere/deep/z.md"` 줄이 있고 파일이 존재할 때 `…/deep/z.md` → `[/elsewhere/deep/z.md]`
  - `test_git_suffix`: repo의 `pkg/sub/b.md`를 `sub/b.md`로 찾는다
  - `test_dedupe_same_file`: 같은 파일이 작업 폴더·git·대화 기록 모두에서 나오면 1개
  - `test_ambiguous_order`: `SKILL.md`가 두 곳에 있고 대화 기록에 A, B, A 순으로 나오면 `[A, B]`
  - `test_no_session`: `session_id=None`이어도 작업 폴더·git으로 찾는다
  - `test_normalize_suffixes`: `normalize("file:///x/a.md:12:3") == "/x/a.md"`, `normalize("(docs/a.md),") == "docs/a.md"`, `normalize("`a.md`.") == "a.md"`
- [ ] **Step 2: 실행해서 실패 확인** — `python3 -m unittest tests.test_resolve -v` → `ModuleNotFoundError`
- [ ] **Step 3: 구현** — git 파일 목록은 `git -C <cwd> ls-files -co --exclude-standard --full-name`과 `rev-parse --show-toplevel`로 만든다. 대화 기록의 절대경로 추출 정규식은 `(?:/|~/)[^\s"'`()<>\[\]{}|,:;\\]+\.md`. 끝부분 일치 비교는 `"/" + 정리된 문자열`로 한다.
- [ ] **Step 4: 통과 확인** — 같은 명령 → OK
- [ ] **Step 5: 커밋** — `git add scripts/resolve.py tests/test_resolve.py && git commit -m "feat: resolve clicked markdown paths to files"`

### Task 2: 훅·링크·상태 (`scripts/glowp.py` 의 hook / link / show)

**Files:**
- Create: `scripts/glowp.py`
- Test: `tests/test_glowp.py`, `tests/fake_herdr.py` (호출을 JSON 줄로 기록하고, `pane get`·`pane list`에는 환경변수로 받은 JSON을 돌려주는 가짜 herdr)

**Interfaces:**
- Consumes: `resolve.normalize`, `resolve.candidates`
- Produces:
  - `is_markdown(path: str) -> bool`: 소문자 기준으로 `.md` 또는 `.markdown`으로 끝나면 참
  - `state_dir() -> str`
  - `show(source: str, paths: list[str]) -> None`: `<state>/<source>.json`에 `{"paths": [...], "seq": <time_ns>}`를 원자적으로 쓴다. `<state>/<source>.viewer`에 적힌 pane이 `pane list`에 없으면 `plugin pane open --plugin nyjin.glow-preview --entrypoint viewer --placement split --target-pane <source> --direction right --no-focus --env GLOWP_SOURCE=<source>`를 호출한다.
  - `main(argv)`: `hook`은 stdin JSON의 `tool_input.file_path`와 `$HERDR_PANE_ID`를 쓰고, 모든 예외를 삼키고 0을 돌려준다. `link`는 `$HERDR_PLUGIN_CLICKED_URL`과 `$HERDR_PANE_ID`를 쓴다. `pane get <id>`에서 `foreground_cwd`(없으면 `cwd`)와 `agent_session.value`를 읽고, 후보가 0개면 `notification show "glow-preview" --body "파일을 찾지 못했습니다: <text>"`를 호출한다.

- [ ] **Step 1: 실패하는 테스트 작성**
  - `test_hook_opens_viewer`: `.md` 경로가 담긴 훅 입력 → 상태 파일에 그 경로가 들어가고, 가짜 herdr에 `plugin pane open … --target-pane <src> --direction right` 호출이 기록된다
  - `test_hook_extensions`: `.MD`, `.markdown`은 처리하고 `.mdx`, `.md.bak`, `.py`는 상태 파일을 쓰지 않는다
  - `test_hook_silent_outside_herdr`: `HERDR_PANE_ID`가 없으면 아무것도 하지 않고 0
  - `test_hook_never_fails`: 깨진 JSON → 종료 코드 0, stdout 비어 있음
  - `test_reuses_live_viewer`: `.viewer`에 적힌 pane이 `pane list`에 있으면 `plugin pane open`을 다시 부르지 않는다
  - `test_reopens_when_viewer_gone`: `.viewer`에 적힌 pane이 목록에 없으면 다시 연다
  - `test_concurrent_hooks_open_one_viewer`: 훅 4개가 동시에 실행돼도 `plugin pane open`은 1번 (소스 pane별 잠금 + open 응답의 pane id를 바로 `.viewer`에 기록)
  - `test_link_not_found_notifies`: 후보가 0개 → `notification show` 호출, 상태 파일 없음
  - `test_link_ambiguous_writes_all`: 후보가 2개 → 상태 파일 `paths` 길이 2
- [ ] **Step 2: 실행해서 실패 확인** — `python3 -m unittest tests.test_glowp -v`
- [ ] **Step 3: 구현**
- [ ] **Step 4: 통과 확인** — `python3 -m unittest discover -s tests -v` 전부 OK
- [ ] **Step 5: 커밋** — `feat: open the viewer from the Claude hook and herdr link clicks`

### Task 3: 뷰어 pane, 매니페스트, 설치

**Files:**
- Modify: `scripts/glowp.py` (`viewer` 서브커맨드)
- Create: `herdr-plugin.toml`, `install.sh`, `README.md`

**Interfaces:**
- Consumes: Task 2의 상태 파일 형식과 `state_dir()`
- Produces: `viewer`는 `$GLOWP_SOURCE`의 상태 파일을 0.3초마다 확인한다.
  - 시작할 때 자기 `$HERDR_PANE_ID`를 `<source>.viewer`에 쓴다.
  - glow가 없으면 `notification show`로 알리고 `brew install glow`를 이 pane 안에서 실행한다.
  - `paths`가 1개면 glow TUI를 자식 프로세스로 띄운다. `seq`가 바뀌면 자식에게 SIGTERM을 보내고, 화면 상태를 복구한 뒤(`stty sane`, 대체 화면 해제 `\x1b[?1049l`, 커서 표시 `\x1b[?25h`) 새로 띄운다.
  - `paths`가 여러 개면 번호 목록을 출력하고 숫자 키를 받아 고른다. 입력을 기다리는 동안에도 상태 파일 변경을 감지한다.
  - glow가 스스로 끝나면 "r 다시 열기 · q 닫기"를 보여 준다.

- [ ] **Step 1: 매니페스트 작성** — id `nyjin.glow-preview`, `min_herdr_version = "0.9.3"`, `platforms = ["macos"]`. `[[panes]]` id `viewer`, placement `split`, command `["sh","-c","exec python3 \"$HERDR_PLUGIN_ROOT/scripts/glowp.py\" viewer"]`. `[[actions]]` id `open-link`, command `["python3","scripts/glowp.py","link"]`. `[[link_handlers]]` id `markdown`, `pattern`은 `.md`/`.markdown`으로 끝나는 문자열에 맞는 정규식, action `open-link`.
- [ ] **Step 2: `install.sh` 작성** — `herdr plugin link "$PWD"` (이미 붙어 있으면 넘어감). `~/.claude/settings.json`을 백업하고, `PostToolUse`에 matcher `Read|Write|Edit|MultiEdit`, `async: true`, command `[ "$HERDR_ENV" = 1 ] || exit 0; python3 "<root>/scripts/glowp.py" hook`인 그룹을 하나만 추가한다 (같은 그룹이 있으면 추가하지 않는다).
- [ ] **Step 3: 뷰어 구현**
- [ ] **Step 4: 실측 — 설치** — `sh install.sh` → `herdr plugin list`에 `nyjin.glow-preview`가 enabled로 나오고, settings.json 그룹이 1개
- [ ] **Step 5: 실측 — 훅 경로** — 이 Claude pane에서 `.md` 하나를 Read → 오른쪽에 pane이 생기고, `pane process-info`에 glow가 보이고, 포커스는 그대로. glow가 없었다면 설치 알림과 설치 과정이 그 pane에 나타난다
- [ ] **Step 6: 실측 — 파일 교체** — 다른 `.md`를 Read → 같은 pane에서 glow가 새 파일로 다시 뜬다 (`pane read`로 확인). 새 pane이 생기지 않는다
- [ ] **Step 7: 실측 — 닫은 뒤 다시 열기** — 뷰어 pane을 닫고 `.md`를 Read → 새 뷰어가 열린다
- [ ] **Step 8: 링크 경로** — `HERDR_PLUGIN_CLICKED_URL=README.md HERDR_PANE_ID=<this> python3 scripts/glowp.py link` → 뷰어에 표시. 실제 마우스 클릭은 사용자 확인 항목으로 남긴다
- [ ] **Step 9: README와 커밋** — README에 설치·동작·제거 방법을 쓰고 커밋한다: `feat: glow viewer pane, manifest and installer`
