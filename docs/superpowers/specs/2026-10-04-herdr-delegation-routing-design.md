# herdr-parallel-worktree: 위임 경로와 상관없이 herdr 워커로 이어지게 — 설계

- 상태: 초안 (승인 대기)
- 날짜: 2026-10-04
- 기준: `494a0d7` + 커밋되지 않은 작업 트리 변경(`SKILL.md`, `config.schema.json`, `plugin.json`, README 두 개). 스킬은 심볼릭 링크로 설치되어 있어 실제로 쓰이는 것이 이 작업 트리 상태다.
- 측정 환경: Claude Code 2.1.289, `claude -p --settings <임시 설정>`으로 훅 입력 JSON을 기록함. 사용자 설정은 건드리지 않았다.
- 문서 위치: 레포에 문서 관례가 없어 `docs/superpowers/specs/`를 제안한다.

## 1. 목표

herdr 안에서 worktree가 필요한 작업은 **어느 경로로 요청되든** 메인 세션이 이 스킬로 이어받아 herdr 워커(사이드바에 보이는 pane)로 실행한다. 메인이 직접 하든, 서브에이전트에 맡기든 결과가 같아야 한다.

성공 기준:
1. 서브에이전트가 worktree를 만들거나 다른 worktree에 쓰려 하면 차단된다. 이때 서브에이전트는 정해진 형식의 작업 명세(HERDR-HANDOFF)를 반환하고 멈춘다.
2. 메인 세션은 HANDOFF를 받으면 사용자에게 `!` 명령이나 훅 끄기를 안내하지 않는다. 스킬로 이어받아 §0의 확인 1회를 거쳐 워커를 띄운다.
3. 워커 안에서는 워커나 worktree를 새로 만들 수 없다(중첩 오케스트레이션 방지).
4. herdr 밖에서는 토큰 비용이 0이다.
5. 판정 로직은 단위 테스트로 고정된다.

## 2. 원칙: 프롬프트가 아니라 행위를 본다

판정은 **결정적인 도구 호출과 그 필드**로만 한다. 요청 프롬프트나 Agent 프롬프트의 문구는 보지 않는다. 문구 해석은 오탐과 누락이 모두 생기지만, 행위는 훅 입력 JSON으로 확정된다.

결과적으로 worktree 관련 작업이 실제로 시작되는 순간에 막는다. 서브에이전트가 일을 조금 시작했다가 멈추는 비용은 감수한다. 발단 사건에서는 서브에이전트의 첫 행동이 `git worktree add`였으므로 작업 전에 막혔을 것이다.

## 3. 측정으로 확인한 사실

| # | 사실 | 설계에 미치는 영향 |
|---|---|---|
| F1 | PreToolUse 입력: 메인은 `session_id, cwd, permission_mode, prompt_id, tool_name, tool_input, tool_use_id, transcript_path, hook_event_name`. 서브에이전트 안의 호출에는 **`agent_id`, `agent_type`이 추가된다** | 주체 구분은 `agent_id` 유무로 확정 |
| F2 | `Agent`의 `tool_input`은 `description, prompt, subagent_type`(+ 지정 시 `isolation`). 서브에이전트가 어디서 일할지 알려 주는 필드는 없다 | Agent 호출 시점에는 `isolation`만 판정 |
| F3 | 서브에이전트가 `cd <다른 디렉터리>`를 한 뒤에도 훅의 `cwd`는 세션 시작 디렉터리 그대로였다 (측정은 프로젝트 밖 디렉터리 기준) | 대상 경로는 `file_path`와 명령 인자에서 얻는다. `cwd`는 "세션의 집"으로만 쓴다 |
| F4 | 이 버전의 `Agent`는 기본이 비동기다. PostToolUse(Agent)는 띄운 직후 `status: "async_launched"`로 발동하고, 결과 텍스트는 없다 | 결과 시점에 HANDOFF를 감지하는 방식은 불가능 |
| F5 | PostToolUse(Agent)의 `additionalContext`는 **메인에 도달한다** | 띄우는 시점에 메인에 미리 지시를 넣을 수 있다 (§5 R6) |
| F6 | SubagentStop에는 `last_assistant_message`가 있다. 하지만 `additionalContext`는 **서브에이전트에** 주입되고, 서브에이전트가 9회 반복 실행되었다(`stop_hook_active: true`) | SubagentStop에서는 아무것도 출력하지 않는다 |
| F7 | `herdr agent start`에는 환경변수 옵션이 없다. pane이 interactive shell prompt 상태여야 하고, 그 셸에서 agent를 실행한다 | 워커 표식은 `agent start` 전에 pane 셸에서 `export` (미검증, §9 V1) |

