"""`ast restore` 가 codex / ChatGPT 앱 세션을 이 컴퓨터에 맞게 마무리하는 부분.

롤아웃 파일을 옮기는 것만으로는 ChatGPT 앱에 대화가 보이지 않는다. 앱과 codex는
`$CODEX_HOME/state_*.sqlite` 의 `threads` 표를 목록의 근거로 삼고, 그 DB가 이미
있는 컴퓨터에서는 새로 들어온 롤아웃을 훑지 않는다. 그리고 롤아웃 안의 cwd 는
원본 컴퓨터의 홈 경로(`/Users/<user>/.codex/.chatgpt-projects/<id>`)라서 다른
사용자 이름의 컴퓨터에서는 프로젝트와 연결되지 않는다.

restore 는 그래서 codex 멤버를 쓴 뒤 두 가지를 더 한다:

- cwd 재작성: manifest 의 `source` (백업한 컴퓨터의 home / codex_home) 를 현재
  값으로 치환한다. `source` 가 없는 옛 아카이브는 `/.codex/` 와 `/Documents/Codex/`
  경로 모양으로 추정한다. `--keep-cwd` 로 끈다.
- DB 등록: 행이 없는 스레드마다 `codex archive <id>` → `codex unarchive <id>` 를
  실행해 codex 의 read-repair 가 롤아웃에서 행을 만들게 하고, 그 과정에서 함께
  보관 처리된 하위 스레드를 다시 unarchive 하며, manifest 의 thread_name 을 빈
  `name` 칼럼에 채운다. `--no-register` 로 끈다. codex 가 없거나 DB 가 없으면
  안내만 하고 넘어간다.
"""
import argparse
import importlib.util
import io
import json
import pathlib
import sqlite3
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

_REPO = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("tracker_restore_reg", _REPO / "tracker.py")
tk = importlib.util.module_from_spec(_spec)
sys.modules["tracker_restore_reg"] = tk
_spec.loader.exec_module(tk)

SID = "019cb053-b194-7b22-ae2f-cead6503f03a"
SUB = "019fc7d7-9fde-7bd1-84db-210cc4ef8008"
PROJECT = "g-p-0123456789abcdef0123456789abcdef"
SRC_HOME = "/Users/alice"
SRC_CODEX = "/Users/alice/.codex"
THREAD_NAME = "샘플 스레드 제목"


def _line(ts, etype, payload, ordinal=0):
    return json.dumps({"timestamp": ts, "ordinal": ordinal, "type": etype,
                       "payload": payload}, ensure_ascii=False)


