"""TUI 기기 표시: DEVICE 열, `m`/`M` 필터 순환, 다른 맥 세션 재개 확인.

pty 안에서 _pick_ui 를 키 시퀀스로 구동한다(test_pick_ui_keys.py 와 같은 방식).
s1 은 다른 맥(HOSTB, 별칭 mbp), s2 는 기기 미상(?)이다.
"""
import importlib.util
import json
import os
import pathlib
import pty
import sys
import tempfile
import unittest
from datetime import datetime, timezone

_TP = pathlib.Path(__file__).resolve().parent.parent / "tracker.py"
_OUT = pathlib.Path(tempfile.gettempdir()) / "ast_device_tui_result.json"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _TP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


tk = _load("tracker_device_tui")


def _child():
    import curses

    tmp = tempfile.mkdtemp()
    os.environ["AST_HOME"] = tmp
    tr = _load("tracker_device_tui_child")
    tr.CACHE_DIR = pathlib.Path(tmp)
    tr.STATE_PATH = tr.CACHE_DIR / "state.json"
    tr._host_id = lambda: "HOSTA"

    def _sm(sid, msg, day):
        return tr.SessionMeta(
            session_id=sid, path=pathlib.Path(f"/x/{sid}.jsonl"),
            cwd=f"/nonexistent-ast-test/{sid[:4]}",
            last_ts=datetime(2026, 6, day, 12, 0, tzinfo=timezone.utc),
            msg_count=2, first_user_msg=msg, entrypoint="cli")

    sessions = [_sm("11111111", "ROWONE", 3), _sm("22222222", "ROWTWO", 1)]
    ctx = tr.StatusContext(live=set(), done=set(), registry={}, overlay={},
                           jobs={}, pins=set(), devices={"11111111": "HOSTB"},
                           aliases={"HOSTB": "mbp"})
    tr.StatusContext.capture = classmethod(lambda cls: ctx)
    tr.get_live_session_info = lambda sid: None
    tr.job_short_for = lambda sid: None

    calls = []
    tr._confirm_other_device_modal = (
        lambda scr, target, label: calls.append(["device", target.session_id, label]) or False)
    tr._orphan_relocate_flow = (
        lambda scr, target: calls.append(["orphan", target.session_id]) or ("cancel", None))

    # frame0: start(all)  m→local  M→all  Enter on row1(s1)  ↓  Enter on row2(s2)
    # m→local  m→HOSTB  Esc
    keyseq = [ord("m"), ord("M"), 10, curses.KEY_DOWN, 10, ord("m"), ord("m"), 27]
    idx = [0]
    captures, views = [], []

    class Proxy:
        def __init__(self, w):
            self._w = w

        def getch(self):
            maxy, _ = self._w.getmaxyx()
            snap = []
            for y in range(maxy):
                try:
                    snap.append(self._w.instr(y, 0).decode("utf-8", "replace"))
                except Exception:
                    snap.append("")
            captures.append("\n".join(snap))
            views.append(tr.load_device_view())
            k = keyseq[idx[0]] if idx[0] < len(keyseq) else 27
            idx[0] += 1
            return k

        def __getattr__(self, name):
            return getattr(self._w, name)

    def run(stdscr):
        try:
            curses.start_color()
        except Exception:
            pass
        tr._pick_ui(Proxy(stdscr), sessions, None, None)

    curses.wrapper(run)
    _OUT.write_text(json.dumps({"captures": captures, "views": views, "calls": calls}))


def _run_headless():
    if _OUT.exists():
        _OUT.unlink()
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.environ["COLUMNS"], os.environ["LINES"] = "140", "30"
            _child()
        except BaseException:
            try:
                import traceback
                _OUT.write_text(json.dumps({"error": traceback.format_exc()}))
            except Exception:
                pass
        os._exit(0)
    while True:
        try:
            if not os.read(fd, 4096):
                break
        except OSError:
            break
    os.waitpid(pid, 0)
    return json.loads(_OUT.read_text())


class TestPure(unittest.TestCase):
    def test_columns_nine_tuple(self):
        cols = tk._tui_columns(10, 10, 120)
        self.assertEqual(len(cols), 9)
        self.assertEqual(cols[3], tk.DEVICE_WIDTH)

    def test_yes_no_ignores_resize(self):
        import curses

        class Scr:
            def __init__(self, keys):
                self.keys = list(keys)

            def getch(self):
                return self.keys.pop(0)

        self.assertTrue(tk._read_yes_no(Scr([curses.KEY_RESIZE, ord("y")])))
        self.assertFalse(tk._read_yes_no(Scr([curses.KEY_RESIZE, -1, ord("n")])))
        self.assertFalse(tk._read_yes_no(Scr([27])))

    def test_header_hint(self):
        self.assertEqual(tk._device_hint("all", {}, 5), "")
        self.assertEqual(tk._device_hint("HOSTB", {"HOSTB": "mbp"}, 0), "  ⌂mbp")
        self.assertEqual(tk._device_hint("HOSTB", {"HOSTB": "mbp"}, 2), "  ⌂mbp ?2")
        self.assertEqual(tk._device_hint("local", {}, 0), "  ⌂local")


class TestDeviceTui(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = _run_headless()

    def setUp(self):
        self.assertNotIn("error", self.res, msg=self.res.get("error"))

    def _rows(self, i):
        return self.res["captures"][i].splitlines()

    def test_device_column_and_cells(self):
        lines = self._rows(0)
        self.assertRegex(lines[2], r"AGENT\s+DEVICE\s+LAST ACTIVITY")
        row1 = next(l for l in lines if "ROWONE" in l)
        row2 = next(l for l in lines if "ROWTWO" in l)
        self.assertRegex(row1, r"claude\s+mbp\s")
        self.assertRegex(row2, r"claude\s+\?\s")
        # header and row cells start in the same column (rows are ASCII here)
        self.assertEqual(lines[2].index("DEVICE"), row1.index("mbp"))
        self.assertEqual(lines[2].index("LAST ACTIVITY"), row1.index("2026-"))

    def test_m_cycles_and_saves(self):
        views = self.res["views"]
        self.assertEqual(views[0], "all")
        self.assertEqual(views[1], "local")
        self.assertEqual(views[2], "all")
        self.assertEqual(views[7], "HOSTB")

    def test_local_view_hides_unknown_and_says_so(self):
        lines = self._rows(1)              # after m → local: no row is HOSTA
        self.assertIn("⌂local ?1", lines[0])
        self.assertFalse(any("ROWTWO" in l for l in lines))

    def test_host_view_shows_only_that_host(self):
        lines = self._rows(7)              # local → HOSTB
        self.assertIn("⌂mbp ?1", lines[0])
        self.assertTrue(any("ROWONE" in l for l in lines))
        self.assertFalse(any("ROWTWO" in l for l in lines))

    def test_enter_on_other_device_asks_first(self):
        calls = self.res["calls"]
        self.assertEqual(calls[0], ["device", "11111111", "mbp"])
        # declined → never reached the resume flow for s1
        self.assertNotIn(["orphan", "11111111"], calls)

    def test_enter_on_unknown_device_skips_the_question(self):
        calls = self.res["calls"]
        self.assertIn(["orphan", "22222222"], calls)
        self.assertNotIn(["device", "22222222", "?"], calls)


if __name__ == "__main__":
    unittest.main()
