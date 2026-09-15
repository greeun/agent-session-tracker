"""`ast backup <id>…` / `--filter` — 특정 세션을 다른 컴퓨터로 옮기는 용도.

기존 backup은 "기준일보다 오래된 세션"만 고르는 정리용 명령이라, 최근 대화
하나를 옮기려면 내일 날짜를 --before 에 지정하는 우회가 필요했다. 여기서는
세션을 직접 지정하는 선택 방식과, 함께 옮겨야 완전한 부속 파일들을 다룬다:

- 부모 세션의 하위 전사본 (claude `subagents/*.jsonl` + `.meta.json`,
  codex `parent_thread_id` 롤아웃) 이 같은 tarball 에 들어가고 restore 가 원위치로
  되돌린다.
- codex 스레드 제목 (`$CODEX_HOME/session_index.jsonl` 의 한 줄) 을 manifest 에
  기록하고, restore 가 대상 컴퓨터의 색인에 그 줄이 없으면 덧붙인다.
"""
import argparse
import importlib.util
import io
import json
import pathlib
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

_REPO = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("tracker_bk_migrate", _REPO / "tracker.py")
tk = importlib.util.module_from_spec(_spec)
sys.modules["tracker_bk_migrate"] = tk
_spec.loader.exec_module(tk)

SID = "019cb053-b194-7b22-ae2f-cead6503f03a"
SUB = "019fc7d7-9fde-7bd1-84db-210cc4ef8008"
OTHER = "019de2b1-deef-74d1-ba0c-228e126e2b67"
CWD = "/repo/codex-app"
CLAUDE_SID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
CLAUDE_SUB = "bbbbbbbb-cccc-dddd-eeee-ffffffffffff"
THREAD_NAME = "샘플 스레드 제목"


def _line(ts, etype, payload, ordinal=0):
    return json.dumps({"timestamp": ts, "ordinal": ordinal, "type": etype,
                       "payload": payload}, ensure_ascii=False)


