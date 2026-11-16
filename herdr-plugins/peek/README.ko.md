# peek

[English](README.md) | **한국어**

pane에 보이는 경로를 **선택하거나** 링크를 **Control + 클릭하면**, 그 pane 오른쪽에서 웹 페이지처럼 렌더링해 보여 주는 herdr 플러그인입니다. 선택하거나 클릭하지 않으면 아무것도 열지 않습니다.

macOS에 들어 있는 WebKit이 화면 밖에서 페이지를 그리고, 그 그림을 Kitty 그래픽으로 herdr pane에 pane의 원래 해상도 그대로 보여 줍니다. 따로 설치할 것은 없습니다. glow, bat, python3, CLI 도구 모두 필요 없습니다.

## 여는 방법

**경로 선택하기:** 아무 pane에서나(Claude Code, 셸, 로그) 경로를 드래그하거나 더블클릭합니다. herdr는 마우스로 선택한 글자를 클립보드에 복사합니다(`copy_on_select`, 기본으로 켜져 있음). peek은 클립보드를 지켜보다가, 복사된 글자가 지금 탭의 pane 화면에 있고 파일을 가리키면 그 pane 옆에 엽니다.

- 글자에 `/`, 확장자, `:줄` 중 하나가 있어야 합니다. 그래서 `peek`, `LICENSE` 같은 그냥 단어는 열리지 않습니다.
- 고른 글자 그대로는 파일이 아니면, 끝에서 최대 네 글자까지 줄여 가며 찾습니다. 그래서 경로에 붙은 조사는 걸리지 않습니다(`kitty.rs:58에서`는 58번째 줄을 엽니다). 한글 폴더와 한글 파일 이름은 고른 그대로 열립니다.
- 폴더는 (아직) 열지 않습니다.
- 감지하지 못하는 경우: 같은 글자를 연달아 고를 때(클립보드에 이미 있는 글자는 herdr가 다시 복사하지 않음), 프로그램이 두 줄로 나눠 찍은 경로(한 줄 안의 부분, 예를 들어 파일 이름만 고르면 됨), SSH로 붙은 herdr 클라이언트, `copy_on_select = false`.
- 복사하려고 고른 경로도 열립니다. 포커스는 가져가지 않습니다. 끄고 켜려면 herdr 액션 `peek: select to open on/off`를 쓰세요.
- 복사된 글자는 메모리에서만 확인하고 저장하지 않습니다. `~/.local/state/peek/watch.log`에는 연 파일만 남습니다. 감시 프로그램(`peek watch`, herdr 서버마다 하나)은 herdr가 시작할 때나 peek이 처음 실행될 때 뜨고, 서버가 끝나면 같이 끝납니다.

**링크를 Control + 클릭하기:** herdr는 **Control**을 누른 채 클릭할 때만 클릭을 플러그인에 넘깁니다. macOS에서도 마찬가지입니다. herdr가 받는 마우스 신호로는 Command와 그냥 클릭을 구별할 수 없기 때문입니다. 넘기는 대상도 두 가지뿐입니다.

- 그냥 글자로 출력된 웹 주소(`http://`, `https://`): Jira, Confluence, GitHub PR 주소는 peek에서, 그 밖의 주소는 브라우저에서 열립니다.
- 프로그램이 출력한 하이퍼링크(OSC 8): 주소가 무엇이든 넘깁니다. `file:///Users/me/a.md`, `docs/a.md`, `src/app.rs:42` 모두 됩니다.

