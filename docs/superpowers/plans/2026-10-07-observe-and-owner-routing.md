# herdr-parallel-worktree: 결과 관찰(R7) + 주인 기반 전달(§13) 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Spec: `docs/superpowers/specs/2026-10-04-herdr-delegation-routing-design.md` (§12, §13, §13.5).

## Context

`design/delegation-routing` 브랜치(미병합)는 herdr 안에서 서브에이전트나 워커가 worktree 작업을 하면 막고, HERDR-HANDOFF로 메인에게 넘기는 훅을 구현한 상태다(E2E 6/6 통과). 그런데 병합 직전 점검에서 두 가지 문제가 드러났다.

1. **명령 문자열 정규식(R5: `cd`/`git -C`)은 원리적으로 불완전하다.** 서브에이전트가 다른 worktree에 쓰는 명령 9개 중 2개만 잡았다.
2. **막힌 일을 보낼 곳이 "새 워커" 하나뿐이다.** 대상 worktree에 주인(형제 워커)이 있으면 그 주인에게 가야 한다.

사용자와 합의한 해법(spec `docs/superpowers/specs/2026-10-04-herdr-delegation-routing-design.md` §12·§13 + 이번 결정)은 다음과 같다.

- **R5를 제거하고 R7을 둔다.** R7은 Bash가 끝난 뒤(PostToolUse/PostToolUseFailure) **"`duration_ms` 시간 창 안에 실제로 바뀌었고(ctime), 명령이 그 worktree 경로를 언급했다"**를 모두 만족할 때만 그 쓰기를 실행한 쪽에 귀속한다. 이 규칙은 이번에 확정했다. 병렬 서브에이전트, 메인, 사용자 편집으로 생기는 오탐을 없애고, 언급된 worktree만 검사하므로 대부분의 Bash는 git 호출이 0회다.
- **주인 기반 전달:** 자기 worktree 밖에 쓰면 그 worktree의 주인이 받는다. 주인이 없으면 새로 만든다. 전달은 항상 메인이 한다. main checkout이면 메인이 사용자에게 알리고 묻는다.

계획을 끝까지 실행한 뒤 브랜치 전체를 다시 리뷰받는다. 그다음 사용자가 요청한 **main 병합과 push**를 한다.

## Global Constraints

- Python 표준 라이브러리만 쓴다. 단위 테스트는 `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v`로 실행한다(`test_*.py`만 수집). `live_*.py`와 `hook_cost.py`는 수동으로 실행한다.
- **fail-open:** 예외, git·herdr 오류, timeout(2초), `duration_ms` 누락, 상태 파일 오류는 모두 출력 없음으로 처리한다. runs.json은 **절대 예외를 던지지 않는 전용 리더**로 읽는다. `runs.load()`는 `sys.exit`를 호출하므로 재사용하지 않는다.
- herdr 밖이거나 `hooks: off`이면 python을 띄우지 않고 출력도 없다.
- git 호출은 모두 `--no-optional-locks`로 한다.
- 경로는 모두 `os.path.realpath`로 정규화한다. 포함 여부는 경로 구분자 경계로 판정한다(`/w/a`가 `/w/ab`를 포함하지 않음). 여럿이 겹치면 가장 긴 접두사가 이긴다.
- `hooks/hooks.json`과 `manage.py hook_entries()`는 같은 집합을 등록한다(테스트로 강제).
- 테스트용 claude는 항상 config `workerArgs`(현재 `--dangerously-skip-permissions`)로 띄운다. 이미 신뢰된 scratch(`/private/tmp/herdr-e2e.XTll/repo`)를 재사용한다. 확인 창이 끼어들지 않게 하기 위해서다.
- 커밋은 태스크 단위로 `design/delegation-routing`에 한다. **R5 제거는 R7 등록과 같은 커밋**에 넣는다. Bash 쓰기를 아무도 보지 않는 중간 상태를 만들지 않기 위해서다.
- **범위:** 관찰과 판정 대상은 (a) runs.json에 열려 있는 워커 worktree(저장소 무관), (b) 쓰는 쪽 저장소의 linked worktree, (c) 쓰는 쪽 저장소의 main checkout이다. 그 밖의 저장소와 경로는 허용한다.

