# 워커 배치: 대상 레포의 스페이스 밑, 없으면 지금 스페이스의 탭 — 설계

- 날짜: 2026-11-10
- 기준: `2f5abc0` (0.8.0)
- 측정 환경: herdr 0.9.0, Claude Code 2.1.319
- 범위: `herdr-parallel-worktree` 스킬 본문·참조 문서, `scripts/place.py`(새), `scripts/hooks/spaces.py`(새), `runs.py`, `finalize-brief.py`, `worker-pane.py`(설명만), `route.py`, 테스트, README

## 1. 무엇이 문제였나

2026-11-10 새벽, `~/src/skills`에서 작업하던 오케스트레이터 세션은 kb-skills 스페이스(w22)의 탭(`good-skills`)에 있었다. cwd만 `~/src/skills`였다. 이 세션이 띄운 것들이 사용자가 기대한 자리에 붙지 않았다.

| 무엇 | 어떻게 띄웠나 | 붙은 자리 | 사용자 기대 |
|---|---|---|---|
| `decided-result` 워커 (worktree) | 스킬 1단계. 지금 스페이스(kb-skills)가 대상 레포(skills)와 달라 `--cwd ~/src/skills` | herdr가 **skills 스페이스(w3S)를 새로 만들고** 그 밑 | skills 스페이스 밑. 없으면 새 최상위 스페이스를 만들지 말 것 |
| `t13-main`, `t13-eval` (worktree 없음) | 스킬 밖에서 `herdr tab create --workspace "$HERDR_WORKSPACE_ID"` | 세션이 있던 kb-skills | 같은 규칙 |

t13 탭은 `HERDR_PW_WORKER` 없이 떴다. 그래서 훅이 이 세션들을 메인 세션으로 보고 오케스트레이터 역할 문단과 첫 작업 분배 정지를 걸었다. 오케스트레이터는 이것을 피하려고 브리프에 "herdr 안내보다 이 지시가 우선한다"를 적고, 훅의 분배 기록 파일을 손으로 만들었다. worktree 없이 보이는 세션을 띄우는 길이 스킬에 없어서 생긴 즉석 처리다.

사용자 결정(2026-11-10): "스페이스가 다르면 herdr로 찾아서 있는지 보고 그 밑에 만들고, 정 없으면 탭으로". worktree 없는 세션도 같은 규칙을 따른다.

## 2. 측정한 사실

임시 저장소 둘(repoA, repoB)과 실험용 스페이스로 확인했다. 만든 것은 모두 지웠다.

| # | 확인한 것 | 결과 | 설계에 미치는 영향 |
|---|---|---|---|
| P1 | `herdr workspace create --cwd <레포 루트>` | 스페이스는 생기지만 `worktree`(repo_key)가 비어 있다. 레포에 묶이지 않는다 | repo_key만으로는 "그 레포의 스페이스"를 다 찾지 못한다 |
| P2 | P1의 스페이스가 있을 때 `worktree create --cwd <레포 루트>` | 새 스페이스를 만들지 않고 P1의 스페이스를 다시 쓰고 묶는다. 새 worktree는 그 밑에 생긴다 | herdr도 "그 레포의 스페이스"를 찾는다 |
| P3 | `herdr worktree list --cwd <레포 루트>` | `result.source.source_workspace_id`가 herdr가 그 레포의 원본 체크아웃에 연결한 스페이스다. 묶이지 않은 P1 스페이스도 나온다. 없으면 이 키가 없다(kurly-fulfillment-auth: 링크된 worktree 스페이스만 있음) | **찾기는 이 값으로 한다.** herdr 자신의 판정이라 우리가 따로 흉내 낼 필요가 없다 |
| P4 | 묶이지 않은 스페이스에 `worktree create --workspace <id>` | 동작하고, 그 스페이스를 레포에 묶는다 | 찾은 스페이스에는 늘 `--workspace`로 붙인다 |
| P5 | `--path` 없이 `feat/x-y` 브랜치 | `~/.herdr/worktrees/<repo_name>/feat-x-y` (`/` → `-`) | 탭 배치에서 herdr 기본 경로를 그대로 따른다 |
| P6 | `--cwd` 상황에서 그 레포의 스페이스가 없을 때 (w3S) | 원본 레포용 스페이스를 새로 만든다 (2026-10-13 설계 G7과 같음) | 이것이 사용자가 바라지 않는 동작이다 |
| P7 | `herdr tab get <tab>` / `herdr pane get <pane>` | 탭에 `agent_status`, `focused`가 있다. pane에 `tab_id`가 있다. 닫힌 pane은 `pane_not_found` | 탭 워커의 정리 판정은 워크스페이스 대신 탭으로 한다 |

