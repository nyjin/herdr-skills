# herdr-skills

[English](README.md) | **한국어**

터미널 안에서 돌아가는 에이전트 멀티플렉서 [herdr](https://herdr.dev)를 위한 Claude Code 스킬(Agent Skills) 모음입니다. 여러 코딩 에이전트를 git worktree로 나눠 병렬로 돌립니다. 보이지 않는 서브에이전트와 달리, 각 Claude Code 작업자가 일하는 모습을 herdr 사이드바에서 직접 볼 수 있습니다. Claude Code 플러그인으로 전부 설치하거나, `gh skill`·`npx skills`로 필요한 스킬만 골라 설치하세요.

## 수록 스킬

하나만 설치하려면 아래 표의 이름을 `<skill>` 자리에 넣으세요.

<!-- skills:start -->
| 스킬 | 설명 |
|---|---|
| [`herdr-parallel-worktree`](skills/herdr-parallel-worktree/SKILL.md) | herdr 안에서 여러 작업을 병렬로 진행합니다. 작업마다 git worktree workspace와 눈에 보이는 `claude` 작업자를 하나씩 띄워, 사이드바에서 각각의 진행을 볼 수 있습니다. 작업자 지시서는 바꿀 수 있는 템플릿으로 만들고, 설정은 기본값으로 바로 동작하고, 처음 실행할 때 바꿀 수 있는 설정을 안내합니다. 끝난 작업자는 정리했다가 나중에 이름으로 다시 열 수 있으며, 대화 내용도 그대로 이어집니다. |
<!-- skills:end -->

## 설치

아래 두 방법 중 **하나만** 쓰세요. 플러그인으로 설치한 스킬은 `/herdr-skills:<skill>`, 개별로 설치한 스킬은 `/<skill>` 이름으로 등록되고 서로 덮어쓰지 않습니다. 그래서 같은 스킬을 양쪽으로 설치하면 두 벌이 남아 두 번 트리거됩니다. 개별 설치로 옮기려면 먼저 `/plugin uninstall herdr-skills@herdr-skills`로 플러그인을 지우세요.

### 전체 설치 — Claude Code 플러그인

```
/plugin marketplace add nyjin/herdr-skills
/plugin install herdr-skills@herdr-skills
```

설치한 뒤 Claude Code를 다시 시작하세요.

### 개별 설치

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

### 설치 방법별로 받는 내용

| 방법 | 받는 내용 |
|---|---|
| `gh skill install` | 가장 최근 태그 릴리스. 릴리스가 없으면 기본 브랜치 |
| `gh skill install ... --pin <tag>` | 특정 릴리스에 고정 (`gh skill update` 대상에서 빠짐) |
| `npx skills add` | 기본 브랜치 |
| Claude Code 플러그인 | 마켓플레이스의 현재 플러그인 버전 |

## 필요한 것

- [herdr](https://herdr.dev) — 스킬은 herdr 세션 안(`HERDR_ENV=1`)에서만 동작합니다
- `claude`(Claude Code), `git`, `jq`, `python3`

## 훅

`herdr-parallel-worktree`는 스킬 설명(description)을 일부러 짧게 둡니다. 설명은 herdr 밖의 세션까지 포함해 모든 Claude Code 세션에 들어가기 때문입니다. 대신 훅이 스킬이 제때 쓰이게 하고, 이 훅들은 herdr 안(`HERDR_ENV=1`)에서만 동작합니다.

- **PreToolUse**: 스킬 밖에서 worktree를 만들려 하면(`git worktree add`, `EnterWorktree`로 새로 만들기, worktree 격리 서브에이전트) 막습니다. 안내는 누가 시도했느냐에 따라 다릅니다. 메인 세션은 스킬로 안내되고, 서브에이전트는 멈춰서 작업을 `HERDR-HANDOFF` 블록으로 돌려줍니다. 스킬이 띄운 워커는 직접 작업하라는 안내를 받습니다. `EnterWorktree`로 이미 있는 worktree에 들어가는 것은 막지 않습니다. 서브에이전트나 워커가 자기 worktree 밖의 파일을 고치려 해도 같은 방식으로 막고, 그곳의 주인이 누구인지 알려 줍니다.
- **PostToolUse**: 서브에이전트나 워커가 Bash 명령을 실행한 뒤, 그 명령이 다른 worktree의 경로를 언급했고 실행 중에 그곳이 실제로 바뀌었으면 멈추고 그 부분을 돌려주게 합니다. 읽기만 한 경우는 그대로 둡니다. 메인 세션이 서브에이전트를 띄우면, 돌아온 `HERDR-HANDOFF` 블록을 어떻게 처리할지 한 줄로 알려 줍니다.

모든 handoff에는 **주인(owner)**이 적혀 있고, 메인 세션이 주인에 따라 처리합니다. 그 worktree의 워커가 주인이면 그 워커에게 후속 작업으로 넘깁니다(필요하면 다시 열거나 재개합니다). 사용자의 main checkout이면 무엇이 바뀌었는지 알리고 묻습니다. 주인이 없으면 한 번 확인을 받은 뒤 새 워커를 띄웁니다. 훅은 프롬프트 문구가 아니라 도구 호출과 그 결과를 보고 판단합니다. herdr 밖에서는 python을 띄우기 전에 끝나고, 일반 메인 세션에서는 편집과 Bash마다 도는 훅이 아무 일도 하기 전에 끝납니다.

플러그인은 `hooks/hooks.json`에 이 훅을 담고 있어 기본으로 켜져 있습니다. 스킬만 따로 설치하면 `~/.claude/settings.json`을 고쳐야 하므로, Claude에게 "herdr 훅 켜줘"라고 하기 전에는 등록하지 않습니다(고치기 전에 백업을 남깁니다). 어느 쪽이든 나중에 "herdr 훅 꺼줘"(또는 켜줘, 지워줘)라고 하면 바꿀 수 있습니다.

## 설정과 데이터

사용자별 설정은 스킬 폴더 밖에 두므로, 다시 설치하거나 업데이트해도 남습니다.

```
${HERDR_SKILLS_DATA_HOME:-~/.local/share/herdr-skills}/<skill>/
```

`herdr-parallel-worktree`는 이곳에 `config.json`(작업자 `claude` 옵션과 훅 스위치. 처음 실행할 때 기본값으로 만들어지며, 직접 고치거나 Claude에게 바꿔 달라고 하면 됩니다), `briefs/`(만들어진 작업자 지시서), `runs.json`(띄운 작업자와 그 Claude 세션 ID를 기록하며, 정리와 재개에 쓰임), 그리고 선택적으로 `brief-template.md`(내 지시서 템플릿)를 둡니다. 템플릿을 바꾸려면 Claude에게 "지시서 템플릿 바꿔줘"라고 하세요.

## 스킬 추가하기

1. `skills/<name>/SKILL.md`를 만듭니다. frontmatter의 `name`은 디렉터리 이름과 같아야 하고, 소문자·숫자·하이픈만 씁니다.
2. `README.md`와 `README.ko.md`의 스킬 표(`skills:start`와 `skills:end` 마커 사이)에 알파벳 순서로 한 줄씩 추가합니다.
3. `.claude-plugin/plugin.json`의 `version`을 올립니다.
4. 머지한 뒤에는 `gh skill publish --tag v<version>`으로 릴리스를 만듭니다. 그래야 `gh skill` 사용자에게 변경이 전달됩니다.

CI(`.github/workflows/skills-check.yaml`)는 `gh skill publish --dry-run`으로 스킬 스펙을 검증합니다. 그 밖에 `name`과 디렉터리 이름이 같은지, 두 README의 스킬 표가 `skills/`와 맞는지, 플러그인 매니페스트가 올바른지도 확인합니다.

## 라이선스

[MIT](LICENSE)
