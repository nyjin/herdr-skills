# herdr-parallel-worktree: 과업별 위임을 탭으로 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** herdr 안에서 다른 스킬(SDD 등)이 과업마다 서브에이전트를 dispatch하면, 그 일이 역할별 herdr 탭(구현 · 리뷰)으로 가게 한다. 흐름은 메인이 쥐고, 탭끼리 직접 넘기는 것은 브리프가 허가한 고침 → 재리뷰 한 단계뿐이다.

**Architecture:** 훅이 두 시점에 지침 하나(`references/dispatch.md`)를 가리킨다. 다른 스킬을 불러올 때는 안내 한 줄만 붙이고, 세션의 첫 과업 dispatch에서는 prompt를 파일로 저장한 뒤 한 번 거절한다. 브리프의 환경 칸과 완료 시 행동 칸은 `finalize-brief.py`가 옵션으로 만든다. 쓰기 훅(R4)은 브리프 환경 칸의 바깥 경로와 "남의 worktree에 있는 탭"을 런타임에 판정한다. 매핑 파일은 새로 두지 않는다.

**Tech Stack:** Python 3 표준 라이브러리, Claude Code hooks, herdr CLI, git.

**Spec:** 아래 "결정" 절(2026-11-08 사용자 결정). 배경은 논의 브리프 `~/.local/share/herdr-skills/herdr-parallel-worktree/briefs/discuss-sdd-routing-20261108.md`, 이전 설계는 `docs/superpowers/specs/2026-10-20-orchestrator-role-and-worker-tab-design.md`.

## 배경

skills-98 세션(11-02 ~ 11-08)에서 메인이 herdr 안에서 계획 44를 SDD로 돌렸다. 그런데 과업별 구현자 · 리뷰어 dispatch가 모두 Agent 서브에이전트로 갔다(장부의 dispatch 줄 27). SKILL.md 첫머리에 규칙이 있었지만 세션 초반에 한 번 읽혔을 뿐이고, 행동 직전에는 SDD 절차만 있었다. 훅도 worktree 격리 Agent만 막았다.

계획 44 장부를 단계별로 세면 다음과 같다. 이 수치가 D2의 근거다.

| 단계 | 메인이 한 일 |
|---|---|
| 구현 → 리뷰 | 10건 중 7건에서 리뷰 전에 판정 · 질문 · 보완이 들어감. 깨끗하게 바로 넘어간 과업 0/10 |
| 리뷰 → 고침 | 10/10이 고침 라운드를 거침. 판정 최소 11건, 장부로 미룬 사소한 지적 48줄 |
| 고침 → 재리뷰 | 뚜렷한 개입 1건(T6 R31). 기계적 |
| 재리뷰 → 다음 | T8b가 5/5 상한에 걸려 메인이 3건을 보류함 |

## 결정

**이전 결정**
- 역할이 다르면 다른 탭이다. 리뷰어는 구현자 workspace의 다른 탭에 둔다.
- "계획 전체를 워커 하나에" 방식은 안내하지 않는다. 장부는 메인만 쓴다.
- 바깥 경로 (ii): 워커는 브리프 환경 칸에 적힌 바깥 경로에만 쓴다. 자기 레포의 메인 체크아웃은 적혀 있어도 막고, git 밖 경로는 자유롭게 쓴다.
- 인계 요청서는 곧 브리프다. 훅은 지침 하나만 가리킨다. 브리프는 환경 / 지시 / 완료 시 행동(선택) 세 부분이다.

**2026-11-08 결정**
- **D1 강제:** 스킬을 불러올 때는 안내만 하고 거절하지 않는다. 두 경로(Skill 도구, `/이름`)를 모두 잡는다. 세션의 첫 과업 dispatch는 prompt를 저장한 뒤 한 번 거절한다. 안내를 붙일 스킬 목록은 config `dispatchSkills`에 둔다.
- **D2:** 탭끼리 직접 넘기는 것은 고침 → 재리뷰뿐이다. 나머지 단계는 메인을 거친다.
- **D3:** 탭들이 함께 쓰는 파일은 `$BRIEFS/<plan>/`에 둔다.
- **D4:** 역할은 탭 이름 규칙(`<plan>-impl`, `<plan>-rev`)으로 런타임에 찾는다. `report-metadata`는 쓰지 않는다.
- **D5:** 리뷰 탭은 자기 이름으로 띄우고, `runs.json`에는 구현 탭만 기록한다.
- **D6:** 워커를 막는 것은 환경 제약과 충돌뿐이다. 중첩 워커와 worktree 생성, 다른 세션이 일하는 곳에 쓰기(다른 워커의 worktree, 메인 체크아웃, 브리프에 없는 다른 레포), 메인 세션 pane으로 보내기가 여기에 해당한다. 나머지는 자유이고, 브리프 점검용 금지 목록은 만들지 않는다.
- **D7:** 훅 등록 상태를 검사하는 코드는 더하지 않는다. 바뀐 훅은 병합 뒤 `manage.py on`을 한 번 돌려 등록한다.
- **D8:** 시험 흔적은 교훈을 이 문서에 남긴 뒤 지운다(완료).
- **D9:** working · blocked 분기는 추가로 시험하지 않는다. 스킬에 "확인하지 않음"으로 적는다.
- **실행:** 작업을 잘게 나누고 작업마다 검증한다. 서브에이전트로 실행한다.

**작성자 결정 (이의 없음으로 확정)**
- 훅의 거절 문구는 "이어서 진행하라"는 형태로 쓴다.
- 환경 칸과 완료 시 행동 칸은 `finalize-brief.py` 층에서 만든다.
- 메인 통보는 끌어오기로 한다(백그라운드 `agent wait`). 메인 pane에 prompt를 보내는 것은 금지한다.
- 직접 넘기기 문구는 시험 때 쓴 문구를 그대로 쓴다.
- SKILL.md 2단계의 붙여 넣기 기록을 바로잡는다.
- R9 역할 문구에 "브리프가 허가한 단계"를 넣는다.

**D5 근거 정정.** 논의 때 "지금 소유자 판정이 리뷰 탭의 쓰기를 막는다"고 했는데, 틀렸다. `write_target`은 쓰는 쪽 cwd의 worktree 안에 쓰는 것을 `runs.json`을 보기 전에 통과시킨다(`route.py:405-407`). 시험의 리뷰 탭은 Write나 Edit를 시도하지 않아서 드러나지 않았다. 그래서 Task 6에서 "자기 cwd worktree의 주인이 다른 이름이면 막는다"를 더한다. 두 탭이 같은 파일을 고치는 충돌을 막는 일이므로 D6 범위에 들어간다.

## 시험에서 얻은 사실 (2026-11-08)

워커 → 워커 전달 시험을 3회 돌렸다. scratch 레포, `HERDR_SKILLS_DATA_HOME`으로 격리한 데이터, workspace 1개에 구현 탭과 리뷰 탭을 두었다. 시험 흔적은 이 절을 쓴 뒤 지웠다.