## 3. 규칙

배치는 대상 레포 `ROOT`와 이 세션의 스페이스 `CUR`(`HERDR_WORKSPACE_ID`)로 정한다.

1. `CUR`이 `ROOT`의 레포에 묶여 있으면(repo_key가 같으면) → `CUR` 밑 (지금과 같음).
2. 아니면 `herdr worktree list --cwd ROOT`의 `source_workspace_id`가 있으면 → 그 스페이스 밑(`--workspace`). 이것이 `CUR`이면 1과 같다.
3. 둘 다 아니면 → 새 스페이스를 만들지 않는다. **`CUR`의 탭**으로 띄운다.

| 배치 | worktree를 만드는 쪽 | 워커가 도는 곳 | 사이드바 |
|---|---|---|---|
| `workspace` (1, 2) | `herdr worktree create --workspace <스페이스>` | 새 worktree 스페이스 안의 `<name>` 탭 (0.7.0과 같음) | 그 레포 스페이스 밑의 서브 스페이스 |
| `tab` (3) | `git -C ROOT worktree add` | `CUR` 안의 `<name>` 탭, cwd는 그 worktree | 지금 스페이스의 탭 |

worktree 없는 세션은 worktree를 만들지 않을 뿐 같은 규칙으로 자리를 정한다. 그 세션이 일하는 디렉터리가 어떤 레포 안이면 그 레포가 `ROOT`다. 레포 밖이면 `CUR`이다.

## 4. 구성

### `scripts/hooks/spaces.py` (새)

`repo_space(root, current, herdr)` 하나. 위 규칙 1~2를 판정해 `(스페이스 id 또는 None, 이유)`를 돌려준다. `place.py`와 `route.py`가 같이 쓴다. 판정이 한 곳에만 있어야 둘이 어긋나지 않는다.

### `scripts/place.py` (새)

배치 판정과 worktree 생성을 맡는다. 문서 세 곳(SKILL.md 1단계, resume.md, deliver.md)과 dispatch.md가 같은 명령을 부른다.

- `place.py where --dir DIR`: 배치만 판정한다. worktree 없는 세션이 쓴다. `DIR`이 레포 밖이면 `tab`(CUR).
- `place.py worktree --root ROOT --name N --branch B (--base SHA | --existing) [--path P] [--trust-repository]`: 배치를 정하고 worktree를 만든다. `workspace`면 `herdr worktree create --workspace`, `tab`이면 `git worktree add`. `--existing`은 재개용이다(브랜치를 만들지 않고 꺼낸다). 만들기 직전 시각을 `since`로 돌려준다(플러그인 대기용).
- `place.py reopen --root ROOT --name N --worktree WT`: worktree는 남았는데 자리(스페이스나 탭)가 사라졌을 때 쓴다. `workspace`면 `herdr worktree open --workspace`, `tab`이면 여는 것 없이 자리만 돌려준다.
- 출력(JSON): `placement`(`workspace`|`tab`), `workspace`(워커 탭을 만들 스페이스), `worktree`, `since`, `why`.
- 아무것도 덮어쓰지 않는다. 경로가 차 있거나 브랜치가 있거나 herdr·git이 실패하면, 그 오류를 stderr에 내고 exit 1.
- `--path`가 상대 경로면 `ROOT` 기준으로 푼다. `tab`이고 `--path`가 없으면 herdr 기본 경로(P5)를 쓴다.

훅은 메인 세션의 `git worktree add`(브랜치)를 막는다. 탭 배치의 worktree는 이 스크립트가 만든다. 훅이 거부 메시지에서 "스킬을 불러 워커를 띄워라, 스킬이 worktree를 만든다"고 이미 말하고 있으므로 같은 길이다. 훅은 명령 텍스트로 판정하므로 스크립트 안의 git 호출은 보지 않는다. 훅을 바꿀 필요가 없다.

### `runs.py`

