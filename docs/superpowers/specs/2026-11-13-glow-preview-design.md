# glow-preview 설계

## 목적

herdr 안에서 Claude Code를 쓰다가 마크다운 파일이 나오면, 그 Claude pane 바로 오른쪽 pane에 glow TUI로 해당 파일을 띄운다. Claude가 쓰거나 읽은 스펙·계획·문서를 터미널을 떠나지 않고 렌더링된 형태로 읽기 위해서다.

## 목표 / 비목표

- 목표
  - Claude가 `.md` 파일을 Read·Write·Edit·MultiEdit하면 오른쪽 뷰가 그 파일로 바뀐다 (자동).
  - Claude pane에 보이는 `.md` 경로를 클릭하면 그 파일을 오른쪽 뷰에 띄운다 (보조).
  - glow가 없으면 설치하고 사용자에게 알린다.
- 비목표: 마크다운 편집, 스크롤 위치 유지, `.md` 외 파일 형식, Linux·Windows 지원.
- 반목표: 엉뚱한 파일을 조용히 여는 것. Claude 작업을 막거나 늦추는 것. 사용자가 쓰는 셸에 명령을 타이핑하는 것.

## 결정된 방식 (사용자 선택: A)

뷰어 pane이 "현재 파일" 상태 파일을 지켜보다가 바뀌면 glow를 끄고 새 파일로 다시 띄운다. 훅과 링크 핸들러는 상태 파일을 쓰고, 뷰어 pane이 없으면 연다.

검토한 다른 방식:
- B. `review-on-focus`처럼 `herdr pane run`으로 셸에 명령을 보내는 방식: 프로세스 감지·종료 대기·`kill -9` 방어 코드가 필요하고, 다른 프로그램에 입력이 들어갈 위험이 있다.
- C. glamour로 전용 Go 뷰어를 만드는 방식: 가장 매끄럽지만 glow를 쓰지 않게 되고 작업량이 크다.

## 동작

- 뷰어는 Claude pane 하나에 하나씩 둔다. 뷰어는 자기를 연 Claude pane id(`GLOWP_SOURCE`)를 알고, `<state>/<source>.json`을 지켜본다.
- 뷰어 pane은 `herdr plugin pane open --placement split --target-pane <source> --direction right --no-focus`로 연다. 포커스는 Claude에 남는다.
- 뷰어는 자기 pane id를 `<state>/<source>.viewer`에 남긴다. 이 pane이 살아 있으면 새로 열지 않는다.

### 경로 찾기 (링크 클릭 시)

클릭한 문자열은 `file://`, 끝의 `:줄[:열]`, 따옴표·괄호·구두점을 걷어낸 뒤 판단한다.

1. 절대경로·`~/`: 파일이 있으면 바로 연다.
2. 그 밖의 경로: 아래 네 출처에서 후보를 한꺼번에 모은다. 순서는 결과에 영향을 주지 않는다.
   - 작업 폴더: 클릭한 pane의 `foreground_cwd` 기준으로 붙인다 (`cwd`가 아니다. worktree로 들어간 세션에서는 `cwd`가 옛 위치를 가리킨다).
   - scratchpad: `/private/tmp/claude-<uid>/*/<세션id>/scratchpad` 기준으로 붙인다. 세션 id는 pane의 `agent_session.value`다. 맨 앞의 `scratchpad/`는 떼고 붙인다.
   - 대화 기록: `~/.claude/projects/*/<세션id>.jsonl`에 나온 절대경로 중 끝부분이 같은 것.
   - git: `foreground_cwd`가 속한 저장소의 파일(추적·미추적, ignore 제외) 중 끝부분이 같은 것.
   - `…/`로 시작하는 문자열은 끝부분 일치에만 쓴다.
3. 실제 파일 기준(realpath)으로 중복을 지운다.
   - 1개면 연다.
   - 여러 개면 뷰어에 고르는 목록을 띄운다. 대화 기록에서 최근에 나온 것이 위에 온다.
   - 0개면 herdr 알림으로 "파일 없음"을 알린다.

실측 근거 (2026-11-13, 열린 Claude pane 22개, `.md` 경로 169건): 후보가 나온 70건 중 56건은 어느 순서로 찾아도 같은 파일이었다. 14건은 후보가 여러 개였고, 그중 3건은 작업 폴더와 대화 기록이 서로 다른 파일을 가리켰다. 그래서 순서를 정해 먼저 걸린 것을 고르지 않고, 후보가 여러 개면 사용자가 고르게 한다.

### 훅

