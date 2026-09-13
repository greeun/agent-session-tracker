"""Rescan progress percentage: the shared percent helper, the on_progress
callback threaded through load_all_sessions / _do_rescan, and the throttled
curses painter that renders it on the TUI footer."""

import curses
import importlib.util
import json
import os
import pty
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def load_tracker():
    spec = importlib.util.spec_from_file_location("tracker_under_test", _REPO / "tracker.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tracker_under_test"] = mod
    spec.loader.exec_module(mod)
    return mod


tk = load_tracker()


def _user_evt(text="hi", **extra):
    e = {"type": "user", "message": {"content": text},
         "timestamp": "2026-05-18T00:00:00Z"}
    e.update(extra)
    return json.dumps(e)


class TestProgressPct(unittest.TestCase):
    def test_basic_ratios(self):
        self.assertEqual(tk.progress_pct(0, 10), 0)
        self.assertEqual(tk.progress_pct(5, 10), 50)
        self.assertEqual(tk.progress_pct(10, 10), 100)

    def test_empty_total_reads_as_finished(self):
        self.assertEqual(tk.progress_pct(0, 0), 100)
        self.assertEqual(tk.progress_pct(0, -3), 100)

    def test_clamped_at_both_ends(self):
        self.assertEqual(tk.progress_pct(11, 10), 100)
        self.assertEqual(tk.progress_pct(-1, 10), 0)

    def test_truncates_rather_than_rounding_up(self):
        # 99/100 must not read as a finished 100%.
        self.assertEqual(tk.progress_pct(99, 100), 99)
        self.assertEqual(tk.progress_pct(1, 3), 33)


class TestRescanProgressText(unittest.TestCase):
    def test_default_label(self):
        self.assertEqual(tk.rescan_progress_text(994, 2370),
                         "Rescanning… 41% (994/2370)")

    def test_custom_label(self):
        self.assertEqual(tk.rescan_progress_text(2, 4, label="Indexing…"),
                         "Indexing… 50% (2/4)")


