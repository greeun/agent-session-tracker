"""state.json 을 동기화 폴더(Synology Drive 등)에 둔 여러 기기 사이의 충돌.

flock 은 한 기기 안의 쓰기만 직렬화한다. 두 기기가 거의 동시에 state.json 을
저장하면 동기화 클라이언트는 한쪽을 `state_<host>_<date>_Conflict.json` 같은
충돌본으로 따로 빼 두고, 예전 ast 는 그 사본을 읽지 않아 거기에만 있던 done 표시가
사라졌다. load_state() 가 충돌본을 병합하고 save_state() 가 병합한 사본을 지우는지,
done 해제(undone) 가 충돌본의 옛 done 에 되살아나지 않는지 확인한다.
"""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("tracker_state_sync", _REPO / "tracker.py")
tk = importlib.util.module_from_spec(_spec)
sys.modules["tracker_state_sync"] = tk
_spec.loader.exec_module(tk)

SYNOLOGY = "state_hostA.local_Sep-29-203512-2026_Conflict.json"
SYNCTHING = "state.sync-conflict-20260929-203512-ABCDEFG.json"
DROPBOX = "state (hostA's conflicted copy 2026-09-29).json"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig = (tk.CACHE_DIR, tk.STATE_PATH)
        self.addCleanup(self._restore)
        tk.CACHE_DIR = Path(self._tmp.name) / "ast"
        tk.CACHE_DIR.mkdir()
        tk.STATE_PATH = tk.CACHE_DIR / "state.json"

    def _restore(self):
        tk.CACHE_DIR, tk.STATE_PATH = self._orig

    def _write(self, name, data):
        (tk.CACHE_DIR / name).write_text(json.dumps(data), encoding="utf-8")

    def _disk(self):
        return json.loads(tk.STATE_PATH.read_text(encoding="utf-8"))


class TestConflictCopies(_Base):
    def test_done_only_in_conflict_copy_is_visible(self):
        self._write("state.json", {"done": {"a": "2026-09-29T10:00:00+00:00"}})
        self._write(SYNOLOGY, {"done": {"b": "2026-09-29T11:00:00+00:00"}})
        self.assertEqual(tk.done_ids(), {"a", "b"})

    def test_all_sync_client_namings_are_recognised(self):
        self._write("state.json", {})
        for i, name in enumerate((SYNOLOGY, SYNCTHING, DROPBOX)):
            self._write(name, {"done": {f"s{i}": "2026-09-29T11:00:00+00:00"}})
        self.assertEqual(tk.done_ids(), {"s0", "s1", "s2"})

    def test_unrelated_files_are_ignored(self):
        self._write("state.json", {})
        self._write("index_hostA_Conflict.json", {"done": {"x": "t"}})
        self._write("status.hostA.json", {"done": {"y": "t"}})
        (tk.CACHE_DIR / "state.123.tmp").write_text('{"done": {"z": "t"}}')
        self.assertEqual(tk.done_ids(), set())

    def test_save_persists_merge_and_deletes_copies(self):
        self._write("state.json", {"theme": "light"})
        self._write(SYNOLOGY, {"done": {"b": "2026-09-29T11:00:00+00:00"},
                               "theme": "dark"})
        tk.set_done("c", True)
        disk = self._disk()
        self.assertEqual(set(disk["done"]), {"b", "c"})
        self.assertEqual(disk["theme"], "light")      # 정본의 설정이 이긴다
        self.assertNotIn(tk._ABSORBED_KEY, disk)
        self.assertFalse((tk.CACHE_DIR / SYNOLOGY).exists())

    def test_read_only_load_keeps_copies(self):
        self._write("state.json", {})
        self._write(SYNOLOGY, {"done": {"b": "t"}})
        tk.done_ids()
        self.assertTrue((tk.CACHE_DIR / SYNOLOGY).exists())

    def test_corrupt_copy_is_left_alone(self):
        self._write("state.json", {})
        (tk.CACHE_DIR / SYNOLOGY).write_text("{ not json", encoding="utf-8")
        tk.set_done("c", True)
        self.assertTrue((tk.CACHE_DIR / SYNOLOGY).exists())
        self.assertEqual(set(self._disk()["done"]), {"c"})

    def test_copy_appearing_after_load_is_not_deleted(self):
        self._write("state.json", {})
        state = tk.load_state()
        self._write(SYNOLOGY, {"done": {"late": "t"}})
        tk.save_state(state)
        self.assertTrue((tk.CACHE_DIR / SYNOLOGY).exists())


class TestUndoneTombstone(_Base):
    def test_unmark_is_not_resurrected_by_older_copy(self):
        self._write("state.json", {})
        tk.set_done("a", True)
        tk.set_done("a", False)
        self._write(SYNOLOGY, {"done": {"a": "2000-01-01T00:00:00+00:00"}})
        self.assertNotIn("a", tk.done_ids())

    def test_newer_done_in_copy_beats_older_unmark(self):
        self._write("state.json",
                    {"undone": {"a": "2026-09-29T10:00:00+00:00"}})
        self._write(SYNOLOGY, {"done": {"a": "2026-09-29T11:00:00+00:00"}})
        self.assertIn("a", tk.done_ids())

    def test_newer_unmark_in_copy_beats_older_done(self):
        self._write("state.json", {"done": {"a": "2026-09-29T10:00:00+00:00"}})
        self._write(SYNOLOGY, {"undone": {"a": "2026-09-29T11:00:00+00:00"}})
        self.assertNotIn("a", tk.done_ids())

    def test_toggle_records_tombstone_and_remark_clears_it(self):
        self.assertTrue(tk.mark_done("a"))
        self.assertFalse(tk.mark_done("a"))
        self.assertIn("a", self._disk()["undone"])
        self.assertTrue(tk.mark_done("a"))
        self.assertNotIn("undone", self._disk())


class TestStatusFile(_Base):
    def test_status_lives_outside_state_json(self):
        tk.set_status("s", "working", "UserPromptSubmit")
        self.assertEqual(tk.status_overlay()["s"]["state"], "working")
        self.assertFalse(tk.STATE_PATH.exists())
        self.assertTrue(tk._status_path().exists())
        self.assertEqual(tk._status_path().parent, tk.CACHE_DIR)

    def test_legacy_status_bucket_is_dropped_on_save(self):
        self._write("state.json", {"status": {"s": {"state": "working"}},
                                   "theme": "light"})
        tk.set_done("a", True)
        disk = self._disk()
        self.assertNotIn("status", disk)
        self.assertEqual(disk["theme"], "light")

    def test_clearing_absent_status_writes_nothing(self):
        tk.set_status("s", None, "SessionEnd")
        self.assertFalse(tk._status_path().exists())


if __name__ == "__main__":
    unittest.main()