def _rollout(sid, cwd, *, extra_meta=None):
    meta = {"session_id": sid, "id": sid, "timestamp": "2026-03-02T20:53:20.917Z",
            "cwd": cwd, "originator": "codex_work_desktop", "cli_version": "0.154.0",
            "source": "vscode", "model_provider": "openai"}
    meta.update(extra_meta or {})
    lines = [
        _line("2026-03-02T20:53:32.0Z", "session_meta", meta),
        _line("2026-03-02T20:53:32.1Z", "turn_context",
              {"turn_id": "t1", "cwd": cwd, "workspace_roots": [cwd], "model": "gpt-5"}),
        _line("2026-03-02T20:53:40.0Z", "response_item",
              {"type": "message", "role": "user",
               "content": [{"type": "input_text", "text": "hello"}]}),
        _line("2026-03-02T20:53:45.0Z", "response_item",
              {"type": "message", "role": "assistant",
               "content": [{"type": "output_text", "text": "hi"}]}),
    ]
    return "\n".join(lines) + "\n"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._orig = {k: getattr(tk, k) for k in (
            "PROJECTS_DIR", "CONFIG_DIR", "CACHE_DIR", "CACHE_PATH", "STATE_PATH",
            "JOBS_DIR", "DAEMON_DIR", "SESSIONS_REGISTRY_DIR", "CODEX_HOME",
            "CODEX_SESSIONS_DIR", "CODEX_LOCKS_DIR", "CODEX_SESSION_INDEX",
            "_run_codex", "_codex_available")}
        tk.CONFIG_DIR = self.root / "claude"
        tk.PROJECTS_DIR = tk.CONFIG_DIR / "projects"
        tk.CACHE_DIR = self.root / "cache"
        tk.CACHE_PATH = tk.CACHE_DIR / "index.json"
        tk.STATE_PATH = tk.CACHE_DIR / "state.json"
        tk.JOBS_DIR = tk.CONFIG_DIR / "jobs"
        tk.DAEMON_DIR = tk.CONFIG_DIR / "daemon"
        tk.SESSIONS_REGISTRY_DIR = tk.CONFIG_DIR / "sessions"
        tk.CODEX_HOME = self.root / "codex"
        tk.CODEX_SESSIONS_DIR = tk.CODEX_HOME / "sessions"
        tk.CODEX_LOCKS_DIR = tk.CODEX_HOME / "thread-writer-locks"
        tk.CODEX_SESSION_INDEX = tk.CODEX_HOME / "session_index.jsonl"
        self.archive = self.root / "bk.tar.gz"
        self.calls: list[list[str]] = []
        tk._codex_available = lambda: True
        tk._run_codex = self._fake_codex

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(tk, k, v)
        self._tmp.cleanup()

    # ---- a stand-in for the real codex CLI's archive / unarchive ----
    def _fake_codex(self, argv):
        """archive on a missing row inserts it (codex's read-repair) and also
        archives the thread's children, like the real CLI; unarchive clears
        the flag on that one id only."""
        self.calls.append(list(argv))
        verb, sid = argv[0], argv[1]
        con = sqlite3.connect(self.db)
        try:
            if verb == "archive":
                row = con.execute("select id from threads where id=?", (sid,)).fetchone()
                if row is None:
                    con.execute("insert into threads(id, archived, name, cwd) values (?,0,'',?)",
                                (sid, self._cwd_of(sid)))
                con.execute("update threads set archived=1 where id=?", (sid,))
                for child in self.children.get(sid, ()):
                    if con.execute("select id from threads where id=?", (child,)).fetchone() is None:
                        con.execute("insert into threads(id, archived, name, cwd) values (?,0,'',?)",
                                    (child, self._cwd_of(child)))
                    con.execute("update threads set archived=1 where id=?", (child,))
            elif verb == "unarchive":
                con.execute("update threads set archived=0 where id=?", (sid,))
            con.commit()
        finally:
            con.close()
        return 0

    def _cwd_of(self, sid):
        for p in tk.CODEX_SESSIONS_DIR.rglob(f"*{sid}.jsonl"):
            return tk._codex_read_session_meta(p).get("cwd", "")
        return ""

    # ---- fixtures ----
    def make_db(self, rows=()):
        tk.CODEX_HOME.mkdir(parents=True, exist_ok=True)
        self.db = tk.CODEX_HOME / "state_5.sqlite"
        con = sqlite3.connect(self.db)
        con.execute("create table threads (id text primary key, archived integer not null default 0, "
                    "name text, cwd text not null default '')")
        for sid, archived, name in rows:
            con.execute("insert into threads(id, archived, name) values (?,?,?)", (sid, archived, name))
        con.commit()
        con.close()
        self.children = {}

    def rows(self):
        con = sqlite3.connect(self.db)
        try:
            return {r[0]: {"archived": r[1], "name": r[2], "cwd": r[3]}
                    for r in con.execute("select id, archived, name, cwd from threads")}
        finally:
            con.close()

    def write_rollout(self, sid, cwd, *, day="2026/03/03", **kw):
        d = tk.CODEX_SESSIONS_DIR / day
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"rollout-2026-03-03T05-53-20-{sid}.jsonl"
        p.write_text(_rollout(sid, cwd, **kw), encoding="utf-8")
        return p

    def make_archive(self, members, manifest):
        with tarfile.open(self.archive, "w:gz") as tar:
            blob = json.dumps(manifest, ensure_ascii=False).encode()
            info = tarfile.TarInfo("manifest.json")
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
            for name, content in members.items():
                blob = content.encode()
                info = tarfile.TarInfo(name)
                info.size = len(blob)
                tar.addfile(info, io.BytesIO(blob))
        return self.archive

    def source_archive(self, *, with_source=True, cwd=None, thread_name=THREAD_NAME,
                       with_child=True):
        """An archive as the other machine's `ast backup <id>` would write it."""
        cwd = cwd or f"{SRC_CODEX}/.chatgpt-projects/{PROJECT}"
        rel = f"2026/03/03/rollout-2026-03-03T05-53-20-{SID}.jsonl"
        sub_rel = f"2026/03/03/rollout-2026-03-03T05-53-20-{SUB}.jsonl"
        members = {f"codex/{rel}": _rollout(SID, cwd)}
        subs = []
        if with_child:
            members[f"codex/{sub_rel}"] = _rollout(
                SUB, cwd, extra_meta={"parent_thread_id": SID, "thread_source": "subagent"})
            subs = [f"codex/{sub_rel}"]
        manifest = {
            "created_at": "2026-03-03T00:00:00+00:00", "cutoff": None,
            "selection": {"ids": [SID[:8]], "filter": None}, "count": 1,
            "sessions": [{"session_id": SID, "cwd": cwd, "first_ts": None,
                          "last_ts": "2026-03-02T20:53:45+00:00", "msg_count": 2,
                          "first_user_msg": "hello", "agent": "chatgpt",
                          "relpath": rel, "arcname": f"codex/{rel}",
                          "subagents": subs, "thread_name": thread_name}],
        }
        if with_source:
            manifest["source"] = {"home": SRC_HOME, "codex_home": SRC_CODEX}
        return self.make_archive(members, manifest)

    # ---- runners ----
    def run_cmd(self, fn, **kw):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(argparse.Namespace(**kw))
        return rc, out.getvalue(), err.getvalue()

    def restore(self, **kw):
        args = dict(archive=str(self.archive), cwd=None, on_conflict="skip",
                    dry_run=False, yes=True, keep_cwd=False, no_register=False)
        args.update(kw)
        return self.run_cmd(tk.cmd_restore, **args)

    def rollout_cwds(self, sid):
        p = next(tk.CODEX_SESSIONS_DIR.rglob(f"*{sid}.jsonl"))
        out = []
        for ln in p.read_text(encoding="utf-8").splitlines():
            e = json.loads(ln)
            pl = e.get("payload") or {}
            if "cwd" in pl:
                out.append(pl["cwd"])
            if "workspace_roots" in pl:
                out.extend(pl["workspace_roots"])
        return out


