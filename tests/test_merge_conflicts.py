"""`ast merge-conflicts` — 동기화 충돌 사본을 원본 transcript 에 병합한다.

동기화된 ~/.claude/projects 에서 두 기기가 같은 세션을 쓰면 동기화 클라이언트가
진 쪽을 `<sid>_<host>_<date>_Conflict.jsonl` 같은 이름으로 따로 둔다. 목록과
resume 은 `<sid>.jsonl` 만 보므로 사본에만 있는 대화가 보이지 않는다. 이름 인식,
uuid 기준 합집합과 순서 보존, 원본 교체와 사본 백업, 실행 중 세션 건너뛰기,
목록 배지를 확인한다.
"""
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_TP = pathlib.Path(__file__).resolve().parent.parent / "tracker.py"
_spec = importlib.util.spec_from_file_location("tracker_merge_conflicts", _TP)
tk = importlib.util.module_from_spec(_spec)
sys.modules["tracker_merge_conflicts"] = tk
_spec.loader.exec_module(tk)

SID = "aaaaaaaa-1111-2222-3333-444444444444"
SYNOLOGY = f"{SID}_hostA.local_Sep-15-010058-2026_Conflict.jsonl"


def ev(uid, ts, text="x", parent=None):
    return json.dumps({"uuid": uid, "parentUuid": parent, "timestamp": ts,
                       "type": "user", "cwd": "/repo",
                       "message": {"role": "user", "content": text}})


def _quiet(fn, *a, **k):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = fn(*a, **k)
    return rc, out.getvalue() + err.getvalue()


class TestConflictNames(unittest.TestCase):
    def test_sync_client_namings(self):
        d = Path("/p")
        cases = {
            SYNOLOGY: f"{SID}.jsonl",
            f"{SID}.sync-conflict-20260915-010058-ABCDEFG.jsonl": f"{SID}.jsonl",
            f"{SID} (hostA's conflicted copy 2026-09-15).jsonl": f"{SID}.jsonl",
            f"{SID} 2.jsonl": f"{SID}.jsonl",
            "rollout-2026-09-15T01-00-00-x_hostA_Sep-15-010058-2026_Conflict.jsonl":
                "rollout-2026-09-15T01-00-00-x.jsonl",
            "MEMORY_hostA.local_Sep-28-184408-2026_Conflict.md": "MEMORY.md",
            "a_b_hostA_Sep-28-184408-2026_Conflict.md": "a_b.md",
        }
        for name, orig in cases.items():
            self.assertEqual(tk.conflict_original(d / name), d / orig, name)

    def test_plain_names_are_not_copies(self):
        for name in (f"{SID}.jsonl", "notes 2.jsonl", "agent-abc.jsonl",
                     "rollout-2026-09-15T01-00-00-x.jsonl"):
            self.assertIsNone(tk.conflict_original(Path("/p") / name), name)


class TestMergeLines(unittest.TestCase):
    def test_union_in_time_order_first_source_wins(self):
        a = [ev("1", "2026-01-01T00:00:01Z", "a"), ev("2", "2026-01-01T00:00:03Z")]
        b = [ev("1", "2026-01-01T00:00:01Z", "b"), ev("3", "2026-01-01T00:00:02Z"),
             ev("4", "2026-01-01T00:00:04Z")]
        lines, added = tk.merge_transcript_lines([a, b])
        self.assertEqual([json.loads(l)["uuid"] for l in lines], ["1", "3", "2", "4"])
        self.assertEqual(json.loads(lines[0])["message"]["content"], "a")
        self.assertEqual(added, 2)

    def test_source_order_is_kept_and_untimed_lines_stay_put(self):
        summary = json.dumps({"type": "summary", "leafUuid": "2"})
        a = [ev("1", "2026-01-01T00:00:05Z"), summary, ev("2", "2026-01-01T00:00:01Z")]
        lines, added = tk.merge_transcript_lines([a, [summary]])
        self.assertEqual(lines, a)                  # 원본 순서는 건드리지 않는다
        self.assertEqual(added, 0)

    def test_lines_without_uuid_dedupe_by_text(self):
        r1 = json.dumps({"timestamp": "2026-01-01T00:00:01Z", "type": "event_msg"})
        r2 = json.dumps({"timestamp": "2026-01-01T00:00:02Z", "type": "event_msg"})
        lines, added = tk.merge_transcript_lines([[r1], [r1, r2, "not json", ""]])
        self.assertEqual(lines, [r1, r2, "not json"])
        self.assertEqual(added, 2)


class _FsBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        names = ("PROJECTS_DIR", "CODEX_SESSIONS_DIR", "CODEX_LOCKS_DIR",
                 "CACHE_DIR", "CACHE_PATH", "STATE_PATH")
        self._orig = {k: getattr(tk, k) for k in names}
        self.addCleanup(lambda: [setattr(tk, k, v) for k, v in self._orig.items()])
        tk.PROJECTS_DIR = root / "projects"
        tk.CODEX_SESSIONS_DIR = root / "codex_sessions"
        tk.CODEX_LOCKS_DIR = root / "codex_locks"
        tk.CACHE_DIR = root / "cache"
        tk.CACHE_PATH = tk.CACHE_DIR / "index.json"
        tk.STATE_PATH = tk.CACHE_DIR / "state.json"
        self.proj = tk.PROJECTS_DIR / "-repo"
        self.proj.mkdir(parents=True)
        self.orig = self.proj / f"{SID}.jsonl"
        self.copy = self.proj / SYNOLOGY

    def _write(self, path, lines):
        path.write_text("".join(l + "\n" for l in lines), encoding="utf-8")

    def _uuids(self, path):
        return [json.loads(l)["uuid"] for l in path.read_text().splitlines()]

    def _run(self, live=(), **kw):
        orig_cap = tk.StatusContext.capture
        tk.StatusContext.capture = staticmethod(
            lambda: type("C", (), {"live": set(live)})())
        try:
            ns = tk.argparse.Namespace(dry_run=False, yes=True, force=False)
            for k, v in kw.items():
                setattr(ns, k, v)
            return _quiet(tk.cmd_merge_conflicts, ns)
        finally:
            tk.StatusContext.capture = orig_cap