- 기록에 `placement`를 더한다(`add`, `mark-open`, `relocate`의 `--placement`). 없는 옛 기록은 `workspace`로 읽는다.
- 탭 워커의 `workspace`는 탭이 있는 스페이스(`CUR`)다.
- 정리 판정(`scan`)에서 탭 워커는 스페이스가 아니라 **탭**을 본다. `pane get`으로 탭을 찾고 `tab get`으로 `agent_status`와 `focused`를 읽는다. pane이 없으면 탭이 닫힌 것이다.
- 탭 워커의 `remove_command`는 `git -C <root> worktree remove <wt> && herdr tab close <tab>`이다. 탭이 이미 닫혔으면 앞부분만 쓴다. worktree를 먼저 지운다. 커밋 안 된 변경이 있으면 git이 거부하므로 탭도 남는다. **`CUR` 스페이스는 절대 닫지 않는다.**

### `finalize-brief.py`

`--workdir PATH`: worktree 없는 세션의 Environment 줄(`- Working directory: …`)을 쓴다. 닫는 문단도 바꾼다. "이 브랜치에 커밋하라" 대신 "커밋하지 말고, git이 추적하는 파일은 바꾸지 마라"이고, 마지막 문장 "Do not push or open a pull request."는 그대로 둔다. 3단계의 `wait-output`이 그 문장을 기다리기 때문이다. 다시 돌려도 Environment 줄로 알아보고 같은 문단을 쓴다.

### `route.py`

- **R8 (EnterWorktree 등록)**: `spaces.repo_space`로 같은 규칙을 쓴다. 1, 2면 그 스페이스에 `worktree open --workspace`. 3이면 등록하지 않는다. 이 세션은 이미 자기 탭에 있고, 새 최상위 스페이스를 만들지 않는다. 지금까지는 `--cwd`로 열어 P6처럼 새 스페이스가 생길 수 있었다.
- **워커 역할 문단**: "Do not write where another session works (… the main checkout …)"는 worktree 없이 어떤 레포의 원본 체크아웃 안(git이 무시하는 작업 폴더)에서 일하는 워커와 어긋난다. "the main checkout"을 "a main checkout outside the working directory your brief gives you"로 바꾼다. 훅의 판정(자기 home 안은 허용)은 이미 그렇게 동작한다.

### 스킬 문서 (drift 없이)

| 문서 | 바뀌는 것 |
|---|---|
| SKILL.md 첫 문단 | "각 작업마다 worktree 스페이스" → 배치 규칙 한 문장 |
| SKILL.md 0단계 | Name이 "스페이스 또는 탭 라벨"임 |
| SKILL.md 1단계 | `LOC`/`WS_KEY` 판정을 `place.py worktree` 한 줄로. 배치 규칙과 이유 |
| SKILL.md 3단계 | `runs.py add --placement`. 탭 설명에 탭 배치 |
| SKILL.md 4단계 보고 | 어디에 붙었는지(스페이스 밑 / 지금 스페이스의 탭과 그 이유) |
| SKILL.md 새 절 "A worker without a worktree" | 언제, `place.py where`, `worker-pane.py`(`HERDR_PW_WORKER`), `finalize-brief.py --workdir`, 기록하지 않음, 후속 전달은 이름으로 |
| SKILL.md Hooks | EnterWorktree 등록이 같은 규칙을 따름. `place.py`가 탭 워커의 worktree를 만듦 |
| resume.md | 2단계를 `place.py worktree --existing`으로. 닫힌 자리의 재개를 `place.py reopen`으로. `mark-open`/`relocate --placement`. 탭 워커의 "자리가 있다"는 pane이 있다는 뜻 |
| deliver.md | 3단계 표와 다시 열기를 `place.py reopen`으로. worktree 없는 워커는 기록이 없으니 이름으로 전달 |
| cleanup.md | 탭 워커는 탭을 닫음. 손으로 되살리는 명령을 배치와 무관한 형태로 |
| dispatch.md | "계획마다 스페이스 하나"를 "1단계가 정한 자리"로. 탭 배치면 `<plan>-impl`·`<plan>-rev`가 지금 스페이스의 탭 |
| brief-filling.md | `--workdir` |
| README.md / README.ko.md | 스킬 한 줄 설명과 EnterWorktree 문단 |