def _rollout(sid, cwd, *, extra_meta=None, first_msg="build it"):
    meta = {"session_id": sid, "id": sid, "timestamp": "2026-03-02T20:53:20.917Z",
            "cwd": cwd, "originator": "codex_cli_rs", "cli_version": "0.151.0",
            "source": "cli", "model_provider": "openai"}
    meta.update(extra_meta or {})
    lines = [
        _line("2026-03-02T20:53:32.0Z", "session_meta", meta),
        _line("2026-03-02T20:53:40.0Z", "response_item",
              {"type": "message", "role": "user",
               "content": [{"type": "input_text", "text": first_msg}]}),
        _line("2026-03-02T20:53:45.0Z", "response_item",
              {"type": "message", "role": "assistant",
               "content": [{"type": "output_text", "text": "On it."}]}),
    ]
    return "\n".join(lines) + "\n"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._orig = {k: getattr(tk, k) for k in (
            "PROJECTS_DIR", "CONFIG_DIR", "CACHE_DIR", "CACHE_PATH", "STATE_PATH",
            "JOBS_DIR", "DAEMON_DIR", "SESSIONS_REGISTRY_DIR",
            "CODEX_SESSIONS_DIR", "CODEX_LOCKS_DIR", "CODEX_SESSION_INDEX")}
        tk.CONFIG_DIR = self.root / "claude"
        tk.PROJECTS_DIR = tk.CONFIG_DIR / "projects"
        tk.CACHE_DIR = self.root / "cache"
        tk.CACHE_PATH = tk.CACHE_DIR / "index.json"
        tk.STATE_PATH = tk.CACHE_DIR / "state.json"
        tk.JOBS_DIR = tk.CONFIG_DIR / "jobs"
        tk.DAEMON_DIR = tk.CONFIG_DIR / "daemon"
        tk.SESSIONS_REGISTRY_DIR = tk.CONFIG_DIR / "sessions"
        tk.CODEX_SESSIONS_DIR = self.root / "codex" / "sessions"
        tk.CODEX_LOCKS_DIR = self.root / "codex" / "thread-writer-locks"
        tk.CODEX_SESSION_INDEX = self.root / "codex" / "session_index.jsonl"
        self.archive = self.root / "bk.tar.gz"

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(tk, k, v)
        self._tmp.cleanup()

    # ---- fixtures ----
    def write_rollout(self, sid, cwd=CWD, *, day="2026/03/03", **kw):
        d = tk.CODEX_SESSIONS_DIR / day
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"rollout-2026-03-03T05-53-20-{sid}.jsonl"
        p.write_text(_rollout(sid, cwd, **kw), encoding="utf-8")
        return p

    def write_codex_sub(self, parent=SID, sid=SUB):
        return self.write_rollout(sid, extra_meta={
            "parent_thread_id": parent, "thread_source": "subagent"})

    def write_index(self, entries):
        tk.CODEX_SESSION_INDEX.parent.mkdir(parents=True, exist_ok=True)
        tk.CODEX_SESSION_INDEX.write_text(
            "".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
            encoding="utf-8")

    def write_claude(self, sid=CLAUDE_SID, cwd="/repo/claude-app"):
        d = tk.PROJECTS_DIR / tk.encode_cwd(cwd)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{sid}.jsonl"
        rows = [
            {"type": "user", "timestamp": "2026-03-02T20:00:00.000Z", "cwd": cwd,
             "message": {"content": "ship the fix"}},
            {"type": "assistant", "timestamp": "2026-03-02T20:00:05.000Z", "cwd": cwd,
             "message": {"content": [{"type": "text", "text": "done"}]}},
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return p

    def write_claude_sub(self, parent_path, sid=CLAUDE_SUB):
        d = tk.subagents_dir(parent_path)
        d.mkdir(parents=True, exist_ok=True)
        jp = d / f"{sid}.jsonl"
        jp.write_text(json.dumps({"type": "user", "timestamp": "2026-03-02T20:01:00.000Z",
                                  "message": {"content": "sub work"}}) + "\n",
                      encoding="utf-8")
        mp = jp.with_suffix(".meta.json")
        mp.write_text(json.dumps({"agentType": "Explore", "description": "look"}),
                      encoding="utf-8")
        return jp, mp

    # ---- runners ----
    def run_cmd(self, fn, **kw):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(argparse.Namespace(**kw))
        return rc, out.getvalue(), err.getvalue()

    def backup(self, **kw):
        args = dict(ids=[], filter=None, days=None, older_than=None, before=None,
                    cwd=None, out=str(self.archive), delete=False, force=False,
                    dry_run=False, yes=True)
        args.update(kw)
        return self.run_cmd(tk.cmd_backup, **args)

    def restore(self, **kw):
        args = dict(archive=str(self.archive), cwd=None, on_conflict="skip",
                    dry_run=False, yes=True)
        args.update(kw)
        return self.run_cmd(tk.cmd_restore, **args)

    def members(self):
        with tarfile.open(self.archive, "r:*") as tar:
            return sorted(m.name for m in tar.getmembers() if m.isfile())

    def manifest(self):
        with tarfile.open(self.archive, "r:*") as tar:
            return json.loads(tar.extractfile("manifest.json").read().decode())


class TestSelectById(_Base):
    """세션을 직접 지정하면 날짜 기준은 적용되지 않는다."""

    def test_recent_session_is_archived_without_a_cutoff(self):
        self.write_rollout(SID)
        rc, out, _ = self.backup(ids=[SID[:8]])
        self.assertEqual(rc, 0, out)
        self.assertIn("✓ Wrote 1/1", out)
        self.assertIn("Selected sessions: 1", out)
        self.assertNotIn("older than", out)

    def test_only_the_named_sessions_are_taken(self):
        self.write_rollout(SID)
        self.write_rollout(OTHER)
        self.backup(ids=[SID[:8]])
        names = self.members()
        self.assertTrue(any(SID in n for n in names), names)
        self.assertFalse(any(OTHER in n for n in names), names)

    def test_unknown_id_is_an_error(self):
        self.write_rollout(SID)
        rc, out, err = self.backup(ids=["ffffffff"])
        self.assertEqual(rc, 1)
        self.assertIn("ffffffff", err)
        self.assertFalse(self.archive.exists())

    def test_filter_matches_first_message_and_cwd(self):
        self.write_rollout(SID, first_msg="샘플 앱 기획 메모")
        self.write_rollout(OTHER, first_msg="unrelated")
        rc, out, _ = self.backup(filter="샘플")
        self.assertEqual(rc, 0, out)
        names = self.members()
        self.assertTrue(any(SID in n for n in names), names)
        self.assertFalse(any(OTHER in n for n in names), names)

    def test_explicit_cutoff_still_narrows_a_filter(self):
        self.write_rollout(SID)   # last activity 2026-03-02
        rc, out, _ = self.backup(filter="build", before="2026-01-01")
        self.assertEqual(rc, 0)
        self.assertIn("no sessions", out)
        self.assertFalse(self.archive.exists())

    def test_older_than_is_an_alias_for_days(self):
        self.write_rollout(SID)
        rc, out, _ = self.backup(older_than=0)
        self.assertEqual(rc, 0, out)
        self.assertIn("✓ Wrote 1/1", out)


class TestSubagentsTravel(_Base):
    def test_codex_child_rollouts_ride_along(self):
        self.write_rollout(SID)
        self.write_codex_sub()
        self.backup(ids=[SID[:8]])
        names = self.members()
        self.assertTrue(any(SUB in n for n in names), names)
        entry = self.manifest()["sessions"][0]
        self.assertEqual(len(entry["subagents"]), 1)
        self.assertIn(SUB, entry["subagents"][0])

    def test_claude_subagent_dir_rides_along_with_meta(self):
        parent = self.write_claude()
        self.write_claude_sub(parent)
        self.backup(ids=[CLAUDE_SID[:8]])
        names = self.members()
        self.assertTrue(any(n.endswith(f"subagents/{CLAUDE_SUB}.jsonl") for n in names), names)
        self.assertTrue(any(n.endswith(f"subagents/{CLAUDE_SUB}.meta.json") for n in names), names)

    def test_restore_puts_subagents_back(self):
        parent = self.write_claude()
        jp, mp = self.write_claude_sub(parent)
        self.write_rollout(SID)
        sub_path = self.write_codex_sub()
        self.backup(ids=[CLAUDE_SID[:8], SID[:8]])
        for p in (parent, jp, mp, sub_path):
            p.unlink()
        rc, out, _ = self.restore()
        self.assertEqual(rc, 0, out)
        for p in (parent, jp, mp, sub_path):
            self.assertTrue(p.exists(), p)
        self.assertIn("sub work", jp.read_text(encoding="utf-8"))

    def test_cutoff_backup_also_carries_subagents(self):
        """정리용 경로(--before)도 같은 묶음 규칙을 따른다."""
        self.write_rollout(SID)
        self.write_codex_sub()
        self.backup(before="2099-01-01")
        self.assertTrue(any(SUB in n for n in self.members()))


class TestThreadName(_Base):
    def test_manifest_records_the_codex_thread_name(self):
        self.write_rollout(SID)
        self.write_index([{"id": SID, "thread_name": THREAD_NAME,
                           "updated_at": "2026-03-02T20:53:45Z"}])
        self.backup(ids=[SID[:8]])
        entry = self.manifest()["sessions"][0]
        self.assertEqual(entry["thread_name"], THREAD_NAME)

    def test_restore_appends_the_index_line_once(self):
        self.write_rollout(SID)
        self.write_index([{"id": SID, "thread_name": THREAD_NAME,
                           "updated_at": "2026-03-02T20:53:45Z"}])
        self.backup(ids=[SID[:8]])
        # 대상 컴퓨터: 색인은 다른 스레드만 알고 있다.
        self.write_index([{"id": OTHER, "thread_name": "x", "updated_at": "2026-01-01T00:00:00Z"}])
        rc, out, _ = self.restore(on_conflict="overwrite")
        self.assertEqual(rc, 0, out)
        lines = [json.loads(l) for l in tk.CODEX_SESSION_INDEX.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual([e["id"] for e in lines], [OTHER, SID])
        self.assertEqual(lines[1]["thread_name"], THREAD_NAME)
        self.assertIn("thread name", out)
        # 두 번째 복원은 같은 줄을 다시 붙이지 않는다.
        self.restore(on_conflict="overwrite")
        lines = [l for l in tk.CODEX_SESSION_INDEX.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(lines), 2)

    def test_restore_creates_the_index_when_missing(self):
        self.write_rollout(SID)
        self.write_index([{"id": SID, "thread_name": THREAD_NAME,
                           "updated_at": "2026-03-02T20:53:45Z"}])
        self.backup(ids=[SID[:8]])
        tk.CODEX_SESSION_INDEX.unlink()
        self.restore(on_conflict="overwrite")
        self.assertIn(THREAD_NAME, tk.CODEX_SESSION_INDEX.read_text(encoding="utf-8"))

    def test_skipped_session_does_not_touch_the_index(self):
        self.write_rollout(SID)
        self.write_index([{"id": SID, "thread_name": THREAD_NAME,
                           "updated_at": "2026-03-02T20:53:45Z"}])
        self.backup(ids=[SID[:8]])
        self.write_index([])
        self.restore(on_conflict="skip")   # 롤아웃이 이미 있으므로 건너뜀
        self.assertEqual(tk.CODEX_SESSION_INDEX.read_text(encoding="utf-8"), "")


class TestCli(_Base):
    def test_parser_accepts_ids_filter_and_older_than(self):
        ap = tk._build_parser()
        ns = ap.parse_args(["backup", "abc", "def", "--filter", "x", "--older-than", "5"])
        self.assertEqual(ns.ids, ["abc", "def"])
        self.assertEqual(ns.filter, "x")
        self.assertEqual(ns.older_than, 5)
        ns = ap.parse_args(["backup", "--days", "3"])
        self.assertEqual(ns.ids, [])
        self.assertEqual(ns.days, 3)


if __name__ == "__main__":
    unittest.main()