## 4. 가설 W1~W4 판정

- **W1 (서브에이전트 맥락 없음): 맞다.** `route.py`에 `agent_id` 분기가 없다. 그래서 차단당한 서브에이전트에게도 "Load that skill and follow it"이라고 하는데, 스킬은 서브에이전트가 오케스트레이터를 맡는 것을 금지한다.
- **W2 (예외 조항 오발동): 맞다.** "If the user explicitly asked for a plain git worktree"를 서브에이전트가 판단할 근거가 없다. 서브에이전트에게는 오케스트레이터 프롬프트가 곧 "사용자"다.
- **W3 (메인 쪽 안내 없음): 맞다.** SKILL.md에 서브에이전트 보고를 받았을 때의 절이 없다. Hooks 절의 "If a hook blocks something the user explicitly asked for … offer `! <command>`"가 오히려 이번 오답으로 이끌었다.
- **W4 (`wait-output` 5초 timeout): 미검증.** 시간 초과가 실제로 있었다는 기록만 있고 원인(브리프 길이, 셸 속도, `--match` 문자열과 출력의 불일치)은 재현하지 않았다. 이번 설계에서는 실패해도 진행하도록 처리만 바꾸고, 원인은 V4에서 확인한다.

## 5. 설계

### 5.1 주체 구분

| 주체 | 판별 |
|---|---|
| `main` | `HERDR_PW_WORKER` 없음, `agent_id` 없음 |
| `sub` | `HERDR_PW_WORKER` 없음, `agent_id` 있음 |
| `worker` | `HERDR_PW_WORKER` 있음, `agent_id` 없음 |
| `worker-sub` | `HERDR_PW_WORKER` 있음, `agent_id` 있음 (환경변수는 상속됨) |

`HERDR_PW_WORKER=<워커 이름>`은 §3에서 `agent start` 전에 pane 셸에 export한다. 재개(`references/resume.md`)할 때도 마찬가지다.

### 5.2 "다른 worktree" 판정

경로 `p`(파일이면 가장 가까운 존재하는 상위 디렉터리)에 대해 `git -C <dir> rev-parse --path-format=absolute --git-dir --git-common-dir --show-toplevel`을 1회 실행한다.

- `git-dir == git-common-dir`이면 linked worktree가 아니다 → **통과**
- git 저장소가 아니거나 오류·시간 초과(2초)이면 → **통과** (fail-open, 기존 성질 유지)
- linked worktree이면 그 toplevel을 `wt(p)`로 둔다. 세션 `cwd`의 toplevel을 `home`으로 두고, `wt(p) == home`이면(자기 worktree) **통과**, 다르면 **걸림**

### 5.3 규칙

모든 규칙은 `HERDR_ENV=1`이고 config의 `hooks`가 `"off"`가 아닐 때만 동작한다.

| ID | 이벤트 / 도구 | 걸리는 조건 | main | sub | worker | worker-sub |
|---|---|---|---|---|---|---|
| R1 | PreToolUse `Bash` | 명령 위치의 `git … worktree add` (기존 정규식) | DENY_MAIN | DENY_SUB | DENY_WORKER | DENY_SUB |
| R2 | PreToolUse `EnterWorktree` | `path` 없음 | DENY_MAIN | DENY_SUB | DENY_WORKER | DENY_SUB |
| R3 | PreToolUse `Agent`/`Task` | `isolation == "worktree"` | DENY_MAIN | DENY_SUB | DENY_WORKER | DENY_SUB |
| R4 | PreToolUse `Write`/`Edit`/`MultiEdit`/`NotebookEdit` | `file_path`(또는 `notebook_path`)가 다른 worktree (§5.2) | 통과 | DENY_SUB | 통과 | DENY_SUB |
| R5 | PreToolUse `Bash` | 명령 안 `git -C <p>` 또는 `cd <p>`의 `p`가 다른 worktree. `p`는 따옴표 없는 토큰이나 단순 따옴표 토큰만 해석하고, 변수나 치환이 들어 있으면 판정하지 않는다 | 통과 | DENY_SUB | 통과 | DENY_SUB |
| R6 | PostToolUse `Agent`/`Task` | 항상 | NOTE_HANDOFF 주입 | — | — | — |

