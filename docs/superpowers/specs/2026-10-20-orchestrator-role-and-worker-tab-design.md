# 역할 주입과 워커 전용 탭 — 설계 기록

- 날짜: 2026-10-20
- 버전: 0.7.0
- 범위: `herdr-parallel-worktree` 스킬 · 훅(`route.py`) · 새 스크립트 `worker-pane.py`

## 1. 무엇이 문제였나

실제 세션 두 건에서 스킬이 발동하지 않았다.

| 사례 | 일어난 일 | 원인 |
|---|---|---|
| 다른 스킬(executor)이 "티켓마다 서브에이전트를 띄운다, 사람이 입력할 수 있는 대화형이어야 한다"고 지시 | 메인 세션이 Agent 서브에이전트로 넘기고, "하네스가 못 주면" 조항으로 빠져나감 | 세션이 herdr 안에서 자기가 오케스트레이터라는 것을 모름. 스킬 설명은 "several … at the same time"에 맞춰져 있고 "Not for single edits"로 티켓 한 건을 밀어냄 |
| 메인 세션이 티켓 한 건을 위해 `git worktree add -b feature/<KEY>` | 훅이 `EnterWorktree`로 보냄. `.claude/worktrees/feature+<KEY>`, 브랜치 `worktree-feature+<KEY>`가 생겨 저장소 관례와 어긋남. herdr-plus가 그 workspace에 claude를 따로 띄워 idle로 남음 | 훅 메시지가 "the same git worktree"라고 사실과 다르게 말하고, 티켓 작업을 메인 세션이 직접 하는 쪽으로 보냄 |

같은 실행에서 워커 경로도 깨질 수 있었다. herdr-plus 레이아웃이 root pane에서 claude를 띄우므로, 스킬의 `pane run "export …; cat brief"`가 셸이 아니라 그 claude에 입력되고 `agent start`는 `agent_pane_busy`가 된다.

## 2. 결정

1. **역할을 세션 시작 때 알려 준다 (SessionStart, R9).** 메인 세션에는 "너는 오케스트레이터다. 넘기는 작업은 티켓 한 건이라도 워커다. 다른 스킬의 '서브에이전트를 띄워라'도 워커다"를, 워커에는 이름과 경계를 준다. 목적을 나열하기보다 역할을 서술한다(사용자 결정). 서브에이전트에는 아무것도 주지 않는다. herdr 안의 세션마다 한 문단(약 100토큰)이 들고, 훅 비용은 약 37ms다.
2. **`git worktree add` 차단 메시지를 역할 문장으로 바꾼다.** 티켓 작업은 워커로, `EnterWorktree`는 사용자가 이 세션 자체를 옮기라고 할 때만. `EnterWorktree`가 실제로 만드는 경로·브랜치를 적는다.
3. **스킬 설명이 단일 작업을 받는다.** "a task, even a single ticket, … that the user can watch or step into". 제외 조건은 "quick edits done in this session"으로 좁힌다. 본문에 오케스트레이터 → 워커 → 워커 안의 서브에이전트 계층과, 다른 스킬과 부딪칠 때의 우선순위를 적는다.
4. **워커는 언제나 자기 탭에서 시작한다.** `worker-pane.py`가 (1) 이 worktree에 반응한 플러그인 핸들러가 끝나기를 기다리고 (2) `HERDR_PW_WORKER`를 환경변수로 넣은 탭을 만들고 (3) 그 셸이 프롬프트에서 쉬고 있을 때까지 기다린다. 플러그인이 만든 탭과 root pane에는 입력하지 않는다. 새 워커·재개·후속 전달이 모두 이 길을 쓴다.
5. **`EnterWorktree` 뒤에 사이드바 라벨을 알려 준다.** 플러그인이 띄운 claude는 별개의 idle 세션이라는 것도 함께.

## 3. 실측

모두 herdr 0.9.3, herdr-plus 0.1.24(`_default.toml`: claude · git · shell 탭), persiyanov.reviewr가 설치된 환경에서 이 저장소로 했다.

