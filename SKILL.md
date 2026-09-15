---
name: agent-session-tracker
description: Track live/waiting/ended/done status of Claude Code sessions — and Codex CLI sessions and ChatGPT desktop app conversations alongside them. List, search, resume, export, backup, restore sessions via `ast` CLI or TUI. Use when user says "list sessions", "세션 상태", "ast", "session tracker", "codex 세션", "chatgpt 세션", "ChatGPT 앱 대화", or wants to resume/search/export/backup sessions.
version: 1.2.0
---

# agent-session-tracker

Tracks **every local coding-agent session in one place**. Forked from
`claude-session-tracker` (itself a fork of `claude-sessions`), which tracked
Claude Code alone; here an `AgentSpec` adapter per CLI (`claude`, `codex`,
plus `chatgpt` for the ChatGPT desktop app's threads in codex's store; gemini
planned) feeds one shared session model, so `list` / `search` / `show`
/ `export` / `resume` / `done` / `relocate` / `backup` / `restore` / TUI work
the same for every agent and an **AGENT** column says which one wrote each
session. On top of the original: live status tracking, a precision hook
overlay, fzf-style filter UX, transcript export, and new-window opening.
Every session resolves to one of five states (done always wins; a dead
process is ended/job-state; a live one resolves overlay → registry → `●`):

- **●** working — the agent is actively producing output.
- **!** waiting — the agent is waiting for your input or a permission
  decision (this is where time leaks; from the Claude Code registry by
  default, `ast install-hook` adds precision). Claude Code only — codex
  exposes no waiting signal.
- **◦** idle — turn finished, process still alive.
- **○** ended — process is gone (or was never registered).
- **✓** done — user explicitly marked the session finished (`D`/`d`/`Ctrl-D`
  in TUI, `ast done <id>`, or the `done!` prompt hook). Persists in
  `~/.ast/state.json`.