main의 쓰기(R4·R5)는 막지 않는다. 사용자가 메인에게 워커 worktree를 직접 고치라고 하는 것은 정상 사용이다.

### 5.4 메시지

- **DENY_MAIN** (R1~R3, 기존 `DENY` 대체): herdr 안에서 worktree 작업은 이 스킬을 거쳐야 한다는 점은 그대로 둔다. 예외 조항은 "**이 대화에서 사용자가 직접** plain worktree나 subagent를 요청한 경우에만"으로 좁힌다. 오케스트레이터가 이미 만든 계획은 예외가 아니라고 명시한다.
- **DENY_SUB**: "너는 서브에이전트다. 워커는 메인 세션만 띄운다. worktree를 만들거나 그곳에 쓰지 말고, 다른 방법으로 재시도하지 말라. 멈추고 최종 응답을 아래 블록으로 끝내라." 사용자에게 `!` 명령이나 훅 끄기를 제안하지 말라는 말도 넣는다.
- **DENY_WORKER**: "너는 herdr 워커 `<name>`이다. 워커는 worktree나 워커를 만들지 않는다. 자기 worktree(`<home>`)에서 직접 하거나, 별도 워커가 필요하면 `## Result`에 HANDOFF 블록으로 적어라. 오케스트레이터가 판단한다."
- **NOTE_HANDOFF** (R6, `additionalContext`): "이 서브에이전트가 `HERDR-HANDOFF` 블록을 반환하면 herdr-parallel-worktree 스킬을 로드해 §0부터 이어가라. 사용자에게 `!` 명령이나 훅 끄기를 안내하지 말라."

HANDOFF 형식 (DENY_SUB와 DENY_WORKER가 지정):

```
HERDR-HANDOFF
To the main session: load the herdr-parallel-worktree skill and turn this into a worker, confirming with the user once (§0). Do not tell the user to run it with `!` or to turn the hooks off.
name: <suggested worker name>
repo: <absolute path of the target repository>
goal: <one line>
branch: <suggested branch, or ->
steps:
- <step>
done: <what was already done, or nothing>
```

worker-sub가 반환한 블록은 워커 메인이 받는다. 워커 메인이 블록 지시대로 스킬을 로드해도 §0의 워커 검사에서 멈추고, 블록을 `## Result`에 옮겨 적는다. 그러면 오케스트레이터가 §5에서 결과를 수집할 때 받아서 판단한다.

블록 첫 줄에도 메인에게 주는 지시를 넣는다. R6이 이미 주입한 지시와 겹치게 해서, 둘 중 하나가 빠져도 메인이 올바른 경로로 가도록 한다.

### 5.5 스킬(SKILL.md 등) 변경

