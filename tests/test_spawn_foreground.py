import os
import subprocess
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import tracker


def _done(stdout="", returncode=0):
    return subprocess.CompletedProcess([], returncode, stdout=stdout, stderr="")


class _Proc:
    """Stand-in for the spawned terminal; `poll` reports it still running."""
    pid = 4242

    def __init__(self, exited=False):
        self._exited = exited

    def poll(self):
        return 0 if self._exited else None


class BuildRaiseScriptTests(unittest.TestCase):
    def test_targets_the_pid_and_raises_only_with_a_window(self):
        script = tracker._build_raise_spawned_script(4242)
        target = "(first process whose unix id is 4242)"
        self.assertIn(f"count of windows of {target}", script)
        self.assertIn(f'perform action "AXRaise" of window 1 of {target}', script)
        self.assertIn(f"set frontmost of {target} to true", script)
        self.assertIn("FOCUSED", script)
        self.assertIn("PENDING", script)

    def test_never_stores_the_process_in_a_variable(self):
        # A stored reference resolves by name, which with several wezterm-gui
        # processes lands on the first one instead of the spawned pid.
        script = tracker._build_raise_spawned_script(4242)
        self.assertNotIn("set p to", script)
        self.assertNotIn("set matches to", script)


class RaiseSpawnedWindowTests(unittest.TestCase):
    """A new `wezterm start` is its own wezterm-gui process, so the window has
    to be raised by pid; `tell application "WezTerm"` cannot reach it."""

    def setUp(self):
        patcher = mock.patch("time.sleep")
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_polls_until_the_window_exists(self):
        results = [_done("PENDING\n"), _done("PENDING\n"), _done("FOCUSED\n")]
        with mock.patch("subprocess.run", side_effect=results) as run:
            self.assertTrue(tracker._raise_spawned_window(_Proc()))
        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args[0][0][0], "osascript")

    def test_stops_when_the_process_exited(self):
        # Exit without a window = the CLI handed off to another GUI instance.
        with mock.patch("subprocess.run") as run:
            self.assertFalse(tracker._raise_spawned_window(_Proc(exited=True)))
        run.assert_not_called()

    def test_stops_on_a_script_error(self):
        # Accessibility denied fails every attempt; don't stall the TUI on it.
        with mock.patch("subprocess.run", return_value=_done(returncode=1)) as run:
            self.assertFalse(tracker._raise_spawned_window(_Proc()))
        self.assertEqual(run.call_count, 1)

    def test_stops_when_osascript_cannot_run(self):
        with mock.patch("subprocess.run", side_effect=OSError("missing")):
            self.assertFalse(tracker._raise_spawned_window(_Proc()))

    def test_gives_up_at_the_deadline(self):
        with mock.patch("subprocess.run", return_value=_done("PENDING\n")) as run, \
             mock.patch("time.monotonic", side_effect=[0.0, 0.1, 99.0]):
            self.assertFalse(tracker._raise_spawned_window(_Proc(), timeout=4.0))
        self.assertEqual(run.call_count, 1)


class OpenMacosRaisesTests(unittest.TestCase):
    def _open(self, raised):
        with mock.patch.object(tracker, "_find_terminal_cli",
                               return_value="/bin/wezterm"), \
             mock.patch("subprocess.Popen", return_value=_Proc()), \
             mock.patch.object(tracker, "_raise_spawned_window",
                               return_value=raised) as raise_win, \
             mock.patch.object(tracker, "_activate_macos_app") as activate:
            ok, info = tracker._open_macos("WezTerm", "echo hi", "/tmp")
        self.assertTrue(ok)
        self.assertIn("WezTerm", info)
        raise_win.assert_called_once()
        return activate

    def test_raised_window_skips_app_activate(self):
        self._open(raised=True).assert_not_called()

    def test_falls_back_to_app_activate(self):
        self._open(raised=False).assert_called_once_with("WezTerm")


if __name__ == "__main__":
    unittest.main()
