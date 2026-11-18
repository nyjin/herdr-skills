# herdr-skills

[English](README.md) | **한국어**

터미널 안에서 돌아가는 에이전트 멀티플렉서 [herdr](https://herdr.dev)를 위한 Agent Skills와 herdr 플러그인 모음입니다. 여러 코딩 에이전트를 git worktree로 나눠 병렬로 돌리고, 보이지 않는 서브에이전트 대신 각 Claude Code 작업자가 일하는 모습을 herdr 사이드바에서 직접 봅니다. 하나씩 따로 설치합니다. 스킬은 `gh skill`이나 `npx skills`로, herdr 플러그인은 `herdr plugin install`로 설치합니다.

## 스킬

하나만 설치하려면 아래 표의 이름을 `<skill>` 자리에 넣으세요.

<!-- skills:start -->
| 스킬 | 설명 |
|---|---|
| [`herdr-parallel-worktree`](skills/herdr-parallel-worktree/SKILL.md) | herdr 안에서 코딩 작업을 눈에 보이는 작업자에게 맡깁니다. 작업마다 git worktree와 `claude` 작업자를 하나씩 띄워, 사이드바에서 각각의 진행을 보고 직접 들어가 볼 수 있습니다. 작업자는 그 저장소의 스페이스 밑에 작업 이름의 workspace로 붙습니다. herdr에 그 저장소의 스페이스가 없으면 지금 스페이스의 탭으로 뜨고, 새 최상위 스페이스는 만들지 않습니다. PR 전에 직접 리뷰할 티켓 한 건에도, 여러 작업을 병렬로 돌릴 때에도 쓰며, herdr 플러그인이 만든 탭은 그대로 둡니다. 작업자 지시서는 바꿀 수 있는 템플릿으로 만들고, 설정은 기본값으로 바로 동작하고, 처음 실행할 때 바꿀 수 있는 설정을 안내합니다. 작업자를 띄운 뒤와 요청할 때마다 **정리 가능한 워커** 목록을 보여 줍니다. 지금 저장소에서 바로 정리할 수 있는 작업자마다 무엇을 하려고 띄웠는지, 브랜치, 마지막 활동, 작업이 어디까지 반영됐는지를 보여 주고, 빠진 작업자는 이유와 함께 알려 주며, 고른 것만 정리합니다. 브랜치는 남고, 정리한 작업자는 나중에 이름으로 다시 열 수 있으며, 대화 내용도 그대로 이어집니다. |
<!-- skills:end -->

### 설치

`install.sh`는 GitHub CLI에 `gh skill`이 있으면(2.90.0 이상) 그것을 쓰고, 없으면 `npx skills`로 설치합니다.

```bash
curl -fsSL https://raw.githubusercontent.com/nyjin/herdr-skills/main/install.sh | bash -s -- herdr-parallel-worktree

# 전부 설치
curl -fsSL https://raw.githubusercontent.com/nyjin/herdr-skills/main/install.sh | bash -s -- --all

# ~/.claude/skills 대신 현재 저장소의 .claude/skills 에 설치
curl -fsSL https://raw.githubusercontent.com/nyjin/herdr-skills/main/install.sh | bash -s -- --scope project herdr-parallel-worktree
```

도구를 직접 써도 됩니다.

```bash
# GitHub CLI 2.90.0 이상 (`gh --version` 으로 확인, 낮으면 `brew upgrade gh`)
gh skill preview nyjin/herdr-skills herdr-parallel-worktree
gh skill install nyjin/herdr-skills herdr-parallel-worktree --agent claude-code --scope user

# npx skills
npx skills add nyjin/herdr-skills -s herdr-parallel-worktree -a claude-code -g
```

`gh skill install`에는 항상 `--agent claude-code --scope user`를 붙이세요. 빼면 GitHub Copilot용으로 프로젝트 범위에 설치됩니다. 나중에 `gh skill update`로 갱신할 수 있습니다.

| 방법 | 받는 내용 |
|---|---|
| `gh skill install` | 가장 최근 태그 릴리스. 릴리스가 없으면 기본 브랜치 |
| `gh skill install ... --pin <tag>` | 특정 릴리스에 고정 (`gh skill update` 대상에서 빠짐) |
| `npx skills add` | 기본 브랜치 |

예전 버전은 Claude Code 플러그인(`herdr-skills@herdr-skills`)으로도 설치할 수 있었지만, 이제 그 플러그인은 없습니다. 플러그인으로 설치했다면 먼저 `/plugin uninstall herdr-skills@herdr-skills`와 `/plugin marketplace remove herdr-skills`로 지우고, 위 방법으로 스킬을 설치한 뒤 Claude에게 "herdr 훅 켜줘"라고 하세요.

### 필요한 것

- [herdr](https://herdr.dev): 스킬은 herdr 세션 안(`HERDR_ENV=1`)에서만 동작합니다
- `claude`(Claude Code), `git`, `jq`, `python3`

### 훅

`herdr-parallel-worktree`는 스킬 설명(description)을 일부러 짧게 둡니다. 설명은 herdr 밖의 세션까지 포함해 모든 Claude Code 세션에 들어가기 때문입니다. 대신 훅이 스킬이 제때 쓰이게 하고, 이 훅들은 herdr 안(`HERDR_ENV=1`)에서만 동작합니다.

- **SessionStart**: 세션이 시작할 때 자기 역할을 한 문단으로 알려 줍니다. 메인 세션은 오케스트레이터로서 작업을 넘길 때는 티켓 한 건이라도 지켜볼 수 있는 작업자로 띄우고, 다른 스킬이 "티켓마다 서브에이전트를 띄우라"고 해도 작업자로 띄웁니다. 작업자는 자기 이름과, worktree 밖의 일은 handoff로 돌려준다는 것을 듣습니다.
- **세션 자신의 worktree**: `EnterWorktree`는 이 세션 자체를 worktree로 옮기고 싶을 때를 위해 막지 않습니다. Claude Code가 평소대로 `.claude/worktrees/<name>`에 `worktree-<name>` 브랜치로 만들고, 그 직후 PostToolUse 훅이 그 worktree를 herdr 사이드바의 해당 저장소 스페이스 밑에 열고 라벨을 세션에 알려 줍니다. herdr에 그 저장소의 스페이스가 없으면 아무것도 열지 않고, 세션은 자기 탭에 그대로 있습니다. `ExitWorktree`로 지우면 훅이 그 workspace를 닫습니다. 브랜치 없이 읽기용으로 만드는 `git worktree add`(detached checkout)도 통과합니다. 메인 세션의 그 밖의 `git worktree add`는 같은 안내로 막습니다. 작업은 작업자에게 가고, 작업자의 worktree는 저장소 관례를 따릅니다. `claude --worktree`로 시작할 때 만든 worktree는 도구 호출을 거치지 않으므로 사이드바에 나타나지 않습니다.
- **PreToolUse**: 다른 에이전트에게 자기 worktree에서 일을 맡기는 것은 스킬을 거칩니다. 메인 세션의 worktree 격리 서브에이전트는 막고 스킬로 안내합니다. worktree를 만들려는 서브에이전트는 멈춰서 작업을 `HERDR-HANDOFF` 블록으로 돌려주고, 스킬이 띄운 워커는 직접 작업하라는 안내를 받습니다. `EnterWorktree`로 이미 있는 worktree에 들어가는 것은 막지 않습니다. 서브에이전트나 워커가 자기 worktree 밖의 파일을 고치려 해도 같은 방식으로 막고, 그곳의 주인이 누구인지 알려 줍니다.
- **PostToolUse**: 서브에이전트나 워커가 Bash 명령을 실행한 뒤, 그 명령이 다른 worktree의 경로를 언급했고 실행 중에 그곳이 실제로 바뀌었으면 멈추고 그 부분을 돌려주게 합니다. 읽기만 한 경우는 그대로 둡니다. 메인 세션이 서브에이전트를 띄우면, 돌아온 `HERDR-HANDOFF` 블록을 어떻게 처리할지 한 줄로 알려 줍니다.

모든 handoff에는 **주인(owner)**이 적혀 있고, 메인 세션이 주인에 따라 처리합니다. 그 worktree의 워커가 주인이면 그 워커에게 후속 작업으로 넘깁니다(필요하면 다시 열거나 재개합니다). 사용자의 main checkout이면 무엇이 바뀌었는지 알리고 묻습니다. 주인이 없으면 바로 새 워커를 띄우고 나서 알려 줍니다. 훅은 프롬프트 문구가 아니라 도구 호출과 그 결과를 보고 판단합니다. herdr 밖에서는 python을 띄우기 전에 끝나고, 일반 메인 세션에서는 편집과 Bash마다 도는 훅이 아무 일도 하기 전에 끝납니다.

훅은 `~/.claude/settings.json`을 고쳐야 등록되므로, Claude에게 "herdr 훅 켜줘"라고 하기 전에는 꺼져 있습니다(고치기 전에 백업을 남깁니다). 등록된 항목은 복사본이라, 스킬을 업데이트한 뒤에는 한 번 더 켜 달라고 해야 새로 생긴 훅 이벤트가 등록됩니다. 나중에 "herdr 훅 꺼줘"(또는 켜줘, 지워줘)라고 하면 바꿀 수 있습니다.

### 설정과 데이터

사용자별 설정은 스킬 폴더 밖에 두므로, 다시 설치하거나 업데이트해도 남습니다.

```
${HERDR_SKILLS_DATA_HOME:-~/.local/share/herdr-skills}/<skill>/
```

`herdr-parallel-worktree`는 이곳에 `config.json`(작업자 `claude` 옵션과 훅 스위치. 처음 실행할 때 기본값으로 만들어지며, 직접 고치거나 Claude에게 바꿔 달라고 하면 됩니다), `briefs/`(만들어진 작업자 지시서), `runs.json`(띄운 작업자와 그 한 줄 작업 요약, Claude 세션 ID를 기록하며, 정리 목록과 재개에 쓰임), 그리고 선택적으로 `brief-template.md`(내 지시서 템플릿)를 둡니다. 템플릿을 바꾸려면 Claude에게 "지시서 템플릿 바꿔줘"라고 하세요.

## herdr 플러그인

herdr 자체의 플러그인입니다. Claude Code가 아니라 `herdr plugin install`로 설치합니다.

지금은 이 저장소에 있는 플러그인이 없습니다. pane이 가리키는 파일이나 링크를 렌더링해 바로 옆 pane에서 보여 주는 [peek](https://github.com/nyjin/herdr-peek)은 자체 저장소로 옮겨 갔습니다. 설치 방법은 그 저장소의 README에 있습니다.

<!-- herdr-plugins:start -->
| 플러그인 | 설명 |
|---|---|
<!-- herdr-plugins:end -->

## 저장소 구성

| 경로 | 내용 |
|---|---|
| `skills/<name>/` | 스킬 하나: `SKILL.md`, `references/`, `assets/`, `scripts/`, 그리고 자기 `tests/` |
| `herdr-plugins/<name>/` | herdr 플러그인 하나: `herdr-plugin.toml`, 스크립트, `README.md` / `README.ko.md`, 그리고 자기 `tests/` |
| `docs/superpowers/` | 설계 문서(`specs/`)와 구현 계획(`plans/`) |
| `scripts/check.sh` | 저장소 검사 전부. 로컬과 CI에서 똑같이 돌립니다 |
| `scripts/release.sh` | `skills/`가 바뀌었을 때 CI에서 스킬 릴리스를 만듭니다 |
| `install.sh` | 스킬 개별 설치 |

## 기여하기

저장소의 글은 모두 영어로 씁니다. 한국어는 `README.ko.md` 파일과, 필요한 경우의 테스트(한국어 모델 응답을 잡는 패턴 등)에만 씁니다. `scripts/check.sh language`가 이를 확인합니다.

### 스킬 추가하기

1. `skills/<name>/SKILL.md`를 만듭니다. frontmatter의 `name`은 디렉터리 이름과 같아야 하고, 소문자·숫자·하이픈만 씁니다.
2. `README.md`와 `README.ko.md`의 스킬 표(`skills:start`와 `skills:end` 마커 사이)에 알파벳 순서로 한 줄씩 추가합니다.
3. `feat:` 커밋으로 올립니다. 머지하면 CI가 릴리스를 만들어 `gh skill` 사용자에게 전달합니다([검사와 릴리스](#검사와-릴리스) 참고).

### herdr 플러그인 추가하기

1. `herdr-plugins/<name>/`에 `herdr-plugin.toml`(버전은 여기에 둡니다), `README.md`, `README.ko.md`를 만듭니다.
2. 두 README의 herdr 플러그인 표(`herdr-plugins:start`와 `herdr-plugins:end` 마커 사이)에 알파벳 순서로 한 줄씩 추가합니다.

### 검사와 릴리스

CI(`.github/workflows/skills-check.yaml`)는 pull request와 `main` push마다 `scripts/check.sh`를 돌립니다. `gh skill publish --dry-run`으로 스킬 스펙을 검증하고, `name`과 디렉터리 이름이 같은지, 두 README의 표가 `skills/`·`herdr-plugins/`와 맞는지, 언어 규칙을 지키는지 확인하고, 릴리스 버전 결정을 테스트하고, 스모크 테스트와 단위 테스트를 돌립니다.

`main` push가 검사를 통과하면 CI가 릴리스를 만들어 `gh skill` 사용자에게 변경을 전달합니다. `scripts/release.sh`가 `gh skill publish --tag v<next>`를 실행합니다. 릴리스 태그가 곧 스킬의 버전입니다. 마지막 `v<major>.<minor>.<patch>` 태그 이후 커밋 가운데 `skills/`를 바꾼 커밋만 세고, 그 커밋들의 [Conventional Commits](https://www.conventionalcommits.org/) 타입으로 올릴 자리를 정합니다. 여러 개면 가장 큰 쪽을 따릅니다.

| `skills/`를 바꾼 커밋 | 릴리스 |
|---|---|
| 호환을 깨는 변경: `type!:` 또는 `BREAKING CHANGE:` 꼬리말 | major |
| `feat` | minor |
| `fix` 또는 `perf` | patch |
| 그 밖의 타입뿐(`docs`, `test`, `refactor`, `chore` 등) | 없음 |

`skills/` 밖의 커밋으로는 릴리스가 나가지 않습니다. herdr 플러그인의 버전은 자기 `herdr-plugin.toml`에 있습니다. `gh skill publish`는 브랜치 끝 커밋에 태그를 달기 때문에, 릴리스 job이 돌기 전에 `main`이 더 나아갔다면 그 실행은 아무것도 릴리스하지 않고 더 새로운 push의 실행이 릴리스합니다. `scripts/release.sh --dry-run`은 지금 체크아웃이라면 무엇을 릴리스할지 출력만 하고, 릴리스는 만들지 않습니다.

## 라이선스

[MIT](LICENSE)
