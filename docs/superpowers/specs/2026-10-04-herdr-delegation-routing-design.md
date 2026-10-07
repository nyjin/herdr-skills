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
| R4 | PreToolUse `Write`/`Edit`/`MultiEdit`/`NotebookEdit` | `file_path`(또는 `notebook_path`)가 자기 worktree 밖이고 owner가 있음 (§13.2 개정: 대상의 owner별) | 통과 | DENY_SUB(owner). main checkout은 통과 | DENY_WORKER_WRITE(owner) | DENY_SUB(owner) |
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

## 11. 실측 결과 (구현 전, 2026-10-05)

| 항목 | 결과 | 반영 |
|---|---|---|
| V1 워커 표식 전달 | A export: `worker=v1a`, B split `--env`: `worker=v1b` (둘 다 전달됨. 두 pane 모두 시작 대화상자 때문에 `agent_not_ready`였지만 SessionStart 훅은 실행됨) | export 유지 |
| V2 `if` 패턴 | (1) `cd /tmp && true` → `Bash(cd *)` (2) `git -C /tmp status` → `Bash(*git -C *)` (3) `ls` → 없음 (4) `true && cd /tmp` → `Bash(cd *)`. `Bash(* cd *)`는 한 번도 발동하지 않음: Claude Code가 복합 명령을 하위 명령별로 매칭함 | Task 4에서 `Bash(* cd *)` 그룹 제거 (`if`를 빼지 않음) |
| V3 프로젝트 안 `cd` 후 `cwd` | main: `cd .worktrees/x` 다음 호출부터 `cwd`가 `…/.worktrees/x`. sub: 메인이 바꾼 `cwd`를 그대로 받음 (세션의 셸 상태 공유). 프로젝트 밖으로 `cd`하면 원위치로 초기화(F3) | `home`은 "hook `cwd`의 worktree이며, 마지막으로 `cd`한 디렉터리일 수 있다". 알려진 누락에 추가(§7-4) |
| V4 `wait-output` | 새 pane에서 300줄: exit 0 / 2.64s. 셸이 떠 있는 pane에서 900줄: exit 0 / 0.56s. `--lines 400`: 한 번은 exit 2 / 0.03s, 재시도는 exit 0 (불안정) | 원인은 브리프 길이가 아니라 새 pane의 셸 시작 시간. Task 5는 `--lines` 없이 timeout 15000 + 화면 재확인 |

§7 보충:

4. **메인 세션이 프로젝트 안의 linked worktree로 `cd`한 상태**(예: `.worktrees/x`)에서는 그 worktree가 `home`이 된다. 서브에이전트가 그곳에 쓰는 것은 "자기 worktree"로 통과한다(V3).

## 12. 개정: Bash 쓰기는 명령이 아니라 결과로 감지한다 (2026-10-05)

### 12.1 배경
병합 직전 점검에서, R5(`cd`/`git -C` 정규식)는 서브에이전트가 다른 worktree를 바꾸는 Bash 명령 9개 중 2개만 잡았다. `echo > …`, `sed -i …`, `cp`, `python -c`, `git --work-tree=…`, `npm --prefix …`, 변수로 조립한 경로는 모두 통과했다. Bash는 임의의 프로그램을 실행하므로 명령 문자열로 "어디에 쓰는가"를 판정하는 방식은 원리적으로 완전할 수 없다. 사용자 결정에 따라 **쓰기는 결과로 감지**하고, **생성은 지금의 결정적 사전 차단(R1~R3)을 유지**한다.

### 12.2 실측 (Claude Code 2.1.289)