## 모듈 구조와 인터페이스

```
scripts/hooks/route.py    진입점(main/argv), enabled(), actor(), creates_worktree() [R1–R3, 유지],
                          decide(event, env, deps=None) → R1–R4 + R6, Bash Post/Failure는 observe.observe 위임
scripts/hooks/owners.py   read_open_runs(path) -> list[dict]           # 절대 예외 없음, realpath 정규화
                          main_checkout_of(path, git) -> str | None     # git worktree list --porcelain -z 첫 항목(bare/prunable 건너뜀)
                          owner_of(path, runs, probe, writer_common, writer_main) -> Owner | None
                          # Owner = ("worker", name, wt) | ("main-checkout", None, top) | ("none", None, wt)
                          # runs 포함 여부를 git probe보다 먼저 본다(서브모듈 안 경로도 그 워커로)
scripts/hooks/observe.py  window(now, duration_ms, pending_starts, margin=0.5) -> (start, end) | None
                          mentioned_paths(texts, cwd, home) -> list[str]        # 절대·~·cwd 기준 상대·대입문 우변(D=/x) 토큰 → realpath
                          candidates(paths, runs, writer_wts, writer_main, home) -> list[str]   # 언급된 경로가 속한 관찰 대상 worktree
                          parse_status_v2_z(data: str) -> list[tuple[str, bool]]   # (relpath, deleted)
                          changed(wt, entries, lstat, win, exclude_dirs, git_paths) -> bool
                          observe(event, env, deps) -> dict | None
                          BgStore: add(session, agent, task_id, start, command) / take(session, agent) / gc(now)
                          Deps(now, lstat, realpath, git, runs, bg)    # real_deps()로 실제 구현 주입
```

각 모듈은 `sys.path`에 hooks 디렉터리를 넣어 import한다. 테스트도 같은 방식을 쓴다.

## 판정 규칙

### R4 확장 — PreToolUse Write|Edit|MultiEdit|NotebookEdit (사전 차단, 대상 경로가 입력에 있음)

| 주체 \ 대상 owner | home(자기) | worker(형제) | main-checkout | none | 범위 밖 |
|---|---|---|---|---|---|
| main | 허용 | 허용 | 허용 | 허용 | 허용 |
| sub (메인의 서브에이전트) | 허용 | DENY_SUB(owner) | 허용 (메인의 home) | DENY_SUB(owner) | 허용 |
| worker | 허용 | DENY_WORKER_WRITE(owner) | DENY_WORKER_WRITE(owner) | DENY_WORKER_WRITE(owner) | 허용 |
| worker-sub | 허용 | DENY_SUB(owner) | DENY_SUB(owner) | DENY_SUB(owner) | 허용 |

home은 `probe(cwd)`의 toplevel이다. `cwd` probe가 실패하면 허용한다(기존 fail-open 규칙).

### R7 — PostToolUse / PostToolUseFailure, tool_name Bash, 주체 sub·worker·worker-sub
1. `tool_response.backgroundTaskId`가 있으면 판정하지 않는다. `BgStore.add`로 기록만 한다. 기록은 task id마다 파일 하나이고 `O_EXCL`로 만든다. 다음 판정 때 `take`로 가져가는데, rename으로 소유권을 가져온 뒤 읽고 지운다.
2. `texts` = 이번 명령 원문 + `take`로 가져온 백그라운드 명령들
3. `mentioned_paths`를 구한다. 경로 토큰이 하나도 없거나 모두 home 안이면 **git 호출 없이 종료**한다. 대부분의 명령이 여기서 끝난다.
4. `candidates`를 구한다: 언급된 경로가 속한 관찰 대상 worktree. 쓰는 쪽 저장소의 worktree 목록이 필요할 때만 `git worktree list --porcelain -z`를 1회 호출한다.
5. 창 `window(now, duration_ms, [백그라운드 시작 시각들])`을 구한다. 시작은 `floor(min(now - dur/1000, *starts) - 0.5)`이다. 1초 해상도 파일시스템까지 덮기 위해 내림한다.
6. 후보 w마다 `changed`를 판정한다. 다음 중 하나라도 ctime이 창 안이면 바뀐 것이다.
   - `git -C w status --porcelain=v2 -z --untracked-files=all`의 항목
   - 삭제된 항목은 **가장 가까운 존재하는 조상** 디렉터리의 ctime
   - `git rev-parse --git-path logs/HEAD`와 `--git-path index`의 ctime. index는 `restore`, `checkout -- f`, `stash`를 잡는다.
   
   home 안이나 다른 관찰 대상 worktree 안에 있는 항목(gitignore되지 않은 `.worktrees/x`)은 제외한다. `lstat`을 쓴다.