| 무엇 | 확인한 것 |
|---|---|
| Skill 도구로 스킬 불러오기 | PreToolUse와 PostToolUse가 모두 걸린다. `tool_name: "Skill"`, `tool_input: {"skill": "superpowers:subagent-driven-development"}` |
| `/이름`으로 스킬 불러오기 | UserPromptSubmit만 걸린다. `prompt`는 `/superpowers:subagent-driven-development <args>` 그대로이고, 스킬 본문은 사용자 메시지로 들어온다. UserPromptSubmit의 `additionalContext`가 모델에 닿는지는 확인하지 않았다(Task 11에서 확인) |
| 한 줄짜리 `herdr agent prompt` | 6/6 모두 `<pasted_content>` 없이 일반 사용자 메시지로 도착했다(메인 → 리뷰 3, 구현 → 리뷰 3). 여러 줄 본문이 붙여 넣기로 간다는 기존 기록과 맞는다 |
| 입력창에 쓰다 만 글이 있는 pane에 `agent prompt` | 쓰다 만 글 뒤에 붙어 한 메시지로 제출된다. 그래서 메인 pane에는 절대 보내지 않는다 |
| 직접 넘기기(고침 → 재리뷰) | 보냄 3/3, 받아 처리함 3/3(재리뷰 모두 APPROVED), 메인 되짚기 3/3 일치, 보내기 전 상태 확인 3/3. R9 역할 문구가 들어간 상태에서는 2/3(2 · 3회차). 리뷰 탭은 구현 탭이 `## Result`를 마치기 10~13초 전에 일을 시작했다 |
| 시간 | 메인 중계 7~24초(세션의 읽기 · 판단 포함, 요청서는 스크립트로 만듦). 직접 넘기기는 상태 확인 → 전송 3~4초, 전송 → working 1초 안 |
| 직접 넘겨도 남는 일 | 구현 탭 결과에 메인이 정할 일이 올라왔다(3회차, 빈 키 처리). 리뷰 탭은 3번 모두 "구현 브리프에 사양이 빠졌다"는 메인용 메모를 남겼다. 직접 넘기기는 메인의 Result 읽기를 없애지 않는다 |
| `report-metadata` | pane id를 먼저 써야 한다(`herdr pane report-metadata <pane> --source <id> --display-agent X`). `--k=v` 형식은 실패한다. 값은 get · list에는 안 나오고 `herdr api snapshot`에만 `display_agent` · `title`로 나온다 |
| 이름으로 찾기 | `herdr agent get <name>`에 `name`이 있고, `tab list`에 `label`이 있다. 구현 탭은 이것만으로 리뷰 탭을 찾았다 |
| 훅 등록 | `~/.claude/settings.json`에 SessionStart가 없었다(등록이 코드보다 뒤처짐). 그래서 실제 환경에서는 R9가 꺼져 있었다. `manage.py status`는 `registered_in_settings: true`만 보고한다 |
| 신뢰 대화상자 | `~/.claude.json` 신뢰 항목이 worktree 경로가 아니라 레포 경로로 남았다. 한 번 누르면 그 레포의 worktree가 모두 통과한다 |
| 시험 방법 | 탭은 `herdr tab create --env HERDR_PW_WORKER=… --env HERDR_SKILLS_DATA_HOME=…`로 만들면 실제 `runs.json`과 섞이지 않는다. `claude --settings <file>`로 탭마다 훅을 더할 수 있다(사용자 설정과 합쳐짐). 메인 통보는 백그라운드 `herdr agent wait`로 충분했다 |
| 기타 | 리뷰 탭이 테스트를 돌리며 만든 `__pycache__`는 Bash 쓰기라 막히지 않았다. 이 환경에는 herdr 플러그인이 없다 |

## Global Constraints

- Python 표준 라이브러리만 쓴다. 단위 테스트(전체): `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -v`. 일부만: 같은 명령에 `-k <이름>`을 붙인다. 저장소 점검: `scripts/check.sh [check ...]`.
- **fail-open:** 예외, git · herdr 오류, 파일 오류는 모두 출력 없음으로 처리한다. 초안을 저장하지 못하면 dispatch를 막지 않는다.
- herdr 밖(`HERDR_ENV != 1`)이거나 `"hooks": "off"`이면 출력하지 않는다.
- `hooks/hooks.json`과 `manage.hook_entries()`는 같은 집합을 등록한다(`test_registration`).
- 스킬 파일(SKILL.md, references, assets, scripts)은 영어로 쓴다(`test_language`). 이 계획은 한국어다.
- 시작 전에 사용자에게 묻지 않는다. `test_no_pause`의 금지어를 쓰지 않는다.
- 판정은 도구 호출과 그 입력으로만 한다. 유일한 예외는 UserPromptSubmit에서 prompt의 첫 토큰이 `/<목록의 스킬 이름>`인지 보는 것이다.
- 경로는 `os.path.realpath`로 정규화하고, 포함 여부는 `owners.inside`(경로 구분자 경계)로 판정한다.
- 아래에 "정확히 이대로"라고 적은 문구는 글자 그대로 쓴다.
- 작업 브랜치는 SDD 작업용 worktree의 브랜치다. 태스크마다 커밋하고 push하지 않는다.
- **테스트 격리:** 단위 테스트는 실제 `~/.local/share/herdr-skills`나 실제 `herdr`를 건드리지 않는다. 기존 `NO_DATA`(`/nonexistent/...`)와 임시 디렉터리를 쓴다.

## 검증 모델

| 층 | 무엇을 증명하나 | 어떻게 | 언제 |
|---|---|---|---|
| L1 단위 | 판정 함수와 스크립트의 입력 → 출력 | `unittest`(`-k`로 작업별, 마지막에 전체) | 모든 작업 |
| L1.5 저장소 점검 | 등록 집합, 훅 실행 경로, 맺음말, 언어 · 금지어, skill spec | `scripts/check.sh <check>` | 등록 · 스크립트 · 문서를 바꾼 작업 |
| L2 실제 Claude Code | 훅 출력이 실제 세션에 닿는지(거절, 초안 저장, 안내 주입) | `tests/live_hooks.py`(가짜 herdr, `--settings`, 격리 데이터) | Task 11 |
| L3 실사용 | herdr 안에서 SDD가 탭으로 흐르는지 | 다음 SDD 계획을 herdr에서 돌릴 때(이 계획 범위 밖) | 병합 후 |

어떤 요구가 검증됐다고 말하려면 아래 표에 적힌 층에서 통과해야 한다. 아래층 통과는 위층의 근거가 되지 않는다.

**결정 → 작업 → 확인하는 테스트**