| # | 항목 | 결과 |
|---|---|---|
| O1 | 실패한 Bash | PostToolUse 대신 `PostToolUseFailure`가 발동한다. `tool_use_id`는 Pre와 같다. `error: "Exit code 1"` |
| O1b | 실패 이벤트의 응답 | `additionalContext`가 서브에이전트에 도달한다 |
| O2 | 성공 이벤트의 응답 | `decision: "block"`의 `reason`과 `additionalContext` 모두 서브에이전트에 도달한다. 하지만 실행을 멈추지는 않는다(서브에이전트가 다음 명령을 계속 실행함) |
| O3 | 백그라운드 Bash | PostToolUse가 실행 시작 0.06초 후 발동한다(`tool_response.backgroundTaskId`). 실제 쓰기는 그 뒤에 일어난다. 서브에이전트가 끝나면 백그라운드 작업도 종료되었다(`backgroundEndsWithFinalResponse`) |
| O4 | 이미 수정된 파일 재수정 | `git status --porcelain`은 변하지 않는다. mtime은 변한다(추적·비추적 파일 모두) |
| O5 | 비용 | 소형 저장소 + linked worktree 5개: 스냅샷 1회 134ms(순차). 실제 저장소(1.8~2.8천 파일) `git status` 1회: 71ms(warm)~177ms(cold) |
| O7 | mtime 대 ctime | `cp -p` 덮어쓰기, `touch -t` 과거 시각, `rsync -a` 새 파일은 mtime이 창 밖으로 남아 놓친다. ctime(inode 변경 시각)은 셋 모두 창 안이었다. `git --no-optional-locks status`와 파일 읽기는 ctime을 바꾸지 않았다 |
| O6 | 실행 시간 | Bash의 PostToolUse와 PostToolUseFailure 모두 `duration_ms`가 있다. 창 [Post 시각 − duration, Post 시각]에 실제 쓰기 mtime이 들어갔다(성공 4.6초 창, 실패 1.1초 창). 창 시작은 PreToolUse 훅 시각보다 약 0.07초 늦다 |

### 12.3 설계

**R5를 교체한다.** `DIR_ARG`/`dir_targets`와 `cd`·`git -C` `if` 필터는 제거한다. R4(Write/Edit 도구의 사전 차단)는 유지한다. 도구의 쓰기는 대상 경로가 입력에 있으므로 미리 막는 편이 낫다.

**R7 — 서브에이전트 Bash의 결과 관찰** (PostToolUse와 PostToolUseFailure, `agent_id`가 있을 때만. 메인과 워커 본인은 곧바로 종료). 실행 전 스냅샷은 찍지 않는다. O6의 `duration_ms`로 명령이 실행된 시간 창을 알 수 있으므로, PreToolUse 훅과 호출별 상태 파일이 필요 없다.

1. **관찰 대상 W**는 두 집합의 합집합이다.
   - 세션 `cwd` 저장소의 linked worktree: `git worktree list --porcelain` 1회
   - runs.json에 기록된 열린 워커의 worktree: 다른 저장소 포함(발단 사건처럼 메인과 다른 저장소)
   
   단, `home`(세션 `cwd`의 worktree)은 제외한다. W가 비어 있으면 아무것도 하지 않는다.
2. **창** = [Post 시각 − `duration_ms` − 0.5초, Post 시각]. 0.5초는 시계와 시각 기록 시점의 오차를 흡수하기 위한 여유다. 파일 시각은 모두 **ctime**으로 본다(O7). mtime은 `cp -p`·`rsync -a`·`touch`로 과거 값을 가질 수 있지만, ctime은 쓰기와 메타데이터 변경 때 항상 현재 시각이 되고 임의로 설정할 수 없다.
3. **변화 감지:** W의 worktree마다 병렬로, 각 호출에 2초 timeout을 걸고 다음 중 하나라도 창 안이면 "바뀜"으로 본다.
   - `git --no-optional-locks status --porcelain=v2 -z --untracked-files=all`에 나온 파일 중 ctime이 창 안인 것: 새 수정과 재수정(O4)을 모두 잡는다.
   - 삭제로 나온 파일은 상위 디렉터리의 ctime이 창 안인지 본다.
   - `git rev-parse --git-path logs/HEAD`의 ctime이 창 안인지 본다: 커밋, 체크아웃, reset을 잡는다.
   
   바뀐 worktree 집합을 C라고 한다.
4. **귀속:** C의 worktree w마다 판정한다.
   - 명령 원문에 w의 경로가 들어 있으면 → 서브에이전트가 바꾼 것이다.
   - 그렇지 않고, w가 열린 워커의 worktree이며 그 워커가 `working` 상태이면 → **보류(통과)**. 워커 자신이 고쳤을 수 있다.
   - 그 밖의 경우 → 서브에이전트가 바꾼 것이다(그 시간에 w를 고칠 다른 주체가 없음).
