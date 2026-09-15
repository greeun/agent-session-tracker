"""ChatGPT desktop app threads: stored as ordinary codex rollouts, listed as
their own `chatgpt` agent.

The app (bundle com.openai.codex) writes a conversation to
$CODEX_HOME/sessions exactly like the codex CLI does. What tells the two apart
is the recorded cwd: a chat without a project runs in a scratch dir under
~/Documents/Codex/<date>/<slug>, a ChatGPT project under
$CODEX_HOME/.chatgpt-projects/<id>. Verified against app build 26.908
(originator `codex_work_desktop`, source `vscode`)."""
import argparse
import fcntl  # noqa: F401  (the live-probe helper below needs a POSIX host)
import importlib.util
import io
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

_REPO = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("tracker_chatgpt", _REPO / "tracker.py")
tk = importlib.util.module_from_spec(_spec)
sys.modules["tracker_chatgpt"] = tk
_spec.loader.exec_module(tk)

CHAT_SID = "01a095af-07f7-7820-8719-ad1d35d12703"
CODE_SID = "01a094eb-1996-7753-b594-6c1be3647cf8"
CHAT_CWD = str(pathlib.Path.home() / "Documents" / "Codex" / "2026-09-12" / "new-chat")
CODE_CWD = "/repo/codex-app"


def _evt(ts, etype, payload):
    return json.dumps({"timestamp": ts, "type": etype, "payload": payload},
                      ensure_ascii=False)


def _msg(role, text, kind="input_text"):
    return {"type": "message", "role": role,
            "content": [{"type": kind, "text": text}]}


def _rollout(sid, cwd, originator, source, question):
    meta = {"session_id": sid, "id": sid, "timestamp": "2026-09-12T12:54:31.159Z",
            "cwd": cwd, "originator": originator, "cli_version": "0.153.4",
            "source": source, "thread_source": "user",
            "model_provider": "openai", "history_mode": "paginated"}
    return "\n".join([
        _evt("2026-09-12T12:54:31.200Z", "session_meta", meta),
        _evt("2026-09-12T12:54:40.000Z", "response_item", _msg("user", question)),
        _evt("2026-09-12T12:54:45.000Z", "response_item",
             _msg("assistant", "Here is an answer.", "output_text")),
    ]) + "\n"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._orig = {k: getattr(tk, k) for k in (
            "PROJECTS_DIR", "CACHE_DIR", "CACHE_PATH", "STATE_PATH",
            "JOBS_DIR", "DAEMON_DIR", "SESSIONS_REGISTRY_DIR",
            "CODEX_SESSIONS_DIR", "CODEX_LOCKS_DIR")}
        tk.PROJECTS_DIR = self.root / "projects"
        tk.CACHE_DIR = self.root / "cache"
        tk.CACHE_PATH = tk.CACHE_DIR / "index.json"
        tk.STATE_PATH = tk.CACHE_DIR / "state.json"
        tk.JOBS_DIR = self.root / "jobs"
        tk.DAEMON_DIR = self.root / "daemon"
        tk.SESSIONS_REGISTRY_DIR = self.root / "sessions"
        tk.CODEX_SESSIONS_DIR = self.root / "codex" / "sessions"
        tk.CODEX_LOCKS_DIR = self.root / "codex" / "thread-writer-locks"
        day = tk.CODEX_SESSIONS_DIR / "2026" / "09" / "12"
        day.mkdir(parents=True)
        self.chat = day / f"rollout-2026-09-12T21-54-31-{CHAT_SID}.jsonl"
        self.chat.write_text(_rollout(CHAT_SID, CHAT_CWD, "codex_work_desktop",
                                      "vscode", "서비스기획의 역할은?"), encoding="utf-8")
        self.code = day / f"rollout-2026-09-12T18-20-30-{CODE_SID}.jsonl"
        self.code.write_text(_rollout(CODE_SID, CODE_CWD, "codex-tui", "cli",
                                      "fix the failing test"), encoding="utf-8")

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(tk, k, v)
        self._tmp.cleanup()

    def _run(self, fn, **kw):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(argparse.Namespace(**kw))
        return rc, out.getvalue(), err.getvalue()