7. 바뀌었고 언급된 w가 있으면 owner별 OBSERVED 메시지를 `additionalContext`로 보낸다. `hookEventName`은 이벤트에 맞춰 `PostToolUse` 또는 `PostToolUseFailure`로 한다.
8. 매번 `BgStore.gc(now)`로 1시간 지난 기록을 지운다.

### 메시지 (모두 owner 기준으로 분기)
- `HANDOFF` 템플릿:

  ```
  HERDR-HANDOFF
  To the main session: load the herdr-parallel-worktree skill and handle this by its `owner:` line …
  name: …
  repo: …
  owner: <worker name | main-checkout | none>
  goal: …
  branch: …
  steps:
  …
  done: …
  ```
  
- `NOTE_HANDOFF`(R6): "…handle it by the block's `owner:` line (skill step 0, Receiving a handoff)…"
- `deny_sub(owner)`: 기존 DENY_SUB에 owner를 명시한다. owner가 worker이면 "the main session will pass it to worker `<n>`"을 덧붙인다.
- `deny_worker_create(name, home)`: 기존 deny_worker. worktree 생성을 막는다.
- `deny_worker_write(name, home, owner)`: 신규. "그 파일은 네 worktree 밖(owner …)이다. 그 부분은 하지 말고 `## Result`에 HANDOFF로 적어라."
- `observed(who, hits)`: "명령이 `<w>`(owner …)를 바꿨다. 더 바꾸지 말고 멈춰라. 바꾼 경로를 `done:`에 적어라." sub와 worker-sub는 최종 응답 HANDOFF로, worker는 `## Result`로 보고한다.

### 메인 걸러내기 (O9 실측 반영: 셸 가드 대신 python 조기 종료)
- 모든 등록 명령은 `[ "$HERDR_ENV" = 1 ] || exit 0; python3 -S "<route>" <arg>` 하나의 GUARD만 쓴다. JSON 안 셸 이스케이프가 필요 없다.
- 메인이 필요 없는 그룹은 argv를 따로 둔다: `pre-tool-use-write`(Write류 Pre), `post-tool-use-bash`(Bash Post), `post-tool-use-failure`(Bash PostFailure). 이 argv에서는 `route.main`이 **stdin 원본 바이트에서 `"agent_id"`를 찾고, 없고 `HERDR_PW_WORKER`도 없으면 JSON import·파싱 전에 종료**한다. 실측: 1KB 24ms, 1MB 33ms, 10MB 86ms. 셸 가드는 10MB에서 467ms였다.
- 메인이 필요한 `pre-tool-use`(Agent / EnterWorktree / `worktree add`)와 `post-tool-use`(Agent|Task의 NOTE)는 기존대로 처리한다.

## 태스크

모든 태스크는 executing-plans 방식으로 진행한다. ledger를 남기고, RED를 확인한 뒤 GREEN으로 가고, 완료 기준은 증거로 확인한다.

