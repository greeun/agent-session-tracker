"""기기별 세션 기록(devices.<host>.json) — 로컬 history.jsonl 내보내기와 병합.

각 맥의 ~/.claude/history.jsonl 은 동기화되지 않는 로컬 파일이라, 그 맥에서
프롬프트를 입력한 세션만 담는다. sync_device_record() 는 그 파일을 증분으로 읽어
동기화 홈의 devices.<host>.json 에 {sid: 마지막 입력 ms} 를 남기고,
load_device_map() 은 모든 기기 파일을 합쳐 sid → host 를 만든다.
"""
import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("tracker_device_record", _REPO / "tracker.py")
tk = importlib.util.module_from_spec(_spec)
sys.modules["tracker_device_record"] = tk
_spec.loader.exec_module(tk)


def _line(sid, ms):
    d = {"display": "x", "pastedContents": {}, "timestamp": ms, "project": "/p"}
    if sid is not None:
        d["sessionId"] = sid
    return json.dumps(d) + "\n"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self._orig = (tk.CACHE_DIR, tk.STATE_PATH, tk.CLAUDE_HISTORY_PATH, tk._host_id)
        self.addCleanup(self._restore)
        tk.CACHE_DIR = root / "ast"
        tk.CACHE_DIR.mkdir()
        tk.STATE_PATH = tk.CACHE_DIR / "state.json"
        tk.CLAUDE_HISTORY_PATH = root / "history.jsonl"
        tk._host_id = lambda: "HOSTA"
        self.hist = tk.CLAUDE_HISTORY_PATH

    def _restore(self):
        tk.CACHE_DIR, tk.STATE_PATH, tk.CLAUDE_HISTORY_PATH, tk._host_id = self._orig

    def _record(self, host="HOSTA"):
        return json.loads((tk.CACHE_DIR / f"devices.{host}.json").read_text("utf-8"))

    def _write_dev(self, name, sessions, host=None):
        # A sync conflict copy keeps the original's content, host field included.
        host = host or name[len("devices."):-len(".json")]
        (tk.CACHE_DIR / name).write_text(
            json.dumps({"version": 1, "host": host, "sessions": sessions}), "utf-8")


class TestSync(_Base):
    def test_first_sync_records_max_ts(self):
        self.hist.write_text(_line("s1", 100) + _line("s1", 300)
                             + _line("s2", 200) + _line(None, 999), "utf-8")
        self.assertTrue(tk.sync_device_record())
        rec = self._record()
        self.assertEqual(rec["sessions"], {"s1": 300, "s2": 200})
        self.assertEqual(rec["host"], "HOSTA")
        self.assertEqual(rec["source"]["offset"], self.hist.stat().st_size)

    def test_unchanged_source_no_write(self):
        self.hist.write_text(_line("s1", 100), "utf-8")
        tk.sync_device_record()
        path = tk.CACHE_DIR / "devices.HOSTA.json"
        os.utime(path, (1, 1))
        self.assertFalse(tk.sync_device_record())
        self.assertEqual(path.stat().st_mtime, 1)

    def test_append_reads_from_offset(self):
        self.hist.write_text(_line("s1", 100) + _line("s2", 200), "utf-8")
        tk.sync_device_record()
        with self.hist.open("a", encoding="utf-8") as f:
            f.write(_line("s3", 300))
        self.assertTrue(tk.sync_device_record())
        self.assertEqual(self._record()["sessions"], {"s1": 100, "s2": 200, "s3": 300})

    def test_shrunk_source_rereads_and_keeps_known_sessions(self):
        # A trimmed history still proves s1/s2 were typed on this Mac.
        self.hist.write_text(_line("s1", 100) + _line("s2", 200), "utf-8")
        tk.sync_device_record()
        self.hist.write_text(_line("s9", 900), "utf-8")
        tk.sync_device_record()
        self.assertEqual(self._record()["sessions"], {"s1": 100, "s2": 200, "s9": 900})
        self.assertEqual(self._record()["source"]["offset"], self.hist.stat().st_size)

    def test_replaced_by_bigger_file_rereads_from_start(self):
        self.hist.write_text(_line("s1", 100), "utf-8")
        tk.sync_device_record()
        new = self.hist.with_name("history.new")
        new.write_text(_line("s5", 500) + _line("s6", 600), "utf-8")
        new.replace(self.hist)   # new inode, larger than the recorded offset
        tk.sync_device_record()
        self.assertEqual(self._record()["sessions"], {"s1": 100, "s5": 500, "s6": 600})

    def test_partial_last_line_deferred(self):
        full = _line("s1", 100)
        partial = _line("s2", 200).rstrip("\n")
        self.hist.write_text(full + partial, "utf-8")
        tk.sync_device_record()
        rec = self._record()
        self.assertEqual(rec["sessions"], {"s1": 100})
        self.assertEqual(rec["source"]["offset"], len(full.encode()))
        with self.hist.open("a", encoding="utf-8") as f:
            f.write("\n")
        tk.sync_device_record()
        self.assertEqual(self._record()["sessions"], {"s1": 100, "s2": 200})

    def test_broken_json_line_skipped(self):
        self.hist.write_text(_line("s1", 100) + "{not json\n" + _line("s2", 200), "utf-8")
        tk.sync_device_record()
        self.assertEqual(self._record()["sessions"], {"s1": 100, "s2": 200})

    def test_missing_source_noop(self):
        self.assertFalse(tk.sync_device_record())
        self.assertFalse((tk.CACHE_DIR / "devices.HOSTA.json").exists())

    def test_sync_skipped_when_home_stubbed(self):
        tk.CLAUDE_HISTORY_PATH = tk._DEFAULT_CLAUDE_HISTORY_PATH
        self.assertFalse(tk.sync_device_record())
        self.assertFalse((tk.CACHE_DIR / "devices.HOSTA.json").exists())


