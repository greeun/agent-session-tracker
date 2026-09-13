"""인자 없이 실행한 `ast`가 무엇을 하는가.

터미널에서는 TUI(`pick`)로 진입하고, tty가 없는 호출(파이프·리다이렉트·에이전트
도구 호출·GUI 호출자)에서는 목록(`list`)으로 물러난다. 후자가 깨지면 `ast`가
curses 초기화에서 죽거나 화면 제어 문자를 쏟아 내므로, 두 경로를 모두 고정해
둔다. 서브커맨드를 명시한 호출은 이 분기에 들어오지 않아야 한다."""
import importlib.util
import pathlib
import sys
import unittest

_REPO = pathlib.Path(__file__).resolve().parents[1]


def load_tracker():
    spec = importlib.util.spec_from_file_location("tracker_default_cmd",
                                                  _REPO / "tracker.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tracker_default_cmd"] = mod
    spec.loader.exec_module(mod)
    return mod


tk = load_tracker()


class _MainHarness(unittest.TestCase):
    """`main()`을 실제로 돌리되, 실행되는 커맨드는 스텁으로 가로챈다.

    `_build_parser()`가 호출될 때 모듈 전역에서 `func`를 읽으므로, 전역을
    갈아 끼우면 파서가 스텁을 바인딩한다."""

    def setUp(self):
        self.calls = []
        self._orig = {name: getattr(tk, name)
                      for name in ("cmd_pick", "cmd_list", "cmd_stats",
                                   "seed_from_cst_home", "_stdio_is_interactive")}
        for name in ("cmd_pick", "cmd_list", "cmd_stats"):
            self._stub(name)
        tk.seed_from_cst_home = lambda: False
        self._orig_argv = sys.argv[:]

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(tk, name, fn)
        sys.argv = self._orig_argv

    def _stub(self, name):
        def fn(args, _n=name):
            self.calls.append((_n, args))
            return 0
        setattr(tk, name, fn)

    def run_main(self, argv, interactive):
        tk._stdio_is_interactive = lambda: interactive
        sys.argv = ["ast", *argv]
        rc = tk.main()
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.calls), 1, self.calls)
        return self.calls[0]


class TestBareInvocation(_MainHarness):
    def test_terminal_opens_the_picker(self):
        name, _ = self.run_main([], interactive=True)
        self.assertEqual(name, "cmd_pick")

    def test_without_a_tty_it_falls_back_to_the_list(self):
        name, _ = self.run_main([], interactive=False)
        self.assertEqual(name, "cmd_list")

    def test_tui_flag_forces_the_picker_without_a_tty(self):
        name, _ = self.run_main(["--tui"], interactive=False)
        self.assertEqual(name, "cmd_pick")

    def test_explicit_list_wins_at_a_terminal(self):
        name, _ = self.run_main(["list"], interactive=True)
        self.assertEqual(name, "cmd_list")

    def test_other_subcommands_are_untouched(self):
        name, _ = self.run_main(["stats"], interactive=True)
        self.assertEqual(name, "cmd_stats")


class TestTopLevelFlagsSurvive(_MainHarness):
    """기본 커맨드는 파서에서 다시 만들어지므로, 최상위 플래그를 옮겨 싣지
    않으면 조용히 사라진다."""

    def test_skip_perm_and_hide_done_reach_the_picker(self):
        _, args = self.run_main(["--skip-perm", "--hide-done"], interactive=True)
        self.assertTrue(args.skip_perm)
        self.assertTrue(args.hide_done)

    def test_theme_reaches_the_picker(self):
        _, args = self.run_main(["--theme", "light"], interactive=True)
        self.assertEqual(args.theme, "light")

    def test_flags_also_reach_the_list_fallback(self):
        _, args = self.run_main(["--hide-done"], interactive=False)
        self.assertTrue(args.hide_done)


class TestInteractiveProbe(unittest.TestCase):
    def test_both_streams_must_be_a_tty(self):
        class Fake:
            def __init__(self, tty):
                self._tty = tty

            def isatty(self):
                return self._tty

        orig = (sys.stdin, sys.stdout)
        try:
            for stdin_tty, stdout_tty, expected in (
                    (True, True, True), (True, False, False),
                    (False, True, False), (False, False, False)):
                sys.stdin, sys.stdout = Fake(stdin_tty), Fake(stdout_tty)
                self.assertEqual(tk._stdio_is_interactive(), expected,
                                 (stdin_tty, stdout_tty))
        finally:
            sys.stdin, sys.stdout = orig

    def test_detached_stream_is_not_interactive(self):
        class Closed:
            def isatty(self):
                raise ValueError("I/O operation on closed file")

        orig = sys.stdin
        try:
            sys.stdin = Closed()
            self.assertFalse(tk._stdio_is_interactive())
        finally:
            sys.stdin = orig


if __name__ == "__main__":
    unittest.main()