- **Hooks 절:** 주체별 규칙(§5.3) 요약과 비용(§6). W3의 원인이 된 "offer `! <command>`" 문장은 "이 대화에서 사용자가 직접 요청한 경우에만"으로 한정한다.
- **§0 시작:** `HERDR_PW_WORKER`가 있으면 즉시 중단한다("워커 안에서는 오케스트레이션 불가. 별도 워커가 필요하면 `## Result`에 HANDOFF를 적어라"). 중첩 방지의 2차 방어선이다.
- **§0 신설 "Receiving a handoff":** HERDR-HANDOFF는 태스크 제안 하나로 취급한다. `repo` → `ROOT`, `name`/`branch`는 제안값으로 쓰되 레포 관례를 우선한다. `steps`/`done`은 브리프에 반영한다. 다른 태스크와 같은 확인 질문에 넣어 확인은 1회로 유지한다. 서브에이전트가 남긴 부분 변경(`done`)이 메인 작업 트리에 있으면 기존 "미커밋 변경 확인" 규칙으로 다룬다.
- **§3:** `herdr pane run "$P" "export HERDR_PW_WORKER=<name>; cat <brief>"`
- **§3 W4:** `wait-output`의 `--timeout`을 15000으로 늘린다. 시간 초과(exit 1)가 나면 `herdr pane read "$P" --source recent-unwrapped --lines 5`로 마지막 줄을 확인한다. 브리프의 마지막 줄이 보이면 그대로 진행하고, 보이지 않으면 보고하고 멈춘다.
- **`references/resume.md`:** `pane run "$P" "echo shell-ready"`를 `"export HERDR_PW_WORKER=<name>; echo shell-ready"`로 바꾼다.
- **Never 목록:** "Start workers or create worktrees from inside a worker (`HERDR_PW_WORKER` set)"를 추가한다. 기존의 "Substitute an `Agent` subagent"는 유지한다.
- **README 두 개:** 훅 설명을 갱신한다.

### 5.6 코드 구조

- `scripts/hooks/route.py`
  - `decide(event: dict, env: Mapping[str, str], probe) -> dict | None`: 순수 판정. `probe(path) -> (git_dir, common_dir, toplevel) | None`을 주입받는다(테스트에서는 가짜, 실행 시에는 git).
  - `main()`: argv(`pre-tool-use` | `post-tool-use`), `enabled()`, stdin 파싱, 출력. 예외가 나면 출력하지 않는 성질은 유지한다.
- `hooks/hooks.json`과 `scripts/hooks/manage.py`의 `hook_entries()`는 **같은 집합**이어야 한다. 테스트로 비교한다.
- 등록 (두 곳 동일):

| 이벤트 | matcher | `if` | 인자 |
|---|---|---|---|
| PreToolUse | `Bash` | `Bash(*worktree add*)` | `pre-tool-use` |
| PreToolUse | `Bash` | `git -C`, `cd`가 들어간 명령만 (정확한 패턴은 V2에서 확정) | `pre-tool-use` |
| PreToolUse | `EnterWorktree\|Agent\|Task` | — | `pre-tool-use` |
| PreToolUse | `Write\|Edit\|MultiEdit\|NotebookEdit` | — | `pre-tool-use` |
| PostToolUse | `Agent\|Task` | — | `post-tool-use` |

- 모든 hook command 앞에 `[ "$HERDR_ENV" = 1 ] || exit 0;` 셸 가드를 둔다. herdr 밖에서는 python을 띄우지 않는다.
- `manage.py`의 `strip_ours()`는 `MARK`로 찾으므로 그룹 수가 늘어도 그대로 동작한다. `on`을 다시 실행하면 기존 그룹을 지우고 새 집합을 등록하므로 업그레이드도 처리된다.

## 6. 비용

- **herdr 밖:** 토큰 0. 해당 도구 호출마다 셸 가드 한 번만 실행된다.
- **herdr 안:** Write/Edit 등을 호출할 때마다 python 1회. 서브에이전트(`agent_id`)일 때만 git을 1회 호출한다. Agent를 띄울 때마다 NOTE_HANDOFF 한 줄(약 50토큰)이 추가된다.

## 7. 알려진 누락

1. **서브에이전트가 메인 작업 트리를 직접 고치는 위임.** worktree가 관여하지 않으므로 범위 (a)에서는 정상이다. 나중에 넓힐 필요가 생기면 config 키(예: `routeSubagentWrites: "worktree" | "all"`)로 검토한다. 이번에는 구현하지 않는다.
2. **경로를 추출할 수 없는 Bash 쓰기:** 스크립트 내부 쓰기, 변수로 조립한 경로, `pushd` 등.
3. **HANDOFF를 받은 메인이 지시를 따르는지는 모델 행동이다.** R6과 블록 첫 줄로 이중화했지만 보장할 수는 없다. V3에서 사건 재현으로 확인한다.

## 8. 기각한 대안

