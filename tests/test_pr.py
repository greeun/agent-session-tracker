"""PR detection via transcript link-scan.

Verified against a real agent-view session that opened a PR: jobs/state.json
carries NO pr field — only linkScanPath/linkScanOffset pointing at the
transcript. agent-view detects PRs by scanning the transcript for PR URLs, so
ast does the same over the transcript it already reads. Real sample URL:
https://github.com/greeun/cst-pr-probe/pull/1
"""
import importlib.util
import json as _json
import pathlib
import sys
import tempfile
import unittest

_TP = pathlib.Path(__file__).resolve().parent.parent / "tracker.py"
_spec = importlib.util.spec_from_file_location("tracker_pr", _TP)
tk = importlib.util.module_from_spec(_spec)
sys.modules["tracker_pr"] = tk
_spec.loader.exec_module(tk)


class TestFindPrRefs(unittest.TestCase):
    def test_github_pull(self):
        refs = tk.find_pr_refs("opened https://github.com/greeun/cst-pr-probe/pull/1 done")
        self.assertEqual(len(refs), 1)
        self.assertEqual(refs[0]["number"], 1)
        self.assertEqual(refs[0]["repo"], "greeun/cst-pr-probe")
        self.assertEqual(refs[0]["host"], "github.com")

    def test_gitlab_merge_request(self):
        refs = tk.find_pr_refs("https://gitlab.com/grp/proj/-/merge_requests/42")
        self.assertEqual((refs[0]["host"], refs[0]["number"]), ("gitlab.com", 42))

    def test_dedup_same_pr(self):
        t = ("https://github.com/o/r/pull/7 ... again "
             "https://github.com/o/r/pull/7")
        self.assertEqual(len(tk.find_pr_refs(t)), 1)

    def test_distinct_prs(self):
        t = "https://github.com/o/r/pull/1 https://github.com/o/r/pull/2"
        self.assertEqual({r["number"] for r in tk.find_pr_refs(t)}, {1, 2})

    def test_no_match(self):
        self.assertEqual(tk.find_pr_refs("github.com/o/r/issues/3 plain text"), [])
        self.assertEqual(tk.find_pr_refs(""), [])


