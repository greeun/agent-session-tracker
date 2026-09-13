"""병렬 인덱싱: 언제 프로세스 풀로 넘어가는가, 그리고 넘어가도 결과가 같은가.

`load_all_sessions` 는 캐시 미스가 많을 때만 `ProcessPoolExecutor` 로 파싱을
분산한다. 여기서 고정하는 성질은 세 가지다.

1. **전환 규칙** — 미스가 적으면 순차, 많으면 병렬. `AST_JOBS` 로 강제·차단.
2. **결과 동일성** — 병렬 경로는 결과를 순서 없이 받으므로, 행 집합·정렬
   순서·캐시 내용이 순차 경로와 한 글자도 달라서는 안 된다. 특히 정렬 순서는
   `dedupe_sessions` 의 결정성이 걸려 있어 느슨하게 둘 수 없다.
3. **폴백** — 풀을 띄울 수 없으면 조용히 순차로 되돌아가 끝까지 인덱싱한다.

벽시계 시간은 재지 않는다(CI 부하에 흔들린다). 전환 여부는 `_index_workers`
에게 직접 묻고, 실제 분산 여부는 풀 호출을 가로채 확인한다.
"""

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]


def load_tracker():
    spec = importlib.util.spec_from_file_location("tracker_parallel", _REPO / "tracker.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["tracker_parallel"] = mod
    spec.loader.exec_module(mod)
    return mod


tk = load_tracker()


class _JobsEnv(unittest.TestCase):
    """AST_JOBS 를 건드리는 테스트가 서로를 오염시키지 않게 복원한다."""

    def setUp(self):
        self._jobs = os.environ.get("AST_JOBS")
        self.addCleanup(self._restore_jobs)

    def _restore_jobs(self):
        if self._jobs is None:
            os.environ.pop("AST_JOBS", None)
        else:
            os.environ["AST_JOBS"] = self._jobs

    def _set_jobs(self, value):
        if value is None:
            os.environ.pop("AST_JOBS", None)
        else:
            os.environ["AST_JOBS"] = value


class TestIndexWorkers(_JobsEnv):
    def test_too_few_misses_stays_sequential(self):
        self._set_jobs(None)
        self.assertEqual(tk._index_workers(0), 0)
        self.assertEqual(tk._index_workers(1), 0)
        self.assertEqual(tk._index_workers(tk._PARALLEL_MIN_MISSES - 1), 0)

    def test_enough_misses_asks_for_workers(self):
        self._set_jobs(None)
        n = tk._index_workers(tk._PARALLEL_MIN_MISSES)
        self.assertGreaterEqual(n, 1)
        self.assertLessEqual(n, tk._PARALLEL_MAX_WORKERS)

    def test_worker_count_never_exceeds_the_work(self):
        self._set_jobs("99")
        self.assertEqual(tk._index_workers(3), 3)

    def test_capped_at_the_pool_maximum(self):
        self._set_jobs(None)
        self.assertLessEqual(tk._index_workers(100000), tk._PARALLEL_MAX_WORKERS)

    def test_jobs_one_disables_parallel_entirely(self):
        self._set_jobs("1")
        self.assertEqual(tk._index_workers(100000), 0)

    def test_jobs_lowers_the_threshold_so_it_is_testable(self):
        # 강제 지정이 있으면 미스 2개만으로도 병렬로 간다.
        self._set_jobs("2")
        self.assertEqual(tk._index_workers(2), 2)
        # 1개뿐이면 나눌 일이 없으니 여전히 순차다.
        self.assertEqual(tk._index_workers(1), 0)

    def test_unparseable_jobs_value_falls_back_to_the_threshold(self):
        self._set_jobs("도합 넷")
        self.assertEqual(tk._index_workers(5), 0)
        self.assertGreaterEqual(tk._index_workers(tk._PARALLEL_MIN_MISSES), 1)

    def test_zero_and_negative_read_as_sequential(self):
        # 0/음수는 1 로 올려 잡히고, 워커 1개는 순차와 같으므로 풀을 띄우지
        # 않는다 — "끄는" 값으로 AST_JOBS=1 뿐 아니라 0 과 -1 도 통한다.
        for value in ("0", "-1"):
            with self.subTest(value=value):
                self._set_jobs(value)
                self.assertEqual(tk._index_workers(500), 0)


class _Sessions(_JobsEnv):
    """여러 세션을 가진 임시 projects 트리."""

    N = 6

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        root = Path(self._tmp.name)
        self._orig = (tk.PROJECTS_DIR, tk.CODEX_SESSIONS_DIR, tk.CODEX_LOCKS_DIR,
                      tk.CACHE_DIR, tk.CACHE_PATH)
        self.addCleanup(self._restore_paths)
        tk.PROJECTS_DIR = root / "projects"
        tk.CODEX_SESSIONS_DIR = root / "codex_sessions"
        tk.CODEX_LOCKS_DIR = root / "codex_locks"
        tk.CACHE_DIR = root / "cache"
        tk.CACHE_PATH = tk.CACHE_DIR / "index.json"

        base = datetime(2026, 6, 1, tzinfo=timezone.utc)
        self.files = []
        for i in range(self.N):
            self.files.append(self._mk(
                f"{i:08d}-0000-0000-0000-000000000000",
                ts=(base + timedelta(minutes=i)),
                cwd=f"/repo/app{i % 2}",
                text=f"세션 {i} 의 첫 요청",
            ))

    def _restore_paths(self):
        (tk.PROJECTS_DIR, tk.CODEX_SESSIONS_DIR, tk.CODEX_LOCKS_DIR,
         tk.CACHE_DIR, tk.CACHE_PATH) = self._orig

    def _mk(self, sid, ts, cwd="/repo/app", text="hi", extra_lines=()):
        p = tk.PROJECTS_DIR / tk.encode_cwd(cwd) / f"{sid}.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        stamp = ts.isoformat().replace("+00:00", "Z")
        lines = [json.dumps({"type": "user", "cwd": cwd, "timestamp": stamp,
                             "gitBranch": "develop", "entrypoint": "cli",
                             "message": {"content": text}})]
        lines.extend(extra_lines)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return p

    def _rows(self, jobs):
        """캐시를 비우고 콜드 로드한 뒤, 비교 가능한 형태로 돌려준다."""
        self._set_jobs(jobs)
        if tk.CACHE_PATH.exists():
            tk.CACHE_PATH.unlink()
        rows = tk.load_all_sessions()
        return [(r.session_id, r.cwd, r.msg_count, r.first_user_msg,
                 r.git_branch, r.entrypoint, r.agent,
                 tuple(sorted(map(repr, r.prs))), r.last_ts) for r in rows]


class TestParallelMatchesSequential(_Sessions):
    def test_same_rows_in_the_same_order(self):
        par = self._rows("4")
        seq = self._rows("1")
        self.assertEqual(len(par), self.N)
        self.assertEqual(par, seq)

    def test_cache_contents_match_too(self):
        self._rows("4")
        par_cache = json.loads(tk.CACHE_PATH.read_text(encoding="utf-8"))
        self._rows("1")
        seq_cache = json.loads(tk.CACHE_PATH.read_text(encoding="utf-8"))
        self.assertEqual(par_cache["entries"].keys(), seq_cache["entries"].keys())
        for key, entry in par_cache["entries"].items():
            self.assertEqual(entry, seq_cache["entries"][key], key)

    def test_parallel_pass_is_actually_used(self):
        # _index_parallel 이 정말 호출되는지 — "결과가 같다"만으로는 순차
        # 폴백이 조용히 전부 처리한 경우와 구별되지 않는다.
        seen = {}
        orig = tk._index_parallel

        def spy(paths, fast, workers, on_done):
            seen["paths"] = len(paths)
            seen["workers"] = workers
            return orig(paths, fast, workers, on_done)

        tk._index_parallel = spy
        self.addCleanup(setattr, tk, "_index_parallel", orig)
        rows = self._rows("3")
        self.assertEqual(seen.get("paths"), self.N)
        self.assertEqual(seen.get("workers"), 3)
        self.assertEqual(len(rows), self.N)

    def test_sequential_path_does_not_touch_the_pool(self):
        called = []
        orig = tk._index_parallel
        tk._index_parallel = lambda *a, **k: called.append(a) or True
        self.addCleanup(setattr, tk, "_index_parallel", orig)
        self._rows("1")
        self.assertEqual(called, [])

    def test_filters_still_apply_on_the_parallel_path(self):
        self._set_jobs("4")
        if tk.CACHE_PATH.exists():
            tk.CACHE_PATH.unlink()
        rows = tk.load_all_sessions(cwd_filter="/repo/app0")
        self.assertTrue(rows)
        self.assertTrue(all(r.cwd == "/repo/app0" for r in rows))
        self.assertLess(len(rows), self.N)

    def test_progress_callback_counts_every_file_once(self):
        self._set_jobs("4")
        if tk.CACHE_PATH.exists():
            tk.CACHE_PATH.unlink()
        calls = []
        tk.load_all_sessions(on_progress=lambda d, t: calls.append((d, t)))
        self.assertEqual(calls[0], (0, self.N))
        self.assertEqual(calls[-1], (self.N, self.N))
        # done 은 1씩 빠짐없이 올라간다(완료 순서는 무관하다).
        self.assertEqual([d for d, _ in calls], list(range(self.N + 1)))


class TestStderrCounterThrottle(_Sessions):
    """`progress=True` 의 stderr 카운터는 퍼센트가 바뀔 때만 다시 그린다.

    파일마다 한 번씩 쓰면 실제 tty 에서 콜드 인덱싱 2.7초 중 0.9초를 같은
    숫자를 그리는 데 쓴다. 진행률 자체는 `on_progress` 가 파일 단위로
    정확하게 보고하므로, 화면 쪽만 줄이면 된다."""

    N = 40

    def _capture(self):
        import io

        class _TtyIO(io.StringIO):
            def isatty(self):
                return True

        buf = _TtyIO()
        orig = sys.stderr
        sys.stderr = buf
        self.addCleanup(setattr, sys, "stderr", orig)
        return buf

    def test_repaints_at_most_once_per_percent(self):
        self._set_jobs("1")
        if tk.CACHE_PATH.exists():
            tk.CACHE_PATH.unlink()
        buf = self._capture()
        tk.load_all_sessions(progress=True)
        frames = [f for f in buf.getvalue().split("\r") if "Indexing" in f]
        # 40개 파일이면 퍼센트는 40번만 바뀔 수 있고, 파일마다 그렸다면 40번
        # 모두 나온다. 같은 퍼센트를 두 번 그리지 않는지가 핵심이다.
        pcts = [f.split("%")[0].split()[-1] for f in frames]
        self.assertEqual(len(pcts), len(set(pcts)),
                         f"같은 퍼센트를 여러 번 그렸다: {pcts}")

    def test_progress_callback_is_not_throttled(self):
        # 화면만 줄이고 콜백은 파일 단위를 유지한다 — 호출자가 자기 속도로
        # 스로틀할 수 있어야 하고, 그 판단을 여기서 대신하지 않는다.
        self._set_jobs("1")
        if tk.CACHE_PATH.exists():
            tk.CACHE_PATH.unlink()
        self._capture()
        calls = []
        tk.load_all_sessions(progress=True,
                             on_progress=lambda d, t: calls.append(d))
        self.assertEqual(calls, list(range(self.N + 1)))

    def test_counter_is_erased_when_the_scan_ends(self):
        self._set_jobs("1")
        if tk.CACHE_PATH.exists():
            tk.CACHE_PATH.unlink()
        buf = self._capture()
        tk.load_all_sessions(progress=True)
        self.assertTrue(buf.getvalue().rstrip("\r").endswith(" "),
                        "진행 줄을 지우지 않고 남겼다")

    def test_warm_scan_prints_nothing(self):
        self._set_jobs("1")
        tk.load_all_sessions()
        buf = self._capture()
        tk.load_all_sessions(progress=True)
        self.assertNotIn("Indexing", buf.getvalue())


class TestParallelFallback(_Sessions):
    def test_pool_failure_falls_back_to_sequential(self):
        orig = tk._index_parallel
        tk._index_parallel = lambda *a, **k: False      # 풀을 띄우지 못한 상황
        self.addCleanup(setattr, tk, "_index_parallel", orig)
        self._set_jobs("4")
        if tk.CACHE_PATH.exists():
            tk.CACHE_PATH.unlink()
        rows = tk.load_all_sessions()
        self.assertEqual(len(rows), self.N)
        self.assertTrue(all(r.first_user_msg for r in rows))

    def test_partial_pool_failure_is_not_silently_half_indexed(self):
        # 풀이 중간에 깨지면 _index_parallel 은 False 를 반환하고, 호출자가
        # 전부 순차로 다시 읽는다. 일부만 읽힌 채 끝나면 안 된다.
        orig = tk._index_parallel

        def half_then_fail(paths, fast, workers, on_done):
            on_done(str(paths[0]), None)
            return False

        tk._index_parallel = half_then_fail
        self.addCleanup(setattr, tk, "_index_parallel", orig)
        self._set_jobs("4")
        if tk.CACHE_PATH.exists():
            tk.CACHE_PATH.unlink()
        rows = tk.load_all_sessions()
        self.assertEqual(len(rows), self.N)


class TestIndexOneWorker(_Sessions):
    def test_returns_a_cache_entry_with_mtime_and_size(self):
        p = self.files[0]
        path_str, entry = tk._index_one((str(p), True))
        self.assertEqual(path_str, str(p))
        self.assertIsNotNone(entry)
        st = p.stat()
        self.assertEqual(entry["mtime"], st.st_mtime)
        self.assertEqual(entry["size"], st.st_size)
        self.assertEqual(entry["session_id"], p.stem)

    def test_messageless_file_reports_none_rather_than_raising(self):
        empty = tk.PROJECTS_DIR / "proj" / "ffffffff-0000-0000-0000-000000000000.jsonl"
        empty.parent.mkdir(parents=True, exist_ok=True)
        empty.write_text("", encoding="utf-8")
        self.assertEqual(tk._index_one((str(empty), True)), (str(empty), None))

    def test_missing_file_reports_none_rather_than_raising(self):
        gone = tk.PROJECTS_DIR / "proj" / "00000000-dead-0000-0000-000000000000.jsonl"
        self.assertEqual(tk._index_one((str(gone), True)), (str(gone), None))


if __name__ == "__main__":
    unittest.main()