| 결정 | 작업 | 테스트 |
|---|---|---|
| D1 첫 dispatch 한 번 멈춤 | 1, 11 | `FirstDispatchTest.*`, live `first_dispatch` |
| D1 스킬 불러올 때 안내(Skill 도구) + `dispatchSkills` | 2 | `SkillNoteTest.*`, `RegistrationTest.*` |
| D1 스킬 불러올 때 안내(`/이름`) | 3, 11 | `SlashNoteTest.*`, `EarlyExitTest.test_plain_prompt_stops_before_json`, live `slash_note` |
| 바깥 경로 (ii): 환경 칸 | 4 | `FinalizeTest.*`, `check.sh finalize-brief` |
| 바깥 경로 (ii): 선언 경로 읽기 | 5 | `DeclaredOutsideTest.*` |
| D5 · D6 남의 worktree에 있는 탭 | 6 | `OtherTabsWorktreeTest.*` |
| (ii) · D6 브리프에 없는 다른 레포 | 7 | `OutsidePathTest.*` |
| D6 역할 문구, 메인 pane 금지, 브리프가 허가한 단계 | 8 | `SessionStartTest.test_role_texts` |
| D2 · D3 · D4 · D5 · D9, 끌어오기 통보 | 9 | `DispatchGuideTest.*` |
| 붙여 넣기 기록 정정, `dispatchSkills` 문서, 훅 문서 | 10 | `SkillTextTest.*`, `LanguageTest`, `NoPauseTest`, `check.sh` |
| D7 등록 한 번 | 병합 후 | 병합 후 단계의 `jq` 확인 |

## Review Focus

1. **막지 말아야 할 첫 dispatch.** 첫 dispatch가 검색용(`Explore`, `Plan`, `claude-code-guide`)이거나, 워커 · 서브에이전트 · linked worktree의 plain 세션에서 온 것이면 막지 않고 표시도 남기지 않는다 → Task 1.
2. **두 번째부터는 통과.** 같은 `session_id`의 두 번째 dispatch는 통과한다. resume이나 compact 뒤에도 id가 같으니 다시 막지 않는다 → Task 1.
3. **UserPromptSubmit의 비용.** 이 훅은 모든 prompt에서 뜬다. `/`로 시작하지 않는 prompt는 `json`을 import하지 않고 끝나야 하고, 목록에 없는 `/이름`은 출력이 없어야 한다 → Task 3.
4. **브리프 찾기의 이름 접두 충돌.** 워커 `proj`가 `proj-101-…md`를 자기 브리프로 읽으면 안 된다 → Task 5.
5. **선언 경로 일치.** `/tmp`와 `/private/tmp` 같은 심볼릭 경로를 같게 보고, `/o/out`이 `/o/outside`를 포함한다고 보지 않는다 → Task 5, Task 7.

## 파일 구조

| 파일 | 바뀌는 것 | 작업 |
|---|---|---|
| `skills/herdr-parallel-worktree/scripts/hooks/route.py` | 첫 dispatch 멈춤, 스킬 안내, UserPromptSubmit 조기 종료, R4 확장, 역할 문구 | 1, 2, 3, 6, 7, 8 |
| `skills/herdr-parallel-worktree/scripts/hooks/owners.py` | `brief_files()`, `declared_outside()` | 5 |
| `skills/herdr-parallel-worktree/scripts/finalize-brief.py` | `--role --worktree --branch --outside --then` | 4 |
| `skills/herdr-parallel-worktree/scripts/hooks/manage.py`, `hooks/hooks.json` | PostToolUse matcher에 `Skill`, UserPromptSubmit 그룹 | 2, 3 |
| `skills/herdr-parallel-worktree/references/config.schema.json` | `dispatchSkills` | 2 |
| `skills/herdr-parallel-worktree/references/dispatch.md` (새 파일) | 훅이 가리키는 지침 하나 | 9 |
| `SKILL.md`, `references/brief-filling.md`, `references/deliver.md` | 본문 갱신 | 10 |
| `skills/herdr-parallel-worktree/tests/` | `test_route.py`, `test_registration.py`, `test_owners.py`, 새 `test_finalize.py` · `test_dispatch_guide.py` · `test_skill_text.py`, `live_hooks.py` | 각 작업 |
| `scripts/check.sh` | `check_hooks`, `check_finalize_brief` | 3, 4 |
| `.claude-plugin/plugin.json` | 버전 0.8.0 | 12 |

---

### Task 1: 세션의 첫 과업 dispatch를 한 번 멈추고 prompt를 저장

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/hooks/route.py` (`decide()`의 PreToolUse 분기, 새 함수)
- Test: `skills/herdr-parallel-worktree/tests/test_route.py` (새 `FirstDispatchTest`)

**Interfaces:**
- Produces:
  - `route.SKILL_DIR: str`: 스킬 디렉터리 절대경로(`route.py`에서 세 단계 위)
  - `route.GUIDE: str = os.path.join(SKILL_DIR, "references", "dispatch.md")`. 파일은 Task 9가 만든다.
  - `route.READ_ONLY_AGENTS = ("Explore", "Plan", "claude-code-guide")`
  - `class route.DispatchStore(path: str)`: `.seen(session_id: str) -> bool`, `.mark(session_id: str) -> None`. 세션마다 파일 하나를 두고 절대 예외를 던지지 않는다. 기본 위치는 `tempfile.gettempdir()/herdr-pw-dispatch`.
  - `route.save_draft(env, session_id: str, tool_input: dict, now=time.time) -> str | None`: `$DATA_DIR/briefs/dispatch-<session_id[:8]>-<YYYYmmdd-HHMMSS>.md`에 쓰고 경로를 돌려준다. 실패하면 None. 파일 내용은 `# Dispatch draft`, `- subagent_type: …`, `- model: …`, `- description: …` 줄, 그다음 `## Prompt`와 prompt 원문이다.
  - `route.deny_first_dispatch(draft: str) -> str`
  - `route.decide(..., store=None, save=None)`: None이면 실제 구현을 쓴다.

거절 문구(정확히 이대로, `{draft}`와 `{GUIDE}`만 채움):
```
Inside herdr, the user installed these hooks so that a task handed to another agent runs as a herdr tab they can watch, not as a hidden subagent. Nothing is lost: this dispatch (description, model and prompt) is saved at {draft}. Read {GUIDE} and start the tab with that file as the brief's instructions, then carry on with the user's request from where you were. Do not ask the user first, and do not suggest turning the hooks off. This happens once per session: a search or a question you meant for a subagent can be sent again unchanged.
```

- [ ] **Step 1: 실패하는 테스트 작성** (`FirstDispatchTest`; `set` 기반 가짜 store와 고정 경로를 돌려주는 가짜 save를 `decide`에 넘긴다)
  - `test_first_task_dispatch_is_stopped_once`: `MAIN_ENV`, cwd `/r`, `Agent(subagent_type="general-purpose", description="Task 3", prompt="Implement Task 3")`.
    - 첫 호출은 deny이고, 사유가 위 문구에 `{draft}="/d/briefs/dispatch-s-1.md"`를 넣은 것과 같다.
    - 같은 `session_id`로 다시 부르면 `None`이다.
  - `test_saved_draft_keeps_the_prompt_verbatim`: 실제 `save_draft`에 임시 `HERDR_SKILLS_DATA_HOME`을 준다. 파일에 여러 줄 prompt(백틱, `$VAR` 포함)가 글자 그대로 있고 `subagent_type`, `model`, `description` 줄이 있다. 파일 이름이 `dispatch-[0-9A-Za-z_-]{1,8}-\d{8}-\d{6}\.md`와 맞는다.
  - `test_read_only_agents_pass_without_marking`: `READ_ONLY_AGENTS` 각각에 대해 결과는 `None`이고 store가 비어 있다.
  - `test_others_pass`: `WORKER_ENV`, `sub=True`, main 세션의 cwd `/w/a`(linked worktree) 모두 `None`이고 store가 비어 있다.
  - `test_unsaved_draft_does_not_block`: save가 `None`을 돌려주면 결과는 `None`이고 store가 비어 있다.
  - `test_worktree_isolation_keeps_its_own_deny`: `isolation="worktree"`인 main Agent는 지금처럼 `DENY_MAIN_AGENT`를 받는다.
  - `test_store_survives_bad_dir`: 쓸 수 없는 경로(`/nonexistent/x`)의 `DispatchStore`는 `seen`이 False, `mark`가 예외 없이 끝난다.