### Task 0: 실측 (완료 2026-10-07, spec §13.5 / 커밋 9022631)
- **T1:** 살아 있는 워커에 "파일을 가리키는 한 줄"로 후속 지시를 보내면(`herdr agent prompt … --wait`) 따르는가. 붙여넣기로 처리되어 거부되는지도 본다.
- **T2:** `working` 상태의 워커에 보내면 어떻게 되는가: 받아들임, 대기열, 거부, 오류 코드. 그리고 `agent wait --until idle --until done` 후 보내는 흐름이 동작하는가.
- **T3:** 워커 claude를 종료하고 resume.md 절차로 재개(`--add-dir BRIEFS` 포함)한 뒤 후속 지시를 보내면 이전 맥락을 유지하는가.
- **O8:** 한 에이전트의 병렬 Bash 호출에서 훅이 동시에 실행되는가(BgStore 설계 확인).
- **O9:** GUARD_NON_MAIN을 1MB 크기 payload에 대해 `sh -c`로 실행할 때의 시간.
- 환경: scratch 저장소에 skill §1~§3 명령으로 테스트 워커를 띄운다(workerArgs, `HERDR_PW_WORKER` export).
- **완료 기준:** spec §13.5에 결과 표가 있다. **T1이 실패하면 중단하고 보고한다**(전달 방식을 다시 설계해야 함). 이 태스크로 만든 워커는 cleanup 절차로 정리하고, 정리가 거절되면 사용자에게 묻는다.

#### 체크포인트 — 실측 결과와 계획 부합 확인 (2026-10-07 사용자 확인 완료)
- 결과: T1·T3 통과. T2는 대기열로 안전하게 처리됨. O8은 동시 실행 확인. O9는 셸 가드의 최악 비용이 큼 → 위 "메인 걸러내기"로 변경. 추가 발견: workspace만 닫힌 워커는 `worktree open`으로 재개해야 하고, `runs.py`에 열린 기록의 위치를 갱신하는 명령이 필요하다(Task 5에 반영).
- T1~T3, O8, O9 결과를 표로 보고한다. 각 결과가 이 계획의 어느 부분을 확인하거나 바꾸는지 대조한다.
  - T1·T2 → deliver.md의 전달 방식
  - T3 → 재개 후 전달
  - O8 → BgStore 설계
  - O9 → 셸 가드 채택 여부
- 계획 수정이 필요하면 이 파일과 spec을 고친 내용을 함께 제시한다.
- 사용자가 확인한 뒤에만 Task 1부터 진행한다.

### Task 1: owners.py (TDD)
- 테스트(`tests/test_owners.py`):
  - `read_open_runs`: 파일 없음, 손상, 리스트 아님, cleaned 혼재, `/var`↔`/private/var` 정규화. 어떤 경우에도 SystemExit가 나지 않아야 한다.
  - `main_checkout_of`: 일반 저장소, `--separate-git-dir`, bare 저장소의 worktree, prunable 항목
  - `owner_of`: 4가지 반환값, 가장 긴 접두사 우선(중첩 worktree), 경로 경계, 형제 worktree 안의 서브모듈 경로 → 그 worker, 다른 저장소의 linked worktree(runs.json에 없으면) → None
  - 실제 git 통합 테스트 1개
- **완료 기준:** 테스트 OK.

### Task 2: R4 확장과 메시지 (route.py, TDD)
- 테스트(`test_route.py`):
  - `R4OwnerMatrixTest`: 위 표의 20칸을 모두 검사한다. 기대 출력은 정확한 메시지 문자열이다.
  - 메시지 테스트: `owner:` 줄 위치, 첫 줄 문구, worker 전달 문구, `deny_worker_write`와 `deny_worker_create` 구분
  - 기존 `SpecMatrixTest`의 R4 행 갱신, R5 행 제거 예정 표시
  
  spec §5.3과 §13.2 표를 대조해서 함께 갱신한다.
- **완료 기준:** OK. 기존 R1~R3·R6 테스트는 변경 없이 통과한다.