class TestClassification(unittest.TestCase):
    def test_app_scratch_dirs_are_chatgpt(self):
        home = pathlib.Path.home()
        for cwd in (str(home / "Documents" / "Codex" / "2026-09-06" / "new-chat"),
                    str(tk.CODEX_HOME / ".chatgpt-projects" / "g-p-6a8aac18")):
            self.assertEqual(tk._codex_listed_as(cwd), "chatgpt", cwd)

    def test_everything_else_stays_codex(self):
        home = pathlib.Path.home()
        for cwd in ("/repo/codex-app", "", str(home),
                    str(home / "Documents" / "Codex"),          # the root itself
                    str(home / "Documents" / "CodexNotes" / "x"),
                    str(tk.CODEX_HOME / ".chatgpt-projects-old" / "x")):
            self.assertEqual(tk._codex_listed_as(cwd), "codex", cwd)

    def test_registered_after_codex(self):
        self.assertEqual(tk.agent_choices(), ("all", "claude", "codex", "chatgpt"))
        self.assertIs(tk.AGENTS["chatgpt"], tk.CHATGPT_AGENT)

    def test_agent_column_fits_every_name(self):
        self.assertGreaterEqual(tk.AGENT_VIEW_WIDTH, max(map(len, tk.AGENTS)))

    def test_chatgpt_spec_reuses_codex_io(self):
        c, g = tk.CODEX_AGENT, tk.CHATGPT_AGENT
        self.assertEqual((g.bin, g.resume_label, g.caps, g.archive_prefix),
                         (c.bin, c.resume_label, c.caps, c.archive_prefix))
        self.assertIs(g.iter_turns, c.iter_turns)


class TestListing(_Base):
    def test_meta_is_filed_under_chatgpt(self):
        self.assertEqual(tk.load_session_meta(self.chat).agent, "chatgpt")
        self.assertEqual(tk.load_session_meta(self.code).agent, "codex")

    def test_codex_still_owns_the_file(self):
        self.assertIs(tk.agent_for_path(self.chat), tk.CODEX_AGENT)
        self.assertIs(tk.agent_of(tk.load_session_meta(self.chat)), tk.CHATGPT_AGENT)

    def test_each_rollout_listed_once(self):
        files = tk.all_session_files()
        self.assertEqual(files.count(self.chat), 1)
        self.assertEqual(files.count(self.code), 1)

    def test_stale_cache_entry_is_reclassified(self):
        """An index written before chatgpt existed says "codex"; reading it
        back must file the thread under chatgpt without a schema bump (which
        would force a full cold re-index)."""
        meta = tk.load_session_meta(self.chat)
        entry = tk._meta_to_cache(meta)
        entry["agent"] = "codex"
        self.assertEqual(tk._meta_from_cache(entry, self.chat).agent, "chatgpt")
        entry["cwd"] = CODE_CWD
        entry["agent"] = "chatgpt"
        self.assertEqual(tk._meta_from_cache(entry, self.chat).agent, "codex")

    def test_unknown_cached_agent_is_kept(self):
        entry = tk._meta_to_cache(tk.load_session_meta(self.code))
        entry["agent"] = "gemini"
        self.assertEqual(tk._meta_from_cache(entry, self.code).agent, "gemini")

    def test_list_agent_filter_splits_the_two(self):
        rc, out, _ = self._run(tk.cmd_list, cwd=None, days=None, status=None,
                               limit=30, json=False, agent="chatgpt")
        self.assertEqual(rc, 0)
        self.assertIn(CHAT_SID[:8], out)
        self.assertNotIn(CODE_SID[:8], out)
        self.assertIn(" chatgpt ", out)
        self.assertTrue(out.rstrip().endswith("[agent:chatgpt]"))
        rc, out, _ = self._run(tk.cmd_list, cwd=None, days=None, status=None,
                               limit=30, json=False, agent="codex")
        self.assertIn(CODE_SID[:8], out)
        self.assertNotIn(CHAT_SID[:8], out)

    def test_json_agent_field(self):
        rc, out, _ = self._run(tk.cmd_list, cwd=None, days=None, status=None,
                               limit=30, json=True, agent="all")
        agents = {r["sessionId"]: r["agent"] for r in json.loads(out)["sessions"]}
        self.assertEqual(agents, {CHAT_SID: "chatgpt", CODE_SID: "codex"})

    def test_search_labels_chatgpt_hit(self):
        rc, out, _ = self._run(tk.cmd_search, query="서비스기획", ignore_case=True,
                               cwd=None, limit=20, agent="chatgpt")
        self.assertEqual(rc, 0)
        self.assertIn(CHAT_SID[:8], out)
        self.assertIn("chatgpt", out)
        self.assertNotIn(CODE_SID[:8], out)

    def test_show_prints_chatgpt(self):
        rc, out, _ = self._run(tk.cmd_show, session_id=CHAT_SID[:8], max_chars=500,
                               with_subagents=False, head_chars=0)
        self.assertEqual(rc, 0)
        self.assertIn("Agent:    chatgpt", out)