- [ ] **Step 2: 실패 확인.** Run: `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -k FirstDispatch -v` → FAIL(`DispatchStore` 없음)
- [ ] **Step 3: 구현.** `decide()`의 PreToolUse에서 `creates_worktree` 분기 다음에 넣는다.
  - 조건: `tool in ("Agent", "Task")`, `who == "main"`, `args.get("subagent_type") not in READ_ONLY_AGENTS`, cwd가 main checkout(`probe(cwd)`의 `[0] == [1]`, SessionStart와 같은 규칙).
  - 이미 표시된 세션이면 None. 아니면 `save(...)`를 부른다. 경로가 나오면 `mark`한 뒤 deny, None이면 None.
- [ ] **Step 4: 검증**
  - `python3 -m unittest discover -s skills/herdr-parallel-worktree/tests -k FirstDispatch -v` → 7개 모두 OK
  - 전체 단위 테스트 → OK. 기존 테스트는 `NO_DATA` 때문에 저장이 실패하므로 결과가 바뀌지 않아야 한다. 바뀐 테스트가 있으면 이 작업의 결함이다.
  - `scripts/check.sh hooks` → OK
- [ ] **Step 5: 커밋.** `feat: stop a session's first task dispatch once and save it as a tab brief draft`

### Task 2: Skill 도구로 불러올 때 지침 안내 + `dispatchSkills` 설정

**Files:**
- Modify: `route.py`, `scripts/hooks/manage.py` (`hook_entries`), `hooks/hooks.json`, `references/config.schema.json`
- Test: `tests/test_route.py` (새 `SkillNoteTest`), `tests/test_registration.py`

**Interfaces:**
- Consumes: `route.GUIDE` (Task 1)
- Produces:
  - `route.DISPATCH_SKILLS = ("superpowers:subagent-driven-development", "superpowers:dispatching-parallel-agents")`
  - `route.read_config(env) -> dict`: 오류가 나면 `{}`. `enabled()`가 이것을 쓴다.
  - `route.dispatch_skills(cfg: dict) -> tuple[str, ...]`: `cfg["dispatchSkills"]`가 문자열 배열이면 그 튜플, 아니면 `DISPATCH_SKILLS`.
  - `route.note_dispatch_skill(skill: str) -> str`
  - `route.decide(..., cfg=None)`: None이면 `read_config(env)`.
  - `hook_entries()`와 `hooks.json`: PostToolUse 첫 그룹의 matcher를 `"Agent|Task|EnterWorktree|ExitWorktree|Skill"`로 바꾼다.
  - config 키 `dispatchSkills`: 문자열 배열, 기본값은 위 두 이름. 스키마에 `"type": "array"`, `"items": {"type": "string"}`, `"default"`, 설명 한 줄. `additionalProperties: false`는 유지한다.

안내 문구(정확히 이대로):
```
Inside herdr, {skill} hands each task to an agent; here each of those agents runs as a herdr tab the user can watch. Before the first dispatch, read {GUIDE}.
```

- [ ] **Step 1: 실패하는 테스트 작성**
  - `SkillNoteTest.test_skill_tool_load_adds_note`: main 세션 PostToolUse `Skill`, `tool_input={"skill": "superpowers:subagent-driven-development"}` → `hookEventName == "PostToolUse"`, `additionalContext == note_dispatch_skill("superpowers:subagent-driven-development")`, 그 안에 `route.GUIDE`.
  - `test_other_skill_gets_nothing`: `{"skill": "superpowers:brainstorming"}` → `None`.
  - `test_worker_and_subagent_get_nothing`: 같은 입력을 `WORKER_ENV`나 `sub=True`로 주면 `None`.
  - `test_config_list_replaces_default`: `dispatch_skills({"dispatchSkills": ["my:skill"]}) == ("my:skill",)`. `{"dispatchSkills": "x"}`, `{"dispatchSkills": [1]}`, `{}`는 `DISPATCH_SKILLS`. `decide(..., cfg={"dispatchSkills": ["my:skill"]})`에서는 `my:skill`만 안내한다.
  - `test_read_config_never_raises`: 없는 경로, 깨진 JSON, 배열 JSON이면 `{}`.
  - `RegistrationTest`: `ARGS`의 PostToolUse 키를 새 matcher로 바꾸고, `test_expected_matchers`의 PostToolUse 목록을 `["Agent|Task|EnterWorktree|ExitWorktree|Skill", "Bash"]`로 바꾼다.
- [ ] **Step 2: 실패 확인.** `-k SkillNote`와 `-k Registration` → FAIL
- [ ] **Step 3: 구현.** `decide()`의 PostToolUse에 `tool == "Skill" and who == "main"` 분기를 더한다(NOTE_HANDOFF 분기와 별개). `hooks.json`과 `hook_entries()`를 같이 고친다.
- [ ] **Step 4: 검증**
  - `-k SkillNote` → OK, `-k Registration` → OK
  - 전체 단위 테스트 → OK
  - `scripts/check.sh hooks` → OK
  - `jq -e '.properties.dispatchSkills.default | length == 2' skills/herdr-parallel-worktree/references/config.schema.json` → true
- [ ] **Step 5: 커밋.** `feat: point the main session to the dispatch guide when it loads a dispatching skill`

### Task 3: `/이름`으로 불러올 때 지침 안내 (UserPromptSubmit)

**Files:**
- Modify: `route.py` (조기 종료 블록, `ALL_ARGS`, `EVENT_OF_ARG`, `decide()`), `manage.py`, `hooks/hooks.json`, `scripts/check.sh` (`check_hooks`)
- Test: `tests/test_route.py` (새 `SlashNoteTest`, `EarlyExitTest` 확장), `tests/test_registration.py`

**Interfaces:**
- Consumes: `route.dispatch_skills`, `route.note_dispatch_skill`, `route.read_config` (Task 2)
- Produces:
  - `route.ALL_ARGS`에 `"user-prompt-submit"`를 더하고 `EVENT_OF_ARG["user-prompt-submit"] = "UserPromptSubmit"`. `NON_MAIN_ARGS`는 그대로 둔다.
  - `hook_entries()`와 `hooks.json`에 `"UserPromptSubmit": [group(None, "user-prompt-submit")]`
  - `route.slash_skill(prompt: str) -> str | None`: 앞 공백을 뺀 prompt가 `/`로 시작하면 첫 토큰에서 `/`를 뗀 이름, 아니면 None