5. **응답:** 서브에이전트로 귀속된 w가 있으면 `additionalContext`로 OBSERVED_SUB를 보낸다. 내용은 "worktree `<w>`를 바꿨다. 더 바꾸지 말고 멈춰서 HANDOFF를 반환하라. 이미 바꾼 것은 `done:`에 적어라"이다. O2에 따라 실행을 멈추는 장치는 없으므로 지시문에 의존한다.
6. **백그라운드(O3):** `tool_response.backgroundTaskId`가 있는 PostToolUse에서는 판정하지 않는다. 대신 `${TMPDIR}/herdr-pw-observe/<session_id>/<agent_id>.json`에 (시작 시각, 명령 원문)을 추가한다. 같은 에이전트의 다음 PostToolUse/PostToolUseFailure에서는 창 시작을 그 기록의 가장 이른 시작 시각으로 넓히고, 귀속 규칙의 명령 원문에 그 백그라운드 명령들을 포함한다. 판정한 뒤 기록을 지운다. 에이전트가 더 이상 Bash를 쓰지 않으면 놓친다(알려진 누락). 1시간이 지난 기록은 훅이 실행될 때 지운다.
7. **실패하면 통과:** git 오류, timeout, `duration_ms` 누락, 기록 파일 오류는 모두 감지 없음으로 처리한다.

**워커 상태 확인:** 귀속 4단계에서만, 그리고 경로 언급이 없고 runs.json의 워커 worktree가 C에 있을 때만 `herdr agent get <name>`을 호출한다.

### 12.4 비용 목표
- 워커와 linked worktree가 없을 때: python 시작만(약 40ms). 메인과 워커 본인은 매번 이 비용만 든다.
- 서브에이전트 Bash, worktree 5개: PostToolUse 1회에 0.3초 이하가 목표다(병렬 git, Pre 없음). 구현 단계에서 L2c로 측정하고, 넘으면 보고한다.

### 12.5 알려진 누락 (§7에 추가)
5. 쓰기는 **사후 감지**다. 첫 명령의 변화는 남는다. 되돌리지 않고 HANDOFF의 `done:`으로 전달한다.
6. `working` 상태 워커의 worktree에, 명령 원문에 경로가 드러나지 않는 방식으로 쓰면 보류로 통과한다(오탐 방지가 우선).
7. 백그라운드 명령의 쓰기는 같은 에이전트가 다음 Bash를 쓸 때만 감지된다.
8. 메인 세션과 워커 본인의 Bash 쓰기는 관찰하지 않는다(정상 사용).
9. ctime은 메타데이터 변경(chmod, 이름 변경)에도 바뀐다. worktree 변화로 취급한다. 시스템 프로세스(확장 속성을 쓰는 보안 도구 등)가 창 안에 ctime을 바꾸면 오탐이 생길 수 있다.
10. `.gitignore`로 무시되는 파일(빌드 산출물 등)의 변화는 `git status`에 나오지 않으므로 보지 않는다.

### 12.6 검증 추가
- **L1:** 창 계산(`duration_ms`, 여유 0.5초, 백그라운드 기록으로 넓히기), 변화 감지 순수 함수(창 안/밖 ctime, 재수정, `cp -p`처럼 mtime이 과거인 쓰기, 삭제의 상위 디렉터리, logs/HEAD), 귀속 규칙 표(경로 언급 × 워커 상태), 실패 시 통과, 백그라운드 기록 정리
- **L2:** live_hooks에 C12~C15 추가
  - C12: 서브에이전트가 `echo > <다른 wt>/f` 실행 → OBSERVED_SUB 수신, HANDOFF 반환
  - C13: `sed -i`로 이미 수정된 파일 재수정 → 감지
  - C14: 실패로 끝나는 쓰기(`…; false`) → `PostToolUseFailure`에서 감지
  - C15: 서브에이전트가 자기 `cwd` worktree에 쓰기 → 통과
- **L2c:** worktree 5개에서 서브에이전트 Bash 1회의 PostToolUse 지연 측정, 목표 0.3초

## 13. 개정: 자기 worktree 밖에 쓰면 그 worktree의 주인에게 전달한다 (2026-10-07)

### 13.1 원칙
**자기 worktree 밖에 쓰면, 그 worktree의 주인이 받는다. 주인이 없으면 새로 만든다. 전달은 항상 메인이 한다.** child와 child의 서브에이전트는 같은 범위로 취급한다. child 안의 서브에이전트 사용(테스트 작성 위임, 리뷰·수정 플러그인 등)은 자기 worktree 안에서는 그대로 허용한다.