class TestScanPrRefs(unittest.TestCase):
    def test_scans_jsonl_file(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        tmp.write(_json.dumps({"type": "user", "message": {"content": "hi"}}) + "\n")
        tmp.write(_json.dumps({"type": "user", "message": {"content":
                  "PR is https://github.com/greeun/cst-pr-probe/pull/1"}}) + "\n")
        tmp.close()
        self.addCleanup(pathlib.Path(tmp.name).unlink, missing_ok=True)
        refs = tk.scan_pr_refs(pathlib.Path(tmp.name))
        self.assertEqual([r["number"] for r in refs], [1])


class TestPrBadge(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(tk.pr_badge([]), "")

    def test_single(self):
        self.assertEqual(tk.pr_badge([{"number": 1}]), "[PR #1]")

    def test_multiple_sorted(self):
        self.assertEqual(tk.pr_badge([{"number": 3}, {"number": 1}]),
                         "[PR #1,3]")


class TestMetaCarriesPrs(unittest.TestCase):
    def test_load_session_meta_extracts_prs(self):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        tmp.write(_json.dumps({"type": "user", "timestamp": "2026-06-20T00:00:00Z",
                  "cwd": "/r", "message": {"content": "do it"}}) + "\n")
        tmp.write(_json.dumps({"type": "user", "timestamp": "2026-06-20T00:01:00Z",
                  "message": {"content":
                  "see https://github.com/greeun/cst-pr-probe/pull/1"}}) + "\n")
        tmp.close()
        self.addCleanup(pathlib.Path(tmp.name).unlink, missing_ok=True)
        meta = tk.load_session_meta(pathlib.Path(tmp.name))
        self.assertEqual([p["number"] for p in meta.prs], [1])

    def test_cache_roundtrip_preserves_prs(self):
        m = tk.SessionMeta(session_id="s", path=pathlib.Path("/x.jsonl"),
                           prs=[{"host": "github.com", "repo": "o/r",
                                 "number": 9, "url": "u"}])
        back = tk._meta_from_cache(tk._meta_to_cache(m), pathlib.Path("/x.jsonl"))
        self.assertEqual(back.prs, m.prs)

    def test_cache_schema_bumped(self):
        # adding the prs field must invalidate v3 caches
        self.assertGreaterEqual(tk._CACHE_SCHEMA, 4)


class TestSinglePassCoverage(unittest.TestCase):
    """The PR scan rides on the Turn stream's own read, so it must still see
    lines the Turn stream itself discards — tool results, records of a type no
    adapter yields, even lines that are not valid JSON. Scanning only the
    user/assistant message text would silently stop detecting PRs that Claude
    opened through a tool call, which is where they actually appear."""

    def _write(self, *lines):
        tmp = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False)
        for line in lines:
            tmp.write(line + "\n")
        tmp.close()
        self.addCleanup(pathlib.Path(tmp.name).unlink, missing_ok=True)
        return pathlib.Path(tmp.name)

    def _numbers(self, path):
        meta = tk.load_session_meta(path)
        return sorted(p["number"] for p in (meta.prs if meta else []))

    def test_url_in_a_record_type_no_adapter_yields(self):
        p = self._write(
            _json.dumps({"type": "user", "timestamp": "2026-06-20T00:00:00Z",
                         "cwd": "/r", "message": {"content": "open a PR"}}),
            # `system` is not user/assistant: iter_turns drops it entirely.
            _json.dumps({"type": "system", "content":
                         "created https://github.com/greeun/probe/pull/7"}),
        )
        self.assertEqual(self._numbers(p), [7])

    def test_url_inside_a_tool_result_block(self):
        p = self._write(
            _json.dumps({"type": "user", "timestamp": "2026-06-20T00:00:00Z",
                         "cwd": "/r", "message": {"content": "gh pr create"}}),
            _json.dumps({"type": "user", "message": {"content": [
                {"type": "tool_result",
                 "content": "https://github.com/greeun/probe/pull/12\n"}]}}),
        )
        self.assertEqual(self._numbers(p), [12])

    def test_url_on_an_unparseable_line(self):
        p = self._write(
            _json.dumps({"type": "user", "timestamp": "2026-06-20T00:00:00Z",
                         "cwd": "/r", "message": {"content": "hi"}}),
            '{"truncated": "https://github.com/greeun/probe/pull/3"',
        )
        self.assertEqual(self._numbers(p), [3])

    def test_deduped_across_the_whole_file_keeping_first_occurrence(self):
        url = "https://github.com/greeun/probe/pull/5"
        p = self._write(
            _json.dumps({"type": "user", "timestamp": "2026-06-20T00:00:00Z",
                         "cwd": "/r", "message": {"content": f"see {url}"}}),
            _json.dumps({"type": "assistant", "message": {"content": f"done {url}"}}),
            _json.dumps({"type": "system", "content":
                         "https://gitlab.com/grp/proj/-/merge_requests/8"}),
        )
        meta = tk.load_session_meta(p)
        self.assertEqual(sorted(x["number"] for x in meta.prs), [5, 8])
        self.assertEqual(len(meta.prs), 2)

    def test_matches_the_standalone_scanner(self):
        p = self._write(
            _json.dumps({"type": "user", "timestamp": "2026-06-20T00:00:00Z",
                         "cwd": "/r", "message": {"content":
                         "https://github.com/greeun/probe/pull/1"}}),
            _json.dumps({"type": "system", "content":
                         "https://bitbucket.org/t/r/pull-requests/2"}),
            _json.dumps({"type": "assistant", "message": {"content":
                         "https://gitlab.com/g/p/-/merge_requests/3"}}),
        )
        meta = tk.load_session_meta(p)
        self.assertEqual(sorted(map(repr, meta.prs)),
                         sorted(map(repr, tk.scan_pr_refs(p))))
        self.assertEqual(sorted(x["number"] for x in meta.prs), [1, 2, 3])

    def test_no_prs_reads_as_an_empty_list(self):
        p = self._write(
            _json.dumps({"type": "user", "timestamp": "2026-06-20T00:00:00Z",
                         "cwd": "/r", "message": {"content":
                         "github.com/o/r/issues/3 is not a pull request"}}),
        )
        self.assertEqual(tk.load_session_meta(p).prs, [])


class TestPrCollector(unittest.TestCase):
    def test_sink_accumulates_across_calls(self):
        refs, sink = tk._pr_collector()
        sink("nothing here")
        self.assertEqual(refs, {})
        sink("https://github.com/greeun/probe/pull/4")
        sink("https://github.com/greeun/probe/pull/4 again")
        sink("https://gitlab.com/g/p/-/merge_requests/9")
        self.assertEqual(sorted(r["number"] for r in refs.values()), [4, 9])

    def test_fast_reject_does_not_drop_any_supported_url_shape(self):
        # The `in` short-circuit inside the sink must admit every shape the
        # regex accepts: /pull/, /pull-requests/ and /-/merge_requests/.
        shapes = ["https://github.com/o/r/pull/1",
                  "https://bitbucket.org/o/r/pull-requests/2",
                  "https://gitlab.com/o/r/-/merge_requests/3"]
        for url in shapes:
            with self.subTest(url=url):
                refs, sink = tk._pr_collector()
                sink(f"text {url} tail")
                self.assertEqual([r["number"] for r in refs.values()],
                                 [int(url.rsplit("/", 1)[1])])


if __name__ == "__main__":
    unittest.main()