- [ ] **Step 1: 실패하는 테스트 작성**
  - `SlashNoteTest.test_slash_prompt_adds_note`: `{"hook_event_name": "UserPromptSubmit", "session_id": "s", "cwd": "/r", "prompt": "/superpowers:subagent-driven-development go"}`, `MAIN_ENV` → `hookEventName == "UserPromptSubmit"`, `additionalContext == note_dispatch_skill("superpowers:subagent-driven-development")`
  - `test_other_or_plain_prompt_gets_nothing`: `"/superpowers:brainstorming"`, `"hello /superpowers:subagent-driven-development"`, `""` → `None`
  - `test_worker_gets_nothing`: 같은 slash prompt를 `WORKER_ENV`로 → `None`
  - `test_slash_skill`: `slash_skill("  /a:b c") == "a:b"`, `slash_skill("/a") == "a"`, `slash_skill("a /b") is None`, `slash_skill("/") is None`
  - `EarlyExitTest.test_plain_prompt_stops_before_json`: `run_route("user-prompt-submit", '{"prompt": "hello"}')` → 출력 `""`, `json` import 없음. `'{"prompt": "/superpowers:subagent-driven-development"}'` → `json` import 있음.
  - `RegistrationTest`: `ARGS`에 `("UserPromptSubmit", None): "user-prompt-submit"`. `test_expected_matchers`에 `[g.get("matcher") for g in self.plugin["UserPromptSubmit"]] == [None]`.
- [ ] **Step 2: 실패 확인.** `-k SlashNote`, `-k EarlyExit`, `-k Registration` → FAIL
- [ ] **Step 3: 구현.**
  - 맨 위 조기 종료 블록: 인자가 `user-prompt-submit`이면 원시 입력을 읽고, `re.search(rb'"prompt"\s*:\s*"\s*/', raw)`가 없으면 `sys.exit(0)`.
  - `decide()`: `hook == "UserPromptSubmit"`이고 `who == "main"`이면 `slash_skill(event.get("prompt") or "")`가 목록에 있을 때 안내를 돌려준다.
  - `check.sh check_hooks`: jq 조건에 `.hooks.UserPromptSubmit`를 더하고, `HERDR_ENV=1`에서 `{"prompt":"hello"}`를 넣으면 출력이 빈지 한 줄로 확인한다.
- [ ] **Step 4: 검증**
  - `-k SlashNote`, `-k EarlyExit`, `-k Registration` → OK
  - 전체 단위 테스트 → OK
  - `scripts/check.sh hooks` → OK
  - 직접 실행: `echo '{"prompt":"hello"}' | HERDR_ENV=1 HERDR_SKILLS_DATA_HOME=/nonexistent python3 -S skills/herdr-parallel-worktree/scripts/hooks/route.py user-prompt-submit` → 출력 없음
- [ ] **Step 5: 커밋.** `feat: point the main session to the dispatch guide when the user types a dispatching skill`

### Task 4: 브리프의 환경 칸과 완료 시 행동 칸 (`finalize-brief.py`)

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/finalize-brief.py`, `scripts/check.sh` (`check_finalize_brief`)
- Create: `skills/herdr-parallel-worktree/tests/test_finalize.py` (`FinalizeTest`)

**Interfaces:**
- Produces:
  - CLI: `finalize-brief.py BRIEF [--role TEXT] [--worktree PATH] [--branch NAME] [--outside PATH REASON]... [--then FILE]` (`--outside`는 `nargs=2`, `action="append"`). 옵션이 없으면 지금과 똑같이 동작한다.
  - 환경 칸 형식(정확히 이대로). 준 옵션의 줄만 쓰고, `--branch`가 없으면 괄호를 뺀다.
    ```
    ## Environment

    - Role: <role>
    - Worktree: `<path>` (branch `<branch>`)
    - Outside path: `<absolute path>` — <reason>
    ```
  - 위치: `## Environment`는 첫 `# ` 줄 바로 다음(없으면 맨 앞), `## On completion`(`--then` 파일 내용)은 맺음말(TAIL) 바로 앞. 같은 제목의 칸이 이미 있으면 바꿔 쓴다.
  - 검사: `--outside` 경로가 절대경로가 아니거나, `--then` 파일이 없거나 비었으면 exit 1이고 파일을 건드리지 않는다.
  - Task 5가 이 형식을 읽는다.

- [ ] **Step 1: 실패하는 테스트 작성** (`FinalizeTest`, 스크립트를 subprocess로 실행)
  - `test_environment_follows_the_title`: `# [t] x\n\n## Goal\ndone\n` 브리프에 `--role reviewer --worktree /w/a --branch b --outside /o/data "shared output"` → 제목 바로 다음 칸이 위 형식과 글자까지 같다.
  - `test_rerun_replaces_sections`: 같은 옵션과 `--then`으로 두 번 돌려도 `## Environment`와 `## On completion`이 하나씩만 있다.
  - `test_on_completion_sits_before_the_closing_paragraph`: 마지막 줄은 TAIL이고, 그 바로 앞 칸이 `## On completion`이며 내용이 `--then` 파일과 같다.
  - `test_relative_outside_path_fails`: `--outside rel "x"` → exit 1, 파일 그대로.
  - `test_missing_or_empty_then_fails`: 없는 파일, 빈 파일 → exit 1, 파일 그대로.
  - `test_no_options_keeps_todays_output`: 옵션 없이 돌린 결과가 지금 스크립트의 결과와 같다(구현 전에 기대 출력을 테스트에 적어 둔다).
- [ ] **Step 2: 실패 확인.** `-k Finalize` → FAIL
- [ ] **Step 3: 구현.** 칸 교체는 레벨 2 heading부터 다음 같은 레벨 이하 heading 전까지를 한 칸으로 본다(기존 `check()`와 같은 규칙). 순서: 주석 제거 → 기존 TAIL 제거 → 칸 넣기 → `check()` → TAIL 붙이기.
- [ ] **Step 4: 검증**
  - `-k Finalize` → 6개 OK
  - 전체 단위 테스트 → OK
  - `scripts/check.sh finalize-brief` → OK. 이 점검에 "`--outside`를 주면 `## Environment` 칸이 생긴다"는 한 줄을 더한다.
- [ ] **Step 5: 커밋.** `feat: let finalize-brief write the brief's environment and completion sections`

### Task 5: 브리프에 선언된 바깥 경로 읽기 (`owners.py`)

**Files:**
- Modify: `skills/herdr-parallel-worktree/scripts/hooks/owners.py`
- Test: `tests/test_owners.py` (새 `DeclaredOutsideTest`)