| # | 확인한 것 | 결과 |
|---|---|---|
| M1 | worktree를 만든 직후 root pane | 0~4초는 셸이 foreground, 8초쯤 claude로 바뀜. 핸들러는 1초 안에 끝났지만 명령은 셸 초기화 동안 입력 대기열에 있었다. **한 순간의 "셸이 비었다"는 판정 기준이 못 된다** |
| M2 | 핸들러가 끝나기 전에 탭을 만들면 | herdr-plus 로그: `already has 2 panes; skipping layout`. 레이아웃이 빠진다 |
| M3 | 완료 신호 | `herdr plugin log list`가 이벤트별 핸들러의 `status`(`running` → `succeeded`)와 시각을 남긴다. workspace id는 없어 시작 시각(`SINCE`)으로 거른다 |
| M4 | `tab create --env` | 새 탭의 셸과 그 안의 claude가 `HERDR_PW_WORKER`를 받는다 (`PW=[probe]`, 워커가 env.txt에 이름을 씀) |
| M5 | 전체 흐름 (스킬 1~3단계 그대로) | 탭이 `claude, git, shell, <name>`. 레이아웃이 그대로 있고, 워커는 전용 탭에서 브리프를 따름. SessionStart로 받은 문장을 그대로 옮겨 적음: "You are herdr worker `e2e-role`, …" |
| M6 | 셸 준비 판정 | foreground 그룹이 셸이어도 프롬프트 훅(`mise`)이 같은 그룹에서 돌면 `agent start`가 `agent_pane_busy`. 판정을 "셸만 foreground에 있음, 두 번 연속"으로 바꾸고, `cat` 뒤 다시 도는 훅에 대비해 `agent_pane_busy`는 1초 간격 최대 세 번 다시 시도한다 |
| M7 | 재개 | workspace를 닫고(worktree 유지) `worktree open` → `worker-pane.py` → 새 탭에서 `claude --resume <id>`. 같은 세션 id로 떠서 앞서 env.txt에 쓴 값을 기억함. 플러그인은 `worktree.opened`에도 반응했고 기다림이 그것을 잡았다 |

## 4. 기각한 안

| 안 | 기각 이유 |
|---|---|
| A. 레이아웃이 띄운 claude를 끄고 그 pane을 쓴다 | 사용자가 레이아웃에 적어 둔 실행(이 저장소는 `JAVA_HOME=…21`)을 무력화한다 |
| C. 레이아웃이 띄운 claude를 워커로 쓴다 (`send-text`로 지시) | 지시는 받았지만(실측), 환경변수를 넣을 수 없어 워커 판정을 cwd로 바꿔야 하고, `workerArgs`·`--add-dir`이 빠지며, 그 pane에 무엇이 뜰지는 플러그인마다 다르다. 특정 명령(claude)을 기준으로 갈래를 나누게 된다 |
| root pane이 셸 프롬프트인지로 판정해 쓴다 | M1: 플러그인 명령이 아직 대기열에 있을 수 있어 경쟁 상태다 |
| Agent 호출의 프롬프트 안 worktree 경로로 막는다 | 훅은 프롬프트 문구로 판정하지 않는다는 원칙과 어긋난다. 역할 주입으로 먼저 다룬다 |

## 5. 남은 것

- 레이아웃이 claude를 띄우면 그 탭에 idle claude가 하나 남는다. 사용자의 레이아웃이므로 손대지 않고, 보고에 워커의 탭 이름을 적는다.
- `plugin log list`가 없는 오래된 herdr에서는 기다릴 핸들러가 없는 것으로 보고 `--quiet-ms`(2초) 뒤 탭을 만든다.
- 다른 저장소의 스킬(executor)이 "서브에이전트"로 적은 문장은 그 저장소에서 고친다. 이 저장소는 역할 주입과 우선순위 문장으로 충돌을 푼다.