### Task 3: observe.py 순수 함수 (TDD)
- 테스트(`tests/test_observe.py`). 리뷰 C절 항목을 모두 포함한다.
  - `parse_status_v2_z`:
    - `1`(필드 8개 + 경로, 경로 안 공백)
    - `2`(필드 9개 + 경로 + **다음 NUL 원래 경로를 소비**, 그 뒤 레코드도 정상 파싱)
    - `u`(필드 10개)
    - `?` 반영, `!` 무시, `#` 헤더 무시
    - 개행과 한글 경로, 빈 출력
    - `.D`/`D.` → deleted
  - `window`: 정상, 누락, 문자열 duration, 백그라운드 시작으로 넓히기, 내림 처리(1초 해상도)
  - `mentioned_paths`: 절대경로, `~`, `../b` 상대(cwd 기준), `D=/w/b` 대입, `--work-tree=/w/b`, 인용부호 안 경로, `/w/ab`는 `/w/a`의 언급이 아님, home 안 경로만 있으면 빈 결과
  - `candidates`: realpath 표기 차이, home 제외, 범위 밖 제외
  - `changed`(lstat 주입):
    - ctime 창 안/밖
    - `cp -p`(mtime은 과거, ctime은 창 안)
    - 삭제 + 부모도 삭제 → 조상
    - logs/HEAD만 변경, index만 변경
    - 중첩 `.worktrees/x` 항목 제외
    - git timeout → False, worktree 디렉터리 없음 → False
  - `BgStore`: add·take·gc, 동시 add 2개 후 take 1회로 둘 다 받음, 손상 파일, 1시간 정리
  - 실제 파일시스템 통합: 임시 저장소 + linked worktree에서 `echo >`, `cp -p`, `git restore`, 커밋을 각각 하고 감지한다.
- **완료 기준:** OK. 통합 테스트가 skip 없이 실행된다.

### Task 4: R7 연결 + R5 제거 + 등록 (한 커밋)
- 테스트:
  - `ObserveDecideTest`(실측 필드 형태 사용):
    - PostToolUse·PostToolUseFailure → `hookEventName` 일치
    - main은 무시
    - sub, worker, worker-sub 각각
    - 언급은 있는데 변화가 없으면 출력 없음, 변화는 있는데 언급이 없으면 출력 없음
    - 백그라운드: 기록만 하고 출력 없음 → 다음 Post에서 귀속
    - 손상된 runs.json·`duration_ms` 누락 → 출력 없음
  - R5 제거 테스트: 서브에이전트의 `cd /w/b && make`가 Pre에서 통과한다(이제 Post가 판정). `DirTargetsTest`는 삭제한다.
  - `test_registration.py`:
    - 새 matcher 목록: PreToolUse Bash `Bash(*worktree add*)` / EnterWorktree|Agent|Task / Write|Edit|MultiEdit|NotebookEdit, PostToolUse Agent|Task / Bash, PostToolUseFailure Bash
    - 모든 그룹이 단일 GUARD + `python3 -S`인지 확인
    - argv 매핑: `pre-tool-use`, `pre-tool-use-write`, `post-tool-use`(Agent|Task), `post-tool-use-bash`, `post-tool-use-failure`
    - parity, `strip_ours`
  - 조기 종료 테스트(실제 프로세스): non-main argv에서 메인 JSON이면 출력이 없고 `json` 모듈을 import하지 않는다(`-X importtime`이나 sys.modules 확인 훅으로 검증). agent_id가 있거나 `HERDR_PW_WORKER`가 있으면 판정까지 간다. 빈 stdin이나 깨진 바이트도 출력 없음.
- 구현: `route.main` argv에 위 5종을 두고, non-main argv는 조기 종료한다. decide를 위임 구조로 바꾸고, `DIR_ARG`와 `dir_targets`를 삭제한다. hooks.json과 manage.py를 갱신한다.
- L2c(`hook_cost.py` 갱신), 목표는 다음과 같다.
  - 메인 Bash Post: python 조기 종료, 1KB 40ms 이하 / 10MB 150ms 이하
  - sub Post, 경로 언급 없음: 80ms 이하
  - sub Post, 언급 1개 + 대형 저장소: 300ms 이하
  - 워커 Bash, 언급 없음: 80ms 이하