**Interfaces:**
- Consumes: Task 4의 환경 칸 형식
- Produces:
  - `owners.brief_files(briefs_dir: str, name: str) -> list[str]`: 파일 이름이 `^{re.escape(name)}-(followup-)?\d{8}-\d{6}\.md$`와 맞는 것만, 정렬해서.
  - `owners.declared_outside(briefs_dir: str, name: str, realpath=os.path.realpath) -> list[str]`: 위 파일들의 `## Environment` 칸에 있는 ``^- Outside path: `([^`]+)` `` 줄의 경로를 realpath로. 절대 예외를 던지지 않는다.

- [ ] **Step 1: 실패하는 테스트 작성**
  - `test_brief_files_ignore_longer_names`: 임시 디렉터리에 `proj-20261108-120000.md`, `proj-followup-20261108-130000.md`, `proj-101-20261108-120000.md`, `proj-20261108-120000-ref.md` → `brief_files(d, "proj")`는 앞의 둘뿐이다.
  - `test_round_trip_with_finalize`: `finalize-brief.py --outside <tmp>/o "r"`로 만든 `<d>/w1-20261108-120000.md` → `declared_outside(d, "w1") == [os.path.realpath(<tmp>/o)]`. macOS에서 `tempfile.gettempdir()` 아래 경로면 `/private/...` realpath와 같아야 한다.
  - `test_outside_lines_elsewhere_are_ignored`: `## Environment` 칸 밖(예: `## Steps`)의 `- Outside path:` 줄은 읽지 않는다.
  - `test_never_raises`: 없는 디렉터리, 읽을 수 없는 파일 → `[]`.
- [ ] **Step 2: 실패 확인.** `-k DeclaredOutside` → FAIL
- [ ] **Step 3: 구현.** 표준 라이브러리 `re`, `os`만 쓴다.
- [ ] **Step 4: 검증.** `-k DeclaredOutside` → 4개 OK. 전체 단위 테스트 → OK.
- [ ] **Step 5: 커밋.** `feat: read the outside paths a worker's briefs declare`

### Task 6: 남의 worktree에 있는 탭은 쓰지 못하게 (R4 확장 a)

**Files:**
- Modify: `route.py` (`write_target`, 새 문구 함수)
- Test: `tests/test_route.py` (새 `OtherTabsWorktreeTest`)

**Interfaces:**
- Consumes: `owners.run_owning` (기존)
- Produces: `route.deny_not_your_worktree(name: str, home: str, owner: str) -> str`

규칙: `HERDR_PW_WORKER=name`인 쪽(worker, worker-sub)의 cwd worktree가 열린 run의 worktree이고 그 run의 이름이 `name`과 다르면, 그 안에 Write · Edit하는 것을 막는다. main과 main의 서브에이전트는 지금과 같다.

문구(정확히 이대로):
```
You are herdr tab `{name}`, working in `{home}`, which belongs to `{owner}`. Only `{owner}` writes here, so two tabs never edit the same files. Do not change files here, and do not retry another way; put what should change in your `## Result` or your verdict file instead.
```

- [ ] **Step 1: 실패하는 테스트 작성** (runs `[{"name": "p-impl", "worktree": "/w/a", "state": "open"}]`)
  - `test_reviewer_tab_cannot_write_in_the_implementers_worktree`: env `HERDR_PW_WORKER=p-rev`, cwd `/w/a`, `Write /w/a/x.py` → deny, 사유가 `deny_not_your_worktree("p-rev", "/w/a", "p-impl")`와 같다.
  - `test_its_subagent_too`: 같은 입력에 `sub=True` → deny.
  - `test_owner_tab_writes_its_worktree`: env `p-impl` → `None`.
  - `test_unrecorded_worktree_unchanged`: runs 없이 env `p-rev`, cwd `/w/a` → `None`(지금 동작 유지).
- [ ] **Step 2: 실패 확인.** `-k OtherTabsWorktree` → FAIL
- [ ] **Step 3: 구현.** `write_target`이 "home 안이면 통과"하기 직전에 `owners.run_owning(home_top, runs)`로 판정한다.
- [ ] **Step 4: 검증.** `-k OtherTabsWorktree` → 4개 OK. 전체 단위 테스트 → OK. `SpecMatrixTest` 칸이 바뀌면 이 규칙에 해당하는 칸인지 확인하고 맞게 갱신한다.
- [ ] **Step 5: 커밋.** `feat: keep a tab from writing in another tab's worktree`

### Task 7: 브리프에 없는 다른 레포에는 쓰지 못하게 (R4 확장 b)

**Files:**
- Modify: `route.py` (`write_target`, `decide(..., declared=None)`, 새 함수)
- Test: `tests/test_route.py` (새 `OutsidePathTest`; `FAKE`에 `"/o": ("/o/.git", "/o/.git", "/o")` 추가)

**Interfaces:**
- Consumes: `owners.declared_outside` (Task 5)
- Produces:
  - `route.briefs_dir(env) -> str`: `$DATA_DIR/briefs`
  - `route.deny_undeclared(name: str, top: str) -> str`
  - `route.decide(..., declared=None)`: `declared(name) -> list[str]`. None이면 `owners.declared_outside(briefs_dir(env), name)`.

규칙(`HERDR_PW_WORKER`가 있는 쪽만):
  - `owner_of`가 None이고 `probe(target)`가 git checkout을 찾으면(다른 레포), 대상이 `declared(name)` 경로 중 하나 안에 있을 때만 통과한다. 아니면 `deny_undeclared`.
  - git 밖 경로는 지금처럼 통과한다.
  - 자기 레포의 메인 체크아웃은 선언돼 있어도 지금처럼 막는다.

