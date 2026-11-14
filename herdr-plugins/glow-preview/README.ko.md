# glow-preview

[English](README.md) | **한국어**

Claude Code pane에 보이는 파일 경로나 링크를 **클릭하면** 오른쪽 pane에 그 내용을 띄우는 herdr 플러그인이다. 클릭하지 않으면 아무것도 열지 않는다.

| 클릭한 것 | 가져오는 도구 (앞에서부터 시도) | 보여 주는 도구 |
|---|---|---|
| `.md`·`.markdown` 경로 | 파일 그대로 | [glow](https://github.com/charmbracelet/glow)(렌더링) ↔ [bat](https://github.com/sharkdp/bat)(원문) |
| 소스코드 경로 (`.py` `.java` `.kt` `.ts` …). `:줄`이 붙으면 그 줄로 이동하고 강조 | 파일 그대로 | bat |
| Jira `…atlassian.net/browse/KEY` | [acli](https://developer.atlassian.com/cloud/acli/reference/commands/) → [jira-cli](https://github.com/ankitpokhrel/jira-cli) → Atlassian MCP | glow |
| Confluence `…atlassian.net/wiki/…` | [cme](https://github.com/Spenhouet/confluence-markdown-exporter) → Atlassian MCP | glow |
| GitHub PR `github.com/<o>/<r>/pull/<n>` | gh | glow |

- 설치되지 않은 도구는 건너뛰고, 실패한 도구는 다음 도구에 넘긴다.
- 모두 안 되면 도구마다 결과(설치 안 됨, 로그인 필요, 권한 없음, 시간 초과)와 해결 방법을 표로 보여 준다.
- Atlassian MCP는 `claude -p`로 Claude의 Atlassian 커넥터를 부르는 방식이다. 실측으로 Jira 13초, Confluence 27초였고, 부를 때마다 Claude 사용량이 든다. 그래서 순서의 맨 뒤에 둔다.
- 가져온 문서는 URL 해시로 캐시한다. 다시 클릭하면 캐시를 바로 보여 준다. less 아래 줄에 링크, 사용한 도구, 가져온 시각이 나오고, 메뉴의 `f`로 새로 가져온다.
- 짧게 줄인 경로(`docs/a.md`, `…/deep/a.md`, `a.md`)는 네 곳에서 후보를 모아 찾는다: 작업 폴더(`foreground_cwd`), 세션 scratchpad, 세션 대화 기록, git 저장소.
  - 후보가 1개면 바로 연다.
  - 여러 개면 번호 목록을 띄운다. 최근에 다룬 파일이 위에 온다.
  - 없으면 herdr 알림을 띄운다.
- 그 밖의 웹 주소는 가로채지 않고 브라우저로 연다.
- 뷰어는 Claude pane 하나에 하나씩 열리고, 열릴 때 포커스를 가져가지 않는다. glow나 bat이 없으면 알림을 띄우고 `brew install`로 설치한다.

## 도구 설치·로그인

| 도구 | 설치 | 로그인 |
|---|---|---|
| acli | `brew tap atlassian/homebrew-acli && brew install acli` | `acli jira auth login` |
| jira-cli | `brew install ankitpokhrel/jira-cli/jira-cli` | `jira init` (API 토큰은 `JIRA_API_TOKEN`) |
| cme | `uv tool install confluence-markdown-exporter` | `cme config` |
| gh | `brew install gh` | `gh auth login` |
| Atlassian MCP | Claude Code(`claude`) | claude.ai에서 Atlassian 커넥터 연결 |

gh는 PR을 `gh pr view <n> -R <o>/<r>`로 가져온다. 저장소별로 계정을 고르는 gh 래퍼가 있으면 `-R`을 보고 계정을 고른다. 인라인 코멘트를 가져오는 `gh api`는 `-R`을 받지 않는다. 그래서 404가 나면 `gh auth status`에 있는 계정 토큰으로 차례로 다시 시도한다.

## 메뉴 (less에서 `q`)

- `r` 다시 보기
- `s` 렌더링/원문 전환 (마크다운)
- `f` 새로 가져오기 (링크)
- `o` 브라우저로 열기 (링크)
- `q` 뷰어 닫기

렌더링/원문 전환은 herdr 액션 **glow preview: 렌더링/원문 전환**으로도 할 수 있다. 뷰어 pane이나 Claude pane에 포커스를 둔 채 실행하면 된다. 단축키로 쓰려면 `~/.config/herdr/config.toml`에 아래를 추가한다. 이 형식은 `herdr config check`로 검사를 통과했다.

```toml
[[keys.command]]
key = "prefix+v"
type = "plugin_action"
command = "nyjin.glow-preview:toggle-view"
```

## 설치 / 제거

```sh
herdr plugin install nyjin/herdr-skills/herdr-plugins/glow-preview   # 설치
herdr plugin uninstall nyjin.glow-preview                            # 제거
```

이 저장소를 받아 둔 곳에서 바로 쓰려면 `sh herdr-plugins/glow-preview/install.sh`를 실행한다. 이 스크립트는 `herdr plugin link`로 붙이고, 0.1~0.2 버전이 남긴 Claude Code 훅이 있으면 `~/.claude/settings.json`을 백업한 뒤 지운다.

## 구조

- `scripts/glowp.py`: 진입점 세 개
  - `link`: 링크 핸들러
  - `toggle`: 전환 액션
  - `viewer`: 플러그인 pane. 파일과 링크 모두 `load()`를 거쳐 less로 보여 준다
- `scripts/resolve.py`: 클릭한 경로 → 후보 파일
- `scripts/targets.py`: 클릭 문자열 → 링크 종류 또는 경로(+줄)
- `scripts/fetch.py`: 링크 → 마크다운. 도구를 순서대로 시도하고, 모두 안 되면 안내를 만든다
- `scripts/adf.py`: Atlassian 문서(ADF) → 마크다운. acli와 jira-cli 결과에 쓴다
- 상태 (`~/.local/state/glow-preview/`):
  - `<claude-pane>.json`: 보여 줄 항목
  - `.viewer`: 뷰어 pane id
  - `.mode`: 렌더링/원문
- 캐시 (`~/.cache/glow-preview/`):
  - `<해시>.md`: 가져온 문서
  - `.tool`: 사용한 도구
  - `.cme/`: cme 내보내기 폴더
- 테스트: `python3 -m unittest discover -s tests`