drift를 막는 장치:
- 배치 판정은 `spaces.py` 한 곳에만 둔다.
- 문서는 판정을 다시 설명하지 않고 `place.py`를 부른다.
- `test_skill_text.py`에 검사를 더한다. 문서가 `place.py`를 부르는지 본다. 새 스페이스를 만들 수 있는 옛 명령(`worktree create --cwd`, `worktree open --cwd`)이 문서에 남지 않았는지도 본다.

## 5. 하지 않는 것

- 이미 떠 있는 워커를 옮기지 않는다. 배치는 만들 때와 재개할 때만 정한다.
- 스페이스를 새로 만들지 않는다. 사용자가 원하면 자기가 만들면 된다. 그 뒤로 띄우는 워커는 규칙 2로 그 밑에 붙는다.
- 탭 배치의 worktree를 herdr에 등록하지 않는다(`worktree open`은 스페이스를 만든다).
- worktree 없는 세션을 runs.json에 기록하지 않는다. 지울 worktree도, 되살릴 worktree도 없다.
- 훅의 판정 방식(명령 텍스트, 도구 호출)은 바꾸지 않는다.

## 6. 내 판단으로 정한 것

- 찾기는 herdr의 `source_workspace_id`(P3)로 한다. 우리가 스페이스 cwd를 따로 비교하지 않는다.
- 링크된 worktree 스페이스만 있고 원본 스페이스가 없는 레포(kurly-fulfillment-auth)는 "스페이스 없음"으로 본다. 붙을 "밑"이 없다.
- EnterWorktree 등록(R8)도 같은 규칙으로 바꾼다. 같은 불만(새 최상위 스페이스)이 같은 원인에서 나오고, 규칙이 둘이면 문서가 어긋난다.
- 버전은 0.9.0으로 올린다(사이드바에 보이는 동작이 바뀐다).
- **worktree 없는 워커를 언제 쓰나** (빌더 검토 질문 1): 저장소의 코딩 작업에는 늘 worktree가 있다. worktree 없는 워커는 worktree가 있으면 안 되거나 필요 없는 일에만 쓴다. 사용자나 저장소 규칙이 worktree·브랜치를 막는 경우, 또는 어떤 저장소도 바꾸지 않는 일(평가, 작업 폴더에 결과를 쓰는 조사·리뷰)이다. `ROLE_MAIN`과 스킬 설명(frontmatter)은 그대로 둔다. 모든 세션이 그 문장의 비용을 내므로, 예외는 SKILL.md 본문에만 둔다.
- **같은 체크아웃을 여러 세션이 고칠 수 있나** (질문 2): 아니다. worktree 없는 워커는 git이 추적하는 파일을 바꾸지 않고 커밋하지 않는다. 쓰기는 자기 작업 디렉터리(git 밖이거나 git이 무시하는 곳)에서만 한다. 이 규칙은 SKILL.md 절, `--workdir` 닫는 문단, 워커 역할 문단에 적는다. 훅 강제는 더하지 않는다(자연스러움과 절약).
- **후속 전달** (질문 3): 기록이 없으니 이름으로 찾는다(`herdr agent get <name>`). 후속 파일도 `--workdir`로 마무리한다. 이름은 기록되었거나 떠 있는 워커와 겹치면 안 된다. 훅이 브리프에서 바깥 경로를 이름으로 읽기 때문이다.
- 다른 세션이 이 스킬을 지금 쓰고 있다(설치본이 main 체크아웃을 가리킴). 그래서 브랜치에서 구현·검증만 하고, main 머지는 사용자에게 맡긴다.

## 7. 검증

- 단위: `spaces.repo_space`(세 경우와 herdr 실패), `place.py` 세 하위 명령(가짜 herdr, 진짜 git), `runs.py` 탭 판정과 `remove_command`, `finalize-brief.py --workdir`, `route.py` R8의 세 경우, 문서 drift 검사.
- 실환경(herdr 0.9.0, 임시 저장소): 세 배치 각각에서 `place.py worktree` → `worker-pane.py`까지 돌린다. 사이드바 배치와 탭 위치는 `workspace list`와 `tab list`로 확인한다. claude는 띄우지 않는다. 그 뒤 `runs.py scan`의 `remove_command`로 정리한다.
- `scripts/check.sh` 전체.