문구(정확히 이대로):
```
You are herdr tab `{name}`. `{top}` is another repository, and your brief does not list this path under outside paths; another session may be working there. Do not write it, and do not retry another way. Finish the rest of your task, and say in your `## Result` which path you needed and why, so the orchestrator can add it to your brief.
```

- [ ] **Step 1: 실패하는 테스트 작성** (워커 env `w1`, cwd `/w/b`)
  - `test_undeclared_other_repo_is_denied`: `declared=lambda n: []`, `Write /o/f` → deny, 사유가 `deny_undeclared("w1", "/o")`와 같다.
  - `test_declared_other_repo_passes_on_boundaries`: `declared=lambda n: ["/o/out"]` → `/o/out/f`는 `None`, `/o/outside/f`는 deny.
  - `test_outside_git_stays_free`: `/x/f` → `None`.
  - `test_declared_main_checkout_still_denied`: `declared=lambda n: ["/r"]`, `Write /r/f` → deny(main-checkout 문구).
  - `test_worker_subagent_follows_the_same_rules`: 위 deny 경우에 `sub=True` → deny.
  - `test_main_session_and_its_subagents_unchanged`: `MAIN_ENV`로 `/o/f` → `None`, `sub=True`도 `None`.
- [ ] **Step 2: 실패 확인.** `-k OutsidePath` → FAIL
- [ ] **Step 3: 구현.** `own is None`일 때만 `probe(path)`를 한 번 더 부른다(흔하지 않은 경우라 git 호출이 늘어도 괜찮다).
- [ ] **Step 4: 검증.** `-k OutsidePath` → 6개 OK. 전체 단위 테스트 → OK. `SpecMatrixTest`에서 워커가 다른 레포에 쓰는 칸이 `None`에서 deny로 바뀌면 이 규칙에 따른 변경으로 갱신한다.
- [ ] **Step 5: 커밋.** `feat: keep tabs out of repositories their brief does not list`

### Task 8: 역할 문구 (워커, 메인)

**Files:**
- Modify: `route.py` (`role_worker`, `ROLE_MAIN`)
- Test: `tests/test_route.py` (`SessionStartTest.test_role_texts`)

**Interfaces:** 다른 작업에 넘길 것 없음.

`role_worker(name)` (정확히 이대로):
```
You are herdr worker `{name}`. Your brief says where you work and what you may touch outside it. Do not start workers or create worktrees: herdr runs you in a tab, and nested workers break it. Do not write where another session works (another worker's worktree, the main checkout, or a repository your brief does not list); anything needed there goes back to the orchestrator in your `## Result`, as a HERDR-HANDOFF block when it is code work. Never send anything to the orchestrator's pane: it is the user's conversation. A step your brief tells you to take, such as sending a re-review request to another tab, is yours to take. If your brief asks for something this rules out, say so in your `## Result` instead of doing it.
```
`ROLE_MAIN`: 지금 문장의 `that dispatch is a worker` 바로 뒤에 ` (see the skill's references/dispatch.md)`를 넣는다. 나머지는 그대로 둔다.

- [ ] **Step 1: 실패하는 테스트 작성.** `test_role_texts`를 갱신한다.
  - 워커 문구: `` `w1` ``, `HERDR-HANDOFF`, `"orchestrator's pane"`, `"brief tells you to take"`, `"nested workers"`가 있다.
  - 메인 문구: `"references/dispatch.md"`가 있고, 기존 검사(`even a single ticket`, `route.SKILL`, `that dispatch is a worker`)는 그대로 통과한다.
  - 두 문구 모두 `confirm`과 `` `! ``가 없다(기존 검사).
- [ ] **Step 2: 실패 확인.** `-k SessionStart` → FAIL
- [ ] **Step 3: 구현.** 문구만 바꾼다.
- [ ] **Step 4: 검증.** `-k SessionStart` → OK. 전체 단위 테스트 → OK. `scripts/check.sh hooks` → OK(세션 시작 역할 출력 검사 포함).
- [ ] **Step 5: 커밋.** `feat: tell workers what conflicts to avoid and that brief-authorized steps are theirs`

### Task 9: 지침 하나 (`references/dispatch.md`)

**Files:**
- Create: `skills/herdr-parallel-worktree/references/dispatch.md`, `skills/herdr-parallel-worktree/tests/test_dispatch_guide.py` (`DispatchGuideTest`)

**Interfaces:**
- Consumes: `route.GUIDE` 경로(Task 1), `finalize-brief.py` 옵션(Task 4), 이름 규칙(D4)

지침에 담을 것(영어, 이 순서, 각 항목은 짧게):
1. **When this applies:** 첫 dispatch에서 훅이 멈췄을 때, 스킬을 불러올 때 안내가 떴을 때, herdr 안에서 다른 스킬이 과업마다 agent를 dispatch할 때. 탐색 · 조사 서브에이전트는 그대로 서브에이전트다.
2. **Tabs per role:**
   - 계획 하나에 workspace 하나를 둔다. SKILL.md 1~3단계로 만들고, 이름은 `<plan>`이다.
   - 구현 탭은 `<plan>-impl`이고 `runs.py add`로 기록한다.
   - 리뷰 탭은 `<plan>-rev`이고 같은 workspace에 `worker-pane.py --name <plan>-rev --since <now>`로 띄운다. 기록하지 않는다. 재리뷰도 리뷰 탭이 한다.
   - 다른 스킬이 새 agent(예: 더 강한 모델)를 요구하면, 같은 workspace에 새 탭(`<plan>-impl2`)을 그 모델(`--model`)로 띄운다.
   - 과업은 계획 브랜치에 쌓이고, 다음 과업은 같은 구현 탭에 후속으로 보낸다(`deliver.md`).
   - 리뷰 탭은 구현 탭의 worktree에 쓰지 못한다(훅이 막는다).
3. **Files:** 보고서, 리뷰 꾸러미, 판정은 `$BRIEFS/<plan>/`에 둔다. 다른 스킬의 장부는 제자리에 두고 오케스트레이터만 쓴다.
4. **The brief:**
   - 지시 칸은 저장된 dispatch 초안이나 다른 스킬의 prompt를 그대로 넣는다. 템플릿은 쓰지 않는다.
   - `finalize-brief.py`에 `--role`, `--worktree`, `--branch`, `--outside "$BRIEFS/<plan>" "shared review folder"`를 주고, 다른 레포에 쓸 일이 있으면 그 경로와 이유를 `--outside`로 더한다.
   - `--then`은 고침 → 재리뷰를 넘길 때만 쓴다. 완료 시 행동이 없으면 오케스트레이터에 보고하는 것이 기본이다.
5. **The one direct hop:** 고침 → 재리뷰만 직접 넘긴다. `--then` 파일 예시를 그대로 싣는다.
   - 커밋한 뒤 `$BRIEFS/<plan>/rereview-request-<n>.md`(범위, 지적 파일, 사양, 테스트 명령, 판정 경로)를 쓴다.
   - `herdr agent get <plan>-rev | jq -r .result.agent.agent_status`로 상태를 확인한다. idle · done · working이면 `herdr agent prompt <plan>-rev "[<plan>-impl] Re-review request: read <file> and follow it." --wait --until working --timeout 15000`로 보낸다. blocked이면 보내지 않는다.
   - `## Result`에 `Handoff` 줄을 남기고, 재리뷰를 기다리지 않는다.
6. **Waiting:**
   - 오케스트레이터는 백그라운드로 `herdr agent wait <name> --until idle --until done --until blocked --timeout <ms>`를 돌린다(Claude Code는 run_in_background로, 끝나면 알림이 온다).
   - `## Result`를 읽고 `herdr agent get`과 파일로 맞춰 본다. 고침 라운드는 오케스트레이터가 센다.
   - 오케스트레이터 pane에는 절대 보내지 않는다. 쓰다 만 사용자 글과 함께 제출된다(시험에서 확인).
7. **Not verified:** 리뷰 탭이 working일 때 직접 넘기면 대기열에 들어갈 것으로 보인다(오케스트레이터 → 워커는 시험됨). blocked이면 herdr가 `agent_blocked`로 거절한다(도움말 기준).

- [ ] **Step 1: 실패하는 테스트 작성** (`DispatchGuideTest`)
  - `test_guide_is_where_the_hooks_point`: `os.path.isfile(route.GUIDE)`
  - `test_names_the_contract`: 본문에 `<plan>-impl`, `<plan>-rev`, `$BRIEFS/<plan>/`, `finalize-brief.py`, `--outside`, `--then`, `--role`, `agent wait`, `run_in_background`, `Not verified`, `agent_blocked`가 모두 있다.
  - `test_only_one_direct_hop`: `herdr agent prompt`가 나오는 줄은 모두 `Re-review request`를 담는다(다른 직접 전송 예시가 없다).
  - `test_finalize_options_in_the_guide_exist`: 지침에 나오는 `--role`, `--worktree`, `--branch`, `--outside`, `--then`이 `finalize-brief.py --help` 출력에 모두 있다.
- [ ] **Step 2: 실패 확인.** `-k DispatchGuide` → FAIL(파일 없음)
- [ ] **Step 3: 지침을 쓴다.**
- [ ] **Step 4: 검증.** `-k DispatchGuide` → 4개 OK. `-k Language`, `-k NoPause` → OK. 전체 단위 테스트 → OK.
- [ ] **Step 5: 커밋.** `docs: one guide for running per-task dispatch as tabs`

### Task 10: 스킬 본문 (SKILL.md, brief-filling.md, deliver.md)

**Files:**
- Modify: `SKILL.md`, `references/brief-filling.md`, `references/deliver.md`
- Create: `skills/herdr-parallel-worktree/tests/test_skill_text.py` (`SkillTextTest`)

**Interfaces:**
- Consumes: Task 1~9의 키, 옵션, 지침 경로

SKILL.md:
- 첫 단락의 "When another skill says to dispatch …" 문장이 `references/dispatch.md`를 가리키게 한다.
- Configuration 표에 `dispatchSkills` 행을 넣고, jq 검사의 키 목록을 `["workerArgs", "hooks", "dispatchSkills"]`로 바꾸고 배열 검사를 더한다.
- Hooks 절:
  - 두 항목을 더한다: 스킬을 불러올 때 안내(Skill 도구와 `/이름` 두 경로), 첫 과업 dispatch를 한 번 멈춤(초안 저장, 검색 agent 예외).
  - "Writing outside" 항목에 브리프에 없는 다른 레포와 남의 worktree에 있는 탭을 더한다.
  - 역할 항목을 새 워커 문구에 맞춘다.
- 2단계 첫 항목: 여러 줄 본문은 붙여 넣은 내용으로 도착하고, 한 줄짜리는 일반 사용자 메시지로 도착한다(시험됨). 그래서 뒤에 오는 지시는 파일과 한 줄로 보낸다.
- Never 목록의 `Send the first instructions with agent prompt` 항목 근거를 같은 내용으로 바꾼다.

`brief-filling.md`:
- 첫 표에 "Environment and On completion sections | the skill | `finalize-brief.py` options" 행을 더한다.
- 4절에 옵션 예시를 넣고, 두 제목은 스크립트가 쓰므로 템플릿에 두지 않는다고 적는다.

`deliver.md` 5단계: 한 줄짜리 안내는 일반 메시지로 도착한다(시험됨)는 한 문장을 더한다.

- [ ] **Step 1: 실패하는 테스트 작성** (`SkillTextTest`)
  - `test_config_keys_match_the_schema`: SKILL.md jq 검사의 키 목록(`keys - [...]` 안)과 `config.schema.json`의 `properties` 키 집합이 같다.
  - `test_config_table_lists_every_key`: Configuration 표에 스키마의 키가 모두 있다.
  - `test_skill_points_to_the_guide`: SKILL.md에 `references/dispatch.md`가 있다.
  - `test_hooks_section_names_both_load_paths`: Hooks 절에 `Skill`과 `UserPromptSubmit`이 있다.
  - `test_finalize_options_documented`: `brief-filling.md`에 `--outside`와 `--then`이 있다.
- [ ] **Step 2: 실패 확인.** `-k SkillText` → FAIL
- [ ] **Step 3: 본문을 고친다.**
- [ ] **Step 4: 검증.** `-k SkillText` → 5개 OK. `-k Language`, `-k NoPause` → OK. 전체 단위 테스트 → OK. `scripts/check.sh skill-spec names readme manifests` → OK(`gh skill`이 없으면 skip은 허용).
- [ ] **Step 5: 커밋.** `docs: document the dispatch hooks, brief sections and the one-line prompt finding`

### Task 11: 실제 Claude Code로 확인 (L2)

**Files:**
- Modify: `skills/herdr-parallel-worktree/tests/live_hooks.py`

**Interfaces:**
- Consumes: Task 1~3의 훅

- [ ] **Step 1: 두 검사를 더한다.** 기존 방식(가짜 herdr, `--settings`로 `hook_entries` 등록, 격리 데이터 디렉터리, 훅 로그)을 그대로 쓴다.
  - `first_dispatch`: "general-purpose 서브에이전트에게 `echo hi`를 시켜라"는 prompt를 준다.
    - PASS 조건: 훅 로그에 첫 Agent PreToolUse의 deny가 있다. 격리 데이터의 `briefs/dispatch-*.md`에 그 prompt가 들어 있다. 같은 세션에서 다시 보낸 dispatch에는 deny가 없다.
    - 모델이 dispatch를 시도하지 않았으면 INCONCLUSIVE.
  - `slash_note`: 이 검사에서만 Skill 도구를 허용하고 `claude -p "/superpowers:subagent-driven-development Reply only with the path of any guide you were told to read."`를 돌린다.
    - PASS 조건: 훅 로그에 UserPromptSubmit 출력이 있고, 답에 `dispatch.md`가 있다.
    - 로그만 있고 답에 없으면 INCONCLUSIVE. superpowers 플러그인이 없는 환경이면 SKIP.
- [ ] **Step 2: 검증.** Run: `python3 skills/herdr-parallel-worktree/tests/live_hooks.py --model sonnet` → 기존 검사와 새 검사 모두 PASS. INCONCLUSIVE면 한 번 더 돌린다. 결과 출력을 보고서 파일에 붙인다.
- [ ] **Step 3: 커밋.** `test: live-check the first-dispatch stop and the slash-load note`

### Task 12: 버전과 마지막 확인

**Files:**
- Modify: `.claude-plugin/plugin.json`

- [ ] **Step 1:** `"version"`을 `"0.8.0"`으로 올린다.
- [ ] **Step 2: 검증.**
  - 전체 단위 테스트 → OK
  - `scripts/check.sh` → 모든 점검 OK(`gh skill`이 없으면 skip 허용)
  - `git log --oneline <시작 커밋>..HEAD` → 작업마다 커밋 하나 이상
- [ ] **Step 3: 커밋.** `chore: bump to 0.8.0`

## 병합 후 (사용자 확인 뒤)

- **D7 등록, 한 번:** 설치본(`~/.claude/skills/herdr-parallel-worktree`)이 메인 체크아웃을 가리키므로, 병합한 뒤에 한 번 실행한다. `~/.claude/settings.json`을 고친다는 것과 백업 경로를 사용자에게 알린다.

  Run: `python3 ~/.claude/skills/herdr-parallel-worktree/scripts/hooks/manage.py on --skill-dir ~/.claude/skills/herdr-parallel-worktree`

  확인: `jq '.hooks | keys' ~/.claude/settings.json`에 `SessionStart`와 `UserPromptSubmit`이 있고, PostToolUse matcher에 `Skill`이 있다.
- **L3 첫 실사용에서 볼 것:**
  - 첫 dispatch에서 탭으로 자연스럽게 넘어가는가(사용자에게 묻지 않고 이어 가는가).
  - 리뷰 탭이 쓰려다 막히는 일이 있는가.
  - 구현 탭이 고침 → 재리뷰를 넘기고, 메인이 라운드를 놓치지 않는가.