class _ProjIsolation(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._orig = (tk.PROJECTS_DIR, tk.CODEX_SESSIONS_DIR, tk.CODEX_LOCKS_DIR,
                      tk.CACHE_DIR, tk.CACHE_PATH)
        tk.PROJECTS_DIR = root / "projects"
        tk.CODEX_SESSIONS_DIR = root / "codex_sessions"
        tk.CODEX_LOCKS_DIR = root / "codex_locks"
        tk.PROJECTS_DIR.mkdir(parents=True)
        tk.CACHE_DIR = root / "cache"
        tk.CACHE_PATH = tk.CACHE_DIR / "index.json"

    def tearDown(self):
        (tk.PROJECTS_DIR, tk.CODEX_SESSIONS_DIR, tk.CODEX_LOCKS_DIR,
         tk.CACHE_DIR, tk.CACHE_PATH) = self._orig
        self._tmp.cleanup()

    def _mk(self, name, **extra):
        p = tk.PROJECTS_DIR / "proj" / f"{name}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(_user_evt("hi", **extra) + "\n", encoding="utf-8")
        return p


class TestLoadAllSessionsCallback(_ProjIsolation):
    def _ids(self, n):
        return [f"{i:08d}-0000-0000-0000-000000000000" for i in range(n)]

    def test_reports_zero_first_then_every_file(self):
        for sid in self._ids(3):
            self._mk(sid)
        calls = []
        tk.load_all_sessions(on_progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(calls, [(0, 3), (1, 3), (2, 3), (3, 3)])

    def test_denominator_is_known_even_with_no_sessions(self):
        calls = []
        tk.load_all_sessions(on_progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(calls, [(0, 0)])
        self.assertEqual(tk.progress_pct(*calls[0]), 100)

    def test_counts_every_file_not_just_the_surviving_rows(self):
        # A cwd filter drops one session from the result, but the scan still
        # had to read it — so the percentage must not jump around.
        self._mk("aaaaaaaa-0000-0000-0000-000000000000", cwd="/aaa/x")
        self._mk("bbbbbbbb-1111-1111-1111-111111111111", cwd="/bbb/y")
        calls = []
        out = tk.load_all_sessions(cwd_filter="/aaa",
                                   on_progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(len(out), 1)
        self.assertEqual(calls[-1], (2, 2))

    def test_omitting_the_callback_still_works(self):
        self._mk("cccccccc-0000-0000-0000-000000000000")
        self.assertEqual(len(tk.load_all_sessions()), 1)


class TestDoRescanForwardsProgress(_ProjIsolation):
    def test_callback_reaches_the_loader(self):
        self._mk("dddddddd-0000-0000-0000-000000000000")
        sessions = []
        calls = []
        res = tk._do_rescan(None, None, sessions,
                            on_progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(len(sessions), 1)
        self.assertIsInstance(res, tk.RescanResult)
        self.assertEqual(calls[0], (0, 1))
        self.assertEqual(calls[-1], (1, 1))

    def test_progress_is_optional(self):
        self._mk("eeeeeeee-0000-0000-0000-000000000000")
        sessions = []
        tk._do_rescan(None, None, sessions)
        self.assertEqual(len(sessions), 1)


class _FakeScr:
    """Minimal curses window: records what the painter writes."""

    def __init__(self, h=24, w=80):
        self._h, self._w = h, w
        self.writes = []
        self.refreshes = 0

    def getmaxyx(self):
        return self._h, self._w

    def addnstr(self, y, x, text, n, attr=0):
        self.writes.append((y, x, text[:n], attr))

    def refresh(self):
        self.refreshes += 1


class _FakeClock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now

    def advance(self, s):
        self.now += s


class TestRescanProgressPainter(unittest.TestCase):
    """The painter runs inside a rescan loop that calls it thousands of times,
    so what matters is what it *skips*: paints before the delay, paints inside
    the throttle window, and repeats of a percentage already on screen."""

    def setUp(self):
        self.clock = _FakeClock()

    def _painter(self, scr, delay):
        return tk._rescan_progress_painter(scr, delay=delay, clock=self.clock)

    def test_no_paint_before_the_delay_elapses(self):
        scr = _FakeScr()
        paint = self._painter(scr, 0.35)
        for i in range(101):
            paint(i, 100)
        self.assertEqual(scr.writes, [])

    def test_paints_once_the_delay_elapses(self):
        scr = _FakeScr()
        paint = self._painter(scr, 0.35)
        paint(10, 100)
        self.clock.advance(0.4)
        paint(20, 100)
        self.assertEqual(len(scr.writes), 1)
        self.assertIn("Rescanning… 20% (20/100)", scr.writes[0][2])
        self.assertEqual(scr.refreshes, 1)

    def test_zero_delay_paints_immediately(self):
        scr = _FakeScr()
        paint = self._painter(scr, 0.0)
        paint(5, 100)
        self.assertEqual(len(scr.writes), 1)
        self.assertIn("5%", scr.writes[0][2])

    def test_throttled_between_paints(self):
        scr = _FakeScr()
        paint = self._painter(scr, 0.0)
        paint(1, 100)
        self.clock.advance(0.01)
        paint(2, 100)          # inside the throttle window — skipped
        self.clock.advance(0.2)
        paint(3, 100)
        self.assertEqual(len(scr.writes), 2)
        self.assertIn("3%", scr.writes[1][2])

    def test_unchanged_percentage_is_not_repainted(self):
        scr = _FakeScr()
        paint = self._painter(scr, 0.0)
        paint(1, 1000)         # 0%
        self.clock.advance(1.0)
        paint(2, 1000)         # still 0% — nothing to redraw
        self.assertEqual(len(scr.writes), 1)

    def test_line_is_padded_to_the_window_width(self):
        scr = _FakeScr(h=24, w=40)
        paint = self._painter(scr, 0.0)
        paint(50, 100)
        y, x, text, _attr = scr.writes[0]
        self.assertEqual((y, x), (23, 0))   # bottom line
        self.assertEqual(len(text), 39)     # w - 1, trailing pad included

    def test_survives_a_curses_error(self):
        class _Boom(_FakeScr):
            def addnstr(self, *a, **kw):
                raise curses.error("no room")

        scr = _Boom()
        paint = self._painter(scr, 0.0)
        paint(1, 10)           # must not propagate out of the rescan loop

    def test_degenerate_window_width_is_skipped(self):
        scr = _FakeScr(h=24, w=1)
        paint = self._painter(scr, 0.0)
        paint(1, 10)
        self.assertEqual(scr.writes, [])


_OUT = Path(tempfile.gettempdir()) / "ast_rescan_progress.json"


def _child():
    """Paint two rescan percentages in a real curses screen and read the
    bottom line back out of the window buffer."""
    import curses

    spec = importlib.util.spec_from_file_location("tracker", _REPO / "tracker.py")
    tr = importlib.util.module_from_spec(spec)
    sys.modules["tracker"] = tr
    spec.loader.exec_module(tr)

    rows = []

    def run(stdscr):
        try:
            curses.start_color()
            tr.tui_init_colors("dark", stdscr)
        except Exception:
            pass
        h, _w = stdscr.getmaxyx()
        paint = tr._rescan_progress_painter(stdscr, delay=0.0)
        paint(37, 100)
        rows.append(stdscr.instr(h - 1, 0).decode("utf-8", "replace"))
        # Far enough apart in both time and percentage to clear the throttle.
        import time as _t
        _t.sleep(0.12)
        paint(100, 100)
        rows.append(stdscr.instr(h - 1, 0).decode("utf-8", "replace"))

    curses.wrapper(run)
    _OUT.write_text(json.dumps({"rows": rows}))


def _run_headless():
    if _OUT.exists():
        _OUT.unlink()
    pid, fd = pty.fork()
    if pid == 0:
        try:
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


class TestRescanProgressOnRealCurses(unittest.TestCase):
    """The footer text has to survive a real curses screen, so it is painted
    headlessly through pty.fork and read back from the window buffer."""

    def test_percentage_reaches_the_bottom_line(self):
        res = _run_headless()
        self.assertNotIn("error", res, msg=res.get("error"))
        rows = res["rows"]
        self.assertEqual(len(rows), 2)
        self.assertIn("Rescanning… 37% (37/100)", rows[0])
        self.assertIn("Rescanning… 100% (100/100)", rows[1])
        # The line is padded, so the earlier, shorter text leaves no tail.
        self.assertNotIn("37%", rows[1])




_E2E_OUT = Path(tempfile.gettempdir()) / "ast_rescan_progress_e2e.json"


def _e2e_child():
    """Drive `_pick_ui` with the R key and record what reaches the painter."""
    import curses
    from datetime import datetime, timezone

    tmp = tempfile.mkdtemp()
    os.environ["AST_HOME"] = tmp
    spec = importlib.util.spec_from_file_location("tracker_rescan_e2e", _REPO / "tracker.py")
    tr = importlib.util.module_from_spec(spec)
    sys.modules["tracker_rescan_e2e"] = tr
    spec.loader.exec_module(tr)
    tr.CACHE_DIR = Path(tmp)
    tr.STATE_PATH = tr.CACHE_DIR / "state.json"

    sessions = [tr.SessionMeta(
        session_id="aaaaaaaa", path=Path("/x/aaaaaaaa.jsonl"), cwd="/w/a",
        last_ts=datetime(2026, 6, 3, 12, 0, tzinfo=timezone.utc),
        msg_count=3, first_user_msg="ROWONE", entrypoint="cli")]

    empty_ctx = tr.StatusContext(live=set(), done=set(), registry={},
                                 overlay={}, jobs={}, pins=set())
    tr.StatusContext.capture = classmethod(lambda cls: empty_ctx)

    # Stand in for the transcript scan: report a handful of steps so the
    # painter the TUI installed is exercised the way a real rescan does.
    def fake_load(cwd_filter=None, days=None, fast=True, progress=False,
                  on_progress=None):
        if on_progress:
            for done in (0, 5, 10):
                on_progress(done, 10)
        return list(sessions)

    tr.load_all_sessions = fake_load

    delays = []
    progress_calls = []
    real_painter = tr._rescan_progress_painter

    def spy_painter(stdscr, label="Rescanning…", delay=tr._RESCAN_PAINT_DELAY_S,
                    clock=None):
        delays.append(delay)
        inner = real_painter(stdscr, label=label, delay=delay, clock=clock)

        def _paint(done, total):
            progress_calls.append([done, total])
            return inner(done, total)

        return _paint

    tr._rescan_progress_painter = spy_painter

    keyseq = [ord("R"), 27]
    idx = [0]

    class Proxy:
        def __init__(self, w):
            self._w = w

        def getch(self):
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
    _E2E_OUT.write_text(json.dumps({"delays": delays, "calls": progress_calls}))


def _run_e2e_headless():
    if _E2E_OUT.exists():
        _E2E_OUT.unlink()
    pid, fd = pty.fork()
    if pid == 0:
        try:
            _e2e_child()
        except BaseException:
            try:
                import traceback
                _E2E_OUT.write_text(json.dumps({"error": traceback.format_exc()}))
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
    return json.loads(_E2E_OUT.read_text())


class TestPickUiRescanKeyReportsProgress(unittest.TestCase):
    """End-to-end: the R key's rescan must hand its progress to the painter,
    and a rescan the user asked for must not sit behind the paint delay."""

    def test_r_key_feeds_the_painter(self):
        res = _run_e2e_headless()
        self.assertNotIn("error", res, msg=res.get("error"))
        self.assertEqual([tuple(c) for c in res["calls"]],
                         [(0, 10), (5, 10), (10, 10)])
        self.assertEqual(res["delays"], [0.0])


if __name__ == "__main__":
    unittest.main()
