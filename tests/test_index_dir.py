"""인덱스 캐시 위치를 홈에서 떼어내는 `$AST_INDEX_DIR`.

홈을 동기화 폴더(Synology Drive 등)에 두면 `index.json` 이 문제가 된다:
rescan 마다 다시 쓰이는 수~수십 MB 파일이라 동기화 데몬이 끊임없이 올리고,
두 기기가 동시에 쓰면 충돌본이 쌓인다. 게다가 키가 transcript 절대 경로,
값이 mtime 이라 공유해서 얻는 것도 없다. 그래서 index.json 만 따로 뺄 수
있어야 하고, **state.json(done 플래그·prefs)은 홈에 남아야** 한다 — 그쪽은
공유할 값어치가 있다.

여기서 고정하는 성질:
1. 변수를 지정하지 않으면 홈과 같은 디렉터리다(기존 설치의 동작·캐시 보존).
2. 지정하면 index.json 만 옮겨가고 state.json / 락 / 백업은 홈에 남는다.
3. 옮겨간 뒤에도 캐시가 정상 적중한다.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def _fresh_tracker(name, env):
    """주어진 환경변수로 tracker 를 새로 import 한다.

    경로 상수는 import 시점에 모듈 전역으로 굳으므로, 환경변수의 효과를 보려면
    매번 새로 읽어들여야 한다."""
    saved = {k: os.environ.get(k) for k in ("AST_HOME", "AST_INDEX_DIR")}
    try:
        for k in saved:
            os.environ.pop(k, None)
        os.environ.update({k: v for k, v in env.items() if v is not None})
        spec = importlib.util.spec_from_file_location(name, _REPO / "tracker.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
        return mod
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class TestDefaultsToHome(unittest.TestCase):
    def test_unset_means_the_home_itself(self):
        with tempfile.TemporaryDirectory() as home:
            tk = _fresh_tracker("tk_idx_default", {"AST_HOME": home})
            self.assertEqual(tk.INDEX_DIR, Path(home))
            self.assertEqual(tk.CACHE_DIR, Path(home))
            self.assertEqual(tk.CACHE_PATH, Path(home) / "index.json")
            self.assertEqual(tk.STATE_PATH, Path(home) / "state.json")

    def test_home_default_is_dot_ast_for_both(self):
        tk = _fresh_tracker("tk_idx_plain", {})
        self.assertEqual(tk.CACHE_DIR, Path.home() / ".ast")
        self.assertEqual(tk.INDEX_DIR, Path.home() / ".ast")

    def test_index_dir_follows_a_changed_home(self):
        # AST_HOME 만 지정해도 인덱스가 그 홈을 따라가야 한다 — 기본값이
        # 리터럴 ~/.ast 로 굳어 있으면 이 단언이 깨진다.
        with tempfile.TemporaryDirectory() as home:
            tk = _fresh_tracker("tk_idx_follows", {"AST_HOME": home})
            self.assertEqual(tk.INDEX_DIR, Path(home))


class TestExplicitIndexDir(unittest.TestCase):
    def test_splits_index_from_state(self):
        with tempfile.TemporaryDirectory() as home, \
             tempfile.TemporaryDirectory() as idx:
            tk = _fresh_tracker("tk_idx_split",
                                {"AST_HOME": home, "AST_INDEX_DIR": idx})
            self.assertEqual(tk.CACHE_DIR, Path(home))
            self.assertEqual(tk.INDEX_DIR, Path(idx))
            self.assertEqual(tk.CACHE_PATH, Path(idx) / "index.json")
            self.assertEqual(tk.STATE_PATH, Path(home) / "state.json")

    def test_tilde_is_expanded(self):
        tk = _fresh_tracker("tk_idx_tilde", {"AST_INDEX_DIR": "~/somewhere/idx"})
        self.assertEqual(tk.INDEX_DIR, Path.home() / "somewhere" / "idx")
        self.assertFalse(str(tk.INDEX_DIR).startswith("~"))

    def test_backups_stay_in_the_home(self):
        # 백업 아카이브는 재생성 불가한 산출물이라 캐시 쪽으로 가면 안 된다.
        with tempfile.TemporaryDirectory() as home, \
             tempfile.TemporaryDirectory() as idx:
            tk = _fresh_tracker("tk_idx_backup",
                                {"AST_HOME": home, "AST_INDEX_DIR": idx})
            self.assertEqual(tk.CACHE_DIR / "backups", Path(home) / "backups")


class TestFilesLandInTheRightPlace(unittest.TestCase):
    """실제로 읽고 써 보고 어느 디렉터리에 무엇이 생기는지 확인한다."""

    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._idx = tempfile.TemporaryDirectory()
        self._proj = tempfile.TemporaryDirectory()
        for d in (self._home, self._idx, self._proj):
            self.addCleanup(d.cleanup)
        self.home, self.idx = Path(self._home.name), Path(self._idx.name)

        self.tk = _fresh_tracker("tk_idx_files",
                                 {"AST_HOME": str(self.home),
                                  "AST_INDEX_DIR": str(self.idx)})
        root = Path(self._proj.name)
        self.tk.PROJECTS_DIR = root / "projects"
        self.tk.CODEX_SESSIONS_DIR = root / "codex_sessions"
        self.tk.CODEX_LOCKS_DIR = root / "codex_locks"
        for i in range(3):
            sid = f"{i:08d}-0000-0000-0000-000000000000"
            p = self.tk.PROJECTS_DIR / "proj" / f"{sid}.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({
                "type": "user", "cwd": "/repo/app",
                "timestamp": datetime(2026, 6, 1, tzinfo=timezone.utc)
                             .isoformat().replace("+00:00", "Z"),
                "message": {"content": f"요청 {i}"},
            }) + "\n", encoding="utf-8")

    def test_index_goes_to_the_index_dir_only(self):
        rows = self.tk.load_all_sessions()
        self.assertEqual(len(rows), 3)
        self.assertTrue((self.idx / "index.json").is_file())
        self.assertFalse((self.home / "index.json").exists())

    def test_state_goes_to_the_home_only(self):
        st = self.tk.load_state()
        st.setdefault("done", {})["ffffffff-0000-0000-0000-000000000000"] = "x"
        self.tk.save_state(st)
        self.assertTrue((self.home / "state.json").is_file())
        self.assertFalse((self.idx / "state.json").exists())

    def test_lock_goes_to_the_home_only(self):
        with self.tk._state_lock():
            pass
        self.assertTrue((self.home / "state.lock").exists())
        self.assertFalse((self.idx / "state.lock").exists())

    def test_no_tmp_files_left_behind(self):
        self.tk.load_all_sessions()
        self.tk.save_state(self.tk.load_state())
        for d in (self.home, self.idx):
            leftovers = [f.name for f in d.iterdir() if f.name.endswith(".tmp")]
            self.assertEqual(leftovers, [], f"{d} 에 tmp 잔여물")

    def test_cache_still_hits_when_split(self):
        self.tk.load_all_sessions()
        parsed = []
        orig = self.tk.load_session_meta

        def counted(path, fast=True):
            parsed.append(Path(path).name)
            return orig(path, fast=fast)

        self.tk.load_session_meta = counted
        self.addCleanup(setattr, self.tk, "load_session_meta", orig)
        rows = self.tk.load_all_sessions()
        self.assertEqual(parsed, [], f"캐시가 적중하지 않았다: {parsed}")
        self.assertEqual(len(rows), 3)

    def test_deleting_the_index_forces_a_reparse(self):
        self.tk.load_all_sessions()
        (self.idx / "index.json").unlink()
        parsed = []
        orig = self.tk.load_session_meta

        def counted(path, fast=True):
            parsed.append(Path(path).name)
            return orig(path, fast=fast)

        self.tk.load_session_meta = counted
        self.addCleanup(setattr, self.tk, "load_session_meta", orig)
        self.tk.load_all_sessions()
        self.assertEqual(len(parsed), 3,
                         "인덱스를 지웠는데 재파싱하지 않았다 — 엉뚱한 곳을 읽는다")

    def test_seeding_guard_still_keys_off_the_home(self):
        # seed_from_cst_home 은 CACHE_DIR(홈)로 스텁 여부를 판단한다. 인덱스
        # 분리가 그 판단을 흐트러뜨리면 테스트 환경에서 실제 ~/.cst 를 읽게 된다.
        self.assertNotEqual(self.tk.CACHE_DIR, self.tk._ast_home())
        self.assertFalse(self.tk.seed_from_cst_home())


if __name__ == "__main__":
    unittest.main()
