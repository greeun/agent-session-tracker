"""기기 표시·별칭·필터 도우미와 `ast devices`.

device_of 는 이 맥에서 실행 중인 세션을 history 보다 우선해 이 맥으로 본다.
특정 기기·local 필터는 기기 미상(?) 행을 빼고 그 수를 돌려준다.
"""
import argparse
import contextlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

_REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("tracker_device_filter", _REPO / "tracker.py")
tk = importlib.util.module_from_spec(_spec)
sys.modules["tracker_device_filter"] = tk
_spec.loader.exec_module(tk)


def _ctx(devices, live=()):
    return tk.StatusContext(live=set(live), done=set(), registry={}, overlay={},
                            jobs={}, devices=dict(devices))


def _s(sid):
    return SimpleNamespace(session_id=sid)


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

    def _restore(self):
        tk.CACHE_DIR, tk.STATE_PATH, tk.CLAUDE_HISTORY_PATH, tk._host_id = self._orig


class TestHelpers(_Base):
    def test_live_overrides_history(self):
        self.assertEqual(tk.device_of("s1", _ctx({"s1": "HOSTB"}, live={"s1"})), "HOSTA")
        self.assertEqual(tk.device_of("s1", _ctx({"s1": "HOSTB"})), "HOSTB")
        self.assertIsNone(tk.device_of("s9", _ctx({})))

    def test_label_alias_truncate_unknown(self):
        self.assertEqual(tk.device_label("MBP-M4P-24-H", {"MBP-M4P-24-H": "mbp"}), "mbp")
        self.assertEqual(tk.device_label("MBP-M4P-24-H", {}), "MBP-M4")
        self.assertEqual(tk.device_label(None, {}), "?")

    def test_filter_host_drops_unknown_and_counts(self):
        ctx = _ctx({"s1": "HOSTB", "s2": "HOSTA"})
        rows = [_s("s1"), _s("s2"), _s("s3")]
        ids = lambda r: [x.session_id for x in r[0]]
        self.assertEqual((ids(tk.filter_device(rows, "HOSTB", ctx)),
                          tk.filter_device(rows, "HOSTB", ctx)[1]), (["s1"], 1))
        self.assertEqual((ids(tk.filter_device(rows, "local", ctx)),
                          tk.filter_device(rows, "local", ctx)[1]), (["s2"], 1))
        self.assertEqual((ids(tk.filter_device(rows, "?", ctx)),
                          tk.filter_device(rows, "?", ctx)[1]), (["s3"], 0))
        self.assertEqual((ids(tk.filter_device(rows, "all", ctx)),
                          tk.filter_device(rows, "all", ctx)[1]), (["s1", "s2", "s3"], 0))

    def test_resolve_view(self):
        aliases, known = {"HOSTB": "mbp"}, {"HOSTA", "HOSTB"}
        self.assertEqual(tk.resolve_device_view("MBP", aliases, known), "HOSTB")
        self.assertEqual(tk.resolve_device_view("hostb", aliases, known), "HOSTB")
        self.assertEqual(tk.resolve_device_view("Local", aliases, known), "local")
        self.assertEqual(tk.resolve_device_view("ALL", aliases, known), "all")
        self.assertEqual(tk.resolve_device_view("?", aliases, known), "?")
        self.assertIsNone(tk.resolve_device_view("nope", aliases, known))

    def test_choices_and_cycle(self):
        ctx = _ctx({"a": "HOSTA", "b": "HOSTB", "c": "HOSTC"})
        choices = tk.device_choices(ctx)
        self.assertEqual(choices, ("all", "local", "HOSTB", "HOSTC"))
        self.assertEqual(tk.cycle_device("HOSTC", choices), "all")
        self.assertEqual(tk.cycle_device("all", choices, -1), "HOSTC")
        self.assertEqual(tk.cycle_device("gone", choices), "local")

    def test_note(self):
        self.assertEqual(tk.device_note("all", {}, 3), "")
        self.assertEqual(tk.device_note("HOSTB", {"HOSTB": "mbp"}, 0), "  [device:mbp]")
        self.assertEqual(tk.device_note("local", {}, 12), "  [device:local, ?:12 hidden]")


