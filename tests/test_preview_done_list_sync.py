"""preview 모달(`v`)에서 `d` 로 상태를 바꿨을 때, 모달 뒤에 깔린 목록 화면이
즉시 따라오는지 검증한다.

모달 박스는 화면 전체를 덮지 않기 때문에 사용자에게는 그 주변으로 목록이 계속
보인다. 예전에는 목록이 모달을 열기 직전 상태 그대로 남아 있어서, 모달 안의
Status 행은 ✓ 로 바뀌었는데 바로 뒤 목록 행은 여전히 ○ 로 보이는 모순이
생겼다. `_pick_ui` 가 넘기는 `on_status_change` 콜백이 그 행과 헤더의 ✓/○
카운트를 다시 그려야 한다.

계층 구분: done 플래그가 실제로 파일에 기록되는지는 test_preview_done.py 가,
Status 행 자체의 색은 test_preview_status_color.py 가 소유한다. 여기서 보는
것은 **모달 안의 토글 → 모달 밖(stdscr) 화면 반영** 경로뿐이다.

curses TUI 는 실제 tty 가 필요하므로 pty.fork 로 헤드리스 구동한다.
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
_OUT = pathlib.Path(tempfile.gettempdir()) / "ast_preview_done_list_sync.json"

_SID_A = "aaaaaaaa-1111"
_SID_B = "bbbbbbbb-2222"
_SID_C = "cccccccc-3333"


def _load():
    spec = importlib.util.spec_from_file_location("tracker_preview_sync", _TP)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tracker_preview_sync"] = mod
    spec.loader.exec_module(mod)
    return mod


def _child():
    import curses

    tmp = tempfile.mkdtemp()
    os.environ["AST_HOME"] = tmp
    tr = _load()
    tr.CACHE_DIR = pathlib.Path(tmp)
    tr.STATE_PATH = tr.CACHE_DIR / "state.json"

    d = pathlib.Path(tempfile.mkdtemp())
    rec = {"type": "user", "timestamp": "2026-06-28T10:00:00.000Z",
           "message": {"content": "ROWONE"}}
    pa = d / "a.jsonl"
    pa.write_text(json.dumps(rec) + "\n")
    pb = d / "b.jsonl"
    pb.write_text(json.dumps(dict(rec, message={"content": "ROWTWO"})) + "\n")
    pc = d / "c.jsonl"
    pc.write_text(json.dumps(dict(rec, message={"content": "ROWTHREE"})) + "\n")

    ts = datetime(2026, 6, 28, 12, 0, tzinfo=timezone.utc)
    sessions = [
        tr.SessionMeta(session_id=_SID_A, path=pa, cwd="/w/a", first_ts=ts,
                       last_ts=ts, msg_count=1, first_user_msg="ROWONE",
                       entrypoint="cli"),
        tr.SessionMeta(session_id=_SID_B, path=pb, cwd="/w/b", first_ts=ts,
                       last_ts=ts, msg_count=1, first_user_msg="ROWTWO",
                       entrypoint="cli"),
        tr.SessionMeta(session_id=_SID_C, path=pc, cwd="/w/c", first_ts=ts,
                       last_ts=ts, msg_count=1, first_user_msg="ROWTHREE",
                       entrypoint="cli"),
    ]

    # 두 세션 모두 살아 있지 않은 상태 -> ○ ended 로 출발한다.
    ctx = tr.StatusContext(live=set(), done=set(), registry={}, overlay={},
                           jobs={}, pins=set())
    tr.StatusContext.capture = classmethod(lambda cls: ctx)

    bg_frames = []      # 모달이 떠 있는 동안의 stdscr(= 뒤쪽 목록) 스냅숏
    list_frames = []    # 목록 루프가 키를 기다리는 시점의 stdscr 스냅숏
    holder = {}

    def _snap(win):
        maxy, _ = win.getmaxyx()
        out = []
        for y in range(maxy):
            try:
                out.append(win.instr(y, 0).decode("utf-8", "replace"))
            except Exception:
                out.append("")
        return "\n".join(out)

    # 모달 안에서 먹일 키: d(토글) -> q(닫기). 키를 요구하는 매 시점마다
    # 모달이 아니라 그 뒤의 stdscr 을 캡처한다.
    modal_keys = [(ord("d"), None), (ord("q"), None)]
    midx = [0]

    def fake_read_key(win):
        bg_frames.append(_snap(holder["stdscr"]))
        k = modal_keys[midx[0]] if midx[0] < len(modal_keys) else (ord("q"), None)
        midx[0] += 1
        return k

    tr._read_key = fake_read_key

    keyseq = [ord("v"), 27]   # v 로 모달을 열고, 닫힌 뒤 Esc 로 종료
    idx = [0]

    class Proxy:
        def __init__(self, w):
            self._w = w

        def getch(self):
            list_frames.append(_snap(self._w))
            k = keyseq[idx[0]] if idx[0] < len(keyseq) else 27
            idx[0] += 1
            return k

        def __getattr__(self, name):
            return getattr(self._w, name)

    result = {}

    def run(stdscr):
        try:
            curses.start_color()
        except Exception:
            pass
        proxy = Proxy(stdscr)
        holder["stdscr"] = proxy
        if os.environ.get("AST_TEST_MODE") == "callback_error":
            # 좁은 터미널 등에서 배경 재렌더가 실패해도 모달과 done 토글은
            # 살아남아야 한다 — 콜백이 curses.error 를 던지게 만들어 확인한다.
            def _boom():
                raise curses.error("simulated too-small terminal")

            ret = tr._preview_modal(proxy, sessions, 0, ctx,
                                    on_status_change=_boom)
            result["returned"] = None if ret is None else ret.session_id
        else:
            # "hide" 모드는 H(완료 숨김)가 켜진 채로 TUI 를 띄운다.
            tr._pick_ui(proxy, sessions, None, None,
                        hide_done_default=os.environ.get("AST_TEST_MODE") == "hide")

    curses.wrapper(run)
    result.update({
        "bg_frames": bg_frames,
        "list_frames": list_frames,
        "done_ids": sorted(tr.done_ids()),
        "ctx_done": sorted(ctx.done),
        "glyph_done": tr.STATUS_DONE,
        "glyph_ended": tr.STATUS_ENDED,
    })
    _OUT.write_text(json.dumps(result))


def _run_headless(mode="sync"):
    if _OUT.exists():
        _OUT.unlink()
    pid, fd = pty.fork()
    if pid == 0:
        try:
            os.environ["AST_TEST_MODE"] = mode
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


def _row(frame: str, msg: str) -> str:
    for ln in frame.split("\n"):
        if msg in ln:
            return ln
    return ""


class TestPreviewDoneListSync(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.res = _run_headless()

    def setUp(self):
        self.assertNotIn("error", self.res, msg=self.res.get("error"))
        self.assertEqual(len(self.res["bg_frames"]), 2,
                         "모달이 키를 두 번(d, q) 요구해야 한다")

    # ---- 모달이 떠 있는 동안의 뒤쪽 목록 --------------------------------
    def test_row_behind_the_modal_follows_the_toggle(self):
        before, after = self.res["bg_frames"]
        done, ended = self.res["glyph_done"], self.res["glyph_ended"]
        self.assertIn(ended, _row(before, "ROWONE"),
                      "토글 전 행은 ○ ended 여야 한다")
        self.assertIn(done, _row(after, "ROWONE"),
                      "모달을 닫기 전에 뒤쪽 목록 행이 ✓ 로 바뀌어야 한다")

    def test_other_rows_are_untouched(self):
        before, after = self.res["bg_frames"]
        self.assertEqual(_row(before, "ROWTWO"), _row(after, "ROWTWO"),
                         "토글하지 않은 행까지 바뀌면 안 된다")

    def test_header_counts_follow_the_toggle(self):
        before, after = self.res["bg_frames"]
        done, ended = self.res["glyph_done"], self.res["glyph_ended"]
        self.assertIn(f"{ended}3 {done}0", before.split("\n")[0])
        self.assertIn(f"{ended}2 {done}1", after.split("\n")[0])

    def test_rows_stay_in_place_when_done_is_not_hidden(self):
        """H 가 꺼져 있으면 ✓ 로 바뀔 뿐 행이 사라지지는 않는다."""
        before, after = self.res["bg_frames"]
        self.assertIn(" 3/3 ", before.split("\n")[0])
        self.assertIn(" 3/3 ", after.split("\n")[0])
        for msg in ("ROWONE", "ROWTWO", "ROWTHREE"):
            self.assertTrue(_row(after, msg), f"{msg} 행이 사라졌다")

    # ---- 모달을 닫은 뒤 (기존 동작의 회귀 방지) -------------------------
    def test_list_still_shows_the_toggle_after_the_modal_closes(self):
        # list_frames[0] = v 를 누르기 전, [1] = 모달이 닫힌 뒤
        self.assertEqual(len(self.res["list_frames"]), 2)
        closed = self.res["list_frames"][1]
        self.assertIn(self.res["glyph_done"], _row(closed, "ROWONE"))

    def test_done_flag_is_persisted(self):
        self.assertEqual(self.res["done_ids"], [_SID_A])
        self.assertEqual(self.res["ctx_done"], [_SID_A])


class TestHiddenWhenDoneIsHidden(unittest.TestCase):
    """`H`(완료 숨김)가 켜진 상태에서 모달 안의 `d` 로 done 처리하면, 뒤쪽
    목록에서도 그 행이 곧바로 사라져야 한다 — 목록에서 `D` 를 누른 것과 같은
    결과이며, 모달을 닫을 때까지 ✓ 행이 남아 있으면 숨김 설정과 모순된다."""

    @classmethod
    def setUpClass(cls):
        cls.res = _run_headless("hide")

    def setUp(self):
        self.assertNotIn("error", self.res, msg=self.res.get("error"))

    def test_the_toggled_row_disappears_from_the_list_behind(self):
        before, after = self.res["bg_frames"]
        self.assertTrue(_row(before, "ROWONE"), "토글 전에는 행이 보여야 한다")
        self.assertFalse(_row(after, "ROWONE"),
                         "숨김이 켜져 있으면 모달을 닫기 전에 사라져야 한다")

    def test_remaining_rows_close_the_gap(self):
        after = self.res["bg_frames"][1]
        self.assertTrue(_row(after, "ROWTWO").strip().startswith("1"),
                        "남은 행이 1번으로 올라와야 한다")
        self.assertTrue(_row(after, "ROWTHREE").strip().startswith("2"))

    def test_header_row_count_shrinks(self):
        before, after = self.res["bg_frames"]
        self.assertIn(" 3/3 ", before.split("\n")[0])
        self.assertIn(" 2/3 ", after.split("\n")[0])

    def test_footer_follows_the_new_focus_row(self):
        before, after = self.res["bg_frames"]
        self.assertIn(_SID_A, before.split("\n")[-1])
        self.assertIn(_SID_B, after.split("\n")[-1],
                      "포커스가 옮겨간 세션을 푸터가 가리켜야 한다")

    def test_the_close_state_matches_what_was_shown_behind(self):
        """모달을 닫은 뒤 목록이 배경에 그려 두었던 것과 같아야 한다 — 배경만
        먼저 바뀌고 닫으면 되돌아오는 식이면 오히려 혼란스럽다."""
        after = self.res["bg_frames"][1]
        closed = self.res["list_frames"][1]
        self.assertFalse(_row(closed, "ROWONE"))
        self.assertEqual(_row(after, "ROWTWO"), _row(closed, "ROWTWO"))
        self.assertEqual(after.split("\n")[0], closed.split("\n")[0])


class TestRepaintFailureIsContained(unittest.TestCase):
    """배경 재렌더는 부가 기능이다. 콜백이 실패하더라도(예: 창이 너무 좁아
    curses.error 가 나는 경우) 모달은 계속 뜨고 done 토글도 그대로 남아야 한다."""

    @classmethod
    def setUpClass(cls):
        cls.res = _run_headless("callback_error")

    def test_modal_survives_a_failing_callback(self):
        self.assertNotIn("error", self.res, msg=self.res.get("error"))
        self.assertIsNone(self.res["returned"], "삭제 요청이 아닌데 값이 반환됐다")
        self.assertEqual(self.res["done_ids"], [_SID_A],
                         "콜백이 실패해도 done 토글 자체는 기록돼야 한다")


if __name__ == "__main__":
    unittest.main()
