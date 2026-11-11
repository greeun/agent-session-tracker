"""DEVICE 열과 --device 필터 — ast list / search / --json / resume.

s1 은 다른 맥(HOSTB, 별칭 mbp)의 기기 기록에 있고 s2 는 어느 기록에도 없다(?).
"""
import argparse
import importlib.util
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("tracker_device_cli", _REPO / "tracker.py")
tk = importlib.util.module_from_spec(_spec)
sys.modules["tracker_device_cli"] = tk
_spec.loader.exec_module(tk)

S1 = "11111111-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
S2 = "22222222-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
_KEYS = ("PROJECTS_DIR", "CODEX_SESSIONS_DIR", "CODEX_LOCKS_DIR", "CACHE_DIR",
         "CACHE_PATH", "STATE_PATH", "JOBS_DIR", "DAEMON_DIR",
         "SESSIONS_REGISTRY_DIR", "CLAUDE_HISTORY_PATH", "_host_id")


def NS(**kw):
    base = dict(cwd=None, days=None, status=None, limit=30, json=False,
                sort=None, origin=None, agent=None, device=None)
    base.update(kw)
    return argparse.Namespace(**base)


def _run(fn, ns):
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        rc = fn(ns)
    return rc, out.getvalue(), err.getvalue()


class TestDeviceCli(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self._orig = {k: getattr(tk, k) for k in _KEYS}
        self.addCleanup(lambda: [setattr(tk, k, v) for k, v in self._orig.items()])
        tk.PROJECTS_DIR = root / "projects"
        tk.CODEX_SESSIONS_DIR = root / "codex_sessions"
        tk.CODEX_LOCKS_DIR = root / "codex_locks"
        tk.CACHE_DIR = root / "cache"
        tk.CACHE_DIR.mkdir()
        tk.CACHE_PATH = tk.CACHE_DIR / "index.json"
        tk.STATE_PATH = tk.CACHE_DIR / "state.json"
        tk.JOBS_DIR = root / "jobs"
        tk.DAEMON_DIR = root / "daemon"
        tk.SESSIONS_REGISTRY_DIR = root / "sessions"
        tk.CLAUDE_HISTORY_PATH = root / "history.jsonl"
        tk._host_id = lambda: "HOSTA"
        for sid, ts in ((S1, "2026-11-10T10:00:00Z"), (S2, "2026-11-10T11:00:00Z")):
            self._write(sid, ts)
        (tk.CACHE_DIR / "devices.HOSTB.json").write_text(json.dumps(
            {"version": 1, "host": "HOSTB", "sessions": {S1: 5}}), "utf-8")
        tk.save_device_alias("HOSTB", "mbp")

    def _write(self, sid, ts):
        cwd = "/tmp/proj"
        d = tk.PROJECTS_DIR / tk.encode_cwd(cwd)
        d.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps({"type": t, "timestamp": ts, "cwd": cwd, "sessionId": sid,
                             "message": {"content": "hello device " + t}})
                 for t in ("user", "assistant")]
        (d / f"{sid}.jsonl").write_text("\n".join(lines) + "\n", "utf-8")

    def _row(self, out, sid):
        return next(l for l in out.splitlines() if sid[:8] in l)

    def test_list_has_device_column(self):
        rc, out, _ = _run(tk.cmd_list, NS())
        self.assertEqual(rc, 0)
        header = next(l for l in out.splitlines() if "AGENT" in l)
        self.assertRegex(header, r"AGENT\s+DEVICE\s+LAST ACTIVITY")
        self.assertRegex(self._row(out, S1), r"claude\s+mbp\s")
        self.assertRegex(self._row(out, S2), r"claude\s+\?\s")

    def test_list_device_filter_note(self):
        rc, out, _ = _run(tk.cmd_list, NS(device="mbp"))
        self.assertEqual(rc, 0)
        self.assertIn(S1[:8], out)
        self.assertNotIn(S2[:8], out)
        self.assertTrue(out.rstrip().endswith("  [device:mbp, ?:1 hidden]"), out)

    def test_unknown_device_rc2(self):
        rc, _, err = _run(tk.cmd_list, NS(device="nope"))
        self.assertEqual(rc, 2)
        self.assertIn("nope", err)

    def test_saved_device_view_applies(self):
        tk.save_device_view("HOSTB")
        rc, out, _ = _run(tk.cmd_list, NS())
        self.assertIn(S1[:8], out)
        self.assertNotIn(S2[:8], out)

    def test_search_device(self):
        parse = tk._build_parser().parse_args
        rc, out, _ = _run(tk.cmd_search, parse(["search", "hello device"]))
        self.assertEqual(rc, 0)
        self.assertRegex(self._row(out, S1), r"claude\s+mbp\s")
        rc, out, _ = _run(tk.cmd_search, parse(["search", "hello device", "--device", "mbp"]))
        self.assertNotIn(S2[:8], out)
        self.assertIn("[device:mbp, ?:1 hidden]", out)

    def test_json_device_fields(self):
        rc, out, _ = _run(tk.cmd_list, NS(json=True))
        data = json.loads(out)
        rows = data["sessions"] if isinstance(data, dict) else data
        by = {r["sessionId"] if "sessionId" in r else r["session_id"]: r for r in rows}
        self.assertEqual(by[S1]["device"], "HOSTB")
        self.assertEqual(by[S1]["device_label"], "mbp")
        self.assertIsNone(by[S2]["device"])
        self.assertEqual(by[S2]["device_label"], "?")

    def test_resume_warns_other_device(self):
        ns = argparse.Namespace(session_id=S1[:8], print_only=True, spawn=False,
                                skip_perm=False)
        rc, _, err = _run(tk.cmd_resume, ns)
        self.assertEqual(rc, 0)
        self.assertIn("was last worked on mbp", err)
        ns.session_id = S2[:8]
        rc, _, err = _run(tk.cmd_resume, ns)
        self.assertNotIn("last worked on", err)


if __name__ == "__main__":
    unittest.main()