그냥 글자로 출력된 경로는 클릭할 수 없습니다. herdr가 그냥 글자에서는 경로를 찾지 않기 때문입니다([herdr discussion #609](https://github.com/herdrdev/herdr/discussions/609)에 요청이 올라와 있습니다). 그런 경로는 선택해서 여세요. 클릭하려면 herdr의 마우스 캡처(`ui.mouse_capture`, 기본으로 켜져 있음)도 켜져 있어야 합니다.

| 열리는 것 | 보이는 모습 |
|---|---|
| `.md`·`.markdown` 경로 | 렌더링한 마크다운(표, 체크리스트, 각주, 이미지). `v`로 원문 전환 |
| 소스 경로(`.py` `.java` `.kt` `.ts` `.rs` …). 끝에 `:줄`이 있으면 그 줄로 이동해 표시 | 줄 번호가 붙은 문법 강조 소스 |
| 이미지(`.png` `.jpg` `.gif` `.webp` `.svg`)나 `.html` 파일 | 이미지, 또는 자체 스타일을 그대로 적용한 페이지 |
| Jira `…atlassian.net/browse/KEY` | 요약, 상태, 담당자, 설명, 댓글 |
| Confluence `…atlassian.net/wiki/…/pages/<id>` | 페이지 본문 |
| GitHub PR `github.com/<o>/<r>/pull/<n>` | 제목, 상태, 설명, 댓글 |

- 줄여 쓴 경로(`docs/a.md`, `…/deep/a.md`, `a.md`)는 네 곳에서 한꺼번에 찾습니다. pane의 작업 폴더, 세션 scratchpad, 세션 기록(transcript), git 저장소입니다. 하나면 바로 열고, 여럿이면 번호 목록을 보여 주고, 없으면 herdr 알림을 띄웁니다.
- 뷰어는 선택하거나 클릭한 pane마다 하나이고, 포커스를 가져가지 않고 열립니다. 보고 있는 파일을 지켜보다가 Claude나 사용자가 저장하면 읽던 위치 그대로 다시 그립니다.
- 페이지 스크립트는 실행하지 않습니다. 마크다운 안의 HTML은 보이기만 하고 동작하지 않습니다. HTML 파일은 자체 스타일시트를 쓰되 스크립트는 꺼져 있습니다. 원격 이미지는 불러옵니다. mermaid와 수식은 코드로 보입니다.

## 키와 상단 막대

뷰어 맨 윗줄은 막대입니다. 문서 이름, 그리고 `⟳ Reload`, `⌕ Find`, `</> Source`(원문을 보는 동안은 `◉ View`. 누를 때마다 둘이 바뀜), `↗ Browser`, `… More`가 있습니다. `… More`를 누르면 이 줄이 `−` 100% `+` `Reset` `⎙ Screenshot` `✕`로 바뀝니다. 항목에 마우스를 올리면 이름과 키가 보이고, 클릭하면 실행됩니다. pane이 좁으면 글자 없이 기호만 보입니다.

`/`나 `⌕`를 누르면 막대 자리에 찾기 줄이 열립니다. 캐럿이 있는 입력칸, `Aa`(대소문자 구분), `ab`(단어 단위), `.*`(정규식), 위치(`3/12`), `↑` `↓` `✕`가 있습니다. 찾기 줄이 열려 있는 동안 입력은 편집기처럼 입력칸으로 갑니다. `Enter`나 `↓`는 다음, `Shift-Enter`나 `↑`는 이전, `Esc`나 `✕`는 닫기이고, PgUp/PgDn과 휠로는 그대로 스크롤됩니다. `Alt-c`, `Alt-w`, `Alt-r`로 옵션을 바꿉니다. 단어 단위와 정규식은 함께 켜지지 않고(하나를 켜면 다른 하나가 꺼짐), 대소문자 구분은 둘 다와 함께 쓸 수 있습니다.

| 키 | 하는 일 |
|---|---|
| `j` `k` ↑ ↓, 휠 | 몇 줄 스크롤 |
| `space` `b` PgDn PgUp | 한 화면 스크롤 |
| `g` `G` | 처음, 끝 |
| `/` | 찾기(위 설명) |
| `r` | 다시 읽기(링크는 다시 받아 옴) |
| `v` | 렌더링 ↔ 원문 |
| `+` `-` `0` | 확대, 축소, 원래대로(50~200 %, 기억함) |
| `s` | 지금 화면 스크린샷. 클립보드에도 복사하고, 저장한 경로를 아래쪽 토스트로 알려 줌 |
| `o` | 브라우저로 열기(로컬 문서는 이미지까지 포함한 페이지로, 링크는 원래 주소로) |
| 링크 클릭 | 로컬 파일은 여기서 열고, 웹 주소는 브라우저로, `#앵커`는 그 위치로 스크롤 |
| `h` Backspace | 뒤로 |
| `q` | 뷰어 닫기 |

모든 명령은 herdr 액션(`peek: reload`, `peek: zoom in` …)으로도 있어서 Claude pane에서도 쓸 수 있습니다. 키에 묶으려면 `~/.config/herdr/config.toml`에 다음을 넣으세요(`herdr config check`를 통과하는 형식입니다).

```toml
[[keys.command]]
key = "prefix+v"
type = "plugin_action"
command = "nyjin.peek:toggle-view"
```

## Jira, Confluence, GitHub 토큰

링크는 각 서비스의 API로 받아 오기 때문에, 서비스마다 토큰을 한 번 등록해야 합니다. 토큰은 macOS 키체인(서비스 이름 `peek`)에 저장됩니다.

```sh
peek auth atlassian <site>.atlassian.net   # 이메일, 그다음 API 토큰(id.atlassian.com → Security → API tokens)
peek auth github                           # GitHub 토큰(공개 저장소도 필요합니다)
```

플러그인의 바이너리로 실행합니다: `<플러그인 폴더>/bin/peek auth …`. 토큰이 없으면 뷰어가 실행할 명령을 알려 줍니다. 실행한 뒤 `r`을 누르세요.

## 파일이 놓이는 곳

```
/tmp/peek-<uid>/<project>/<session>/      다른 사용자는 읽을 수 없음(0700). <session>은 그 pane의 Claude 세션, 없으면 pane-<id>
  screenshots/<YYYYMMDD-HHMMSS>-<문서>[-L<줄>].png
  browser/<문서>.html                     브라우저로 넘긴 페이지
  pages/                                  뷰어가 불러오는 페이지
  viewer.log                              마지막 뷰어 실행의 시간 기록과 오류
~/.local/state/peek/                      뷰어마다 보여 줄 것, 확대 배율, 선택해서 열기 설정, watch.log
~/.cache/peek/links/                      받아 온 Jira, Confluence, PR 페이지와 이미지
```

`/tmp`는 재시작할 때 비워질 수 있습니다. 남겨 둘 스크린샷은 다른 곳으로 옮기세요.

## 설치 / 제거

```sh
git clone https://github.com/nyjin/herdr-skills && cd herdr-skills/herdr-plugins/peek
cargo build --release                       # Rust 툴체인이 필요합니다. 릴리스 다운로드는 준비 중입니다
herdr plugin link "$PWD"                    # 설치
herdr plugin uninstall nyjin.peek           # 제거
```

macOS와 herdr 0.9.3 이상, Kitty 그래픽을 지원하는 터미널(Ghostty)이 필요합니다. pane 안의 그림은 herdr의 표준 Kitty 그래픽으로 그리며, herdr 0.9.5는 이 기능이 기본으로 켜져 있습니다.

0.3.0까지는 이름이 glow-preview(`nyjin.glow-preview`)였습니다. 그것을 설치했다면 `herdr plugin uninstall nyjin.glow-preview`로 지운 뒤 peek을 설치하세요.

## 구성

- `src/`: 크레이트 하나입니다. 플랫폼과 무관한 모듈(`target`, `resolve`, `state`, `herdr`, `link`, `page`, `script`, `fetch`, `kitty`, `term`)은 어디서나 빌드·테스트되고, `src/mac/`(WebKit 렌더러, 뷰어, 파일 감시, 키체인, 클립보드)은 macOS가 필요합니다.
- `bin/peek`: 이 폴더에서 빌드한 바이너리를 실행합니다.
- `tests/`: `cargo test`(`scripts/check.sh unit`이 실행합니다).
- `evals/`: 렌더링 실험과 측정 결과(`evals/results.md`). 스크린샷은 로컬에만 둡니다.
- 설계: `docs/superpowers/specs/2026-11-15-peek-webkit-viewer-design.md`.