class TestPersistence(_Base):
    def test_view_round_trip(self):
        self.assertEqual(tk.load_device_view(), "all")
        tk.save_device_view("HOSTB")
        self.assertEqual(tk.load_device_view(), "HOSTB")

    def test_alias_round_trip(self):
        tk.save_device_alias("HOSTB", "mbp")
        self.assertEqual(tk.load_device_aliases(), {"HOSTB": "mbp"})
        tk.save_device_alias("HOSTB", None)
        self.assertEqual(tk.load_device_aliases(), {})


class TestCmdDevices(_Base):
    def _run(self, **kw):
        ns = argparse.Namespace(alias=kw.get("alias"), unalias=kw.get("unalias"),
                                primary=kw.get("primary"),
                                no_primary=kw.get("no_primary", False))
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            rc = tk.cmd_devices(ns)
        return rc, out.getvalue(), err.getvalue()

    def test_alias_and_listing(self):
        (tk.CACHE_DIR / "devices.HOSTB.json").write_text(json.dumps(
            {"version": 1, "host": "HOSTB", "sessions": {"s1": 1, "s2": 2}}), "utf-8")
        (tk.CACHE_DIR / "devices.HOSTA.json").write_text(json.dumps(
            {"version": 1, "host": "HOSTA", "sessions": {"s3": 1}}), "utf-8")
        rc, _, _ = self._run(alias="HOSTB=mbp")
        self.assertEqual(rc, 0)
        self.assertEqual(tk.load_device_aliases(), {"HOSTB": "mbp"})
        rc, out, _ = self._run()
        self.assertEqual(rc, 0)
        lines = {l.split()[0].lstrip("*"): l for l in out.splitlines()[1:] if l.strip()}
        self.assertIn("mbp", lines["HOSTB"])
        self.assertIn("2", lines["HOSTB"].split())
        self.assertTrue(lines["HOSTA"].startswith("*"))

    def test_bad_alias_rc2(self):
        rc, _, err = self._run(alias="bad")
        self.assertEqual(rc, 2)
        self.assertIn("HOST=NAME", err)

    def test_primary_set_list_clear(self):
        (tk.CACHE_DIR / "devices.HOSTB.json").write_text(json.dumps(
            {"version": 1, "host": "HOSTB", "sessions": {"s1": 1}}), "utf-8")
        rc, _, _ = self._run(primary="HOSTB")
        self.assertEqual(rc, 0)
        self.assertEqual(tk.load_device_primary(), "HOSTB")
        rc, out, _ = self._run()
        row = next(l for l in out.splitlines() if "HOSTB" in l)
        self.assertTrue(row.rstrip().endswith("primary"), row)
        rc, _, _ = self._run(no_primary=True)
        self.assertIsNone(tk.load_device_primary())

    def _known(self):
        (tk.CACHE_DIR / "devices.HOSTB.json").write_text(json.dumps(
            {"version": 1, "host": "HOSTB", "sessions": {"s1": 1}}), "utf-8")

    def test_alias_rejects_unknown_host(self):
        self._known()
        rc, _, err = self._run(alias="HOSTZ=zed")
        self.assertEqual(rc, 2)
        self.assertIn("HOSTZ", err)
        self.assertEqual(tk.load_device_aliases(), {})

    def test_alias_rejects_reserved_long_and_taken_names(self):
        self._known()
        for bad in ("local", "ALL", "?", "toolongname"):
            rc, _, _ = self._run(alias=f"HOSTB={bad}")
            self.assertEqual(rc, 2, bad)
        self.assertEqual(self._run(alias="HOSTA=mbp")[0], 0)   # this Mac is known
        rc, _, err = self._run(alias="HOSTB=MBP")
        self.assertEqual(rc, 2)
        self.assertIn("HOSTA", err)

    def test_primary_rejects_unknown_host(self):
        self._known()
        rc, _, _ = self._run(primary="HOSTZ")
        self.assertEqual(rc, 2)
        self.assertIsNone(tk.load_device_primary())

    def test_unalias(self):
        tk.save_device_alias("HOSTB", "mbp")
        rc, _, _ = self._run(unalias="HOSTB")
        self.assertEqual(rc, 0)
        self.assertEqual(tk.load_device_aliases(), {})


if __name__ == "__main__":
    unittest.main()