class TestActions(_Base):
    def test_resume_goes_through_codex(self):
        rc, out, _ = self._run(tk.cmd_resume, session_id=CHAT_SID[:8],
                               print_only=True, skip_perm=False)
        self.assertEqual(rc, 0)
        self.assertEqual(out.strip(),
                         f"cd {CHAT_CWD} && codex resume {CHAT_SID}")

    def test_claude_only_capabilities_refused(self):
        target = tk.find_session(CHAT_SID[:8])
        err = io.StringIO()
        with redirect_stderr(err):
            self.assertFalse(tk.require_cap(target, "attach", "attach"))
        self.assertIn("not supported for chatgpt", err.getvalue())

    def test_backup_keeps_the_codex_archive_layout(self):
        """Same data root as codex, so a chatgpt thread archives under codex/
        and restores through the codex spec — archives stay readable by
        builds that predate the chatgpt agent."""
        meta = tk.find_session(CHAT_SID[:8])
        rel, arc = tk.archive_member_for(meta)
        self.assertTrue(arc.startswith("codex/"), arc)
        self.assertIs(tk.archive_spec_for_member(arc), tk.CODEX_AGENT)


class TestLive(_Base):
    def setUp(self):
        super().setUp()
        tk.CODEX_LOCKS_DIR.mkdir(parents=True)
        self.lock = tk.CODEX_LOCKS_DIR / f"{CHAT_SID}.lock"
        self.lock.touch()
        self.holder = subprocess.Popen(
            [sys.executable, "-c",
             "import fcntl,sys,time\n"
             f"f=open({str(self.lock)!r},'r+'); fcntl.flock(f, fcntl.LOCK_EX)\n"
             "sys.stdout.write('ok\\n'); sys.stdout.flush(); time.sleep(20)"],
            stdout=subprocess.PIPE, text=True)
        self.holder.stdout.readline()

    def tearDown(self):
        self.holder.kill()
        self.holder.wait()
        self.holder.stdout.close()
        super().tearDown()

    def test_probed_once_and_reported_as_chatgpt(self):
        """The codex probe already covers every thread in the shared store, so
        the chatgpt spec must not probe the same locks a second time."""
        self.assertIsNone(tk.CHATGPT_AGENT.live_probe)
        self.assertIsNone(tk.CHATGPT_AGENT.live_info)
        ctx = tk.StatusContext.capture()
        self.assertIn(CHAT_SID, ctx.live)
        self.assertEqual(ctx.resolve(CHAT_SID), tk.STATUS_WORKING)
        info = tk.get_live_session_info(CHAT_SID)
        self.assertEqual(info["agent"], "chatgpt")
        self.assertEqual(info["cwd"], CHAT_CWD)


if __name__ == "__main__":
    unittest.main()