class TestMerge(_Base):
    def test_merge_latest_host_wins(self):
        self._write_dev("devices.HOSTA.json", {"s1": 100})
        self._write_dev("devices.HOSTB.json", {"s1": 500, "s2": 1})
        self.assertEqual(tk.load_device_map(sync=False), {"s1": "HOSTB", "s2": "HOSTB"})

    def test_tie_goes_to_primary_host(self):
        # A history copied to a new Mac duplicates every line, timestamp included.
        self._write_dev("devices.HOSTA.json", {"s1": 100})
        self._write_dev("devices.HOSTB.json", {"s1": 100})
        tk.save_device_primary("HOSTB")
        self.assertEqual(tk.load_device_map(sync=False), {"s1": "HOSTB"})
        tk.save_device_primary("HOSTA")
        self.assertEqual(tk.load_device_map(sync=False), {"s1": "HOSTA"})

    def test_tie_without_primary_is_host_name_order(self):
        for names in (("HOSTB", "HOSTA"), ("HOSTA", "HOSTB")):
            for p in tk.CACHE_DIR.glob("devices.*.json"):
                p.unlink()
            for n in names:
                self._write_dev(f"devices.{n}.json", {"s1": 100})
            self.assertEqual(tk.load_device_map(sync=False), {"s1": "HOSTA"})

    def test_later_prompt_beats_primary(self):
        self._write_dev("devices.HOSTA.json", {"s1": 200})
        self._write_dev("devices.HOSTB.json", {"s1": 100})
        tk.save_device_primary("HOSTB")
        self.assertEqual(tk.load_device_map(sync=False), {"s1": "HOSTA"})

    def test_conflict_copy_ignored(self):
        self._write_dev("devices.HOSTB.json", {"s1": 5})
        self._write_dev("devices.HOSTB_MBP_Nov-11_Conflict.json", {"s2": 9}, host="HOSTB")
        m = tk.load_device_map(sync=False)
        self.assertEqual(m, {"s1": "HOSTB"})

    def test_sync_runs_before_merge(self):
        self.hist.write_text(_line("s7", 100), "utf-8")
        self.assertEqual(tk.load_device_map(), {"s7": "HOSTA"})

    def test_capture_carries_devices(self):
        self._write_dev("devices.HOSTB.json", {"s1": 5})
        self.assertEqual(tk.StatusContext.capture().devices.get("s1"), "HOSTB")


class TestSyncCost(_Base):
    def test_partial_line_growth_does_not_rewrite(self):
        self.hist.write_text(_line("s1", 100) + '{"display": "x', "utf-8")
        tk.sync_device_record()
        path = tk.CACHE_DIR / "devices.HOSTA.json"
        os.utime(path, (1, 1))
        with self.hist.open("a", encoding="utf-8") as f:
            f.write('yz')            # still no newline
        self.assertFalse(tk.sync_device_record())
        self.assertEqual(path.stat().st_mtime, 1)

    def test_unchanged_source_skips_the_lock(self):
        self.hist.write_text(_line("s1", 100), "utf-8")
        tk.sync_device_record()
        orig = tk._file_lock
        self.addCleanup(setattr, tk, "_file_lock", orig)

        def boom(*a, **k):
            raise AssertionError("lock taken for an unchanged history")
        tk._file_lock = boom
        self.assertFalse(tk.sync_device_record())

    def test_home_under_tempdir_with_real_history_is_skipped(self):
        # AST_HOME pointed at a temp dir before import: CACHE_DIR == _ast_home()
        self.addCleanup(setattr, tk, "_ast_home", tk._ast_home)
        tk._ast_home = lambda: tk.CACHE_DIR
        tk.CLAUDE_HISTORY_PATH = tk._DEFAULT_CLAUDE_HISTORY_PATH
        self.assertFalse(tk.sync_device_record())
        self.assertFalse((tk.CACHE_DIR / "devices.HOSTA.json").exists())


class TestHostId(unittest.TestCase):
    def test_status_path_uses_host_id(self):
        self.assertEqual(tk._status_path().name, f"status.{tk._host_id()}.json")


if __name__ == "__main__":
    unittest.main()
