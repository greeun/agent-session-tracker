"""`/` search inside the help modal (`?`).

The key handling is the pure `_help_key(state, key, ch_str, lines, view_h,
keys, backspace)` so most of it is tested without curses; one pty-driven test
runs the real `_show_help_modal` to check the highlight and the footer prompt.
"""
import importlib.util
import json
import os
import pathlib
import pty
import sys
import tempfile
import unittest

_TP = pathlib.Path(__file__).resolve().parent.parent / "tracker.py"
_spec = importlib.util.spec_from_file_location("tracker", _TP)
tracker = importlib.util.module_from_spec(_spec)
sys.modules["tracker"] = tracker
_spec.loader.exec_module(tracker)

# Fake curses codes: (UP, DOWN, PPAGE, NPAGE, HOME, END) + KEY_BACKSPACE.
KEYS = (259, 258, 339, 338, 262, 360)
BS = 263
ESC, ENTER = 27, 10

LINES = [f"line {i}" for i in range(30)]
LINES[3] = "alpha Beta"
LINES[20] = "beta gamma"
LINES[25] = "한글 도움말 beta"


def press(st, key, ch_str=None, lines=LINES, view_h=10):
    return tracker._help_key(st, key, ch_str, lines, view_h, KEYS, BS)


def type_text(st, text, **kw):
    for ch in text:
        press(st, ord(ch), ch, **kw)


class TestHelpKeySearch(unittest.TestCase):
    def test_slash_opens_prompt_without_closing(self):
        st = tracker.HelpSearch()
        self.assertFalse(press(st, ord('/'), '/'))
        self.assertTrue(st.searching)

    def test_typing_is_incremental_and_case_insensitive(self):
        st = tracker.HelpSearch()
        press(st, ord('/'), '/')
        type_text(st, "BETA")
        self.assertEqual(st.query, "BETA")
        self.assertEqual([m[0] for m in st.matches], [3, 20, 25])
        self.assertEqual(st.cur, 0)

    def test_close_keys_are_typed_while_prompt_is_open(self):
        # q and ? close the modal normally; inside the prompt they are text.
        st = tracker.HelpSearch()
        press(st, ord('/'), '/')
        self.assertFalse(press(st, ord('q'), 'q'))
        self.assertFalse(press(st, ord('?'), '?'))
        self.assertEqual(st.query, "q?")
        self.assertTrue(st.searching)

    def test_korean_query(self):
        st = tracker.HelpSearch()
        press(st, ord('/'), '/')
        type_text(st, "도움말")
        self.assertEqual(st.matches, [(25, 3, 6)])

    def test_first_match_is_scrolled_into_view(self):
        st = tracker.HelpSearch()
        press(st, ord('/'), '/')
        type_text(st, "gamma")
        self.assertEqual(st.matches, [(20, 5, 10)])
        # line 20 must sit inside [offset, offset + view_h)
        self.assertLessEqual(st.offset, 20)
        self.assertGreater(st.offset + 10, 20)

    def test_match_search_starts_at_current_offset(self):
        st = tracker.HelpSearch(offset=15)
        press(st, ord('/'), '/')
        type_text(st, "beta")
        self.assertEqual(st.cur, 1)            # line 20, not line 3 above the view

    def test_enter_keeps_highlights(self):
        st = tracker.HelpSearch()
        press(st, ord('/'), '/')
        type_text(st, "beta")
        self.assertFalse(press(st, ENTER))
        self.assertFalse(st.searching)
        self.assertEqual(st.query, "beta")
        self.assertEqual(len(st.matches), 3)

    def test_esc_in_prompt_drops_the_search(self):
        st = tracker.HelpSearch()
        press(st, ord('/'), '/')
        type_text(st, "beta")
        self.assertFalse(press(st, ESC))
        self.assertEqual((st.searching, st.query, st.matches, st.cur),
                         (False, "", [], -1))

    def test_backspace_and_ctrl_u(self):
        st = tracker.HelpSearch()
        press(st, ord('/'), '/')
        type_text(st, "gammax")
        self.assertEqual(st.matches, [])
        self.assertEqual(st.cur, -1)
        press(st, BS)
        self.assertEqual(st.query, "gamma")
        self.assertEqual(len(st.matches), 1)
        press(st, 127)
        self.assertEqual(st.query, "gamm")
        press(st, 21)                          # Ctrl-U
        self.assertEqual((st.query, st.matches), ("", []))

    def test_char_sharing_a_special_key_code_is_typed(self):
        # _read_key returns (263, 'ć') for U+0107, the same code as
        # KEY_BACKSPACE; a printable char must never be read as an edit key.
        st = tracker.HelpSearch()
        press(st, ord('/'), '/')
        type_text(st, "ab")
        press(st, BS, "ć")
        self.assertEqual(st.query, "abć")

    def test_n_and_shift_n_walk_matches_cyclically(self):
        st = tracker.HelpSearch()
        press(st, ord('/'), '/')
        type_text(st, "beta")
        press(st, ENTER)
        press(st, ord('n'), 'n')
        self.assertEqual(st.cur, 1)
        self.assertLessEqual(st.offset, 20)
        self.assertGreater(st.offset + 10, 20)
        press(st, ord('n'), 'n')
        press(st, ord('n'), 'n')
        self.assertEqual(st.cur, 0)            # wrapped
        self.assertEqual(st.offset, 3)         # scrolled back up to line 3
        press(st, ord('N'), 'N')
        self.assertEqual(st.cur, 2)

    def test_n_without_matches_is_a_noop(self):
        st = tracker.HelpSearch(offset=4)
        self.assertFalse(press(st, ord('n'), 'n'))
        self.assertEqual((st.offset, st.cur), (4, -1))

    def test_slash_reopens_prompt_keeping_query(self):
        st = tracker.HelpSearch()
        press(st, ord('/'), '/')
        type_text(st, "beta")
        press(st, ENTER)
        press(st, ord('/'), '/')
        self.assertTrue(st.searching)
        self.assertEqual(st.query, "beta")

    def test_esc_clears_active_search_before_closing(self):
        st = tracker.HelpSearch()
        press(st, ord('/'), '/')
        type_text(st, "beta")
        press(st, ENTER)
        self.assertFalse(press(st, ESC))       # first Esc: clear
        self.assertEqual((st.query, st.matches, st.cur), ("", [], -1))
        self.assertTrue(press(st, ESC))        # second Esc: close

    def test_scroll_and_close_keys_still_work(self):
        st = tracker.HelpSearch()
        self.assertFalse(press(st, 258))       # DOWN
        self.assertEqual(st.offset, 1)
        self.assertFalse(press(st, ord('G'), 'G'))
        self.assertEqual(st.offset, 20)        # 30 lines - view 10
        for close in (ord('q'), ord('Q'), ENTER, 13, ord('?'), ESC):
            self.assertTrue(press(tracker.HelpSearch(), close), close)