- L2(`live_hooks.py`에 추가, C1~C11은 회귀로 유지):
  - C12: sub `echo x > <wt>/f` → OBSERVED(owner none) + HANDOFF
  - C13: sub `sed -i`로 이미 수정된 파일 재수정 → 감지
  - C14: `…; false` → PostToolUseFailure에서 감지
  - C15: sub가 자기 cwd worktree에 쓰기 → 없음
  - C16: worker Write로 형제 worktree → DENY_WORKER_WRITE(owner)
  - C17: worker Bash로 형제 worktree → OBSERVED
  - C18: 메인 Bash → 로그 없음(python 미실행)
  - C19: sub가 `cat <wt>/f`만 실행(읽기) → 없음
- 마지막으로 `manage.py on`으로 사용자 설정을 재등록한다. 실행 전에 `~/.claude/settings.json`을 수정한다는 사실과 백그라운드 경로를 사용자에게 알린다.
- **완료 기준:** 단위 테스트 OK, L2c 4줄 PASS, L2 `0 fail, 0 inconclusive`.

### Task 5: 스킬 문서 (L3 red → green)
- RED: `live_skill.py`에 S4~S6을 먼저 추가하고 실패를 확인한다.
  - S4: owner worker HANDOFF → 메인이 `deliver.md`를 따른다(Read 또는 `herdr agent prompt` 시도). `herdr worktree create`는 시도하지 않는다.
  - S5: owner main-checkout → 사용자에게 묻는다. herdr 명령은 시도하지 않는다.
  - S6: 워커의 `## Result`에 담긴 HANDOFF를 받은 메인 → S4와 같은 처리
  - S1~S3은 회귀로 유지한다.
- GREEN:
  - **SKILL.md 맨 앞 워커 가드:** 자기 worktree 밖의 일은 `## Result`에 HANDOFF(owner 포함)로 적는다.
  - **§0 "Receiving a handoff":** owner로 분기한다(worker → `deliver.md`, main-checkout → 알리고 묻기, none → 새 워커). 확인은 1회다.
  - **step 5:** Result 안의 HANDOFF도 같은 처리로 넘긴다.
  - **Never 목록 정리:** "첫 지시는 `agent prompt`로 보내지 않는다. 후속 지시는 파일 + 한 줄로 보낸다(deliver.md)." T1 결과를 반영한다.
  - **`references/deliver.md` (신규, T1~T3 반영):**
    1. runs.py `show`로 워커를 조회한다.
    2. 열려 있고 살아 있으면: 후속 파일을 `BRIEFS/<name>-followup-<ts>.md`에 쓰고 `finalize-brief.py`로 마무리한다. 작업 중이면 T2 방식대로 기다리고, 한 줄 prompt를 보낸다.
    3. 정리됐거나 종료됐으면 `resume.md` 다음 2를 한다. 세 경우를 구분한다: (a) 워커는 열려 있지만 claude가 종료됨 → 같은 pane에서 재개, (b) workspace는 닫혔지만 worktree는 남음 → `herdr worktree open --cwd <root> --path <wt> --label <name> --no-focus` 후 재개(T3), (c) worktree까지 정리됨 → 기존 resume.md의 재생성 경로.
    - 작업 중이면 `herdr agent wait <name> --until idle --until done --timeout 600000`으로 기다린 뒤 보낸다. 대기가 timeout이면 그냥 보낸다(T2: 현재 작업이 끝난 뒤 대기열로 처리되고 끊기지 않음).
    4. `agent read`로 확인하고 보고한다.
  - **`references/resume.md`:** `agent start` 인자에 `--add-dir "$BRIEFS"`를 추가한다. "workspace만 닫힌 경우 `worktree open`" 경로를 추가한다. "후속 지시는 `deliver.md`로"를 연결한다.
  - **`scripts/runs.py`:** `mark-open`은 지금 cleaned 기록만 다시 연다. 열린 기록의 위치(workspace, pane)를 갱신하는 `relocate --root --name --workspace --pane` 하위 명령을 추가한다(T3에서 발견). `tests/test_runs.py`를 신설해 임시 DATA_DIR로 add, relocate, show를 검증한다. herdr 호출은 PATH에 가짜 herdr를 두어 처리한다.