### 13.2 쓰는 주체 × 대상

| 쓰는 주체 ↓ / 대상 → | 자기 worktree (`home`) | 형제 child의 worktree (runs.json에 주인 있음) | 원본 저장소의 main checkout | 주인 없는 linked worktree |
|---|---|---|---|---|
| 메인 | 허용 | 허용 | 허용 | 허용 |
| 메인의 서브에이전트 | 허용 | HANDOFF → 메인이 주인 child에게 전달 | 허용 (메인의 home) | HANDOFF → 메인이 새 child 생성 (확인 1회) |
| child / child의 서브에이전트 | 허용 | 메인에 보고 → 메인이 주인 child에게 전달 | 메인에 보고 → **메인이 사용자에게 알리고 묻는다** | 메인에 보고 → 메인이 새 child 생성 (확인 1회) |
| worktree 생성 (child / child의 서브에이전트) | 차단. 그래서 child가 만든 worktree는 생기지 않는다 | | | |

"주인"은 runs.json의 열린 기록에서 worktree 경로로 찾는다. "main checkout"은 대상 worktree가 linked worktree가 아니고(`git-dir == common-dir`), 그 저장소가 child의 저장소와 같은 경우다.

### 13.3 감지 범위 확장
- **child 본인도 감지 대상에 넣는다.** §5.3의 R4(Write/Edit 사전 차단)와 §12의 R7(Bash 결과 관찰)을 `worker` 주체에도 적용한다. 판단 기준은 "home 밖"이다. home 안의 작업은 계속 통과하고 관찰 비용도 들지 않는다(대상 집합 W에서 home을 제외하므로).
- child의 관찰 대상 W에는 main checkout도 포함한다. 메인 쪽 주체에게 main checkout은 home이므로 대상이 아니다.
- 차단이나 감지 메시지에는 대상 worktree의 **주인 이름**(있으면)을 넣는다. HANDOFF에는 `owner: <worker name | main-checkout | none>` 줄을 추가한다.

### 13.4 메인의 전달 절차 (스킬에 새 절 추가)
HANDOFF를 받거나 child의 `## Result`에서 보고를 받으면 `owner`에 따라 처리한다.
- **`owner: <worker>`**
  1. 그 워커가 열려 있고 claude가 살아 있으면 후속 지시를 보낸다. 첫 지시와 같은 방식을 쓴다: 지시를 파일로 쓰고, 그 파일을 가리키는 한 줄을 보낸다(긴 붙여넣기는 거부될 수 있음). 워커가 `working`이면 `idle`/`done`이 될 때까지 기다린 뒤 보낸다.
  2. 워커가 정리됐거나 세션이 끝났으면 `references/resume.md`로 재개한 뒤 보낸다.
  
  기존 워커에 일을 더하는 것이므로, 같은 확인 질문 안에서 사용자에게 보이고 확인 1회를 유지한다.
- **`owner: main-checkout`**: 무엇이 바뀌었는지(또는 바뀌려 했는지)와 경로를 사용자에게 그대로 알리고 어떻게 할지 묻는다. 메인이 대신 반영하거나 되돌리지 않는다.
- **`owner: none`**: 기존 흐름대로 새 child를 만든다(확인 1회).

### 13.5 실측 결과 (2026-10-07, scratch 워커 `scratch-fix`)

