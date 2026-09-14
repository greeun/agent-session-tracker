# agent-session-tracker

Browse, search, resume, export, back up, and **track the live/waiting/ended/done status** of every local coding-agent session — Claude Code, OpenAI Codex and the ChatGPT desktop app in one list. Run `ast` in a terminal and the curses TUI opens; pipe or redirect it, or call it from a script, and you get the table instead.

A fork of [`claude-session-tracker`](https://github.com/greeun/claude-session-tracker) (`cst`), which tracked Claude Code alone. One `AgentSpec` adapter per agent CLI feeds a single session model, so every command works the same whichever agent wrote the session, and an AGENT column says which one did. Everything `cst` added over `claude-sessions` is kept: a STATUS column driven by the `~/.claude/sessions/<pid>.json` live-process registry, a precision overlay from Claude Code lifecycle hooks, a user-driven "task done" flag, and an fzf-style filter experience. **Stdlib-only, zero dependencies, Python 3.10+.**

---

## Why

Claude Code stores every conversation as a `.jsonl` transcript under `~/.claude/projects/`. With dozens of projects and hundreds of sessions, basic questions become painful:

- "Which sessions are actually running right now?"
- "Which one is **waiting on me** for a permission decision?"
- "Which ones did I finish and can ignore?"
- "Where's that session from two weeks ago that set up the auth migration?"
- "Was that in Claude Code, in Codex, or in a ChatGPT chat?"

`ast` answers all five in one view with zero dependencies. Codex keeps its
sessions in `~/.codex/sessions/` in a format of its own — and the ChatGPT
desktop app writes its conversations there too — so without a single browser
you end up searching two places by hand.

---

## Install

```bash
# 1. Clone the repo (anywhere; ~/.claude/skills/ keeps it discoverable)
git clone <this-repo> ~/.claude/skills/agent-session-tracker

# 2. Make executable + symlink `ast` into PATH
chmod +x ~/.claude/skills/agent-session-tracker/tracker.py
mkdir -p ~/.local/bin
ln -sf ~/.claude/skills/agent-session-tracker/tracker.py ~/.local/bin/ast

# 3. Verify
ast --version
# agent-session-tracker v1.1.0

# 4. (optional) wire the 0-token done!/undone! prompt hook + status precision layer
ast install-hook
```

Requires `~/.local/bin` in `PATH` and Python 3.10+.

### Already running `cst`?

Both install side by side — `ast` never touches `cst`'s files. They keep
separate homes (`~/.ast` vs `~/.cst`), so a session you mark ✓ done in one
does not show up as done in the other. On its first run `ast` copies
`~/.cst/state.json` into `~/.ast/` so you start from the flags and prefs you
already had; the original stays put. Hook entries also stay separate
(`ast prompt-hook` vs `cst prompt-hook`), and installing both just means two
tools record the same events into their own homes — pick one.

### Uninstall

```bash
# 1. Remove hooks from Claude Code settings (preserves foreign hooks)
ast uninstall-hook

# 2. Remove the `ast` symlink
rm ~/.local/bin/ast

# 3. (optional) Drop cache + done-state overlay
rm -rf ~/.ast

# 4. (optional) Remove the cloned repo
rm -rf ~/.claude/skills/agent-session-tracker
```

`uninstall-hook` only strips ast entries from `~/.claude/settings.json` — other tools' hooks (e.g. `csm`) are kept untouched. Your `.jsonl` transcripts under `~/.claude/projects/` are **never** touched by uninstall.

---

## Quick start

```bash
ast                           # TUI at a terminal; the table when piped/redirected
ast list                      # always the table: # + ST + LAST + SESSION + MSGS + MESSAGE + PROJECT
ast --tui                     # force the TUI even without a tty (same as `ast pick`)
ast live                      # only sessions with a live Claude Code process
ast search "auth refactor"    # full-text search across every transcript
ast done <id>                 # mark a session as done
ast done --filter "text" -y   # bulk done every session matching text (TUI Ctrl-A+d)
ast export <id>               # write transcript to ./<id>.md
ast stats                     # counts, top projects, status breakdown
ast list --sort msgs          # sort by a column (time|status|msgs|message|project; --reverse flips)
ast list --origin user        # only sessions you started (--origin agent = SDK-spawned)
ast list --agent chatgpt      # one agent's sessions (all|claude|codex|chatgpt; TUI `a` cycles)
ast jobs                      # agent-view background sessions (claude --bg)
ast --skip-perm --tui         # auto-apply --dangerously-skip-permissions on resume
ast --theme light --tui       # force a TUI color theme (auto|dark|light; `t`/`T` toggles live)
```

---

## Status glyphs

Compact one-column glyphs in the `ST` column. Resolution order in `classify_status()`: **`✓` done always wins**; otherwise a **dead** process is `○` ended (or, for a background/agent-view job, its last persisted state); a **live** process resolves from the hook **overlay** if present, else the live **registry** (`busy`→`●`, `waiting`→`!`, `idle`→`◦`), falling back to `●` when alive with no signal. So liveness gates the active states — `done > (dead⇒ended) > overlay > registry > ●`.

| Glyph | Label | Meaning |
|:---:|:---|:---|
| **●** | working | Claude is actively producing output. |
| **!** | waiting | Claude is waiting for your input or a permission decision — this is where time leaks. Detected from Claude Code's own registry (`status: "waiting"`); `ast install-hook` adds a precision overlay. |
| **◦** | idle | Turn finished, process still alive. |
| **○** | ended | Process is gone (clean exit) or was never registered. Transcript remains readable. |
| **✓** | done | You explicitly marked it done (`D`/`d`/`Ctrl-D` in TUI, `ast done <id>`, or the `done!` prompt hook). Persists in `~/.ast/state.json`. |

Status is **computed fresh on every command invocation** — there is no background daemon. The TUI auto-rescans every 10s by default (configurable / off via `i`).

**Self-healing:** when the hook overlay is installed and reports `waiting`/`working` but the registry shows a newer `idle` event, the stale overlay is overridden and the glyph collapses to `◦` to avoid a stuck `!`.

---

## Multi-agent: Codex CLI and ChatGPT app sessions

Since 1.18 `ast` is not Claude-only. `tracker.py` keeps one `AgentSpec` per
agent CLI in `AGENTS` — data root, transcript discovery, parsing into a shared
`Turn` stream, resume command, live probe, capability set — and everything
above that table (loader, cache, status, CLI, TUI) is agent-agnostic. An
**AGENT** column on every row says which CLI wrote the session; `--agent` /
the TUI `a` key narrow the view.

| | claude | codex |
|:--|:--|:--|
| Transcripts | `~/.claude/projects/**/*.jsonl` | `$CODEX_HOME/sessions/YYYY/MM/DD/rollout-<ts>-<uuid>.jsonl` (default `~/.codex`; subagent rollouts hidden like `subagents/`) |
| list / search / show / export / TUI / done / rm | ✓ | ✓ |
| Resume (`Enter`, `ast resume`) | `claude --resume <id>` | `codex resume <uuid>` (skip-perm → `--dangerously-bypass-approvals-and-sandbox`) |
| Live status | pid registry + hook overlay | flock probe on `thread-writer-locks/<uuid>.lock`: held → alive; rollout written < 90 s ago → `●`, else `◦`. `!` waiting is not detectable for codex |
| Origin (`--origin`) | `entrypoint` cli vs `sdk-*` | `source` cli / vscode → user; exec / mcp / subagent → agent |
| Relocate (`ast relocate`) | Moves the transcript into `projects/<encoded-new-cwd>/` | Rewrites the recorded cwd in place — a rollout's path encodes only its start date, so the file never moves. `--keep-original` is refused rather than ignored: there is no second location to copy to, so honoring it would mean rewriting the very file it asks to preserve |
| Backup / restore | Archived under `projects/…` | Archived under `codex/…` of the same tarball; each member restores to its own agent's root |
| Subagents (`ast subagents`) | `subagents/*.jsonl` beside the transcript | Rollouts whose `parent_thread_id` names this thread (codex's guardian / subagent threads) |
| attach / jobs / bg / hooks | ✓ | ✗ — Claude Code features with no codex counterpart (`not supported for codex sessions`) |

Codex turns are the rollout's `response_item`/`message` records with role
`user` or `assistant`; `developer` records and codex's own user-role wrappers
(`<environment_context>`, `# AGENTS.md instructions`, …) are dropped so the
MESSAGE column and transcripts show what the human typed. Deleting a codex
session only unlinks the rollout (codex's sqlite index tolerates that;
`codex delete <id>` is the first-party route). Relocating one rewrites the cwd
in `session_meta`, every `turn_context`, the `world_state` snapshot and any
`workspace_roots` entry that matched the old path — message text is left
alone, since a path inside a prompt is content rather than metadata. Gemini
CLI is the next adapter.

### ChatGPT desktop app

The ChatGPT desktop app (`/Applications/ChatGPT.app`, bundle id
`com.openai.codex`) runs on codex's thread store: a conversation there is an
ordinary rollout under `$CODEX_HOME/sessions`, in the codex format. `ast` lists
those threads under their own **`chatgpt`** agent, so `--agent chatgpt` and the
TUI `a` key separate them from codex work.

The split follows the cwd the thread was recorded in, not the app that wrote it:

| Recorded cwd | Agent |
|:--|:--|
| `~/Documents/Codex/<date>/<slug>` — a chat without a project | `chatgpt` |
| `$CODEX_HOME/.chatgpt-projects/<project-id>` — a chat inside a ChatGPT project | `chatgpt` |
| Anything else, including a real repository opened in the app | `codex` |

The rollout's `originator` looks like the obvious key but is not usable: it
changed between app builds (`Codex Desktop` → `codex_work_desktop`) and stays
the same when the app works on a repository. Everything below the label is
codex's — parsing, resume (`codex resume <uuid>`), the flock live probe,
relocate, subagents and backup (members stay under `codex/…`, so archives
remain restorable by earlier builds). The label is re-derived whenever the
index is read, so upgrading needs no re-index. Conversations that exist only on
chatgpt.com (web or mobile) have no rollout on disk and are not listed.

---

## CLI reference

### Top-level flags

| Flag | Effect |
|---|---|
| `-V`, `--version` | Print version and exit |
| `--tui` | Launch the TUI (same as `ast pick`) |
| `--skip-perm` | When resuming (TUI or `resume`), pass `--dangerously-skip-permissions` to `claude` automatically. Without it, the TUI shows a per-resume confirmation. |
| `--hide-done` | Start the TUI with `✓` done sessions hidden (toggle in-TUI with `H`). |
| `--theme auto\|dark\|light` | TUI color theme. `auto` sniffs `COLORFGBG`, else dark. `t`/`T` toggles live and persists. |

### `ast list` — default table view

```bash
ast list [--limit 30] [--cwd PREFIX] [--days N]
         [--status working|waiting|idle|ended|done|active]
         [--sort time|status|msgs|message|project] [--reverse]
         [--origin all|user|agent] [--agent all|claude|codex|chatgpt] [--json]
```

```
agent-session-tracker v1.1.0
  #  ST  AGENT    LAST ACTIVITY     SESSION   MSGS  MESSAGE                   PROJECT
  1  ●   claude   2026-05-24 01:17  960faaa8   261  claude-sessions 는…       ~/.claude/skills
  2  !   claude   2026-05-24 01:16  06d116f7    34  proceed? (y/N)            ~/project/url-shortener
  3  ◦   codex    2026-05-24 01:15  019cb053    12  실패건을 해결하라.        ~/project/url-shortener
  4  ✓   chatgpt  2026-05-24 01:15  01a07c61     4  서비스기획의 역할은?      ~/Documents/Codex/2026-05-24/new-chat
  5  ○   claude   2026-05-23 21:24  afbd9e28   241  pnpm 적용 되어 있는가?    ~/project/url-shortener
```

- Row numbers start at 1; column auto-expands for 1000+ sessions.
- `--status active` is a backward-compatibility alias for `working`.
- Combinable: `--cwd ~/project --status waiting --days 7`.
- **Sort:** `--sort time|status|msgs|message|project` (default `time`, newest-first).
  `--reverse` flips direction. `status` orders working→waiting→idle→ended→done;
  `message` orders by the first user message text (A→Z); ties always break by
  recency. An explicit `--sort` is a one-off; with no
  `--sort` the saved TUI sort preference is used. Sort runs **before** `--limit`,
  so the slice is the top-N of the chosen order.
- **Origin:** `--origin all|user|agent` (default `all`) splits sessions by who
  started them, read from the transcript's `entrypoint` field. `user` = typed
  into a terminal (`cli` — agent-view `bg` jobs count, a human dispatched
  them); `agent` = SDK-spawned (`sdk-py`/`sdk-cli`/`sdk-ts`: security-review
  hooks, `claude -p` scripts, tooling), which can otherwise flood the list.
  A session whose entrypoint is missing or unrecognised reads as `user`, so an
  unprovable origin is never silently hidden. An explicit `--origin` is a
  one-off; with no flag the saved TUI preference (`f`/`F`) is used, and an
  active filter is announced as `[origin:user]` in the summary line. The same
  flag works on `ast search`.
- **Agent:** `--agent all|claude|codex|chatgpt` (default `all`) shows one
  agent's sessions (`chatgpt` = ChatGPT desktop app conversations, see above). An explicit `--agent` is a one-off; with no flag the view the TUI
  `a` key last saved is used, announced as `[agent:codex]` in the summary
  line. Same flag on `ast search` and `ast pick`.
- **`--json`** emits the list as machine-readable JSON instead of the table
  (the contract consumed by the cst.app macOS companion). Each session carries
  `entrypoint`, `origin` and `agent`.

### `ast pick` / `--tui` — interactive TUI

```bash
ast pick [--cwd PREFIX] [--days N] [--agent all|claude|codex|chatgpt]
ast --tui            # equivalent
```

Requires a real TTY. Won't work from non-interactive agent tool calls.

### `ast search "<query>"` — full-text transcript search

```bash
ast search "nextjs|remix" --limit 10 -i --cwd ~/project
```

- `|` = OR. `-i` / `--ignore-case` = case-insensitive.
- Each hit shows up to 3 matched snippets with the session's status glyph and 8-char id.

### `ast show <id>` — print a session transcript

```bash
ast show 960faaa8 --max-chars 500 --with-subagents
ast show 960faaa8 --head-chars 4000        # fast head preview of a huge session
```

Header shows **Status**, cwd, first/last timestamps, message count, subagent count.

- `--max-chars N` truncates each message; `--head-chars N` caps the **total**
  transcript output and stops reading the file early (0 = unlimited) — the
  fast-preview path used by cst.app on multi-hundred-MB transcripts.

### `ast export <id>` — write transcript to file

```bash
ast export 960faaa8                       # writes ./960faaa8….md
ast export 960faaa8 --format txt           # writes ./960faaa8….txt
ast export 960faaa8 --out ~/exports/       # writes <id>.md into the directory
ast export 960faaa8 --out ~/exports/x.md   # writes to the exact file
```

Formats: `md` (default, with role headings) · `txt` (plain). The `--out` argument accepts a directory or a full path.

### `ast resume <id>` — emit `cd + claude --resume` command

```bash
ast resume 960faaa8 --print-only | bash
ast --skip-perm resume 960faaa8 --print-only | bash   # add the skip-perm flag
ast resume 960faaa8 --spawn                # actually open/attach in a new terminal
```

`--spawn` opens the session itself instead of printing the command — same logic
as the TUI `Enter` key (focus a live session's window, `claude attach` for a
background job, else spawn `claude --resume` in a new terminal window). Used by
cst.app.

Both `--spawn` and `ast open` pick the terminal app from `$TERM_PROGRAM`.
`--terminal NAME` overrides that choice (`wezterm` · `iterm` · `ghostty` ·
`kitty` · `alacritty` · `terminal`) — GUI callers such as cst.app have no
`$TERM_PROGRAM` and would otherwise always fall back to Terminal.app. An
unknown name, or one whose CLI is not installed, also falls through to
Terminal.app.

```bash
ast resume 960faaa8 --spawn --terminal wezterm
```

### `ast open <id>` — open the session's folder in a new terminal

```bash
ast open 960faaa8                      # plain shell at the session's cwd
ast open 960faaa8 --terminal wezterm   # force the terminal app
```

The CLI form of the TUI `o` key. Opens a new terminal window at the session's
recorded working directory as a plain shell — no `claude` command is run, so
nothing is resumed or attached. Used by cst.app.

### `ast done <id>` / `ast undone <id>` — done flag

```bash
ast done 06d116f7      # ✓ Marked done
ast done 06d116f7 9c01a2b3          # multiple ids at once
ast undone 06d116f7    # ✓ Cleared done
```

Bulk mode — the TUI "`/` filter → `Ctrl-A` → `d`" flow as one command.
`--filter` matches a case-insensitive substring of `sessionId + cwd + first
user message` (exactly like the TUI filter); already-done sessions are
excluded and ● working ones are skipped unless `--force`:

```bash
ast done --filter "heyhey"                 # list matches, confirm, mark
ast done --filter "heyhey" -y              # skip the prompt (scripts)
ast done --filter "버그" --days 7 --status ended
ast done --filter "x" --cwd ~/project/old  # narrow by cwd prefix
```

Non-interactive callers must pass `-y/--yes`, otherwise the command refuses
instead of hanging on the confirmation prompt.

### `ast live [--all]` — live process registry

```bash
ast live          # only PIDs that respond to kill -0
ast live --all    # include stale registry entries (dead PIDs too)
```

### `ast backup` / `ast restore` — archive old sessions

```bash
ast backup --days 90 --dry-run
ast backup --days 90 --delete -y
ast backup --before 2026-01-01 --cwd ~/project/old --out /tmp/old.tar.gz
ast restore ~/.ast/backups/sessions-20260524.tar.gz --on-conflict rename -y
```

`backup` options:

| Flag | Meaning |
|---|---|
| `--days N` | Archive sessions whose last activity is older than N days (default: 90 when neither `--days` nor `--before` is given) |
| `--before YYYY-MM-DD` | Archive sessions before a specific date (overrides `--days`) |
| `--cwd PREFIX` | Restrict to sessions under this cwd |
| `--out PATH` | Output archive path (default: `~/.ast/backups/sessions-<timestamp>.tar.gz`) |
| `--delete` | Remove originals after a successful archive |
| `--force` | Allow `--delete` even if some files failed to archive |
| `--dry-run` | Preview without writing |
| `-y` / `--yes` | Skip the confirmation prompt |

`restore` conflict policies: `skip` (default) · `overwrite` · `rename` (writes `<id>.restored-<ts>.jsonl`).

### `ast relocate <id> <new-cwd>` — fix a session's recorded cwd

```bash
ast relocate 960faaa8 ~/project/real-folder --dry-run
ast relocate 960faaa8 ~/project/real-folder -y
ast relocate 960faaa8 ~/project/real-folder --keep-original --force
```

Rewrites `cwd` on every event in the JSONL and moves the file into the new project directory. Subagent transcripts under `<parent-id>/subagents/` move too.

| Flag | Meaning |
|---|---|
| `--keep-original` | Copy instead of move (originals preserved) |
| `--force` | Proceed even if the new cwd doesn't exist on disk |
| `--dry-run` | Show the rewrite plan; no changes |
| `-y` / `--yes` | Skip confirmation |

### `ast rm <id> [<id> ...]` — unlink session transcript(s)

```bash
ast rm 960faaa8 --dry-run       # show what would be removed
ast rm 960faaa8 -y              # remove without prompting
ast rm 960faaa8 3a7f21bc -y     # remove multiple ids in one call
```

Unlinks the transcript `.jsonl` and purges its cache/done-flag traces — the
same operation as the TUI `Del` key, scriptable. **Only the transcript is
removed: a live background process keeps running** (stop it with `ast stop
<id>` first). Non-interactive callers must pass `-y` (it refuses rather than
hang waiting for a tty); `--force` also skips confirmation (single-id form
only — bulk mode below handles `--force` differently).

### Bulk delete

Remove many sessions at once — the TUI's `/` filter → `Ctrl-A` → `Del` as one command:

```bash
ast rm --filter "prototype"              # id + cwd + first message substring
ast rm --cwd ~/proj/scratch --status done
ast rm --status ended --older-than 90    # untouched for 90+ days
ast rm --status ended --before 2026-01-01
ast rm --filter test --days 7 --dry-run  # last 7 days, preview only
```

Live sessions (● working / ! waiting) are skipped — a running Claude process
keeps appending to the transcript it holds open, so unlinking it loses whatever
comes next. This also catches a **✓ done session whose process is still alive
and working/waiting** — done is a bookmark flag, not a stop signal, so it's
skipped too (the row still displays ✓). Pass `--force` to include live
sessions in the target set. Unlike the single-id form above, in bulk mode
`--force` does **not** skip the confirmation prompt — pass `-y`/`--yes` for
that, or combine both to include live sessions *and* skip confirmation.
`--days` / `--older-than` / `--before` are mutually exclusive, and `--days N`
means *the last N days* (same as `ast list`), **not** "older than N days" —
that's the opposite of `ast backup --days N`; use `--older-than` here for
"older than N days".

Non-interactive callers must pass `-y`. Deleting only unlinks the transcript —
a background session's process keeps running; stop it with `ast stop <id>`.

### `ast stats [--top N]` — overview

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

### `ast subagents <parent-id>` — Task-tool subagents

Lists every subagent dispatched from a parent session with `agentType`, description, message count, and first prompt.

### Background (agent-view) sessions — `claude --bg` / `claude agents`

ast also surfaces the supervisor-managed **background** sessions that the
agent-view dispatches (`claude --bg`). These are addressed by their short
`daemonShort` id, so ast drives the real `claude` CLI instead of forking the
transcript.

```bash
ast jobs                  # list EVERY agent-view job (incl exec/transcript-less),
                          #   with a daemon-status header; * = pinned in agent-view
ast bg "<prompt>" [--name N]  # dispatch a NEW background session (claude --bg)
ast stop <id>             # stop a live bg process (claude stop <short>) — the only
                          #   way to actually stop it; ast's Del just unlinks the transcript
ast logs <id>             # peek a bg session's recent output (claude logs <short>)
```

- **Resume/Enter attaches.** For a job-backed row, `ast resume` and TUI `Enter`
  run `claude attach <short>` (live supervisor session: catch-up + live stream)
  instead of a transcript fork.
- **Row badges** (appended to the PROJECT column in `ast list` / TUI rows):
  `[bg]`, `[exec]`, `[bg ⎇<branch>]` (git-worktree branch), `[bg ∙]` (process
  exited but still attach/respawn-able), `[PR #1]` / `[PR #1,3]` (PR/MR URLs
  found in the transcript), and a leading `*` for sessions pinned in agent-view
  (read from `~/.claude/jobs/pins.json`; ast never writes it).

### Hook commands

| Command | When you'd run it |
|---|---|
| `ast install-hook [--settings PATH]` | Once, to wire the precision layer into `~/.claude/settings.json`. Idempotent; preserves foreign hooks. |
| `ast uninstall-hook [--settings PATH]` | To remove ast entries from settings; foreign hooks kept. |
| `ast prompt-hook` | *Internal* — Claude Code invokes it on `UserPromptSubmit`. Don't run by hand. |
| `ast status-hook [event]` | *Internal* — Claude Code invokes it on lifecycle events. Don't run by hand. |

See [Hooks](#hooks) below.

---

## TUI (`ast --tui`)

A curses picker with fzf-style filter, status glyphs, modals, and action keys. **Two modes** — normal (shortcuts) and search (typing query).

### Normal mode

| Key | Action |
|---|---|
| `↑↓` / `Ctrl-P` `Ctrl-N` | Move one row |
| `PgUp` / `PgDn` / `Home` / `End` | Page / jump |
| **`Enter`** | **Open selected session in a new terminal window** (same terminal app as your current one). If the session's cwd has moved, an orphan-relocate modal helps you fix it. |
| `Space` | Toggle mark on current row |
| `Ctrl-A` | Toggle marks on **all** visible rows |
| `Ctrl-X` | Clear all marks |
| **`v`** / **`V`** | Preview the focused session (scrollable modal; the metadata header stays pinned at the top). Inside: `↑↓/j/k` scroll · `PgUp/PgDn/Space` page · `g/G` top/bottom · `←/→` prev/next session · `d/Ctrl-D` toggle done on previewed session (scroll position kept) · `Del` delete previewed session (confirm in place; cancel returns to preview) · `q/Esc/v` close |
| **`e`** / **`E`** | Export focused session to `./<id>.md` (toast shows the path) |
| **`o`** / **`O`** | Open the focused session's **folder** in a new terminal window — a plain interactive shell at the recorded cwd, no `claude` command (same terminal-app detection as `Enter`; cmux tab/window chooser inside cmux; a missing cwd fails with a `ast relocate` hint) |
| **`D`** / **`d`** / **`Ctrl-D`** | Toggle **done** on current row (or all marked rows). Persists. |
| **`H`** / **`h`** | Toggle hide-done — hide/show ✓ rows (no `Ctrl-H` alias — that's Backspace) |
| **`C`** / **`c`** | Toggle cwd-only — show only sessions under the TUI's launch cwd (NFC-normalized prefix match) |
| **`R`** / **`r`** / **`Ctrl-R`** | Rescan sessions + live-process registry. The footer counts the scan while it runs — `Rescanning… 42% (994/2370)`. An auto-rescan tick shows the same counter once it has run past ~0.35s (a warm, fully-cached scan finishes before that and stays silent). |
| **`a`** / **`A`** | Cycle the agent view: `all → claude → codex → chatgpt` (`A` backwards). Header shows `⚙codex` when not `all`. Persisted, shared with `ast list --agent`. |
| **`i`** / **`I`** | Auto-rescan interval popup (Off / 5 / 10 / 30 / 60 / 120s; default ON 10s, persisted in `state.json`; `curses.beep()` + a sticky TUI toast when a session newly enters `!` waiting — no macOS desktop notification). Was `a` before 1.18. |
| **`s`** | Cycle sort column in on-screen column order: `status → time → msgs → message → project` (resets to the column's natural direction). Header shows `sort:<col>▼/▲` and highlights the active column. Persisted. |
| **`S`** | Reverse the current sort direction. Persisted. |
| **`f`** | Cycle origin filter: `all → user → agent`. `user` = started from a terminal (agent-view `bg` jobs included); `agent` = SDK-spawned (security-review hooks, `claude -p`, tooling). Header shows `👤user` / `🤖agent`. Persisted, shared with `ast list --origin`. |
| **`F`** | Cycle the origin filter backwards (`all → agent → user`). Persisted. |
| **`t`** / **`T`** | Toggle color theme (dark ↔ light). Persisted in `state.json`. |
| `Del` / `Fn+Delete` | Delete marked/current session(s) (confirmation modal) |
| `?` | Help modal |
| `/` | Enter search mode |
| `Esc` | Clear filter/search if any; otherwise quit |

> **Plain ASCII letters that aren't bound do nothing in normal mode.** All free text input lives behind `/`.

### Search mode (after pressing `/`)

A cursor appears on the prompt line. Live filtering happens as you type.

| Key | Action |
|---|---|
| *letters* (any Unicode — Korean/Japanese/Chinese OK) | Live metadata filter (id + cwd + first user message) |
| `↑↓` / `Ctrl-P` `Ctrl-N` / `PgUp PgDn` / `Home End` | Move selection **while filtering** |
| `Backspace` / `Ctrl-U` | Edit / wipe the query |
| **`Enter`** | Commit filter, exit search mode (filter stays applied) |
| `Ctrl-A` | Toggle marks on all visible (stays in search mode) |
| `Ctrl-D` | Toggle done on current row (stays in search mode) |
| `Ctrl-R` | Rescan (stays in search mode) |
| `Tab` | Escalate to full-text transcript search for the current query |
| `Esc` | Clear query and exit search mode |

### Header bar

```
 agent-session-tracker v1.1.0  12/563  ●3 !1 ◦0 ○558 ✓1  ⟳10s  sort:time▼  👤user  ⚙codex  [✓ hidden]  [📂 ~/project]   ? help  Enter open  o folder  / filter  s sort  f origin  a agent  i auto  ^R rescan  ^D mark✓  H hide✓  C cwd  Esc quit
```

- `12/563` — visible rows / total sessions
- `●3 !1 ◦0 ○558 ✓1` — per-status counts in the current view
- `⟳10s` — auto-rescan interval (or `⟳off`)
- `sort:time▼` — active sort column + direction (`▼` desc / `▲` asc); the matching column header is highlighted
- `👤user` / `🤖agent` — shown only when the origin filter is not `all`
- `⚙codex` — shown only when the agent view is not `all`
- `[✓ hidden]` — shown only when hide-done is on
- `[📂 ~/project]` — shown only when cwd-only is on

### Prompt line (below header)

Reflects the current state:
- Idle: `(press / to filter, ? for help)` dimly
- Filter active: `filter=abc   (/ to edit, Esc/clear)` dimly
- Full-text search active: `text=auth→14   (/ to edit, Esc/clear)` dimly
- Search mode active: `/ <query>█` bold with cursor

### Modal dialogs

- **Help (`?`)** — scrollable cheat-sheet.
- **Preview (`v`)** — transcript with role colors, full message text (wrapped). The metadata header (Session / Status / Cwd / Branch / Started) is pinned above the rule and never scrolls away, and its Status row is colored by state like the list's ST column (● green · ! red · ◦ cyan · ○ dim · ✓ magenta); `d`/`Ctrl-D` toggles done in place, keeping the scroll position and any active search, and inverts the Status row for one keypress so the change is visible. The list still visible around the modal box follows the same toggle right away, and shows exactly what you will see once the modal closes: the row's ST glyph, the header's ✓/○ counts, a status sort's order, and — with `H` (hide ✓) on — the row leaving the list entirely. The modal keeps previewing the session it was opened on either way, and `←`/`→` still walks the sessions that were listed when it opened; `Del` deletes in place (with confirmation).
- **Auto-rescan interval (`i`)** — Off / 5 / 10 / 30 / 60 / 120s. `1`–`6` jumps directly to an option; Enter applies; saved to `state.json`.
- **Delete confirmation (`Del`)** — `y` confirm · `n/Esc/Enter` cancel · shows up to 5 victims.
- **Skip-permissions confirmation** — appears on `Enter` resume when you didn't pass `--skip-perm`. `y/Y/Enter` resumes with the flag · `n/N` without · `Esc` cancels.
- **cmux chooser** — only if ast is running inside cmux. `t/T/Enter` opens in a cmux workspace tab · `w/W` in a new cmux window · `Esc` cancels.
- **Orphan-relocate flow** — when the session's recorded cwd no longer exists, ast scans (`mdfind` on macOS, `fd` if installed, `os.walk` fallback) for a likely new home and offers candidates:
  - **Confirm** (one high-confidence match) — `y/Y/Enter` use it · `e/E` enter a path · `o/O` placeholder · `Esc` cancel
  - **Pick** (several candidates) — `↑↓` navigate · `Enter` use · `e/o/Esc` as above
  - **None** — `e/E` enter a path · `o/O` placeholder · `Esc` cancel

---

## Opening a session

Pressing `Enter` in the TUI spawns `claude --resume <sid>` in a **new window of the terminal app you're already using** (detected via `$TERM_PROGRAM`):

| `$TERM_PROGRAM` | Backend | Foreground activation |
|---|---|---|
| `iTerm.app` | iTerm2 AppleScript (`create window with default profile`) | `activate` in-script |
| `Apple_Terminal` | Terminal.app AppleScript (`do script`) | `activate` in-script |
| `WezTerm` | `wezterm start --cwd ... -- bash -lc "..."` | `osascript` activates WezTerm |
| `ghostty` | `ghostty --working-directory ... -e bash -lc "..."` | `osascript` activates Ghostty |
| `kitty` | `kitty --detach --directory ... bash -lc "..."` | `osascript` activates kitty |
| `Alacritty` | `alacritty --working-directory ... -e bash -lc "..."` | `osascript` activates Alacritty |
| `WarpTerminal` | Falls back to Terminal.app (Warp has no scriptable command API) | — |
| `vscode` / `cursor` | Falls back to Terminal.app (IDE terminal → external window) | — |
| Unknown | Falls back to Terminal.app | — |
| Linux | `$TERMINAL` → `gnome-terminal` / `konsole` / `alacritty` / `kitty` / `wezterm` / `xterm` in order | — |
| Inside cmux | Workspace tab or new cmux window (you pick) | — |

**The absolute path to `claude`** is resolved in the parent process via `shutil.which("claude")` and embedded in the spawned command — this bypasses PATH mismatches in the new shell (nvm/volta/asdf setups often break naive `cd && claude` invocations).

**If `claude` fails**, the new window stays open with a visible error:
```
[ast] 'claude --resume' failed (exit 127)
[ast] claude binary: /Users/you/.local/bin/claude
[ast] press Enter to close this window...
```

---

## Hooks

`ast install-hook` wires Claude Code lifecycle hooks into `~/.claude/settings.json`. The hooks are **optional** — `ast` works without them — but they give you:

1. A **zero-token** `done!` / `undone!` prompt command.
2. A **precision layer** for the `!` waiting glyph (faster/finer transitions, cleaner `◦` idle signal).

### `done!` / `undone!` prompt command (0 tokens)

After `install-hook`, inside any Claude Code session you can type these as the **entire** prompt:

| You type | Effect |
|:--|:--|
| `done!` | mark **this** session ✓ done (uses the hook payload's `session_id`) |
| `done! <id>` | mark that session (8-char prefix OK) |
| `undone!` / `undone! <id>` | clear the done flag |
| `/done`, `/undone` | legacy aliases — still matched, but a leading `/` often opens Claude Code's slash-command palette and blocks submission. Prefer the bang forms. |

The trigger must be the **entire** prompt. Sentences like "I am done!" or "done! great work" are *not* matched and go to the model normally. The hook runs the toggle locally and **blocks the prompt before it reaches the model** — so the model is never invoked, **zero tokens**.

### What `install-hook` registers

| Event | Command | Timeout | Purpose |
|---|---|---|---|
| `UserPromptSubmit` | `ast prompt-hook` | 25s | Intercept `done!`/`undone!` |
| `UserPromptSubmit` | `ast status-hook` | 10s | Record `working` state |
| `Notification` | `ast status-hook` | 10s | Record `waiting` state |
| `PermissionRequest` | `ast status-hook` | 10s | Record `waiting` state |
| `Stop` | `ast status-hook` | 10s | Record `idle` state |
| `SessionEnd` | `ast status-hook` | 10s | Clear status overlay |

Equivalent manual entry (one event shown):
```json
{ "hooks": { "UserPromptSubmit": [
  { "matcher": "", "hooks": [
    { "type": "command", "command": "ast prompt-hook", "timeout": 25 },
    { "type": "command", "command": "ast status-hook",  "timeout": 10 }
  ] } ] } }
```

### Operational notes

- **`!` works without hooks.** Claude Code 2.x already writes `status:"waiting"` / `waitingFor` into `~/.claude/sessions/<pid>.json`; `ast` reads it directly.
- **Idempotent install.** Re-running `ast install-hook` strips ast entries first, then re-adds them. Foreign hooks are untouched — including `cst`'s, since ast only claims commands ending in `ast prompt-hook` / `ast status-hook`.
- **Self-healing overlay.** If the registry reports a newer `idle` event than the last hook event, a stale `!` will collapse to `◦` automatically.
- **cmux compatibility.** cmux injects its own Claude hooks via `--settings`; Claude Code merges them additively with `~/.claude/settings.json`, so ast's hooks still fire on the same session id — no conflict.
- **Hot reload.** Code changes to `tracker.py` take effect immediately (each hook invocation re-runs `ast`). Only `settings.json` changes need `/hooks` opened once (or a restart) so the settings watcher reloads.

---

## Data files

| Path | Purpose | Safe to delete? |
|---|---|---|
| `~/.claude/projects/**/*.jsonl` | Session transcripts (Claude Code's own data) | **No** — your history |
| `~/.claude/sessions/<pid>.json` | Claude Code's live-process registry (read-only) | Leave alone |
| `~/.claude/settings.json` | Claude Code settings (ast writes hook entries here) | No — `ast uninstall-hook` only removes ast entries |
| `~/.claude/jobs/<short>/state.json` | Agent-view background-job state (read-only) | Leave alone |
| `~/.claude/jobs/pins.json` | Agent-view pin set (read-only; ast never writes) | Leave alone |
| `$CODEX_HOME/sessions/**/rollout-*.jsonl` | Codex CLI transcripts, plus the ChatGPT desktop app's conversations (default `~/.codex`; read-only) | Leave alone |
| `$CODEX_HOME/thread-writer-locks/<uuid>.lock` | Codex's per-thread writer lock — ast probes the flock for liveness (read-only) | Leave alone |
| `~/.ast/index.json` | mtime/size-invalidated session-metadata cache (schema 6, entries carry `agent`) | Yes — regenerates on next run |
| `~/.ast/state.json` | done flags + hook status overlay + user prefs (auto-rescan, theme, sort, origin, agent view) | Yes — clears all `✓` marks, overlay, and prefs |

All `~/.claude/...` paths above honor **`$CLAUDE_CONFIG_DIR`** (same convention
as Claude Code itself): when set, ast reads `projects/`, `sessions/`, `jobs/`,
`daemon/` and `settings.json` from that root instead of `~/.claude`. Codex
paths follow **`$CODEX_HOME`** (default `~/.codex`) the same way.

ast's own files (`index.json`, `state.json`, and archives written by `backup`
without `--out`) live under **`~/.ast`**, overridable with **`$AST_HOME`**. On
its first run ast copies `~/.cst/state.json` there once if it exists, so done
flags and prefs carry over from `cst`; the original is left untouched because
`cst` keeps using it.

### Indexing speed

`index.json` is what makes a listing fast. With it warm, every command — and
every TUI rescan — answers in milliseconds, because only the transcripts whose
mtime or size moved are read again. Building it from cold has to read every
transcript, so ast spreads that across worker processes: measured on 2,370
sessions totalling 3.9GB, a cold index takes ~2.5s instead of ~16.6s. A warm
rescan stays single-process, since forking for a handful of changed files costs
more than it saves.

**`$AST_JOBS`** overrides the choice: `AST_JOBS=1` keeps indexing sequential
(useful on a machine where you would rather ast not take several cores), and a
higher number pins the worker count. Unset, ast uses up to 12 workers, never
more than the core count.

Deleting `index.json` is safe but means the next run pays for a full cold
index. `relocate` and `restore` no longer delete it — they drop only the
entries for the transcripts they touched.

#### Keeping the index out of a synced folder

If `~/.ast` lives in a synced folder (Synology Drive, Dropbox, iCloud), set
**`$AST_INDEX_DIR`** to move `index.json` somewhere local:

```bash
export AST_INDEX_DIR="$HOME/.cache/ast"
```

`state.json` — your ✓ done flags and prefs — stays in the home and keeps
syncing, which is the part worth sharing between machines. `index.json` is the
part that is not: it is rewritten on every rescan that sees a changed
transcript, so the sync daemon uploads it over and over, and two machines
writing it leave `index_<host>_…_Conflict.json` files behind. Sharing it gains
nothing either, because its keys are absolute transcript paths and its values
are mtimes — if the sync does not preserve mtime, every entry misses on the
other machine anyway.

Unset, `AST_INDEX_DIR` defaults to the home itself, so nothing changes for an
existing install and no warm cache is thrown away.

### `state.json` schema

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

`status` is populated by `ast status-hook` (only when hooks are installed).
`auto_rescan` is set from the TUI `i` popup, `theme` from `t`/`T` (or `--theme`),
`sort` from the TUI `s`/`S` keys, `origin` from `f`/`F`, `agent` from `a`/`A`.
Deleting `state.json` clears all of them.

---

## Workflows

### "What's running right now?"

```bash
ast live
ast list --status working
ast list --status waiting    # who's blocked on me?
```

### "Clean up anything I finished"

```bash
ast --tui
# /      → type keyword to filter (live metadata match)
# Enter  → commit filter (exit search mode, keep filter)
# Ctrl-A → mark all visible
# D      → mark all marked rows done
# H      → hide ✓ rows
# R      → rescan
```

### "Find that session where I set up the auth migration"

```bash
ast search "auth migration" -i --limit 5
# or in TUI:
#   / → type "auth" → Tab (full-text scan) → ↑↓ → Enter opens new window
```

### "Export a transcript to share"

```bash
ast export 960faaa8 --out ~/exports/
# Or from the TUI: focus the row, press `e`.
```

### "Archive everything older than 90 days"

```bash
ast backup --days 90 --dry-run        # preview
ast backup --days 90 --delete -y      # archive + remove originals
ast backup --before 2026-01-01 -y     # by absolute date instead
```

### "I launched Claude in the wrong directory"

```bash
ast relocate <id> ~/project/actual-folder --dry-run
ast relocate <id> ~/project/actual-folder -y
# Or just press Enter on the row in the TUI — if the cwd is missing,
# ast opens the orphan-relocate flow and helps you find/pick the new home.
```

---

## Comparison

### vs. `claude-session-tracker` (cst)

Same tool, one agent wider. `cst` tracks Claude Code; `ast` tracks Claude Code
and Codex through one adapter layer, and carries that all the way through the
data commands:

- Codex sessions are discovered, parsed, listed, searched, resumed, relocated,
  archived and restored alongside Claude Code ones
- ChatGPT desktop app conversations, which the app stores among codex's
  rollouts, are listed as their own `chatgpt` agent
- Backup tarballs group members per agent (`projects/…`, `codex/…`) and the
  manifest records each session's agent; archives written by `cst` still
  restore unchanged
- `ast relocate` works on a codex session by rewriting its recorded cwd in
  place, and `ast subagents` lists codex's spawned guardian threads
- Data home is `~/.ast` (`$AST_HOME`), seeded once from `~/.cst/state.json`
- Hook commands are `ast prompt-hook` / `ast status-hook`, so both tools' hook
  entries can coexist in `settings.json`

Fixed along the way: in `cst`, a single codex session older than the backup
cutoff aborted `backup` outright (it resolved every transcript path relative
to `~/.claude/projects`).

### vs. `claude-sessions`

`ast` is a superset. Every `claude-sessions` subcommand is preserved, plus:

- **#** row-number column + **ST** glyph column + **AGENT** column + **PROJECT** column on every row
- **Multi-agent:** Codex CLI sessions and ChatGPT desktop app conversations listed, searched, shown, exported, resumed and status-tracked next to Claude's (`--agent`, TUI `a`)
- **`done`**, **`undone`**, **`live`**, **`export`**, **`bg`** / **`jobs`** / **`stop`** / **`logs`** (agent-view background sessions), **`install-hook`** / **`uninstall-hook`** / **`prompt-hook`** / **`status-hook`** subcommands
- `ast list --sort time|status|msgs|message|project [--reverse]` column sort
- `ast list --origin all|user|agent` (and `ast search --origin`) — hide SDK-spawned sessions, or show only those
- TUI keys: `D/d/Ctrl-D` (toggle done) · `H/h` (hide done) · `C/c` (cwd-only) · `R/r/Ctrl-R` (rescan) · `e/E` (export) · `o/O` (open folder) · `a/A` (agent view) · `i/I` (auto-rescan) · `s`/`S` (column sort) · `f`/`F` (origin filter) · `t/T` (theme) · `Ctrl-A` (mark all) · `?` (help) · `v/V` (preview; `←/→` prev/next session inside it)
- Background/agent-view rows: `[bg]`/`[exec]`/`[bg ⎇branch]`/`[bg ∙]`/`[PR #N]` badges, `*` pin marker, `Enter` attaches (not forks)
- Color themes (dark/light, `--theme` / `t`)
- fzf-style `/` with live filter and typing-while-navigating
- Unicode (Korean/Japanese/Chinese) input support in search
- Enter opens the session in a **new terminal window of the same app** you're in (iTerm/WezTerm/Ghostty/kitty/Alacritty/Terminal/cmux), raised to the foreground — the old behavior replaced the TUI process with `claude`
- Orphan-relocate flow when a session's recorded cwd is missing

### vs. `claude-session-manager` (csm)

Different goals, complementary tools.

| | **csm** | **ast** |
|---|---|---|
| Role | Task manager for **concurrent running** sessions | Browser for **all** sessions (live + archived) |
| Platform | macOS-only (osascript window focus) | Cross-platform (stdlib only) |
| Data | Separate registry (title / priority / tags / note) | Original jsonl + minimal overlay (done flag + hook status + auto-rescan / theme / sort / origin prefs) |
| Headline features | Window focus · priority ranking · stale review · watch TUI · hooks · statusline | List / search / resume / export / backup / restore / relocate / status glyphs / orphan-relocate |
| Scope | Sessions you actively juggle | 500+ sessions in history |

**Use csm** to triage multiple running terminal windows.
**Use ast** to find, resume, export, or back up anything from your session history.

---

## FAQ

**Q: When a Claude Code session closes, does the status update automatically?**
A: Every `ast list` / `ast search` / `ast live` re-scans live processes. In the TUI, press `R` (or wait for the next auto-rescan tick, default 10s).

**Q: Enter in the TUI opens a terminal but `claude` doesn't run.**
A: Check the error message that stays on-screen. Most commonly: the new shell's `PATH` doesn't include the directory containing `claude`. `ast` already resolves the absolute path via `shutil.which("claude")` in the parent process — if it still fails, ensure `claude` is on your `PATH` *when you launch `ast`*.

**Q: Enter opened the window but it's hidden behind the TUI.**
A: `ast` calls `osascript activate` right after spawning; if your window manager still hides it, click the app icon in the Dock once — subsequent opens come to the front.

**Q: Does Korean/Japanese/Chinese input work in `/`?**
A: Yes. `ast` reads key events byte-by-byte and assembles UTF-8 sequences manually, sidestepping a Python `curses.get_wch()` bug on some terminals (e.g. WezTerm) that turns arrow keys into multi-char strings.

**Q: Why isn't there a `Ctrl-H` alias for `H`?**
A: `Ctrl-H == ASCII 8 == Backspace` on virtually every terminal and curses build. Binding it would break backspace.

**Q: I pressed `Esc` and my filter is gone. How do I keep the filter but exit the prompt?**
A: Press `Enter` instead of `Esc`. `Enter` in search mode commits the filter; `Esc` clears it.

**Q: Does the auto-rescan really beep when something needs me?**
A: Yes. When the rescan detects a session **newly entering** `!` waiting (i.e. not in the previous tick), it rings `curses.beep()` and shows a sticky in-TUI toast (`⚠ N now waiting: …`). Already-waiting sessions don't re-alert. (There is **no** macOS desktop notification — `osascript -e 'display notification'` is owned by Script Editor, so it was removed.)

**Q: Does it work on Linux / Windows?**
A: Linux: yes (pure stdlib). Windows: the curses TUI needs `windows-curses`; CLI commands work as-is.

**Q: How do I get rid of ast entirely?**
A: See [Uninstall](#uninstall) above — `ast uninstall-hook`, remove the symlink, optionally clear `~/.ast`.

---

## License

MIT. Fork of [`claude-sessions`](https://github.com/) (same license).
