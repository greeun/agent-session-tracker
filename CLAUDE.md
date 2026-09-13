# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

`agent-session-tracker` (CLI: `ast`) is a single-file Python tool that browses, searches, resumes, and tracks the status of local coding-agent sessions — Claude Code and OpenAI Codex through one UI, with an `AgentSpec` adapter per agent (gemini is the planned next one). It forks `claude-session-tracker` (CLI: `cst`), which covered Claude Code alone, and keeps everything that one added over `claude-sessions`: live-process status detection, a "task done" flag, and an fzf-style curses TUI. It keeps its own data home, so it can be installed beside `cst` rather than replacing it. **Stdlib-only, zero dependencies**, Python 3.10+.

The entire implementation lives in `tracker.py` (~7,000 lines), with a stdlib `unittest` suite under `tests/`. There is no build system and no package manager. `SKILL.md` is the Claude Code skill definition; `README.md` / `README.ko.md` are the human-facing docs.

## Running and Installing

```bash
# Run directly
python3 tracker.py

# Or via symlink (standard install path)
chmod +x tracker.py
ln -sf "$(pwd)/tracker.py" ~/.local/bin/ast
ast --version
```

## Architecture

`tracker.py` is a self-contained script with these logical sections (top to bottom):

1. **Constants & helpers** (lines ~40–110) — paths, `_CACHE_SCHEMA`, status glyphs (`●`/`!`/`◦`/`○`/`✓`), labels, `_JOB_STATE_GLYPH`
1b. **AGENT LAYER** (`Turn`, `AgentSpec`, `AGENTS`, ~line 190–520) — one frozen `AgentSpec` per agent CLI: `name`/`bin`/`resume_label`, `owns(path)`, `session_files(include_subagents)`, `session_id_of(path)`, `iter_turns(path, line_sink=None)` (the transcript → `Turn(etype, ts, text, cwd, git_branch, entrypoint)` stream every consumer folds; `line_sink` is handed every raw line as the stream is read, which is how `load_session_meta` collects PR URLs inside the same single pass instead of re-reading the file — an adapter may ignore the argument but must accept it, and both built-in adapters just forward it to `iter_jsonl`), `resume_argv(bin, sid, skip_perm)`, `caps` (`resume attach jobs hooks subagents relocate backup`), `skip_perm_flag`, optional `live_probe()` / `live_info(sid)` for agents without a pid registry, and the data-layout group used by relocate/backup/restore/subagents: `data_root()` (the root archived paths are relative to and a restore writes back into), `archive_prefix` (the tarball's top-level dir — `projects` for claude so pre-fork archives still restore, `codex` for codex), `rewrite_event_cwd(evt, new_cwd, old_cwd)`, `relocated_path(path, new_cwd)` (`None` ⇒ the transcript stays put), `subagents_of(path)` and `file_fingerprint(path, …)`. `CLAUDE_AGENT` wraps the original single-agent code paths through late-bound lambdas (tests re-point `PROJECTS_DIR` after import, so specs must read module globals at call time). `CODEX_AGENT` reads `$CODEX_HOME/sessions/**/rollout-*.jsonl` (`session_meta` header → cwd/git.branch/source; `response_item`/`message` user+assistant turns; developer records and codex's user-role wrappers dropped via `_codex_is_wrapper`; subagent rollouts — dict `source`, `parent_thread_id`, or `thread_source` subagent/guardian_review — hidden by default), resumes with `codex resume <uuid>` (`--dangerously-bypass-approvals-and-sandbox` for skip-perm), and reports liveness by non-blocking-flock-probing `thread-writer-locks/<uuid>.lock` (`_flock_held`; codex holds that flock while a thread has an active writer — verified in codex's `writer_lock.rs`), busy vs idle by rollout mtime within `_CODEX_BUSY_WINDOW_S`. Its data ops: `relocate` rewrites every nested `cwd` plus matching `workspace_roots` entries and returns `None` from `relocated_path` so the dated rollout never moves; `subagents_of` matches `parent_thread_id`; `file_fingerprint` mines `apply_patch` headers, `view_image` paths and `exec_command` arguments (the claude extractor reads `input.file_path` tool blocks, which a rollout never has). `agent_for_path(path)` picks the owning spec (claude for unowned/test paths), `agent_of(meta)` prefers `SessionMeta.agent`, `require_cap(meta, cap, verb)` gates a command on agents that have no counterpart for it — `attach`/`jobs`/`hooks` are Claude Code features; codex carries `resume relocate backup subagents`. (TUI Enter skips the orphan-relocate flow for agents without `relocate`.) Adding an agent = one `AgentSpec` + an `AGENTS` entry; nothing above the table changes. Gemini CLI's format (`~/.gemini/tmp/<project>/chats/session-*.jsonl`, first line metadata, `$set`/`$rewindTo` records) is researched but not wired.
2. **Terminal-window spawning & focus** (`open_in_new_terminal`, ~line 166; `focus_existing_window`, ~line 904) — `open_in_new_terminal` detects `$TERM_PROGRAM` and opens sessions in new windows for iTerm/Terminal.app/WezTerm/Ghostty/kitty/Alacritty (+`cmux`). A `terminal=` kwarg (CLI: `resume --spawn --terminal NAME` / `open --terminal NAME`) overrides the `$TERM_PROGRAM` pick — GUI callers like cst.app have no `$TERM_PROGRAM` and would otherwise always fall back to Terminal.app; unknown/missing CLIs still fall through to Terminal.app. `focus_existing_window` raises a *live* session's existing window by matching the claude PID's controlling tty (`ps -o tty=`): WezTerm via `wezterm cli list` → window title → macOS Accessibility `AXRaise` of the `wezterm-gui` window (WezTerm has no CLI window-raise); Terminal.app tabs / iTerm2 sessions via AppleScript `tty` match; cmux workspaces via `cmux --id-format both debug-terminals` (maps tty → surface → workspace/window UUIDs) then `select-workspace` + `focus-pane` + `focus-window` **+ `_activate_macos_app("cmux")`** — cmux's `focus-window` (and `set-app-focus`/`simulate-app-active`) only move cmux's *internal* current-window; none activate the app process, so when cmux isn't already frontmost (user in another app, or target in a different OS window) the window never visibly rises. Only an AppleScript `tell application "cmux" to activate` (NSApp activate) brings the now-current window forward. cmux runs Ghostty as `$TERM_PROGRAM`, so it's probed first whenever `$CMUX_WORKSPACE_ID` is set, else as a fallback. The cmux backend is gated by `_cmux_available()` (env var inside a workspace, else `cmux ping`) — **not** `pgrep -x cmux`, which is flaky: the GUI's process name is its full bundle path so the exact match only ever catches transient CLI invocations. TUI Enter tries focus first, then falls back to spawning.
3. **Display utilities** (~line 960) — `display_width`, `pad_display`, `truncate_display`, `truncate_display_tail`, `shorten_path` — CJK-aware column formatting using `unicodedata.east_asian_width`
4. **Live-process detection** (`scan_live_sessions`, ~line 1103) — scans `~/.claude/sessions/<pid>.json` + `kill -0` to determine active vs ended
5. **State persistence & prefs** (`load_state`/`save_state`, ~line 1276) — `state.json` holds 작업종료 (done) flags + the status overlay + user prefs (auto-rescan ~line 1504, TUI theme ~line 1545, column sort ~line 1604); `index.json` is the mtime-invalidated session cache
6. **Session loading** (`SessionMeta` dataclass, ~line 2100; `load_all_sessions`, ~line 2400) — `load_session_meta`, `iter_messages`, `cmd_search`, the TUI full-text search and the preview modal all fold the owning spec's `iter_turns()` stream, so a transcript format lives in exactly one place; `SessionMeta.agent` names the spec and rides the index cache (`_CACHE_SCHEMA` 6); `all_session_files()` concatenates every spec's files in registry order; also `scan_pr_refs`/`pr_badge`
7. **CLI subcommands** (~line 2082) — `cmd_list`, `cmd_search`, `cmd_show`, `cmd_export`, `cmd_resume`, `cmd_open` (TUI `o` as a subcommand — folder in a new terminal, for cst.app), `cmd_done`, `cmd_undone`, `cmd_live`, `cmd_stop`, `cmd_logs`, `cmd_bg`, `cmd_jobs`, `cmd_relocate`, `cmd_rm`, `cmd_backup`, `cmd_restore`, `cmd_stats`, `cmd_subagents`, plus the hook commands `cmd_prompt_hook`/`cmd_status_hook`/`cmd_install_hook`/`cmd_uninstall_hook`

### bg-aware actions (attach / stop / logs)

Background (agent-view) sessions are addressed by their `daemonShort` (from
`scan_jobs()`, via `job_short_for(sid)`), so ast drives the real `claude` CLI
instead of forking the transcript:

- **open/attach** — `session_open_invocation()` returns `claude attach <short>`
  for a job-backed session (the terminal takes over the *live* supervisor
  session: catch-up summary + live stream) and `claude --resume <sid>` (a fresh
  transcript fork) otherwise. `open_in_new_terminal(..., attach_short=...)` and
  `cmd_resume` both use it; TUI Enter attaches when the row is job-backed
  (skipping the resume-only orphan-relocate / skip-perm prompts).
- **`ast stop <id>`** (`cmd_stop`) — `claude stop <short>`, the only way to
  actually stop a live bg process. Refuses non-bg sessions.
- **`ast logs <id>`** (`cmd_logs`) — `claude logs <short>` passthrough, to peek
  a bg session's recent output without attaching.
- **delete warning** — `bg_delete_warning()` warns in the TUI delete modal that
  Del only unlinks the transcript and does NOT stop the live process.

All shell out through `_run_claude(argv)` (isolated for testing).

- **row badge** — `job_badge(job)` tags job-backed rows with their agent-view
  `template`, git worktree branch, and process liveness: `[exec]`, `[bg]`,
  `[bg ⎇<branch>]`, `[bg ∙]` (the ∙ mirrors agent-view's ✻/∙ — `tempo != active`
  means the process exited but is still attach/respawn-able). Branch/worktreePath
  come from state.json, which `scan_jobs()` captures. Appended to the PROJECT
  column in `ast list` and the TUI rows.
- **`ast jobs`** (`cmd_jobs`) — lists EVERY agent-view background job from
  `~/.claude/jobs`, including exec / transcript-less jobs the transcript-based
  session browser can't show, with a `daemon_status_line()` header
  (`read_daemon_roster()` reads `~/.claude/daemon/roster.json`). Read-only.
- **`ast bg <prompt> [--name N]`** (`cmd_bg`) — dispatch a new background session
  (`claude --bg`), turning ast into a launcher as well as a viewer.
- **PR detection** — verified against a real PR-opening session: jobs/state.json
  has NO pr field, only `linkScanPath`/`linkScanOffset`; agent-view detects PRs
  by link-scanning the transcript. ast mirrors this — `scan_pr_refs(path)` /
  `find_pr_refs(text)` extract `{host,repo,number,url}` from GitHub pull /
  GitLab-Bitbucket MR URLs, stored on `SessionMeta.prs` (cached; `_CACHE_SCHEMA`
  bumped 3→4). `pr_badge(prs)` renders `[PR #1]` / `[PR #1,3]` in `ast list` and
  the TUI rows. Heuristic: any PR URL in the transcript counts (same as
  agent-view), so a session that merely *mentions* a PR URL will show it.

- **pin display (read-only)** — `read_pins()` reads `~/.claude/jobs/pins.json`,
  whose real format (captured from an agent-view Ctrl+T pin) is a JSON array of
  daemonShort strings, e.g. `["cbe8e3bb","4c51890c"]` (stale shorts persist).
  `pin_marker(short, pins)` renders `*` (1-col ASCII, not the double-width emoji)
  on pinned rows in `ast list`, `ast jobs`, and the TUI; `StatusContext.pins`
  carries the set so it refreshes on rescan. **Read-only by design** — ast never
  writes pins.json: it's a supervisor-locked file and a concurrent write could
  corrupt agent-view's own pin state. Bidirectional sync (ast Ctrl-T ↔ pins.json)
  is feasible now that the format is known but intentionally not done.

### Column sort (`ast list --sort` / TUI `s`,`S`)

`sort_sessions(sessions, ctx, sort_key, reverse)` (~line 1578) is the shared
sorter for both `ast list` and the TUI. Sortable columns: `SORT_KEYS =
("status","time","msgs","project")` — also the TUI `s`-cycle order. `_SORT_DEFAULT_DESC` gives each column a
natural direction (time/msgs descending, status/project ascending). Ties break
by `last_ts` descending — the function pre-sorts by recency and relies on
Python's **stable** sort so equal primary keys keep newest-first. `status` sorts
by `_status_sort_rank()` (working→waiting→idle→ended→done, needs the
`StatusContext` to resolve live status). The pref persists in `state.json` as
`{"sort": {"key", "reverse"}}` via `load_sort`/`save_sort` (~line 1604, mirrors
`save_theme`). `cmd_list` honours an explicit `--sort` (natural dir, flipped by
`--reverse`) as a one-off, else falls back to the saved pref; sort runs **before**
`--limit` so the slice is top-N of the chosen order. In the TUI, `s` cycles the
column (resetting to its natural direction) and `S` toggles reverse — both save
immediately, reset the cursor, and the header shows `sort:<col>▼/▲` with the
active column's header label highlighted.

### Origin filter (`ast list --origin` / TUI `f`,`F`)

Claude Code stamps every user/assistant event with an `entrypoint`: `cli` when a
human typed the session into a terminal, `sdk-py`/`sdk-cli`/`sdk-ts` when an SDK
spawned it (security-review hooks, `claude -p` scripts, tooling). Agent-view
`--bg` jobs are `cli` — a human dispatched them — so they count as user
sessions. `load_session_meta` picks the first non-empty value in the same event
loop that fills `git_branch` (no extra file read); `SessionMeta.entrypoint`
carries it and `_CACHE_SCHEMA` was bumped 4→5 to invalidate pre-entrypoint
cache entries. `cmd_search`, which builds its own `SessionMeta` without the
cache, captures it in its own loop.

`session_origin(meta)` maps that to `"agent"` (entrypoint starts with `sdk`) or
`"user"` (everything else). **Unknown or absent entrypoints deliberately read as
`user`** — some transcript-less bg jobs carry none, and a filter must not
silently swallow a session whose origin ast cannot prove. `filter_origin(rows,
origin)` returns a new list; `"all"` and any unrecognised value keep everything.
`cycle_origin(origin, step)` walks `ORIGIN_CHOICES = ("all","user","agent")` in
either direction. The pref persists as `{"origin": "..."}` via
`load_origin`/`save_origin` (mirrors `save_theme`/`save_sort`).

Both `cmd_list` and `cmd_search` honour an explicit `--origin` as a one-off,
else fall back to the saved TUI pref, and append `origin_note(origin)` —
`  [origin:user]` — to their summary line so a saved filter never shrinks a
listing invisibly. `session_to_dict` exposes `entrypoint` + `origin` for
`--json` (cst.app). In the TUI, `f` cycles forward and `F` backwards; both save
immediately and reset the cursor. The header hint (`👤user` / `🤖agent`) sits
right after `sort:<col>` — anything longer, or placed after the transient
mark/search/hide/cwd hints, truncates at 80 columns.

### Agent view (`ast list --agent` / TUI `a`,`A`)

Which agent CLI's sessions are shown: `"all"` or an `AGENTS` key
(`agent_choices()` = `("all", *AGENTS)`). `filter_agent(rows, view)` returns a
new list and keeps everything for `"all"`/unknown values (mirrors
`filter_origin`); `cycle_agent(view, step)` walks the choices; `agent_note()`
appends `  [agent:codex]` to CLI summaries. The pref persists as
`{"agent": "..."}` via `load_agent_view`/`save_agent_view`. `cmd_list`,
`cmd_search` and `cmd_pick` honour an explicit `--agent` as a one-off (pick
via the `agent_view_override` kwarg of `_pick_ui`), else the saved view. In
the TUI `a` cycles forward and `A` backwards, both save immediately and reset
the cursor; the header hint is `⚙<agent>` right after the origin hint. The
**AGENT** column (`AGENT_VIEW_WIDTH` = 6) sits between ST and LAST ACTIVITY in
`ast list`, `ast search` rows and the TUI (`_tui_columns` returns an 8-tuple:
`num, status, agent, ts, sid, msgs, msg, proj`); `session_to_dict` exposes
`agent` for `--json`. Moving the auto-rescan popup off `a` to `i` made room
for this key.
8. **TUI** (`_pick_ui`, ~line 4179) — curses-based picker with two modes (normal + search), rendering loop, modal dialogs (help, preview, delete confirm, cmux chooser). The preview modal (`_preview_modal`) pins its metadata header: `_build_lines()` returns `(lines, head_n)`, `_preview_sticky_head(head_n, view_h)` caps how many of those rows stay on screen (leaving `_PREVIEW_MIN_BODY_ROWS` for the transcript, and letting the overflow scroll normally since the body starts at the pinned count), and `top` is an absolute index into `lines` clamped to `[head_h, max_top]`. `d`/`Ctrl-D` therefore rewrites only `lines[_PREVIEW_STATUS_ROW]` in place instead of rebuilding every line, so the scroll offset and the active search survive a done toggle. That row is built by `_preview_status_row(status, inner_w, flash)`, which borrows `_status_attr()` — the list's ST palette — so the state reads by color, and ORs in `A_REVERSE|A_BOLD` when `flash` is set; a successful `d` sets `status_flash`, and the next keypress repaints the row unflashed alongside the `notice` reset. The same `d` also fires the `on_status_change` callback the caller passes in, because the modal box never covers the whole screen and the list around it was painted before the modal opened — without it the row behind the box keeps showing ○ while the modal's own Status row reads ✓. `_pick_ui` supplies `_repaint_list_bg`, a closure over that frame's `top`/`sel`/`cols` that re-runs `filtered()` and re-renders the header line (`_header_line(rows)`, extracted so both the row count and the ✓/○ counts recount from `ctx`), the rows, and the footer (`_tui_footer_info(row)`, extracted for the same reason), staging them with `noutrefresh` only; the modal then sets `win.clearok(True)` so its next `refresh()` flushes list and box in one update with no blink. Re-running `filtered()` — not reusing the frozen `items` — is what makes the background match what the list will look like after the modal closes: with `H` on, the row the toggle just marked ✓ vanishes, and a status sort re-orders. The modal keeps indexing into its own `items`, so its `‹`/`›` walk is unaffected. Two details the shrinking row set forces: the strip is blanked before `_tui_draw_rows` (rows carry no trailing padding, so a vanished or longer previous row would bleed through), and `bsel`/`btop` are re-clamped by the main loop's own rules so the row highlighted behind the box is the one that stays focused afterwards. `cols` is reused rather than recomputed, keeping the rows aligned with the untouched column header on row 2. The modal never rescans, so a status change originating *outside* it (a process ending while the modal is open) shows up only on re-entry or a `‹`/`›` session switch. Normal-mode action keys include `s`/`S` (sort), `f`/`F` (origin filter), `a`/`A` (agent view), `i`/`I` (auto-rescan popup), `t`/`T` (theme), and `o`/`O` (open the focused session's folder in a new terminal — plain shell via `open_folder_in_new_terminal()`, no claude command) alongside `D`/`H`/`C`/`R`/`e`/`v`. Enter resumes through `open_in_new_terminal(..., agent=spec.name)`, and the skip-permissions modal titles itself with the spec's `skip_perm_flag`. **Color theme**: dark/light palettes via `tui_init_colors()` — pair NUMBERS carry fixed meaning (1–9), only (fg,bg) swap per theme, so the whole UI re-themes without touching call sites; pair 7 doubles as the full-screen `bkgd` fill so each theme renders identically across terminals. `resolve_theme()` picks the effective theme (CLI `--theme` → saved pref → `COLORFGBG` auto-detect → dark); `t`/`T` toggles live and persists via `save_theme()` into `state.json`.
9. **Argument parser** (`_build_parser`) and `main` — with no subcommand, `main()` re-parses a synthesized default one through the same parser (so subparser defaults can never drift) and carries the top-level `--skip-perm` / `--hide-done` / `--theme` back onto the fresh namespace. The default is `pick`: a bare `ast` opens the TUI. `_stdio_is_interactive()` gates it on both stdin and stdout being a tty, so a pipe, a redirect, an agent tool call or a GUI caller gets `list` instead of a curses failure; `--tui` forces `pick` regardless. `tests/test_default_command.py` pins both branches.

### Key data flow

`load_all_sessions()` is the central data loader — it reads every agent's transcripts (`all_session_files()`: `~/.claude/projects/**/*.jsonl` plus `$CODEX_HOME/sessions/**/rollout-*.jsonl`), applies the mtime-based index cache, resolves live/done status, filters by `--cwd`/`--days`/`--status`, and returns `SessionMeta` objects sorted by `last_ts` descending (the default order). Both CLI commands and the TUI consume this, then re-order via `sort_sessions()` when a non-default column sort is active.

It runs in **two passes**. Pass 1 only `stat()`s each file and sorts it into a
cache hit (`_meta_from_cache`) or a miss; pass 2 parses the misses. The split
is what makes the parallel path below possible, and it is free when the cache
is warm — `stat()` over a couple of thousand files is single-digit
milliseconds. Results are keyed by path and the survivors are assembled back
in `all_session_files()` order, because `dedupe_sessions()` depends on that
order being deterministic and the parallel pass completes out of order.

### Parallel indexing (`AST_JOBS`)

A cold index re-reads every transcript — gigabytes of JSON through
`json.loads`, which is CPU-bound behind the GIL, so threads measured as no
improvement at all while separate processes scale nearly linearly. Pass 2
therefore hands the misses to a **forked** `ProcessPoolExecutor`:
`_index_workers(miss_count)` decides how many workers (0 = stay sequential),
`_index_one((path, fast))` is the worker body returning the cache-entry dict
(never a `SessionMeta` — a dict is what crosses the process boundary cheaply
and is exactly what the index stores), and `_index_parallel()` drives the pool,
returning False if it could not be used so the caller re-indexes everything
sequentially. Every worker failure collapses into `None` because a worker must
never write to stderr, which in the TUI *is* the curses screen.

Only misses are farmed out, and only past `_PARALLEL_MIN_MISSES` (200): a warm
rescan misses a handful of files and finishes in ~170ms, where forking costs
more than it saves. `AST_JOBS=N` pins the worker count and lowers the threshold
to 2 (so the path is testable without thousands of files); `AST_JOBS=1` (also
`0`, `-1`) forces the sequential path. Only `fork` is used — `spawn` would
re-import this 7k-line script per worker — so a platform without it stays
sequential. Measured on 2,370 sessions / 3.9GB: 16.6s → 2.5s.

Two smaller cuts came with it. `load_session_meta` collects PR URLs through
`iter_turns`' `line_sink` instead of calling `scan_pr_refs()` afterwards, which
stops reading every transcript twice (~11% of a sequential cold index), and
`_pr_collector()` holds the shared dedupe rule for both. The stderr progress
counter only repaints when its percentage moves — drawing it per file cost
0.9s of a 2.7s parallel scan on a real tty — while `on_progress` still reports
per file so callers can throttle to their own cadence.

### Cache invalidation is per entry

`invalidate_cache_entries(paths)` drops just those paths from `index.json` and
keeps the rest. `cmd_relocate` (both ends of the move) and `cmd_restore` (the
transcripts it actually wrote) call it; both used to `CACHE_PATH.unlink()` the
whole index, so changing one session made the *next* run a full cold scan — and
because TUI Enter reaches relocate through the orphan flow, that stall landed
on the following rescan. mtime+size checking would catch most of these cases on
its own; the explicit invalidation covers the rest (an in-place cwd rewrite that
happens to leave both size and mtime unchanged) and costs one small cache write.

### Rescan progress (`%`)

A rescan spends essentially all of its time inside `load_all_sessions()` —
re-reading every transcript whose mtime moved costs seconds on a large
collection (~15s for 2,400 files with a cold cache, ~0.2s fully warm), while
the `StatusContext.capture()` that follows it costs a couple of milliseconds.
So progress is counted over transcript files, and both front ends render the
same number through `progress_pct(done, total)` (0–100, clamped, an empty set
reading as 100).

`load_all_sessions(on_progress=…)` calls back `(done, total)` once with
`(0, total)` before the scan — so the denominator is known even when there is
nothing to index — then after every file, counting **every** file scanned
rather than the rows that survive `--cwd`/`--days`, so the percentage never
jumps backwards. `_do_rescan()` forwards the callback; the CLI path
(`progress=True`) keeps writing its own stderr line, now
`Indexing sessions…  42% (994/2370)`.

In the TUI, `_rescan_progress_painter(stdscr, label, delay, clock)` builds that
callback: it renders `rescan_progress_text()` on the bottom line in pair 2, and
its whole job is deciding what **not** to paint — nothing before `delay`
seconds have passed, nothing within `_RESCAN_PAINT_INTERVAL_S` (80ms) of the
last paint, and nothing for a percentage already on screen. The footer is never
restored, because the main loop repaints it on the next iteration. Manual
rescans (normal-mode `R`/`r`/`Ctrl-R`, search-mode `Ctrl-R`) pass `delay=0.0` —
the user asked and is already watching the footer; the auto-rescan tick keeps
the default `_RESCAN_PAINT_DELAY_S` (0.35s) so a warm tick never flashes a
counter. `clock` exists for tests, since `time` is imported per-function here
and cannot be stubbed on the module.

**One row per sessionId** — `dedupe_sessions()` (~line 2167) runs just before
that sort, and `cmd_search` applies it to its own hits. `session_id` is
`path.stem`, so the *same* session existing as a `.jsonl` in two project dirs
renders twice. That is not hypothetical: renaming a project (or copying
`~/.claude/projects` around, e.g. through a synced folder) leaves the old
`<encoded-cwd>/<sid>.jsonl` behind, byte-identical, and both copies report the
same transcript `cwd` — so the two rows are indistinguishable on screen.
`_dup_rank()` keeps the canonical copy (parent dir == `encode_cwd(meta.cwd)`),
then the richer transcript (`msg_count`), then the fresher `last_ts`; ties keep
the first, which is deterministic because `all_session_files()` is path-sorted.
Dedup is display-only — ast never deletes the redundant file.

### Data files read/written

| Path | Read/Write | Purpose |
|---|---|---|
| `~/.claude/projects/**/*.jsonl` | Read | Session transcripts (Claude Code's data) |
| `~/.claude/sessions/<pid>.json` | Read | Live-process registry (interactive sessions) |
| `~/.claude/jobs/<short>/state.json` | Read | Agent-view background-session state (`scan_jobs()`) |
| `$CODEX_HOME/sessions/**/rollout-*.jsonl` | Read | Codex CLI transcripts (`CODEX_AGENT`; default `~/.codex`) |
| `$CODEX_HOME/thread-writer-locks/<uuid>.lock` | Read (flock probe) | Codex's per-thread writer lock — held ⇒ live (`codex_live_probe`); never written |
| `~/.ast/index.json` (or `$AST_INDEX_DIR/index.json`) | R/W | Session metadata cache (safe to delete, but deleting it forces a full cold re-index — see `invalidate_cache_entries`) |
| `~/.ast/state.json` | R/W | Done-flag overlay + status overlay + user prefs: auto-rescan, TUI theme, column sort, origin filter, agent view (safe to delete) |
| `~/.claude/jobs/pins.json` | Read | Agent-view pin set (`read_pins()`) — never written |
| `~/.cst/state.json` | Read once | claude-session-tracker's overlay, copied into `~/.ast/state.json` on a first run (`seed_from_cst_home()`) — never written |

### Home vs. index cache

`_ast_home()` (`$AST_HOME`, else `~/.ast`) holds what cannot be regenerated:
`state.json`, its lock, and `backups/`. `_ast_index_home()` (`$AST_INDEX_DIR`,
else **the home itself**) holds `index.json`. The default keeps them in one
directory so an existing install's behaviour and its warm cache are untouched —
the split is something the user opts into.

The case it exists for is a home inside a synced folder. `index.json` runs to
tens of megabytes and is rewritten on every rescan that finds a changed
transcript, so a sync daemon uploads it continuously, and two machines writing
it produce `index_<host>_…_Conflict.json` leftovers (the pre-fork `~/.cst` had
exactly those). Sharing it buys nothing either: its keys are absolute
transcript paths and its values are mtimes, so a sync that does not preserve
mtime makes every entry a miss on the other machine. `state.json` is the
opposite — done flags and prefs are worth sharing — so it stays in the home.

`CACHE_DIR` still names the *home*, not the index dir, because ~36 test files
stub it; `INDEX_DIR` was added alongside rather than renaming it. Only
`CACHE_PATH` moved onto `INDEX_DIR`, and `_save_cache` already did
`CACHE_PATH.parent.mkdir(parents=True)`, so a fresh index dir is created on
first write. `seed_from_cst_home()`'s stub guard still compares `CACHE_DIR`
against `_ast_home()`, which the split leaves alone.

ast's own dir is `_ast_home()` — `$AST_HOME` if set, else `~/.ast`. `main()`
calls `seed_from_cst_home()` once per invocation: if `~/.ast/state.json` does
not exist yet and `~/.cst/state.json` does, the latter is **copied** over, so a
user coming from `cst` keeps their ✓ done flags and prefs. It is a copy, not a
move, so a `cst` that is still installed goes on reading its own home; the
regenerable `index.json` is not brought along. No-op when the target exists,
and when module paths are test-stubbed (`CACHE_DIR != _ast_home()`).

### Status resolution priority

Agents without a pid registry plug into the same decision: `StatusContext.capture()` calls every spec's `live_probe()` and folds the result into `live` plus a synthetic registry record (`{"status": "busy"|"idle", "updatedAt": ms}`), so codex sessions reach `classify_status()` looking like registry-backed claude ones (`●` when the rollout was written within `_CODEX_BUSY_WINDOW_S`, else `◦`; `!` waiting is not detectable for codex). `get_live_session_info()` likewise falls back to `spec.live_info(sid)` (pid via `lsof -t` on the lock) so window focus and the TUI footer work for a live codex thread.

`classify_status()` (via `resolve_status()` / `StatusContext.resolve`) decides
in this order: **✓ done always wins**; otherwise a **dead** process is `○` ended
(or, for a background/agent-view job, its last persisted job-state); a **live**
process resolves from the hook **overlay** if present (with a self-heal that
downgrades a stale `working`/`waiting` to `◦` idle when the registry has a newer
idle tick), else from the live **registry** (`busy`→`●`, `waiting`→`!`,
`idle`→`◦`); a live process with no signal falls back to `●`. So liveness gates
the active states — done > (dead⇒ended/job-state) > overlay > registry > `●`.

Background (agent-view) sessions are managed by the supervisor, not the pid
registry, so when their idle process is stopped they vanish from
`~/.claude/sessions` and would otherwise read as ○ ended. `scan_jobs()` reads
`~/.claude/jobs/<short>/state.json` and `classify_status(job=...)` uses the
persisted agent-view `state` (`working`→●, `blocked`→!, `idle`→◦,
`done`/`failed`/`stopped`→○) **only when the session is not alive in the pid
registry** — a live/attached bg session is in the registry, so the fresher
signal there still wins. Joined onto transcripts by `sessionId`.

**done guard**: marking done is refused on an actively-working (●) session,
since done > every state would mask a live, quota-burning session.
`done_guard_blocks(status, force)` gates `cmd_done`, the `done!` prompt-hook
(explicit target only — see below), and TUI `D`/`Ctrl-D`. Waiting/idle/ended
and unmarking stay allowed; `ast done --force` overrides. Stop the session with
`claude stop
<short>` (ast's own Del removes the transcript but does NOT stop the live bg
process) or let the turn finish, then mark done.

Self `done!` (no explicit target) is **exempt** from the working-guard: that
session is necessarily ● working while it processes the very `done!` prompt, so
guarding it would block self-done 100% of the time. The guard fires only on an
explicit `done! <id>` — a *different* live session ✓ would otherwise mask.

### bulk rm (`ast rm --filter`)

`cmd_rm` dispatches: explicit id prefix(es) → `_rm_one` per id, or any of
`--filter/--cwd/--status/--days/--older-than/--before` (`_RM_SELECTORS`) →
`_bulk_rm`. Passing both is an error, as is passing neither (there is no
delete-everything path). `_rm_candidates()` is the pure selector — same
case-insensitive `sessionId+cwd+first_user_msg` substring match as the TUI `/`
filter and `_bulk_done`, but ✓ done sessions are kept (they're the prime delete
candidates). `_rm_cutoff()` turns `--older-than N` / `--before YYYY-MM-DD` into
the timestamp `last_ts` must precede; `--days N` still means *the last N days*
via `load_all_sessions`, so the three time flags are mutually exclusive at the
parser level.

`rm_guard_blocks(status, force)` sits beside `done_guard_blocks` and is
stricter: it blocks ● working **and** ! waiting. A live process holds the
`.jsonl` open and keeps appending to the unlinked inode, so deleting it drops
everything said afterwards. The status the guard judges comes from
`_rm_guard_status(sid, ctx)`, not the plain `ctx.resolve()` glyph:
`resolve_status`/`classify_status` let ✓ done short-circuit before liveness is
even checked, so a session that's ✓ done AND still alive-and-working (e.g.
mid self `done!`) would otherwise resolve to ✓ and slip straight past the
guard. `_rm_guard_status` re-classifies past the done flag only when
`session_id in ctx.live` (skipping that check would wrongly block dead
background jobs whose last persisted state happens to be "working"); the
printed candidate row still shows ✓ via `ctx.resolve()`. `--force` widens the
target set to include live sessions, but — unlike the single-id `_rm_one`
path, where `--force` still implies `-y` — it does **not** also skip bulk
mode's confirmation prompt (mirrors `_bulk_done`). Deletion itself goes
through `_delete_sessions`, shared with the TUI `Del` key.

## Development Notes

- Tests live under `tests/` (stdlib `unittest`, run with `python3 -m pytest -q` or `python3 -m unittest discover -s tests`) — one `test_*.py` per feature; add one when you add a feature. They load `tracker.py` via `importlib` and stub `CACHE_DIR`/`STATE_PATH` into a tempdir for state tests. **Any test that stubs `PROJECTS_DIR` must also stub `CODEX_SESSIONS_DIR` / `CODEX_LOCKS_DIR`** (the session universe now spans every agent; an unstubbed codex root leaks the real `~/.codex` rollouts into the fixture and slows the run)
- `tests/test_golden_cli.py` + `tests/golden/*.txt` are byte-for-byte characterisation snapshots of list/json/search/show/export/stats/resume over a fixed fixture set. A deliberate output change must regenerate them with `AST_GOLDEN_UPDATE=1 python3 -m unittest tests.test_golden_cli` and the golden diff is reviewed like code; any other change must leave them untouched
- The TUI itself requires a real TTY — `_pick_ui` can't run from non-interactive Bash calls or agent tool calls (verify its curses layout headlessly via `pty.fork` + `getyx`)
- CJK/Unicode display width is handled manually via `east_asian_width`; search mode assembles UTF-8 byte-by-byte to work around Python curses bugs on some terminals
- `ESCDELAY` is set to 25ms for responsive Esc handling
- `_CACHE_SCHEMA` version (currently 6) must be bumped when `SessionMeta` fields or extraction logic change, to invalidate stale cache entries
- `encode_cwd()` NFC-normalizes paths before encoding — important for Korean filesystem paths on macOS
- Version string is in `__version__` at the top of `tracker.py` — and a release
  has to carry it into four other places: `SKILL.md`'s frontmatter `version:`,
  its `Main script: … v<X.Y.Z>` line, and the `agent-session-tracker v<X.Y.Z>`
  headers in `README.md` / `README.ko.md` (the install-check output and the
  list/TUI screen examples). `tests/test_version_drift.py` fails and names the
  stragglers, so there is no need to remember the list; before that test
  covered the docs, README had drifted to `v1.10.0` — a version that never
  existed — while the examples still said `v1.1.0`
