"""TUI `/` → Tab escalates to full-text search and shows every transcript hit.

Regression: after Tab the typed query stayed in the metadata filter
(id + cwd + first user msg), so the full-text hits were intersected with
metadata matches and a session that matched only in its transcript body
never appeared.

Driven headlessly via pty.fork like test_agent_tui. `_tui_run_search` is
stubbed so the test needs no transcript files on disk.
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
_OUT = pathlib.Path(tempfile.gettempdir()) / "ast_tui_fulltext_tab_result.json"


def _load():
    spec = importlib.util.spec_from_file_location("tracker_fulltext_tab", _TP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tracker_fulltext_tab"] = mod
    spec.loader.exec_module(mod)
    return mod


def _child():
    import curses

    tmp = tempfile.mkdtemp()
    os.environ["AST_HOME"] = tmp
    tr = _load()
    tr.CACHE_DIR = pathlib.Path(tmp)
    tr.STATE_PATH = tr.CACHE_DIR / "state.json"

    def _sm(sid, msg):
        return tr.SessionMeta(
            session_id=sid, path=pathlib.Path(f"/x/{sid}.jsonl"), cwd="/w",
            last_ts=datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc),
            msg_count=3, first_user_msg=msg, agent="claude")

    sessions = [_sm("aaaaaaaa", "HEADONE keyword in first msg"),
                _sm("bbbbbbbb", "BODYONE unrelated first msg"),
                _sm("cccccccc", "MISSONE unrelated first msg")]

    empty_ctx = tr.StatusContext(live=set(), done=set(), registry={},
                                 overlay={}, jobs={}, pins=set())
    tr.StatusContext.capture = classmethod(lambda cls: empty_ctx)
    # Both aaaaaaaa (first msg) and bbbbbbbb (transcript body) contain it.
    tr._tui_run_search = lambda stdscr, sess, q: {
        "aaaaaaaa": "keyword in first msg",
        "bbbbbbbb": "...the keyword appears deep in the transcript...",
    }

    captures = []
    keyseq = [ord("/")] + [ord(c) for c in "keyword"] + [9, 27, 27, 27]
    idx = [0]

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
    _OUT.write_text(json.dumps({"captures": captures}))


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


class TestTuiFulltextTab(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = _run_headless()

    def frames(self):
        self.assertNotIn("error", self.res, msg=self.res.get("error"))
        return self.res["captures"]

    def test_metadata_filter_before_tab_shows_only_first_msg_match(self):
        before_tab = self.frames()[1 + len("keyword")]
        self.assertIn("HEADONE", before_tab)
        self.assertNotIn("BODYONE", before_tab)

    def test_tab_shows_transcript_only_hit(self):
        # Full-text rows show the matched snippet in MESSAGE, so check ids.
        after_tab = self.frames()[2 + len("keyword")]
        self.assertIn("aaaaaaaa", after_tab)
        self.assertIn("bbbbbbbb", after_tab)
        self.assertNotIn("cccccccc", after_tab)
        self.assertNotIn("filter='keyword'", after_tab)


if __name__ == "__main__":
    unittest.main()
