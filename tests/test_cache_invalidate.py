"""인덱스 캐시를 **엔트리 단위로** 버리는가.

relocate 와 restore 는 transcript 를 옮기거나 덮어쓰므로 해당 세션의 캐시
엔트리를 무효화해야 한다. 예전에는 `index.json` 자체를 지웠는데, 그러면 세션
한 건을 고친 대가로 다음 실행이 전량 재파싱이 된다(수천 세션에서 10초 이상).
TUI 의 Enter 가 고아 세션 relocate 흐름을 타므로 그 비용은 곧바로 다음
rescan 에 떨어졌다.

여기서 고정하는 성질: 관련된 엔트리만 사라지고, **나머지는 전부 살아남고**,
그 결과 다음 로드가 건드린 파일만 다시 읽는다.
"""

import importlib.util
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def load_tracker():
    spec = importlib.util.spec_from_file_location("tracker_cacheinv", _REPO / "tracker.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tracker_cacheinv"] = mod
    spec.loader.exec_module(mod)
    return mod


tk = load_tracker()


class _Base(unittest.TestCase):
    N = 5

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self._orig = (tk.PROJECTS_DIR, tk.CODEX_SESSIONS_DIR, tk.CODEX_LOCKS_DIR,
                      tk.CACHE_DIR, tk.CACHE_PATH)
        self.addCleanup(self._restore)
        tk.PROJECTS_DIR = root / "projects"
        tk.CODEX_SESSIONS_DIR = root / "codex_sessions"
        tk.CODEX_LOCKS_DIR = root / "codex_locks"
        tk.CACHE_DIR = root / "cache"
        tk.CACHE_PATH = tk.CACHE_DIR / "index.json"

        base = datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.files = [
            self._mk(f"{i:08d}-0000-0000-0000-000000000000",
                     base + timedelta(minutes=i))
            for i in range(self.N)
        ]

    def _restore(self):
        (tk.PROJECTS_DIR, tk.CODEX_SESSIONS_DIR, tk.CODEX_LOCKS_DIR,
         tk.CACHE_DIR, tk.CACHE_PATH) = self._orig

    def _mk(self, sid, ts, cwd="/repo/app"):
        p = tk.PROJECTS_DIR / tk.encode_cwd(cwd) / f"{sid}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({
            "type": "user", "cwd": cwd,
            "timestamp": ts.isoformat().replace("+00:00", "Z"),
            "message": {"content": f"요청 {sid[:4]}"},
        }) + "\n", encoding="utf-8")
        return p

    def _entries(self):
        return set(json.loads(tk.CACHE_PATH.read_text(encoding="utf-8"))["entries"])


class TestInvalidateCacheEntries(_Base):
    def test_removes_only_the_named_paths(self):
        tk.load_all_sessions()
        before = self._entries()
        self.assertEqual(len(before), self.N)

        removed = tk.invalidate_cache_entries([self.files[2]])
        self.assertEqual(removed, 1)
        after = self._entries()
        self.assertEqual(before - after, {str(self.files[2])})
        self.assertEqual(len(after), self.N - 1)

    def test_unknown_path_is_not_counted_and_changes_nothing(self):
        tk.load_all_sessions()
        before = self._entries()
        self.assertEqual(tk.invalidate_cache_entries(
            [tk.PROJECTS_DIR / "nope" / "x.jsonl"]), 0)
        self.assertEqual(self._entries(), before)

    def test_empty_input_leaves_the_cache_file_untouched(self):
        tk.load_all_sessions()
        stamp = tk.CACHE_PATH.stat().st_mtime_ns
        self.assertEqual(tk.invalidate_cache_entries([]), 0)
        self.assertEqual(tk.CACHE_PATH.stat().st_mtime_ns, stamp)

    def test_missing_cache_file_is_not_an_error(self):
        self.assertFalse(tk.CACHE_PATH.exists())
        self.assertEqual(tk.invalidate_cache_entries([self.files[0]]), 0)

    def test_only_the_invalidated_file_is_reparsed_next_load(self):
        tk.load_all_sessions()
        tk.invalidate_cache_entries([self.files[1]])

        parsed = []
        orig = tk.load_session_meta

        def counted(path, fast=True):
            parsed.append(Path(path).name)
            return orig(path, fast=fast)

        tk.load_session_meta = counted
        self.addCleanup(setattr, tk, "load_session_meta", orig)
        rows = tk.load_all_sessions()
        self.assertEqual(parsed, [self.files[1].name])
        self.assertEqual(len(rows), self.N)


class TestRelocateKeepsOtherEntries(_Base):
    def test_relocate_does_not_discard_the_whole_index(self):
        sessions = tk.load_all_sessions()
        before = self._entries()
        target = next(s for s in sessions if s.path == self.files[3])

        new_cwd = str(Path(self._tmp.name) / "moved")
        Path(new_cwd).mkdir(parents=True, exist_ok=True)
        res = tk.relocate_session(target, new_cwd, dry_run=False)
        self.assertTrue(res.ok, res.message)

        self.assertTrue(tk.CACHE_PATH.exists(),
                        "relocate 가 인덱스 파일 자체를 지웠다")
        after = self._entries()
        # 옮긴 세션의 옛 경로만 빠지고 나머지 4건은 그대로 남는다.
        self.assertNotIn(str(self.files[3]), after)
        for keep in (self.files[0], self.files[1], self.files[2], self.files[4]):
            self.assertIn(str(keep), after)
        self.assertEqual(len(before) - len(after), 1)

    def test_next_load_reparses_only_the_moved_session(self):
        sessions = tk.load_all_sessions()
        target = next(s for s in sessions if s.path == self.files[3])
        new_cwd = str(Path(self._tmp.name) / "moved2")
        Path(new_cwd).mkdir(parents=True, exist_ok=True)
        self.assertTrue(tk.relocate_session(target, new_cwd, dry_run=False).ok)

        parsed = []
        orig = tk.load_session_meta

        def counted(path, fast=True):
            parsed.append(Path(path).name)
            return orig(path, fast=fast)

        tk.load_session_meta = counted
        self.addCleanup(setattr, tk, "load_session_meta", orig)
        rows = tk.load_all_sessions()
        # 새 경로 한 건만 읽는다(옛 경로는 사라졌으므로 읽을 것이 없다).
        self.assertEqual(parsed, [self.files[3].name])
        self.assertEqual(len(rows), self.N)
        self.assertTrue(any(r.cwd == new_cwd for r in rows))


if __name__ == "__main__":
    unittest.main()