Main script: `tracker.py` (stdlib only, Python 3.10+, v1.2.0). Installed as
`~/.local/bin/ast`. All `~/.claude/...` data paths honor `$CLAUDE_CONFIG_DIR`
(same convention as Claude Code itself) and `~/.codex/...` honors
`$CODEX_HOME` (Codex's own convention); ast's own files live under `~/.ast`
(override with `$AST_HOME`). `$AST_INDEX_DIR` moves just `index.json` — the
regenerable index cache — out of that home; set it when the home sits in a
synced folder, since a multi-megabyte file rewritten on every rescan is exactly
what a sync daemon handles worst.

Building the index from cold reads every transcript, so it is spread across
worker processes once there is enough to read (a warm rescan stays
single-process — forking for a few changed files costs more than it saves).
`$AST_JOBS` overrides that: `AST_JOBS=1` keeps indexing sequential, a higher
number pins the worker count.

`ast` keeps its own home, so it can sit beside an installed `cst` without
either one seeing the other's ✓ done marks. On its first run `ast` copies
`~/.cst/state.json` into `~/.ast/` once if it is there, so a user coming from
`cst` keeps their done flags and prefs; the original is copied rather than
moved, so a `cst` that is still installed goes on working. Installing both
hook sets is possible but redundant — each writes its own home, so pick one.

## When to Use

- "세션 상태 보여줘" / "지금 열려있는 세션만 보여줘"
- "대기 중인 세션만" / "내 입력 기다리는 세션"
- "이 세션 작업 끝났다고 표시" / "done 마크"
- "끝낸 세션은 목록에서 숨기고 싶어"
- "세션 검색해서 새 창에서 이어서 작업"
- "트랜스크립트 파일로 내보내줘" / "export 세션"
- "코덱스 세션도 같이 보여줘" / "어제 codex로 뭐 했지"
- "ChatGPT 앱에서 물어본 대화 찾아줘" / "chatgpt 세션만 보여줘"
- Anything `cst` / `claude-sessions` did — list / search / show / resume /
  backup / restore / relocate / stats / subagents — `ast` is a drop-in
  superset that also covers Codex.

## CLI

`ast` with no subcommand opens the **TUI** when stdin and stdout are a
terminal. Without a tty — a pipe, a redirect, an agent tool call, a GUI caller
— it prints the list instead, so scripted callers keep working. `ast list`
asks for the table at a terminal.

Top-level flags: `-V/--version`, `--tui` (= `ast pick`; only needed to force
the picker without a tty), `--skip-perm`
(pass `--dangerously-skip-permissions` to `claude` on resume; otherwise the
TUI confirms per-resume), `--hide-done` (start the TUI with ✓ done sessions
hidden; toggle in-TUI with `H`), `--theme auto|dark|light` (TUI color theme;
`t`/`T` toggles live and persists).

```bash
ast                       # interactive TUI at a terminal; the list when piped/redirected
ast list                  # always the table: # + ST + LAST + SESSION + MSGS + MESSAGE + PROJECT
ast --tui                 # force the TUI even without a tty (same as `ast pick`)
ast --tui --hide-done     # TUI, ✓ done hidden from the start (also: ast pick --hide-done)
ast list --status working # working|waiting|idle|ended|done (active = alias for working)
ast list --cwd ~/p --days 7 --limit 50
ast list --sort msgs      # sort column: time(default)|status|msgs|message|project; --reverse flips
                          #   no --sort uses the saved TUI sort pref
ast list --origin user    # who started it: all(default)|user|agent
                          #   user  = typed in a terminal (agent-view bg jobs included)
                          #   agent = SDK-spawned (security-review hooks, claude -p, tooling)
                          #   no --origin uses the saved TUI origin pref; same flag on `search`
ast list --agent codex    # one agent's sessions: all(default)|claude|codex|chatgpt
                          #   chatgpt = ChatGPT desktop app conversations (see Multi-agent)
                          #   no --agent uses the view the TUI `a` key last saved;
                          #   same flag on `search` and `pick`; summary shows [agent:codex]
ast list --json           # machine-readable JSON instead of the table (cst.app contract;
                          #   each session carries "agent": "claude"|"codex"|"chatgpt")
ast search "<query>"      # full-text transcript search (OR via `|`, -i = ignore case)
ast show <id>             # transcript with Status header (--max-chars, --with-subagents;
                          #   --head-chars N caps TOTAL output & stops reading early — fast preview)
ast export <id>           # write transcript to <id>.md (--format md|txt, --out PATH|DIR)
ast resume <id> --print-only | bash
ast resume <id> --spawn   # actually open/attach in a new terminal (TUI Enter logic; cst.app)
ast open <id>             # open the session's FOLDER in a new terminal (TUI `o`;
                          #   plain shell at the recorded cwd, no claude; cst.app)
# --spawn / open pick the terminal from $TERM_PROGRAM; override with
#   --terminal wezterm|iterm|ghostty|kitty|alacritty|terminal
#   (GUI callers like cst.app have no $TERM_PROGRAM → Terminal.app without it)
ast done <id> [<id> ...] / ast undone <id>
ast done --filter TEXT [-y] [--force] [--cwd PFX] [--days N] [--status S]
                          # bulk done: case-insensitive substring over
                          #   id+cwd+first-msg (the TUI /-filter → Ctrl-A → d
                          #   flow); skips ● working unless --force; non-tty
                          #   callers MUST pass -y
ast live [--all]          # live Claude Code processes (--all shows stale entries)
ast stats [--top N]       # counts + top projects
ast subagents <parent-id> # Task-tool subagents
ast backup [--days N|--older-than N|--before YYYY-MM-DD] [--cwd PFX]
           [--out PATH] [--delete] [--force] [--dry-run] [-y]
                          # housekeeping: sessions OLDER than the cutoff
                          #   (default 90 days). --days here means "older
                          #   than N days" — the opposite of `list --days`
ast backup <id> [<id> ...] [--filter TEXT] [--out PATH] [-y]
                          # migration: the named sessions (id prefixes and/or
                          #   the id+cwd+first-msg substring), no age cutoff
                          #   unless one is given. Either form also packs each
                          #   session's subagent transcripts and, for codex /
                          #   chatgpt, its thread title from session_index.jsonl
ast restore <archive.tar.gz> [--cwd PFX]
            [--on-conflict skip|overwrite|rename] [--dry-run] [-y]
                          # puts subagents back beside their parent and adds
                          #   a missing thread title to session_index.jsonl
ast relocate <id> <new-cwd> [--keep-original] [--force] [--dry-run] [-y]
ast rm <id> [<id> ...] [--dry-run] [-y] [--force]   # unlink session transcript(s)
                          #   (only removes the transcript; a live bg process keeps
                          #   running; --force implies -y here, single-id only)
ast rm [--filter TEXT] [--cwd PFX] [--status S]
       [--days N|--older-than N|--before D] [--dry-run] [-y] [--force]
                          # bulk rm: needs at least one selector (--filter is
                          #   NOT required — e.g. `ast rm --status ended` alone
                          #   works); same id+cwd+first-msg substring match as
                          #   done --filter; skips ● working / ! waiting incl. a
                          #   ✓ done session whose process is still live; --force
                          #   only widens the target set — confirmation still
                          #   needs -y (unlike the single-id form above); --days N
                          #   = last N days, opposite of `ast backup --days`
                          #   (use --older-than for "older than N days");
                          #   non-tty callers MUST pass -y

# Background (agent-view) sessions — claude --bg / `claude agents`:
ast jobs                  # ALL agent-view jobs incl exec/transcript-less ones,
                          #   with daemon status; * = pinned in agent-view
ast bg "<prompt>" [--name N]  # dispatch a new background session (claude --bg)
ast stop <id>             # stop a live background session (claude stop <short>)
ast logs <id>            # a bg session's recent output (claude logs <short>)
# Rows are tagged: [bg ⎇<branch>] / [exec] / [bg ∙](process exited) / [PR #N] / *(pinned)
# `ast resume`/TUI Enter ATTACH a bg session (claude attach) instead of forking.

# Hooks (install once, then automatic):
ast install-hook   [--settings PATH]   # wire prompt-hook + status-hook
ast uninstall-hook [--settings PATH]   # remove ast entries, keep foreign hooks
ast prompt-hook                        # (internal) intercepts done!/undone!
ast status-hook [event]                # (internal) records working/waiting/idle
```

## Prompt hook — `done!` / `undone!` with zero AI tokens

`ast install-hook` adds two hook commands to `~/.claude/settings.json`:
`ast prompt-hook` (on `UserPromptSubmit`) and `ast status-hook` (on
`UserPromptSubmit`, `Notification`, `PermissionRequest`, `Stop`, `SessionEnd`).
Inside any Claude Code session the user can then type:

- `done!` → mark the **current** session ✓ done (uses payload `session_id`)
- `done! <id>` → mark that session · `undone! [id]` → clear the flag
- legacy `/done` / `/undone` accepted, but a leading `/` opens Claude Code's
  slash-command palette and usually blocks submission — prefer the bang forms

The hook runs `set_done()` locally and **blocks the prompt before it reaches
the model** (0 tokens). Trigger must be the whole prompt — `I am done!` /
`done! nice work` pass through untouched. Install is idempotent, and foreign
hooks are preserved — a `cst` install's own entries included, since `ast` only
claims commands ending in `ast prompt-hook` / `ast status-hook`. Code changes take effect
immediately; only settings.json edits need `/hooks` opened once or a restart.

### Live status accuracy

ast resolves `!` waiting **by default** from `~/.claude/sessions/<pid>.json`
(`status:"waiting"`, `waitingFor:"permission prompt"/"selection"/...`) on
Claude Code 2.x — no setup. The registry also gives `●` working / `◦` idle;
a dead PID is `○`.

`ast install-hook` (optional) wires `ast status-hook` across 5 lifecycle events
as a **precision layer** that writes to `state.json["status"]` — faster/finer
transitions, cleaner finished signal. **Not required for `!`.** Inside cmux:
cmux injects its own Claude hooks via `--settings`; Claude Code merges them
additively, so ast's hooks still fire — no conflict. *With hooks installed*,
if the registry reports a newer idle activity than the last hook event, a
stale `!` self-heals to `◦` to avoid a stuck state.

## TUI keybindings

**Normal mode** — row navigation + actions:

- `↑↓` / `Ctrl-P Ctrl-N` · `PgUp PgDn Home End` — move / page
- `Enter` — **open selected session in a new window of the same terminal app**
  (iTerm / Terminal.app / WezTerm / Ghostty / kitty / Alacritty on macOS;
  `$TERMINAL` or common terms on Linux; cmux tab/window if inside cmux).
  Brought to foreground via `osascript activate`. Absolute `claude` path
  resolved in parent process to avoid new-shell PATH issues. On failure the
  new window stays open with an error. If the session's cwd is missing, an
  orphan-relocate flow helps you find/pick the new home.
- `Space` toggle mark · `Ctrl-A` mark all visible · `Ctrl-X` clear marks
  · `Del` delete marked/current (with confirmation)
- **`v` / `V`** — preview modal (scrollable transcript). The metadata header
  (Session / Status / Cwd / Branch / Started) is **pinned** at the top of the
  modal, so only the transcript below the rule scrolls and the session stays
  identified at any scroll offset. Inside it `←`/`→` (or `‹`/`›`, `[`/`]`)
  step to the prev/next session in the list without closing, `d`/`Ctrl-D`
  toggles done on the previewed session (same ● working guard as the list;
  the scroll position and any active search are kept), and `Del` deletes the
  previewed session (confirm in place — cancel returns to the preview).
  The pinned Status row is colored by state, reusing the list's ST palette
  (● green · ! red · ◦ cyan · ○ dim · ✓ magenta), and it inverts for one
  keypress right after `d` changes the flag so the in-place repaint is not
  missed. The list visible *around* the modal box follows the same toggle
  immediately, exactly as it will look once the modal closes: the row's ST
  glyph, the header's ✓/○ counts, a status sort's order, and — with `H`
  (hide ✓) on — the row disappearing altogether. The modal itself keeps
  previewing the session it was opened on, and its `←`/`→` walk still covers
  the sessions listed when it opened
- **`e` / `E`** — export focused session to `./<id>.md`
- **`o` / `O`** — open the focused session's **folder** in a new terminal
  window: a plain interactive shell at the recorded cwd, no `claude` command
  (same terminal-app detection as Enter; cmux tab/window chooser inside cmux;
  a missing cwd fails with a `ast relocate` hint instead of recreating it)
- **`D` / `d` / `Ctrl-D`** — toggle done (or apply to all marked)
- **`H` / `h`** — hide ✓ rows (no Ctrl-H alias — Backspace collision);
  start hidden with `ast --hide-done` / `ast pick --hide-done`
- **`C` / `c`** — toggle: only sessions under the TUI launch cwd
  (NFC-normalized prefix match, Korean paths OK)
- **`R` / `r` / `Ctrl-R`** — rescan. While it runs, the footer counts the
  transcript scan: `Rescanning… 42% (994/2370)`. An auto-rescan tick shows
  the same counter, but only once it has run past ~0.35s, so a warm scan
  stays silent.
- **`a`** — cycle the agent view (all→claude→codex→chatgpt) · **`A`** — cycle
  backwards. Header shows `⚙codex` when not `all`; the last view is saved in
  `state.json` and reused by `ast list` / `ast search` without `--agent`.
- **`i` / `I`** — auto-rescan interval popup (Off / 5 / 10 / 30 / 60 / 120s;
  default ON 10s; persisted in `state.json`; `curses.beep()` + a sticky TUI
  toast when a session **newly** enters `!` waiting — no macOS desktop
  notification). Was `a` before 1.18.
- **`s`** — cycle sort column (status→time→msgs→message→project, in on-screen
  column order; resets to the column's natural direction) · **`S`** — reverse sort
  direction. Header shows `sort:<col>▼/▲` + highlights the active column;
  persisted in `state.json`.
- **`f`** — cycle origin filter (all→user→agent) · **`F`** — cycle backwards.
  `user` = started from a terminal (agent-view `bg` jobs included, since a
  human dispatched them); `agent` = SDK-spawned (`sdk-py`/`sdk-cli`/`sdk-ts`:
  security-review hooks, `claude -p` scripts, tooling). Header shows
  `👤user` / `🤖agent`; persisted in `state.json`, shared with `ast list
  --origin` / `ast search --origin`.
- **`t` / `T`** — toggle color theme (dark ↔ light), persisted in `state.json`
- `?` — help modal · `/` — enter search mode · `Esc` — clear/quit

**Search mode (`/` prompt)** — fzf-style, all text input lives here:

- typing — live metadata filter (id + cwd + first user msg). Unicode OK
  (한글/일본어/중국어 works via manual UTF-8 reassembly).
- `↑↓ Ctrl-P/N PgUp/Dn Home/End` — move selection while filtering
- `Backspace / Ctrl-U` — edit / wipe
- `Ctrl-A` — mark all visible (stays in search mode)
- `Ctrl-D` — toggle done (stays in search mode)
- `Ctrl-R` — rescan (stays in search mode)
- **`Enter`** — commit filter, exit search mode (filter stays applied;
  use ↑↓ + Enter in normal mode to open)
- `Tab` — escalate to full-text transcript search
- `Esc` — clear query and exit mode

**Modals** — `?` help · `v` preview · `i` auto-rescan · `Del` delete-confirm
· skip-permissions confirm (on resume without `--skip-perm`) · cmux chooser
(workspace tab vs new window) · orphan-relocate (confirm/pick/none stages
with manual-entry and placeholder escape hatches).

## Multi-agent (codex, chatgpt)

`tracker.py` keeps one `AgentSpec` per CLI in `AGENTS` (data root, transcript
discovery + parsing into `Turn`s, resume argv, live probe, capability set).
Everything else is agent-agnostic. What each agent gets:

| | claude | codex |
|---|---|---|
| transcripts | `~/.claude/projects/**/*.jsonl` | `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl` (subagent rollouts hidden, like `subagents/`) |
| list / search / show / export / TUI / done / rm | ✓ | ✓ |
| resume (`Enter`, `ast resume`) | `claude --resume <id>` | `codex resume <uuid>` (skip-perm → `--dangerously-bypass-approvals-and-sandbox`) |
| live status | pid registry + hooks | `thread-writer-locks/<uuid>.lock` flock probe: held → alive; rollout written < 90 s ago → `●`, else `◦`; `!` waiting is not detectable |
| origin (`--origin`) | `entrypoint` cli vs sdk-* | `source` cli/vscode = user; exec / mcp / subagent = agent |
| relocate | moves the transcript into `projects/<encoded-new-cwd>/` | rewrites the cwd in place — a rollout's path encodes only its start date, so the file never moves (`--keep-original` is refused: there is no second location to copy to) |
| backup / restore | archived under `projects/…` | archived under `codex/…` in the same tarball; each member restores to its own agent's root |
| subagents | `subagents/*.jsonl` beside the transcript | rollouts whose `parent_thread_id` names this thread (guardian / subagent) |
| attach / jobs / bg / hooks | ✓ | ✗ — Claude Code features with no codex counterpart, refused with `not supported for codex sessions` |

Codex messages are the rollout's `response_item`/`message` records with role
`user` or `assistant`; `developer` records and codex's own user-role wrappers
(`<environment_context>`, `# AGENTS.md instructions`, …) are dropped, so the
first user message and the transcript views show what the human typed.
Deleting a codex session (`rm` / `Del`) only unlinks the rollout; codex's own
sqlite index tolerates a missing file, but `codex delete <id>` is the
first-party way. `ast relocate` on a codex session rewrites `session_meta`,
every `turn_context`, the `world_state` snapshot and matching
`workspace_roots` entries, and deliberately leaves message text alone — a
path inside a prompt is content, not metadata. Gemini CLI is the next adapter (its `~/.gemini/tmp/<project>/chats`
JSONL format is already researched, not yet wired in).

**chatgpt** — the ChatGPT desktop app (`/Applications/ChatGPT.app`, bundle id
`com.openai.codex`) stores its conversations as ordinary codex rollouts in
`$CODEX_HOME/sessions`. They are listed as agent `chatgpt` when the recorded
cwd is one of the app's own workspace dirs — `~/Documents/Codex/<date>/<slug>`
(a chat without a project) or `$CODEX_HOME/.chatgpt-projects/<id>` (a ChatGPT
project) — and as `codex` otherwise, including a real repository opened in the
app. `originator` is not the key: it changed between app builds and is the same
for repository work. Everything but the label is codex's: resume is
`codex resume <uuid>`, status comes from the same flock probe, relocate /
subagents / backup (members under `codex/…`) behave as in the codex column.
Conversations that exist only on chatgpt.com (web / mobile) are not on disk and
are not listed. To find a ChatGPT chat: `ast search "<text>" --agent chatgpt`.

## Differences from claude-session-tracker (cst)

- **Codex sessions are first-class**: discovered, parsed, listed, searched,
  resumed, relocated, archived and restored next to Claude Code sessions
- **ChatGPT desktop app conversations** get their own `chatgpt` agent
- Backup tarballs group members by agent (`projects/…`, `codex/…`) and the
  manifest records each session's agent; `cst`-era archives still restore
- Data home is `~/.ast` (`$AST_HOME`), seeded once from `~/.cst/state.json`
- Hook commands are `ast prompt-hook` / `ast status-hook`, so the two tools'
  hook entries never collide
- **#** row-number column + **ST** glyph column + **AGENT** column +
  **PROJECT** column on every row
- **`done` / `undone` / `live` / `export` / `install-hook` / `uninstall-hook` /
  `prompt-hook` / `status-hook`** subcommands
- Top-level `--skip-perm` flag for resume; `--hide-done` to start the TUI with
  ✓ done sessions hidden
- TUI: `D`/`d`/`Ctrl-D` toggle-done, `H`/`h` hide-done, `C`/`c` cwd-only,
  `R`/`r`/`Ctrl-R` rescan, `e`/`E` export, `o`/`O` open-folder,
  `a`/`A` agent view, `i`/`I` auto-rescan, `s`/`S` column sort, `t`/`T` theme,
  `Ctrl-A` mark-all, `?` help, `v`/`V` preview
- fzf-style `/` — type + ↑↓ at once, Enter commits (doesn't auto-open),
  Ctrl-D marks while filtering, Tab escalates to full-text
- Unicode input in `/` (manual UTF-8 assembly bypasses Python curses bugs
  on some terminals like WezTerm)
- Enter opens the session in a **new window of the same terminal app** and
  brings it to the foreground (instead of replacing the TUI process)
- Orphan-relocate flow when a session's recorded cwd is missing
- ESCDELAY tuned to 25 ms so Esc is instant
Every other `cst` / `claude-sessions` feature is preserved: search with OR,
subagent transcripts, backup tar.gz + manifest, restore with conflict policy,
relocate with cwd rewrite, interactive delete, multi-select marks.

## How to use with the user

1. **Clarify scope first** for broad requests. Don't dump 80+ sessions into
   chat — ask about days, cwd prefix, status, or a keyword.
2. **Prefer `list` / `search` inside agent tool calls.** The TUI needs a real
   TTY and won't work from non-interactive Bash calls. A bare `ast` from a
   tool call already falls back to the list, but say `ast list` explicitly so
   the intent is clear. If the user wants the TUI, tell them to run `ast`
   themselves in their terminal.
3. **Run `ast` via Bash** with filters (`--limit`, `--days`, `--cwd`,
   `--status`) to keep output manageable.
4. **Render results as a table in chat**, not raw stdout. Include the 8-char
   session prefix, ST glyph, last-activity timestamp, shortened cwd
   (`~/...`), message count, and the first user message or matched snippet.
5. **Confirm destructive operations.** For `backup --delete`, `restore`,
   `relocate`, TUI delete — always run `--dry-run` / preview first, and only
   proceed after the user approves (`-y` once confirmed).
6. **For export tasks**, prefer `ast export <id> --out <dir>` over piping
   `ast show` to a file — the former preserves role headings and metadata.

## Data sources

- `~/.claude/projects/**/*.jsonl` — session transcripts (source of truth,
  append-only).
- `~/.claude/sessions/<pid>.json` — Claude Code's live-process registry.
  Each running process writes `{pid, sessionId, cwd, startedAt, version,
  kind, entrypoint}`. `ast` scans these and runs `kill -0 <pid>` to get an
  `alive` boolean: not-alive → `○` ended; alive feeds the 5-state classifier
  (working/waiting/idle resolved from the hook overlay, else the registry).
- `~/.claude/settings.json` — ast's hook entries live here under `hooks`.
- `$CODEX_HOME/sessions/**/rollout-*.jsonl` (default `~/.codex`) — Codex CLI
  transcripts and ChatGPT desktop app conversations;
  `$CODEX_HOME/thread-writer-locks/<uuid>.lock` — flock held by a
  live codex thread (ast probes it, never writes it).
- `~/.ast/index.json` (`$AST_INDEX_DIR/index.json` when set) —
  mtime/size-invalidated indexing cache (schema 6; entries carry `agent`, which
  is re-derived from the cached cwd on read for codex/chatgpt). Safe
  to delete — but it is what keeps a listing fast: a warm cache answers in
  milliseconds, while rebuilding it from scratch re-reads every transcript.
  Commands that move or overwrite a transcript (`relocate`, `restore`) drop only
  the affected entries, never the whole file.
- `~/.cst/state.json` — read once on first run to seed `~/.ast/state.json`,
  never written.
- `~/.ast/state.json` — overlay storing
  `{done: {sid: ts}, status: {sid: {state, event, ts}}, auto_rescan: {enabled, interval}, theme: "auto"|"dark"|"light", sort: {key, reverse}, origin: "all"|"user"|"agent", agent: "all"|"claude"|"codex"|"chatgpt"}`.
  Safe to delete (clears all ✓ marks, status overlay, auto-rescan / theme /
  sort / origin / agent-view prefs).
- `~/.claude/jobs/pins.json` — agent-view pin set (read-only; ast never writes).

## Do not

- Do not `Read` large `.jsonl` files directly — use `ast show` or `ast export`.
- Do not modify `~/.claude/projects/` with `rm` / `mv` / `tar` — use `ast`
  (`delete` in TUI, or `backup` / `restore` / `relocate`).
- Do not run `pick` / `--tui` from agent tool calls (no TTY). Use `list` /
  `search` and present the table yourself.
- Do not skip the `-y` / confirm step on destructive commands without first
  showing the user what will change.
- Do not call `ast prompt-hook` or `ast status-hook` by hand — they're
  invoked by Claude Code via `settings.json`.