| # | 항목 | 결과 | 반영 |
|---|---|---|---|
| T3 | 정리된 워커를 재개한 뒤 후속 지시 | workspace는 닫혔지만 worktree는 남아 있었다 → `herdr worktree open --cwd <root> --path <wt> --label <name>`으로 다시 열고, `export HERDR_PW_WORKER` 후 `agent start … -- <workerArgs> --add-dir <BRIEFS> --resume <session_id>`. 같은 session_id로 돌아왔다. "파일을 가리키는 한 줄"을 `agent prompt --wait`로 보내자, 이전 대화에서 받은 훅 오류 문장을 기억해 정확히 썼다 | 재개 후 전달 가능. resume.md는 "worktree는 남고 workspace만 닫힌 경우"(`worktree open`)를 다뤄야 한다 |
| T1 | 살아 있는 워커에 한 줄 후속 지시 | 위 재개된 워커와 이후 T2에서 3회 모두 거부 없이 파일을 읽고 따랐다 | deliver.md는 "파일 + 한 줄 `agent prompt`" |
| T2 | 작업 중인 워커에 보내기 | 25초 반복문 실행 중(21:00:08)에 보냈다. 반복문은 중단 없이 끝났고(21:00:33), 후속 지시는 그 뒤(21:00:38)에 처리됐다. 오류도 거부도 없었다(대기열). `agent wait --until idle --until done` 후 보내는 흐름도 동작했다 | 기본은 대기 후 전달. 대기가 timeout이면 그냥 보내도 대기열로 안전하다 |
| O8 | 한 에이전트의 병렬 Bash 훅 | 병렬 Bash 2개의 PostToolUse 훅이 같은 시각(±0.01초)에 동시에 실행됐다 | BgStore는 작업별 파일 + rename 소유권 획득(동시성 안전)이어야 한다 |
| O9 | 메인을 걸러내는 방법의 비용 | 셸 가드(`IN=$(cat)`; bash 3.2): 1KB 12ms, 1MB 58ms, 10MB 467ms. python `-S` 조기 종료(원본 바이트에서 `"agent_id"`를 찾고, 없으면 JSON 파싱 전에 종료): 24 / 33 / 86ms | 셸 가드 대신 python 조기 종료를 쓴다. 최악의 경우가 제한되고, JSON 안 셸 이스케이프가 필요 없다 |

## 14. 구현 결과로 확정된 규칙 (2026-10-07, plan `docs/superpowers/plans/2026-10-07-observe-and-owner-routing.md`)

§12.3의 R7은 구현하면서 다음과 같이 확정되었다. §12.3과 이 절이 다르면 이 절을 따른다.

- **귀속은 "변화 + 언급"이다.** 실행 시간 창 안에 그 worktree가 실제로 바뀌었고(ctime), 그리고 명령이 그 worktree 안의 경로를 언급했을 때만 귀속한다. §12.3-4의 "언급이 없으면 워커 상태로 판단"(보류 규칙과 `herdr agent get` 조회)은 없앴다. 병렬 서브에이전트, 메인 세션, 사용자의 동시 편집에서 생기는 오탐을 막기 위해서다(사용자 결정).
- **언급이 없으면 git을 호출하지 않는다.** 경로 토큰이 없으면 세션 디렉터리 조회도 하지 않는다. 실측: 서브에이전트나 워커의 언급 없는 Bash는 54~56ms였다.
- **index ctime은 쓰지 않는다.** 다른 프로세스가 평범한 `git status`를 실행할 때마다 index가 다시 쓰였다(실측). 그 대신 명령이 언급한 경로 자체의 ctime(없으면 가장 가까운 존재하는 상위 디렉터리)과 `logs/HEAD`를 본다. 이것으로 `git restore f`와 `git -C wt restore f`를 잡는다.
- **메인 걸러내기는 python 조기 종료로 한다(§13.5 O9).** `pre-tool-use-write`, `post-tool-use-bash`, `post-tool-use-failure` 인자는 원본 바이트에 `"agent_id"`가 없고 `HERDR_PW_WORKER`도 없으면 json을 import하기 전에 끝난다.
- **owner 판정(§13.2)은 `owners.py`가 한다.** runs.json을 git보다 먼저 보므로, 워커 worktree 안의 서브모듈도 그 워커 소유다. `--separate-git-dir` 저장소에서는 git이 main checkout 대신 git 디렉터리를 보고하므로, 검증에 실패하면 "모름"(허용)으로 처리한다.

§7 알려진 누락 추가:

11. 명령에 경로가 드러나지 않는 쓰기는 놓친다(스크립트 내부, `cd ..; cd b`처럼 단계적으로 만든 경로).
12. 다른 worktree를 읽는 명령이, 그곳에서 동시에 일어난 다른 주체의 쓰기와 같은 시간 창에 겹치면 오탐이 될 수 있다. 시간 창 시작을 1초 단위로 내림하므로 최대 1.5초 앞까지 넓어진다.
13. 데몬화된 자식 프로세스(`nohup … &`)가 명령이 끝난 뒤에 쓰는 것은 놓친다. 하위 디렉터리 파일만 건드리는 `git -C wt stash`처럼, 언급된 경로와 logs/HEAD를 모두 건드리지 않는 파괴적 명령도 놓친다.