class TestHelpFooter(unittest.TestCase):
    def test_idle_footer_advertises_search(self):
        self.assertIn("/ search", tracker._help_footer(tracker.HelpSearch()))

    def test_prompt_footer(self):
        st = tracker.HelpSearch(query="beta", searching=True,
                                matches=[(3, 6, 10), (20, 0, 4)], cur=0)
        text = tracker._help_footer(st)
        self.assertIn("/beta▏", text)
        self.assertIn("[1/2]", text)
        self.assertIn("Esc cancel", text)

    def test_committed_footer(self):
        st = tracker.HelpSearch(query="beta", matches=[(3, 6, 10)], cur=0)
        text = tracker._help_footer(st)
        self.assertIn("/beta ", text)
        self.assertIn("[1/1]", text)
        self.assertIn("n/N", text)

    def test_no_match_counts_zero(self):
        st = tracker.HelpSearch(query="zzz", searching=True)
        self.assertIn("[0/0]", tracker._help_footer(st))


class TestHelpLinesDocumentSearch(unittest.TestCase):
    def test_help_mentions_its_own_search(self):
        joined = "\n".join(tracker.HELP_LINES)
        self.assertIn("/ search", joined)
        self.assertIn("n/N", joined)


# ── headless render check ───────────────────────────────────────────────────

_OUT = pathlib.Path(tempfile.gettempdir()) / "ast_help_search.json"


def _child():
    import curses
    import fcntl
    import struct
    import termios

    fcntl.ioctl(0, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 100, 0, 0))
    spec = importlib.util.spec_from_file_location("tracker", _TP)
    tr = importlib.util.module_from_spec(spec)
    sys.modules["tracker"] = tr
    spec.loader.exec_module(tr)

    frames = []
    keyseq = [(ord('/'), '/')] + [(ord(c), c) for c in "cmux"] + [(10, None)]
    idx = [0]

    def fake_read_key(win):
        # Start inside the left border so the box's line-drawing glyph never
        # shifts the column arithmetic below.
        maxy, maxx = win.getmaxyx()
        rows, reverse = [], []
        for y in range(maxy):
            rows.append(win.instr(y, 2).decode("utf-8", "replace"))
            reverse.append("".join(
                "R" if win.inch(y, x) & curses.A_REVERSE else "."
                for x in range(2, maxx)))
        frames.append({"rows": rows, "reverse": reverse})
        k = keyseq[idx[0]] if idx[0] < len(keyseq) else (ord('q'), 'q')
        idx[0] += 1
        return k

    tr._read_key = fake_read_key

    def run(stdscr):
        try:
            curses.start_color()
            tr.tui_init_colors("dark")
        except Exception:
            pass
        tr._show_help_modal(stdscr)

    curses.wrapper(run)
    _OUT.write_text(json.dumps({"frames": frames}))


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


class TestHelpSearchRender(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = _run_headless()

    def test_no_error(self):
        self.assertNotIn("error", self.res, msg=self.res.get("error"))

    def test_footer_shows_prompt_then_committed_query(self):
        frames = self.res["frames"]
        # frame 0: idle, frame 5: "/cmux" typed, frame 6: after Enter
        self.assertIn("/ search", "\n".join(frames[0]["rows"]))
        self.assertIn("/cmux▏", "\n".join(frames[5]["rows"]))
        self.assertIn("n/N", "\n".join(frames[6]["rows"]))

    def test_match_is_highlighted(self):
        frame = self.res["frames"][6]
        hits = 0
        for text, rev in zip(frame["rows"], frame["reverse"]):
            col = text.find("cmux")
            if col < 0 or "/cmux" in text:     # skip the footer prompt itself
                continue
            # instr returns one cell per column for this ASCII-only prefix
            if text[:col].isascii():
                self.assertEqual(rev[col:col + 4], "RRRR", msg=text)
                hits += 1
        self.assertGreater(hits, 0)


if __name__ == "__main__":
    unittest.main()