class TestBackupRecordsSource(_Base):
    def test_manifest_carries_home_and_codex_home(self):
        self.write_rollout(SID, f"{tk.CODEX_HOME}/.chatgpt-projects/{PROJECT}")
        rc, out, _ = self.run_cmd(tk.cmd_backup, ids=[SID[:8]], filter=None, days=None,
                                  older_than=None, before=None, cwd=None,
                                  out=str(self.archive), delete=False, force=False,
                                  dry_run=False, yes=True)
        self.assertEqual(rc, 0, out)
        with tarfile.open(self.archive, "r:*") as tar:
            m = json.loads(tar.extractfile("manifest.json").read().decode())
        self.assertEqual(m["source"]["home"], str(pathlib.Path.home()))
        self.assertEqual(m["source"]["codex_home"], str(tk.CODEX_HOME))


class TestRemapCwd(_Base):
    def test_codex_home_prefix_is_swapped_for_the_local_one(self):
        src = f"{SRC_CODEX}/.chatgpt-projects/{PROJECT}"
        self.assertEqual(
            tk.remap_source_cwd(src, {"home": SRC_HOME, "codex_home": SRC_CODEX}),
            f"{tk.CODEX_HOME}/.chatgpt-projects/{PROJECT}")

    def test_home_prefix_is_swapped_when_not_under_codex_home(self):
        src = f"{SRC_HOME}/Documents/Codex/2026-03-03/chat"
        self.assertEqual(
            tk.remap_source_cwd(src, {"home": SRC_HOME, "codex_home": SRC_CODEX}),
            str(pathlib.Path.home() / "Documents/Codex/2026-03-03/chat"))

    def test_unrelated_path_is_left_alone(self):
        self.assertEqual(tk.remap_source_cwd("/srv/repo", {"home": SRC_HOME, "codex_home": SRC_CODEX}),
                         "/srv/repo")

    def test_same_machine_is_a_no_op(self):
        src = f"{tk.CODEX_HOME}/.chatgpt-projects/{PROJECT}"
        self.assertEqual(tk.remap_source_cwd(src, {"home": str(pathlib.Path.home()),
                                                   "codex_home": str(tk.CODEX_HOME)}), src)

    def test_prefix_match_is_by_path_component(self):
        # /Users/alice2/... must not be read as /Users/alice + "2/..."
        src = "/Users/alice2/.codex/.chatgpt-projects/x"
        self.assertEqual(tk.remap_source_cwd(src, {"home": SRC_HOME, "codex_home": SRC_CODEX}), src)

    def test_old_archive_without_source_uses_the_path_shape(self):
        src = f"/Users/someone/.codex/.chatgpt-projects/{PROJECT}"
        self.assertEqual(tk.remap_source_cwd(src, None),
                         f"{tk.CODEX_HOME}/.chatgpt-projects/{PROJECT}")
        src2 = "/Users/someone/Documents/Codex/2026-03-03/chat"
        self.assertEqual(tk.remap_source_cwd(src2, None),
                         str(pathlib.Path.home() / "Documents/Codex/2026-03-03/chat"))
        self.assertEqual(tk.remap_source_cwd("/Users/someone/repo", None), "/Users/someone/repo")