- **완료 기준:** live_skill S1~S6 PASS를 연속 2회.

### Task 6: 문서·README·회귀
- README 두 개: R5 설명을 삭제하고, 결과 관찰과 owner 전달을 설명한다.
- spec §12.3을 "변화 + 언급" 규칙으로 갱신한다(보류 규칙과 워커 상태 조회 삭제). §7에 알려진 누락을 추가한다.
  - 경로가 명령에 드러나지 않는 쓰기
  - 읽기 명령과 워커의 동시 쓰기가 겹칠 때 생기는 오탐
  - daemon 자식 프로세스(`nohup … &`)의 쓰기
- 버전은 0.5.0을 유지한다(ruling으로 기록).
- 회귀로 L1, L2, L2c, L3를 모두 다시 실행한다.

### Task 7: herdr E2E (사용자와 함께, workerArgs 적용, 신뢰된 scratch)
- **E1:** 워커 A·B를 띄운 뒤 A에게 B의 worktree에 있는 파일을 고치게 한다. 기대: A가 Result에 HANDOFF(owner B)를 남긴다 → 메인이 deliver로 B에게 전달 → B가 수행한다.
- **E2:** B를 정리한 뒤 같은 요청을 한다. 기대: 메인이 B를 재개해 전달하고, B가 맥락을 유지한다.
- **E3:** 워커가 main checkout을 고치려 한다. 기대: 메인이 사용자에게 알리고 묻는다.
- **E4:** 메인의 서브에이전트가 `echo > <B wt>/f`를 실행한다. 기대: OBSERVED → HANDOFF(owner B) → B에게 전달한다.
- 각 기대값의 PASS/FAIL과 관찰 내용을 기록한다. 정리는 cleanup 절차로 하고, 거절되면 사용자에게 묻는다.

### Task 8: 최종 리뷰 → main 병합 → push
- 브랜치 전체를 review-package로 묶어 새 리뷰어(opus)에게 맡긴다. Critical과 Important는 수정 패스 1회로 처리한다(RED→GREEN).
- `git checkout main && git pull --ff-only && git merge design/delegation-routing`을 한다. 병합 결과로 L1을 실행한 뒤 `git push origin main`을 하고 `git branch -d design/delegation-routing`으로 브랜치를 지운다.

## 검증 요약

| 층 | 수단 | 핵심 확인 |
|---|---|---|
| L1 | `test_owners.py`, `test_observe.py`, `test_route.py`, `test_registration.py` | R4 20칸, porcelain 파싱, 언급 추출, 창, ctime, 백그라운드, 가드 실행, parity |
| L2 | `live_hooks.py` C1~C19 | 실제 Claude Code 이벤트 형태로 발동하고, 메시지가 도달하는지 |
| L2c | `hook_cost.py` | 메인 조기 종료 40ms(1KB)·150ms(10MB), 언급 없음 80ms, 언급 있음 300ms |
| L3 | `live_skill.py` S1~S6 (red 먼저) | 메인이 owner별로 올바르게 처리하는지 |
| L4 | E1~E4 | herdr 안에서 전체 흐름 |

**최종 리뷰어 Review Focus**
1. porcelain v2 `-z` 이름 변경과 특수 경로
2. realpath 경계: runs.json, `git worktree list`, 명령 원문, `/var`↔`/private/var`
3. 언급 추출의 오탐과 누락(읽기 명령, 대입문, 상대경로)
4. non-main argv 조기 종료가 메인이 필요한 경로(Agent·EnterWorktree·worktree add·NOTE)를 실수로 막지 않는지
5. BgStore의 동시성과 손상 처리