class TestMergeCommand(_FsBase):
    def test_copy_is_folded_in_and_moved_to_backup(self):
        self._write(self.orig, [ev("1", "2026-01-01T00:00:01Z")])
        self._write(self.copy, [ev("1", "2026-01-01T00:00:01Z"),
                                ev("2", "2026-01-01T00:00:02Z")])
        rc, out = self._run()
        self.assertEqual(rc, 0, out)
        self.assertEqual(self._uuids(self.orig), ["1", "2"])
        self.assertFalse(self.copy.exists())
        backups = list((tk.CACHE_DIR / "backups" / "conflicts").rglob(SYNOLOGY))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].parent.name, "-repo")
        kept = list((tk.CACHE_DIR / "backups" / "conflicts").rglob(f"{SID}.jsonl"))
        self.assertEqual(len(kept), 1)
        self.assertEqual(self._uuids(kept[0]), ["1"])       # 병합 전 원본

    def test_merged_file_keeps_newest_source_mtime(self):
        import os
        self._write(self.orig, [ev("1", "2026-01-01T00:00:01Z")])
        self._write(self.copy, [ev("2", "2026-01-01T00:00:02Z")])
        os.utime(self.orig, (1_000_000, 1_000_000))
        os.utime(self.copy, (2_000_000, 2_000_000))
        rc, _ = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(self.orig.stat().st_mtime, 2_000_000)

    def test_missing_original_is_rebuilt_from_copy(self):
        self._write(self.copy, [ev("1", "2026-01-01T00:00:01Z")])
        rc, _ = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(self._uuids(self.orig), ["1"])

    def test_dry_run_writes_nothing(self):
        self._write(self.orig, [ev("1", "2026-01-01T00:00:01Z")])
        self._write(self.copy, [ev("2", "2026-01-01T00:00:02Z")])
        rc, out = self._run(dry_run=True)
        self.assertEqual(rc, 0)
        self.assertIn("dry run", out)
        self.assertEqual(self._uuids(self.orig), ["1"])
        self.assertTrue(self.copy.exists())

    def test_live_session_is_skipped_unless_forced(self):
        self._write(self.orig, [ev("1", "2026-01-01T00:00:01Z")])
        self._write(self.copy, [ev("2", "2026-01-01T00:00:02Z")])
        rc, out = self._run(live={SID})
        self.assertEqual(rc, 1)
        self.assertIn("skipped", out)
        self.assertTrue(self.copy.exists())
        rc, _ = self._run(live={SID}, force=True)
        self.assertEqual(rc, 0)
        self.assertEqual(self._uuids(self.orig), ["1", "2"])

    def test_codex_store_is_scanned(self):
        day = tk.CODEX_SESSIONS_DIR / "2026" / "01" / "01"
        day.mkdir(parents=True)
        orig = day / "rollout-2026-01-01T00-00-00-x.jsonl"
        copy = day / "rollout-2026-01-01T00-00-00-x_hostA_Jan-01-000000-2026_Conflict.jsonl"
        r1 = json.dumps({"timestamp": "2026-01-01T00:00:01Z", "type": "a"})
        r2 = json.dumps({"timestamp": "2026-01-01T00:00:02Z", "type": "b"})
        self._write(orig, [r1])
        self._write(copy, [r1, r2])
        self.assertEqual(tk.find_transcript_conflicts(), {orig: [copy]})
        rc, _ = self._run()
        self.assertEqual(rc, 0)
        self.assertEqual(orig.read_text().splitlines(), [r1, r2])

    def test_nothing_to_do(self):
        rc, out = self._run()
        self.assertEqual(rc, 0)
        self.assertIn("no sync conflict copies", out)

    def test_non_interactive_without_yes_refuses(self):
        self._write(self.copy, [ev("1", "2026-01-01T00:00:01Z")])
        orig_stdin = sys.stdin
        sys.stdin = io.StringIO("")
        try:
            rc, out = self._run(yes=False)
        finally:
            sys.stdin = orig_stdin
        self.assertEqual(rc, 1)
        self.assertIn("--yes", out)
        self.assertFalse(self.orig.exists())


class TestBadge(unittest.TestCase):
    def test_dedupe_counts_copies_on_the_kept_row(self):
        a = tk.SessionMeta(session_id=SID, path=Path(f"/p/{SID}.jsonl"))
        b = tk.SessionMeta(session_id=SID, path=Path(f"/p/{SYNOLOGY}"))
        kept = tk.dedupe_sessions([b, a])
        self.assertEqual(kept, [a])
        self.assertEqual(a.conflicts, 1)

    def test_badge_text(self):
        self.assertEqual(tk.conflict_badge(0), "")
        self.assertEqual(tk.conflict_badge(1), "[conflict]")
        self.assertEqual(tk.conflict_badge(3), "[conflict:3]")


if __name__ == "__main__":
    unittest.main()