class TestRestoreRewritesCwd(_Base):
    def test_parent_and_child_rollouts_point_at_the_local_project_dir(self):
        self.make_db()
        self.source_archive()
        rc, out, _ = self.restore()
        self.assertEqual(rc, 0, out)
        local = f"{tk.CODEX_HOME}/.chatgpt-projects/{PROJECT}"
        for sid in (SID, SUB):
            cwds = self.rollout_cwds(sid)
            self.assertTrue(cwds, sid)
            self.assertTrue(all(c == local for c in cwds), (sid, cwds))
        self.assertIn("2 cwd", out)

    def test_keep_cwd_leaves_the_rollouts_untouched(self):
        self.make_db()
        self.source_archive()
        self.restore(keep_cwd=True)
        self.assertTrue(all(c.startswith(SRC_CODEX) for c in self.rollout_cwds(SID)))

    def test_skipped_member_is_not_rewritten(self):
        self.make_db()
        src = f"{SRC_CODEX}/.chatgpt-projects/{PROJECT}"
        self.write_rollout(SID, src)
        self.source_archive(with_child=False)
        self.restore(on_conflict="skip")
        self.assertTrue(all(c == src for c in self.rollout_cwds(SID)))


class TestRestoreRegisters(_Base):
    def test_missing_thread_is_registered_through_archive_unarchive(self):
        self.make_db()
        self.children = {SID: [SUB]}
        self.source_archive()
        rc, out, _ = self.restore()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls[:2], [["archive", SID], ["unarchive", SID]])
        rows = self.rows()
        self.assertEqual(rows[SID]["archived"], 0)
        self.assertEqual(rows[SUB]["archived"], 0, "the child archived alongside must come back")
        self.assertIn("registered 2 thread(s)", out)

    def test_registered_row_gets_the_local_cwd(self):
        """cwd is rewritten before codex reads the rollout, so the row it
        creates already points at this machine's project dir."""
        self.make_db()
        self.source_archive(with_child=False)
        self.restore()
        self.assertEqual(self.rows()[SID]["cwd"], f"{tk.CODEX_HOME}/.chatgpt-projects/{PROJECT}")

    def test_thread_name_fills_an_empty_name(self):
        self.make_db()
        self.source_archive(with_child=False)
        self.restore()
        self.assertEqual(self.rows()[SID]["name"], THREAD_NAME)

    def test_existing_name_is_not_overwritten(self):
        self.make_db(rows=[(SID, 0, "내가 붙인 이름")])
        self.write_rollout(SID, f"{SRC_CODEX}/.chatgpt-projects/{PROJECT}")
        self.source_archive(with_child=False)
        self.restore(on_conflict="overwrite")
        self.assertEqual(self.rows()[SID]["name"], "내가 붙인 이름")
        self.assertEqual(self.calls, [], "a thread that already has a row is not touched")

    def test_no_register_skips_codex_entirely(self):
        self.make_db()
        self.source_archive()
        self.restore(no_register=True)
        self.assertEqual(self.calls, [])
        self.assertNotIn(SID, self.rows())

    def test_missing_state_db_is_reported_not_fatal(self):
        tk.CODEX_HOME.mkdir(parents=True, exist_ok=True)
        self.source_archive(with_child=False)
        rc, out, _ = self.restore()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls, [])
        self.assertIn("state DB", out)

    def test_missing_codex_binary_prints_the_manual_commands(self):
        self.make_db()
        tk._codex_available = lambda: False
        self.source_archive(with_child=False)
        rc, out, err = self.restore()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.calls, [])
        self.assertIn(f"codex archive {SID}", out + err)

    def test_dry_run_touches_nothing(self):
        self.make_db()
        self.source_archive()
        self.restore(dry_run=True)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.rows(), {})


class TestCli(_Base):
    def test_parser_accepts_the_new_flags(self):
        ap = tk._build_parser()
        ns = ap.parse_args(["restore", "x.tar.gz", "--keep-cwd", "--no-register"])
        self.assertTrue(ns.keep_cwd)
        self.assertTrue(ns.no_register)
        ns = ap.parse_args(["restore", "x.tar.gz"])
        self.assertFalse(ns.keep_cwd)
        self.assertFalse(ns.no_register)


if __name__ == "__main__":
    unittest.main()
