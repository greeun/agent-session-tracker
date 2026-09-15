# agent-session-tracker

로컬 코딩 에이전트 세션을 **상태(작업중/대기/유휴/종료/완료) 추적과 함께** 브라우징·검색·재개·내보내기·백업하는 도구입니다. Claude Code, OpenAI Codex, ChatGPT 데스크톱 앱의 세션을 한 목록에서 함께 다룹니다. 터미널에서 `ast`를 실행하면 curses TUI가 열리고, 파이프나 리다이렉트로 넘기거나 스크립트에서 호출하면 표 형식 목록을 출력합니다.

Claude Code만 추적하던 [`claude-session-tracker`](https://github.com/greeun/claude-session-tracker)(`cst`)의 포크입니다. 에이전트 CLI마다 `AgentSpec` 어댑터 하나가 공통 세션 모델에 연결되므로, 어느 에이전트가 만든 세션이든 모든 명령이 동일하게 동작하고 **AGENT** 열이 출처를 알려 줍니다. 원본이 `claude-sessions`에 더했던 기능은 그대로 유지합니다: `~/.claude/sessions/<pid>.json` 라이브 프로세스 레지스트리를 이용한 STATUS 컬럼, Claude Code 라이프사이클 훅을 이용한 정밀 오버레이, 사용자 주도 "done(완료)" 플래그, fzf 스타일 필터링. **Python stdlib만 사용 — 외부 의존성 없음, Python 3.10+.**

---

## 왜 필요한가

Claude Code는 모든 대화를 `~/.claude/projects/` 아래 `.jsonl` 트랜스크립트로 저장합니다. 수백 개 세션이 쌓이면 다음 질문들이 어려워집니다:

- "지금 실제로 돌고 있는 세션은 어떤 거지?"
- "**내 입력을 기다리는** 세션은 어떤 거지?" (권한 결정 등)
- "이미 끝낸 건 어떻게 표시해 두지?"
- "2주 전에 인증 마이그레이션 세팅하던 세션 어디 갔지?"
- "그 작업을 Claude Code에서 했던가, Codex에서 했던가, ChatGPT에서 물어봤던가?"

`ast`가 한 화면에서 다 해결합니다. Codex는 세션을 `~/.codex/sessions/` 아래에
자체 형식으로 저장하고, ChatGPT 데스크톱 앱도 대화를 같은 위치에 저장합니다.
그래서 통합 브라우저가 없으면 두 군데를 각각 뒤져야 합니다.

---

## 설치

```bash
# 1. 저장소 클론 (위치 자유, ~/.claude/skills/ 권장)
git clone <this-repo> ~/.claude/skills/agent-session-tracker

# 2. 실행 권한 + PATH 심볼릭 링크
chmod +x ~/.claude/skills/agent-session-tracker/tracker.py
mkdir -p ~/.local/bin
ln -sf ~/.claude/skills/agent-session-tracker/tracker.py ~/.local/bin/ast

# 3. 확인
ast --version
# agent-session-tracker v1.3.0

# 4. (선택) 토큰 0짜리 done!/undone! 프롬프트 훅 + 상태 정밀 레이어 설치
ast install-hook
```

`~/.local/bin`이 `PATH`에 포함돼 있어야 합니다. Python 3.10+ 필요.

### 이미 `cst`를 쓰고 있다면

두 도구는 나란히 설치되며 `ast`는 `cst`의 파일을 건드리지 않습니다. 데이터
홈이 `~/.ast`와 `~/.cst`로 분리돼 있으므로, 한쪽에서 ✓ done으로 표시한 세션이
다른 쪽에 반영되지는 않습니다. 다만 `ast`는 첫 실행 때 `~/.cst/state.json`을
`~/.ast/`로 한 번 복사하므로 기존 완료 표시와 표시 설정을 그대로 이어받습니다.
원본은 `cst`가 계속 사용하므로 옮기지 않고 복사만 합니다. 훅 항목도
`ast prompt-hook`과 `cst prompt-hook`으로 구분되어 공존할 수 있지만, 둘 다
설치하면 같은 이벤트를 두 도구가 각자의 홈에 기록하므로 하나만 설치하기를
권장합니다.

### 제거

```bash
# 1. Claude Code 설정에서 훅 제거 (다른 훅은 보존)
ast uninstall-hook

# 2. ast 심볼릭 링크 제거
rm ~/.local/bin/ast

# 3. (선택) 캐시 + done 플래그 오버레이 제거
rm -rf ~/.ast

# 4. (선택) 클론한 저장소 제거
rm -rf ~/.claude/skills/agent-session-tracker
```

`uninstall-hook`은 `~/.claude/settings.json`에서 ast 항목만 골라 제거합니다 — 다른 도구(`csm` 등)의 훅은 그대로 유지됩니다. `~/.claude/projects/`의 `.jsonl` 트랜스크립트는 제거에 **절대** 영향받지 않습니다.

---

## 빠른 시작

```bash
ast                           # 터미널에서는 TUI, 파이프·리다이렉트에서는 표 형식 목록
ast list                      # 항상 표 형식: # + ST + LAST + SESSION + MSGS + MESSAGE + PROJECT
ast --tui                     # tty가 없어도 TUI를 강제 (ast pick과 동일)
ast live                      # 지금 실행중인 Claude Code 프로세스만
ast search "인증 리팩토링"     # 모든 세션 트랜스크립트 본문 검색
ast done <id>                 # 세션을 done으로 표시
ast done --filter "문자열" -y  # 매칭 세션 일괄 done (TUI Ctrl-A+d와 동일)
ast export <id>               # 트랜스크립트를 ./<id>.md로 출력
ast stats                     # 요약 (프로젝트·상태 분포)
ast list --sort msgs          # 컬럼 정렬 (time|status|msgs|message|project; --reverse로 방향 반전)
ast list --origin user        # 사용자가 시작한 세션만 (--origin agent는 SDK가 생성한 것만)
ast list --agent chatgpt      # 특정 에이전트의 세션만 (all|claude|codex|chatgpt; TUI `a` 키로 순환)
ast jobs                      # agent-view 백그라운드 세션 (claude --bg)
ast --skip-perm --tui         # 재개 시 --dangerously-skip-permissions 자동 적용
ast --theme light --tui       # TUI 색 테마 지정(auto|dark|light; `t`/`T`로 실시간 토글)
```

---

## 상태 글리프

`ST` 컬럼에 1칸 글리프로 표시. `classify_status()`의 해결 순서: **`✓` done이 항상 우선**; 그 외에는 **죽은** 프로세스는 `○` ended(백그라운드/agent-view 잡이면 마지막으로 저장된 상태); **살아있는** 프로세스는 훅 **오버레이**가 있으면 그것, 없으면 라이브 **레지스트리**(`busy`→`●`, `waiting`→`!`, `idle`→`◦`)로 해결, 살아있지만 신호 없으면 `●`로 폴백. 즉 liveness가 활성 상태를 게이트 — `done > (죽음⇒ended) > 오버레이 > 레지스트리 > ●`.

| 글리프 | 라벨 | 의미 |
|:---:|:---|:---|
| **●** | working (작업중) | Claude가 현재 출력을 생성하는 중. |
| **!** | waiting (대기중) | Claude가 당신의 입력 또는 권한 결정을 기다리는 중 — 시간이 새는 곳. Claude Code 레지스트리에서 기본값으로 감지 (`status: "waiting"`); `ast install-hook`는 정밀 오버레이를 추가. |
| **◦** | idle (유휴) | 턴이 끝났고 프로세스는 아직 살아 있음. |
| **○** | ended (종료됨) | 프로세스가 없음 (정상 종료 또는 등록된 적 없음). 트랜스크립트는 그대로 읽을 수 있음. |
| **✓** | done (완료) | 사용자가 명시적으로 끝났다고 표시. TUI의 `D`/`d`/`Ctrl-D`, `ast done <id>`, 또는 `done!` 프롬프트 훅. `~/.ast/state.json`에 영구 저장. |

상태는 **매 명령 실행마다 새로 계산**됩니다 — 백그라운드 데몬 없음. TUI는 기본 10초 간격으로 자동 재스캔합니다 (`i` 키로 변경/끔).

**자기 치유:** 훅 오버레이가 설치된 상태에서 `waiting`/`working`을 기록했는데 레지스트리가 더 최신 `idle` 이벤트를 보고하면, 오래된 오버레이는 덮어쓰여지고 글리프가 `◦`로 정정됩니다 — 고착된 `!`가 남지 않도록.

---

## 멀티 에이전트: Codex CLI와 ChatGPT 앱 세션

`ast`는 Claude 전용이 아닙니다. `tracker.py`는 에이전트 CLI마다
`AgentSpec` 하나를 `AGENTS`에 등록하고(데이터 루트, 트랜스크립트 탐색, 공통
`Turn` 스트림으로의 파싱, 재개 명령, 실행 감지, 지원 기능 집합), 그 위의
로더·캐시·상태 판정·CLI·TUI는 에이전트를 구분하지 않습니다. 모든 행의
**AGENT** 열이 어느 CLI가 만든 세션인지 보여 주고, `--agent`와 TUI `a` 키로
뷰를 좁힙니다.

| | claude | codex |
|:--|:--|:--|
| 트랜스크립트 | `~/.claude/projects/**/*.jsonl` | `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<시각>-<uuid>.jsonl` (기본 `~/.codex`; 서브에이전트 rollout은 `subagents/`처럼 숨김) |
| list / search / show / export / TUI / done / rm | ✓ | ✓ |
| 재개 (`Enter`, `ast resume`) | `claude --resume <id>` | `codex resume <uuid>` (권한 생략 → `--dangerously-bypass-approvals-and-sandbox`) |
| 실행 상태 | pid 레지스트리 + 훅 오버레이 | `thread-writer-locks/<uuid>.lock`의 flock 탐지: 잠겨 있으면 실행 중; rollout이 90초 이내에 갱신되었으면 `●`, 아니면 `◦`. codex는 `!` 대기를 감지할 수 없음 |
| 생성 주체 (`--origin`) | `entrypoint` cli 대 `sdk-*` | `source` cli / vscode → user; exec / mcp / subagent → agent |
| 재배치 (`ast relocate`) | 트랜스크립트를 `projects/<인코딩된 새 cwd>/`로 이동 | 기록된 cwd만 제자리에서 재작성 — rollout 경로에는 시작 날짜만 담기므로 파일을 옮길 필요가 없음. `--keep-original`은 무시하지 않고 거부함(사본을 놓을 새 위치가 없어, 그대로 진행하면 보존하라고 지정한 파일 자체를 재작성하게 됨) |
| 백업 / 복원 | 아카이브의 `projects/…` 아래에 저장 | 같은 아카이브의 `codex/…` 아래에 저장되며, 복원 시 각자의 데이터 루트로 되돌아감 |
| 서브에이전트 (`ast subagents`) | 트랜스크립트 옆의 `subagents/*.jsonl` | `parent_thread_id`가 이 스레드를 가리키는 rollout(codex의 guardian·subagent 스레드) |
| attach / jobs / bg / hooks | ✓ | ✗ — codex에 대응 기능이 없는 Claude Code 전용 기능 (`not supported for codex sessions`) |

codex의 대화는 rollout의 `response_item`/`message` 레코드 중 role이 `user`
또는 `assistant`인 것이며, `developer` 레코드와 codex가 user 역할로 주입하는
래퍼(`<environment_context>`, `# AGENTS.md instructions` 등)는 제외하므로
MESSAGE 열과 트랜스크립트에는 사람이 입력한 내용만 보입니다. codex 세션
삭제는 rollout 파일만 지웁니다(codex의 sqlite 색인은 누락 파일을 허용하며,
정식 경로는 `codex delete <id>`). 재배치는 `session_meta`, 모든
`turn_context`, `world_state` 스냅샷, 그리고 이전 경로와 정확히 일치하는
`workspace_roots` 항목의 cwd를 재작성하며, 메시지 본문은 건드리지 않습니다.
프롬프트 안에 적힌 경로는 메타데이터가 아니라 내용이기 때문입니다. 다음
어댑터는 Gemini CLI입니다.

### ChatGPT 데스크톱 앱

ChatGPT 데스크톱 앱(`/Applications/ChatGPT.app`, 번들 ID `com.openai.codex`)은
codex의 스레드 저장소를 그대로 사용합니다. 앱에서 나눈 대화는
`$CODEX_HOME/sessions` 아래에 codex 형식의 일반 rollout으로 저장됩니다. `ast`는
이 스레드를 별도의 **`chatgpt`** 에이전트로 표시하므로, `--agent chatgpt`나
TUI `a` 키로 codex 작업과 나누어 볼 수 있습니다.

구분 기준은 스레드를 만든 앱이 아니라, 스레드에 기록된 cwd입니다.

| 기록된 cwd | 에이전트 |
|:--|:--|
| `~/Documents/Codex/<날짜>/<slug>`: 프로젝트 없이 시작한 대화 | `chatgpt` |
| `$CODEX_HOME/.chatgpt-projects/<프로젝트 ID>`: ChatGPT 프로젝트 안의 대화 | `chatgpt` |
| 그 밖의 경로(앱에서 실제 저장소를 열고 작업한 경우 포함) | `codex` |

rollout의 `originator` 필드는 구분 기준으로 쓸 수 없습니다. 앱 빌드에 따라
값이 바뀌었고(`Codex Desktop` → `codex_work_desktop`), 앱에서 저장소를 열고
작업할 때에도 같은 값이 기록되기 때문입니다. 표시 이름을 제외한 나머지는 모두
codex와 같습니다. 파싱, 재개(`codex resume <uuid>`), flock 기반 실행 감지,
재배치, 서브에이전트, 백업이 codex 코드로 처리되며, 백업 멤버도 `codex/…`
아래에 저장되므로 이전 빌드로도 복원할 수 있습니다. 표시 이름은 색인을 읽을
때마다 다시 계산되므로, 업그레이드한 뒤에 재색인할 필요가 없습니다.
chatgpt.com(웹·모바일)에만 있는 대화는 디스크에 rollout이 없으므로 목록에
나타나지 않습니다.

---

## CLI 레퍼런스

### 최상위 플래그

| 플래그 | 효과 |
|---|---|
| `-V`, `--version` | 버전 출력 후 종료 |
| `--tui` | TUI 실행 (ast pick과 동일) |
| `--skip-perm` | 재개 시(TUI 또는 `resume`) `--dangerously-skip-permissions`를 자동으로 `claude`에 전달. 없으면 TUI에서 재개마다 확인 모달이 뜸. |
| `--hide-done` | TUI를 `✓` done 세션을 숨긴 상태로 시작 (TUI에서 `H`로 토글) |
| `--theme auto\|dark\|light` | TUI 색 테마. `auto`는 `COLORFGBG` 감지, 실패 시 dark. `t`/`T`로 실시간 토글·저장. |

### `ast list` — 기본 테이블 뷰

```bash
ast list [--limit 30] [--cwd PREFIX] [--days N]
         [--status working|waiting|idle|ended|done|active]
         [--sort time|status|msgs|message|project] [--reverse]
         [--origin all|user|agent] [--agent all|claude|codex|chatgpt] [--json]
```

```
agent-session-tracker v1.3.0
  #  ST  AGENT    LAST ACTIVITY     SESSION   MSGS  MESSAGE                   PROJECT
  1  ●   claude   2026-05-24 01:17  960faaa8   261  claude-sessions 는…       ~/.claude/skills
  2  !   claude   2026-05-24 01:16  06d116f7    34  proceed? (y/N)            ~/project/url-shortener
  3  ◦   codex    2026-05-24 01:15  019cb053    12  실패건을 해결하라.        ~/project/url-shortener
  4  ✓   chatgpt  2026-05-24 01:15  01a07c61     4  서비스기획의 역할은?      ~/Documents/Codex/2026-05-24/new-chat
  5  ○   claude   2026-05-23 21:24  afbd9e28   241  pnpm 적용 되어 있는가?    ~/project/url-shortener
```

- 번호는 1부터, 1000개 이상 세션은 자동으로 컬럼 폭 확장
- `--status active`는 `working`의 하위 호환 별칭
- 조합 가능: `--cwd ~/project --status waiting --days 7`
- **정렬:** `--sort time|status|msgs|message|project` (기본 `time`, 최신순). `--reverse`로
  방향 반전. `status`는 working→waiting→idle→ended→done 순; `message`는 첫 사용자
  메시지 텍스트 기준 오름차순; 동점은 항상 최신순으로 깨짐. 명시적 `--sort`는
  일회성이고, `--sort` 없으면 저장된 TUI 정렬 설정을 사용.
  정렬은 `--limit` **이전**에 적용되어 선택된 순서의 상위 N개를 자름.
- **생성 주체:** `--origin all|user|agent` (기본 `all`). 트랜스크립트의
  `entrypoint` 필드로 누가 세션을 시작했는지 구분한다. `user`는 터미널에서
  직접 시작한 세션(`cli` — agent-view `bg` 잡도 사람이 발행했으므로 포함),
  `agent`는 SDK가 생성한 세션(`sdk-py`/`sdk-cli`/`sdk-ts`: 보안 리뷰 훅,
  `claude -p` 스크립트, 각종 도구)으로, 목록을 뒤덮기 쉬운 쪽이다.
  `entrypoint`가 없거나 알 수 없는 값이면 `user`로 취급해, 근거 없이 세션을
  감추지 않는다. 명시적 `--origin`은 일회성이고, 플래그가 없으면 저장된 TUI
  설정(`f`/`F`)을 사용하며, 필터가 걸린 상태는 요약 줄에 `[origin:user]`로
  표시된다. `ast search`도 같은 플래그를 지원.
- **에이전트:** `--agent all|claude|codex|chatgpt` (기본 `all`). 특정 에이전트의
  세션만 보여 준다(`chatgpt`는 ChatGPT 데스크톱 앱 대화이며, 위 설명 참고). 명시적 `--agent`는 일회성이고, 플래그가 없으면 TUI `a` 키가
  마지막으로 저장한 뷰를 사용하며, 요약 줄에 `[agent:codex]`로 표시된다.
  `ast search`와 `ast pick`도 같은 플래그를 지원.
- **`--json`** — 테이블 대신 기계가 읽는 JSON으로 출력
  (cst.app macOS 컴패니언이 소비하는 계약). 각 세션에 `entrypoint`, `origin`,
  `agent` 필드가 포함된다.

### `ast pick` / `--tui` — 인터랙티브 TUI

```bash
ast pick [--cwd PREFIX] [--days N] [--agent all|claude|codex|chatgpt]
ast --tui            # 동일
```

실제 TTY가 필요합니다. 에이전트의 비대화식 Bash 호출에서는 실행 불가.

### `ast search "<쿼리>"` — 본문 전체 검색

```bash
ast search "nextjs|remix" --limit 10 -i --cwd ~/project
```

- `|` = OR. `-i` / `--ignore-case` = 대소문자 무시
- 세션별 최대 3개 매칭 스니펫을 상태 글리프 + 8자 id와 함께 출력

### `ast show <id>` — 트랜스크립트 출력

```bash
ast show 960faaa8 --max-chars 500 --with-subagents
ast show 960faaa8 --head-chars 4000        # 거대 세션의 빠른 헤드 미리보기
```

헤더에 **Status**, cwd, 시작/마지막 타임스탬프, 메시지 수, 서브에이전트 수가 표시됩니다.

- `--max-chars N`은 메시지별 자르기, `--head-chars N`은 **전체** 출력 총량을
  제한하고 파일 읽기를 조기 중단 (0 = 무제한) — 수백 MB 트랜스크립트에서
  cst.app이 쓰는 고속 미리보기 경로.

### `ast export <id>` — 트랜스크립트를 파일로 출력

```bash
ast export 960faaa8                       # ./960faaa8….md 생성
ast export 960faaa8 --format txt           # ./960faaa8….txt 생성
ast export 960faaa8 --out ~/exports/       # 디렉터리에 <id>.md 생성
ast export 960faaa8 --out ~/exports/x.md   # 정확한 경로로 생성
```

포맷: `md` (기본, 역할 헤더 포함) · `txt` (평문). `--out`은 디렉터리/파일 경로 모두 허용.

### `ast resume <id>` — `cd + claude --resume` 명령 출력

```bash
ast resume 960faaa8 --print-only | bash
ast --skip-perm resume 960faaa8 --print-only | bash   # skip-perm 플래그 포함
ast resume 960faaa8 --spawn                # 실제로 새 터미널에서 열기/attach
```

`--spawn`은 명령 출력 대신 세션을 직접 엽니다 — TUI `Enter`와 같은 로직
(라이브 세션은 기존 창 포커스, 백그라운드 잡은 `claude attach`, 그 외에는
새 터미널 창에서 `claude --resume`). cst.app이 사용.

`--spawn`과 `ast open`은 터미널 앱을 `$TERM_PROGRAM`에서 고릅니다.
`--terminal NAME`으로 이를 덮어쓸 수 있습니다 (`wezterm` · `iterm` ·
`ghostty` · `kitty` · `alacritty` · `terminal`) — cst.app 같은 GUI 호출자는
`$TERM_PROGRAM`이 없어 지정하지 않으면 항상 Terminal.app으로 폴백합니다.
알 수 없는 이름이거나 해당 CLI가 설치돼 있지 않으면 역시 Terminal.app으로
폴백합니다.

```bash
ast resume 960faaa8 --spawn --terminal wezterm
```

### `ast open <id>` — 세션 폴더를 새 터미널에서 열기

```bash
ast open 960faaa8                      # 세션의 cwd에서 일반 셸 실행
ast open 960faaa8 --terminal wezterm   # 터미널 앱 지정
```

TUI `o` 키의 CLI 버전. 세션에 기록된 작업 디렉터리에서 새 터미널 창을 일반
셸로 엽니다 — `claude` 명령은 실행하지 않으므로 재개(resume)나 attach는
일어나지 않습니다. cst.app이 사용.

### `ast done <id>` / `ast undone <id>` — done 플래그

```bash
ast done 06d116f7      # ✓ Marked done
ast done 06d116f7 9c01a2b3          # 여러 ID 한 번에
ast undone 06d116f7    # ✓ Cleared done
```

일괄 모드 — TUI의 "`/` 필터 → `Ctrl-A` → `d`" 흐름을 명령 한 번으로.
`--filter`는 `세션ID + cwd + 첫 사용자 메시지`에 대한 대소문자 무시 부분
문자열 매칭(TUI 필터와 동일). 이미 done인 세션은 제외되고, ● working
세션은 `--force` 없이는 건너뛴다:

```bash
ast done --filter "heyhey"                 # 매칭 목록 출력 → 확인 → 마킹
ast done --filter "heyhey" -y              # 확인 생략 (스크립트용)
ast done --filter "버그" --days 7 --status ended
ast done --filter "x" --cwd ~/project/old  # cwd 접두어로 범위 제한
```

비대화형 호출은 `-y/--yes`를 명시해야 하며, 없으면 확인 프롬프트에서
멈추는 대신 거부한다.

### `ast live [--all]` — 라이브 프로세스 레지스트리

```bash
ast live          # kill -0 응답하는 PID만
ast live --all    # 죽은 PID(유령 레지스트리 항목)까지 포함
```

### `ast backup` / `ast restore` — 오래된 세션 아카이빙, 또는 지정한 세션 이동

```bash
ast backup --days 90 --dry-run
ast backup --days 90 --delete -y
ast backup --before 2026-01-01 --cwd ~/project/old --out /tmp/old.tar.gz
ast backup 01a0a576 --out ~/Desktop/chat.tar.gz -y        # 세션 1건, 날짜 무관
ast backup --filter "학습 앱 기획" --out ~/Desktop/chat.tar.gz -y
ast restore ~/.ast/backups/sessions-20260524.tar.gz --on-conflict rename -y
```

대상을 고르는 방식은 두 가지입니다. id도 `--filter`도 지정하지 않으면 예전과
같은 정리용 명령으로, 최종 활동이 기준일보다 오래된 세션을 담습니다. 세션을
지정하면(id 접두어, `--filter`, 또는 둘 다) 이동용 명령이 되어, 아무리 최근
세션이라도 지정한 것만 담아 다른 컴퓨터에서 `restore`할 수 있게 합니다. 어느
쪽이든 각 세션의 하위 전사본(claude `subagents/*.jsonl` + `.meta.json`, codex
하위 롤아웃)이 함께 들어가고, codex / ChatGPT 앱 스레드는 `session_index.jsonl`에
기록된 제목을 함께 가져가서 복원 뒤에도 같은 이름으로 표시됩니다.

`backup` 옵션:

| 플래그 | 의미 |
|---|---|
| `ID …` | 날짜와 무관하게 아카이브할 세션 id 접두어 (없거나 여러 개에 걸치면 오류) |
| `--filter TEXT` | id·cwd·첫 사용자 메시지에 TEXT가 포함된 세션도 아카이브 (대소문자 무시) |
| `--days N` / `--older-than N` | 최종 활동이 N일보다 **오래된** 세션을 아카이브 (기본: id·`--filter`·`--days`·`--before` 모두 생략 시 90일). `ast list --days`와 반대 의미 |
| `--before YYYY-MM-DD` | 특정 날짜 이전 세션을 아카이브 (`--days`보다 우선). id / `--filter`와 함께 쓰면 그 선택을 다시 좁힘 |
| `--cwd PREFIX` | 해당 cwd 아래 세션으로 제한 |
| `--out PATH` | 아카이브 경로 (기본: `~/.ast/backups/sessions-<timestamp>.tar.gz`) |
| `--delete` | 성공적으로 아카이브된 원본 제거 |
| `--force` | 일부 파일 아카이브 실패해도 `--delete` 강행 |
| `--dry-run` | 미리보기 (변경 없음) |
| `-y` / `--yes` | 확인 프롬프트 건너뛰기 |

`restore` 충돌 정책: `skip`(기본) · `overwrite` · `rename` (`<id>.restored-<ts>.jsonl`로 저장).

#### codex / ChatGPT 앱 스레드를 다른 컴퓨터에서 복원할 때

롤아웃 파일을 복사하는 것만으로는 ChatGPT 데스크톱 앱(그리고 `codex resume` 선택 화면)에 그 대화가 나타나지 않습니다. codex는 상태 DB(`$CODEX_HOME/state_<n>.sqlite`)에서 스레드 목록을 읽고, 그 DB가 이미 있으면 sessions 폴더를 다시 훑지 않습니다. 또 롤아웃에 기록된 cwd는 원본 컴퓨터의 `/Users/<user>/.codex/.chatgpt-projects/<id>`라서, 사용자 이름이 다른 컴퓨터의 프로젝트 폴더와 맞지 않습니다. 그래서 `restore`는 codex 롤아웃을 쓴 뒤 두 단계를 더 수행합니다.

1. **cwd를 이 컴퓨터 기준으로 이동.** manifest의 `source`(백업한 컴퓨터의 home과 `CODEX_HOME`)를 현재 값으로 바꿔 codex가 cwd를 기록한 모든 자리에 반영합니다. 프로젝트 대화는 `$CODEX_HOME/.chatgpt-projects/<id>` 아래로, 프로젝트 없는 대화는 `~/Documents/Codex/…` 아래로 옮겨집니다. `source`가 없는 아카이브(v1.2.0)는 이 두 경로의 모양으로 추정합니다. `--keep-cwd`로 끌 수 있습니다.
2. **codex 상태 DB에 행 등록.** 행이 없는 복원 스레드마다 `codex archive <id>` 뒤 `codex unarchive <id>`를 실행해 codex가 롤아웃에서 행을 다시 만들게 합니다. 부모와 함께 보관 처리된 하위 스레드는 다시 unarchive하고, manifest의 `thread_name`으로 빈 `name`을 채웁니다. `--no-register`로 끌 수 있습니다. `codex`가 PATH에 없으면 실행할 명령을 대신 출력하고, 상태 DB가 아직 없으면 codex가 다음 실행 때 롤아웃에서 직접 만듭니다.

실제 `~/.codex`에 복원할 때는 ChatGPT 앱을 먼저 종료하고, 복원 후 다시 실행하세요.

### `ast relocate <id> <new-cwd>` — cwd 수정

```bash
ast relocate 960faaa8 ~/project/real-folder --dry-run
ast relocate 960faaa8 ~/project/real-folder -y
ast relocate 960faaa8 ~/project/real-folder --keep-original --force
```

JSONL의 모든 이벤트의 `cwd` 필드를 재작성하고 파일을 새 프로젝트 디렉터리로 이동. 서브에이전트 트랜스크립트(`<parent-id>/subagents/`)도 함께 이동.

| 플래그 | 의미 |
|---|---|
| `--keep-original` | 이동 대신 복사 (원본 유지) |
| `--force` | 새 cwd가 디스크에 존재하지 않아도 강행 |
| `--dry-run` | 재작성 계획 표시 (변경 없음) |
| `-y` / `--yes` | 확인 건너뛰기 |

### `ast rm <id> [<id> ...]` — 세션 트랜스크립트 삭제

```bash
ast rm 960faaa8 --dry-run       # 무엇이 삭제될지 표시
ast rm 960faaa8 -y              # 확인 없이 삭제
ast rm 960faaa8 3a7f21bc -y     # 한 번에 여러 id 삭제
```

트랜스크립트 `.jsonl`을 unlink하고 캐시/done 플래그 흔적을 정리 — TUI `Del`
키와 같은 동작의 스크립트 버전. **트랜스크립트만 삭제됩니다: 라이브
백그라운드 프로세스는 계속 실행됨** (먼저 `ast stop <id>`로 중지).
비대화식 호출은 `-y` 필수(tty 없이 입력 대기하는 대신 거부); `--force`도
확인을 건너뜀(단일 id 형태에 한함 — 벌크 모드는 아래에서 `--force` 동작이
다르다).

### 일괄 삭제

세션을 한 번에 여러 개 삭제 — TUI의 `/` 필터 → `Ctrl-A` → `Del` 흐름을
명령 한 번으로:

```bash
ast rm --filter "prototype"              # id + cwd + 첫 메시지 부분 문자열
ast rm --cwd ~/proj/scratch --status done
ast rm --status ended --older-than 90    # 90일 이상 손대지 않은 세션
ast rm --status ended --before 2026-01-01
ast rm --filter test --days 7 --dry-run  # 최근 7일, 미리보기만
```

라이브 세션(● working / ! waiting)은 건너뜁니다 — 실행 중인 Claude
프로세스가 열어 둔 트랜스크립트에 계속 이어 쓰기 때문에, unlink하면 그
이후 내용이 사라집니다. **✓ done으로 표시됐지만 프로세스가 아직 살아서
working/waiting 중인 세션**도 같은 이유로 건너뜁니다 — done은 단순 북마크
플래그일 뿐 프로세스를 멈추지 않으며, 목록에는 그대로 ✓로 표시됩니다.
이런 라이브 세션을 대상에 포함하려면 `--force`를 지정. 단일 id 형태와
달리 벌크 모드의 `--force`는 확인 프롬프트를 건너뛰지 않습니다 — 확인까지
생략하려면 `-y`/`--yes`를 함께 지정하세요. `--days` / `--older-than` /
`--before`는 서로 배타적이며, `--days N`은 (`ast list`와 동일하게) "최근
N일"을 뜻합니다 — "N일 이상 지난"이 아닙니다. 이는 `ast backup --days N`과
정반대 의미이므로, "N일 이상 지난"이 필요하면 `--older-than`을 사용하세요.

비대화형 호출은 `-y`를 명시해야 합니다. 삭제는 트랜스크립트만 unlink —
백그라운드 세션의 프로세스는 계속 실행되므로 `ast stop <id>`로 중지하세요.

### `ast stats [--top N]` — 전체 요약

```
Total sessions:  563
Total messages:  70778
  ● working: 1
  ! waiting: 2
  ◦ idle:   8
  ○ ended:  540
  ✓ done:   12

Top projects:
  ~/project/url-shortener-mvp    87
  ~/.claude/skills               42
  …
```

### `ast subagents <parent-id>` — Task 서브에이전트 목록

부모 세션에서 디스패치된 모든 서브에이전트를 `agentType`, description, 메시지 수, 첫 프롬프트와 함께 출력.

### 백그라운드 (agent-view) 세션 — `claude --bg` / `claude agents`

cst는 agent-view가 디스패치한 supervisor 관리 **백그라운드** 세션(`claude --bg`)도
보여줍니다. 이들은 짧은 `daemonShort` id로 주소 지정되며, cst는 트랜스크립트를
포크하는 대신 실제 `claude` CLI를 구동합니다.

```bash
ast jobs                  # 모든 agent-view 잡 나열(exec/트랜스크립트 없는 잡 포함),
                          #   데몬 상태 헤더 포함; * = agent-view에서 핀 고정됨
ast bg "<prompt>" [--name N]  # 새 백그라운드 세션 디스패치 (claude --bg)
ast stop <id>             # 라이브 bg 프로세스 정지 (claude stop <short>) — 실제로
                          #   정지하는 유일한 방법; cst의 Del은 트랜스크립트만 언링크
ast logs <id>             # bg 세션 최근 출력 보기 (claude logs <short>)
```

- **재개/Enter는 attach.** 잡 기반 행에서 `ast resume`·TUI `Enter`는 트랜스크립트
  포크 대신 `claude attach <short>`(라이브 supervisor 세션: catch-up + 라이브 스트림)을 실행.
- **행 배지** (`ast list`/TUI 행의 PROJECT 컬럼에 덧붙음): `[bg]`, `[exec]`,
  `[bg ⎇<branch>]`(git worktree 브랜치), `[bg ∙]`(프로세스 종료됐지만 attach/재실행
  가능), `[PR #1]`/`[PR #1,3]`(트랜스크립트에서 발견된 PR/MR URL), 그리고 agent-view에서
  핀 고정된 세션 앞의 `*`(`~/.claude/jobs/pins.json`에서 읽음; cst는 절대 쓰지 않음).

### 훅 관련 명령

| 명령 | 사용 시점 |
|---|---|
| `ast install-hook [--settings PATH]` | 정밀 레이어를 `~/.claude/settings.json`에 한 번 등록. 멱등; 다른 훅 보존. |
| `ast uninstall-hook [--settings PATH]` | 설정에서 ast 항목만 제거. 다른 훅 유지. |
| `ast prompt-hook` | *내부* — Claude Code가 `UserPromptSubmit`에 호출. 수동 실행 금지. |
| `ast status-hook [event]` | *내부* — Claude Code가 라이프사이클 이벤트에 호출. 수동 실행 금지. |

상세는 아래 [훅](#훅) 섹션 참조.

---

## TUI (`ast --tui`)

fzf 스타일 필터, 상태 글리프, 모달, 액션 키를 갖춘 curses 선택기. **두 모드** — 일반(단축키) + 검색(쿼리 타이핑).

### 일반 모드

| 키 | 동작 |
|---|---|
| `↑↓` / `Ctrl-P` `Ctrl-N` | 한 행 이동 |
| `PgUp` / `PgDn` / `Home` / `End` | 페이지 / 점프 |
| **`Enter`** | **선택 세션을 새 터미널 창에서 열기** (현재와 같은 터미널 앱). 세션의 cwd가 사라졌다면 orphan-relocate 모달이 도와줌. |
| `Space` | 현재 행 마크 토글 |
| `Ctrl-A` | 보이는 **모든** 행 마크 토글 |
| `Ctrl-X` | 모든 마크 초기화 |
| **`v`** / **`V`** | 포커스된 세션 미리보기 (스크롤 모달; 상단 메타 정보는 고정). 내부: `↑↓/j/k` 스크롤 · `PgUp/PgDn/Space` 페이지 · `g/G` 처음/끝 · `←/→` 이전/다음 세션 · `d/Ctrl-D` 미리보기 중인 세션 done 토글(스크롤 위치 유지) · `Del` 미리보기 중인 세션 삭제 (그 자리에서 확인; 취소하면 미리보기로 복귀) · `q/Esc/v` 닫기 |
| **`e`** / **`E`** | 포커스된 세션을 `./<id>.md`로 내보내기 (토스트에 경로 표시) |
| **`o`** / **`O`** | 포커스된 세션의 **폴더**를 새 터미널 창에서 열기 — 기록된 cwd에서 순수 대화형 셸만 실행, `claude` 명령 없음 (`Enter`와 같은 터미널 앱 감지; cmux 안에서는 탭/창 선택 모달; cwd가 사라졌으면 `ast relocate` 안내와 함께 실패) |
| **`D`** / **`d`** / **`Ctrl-D`** | 현재 행(또는 마크된 모든 행) **done** 토글. 영구 저장. |
| **`H`** / **`h`** | hide-done 토글 — ✓ 행 숨김/표시 (`Ctrl-H`는 Backspace라 별칭 없음) |
| **`C`** / **`c`** | cwd-only 토글 — TUI 실행 cwd 아래의 세션만 표시 (NFC-정규화 prefix 매치) |
| **`R`** / **`r`** / **`Ctrl-R`** | 세션 목록 + 라이브 프로세스 레지스트리 재스캔. 재스캔이 진행되는 동안 하단 줄에 진행률이 표시됩니다 — `Rescanning… 42% (994/2370)`. 자동 재스캔도 같은 진행률을 표시하지만, 약 0.35초를 넘겨 실행될 때에만 나타납니다 (캐시가 이미 채워진 재스캔은 그 전에 끝나므로 표시되지 않습니다). |
| **`a`** / **`A`** | 에이전트 뷰 순환: `all → claude → codex → chatgpt` (`A`는 역방향). `all`이 아닐 때 헤더에 `⚙codex` 표시. 저장되며 `ast list --agent`와 공유. |
| **`i`** / **`I`** | 자동 재스캔 간격 팝업 (Off / 5 / 10 / 30 / 60 / 120초; 기본 ON 10초, `state.json`에 저장; 세션이 **새로** `!` 대기로 전이 시 `curses.beep()` + 고정 TUI 토스트 — macOS 데스크톱 알림 없음). 1.18 이전에는 `a` 키였음. |
| **`s`** | 정렬 컬럼 순환 (화면 컬럼 순서대로): `status → time → msgs → message → project` (해당 컬럼의 자연 방향으로 리셋). 헤더에 `sort:<col>▼/▲` 표시 + 활성 컬럼 하이라이트. 저장됨. |
| **`S`** | 현재 정렬 방향 반전. 저장됨. |
| **`f`** | 생성 주체 필터 순환: `all → user → agent`. `user`는 터미널에서 시작한 세션(agent-view `bg` 잡 포함), `agent`는 SDK가 생성한 세션(보안 리뷰 훅, `claude -p`, 각종 도구). 헤더에 `👤user` / `🤖agent` 표시. 저장되며 `ast list --origin`과 공유. |
| **`F`** | 생성 주체 필터를 역방향으로 순환 (`all → agent → user`). 저장됨. |
| **`t`** / **`T`** | 색 테마 토글 (dark ↔ light). `state.json`에 저장. |
| `Del` / `Fn+Delete` | 마크된/현재 세션 삭제 (확인 모달) |
| `?` | 도움말 모달 |
| `/` | 검색 모드 진입 |
| `Esc` | 필터/검색 있으면 초기화, 없으면 종료 |

> **바인딩되지 않은 일반 ASCII 문자는 일반 모드에서 무시됩니다.** 모든 자유 입력은 `/` 뒤에 있음.

### 검색 모드 (`/` 누른 후)

프롬프트 줄에 커서가 표시됩니다. 타이핑하면 실시간 필터링.

| 키 | 동작 |
|---|---|
| *문자* (ASCII, **한글**, 일본어, 중국어 모두) | 라이브 메타데이터 필터 (id + cwd + 첫 유저 메시지) |
| `↑↓` / `Ctrl-P` `Ctrl-N` / `PgUp PgDn` / `Home End` | 필터링 **중에도** 선택 이동 |
| `Backspace` / `Ctrl-U` | 수정 / 비우기 |
| **`Enter`** | 필터 확정, 검색 모드 종료 (필터는 유지) |
| `Ctrl-A` | 보이는 모든 행 마크 토글 (검색 모드 유지) |
| `Ctrl-D` | 현재 행 done 토글 (검색 모드 유지) |
| `Ctrl-R` | rescan (검색 모드 유지) |
| `Tab` | 현재 쿼리로 **본문 전체 검색(full-text)**까지 확대 |
| `Esc` | 쿼리 지우고 검색 모드 종료 |

### 헤더

```
 agent-session-tracker v1.3.0  12/563  ●3 !1 ◦0 ○558 ✓1  ⟳10s  sort:time▼  👤user  ⚙codex  [✓ hidden]  [📂 ~/project]   ? help  Enter open  o folder  / filter  s sort  f origin  a agent  i auto  ^R rescan  ^D mark✓  H hide✓  C cwd  Esc quit
```

- `12/563` — 보이는 행 / 전체 세션 수
- `●3 !1 ◦0 ○558 ✓1` — 현재 뷰의 상태별 카운트
- `⟳10s` — 자동 재스캔 간격 (또는 `⟳off`)
- `sort:time▼` — 활성 정렬 컬럼 + 방향 (`▼` 내림 / `▲` 오름); 해당 컬럼 헤더가 하이라이트됨
- `👤user` / `🤖agent` — 생성 주체 필터가 `all`이 아닐 때만 표시
- `⚙codex` — 에이전트 뷰가 `all`이 아닐 때만 표시
- `[✓ hidden]` — hide-done이 켜졌을 때만 표시
- `[📂 ~/project]` — cwd-only가 켜졌을 때만 표시

### 프롬프트 줄 (헤더 아래)

현재 상태를 반영:
- 비어있음: `(press / to filter, ? for help)` (dim)
- 필터 적용됨: `filter=abc   (/ to edit, Esc/clear)` (dim)
- 본문 검색 적용됨: `text=auth→14   (/ to edit, Esc/clear)` (dim)
- 검색 모드 중: `/ <query>█` (bold, 커서)

### 모달 다이얼로그

- **도움말 (`?`)** — 스크롤 가능한 치트시트
- **미리보기 (`v`)** — 역할별 색상의 트랜스크립트, 메시지 전문 표시(줄바꿈 처리). 상단 메타 정보(Session / Status / Cwd / Branch / Started)는 구분선 위에 고정되어 스크롤해도 사라지지 않으며, Status 행은 목록의 ST 컬럼과 같은 팔레트로 상태별 색상이 적용된다(● 초록 · ! 빨강 · ◦ 시안 · ○ 흐림 · ✓ 마젠타); `d`/`Ctrl-D`로 done 토글(스크롤 위치와 검색 상태 유지, 변경 직후 Status 행이 한 번의 키 입력 동안 반전되어 변화를 알림). 모달 박스 주위로 보이는 목록도 같은 토글을 즉시 따라가며, 모달을 닫았을 때의 모습을 그대로 보여준다. 해당 행의 ST 글리프, 헤더의 ✓/○ 개수, status 정렬 순서가 갱신되고, `H`(완료 숨김)가 켜져 있으면 그 행 자체가 목록에서 사라진다. 어느 경우든 모달은 열었을 때의 세션을 계속 보여주며, `←`/`→` 이동 범위도 모달을 열던 시점의 목록을 유지한다. `Del`로 그 자리에서 삭제(확인)
- **자동 재스캔 간격 (`i`)** — Off / 5 / 10 / 30 / 60 / 120초. `1`–`6`로 직접 점프, Enter 적용; `state.json`에 저장
- **삭제 확인 (`Del`)** — `y` 확정 · `n/Esc/Enter` 취소 · 최대 5개 미리 표시
- **권한 건너뛰기 확인** — `--skip-perm` 없이 재개할 때 Enter에서 표시. `y/Y/Enter` 플래그 적용 · `n/N` 미적용 · `Esc` 취소
- **cmux 선택기** — cst가 cmux 안에서 실행될 때만 표시. `t/T/Enter` cmux 워크스페이스 탭 · `w/W` cmux 새 창 · `Esc` 취소
- **Orphan-relocate 흐름** — 세션의 기록된 cwd가 더 이상 존재하지 않을 때, cst가 새 위치 후보를 찾아줌 (macOS는 `mdfind`, `fd` 설치돼 있으면 fd, 폴백은 `os.walk`):
  - **Confirm** (고신뢰 단일 매치) — `y/Y/Enter` 사용 · `e/E` 경로 수동 입력 · `o/O` placeholder · `Esc` 취소
  - **Pick** (복수 후보) — `↑↓` 이동 · `Enter` 사용 · `e/o/Esc` 위와 동일
  - **None** — `e/E` 수동 입력 · `o/O` placeholder · `Esc` 취소

---

## 세션 열기 (Enter 동작)

TUI에서 `Enter`를 누르면 **현재 쓰는 터미널 앱과 동일한 앱의 새 창**에서 `claude --resume <sid>`가 실행됩니다 (`$TERM_PROGRAM`으로 감지):

| `$TERM_PROGRAM` | 처리 방식 | 포그라운드 활성화 |
|---|---|---|
| `iTerm.app` | iTerm2 AppleScript (`create window with default profile`) | 스크립트 내 `activate` |
| `Apple_Terminal` | Terminal.app AppleScript (`do script`) | 스크립트 내 `activate` |
| `WezTerm` | `wezterm start --cwd ... -- bash -lc "..."` | `osascript`로 WezTerm 활성화 |
| `ghostty` | `ghostty --working-directory ... -e bash -lc "..."` | `osascript`로 Ghostty 활성화 |
| `kitty` | `kitty --detach --directory ... bash -lc "..."` | `osascript`로 kitty 활성화 |
| `Alacritty` | `alacritty --working-directory ... -e bash -lc "..."` | `osascript`로 Alacritty 활성화 |
| `WarpTerminal` | Terminal.app으로 폴백 (Warp은 커맨드 스크립팅 API 없음) | — |
| `vscode` / `cursor` | Terminal.app으로 폴백 (IDE 내장 터미널 → 외부 창) | — |
| 알 수 없음 | Terminal.app으로 폴백 | — |
| Linux | `$TERMINAL` → `gnome-terminal` / `konsole` / `alacritty` / `kitty` / `wezterm` / `xterm` 순 | — |
| cmux 내부 | cmux 워크스페이스 탭 또는 새 창 (선택) | — |

**`claude` 절대 경로는 부모 프로세스에서 `shutil.which("claude")`로 해결**되어 새 쉘 PATH 문제를 우회합니다 (nvm/volta/asdf 환경에서 `cd && claude`가 실패하는 케이스 방지).

**`claude` 실행이 실패하면** 새 창이 바로 닫히지 않고 다음 에러가 남아 원인을 확인할 수 있습니다:
```
[ast] 'claude --resume' failed (exit 127)
[ast] claude binary: /Users/you/.local/bin/claude
[ast] press Enter to close this window...
```

---

## 훅

`ast install-hook`은 Claude Code 라이프사이클 훅을 `~/.claude/settings.json`에 등록합니다. 훅은 **선택사항** — 없어도 `ast`는 동작합니다 — 하지만 설치하면:

1. **토큰 0**짜리 `done!` / `undone!` 프롬프트 명령
2. `!` 대기 글리프의 **정밀 레이어** (더 빠르고 세밀한 전이, 깔끔한 `◦` 유휴 신호)

### `done!` / `undone!` 프롬프트 명령 (토큰 0)

`install-hook` 후, 어떤 Claude Code 세션 안에서든 다음을 **프롬프트 전체**로 입력할 수 있습니다:

| 입력 | 동작 |
|:--|:--|
| `done!` | **현재** 세션을 ✓ done으로 표시 (훅 payload의 `session_id`) |
| `done! <id>` | 해당 세션 마크 (8자 prefix 가능) |
| `undone!` / `undone! <id>` | done 플래그 해제 |
| `/done`, `/undone` | 레거시 — 여전히 인식되지만, 맨 앞 `/`는 Claude Code 슬래시 커맨드 팔레트를 띄워 제출을 막는 경우가 많음. bang 형태 권장. |

트리거는 프롬프트 **전체**여야 합니다. "I am done!" / "done! 수고했어" 같은 문장은 매칭되지 않고 그대로 모델로 갑니다. 훅이 로컬에서 토글을 실행하고 **프롬프트가 모델에 도달하기 전에 차단**하므로 모델 호출 자체가 없습니다 — **토큰 0**.

### `install-hook`이 등록하는 것

| 이벤트 | 명령 | 타임아웃 | 용도 |
|---|---|---|---|
| `UserPromptSubmit` | `ast prompt-hook` | 25s | `done!`/`undone!` 가로채기 |
| `UserPromptSubmit` | `ast status-hook` | 10s | `working` 상태 기록 |
| `Notification` | `ast status-hook` | 10s | `waiting` 상태 기록 |
| `PermissionRequest` | `ast status-hook` | 10s | `waiting` 상태 기록 |
| `Stop` | `ast status-hook` | 10s | `idle` 상태 기록 |
| `SessionEnd` | `ast status-hook` | 10s | 상태 오버레이 정리 |

수동 등록 시 동일한 항목 (한 이벤트 예시):
```json
{ "hooks": { "UserPromptSubmit": [
  { "matcher": "", "hooks": [
    { "type": "command", "command": "ast prompt-hook", "timeout": 25 },
    { "type": "command", "command": "ast status-hook",  "timeout": 10 }
  ] } ] } }
```

### 운영 노트

- **`!`는 훅 없이도 동작.** Claude Code 2.x가 `~/.claude/sessions/<pid>.json`에 `status:"waiting"` / `waitingFor`를 직접 기록하므로 `ast`가 그대로 읽음.
- **멱등 설치.** `ast install-hook` 재실행 시 ast 항목을 먼저 제거하고 재추가합니다. 다른 훅은 그대로 두며, `cst`의 훅도 여기에 해당합니다. ast는 명령이 `ast prompt-hook` / `ast status-hook`으로 끝나는 항목만 자기 것으로 인식하기 때문입니다.
- **자기 치유.** 레지스트리가 마지막 훅 이벤트보다 최신 `idle`을 보고하면 고착된 `!`는 자동으로 `◦`로 정정됨.
- **cmux 호환.** cmux가 `--settings`로 자체 Claude 훅을 주입해도, Claude Code가 `~/.claude/settings.json`과 합산 로드하므로 ast 훅도 동일 session id로 정상 동작 — 충돌 없음.
- **핫 리로드.** `tracker.py` 코드 변경은 즉시 반영(매번 `ast`를 새로 실행). `settings.json` 변경만 `/hooks`를 한 번 열거나 재시작해야 설정 워처가 리로드.

---

## 데이터 파일

| 경로 | 용도 | 삭제 안전? |
|---|---|---|
| `~/.claude/projects/**/*.jsonl` | 세션 트랜스크립트 (Claude Code 원본) | **아니오** — 작업 이력 |
| `~/.claude/sessions/<pid>.json` | Claude Code의 라이브 프로세스 레지스트리 (읽기 전용) | 건드리지 말 것 |
| `~/.claude/settings.json` | Claude Code 설정 (cst가 훅 항목을 기록) | 아니오 — `ast uninstall-hook`로 ast 항목만 제거 |
| `~/.claude/jobs/<short>/state.json` | agent-view 백그라운드 잡 상태 (읽기 전용) | 건드리지 말 것 |
| `~/.claude/jobs/pins.json` | agent-view 핀 집합 (읽기 전용; cst는 쓰지 않음) | 건드리지 말 것 |
| `$CODEX_HOME/sessions/**/rollout-*.jsonl` | Codex CLI 트랜스크립트와 ChatGPT 데스크톱 앱 대화 (기본 `~/.codex`; 읽기 전용) | 건드리지 말 것 |
| `$CODEX_HOME/thread-writer-locks/<uuid>.lock` | codex의 스레드별 writer 잠금 — cst는 flock 탐지로 실행 여부만 확인 (읽기 전용) | 건드리지 말 것 |
| `~/.ast/index.json` | mtime/size 무효화 세션 메타 캐시 (스키마 6, 항목마다 `agent` 보유) | 예 (다음 실행 시 재생성) |
| `~/.ast/state.json` | done 플래그 + 훅 상태 오버레이 + 사용자 설정(자동 재스캔·테마·정렬·생성 주체·에이전트 뷰) | 예 (모든 `✓` 마크·오버레이·설정 초기화) |

위 표의 `~/.claude/...` 경로는 모두 **`$CLAUDE_CONFIG_DIR`**를 따릅니다
(Claude Code 자체와 같은 규약): 설정돼 있으면 `projects/`, `sessions/`,
`jobs/`, `daemon/`, `settings.json`을 `~/.claude` 대신 그 루트에서 읽습니다.
codex 경로도 같은 방식으로 **`$CODEX_HOME`**(기본 `~/.codex`)를 따릅니다.

ast 자체 파일(`index.json`, `state.json`, 그리고 `--out` 없이 실행한
`backup`이 만드는 아카이브)은 **`~/.ast`** 아래에 저장되며 **`$AST_HOME`**
환경변수로 재지정할 수 있습니다. 첫 실행 시 `~/.cst/state.json`이 있으면 한 번
복사하므로 `cst`에서 쓰던 done 플래그와 설정이 그대로 이어집니다. `cst`가 자기
홈을 계속 사용하므로 원본은 그대로 둡니다.

### 인덱싱 속도

목록 조회가 빠른 이유는 `index.json` 덕분입니다. 이 캐시가 살아 있으면 모든
명령과 TUI의 rescan이 밀리초 단위로 끝나는데, mtime이나 크기가 바뀐 transcript
만 다시 읽기 때문입니다. 캐시가 없는 상태에서 인덱스를 새로 만들 때는 모든
transcript를 읽어야 하므로, ast는 그 작업을 여러 워커 프로세스에 분산합니다.
세션 2,370개(합계 3.9GB)로 측정한 결과 콜드 인덱싱이 약 16.6초에서 약 2.5초로
줄었습니다. 변경된 파일이 몇 개뿐인 warm rescan에서는 프로세스를 만드는 비용이
더 크기 때문에 단일 프로세스를 유지합니다.

이 판단은 **`$AST_JOBS`**로 재지정할 수 있습니다. `AST_JOBS=1`을 지정하면
인덱싱을 순차로만 수행하고(ast가 여러 코어를 점유하지 않기를 원하는 환경에서
유용합니다), 더 큰 수를 지정하면 워커 개수를 그 값으로 고정합니다. 지정하지
않으면 최대 12개까지, 그리고 코어 수를 넘지 않는 범위에서 사용합니다.

`index.json`은 삭제해도 안전하지만, 그다음 실행은 전체 콜드 인덱싱 비용을
치릅니다. `relocate`와 `restore`는 더 이상 이 파일을 삭제하지 않고, 실제로
건드린 transcript의 항목만 무효화합니다.

#### 동기화 폴더에서 인덱스를 분리하기

`~/.ast`를 동기화 폴더(Synology Drive, Dropbox, iCloud 등)에 두었다면
**`$AST_INDEX_DIR`**를 지정해 `index.json`만 로컬로 옮길 수 있습니다.

```bash
export AST_INDEX_DIR="$HOME/.cache/ast"
```

✓ done 플래그와 표시 설정이 들어 있는 `state.json`은 홈에 남아 계속
동기화됩니다. 기기 사이에서 공유할 값어치가 있는 쪽은 이것입니다. 반면
`index.json`은 공유할 이유가 없습니다. transcript가 하나라도 변한 rescan마다
다시 기록되므로 동기화 데몬이 같은 파일을 끝없이 업로드하고, 두 기기가 동시에
기록하면 `index_<호스트명>_…_Conflict.json` 같은 충돌본이 쌓입니다. 게다가 이
캐시는 키가 transcript의 절대 경로이고 값이 mtime이어서, 동기화가 mtime을
보존하지 못하면 다른 기기에서는 모든 항목이 캐시 미스가 됩니다.

지정하지 않으면 기본값이 홈 자체이므로, 기존 설치의 동작은 달라지지 않고 이미
만들어 둔 캐시도 버리지 않습니다.

### `state.json` 스키마

```json
{
  "done": {
    "<session-id>": "<iso-8601 timestamp>"
  },
  "status": {
    "<session-id>": {
      "state": "working" | "waiting" | "idle",
      "event": "<hook-event-name>",
      "ts": "<iso-8601 timestamp>"
    }
  },
  "auto_rescan": {
    "enabled": true,
    "interval": 10
  },
  "theme": "auto" | "dark" | "light",
  "sort": {
    "key": "time" | "status" | "msgs" | "message" | "project",
    "reverse": true
  },
  "origin": "all" | "user" | "agent",
  "agent": "all" | "claude" | "codex" | "chatgpt"
}
```

`status`는 `ast status-hook`이 채움 (훅이 설치돼 있을 때만). `auto_rescan`은 TUI `i`
팝업, `theme`은 `t`/`T`(또는 `--theme`), `sort`는 TUI `s`/`S` 키, `origin`은 `f`/`F`
키, `agent`는 `a`/`A` 키에서 설정. `state.json`을 지우면 전부 초기화.

---

## 워크플로

### "지금 뭐가 돌고 있지?"

```bash
ast live
ast list --status working
ast list --status waiting    # 내 입력을 기다리는 세션은?
```

### "끝낸 작업 정리"

```bash
ast --tui
# /      → 키워드 입력 (실시간 필터)
# Enter  → 필터 확정, 검색 모드 종료 (필터 유지)
# Ctrl-A → 보이는 모든 행 마크
# D      → 마크된 모든 행을 done으로
# H      → ✓ 숨김 토글
# R      → 재스캔
```

### "인증 마이그레이션 세팅하던 세션 찾기"

```bash
ast search "인증 마이그레이션" -i --limit 5
# 또는 TUI에서:
#   / → "인증" 입력 → Tab (본문 전체 스캔) → ↑↓ → Enter로 새 창 열기
```

### "트랜스크립트를 공유하려고 내보내기"

```bash
ast export 960faaa8 --out ~/exports/
# 또는 TUI에서 행 포커스 후 `e` 키
```

### "90일 이상 된 세션 아카이빙"

```bash
ast backup --days 90 --dry-run        # 미리보기
ast backup --days 90 --delete -y      # 아카이브 + 원본 제거
ast backup --before 2026-01-01 -y     # 절대 날짜 기준
```

### "Claude를 잘못된 디렉터리에서 실행했다"

```bash
ast relocate <id> ~/project/actual-folder --dry-run
ast relocate <id> ~/project/actual-folder -y
# 또는 TUI에서 해당 행에서 Enter — cwd가 사라졌다면 cst가
# orphan-relocate 흐름으로 새 위치 찾기/선택을 도와줌.
```

---

## 비교

### vs. `claude-session-tracker` (cst)

같은 도구에 에이전트가 하나 더해진 관계입니다. `cst`는 Claude Code만 추적하고,
`ast`는 어댑터 계층을 통해 Claude Code와 Codex를 함께 추적하며 그 범위를 데이터
명령까지 확장했습니다.

- codex 세션을 Claude Code 세션과 나란히 탐색·파싱·목록·검색·재개·재배치·백업·복원
- ChatGPT 데스크톱 앱이 codex rollout 사이에 저장하는 대화를 별도의 `chatgpt`
  에이전트로 표시함
- 백업 아카이브가 에이전트별로 구분되고(`projects/…`, `codex/…`) manifest에 각
  세션의 에이전트가 기록됨. `cst`가 만든 아카이브도 그대로 복원됨
- `ast relocate`는 codex 세션의 기록된 cwd를 제자리에서 재작성하고,
  `ast subagents`는 codex가 생성한 guardian 스레드를 보여 줌
- 데이터 홈이 `~/.ast`(`$AST_HOME`)이며 첫 실행 시 `~/.cst/state.json`에서 복사
- 훅 명령이 `ast prompt-hook` / `ast status-hook`이라 두 도구의 훅 항목이 공존 가능

수정한 결함: `cst`에서는 백업 기준일보다 오래된 codex 세션이 하나라도 있으면
`backup`이 중단됐습니다. 모든 트랜스크립트 경로를 `~/.claude/projects` 기준
상대 경로로 계산했기 때문입니다.

### vs. `claude-sessions`

`ast`는 상위 집합. 모든 `claude-sessions` 서브커맨드 유지 + 추가:

- **#** 번호 컬럼 + **ST** 글리프 컬럼 + **AGENT** 컬럼 + **PROJECT** 컬럼을 매 행에 표시
- **멀티 에이전트:** Codex CLI 세션과 ChatGPT 데스크톱 앱 대화를 Claude 세션과 나란히 목록·검색·조회·내보내기·재개·상태 추적 (`--agent`, TUI `a`)
- **`done`**, **`undone`**, **`live`**, **`export`**, **`bg`** / **`jobs`** / **`stop`** / **`logs`** (agent-view 백그라운드 세션), **`install-hook`** / **`uninstall-hook`** / **`prompt-hook`** / **`status-hook`** 서브커맨드
- `ast list --sort time|status|msgs|message|project [--reverse]` 컬럼 정렬
- `ast list --origin all|user|agent` (및 `ast search --origin`) — SDK가 생성한 세션을 숨기거나, 그것만 보기
- TUI 키: `D/d/Ctrl-D` (done 토글) · `H/h` (숨김 토글) · `C/c` (cwd-only) · `R/r/Ctrl-R` (rescan) · `e/E` (내보내기) · `o/O` (폴더 열기) · `a/A` (에이전트 뷰) · `i/I` (자동 재스캔) · `s`/`S` (컬럼 정렬) · `f`/`F` (생성 주체 필터) · `t/T` (테마) · `Ctrl-A` (전체 마크) · `?` (도움말) · `v/V` (미리보기)
- 백그라운드/agent-view 행: `[bg]`/`[exec]`/`[bg ⎇branch]`/`[bg ∙]`/`[PR #N]` 배지, `*` 핀 마커, `Enter`는 attach(포크 아님)
- 색 테마 (dark/light, `--theme` / `t`)
- fzf 스타일 `/` — 타이핑하며 동시에 이동, 필터 확정 후 다양한 액션
- Unicode (**한글**/일본어/중국어) 검색 입력 지원
- Enter가 **현재와 같은 터미널 앱의 새 창**(iTerm/WezTerm/Ghostty/kitty/Alacritty/Terminal/cmux)에서 세션을 열고 **포그라운드로 끌어옴** (기존 `claude-sessions`는 TUI 프로세스를 `claude`로 교체)
- 세션의 기록 cwd가 사라졌을 때 orphan-relocate 흐름

### vs. `claude-session-manager` (csm)

목적이 달라 상호 보완적.

| | **csm** | **ast** |
|---|---|---|
| 역할 | **동시 실행 중**인 세션의 작업 매니저 | **모든** 세션(라이브+과거) 브라우저 |
| 플랫폼 | macOS 전용 | 크로스 플랫폼 (stdlib만) |
| 데이터 | 별도 레지스트리 (제목/우선순위/태그/노트) | 원본 jsonl + 최소 overlay (done 플래그 + 훅 상태 + 자동 재스캔·테마·정렬·생성 주체 설정) |
| 주요 기능 | 윈도우 포커스 · 우선순위 · stale 리뷰 · watch TUI · 훅 · statusline | list / search / resume / export / backup / restore / relocate / 상태 글리프 / orphan-relocate |
| 범위 | 지금 동시에 처리 중인 세션 | 이력 전체 수백 개 |

**csm**: 동시에 돌고 있는 여러 터미널 창 트리아지
**ast**: 과거 세션 찾기/재개/내보내기/백업

---

## FAQ

**Q: Claude Code 세션이 닫히면 상태가 자동 업데이트되나요?**
A: `ast list` / `ast search` / `ast live` 호출마다 새로 스캔합니다. TUI에서는 `R` (또는 다음 자동 재스캔 — 기본 10초).

**Q: TUI에서 Enter를 누르면 터미널은 열리는데 `claude`가 실행 안 돼요.**
A: 새 창에 남는 에러 메시지를 확인하세요. 대개 새 쉘의 `PATH`에 `claude` 경로가 없어서 그렇습니다. `ast`는 부모 프로세스에서 `shutil.which("claude")`로 절대 경로를 미리 해결해 넣는데도 실패한다면, `ast` 실행 시점의 쉘에 `claude`가 PATH로 잡혀있는지 확인하세요.

**Q: Enter로 창은 열렸는데 TUI 뒤에 숨어 있어요.**
A: `ast`는 스폰 직후 `osascript activate`로 해당 앱을 전면으로 올립니다. 그래도 숨으면 Dock 아이콘을 한 번 클릭해 주세요 — 이후 Enter는 앞으로 올라옵니다.

**Q: `/` 입력 후 한글이 안 들어가요.**
A: `ast`는 키 이벤트를 바이트 단위로 읽어 UTF-8을 직접 조립합니다 — WezTerm 등 일부 터미널의 Python `curses.get_wch()` 이슈(화살표 키가 다중 문자열로 들어옴)를 우회합니다.

**Q: `Ctrl-H`로 hide 토글은 왜 안 되나요?**
A: `Ctrl-H == ASCII 8 == Backspace`. 바인딩하면 Backspace가 망가져서 지원 안 함.

**Q: Esc 눌렀더니 필터가 지워졌어요. 필터 유지하면서 프롬프트만 닫으려면?**
A: `Esc` 대신 **`Enter`**. 검색 모드의 Enter = 필터 확정 + 모드 종료. Esc는 초기화.

**Q: 자동 재스캔이 정말로 알림을 울리나요?**
A: 네. 직전 틱에 없었는데 이번 틱에 **새로** `!` 대기로 들어온 세션이 감지되면 `curses.beep()`를 울리고 고정 TUI 토스트(`⚠ N now waiting: …`)를 띄웁니다. 이미 대기 중이던 세션은 재알림하지 않습니다. (macOS 데스크톱 알림은 **없습니다** — `osascript -e 'display notification'`이 Script Editor 소유라 제거됨.)

**Q: Linux / Windows에서 동작하나요?**
A: Linux: 동작 (순수 stdlib). Windows: curses TUI는 `windows-curses` 패키지 필요, CLI 명령은 그대로 동작.

**Q: cst를 완전히 제거하려면?**
A: 위 [제거](#제거) 섹션 참조 — `ast uninstall-hook` → 심볼릭 링크 제거 → 선택적으로 `~/.ast` 삭제.

---

## 라이선스

MIT. [`claude-sessions`](https://github.com/)의 포크 (동일 라이선스).