Claude Code `PostToolUse`, matcher `Read|Write|Edit|MultiEdit`, `async: true`. `tool_input.file_path`가 `.md`이고 `HERDR_PANE_ID`가 있으면 그 경로(항상 절대경로)를 연다. 어떤 실패도 Claude에 보이지 않게 종료 코드 0으로 끝낸다.

### glow

뷰어가 시작할 때 glow가 없으면 herdr 알림으로 설치를 알리고, 뷰어 pane 안에서 `brew install glow`를 실행해 진행 상황을 보여 준다. brew가 없으면 설치 방법을 출력하고 기다린다.

## 제약

- macOS, herdr ≥ 0.9.3 (`link_handlers`, `plugin pane open --env`), python3 표준 라이브러리만 사용.
- 설치 위치: 처음에는 `~/.config/herdr-plugins/glow-preview`(`herdr plugin link`)였고, 지금은 이 저장소의 `herdr-plugins/glow-preview/`다(`herdr plugin install nyjin/herdr-skills/herdr-plugins/glow-preview`). 훅은 `~/.claude/settings.json`에 등록하고, 바꾸기 전에 백업한다.

## 구현자에게 맡기는 것

- glow TUI 실행 인자, 뷰어 화면 문구, 상태 파일 폴링 주기.
- 링크 핸들러 `pattern`의 정확한 형식. herdr에 문서가 없으므로 `plugin link`의 검증 결과와 실제 클릭으로 확인한다.

## 2차 확장 (2026-11-13): 소스·원문 전환·링크 내용 보기

사용자 결정: `.md`는 glow, 소스코드는 bat, GitHub PR은 gh, Jira·Confluence는 acli(안 되면 MCP). 브라우저를 띄우지 않고 CLI로 내용을 가져와 마크다운으로 바꿔 같은 뷰어에서 읽는다. 버튼 조작이나 코멘트 작성은 하지 않는다.

### 보기 방식
- 뷰어는 TUI(`glow -t`)를 쓰지 않는다. TUI는 `-w` 값을 무시하고, 한글 긴 문단을 pane 폭에서 잘라 내용이 사라진다(실측: 170칸 pane에서 설정 80·`-w 0`·`-w 60` 모두 잘림). 그래서 `glow -p -w <pane 폭-2>`(less)를 쓴다. `glow.yml`은 사용자의 일반 glow 사용에도 적용되므로 건드리지 않는다.
- 소스코드는 `bat --paging=always`로 보여 준다. 클릭 문자열 끝의 `:줄`은 그 줄로 이동하고 강조한다.
- `.md`(와 링크에서 가져온 문서)는 렌더링(glow)과 원문(bat)을 오갈 수 있다. 전환 방법은 두 가지다.
  - pager를 `q`로 나온 뒤 메뉴에서 `s` 키로 전환한다.
  - herdr 액션 `glow preview: 렌더링/원문 전환`으로 전환한다. 이 액션은 pager가 떠 있어도 동작한다.
  - 전환한 상태는 그 뷰어에서 유지된다.
- 자동으로 여는 것은 여전히 `.md`뿐이다. 소스코드와 링크는 클릭할 때만 연다.

### 링크
| 링크 | 가져오기 | 실측 (세션 링크 전수) |
|---|---|---|
| `https://*.atlassian.net/browse/KEY` | `acli jira workitem view KEY --json` (요약·상태·담당·본문·코멘트) | 28건 중 27건 성공, 평균 9.9초, 최대 242초 → 제한 시간 30초 |
| `https://*.atlassian.net/wiki/.../pages/<id>` | `acli confluence page view --id <id> --body-format atlas_doc_format --json` | 인증 뒤 23건 모두 성공, 평균 1.7초 |
| `https://github.com/<o>/<r>/pull/<n>` | `gh pr view <n> -R <o>/<r>` + `gh api .../pulls/<n>/comments` | `-R`을 붙이면 43건 모두 성공, 평균 0.9초 |

- Jira·Confluence 본문은 같은 형식(ADF)으로 받으므로 변환기 하나로 마크다운으로 바꾼다. 세션 링크 51개에서 쓰인 노드와 마크를 모두 다룬다. 모르는 노드는 자식 텍스트만 살린다.
- gh: 저장소별로 계정을 고르는 gh 래퍼는 흔히 `-R`이나 현재 폴더의 origin을 보고 계정을 고르고, URL은 보지 않는다. 그래서 `pr view`에는 `-R`을 붙인다. `gh api`는 `-R`을 받지 않으므로, 404가 나면 `gh auth status --json hosts`에 있는 계정 토큰으로 차례로 다시 시도한다.
- 실패하면 원인별 안내를 마크다운으로 만들어 뷰어에 보여 준다.
  - CLI 없음: 설치 명령
  - 인증 오류: `acli … auth login`, `gh auth login`
  - 404: 계정이나 권한 문제
  - 시간 초과
