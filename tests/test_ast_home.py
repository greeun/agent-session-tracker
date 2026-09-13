"""ast의 데이터 홈(~/.ast)과 cst 홈에서 상태를 이어받는 1회 시딩.

ast는 자기 홈을 쓰므로 cst가 설치돼 있어도 나란히 둘 수 있다. 그래서 이전의 "레거시 디렉터리를
옮긴다"가 아니라 "cst가 쓰던 state.json을 첫 실행 때 한 번 복사한다"가 되며,
원본은 cst가 계속 쓰도록 그대로 둬야 한다."""
import importlib.util
import os
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


class TestAstHomeDerivation(unittest.TestCase):
    def setUp(self):
        self._saved = os.environ.get("AST_HOME")

    def tearDown(self):
        if self._saved is None:
            os.environ.pop("AST_HOME", None)
        else:
            os.environ["AST_HOME"] = self._saved

    def test_default_is_dot_ast_under_home(self):
        os.environ.pop("AST_HOME", None)
        self.assertEqual(tk._ast_home(), Path.home() / ".ast")

    def test_env_override(self):
        os.environ["AST_HOME"] = "/tmp/custom-ast"
        self.assertEqual(tk._ast_home(), Path("/tmp/custom-ast"))

    def test_does_not_share_the_cst_home(self):
        """cst와 홈이 갈려야 두 도구의 done 플래그가 서로 덮어쓰지 않는다."""
        os.environ.pop("AST_HOME", None)
        self.assertNotEqual(tk._ast_home(), Path.home() / ".cst")

    def test_module_paths_derive_from_cache_dir(self):
        # index.json / state.json live side by side under the single home.
        self.assertEqual(tk.CACHE_PATH, tk.CACHE_DIR / "index.json")
        self.assertEqual(tk.STATE_PATH, tk.CACHE_DIR / "state.json")


class _SeedEnv(unittest.TestCase):
    """AST_HOME이 스텁 경로를 가리켜야 seed_from_cst_home()의
    가드(CACHE_DIR == _ast_home())를 통과한다."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        root = Path(self._tmp.name)
        self._saved_env = os.environ.get("AST_HOME")
        os.environ["AST_HOME"] = str(root / "ast")
        self._orig = (tk.CACHE_DIR, tk.CACHE_PATH, tk.STATE_PATH, tk._CST_HOME_DIR)
        tk.CACHE_DIR = root / "ast"
        tk.CACHE_PATH = tk.CACHE_DIR / "index.json"
        tk.STATE_PATH = tk.CACHE_DIR / "state.json"
        tk._CST_HOME_DIR = root / "cst"

    def tearDown(self):
        (tk.CACHE_DIR, tk.CACHE_PATH, tk.STATE_PATH, tk._CST_HOME_DIR) = self._orig
        if self._saved_env is None:
            os.environ.pop("AST_HOME", None)
        else:
            os.environ["AST_HOME"] = self._saved_env
        self._tmp.cleanup()

    def _make_cst_home(self, state='{"done": {"sid": "t"}}', index='{"schema": 5}'):
        tk._CST_HOME_DIR.mkdir(parents=True)
        if state is not None:
            (tk._CST_HOME_DIR / "state.json").write_text(state, encoding="utf-8")
        if index is not None:
            (tk._CST_HOME_DIR / "index.json").write_text(index, encoding="utf-8")


class TestSeedFromCstHome(_SeedEnv):
    def test_copies_state_and_leaves_the_original(self):
        self._make_cst_home()
        self.assertTrue(tk.seed_from_cst_home())
        self.assertEqual(tk.STATE_PATH.read_text(encoding="utf-8"),
                         '{"done": {"sid": "t"}}')
        self.assertTrue((tk._CST_HOME_DIR / "state.json").exists(),
                        "cst는 자기 홈을 계속 쓰므로 원본을 옮기면 안 된다")

    def test_index_is_not_copied(self):
        """index.json은 언제든 재생성되는 캐시이고 파일 경로 키가 갈릴 수
        있으므로 가져오지 않는다."""
        self._make_cst_home()
        tk.seed_from_cst_home()
        self.assertFalse(tk.CACHE_PATH.exists())

    def test_existing_state_is_never_overwritten(self):
        self._make_cst_home(state='{"old": true}')
        tk.CACHE_DIR.mkdir(parents=True)
        tk.STATE_PATH.write_text('{"new": true}', encoding="utf-8")
        self.assertFalse(tk.seed_from_cst_home())
        self.assertEqual(tk.STATE_PATH.read_text(encoding="utf-8"), '{"new": true}')

    def test_noop_without_a_cst_home(self):
        self.assertFalse(tk.seed_from_cst_home())
        self.assertFalse(tk.STATE_PATH.exists())

    def test_noop_when_cst_home_has_no_state(self):
        self._make_cst_home(state=None)
        self.assertFalse(tk.seed_from_cst_home())
        self.assertFalse(tk.STATE_PATH.exists())

    def test_idempotent_second_run_is_noop(self):
        self._make_cst_home()
        self.assertTrue(tk.seed_from_cst_home())
        self.assertFalse(tk.seed_from_cst_home())

    def test_guard_blocks_when_paths_are_stubbed_elsewhere(self):
        # CACHE_DIR != _ast_home() means paths were redirected (e.g. another
        # test suite's stubs) — seeding must not touch anything.
        self._make_cst_home()
        os.environ["AST_HOME"] = str(Path(self._tmp.name) / "other")
        self.assertFalse(tk.seed_from_cst_home())
        self.assertFalse(tk.STATE_PATH.exists())


if __name__ == "__main__":
    unittest.main()