| 대안 | 기각 이유 |
|---|---|
| Agent 프롬프트 텍스트에서 worktree 지시 검사 | 문구 휴리스틱이라 오탐·누락이 생김. 행위 원칙(§2)에 반함 |
| UserPromptSubmit에서 "병렬" 키워드 감지 | 같은 이유 |
| C. 사전 허가 위임 (서브에이전트가 직접 스킬 실행) | AskUserQuestion이 메인에만 있어 확인 원칙이 깨지고 중첩 위험이 있음 |
| PostToolUse(Agent)에서 결과의 HANDOFF 감지 | F4: 비동기라 결과 텍스트가 없음 |
| SubagentStop에서 메인에 지시 주입 | F6: 서브에이전트에 주입되고 9회 반복 실행됨. **다시 시도하지 말 것** |
| runs.json의 worktree 경로로 워커 판별 | 간접 추론. V1이 실패할 때만 대체 수단으로 씀 |
| 서브에이전트의 저장소 쓰기 전반 차단 (b′) | 가벼운 위임까지 막힘. 사용자가 (a)를 선택함 |

## 9. 검증

### 구현 전 실측 (계획의 첫 단계)

- **V1:** herdr pane에서 `export HERDR_PW_WORKER=x` 후 `herdr agent start`로 띄운 claude의 훅이 이 변수를 보는지 확인한다. 실패하면 runs.json의 `worktree`와 `cwd`를 비교하는 대체 판별로 바꾼다.
- **V2:** `if` 필터 문법으로 `git -C`, `cd`를 포함한 명령만 걸러지는지 확인한다(`Bash(*git -C *)`, `Bash(cd *)`, `Bash(* cd *)` 등).
- **V3:** 프로젝트 안 경로(`.worktrees/x`)에서도 F3(`cwd`가 `cd`를 따라가지 않음)가 성립하는지 확인한다.
- **V4:** W4 재현. 긴 브리프로 `wait-output`의 시간 초과 원인을 확인한다.

### 단위 테스트 (`skills/herdr-parallel-worktree/tests/`, 표준 라이브러리 `unittest`만 사용)

- **입력 fixture:** §3에서 측정한 JSON 형태(메인/서브 PreToolUse, PostToolUse(Agent))를 그대로 쓴다.
- **판정 행렬:** R1~R6 × 주체 4종 × 걸림/통과. 그리고 다음 경우들.
  - 자기 worktree 쓰기는 통과
  - 저장소 아님, git 오류, 시간 초과는 통과
  - `HERDR_ENV` 없음이나 `hooks: off`이면 출력 없음
  - 커밋 메시지 안의 "worktree add"는 통과 (기존 동작)
  - 발단 사건의 서브에이전트 명령 `git worktree add ../kb-skills-fix-normalize -b fix/...` → DENY_SUB
- **실제 git 통합 테스트 1개:** 임시 저장소와 linked worktree를 테스트 코드 안에서 만들고(`subprocess`), 실제 `probe`로 §5.2를 확인한다.
- **등록 일치:** `hooks/hooks.json`과 `manage.py hook_entries()`가 경로 접두어만 빼고 같은지 확인한다.

### 수동 E2E

herdr 안에서 발단 사건을 재현한다. 메인이 worktree 지시를 담은 Agent를 띄우면 → R1 DENY_SUB → HANDOFF가 반환되고 → 메인이 스킬 §0 확인 1회 → 워커가 사이드바에 나타나고 `HERDR_PW_WORKER`가 설정되어 있어야 한다.

## 10. 변경 파일

- `skills/herdr-parallel-worktree/scripts/hooks/route.py` — 판정 재구성, `post-tool-use` 추가
- `hooks/hooks.json`, `skills/herdr-parallel-worktree/scripts/hooks/manage.py` — 등록 집합
- `skills/herdr-parallel-worktree/SKILL.md` — Hooks, §0, §3, Never
- `skills/herdr-parallel-worktree/references/resume.md` — export
- `skills/herdr-parallel-worktree/tests/` — 신규
- `README.md`, `README.ko.md` — 훅 설명
- `.claude-plugin/plugin.json` — 버전 올림