- Jira·Confluence가 실패하면 안내 화면에서 `m`을 눌러 MCP(`claude -p`, Atlassian 커넥터)로 가져올 수 있다. 실측 3분 35초, 약 $0.016. 느리고 비용이 들기 때문에 사용자가 고를 때만 실행하고, 안내 화면에 이 숫자를 함께 보여 준다.
- 링크 화면에서 `o`를 누르면 브라우저로 연다(`open`).
- 가져온 문서는 `~/.cache/glow-preview/`에 저장한다. 다시 열기(`r`)와 원문 보기는 저장한 파일을 쓰고, 새로 가져오는 것은 링크를 다시 클릭할 때다.

### 비목표
웹 화면 재현, 코멘트 작성·승인·상태 변경, 소스코드 자동 열기.

### 변경 (2026-11-13, 실측 후)
- MCP: 첫 시도는 `Reached max turns (6)`로 실패했다. 원인은 두 가지였다. MCP 도구를 불러오는 데(ToolSearch) 한 턴이 들었고, Jira 응답이 7만 5천 자라 파일로 저장된 것을 Bash로 나눠 읽다가 턴을 다 썼다. 그래서 compact view와 필요한 필드만 요청하게 하고, 저장된 결과는 Read로 읽게 했으며, 턴 한도를 12로 올렸다. 그 뒤 Jira 13초, Confluence 27초.
- 링크 캐시: 다시 클릭하면 URL 해시로 저장한 캐시를 바로 보여 준다(사용자 요청). less 아래 줄에 가져온 시각을 보여 주고, 메뉴 `f`로 새로 가져온다. 실패 결과는 캐시하지 않는다. MCP 결과도 같은 캐시에 저장한다.

## 3차 변경 (2026-11-13): 클릭으로만 열기, 도구 순서

사용자 결정:
- **클릭하지 않으면 아무것도 열지 않는다.** Claude Code `PostToolUse` 훅을 없앴다. 이 훅 때문에 다른 세션이 쓰는 작업 메모(`/tmp/<agent-workdir>/…/handoff/*.md`, scratchpad)까지 뷰어로 열렸다. `install.sh`는 이전 버전이 남긴 훅을 settings.json을 백업한 뒤 지운다. 이 결정으로 1차 설계의 "목표: 자동"은 취소된다.
- **Jira**는 acli → jira-cli(`jira issue view KEY --raw`) → Atlassian MCP 순서로, **Confluence**는 cme → Atlassian MCP 순서로 시도한다. 설치되지 않은 도구는 건너뛰고, 실패하면 다음 도구로 넘어간다. 모두 안 되면 도구마다 결과와 해결 방법을 표로 보여 준다. MCP가 자동으로 시도되므로 `m` 키는 없앴다.
- cme: 결과 파일이 생겼는지로 성공을 판단한다(없는 페이지에도 rc 0으로 끝난다). 첨부 받기는 끈다(`CME_EXPORT__ATTACHMENTS_EXPORT=disabled`). 내보낸 파일 사이의 상대 링크는 글자만 남긴다. 제한 시간은 180초다. 긴 페이지 하나가 64초 걸렸고, 첨부를 꺼도 63초였다.
- 실측 (세션 링크): Confluence 23건 중 22건은 cme, 1건은 cme가 60초 제한을 넘겨 MCP로 넘어갔다(121초). 그 뒤 제한을 180초로 올렸다. Jira 5건은 모두 acli, 평균 1.1초. jira-cli는 설치되어 있지 않아 가짜 CLI 테스트로만 확인했다.
- 뷰어는 파일과 링크를 `load(item)` 하나로 연다. 이 함수는 캐시 우선이고, 사용한 도구를 `<해시>.md.tool`에 기록해 less 아래 줄에 보여 준다.

### 공개 전 정리
- MCP 도구 이름은 claude.ai 커넥터 이름에서 나온다. 기본 커넥터(`mcp__claude_ai_Atlassian__…`)와 조직이 "Atlassian MCP"라는 이름으로 등록한 커넥터(`mcp__claude_ai_Atlassian_MCP__…`)를 모두 허용한다.
