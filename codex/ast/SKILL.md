---
name: ast
description: Browse, search, resume, export, and mark local Claude Code, Codex, or ChatGPT desktop sessions with agent-session-tracker. Use for requests to ast or session tracking.
---

# ast

This is the short Codex entry point for agent-session-tracker. Resolve this
file's symlink to its real location and read `../../SKILL.md` relative to that
location for the session workflow. The CLI script is `../../tracker.py` at
that same location; use `python3 <resolved-script-path>` when `ast` is not on PATH.

For `$ast` without a request, show the latest 10 sessions using `list --limit 10
--agent all --origin all --device all`. For a request, apply its filters and
report results using the main skill's workflow.

`done!` and `undone!` are local prompt commands after installing the Codex
hooks (`ast install-hook --agent codex`). If either reaches the model, the
hook is missing, disabled, or not trusted: explain setup rather than claiming
the command ran. Never guess the current session by project or modification time.

Codex CLI reserves slash commands, so bare `/ast` cannot be registered by
this skill. Use `$ast` for agent-assisted operations, or `ast!` for a local
list without a model call. A `/ast` submitted as ordinary text is also handled
by the prompt hook; CLI users can put a space before the slash to submit it.
