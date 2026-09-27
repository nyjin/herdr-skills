# herdr-skills

[English](README.md) | **한국어**

[herdr](https://herdr.dev)(터미널 안에서 돌아가는 에이전트 멀티플렉서)용 Claude Code 스킬(Agent Skills) 모음입니다. 여러 코딩 에이전트를 git worktree로 나눠 병렬로 돌리고, 보이지 않는 서브에이전트 대신 각 Claude Code 작업자의 진행을 herdr 사이드바에서 직접 봅니다. Claude Code 플러그인으로 전부 설치하거나, `gh skill`·`npx skills`로 필요한 스킬만 골라 설치할 수 있습니다.

## 수록 스킬

하나만 설치하려면 아래 표의 이름을 `<skill>` 자리에 넣으세요.

<!-- skills:start -->
| 스킬 | 설명 |
|---|---|
| [`herdr-parallel-worktree`](skills/herdr-parallel-worktree/SKILL.md) | herdr 안에서 여러 작업을 병렬로 진행합니다. 작업마다 git worktree workspace와 눈에 보이는 `claude` 작업자를 하나씩 띄워, 사이드바에서 각각의 진행을 볼 수 있습니다. 작업자 지시서는 바꿀 수 있는 템플릿으로 만들고, 작업자 권한 옵션은 처음 쓸 때 묻습니다. |
<!-- skills:end -->

## 설치

아래 두 방법 중 **하나만** 쓰세요. **둘을 겹쳐 쓰지 마세요.** 플러그인 스킬은 `/herdr-skills:<skill>`, 개별 설치본은 `/<skill>`로 붙는데, 한쪽이 다른 쪽을 덮지 않습니다. 같은 스킬을 양쪽으로 설치하면 두 벌이 남아 두 번 트리거됩니다. 개별 설치로 옮기려면 먼저 `/plugin uninstall herdr-skills@herdr-skills`로 플러그인을 지우세요.

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

## 설정과 데이터

사용자별 설정은 스킬 폴더 밖에 두므로, 다시 설치하거나 업데이트해도 남습니다.

```
${HERDR_SKILLS_DATA_HOME:-~/.local/share/herdr-skills}/<skill>/
```

`herdr-parallel-worktree`는 이곳에 `config.json`(작업자 `claude` 옵션), `briefs/`(만들어진 작업자 지시서), 그리고 선택적으로 `brief-template.md`(내 지시서 템플릿)를 둡니다. 템플릿을 바꾸려면 Claude에게 "지시서 템플릿 바꿔줘"라고 하세요.

## 스킬 추가하기

1. `skills/<name>/SKILL.md`를 만듭니다. frontmatter의 `name`은 디렉터리 이름과 같아야 하고, 소문자·숫자·하이픈만 씁니다.
2. `README.md`와 `README.ko.md`의 스킬 표(`skills:start`와 `skills:end` 마커 사이)에 알파벳 순서로 한 줄씩 추가합니다.
3. `.claude-plugin/plugin.json`의 `version`을 올립니다.
4. 머지한 뒤 릴리스를 만들어야 `gh skill` 사용자에게 변경이 전달됩니다: `gh skill publish --tag v<version>`

CI(`.github/workflows/skills-check.yaml`)는 `gh skill publish --dry-run`으로 스킬 스펙을 검증하고, `name`과 디렉터리 이름이 같은지, 두 README의 스킬 표가 `skills/`와 맞는지, 플러그인 매니페스트가 올바른지 확인합니다.

## 라이선스

[MIT](LICENSE)
