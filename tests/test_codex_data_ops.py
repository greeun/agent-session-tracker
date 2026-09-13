"""Codex data operations: in-place relocate, multi-agent backup/restore,
subagent linking and the rollout file fingerprint.

These cover what the codex adapter could not do when it shipped: relocate and
backup were refused outright, and a codex session reaching cmd_backup crashed
it (`relative_to(PROJECTS_DIR)` on a ~/.codex path). Fixtures mirror the real
rollout format — session_meta first, then response_item/turn_context/
world_state records (verified against codex-cli 0.151 and rollouts written by
0.104 through 0.153)."""
import argparse
import importlib.util
import io
import json
import pathlib
import sys
import tarfile
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

_REPO = pathlib.Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("tracker_codex_ops", _REPO / "tracker.py")
tk = importlib.util.module_from_spec(_spec)
sys.modules["tracker_codex_ops"] = tk
_spec.loader.exec_module(tk)

SID = "019cb053-b194-7b22-ae2f-cead6503f03a"
SUB = "019fc7d7-9fde-7bd1-84db-210cc4ef8008"
OTHER = "019de2b1-deef-74d1-ba0c-228e126e2b67"
CWD = "/repo/codex-app"
CLAUDE_SID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _line(ts, etype, payload, ordinal=0):
    return json.dumps({"timestamp": ts, "ordinal": ordinal, "type": etype,
                       "payload": payload}, ensure_ascii=False)


def _rollout(sid, cwd, *, source="cli", extra_meta=None, mention_cwd=True):
    """A rollout carrying the cwd in every place codex records it."""
    meta = {"session_id": sid, "id": sid, "timestamp": "2026-03-02T20:53:20.917Z",
            "cwd": cwd, "originator": "codex_cli_rs", "cli_version": "0.151.0",
            "source": source, "model_provider": "openai"}
    meta.update(extra_meta or {})
    lines = [
        _line("2026-03-02T20:53:32.0Z", "session_meta", meta),
        _line("2026-03-02T20:53:32.1Z", "turn_context",
              {"turn_id": "t1", "cwd": cwd, "workspace_roots": [cwd, "/elsewhere"],
               "model": "gpt-5"}),
        _line("2026-03-02T20:53:32.2Z", "world_state",
              {"full": True, "state": {"environments": {"environments": {
                  "local": {"cwd": cwd, "status": "available", "shell": "zsh"}}}}}),
        _line("2026-03-02T20:53:40.0Z", "response_item",
              {"type": "message", "role": "user",
               "content": [{"type": "input_text",
                            "text": (f"build it under {cwd}" if mention_cwd
                                     else "build it")}]}),
        _line("2026-03-02T20:53:45.0Z", "response_item",
              {"type": "message", "role": "assistant",
               "content": [{"type": "output_text", "text": "On it."}]}),
    ]
    return "\n".join(lines) + "\n"


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        self._orig = {k: getattr(tk, k) for k in (
            "PROJECTS_DIR", "CONFIG_DIR", "CACHE_DIR", "CACHE_PATH", "STATE_PATH",
            "JOBS_DIR", "DAEMON_DIR", "SESSIONS_REGISTRY_DIR",
            "CODEX_SESSIONS_DIR", "CODEX_LOCKS_DIR")}
        tk.CONFIG_DIR = self.root / "claude"
        tk.PROJECTS_DIR = tk.CONFIG_DIR / "projects"
        tk.CACHE_DIR = self.root / "cache"
        tk.CACHE_PATH = tk.CACHE_DIR / "index.json"
        tk.STATE_PATH = tk.CACHE_DIR / "state.json"
        tk.JOBS_DIR = tk.CONFIG_DIR / "jobs"
        tk.DAEMON_DIR = tk.CONFIG_DIR / "daemon"
        tk.SESSIONS_REGISTRY_DIR = tk.CONFIG_DIR / "sessions"
        tk.CODEX_SESSIONS_DIR = self.root / "codex" / "sessions"
        tk.CODEX_LOCKS_DIR = self.root / "codex" / "thread-writer-locks"
        self.path = self.write_rollout(SID, CWD)

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(tk, k, v)
        self._tmp.cleanup()

    def write_rollout(self, sid, cwd, *, day="2026/03/03", **kw):
        d = tk.CODEX_SESSIONS_DIR / day
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"rollout-2026-03-03T05-53-20-{sid}.jsonl"
        p.write_text(_rollout(sid, cwd, **kw), encoding="utf-8")
        return p

    def write_claude(self, sid=CLAUDE_SID, cwd="/repo/claude-app"):
        d = tk.PROJECTS_DIR / tk.encode_cwd(cwd)
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"{sid}.jsonl"
        rows = [
            {"type": "user", "timestamp": "2026-03-02T20:00:00.000Z", "cwd": cwd,
             "message": {"content": "ship the fix"}},
            {"type": "assistant", "timestamp": "2026-03-02T20:00:05.000Z", "cwd": cwd,
             "message": {"content": [{"type": "text", "text": "done"}]}},
        ]
        p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
        return p

    def run_cmd(self, fn, **kw):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            rc = fn(argparse.Namespace(**kw))
        return rc, out.getvalue(), err.getvalue()

    def events(self, path):
        return [json.loads(ln) for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()]


class TestRelocate(_Base):
    def _relocate(self, new_cwd, **kw):
        target = tk.find_session(SID[:8])
        return tk.relocate_session(target, new_cwd, **kw)

    def test_rollout_stays_put_and_every_cwd_moves(self):
        dest = self.root / "moved"
        dest.mkdir()
        res = self._relocate(str(dest))
        self.assertTrue(res.ok, res.message)
        self.assertEqual(res.new_path, self.path, "codex rollouts never move")
        self.assertTrue(self.path.exists())
        evts = self.events(self.path)
        self.assertEqual(evts[0]["payload"]["cwd"], str(dest))
        self.assertEqual(evts[1]["payload"]["cwd"], str(dest))
        self.assertEqual(
            evts[2]["payload"]["state"]["environments"]["environments"]["local"]["cwd"],
            str(dest), "the nested world_state snapshot moves too")

    def test_workspace_roots_swap_only_the_old_path(self):
        dest = self.root / "moved"
        dest.mkdir()
        self._relocate(str(dest))
        roots = self.events(self.path)[1]["payload"]["workspace_roots"]
        self.assertEqual(roots, [str(dest), "/elsewhere"])

    def test_message_text_is_left_alone(self):
        dest = self.root / "moved"
        dest.mkdir()
        self._relocate(str(dest))
        user = self.events(self.path)[3]["payload"]["content"][0]["text"]
        self.assertIn(CWD, user, "a path inside a prompt is content, not metadata")

    def test_session_reads_back_under_the_new_cwd(self):
        dest = self.root / "moved"
        dest.mkdir()
        self._relocate(str(dest))
        self.assertEqual(tk.find_session(SID[:8]).cwd, str(dest))

    def test_rewrite_count_and_in_place_note(self):
        dest = self.root / "moved"
        dest.mkdir()
        res = self._relocate(str(dest))
        self.assertEqual(res.rewritten, 3, "session_meta + turn_context + world_state")
        self.assertIn("transcript kept in place", res.message)

    def test_keep_original_is_refused_rather_than_ignored(self):
        """사본을 놓을 새 위치가 없으므로, 진행하면 보존하라고 지정한 바로 그
        파일을 재작성하게 된다. 아무 것도 바꾸지 않고 거부한다."""
        dest = self.root / "moved"
        dest.mkdir()
        res = self._relocate(str(dest), keep_original=True)
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "keeporiginal")
        self.assertEqual(self.events(self.path)[0]["payload"]["cwd"], CWD)

    def test_cli_reports_the_keep_original_refusal(self):
        dest = self.root / "moved"
        dest.mkdir()
        rc, _, err = self.run_cmd(tk.cmd_relocate, session_id=SID[:8],
                                  new_cwd=str(dest), keep_original=True,
                                  force=False, dry_run=False, yes=True)
        self.assertEqual(rc, 1)
        self.assertIn("--keep-original cannot be honored", err)

    def test_missing_target_still_refused_without_force(self):
        res = self._relocate(str(self.root / "nope"))
        self.assertFalse(res.ok)
        self.assertEqual(res.reason, "nodir")
        self.assertEqual(self.events(self.path)[0]["payload"]["cwd"], CWD)

    def test_same_cwd_is_a_no_op(self):
        """The existing-folder check runs first, so this needs a live cwd."""
        here = self.root / "live"
        here.mkdir()
        self.path = self.write_rollout(SID, str(here))
        res = self._relocate(str(here))
        self.assertEqual(res.reason, "samecwd")

    def test_cli_preview_omits_the_move_arrow(self):
        dest = self.root / "moved"
        dest.mkdir()
        rc, out, _ = self.run_cmd(tk.cmd_relocate, session_id=SID[:8],
                                  new_cwd=str(dest), keep_original=False,
                                  force=False, dry_run=True, yes=True)
        self.assertEqual(rc, 0)
        self.assertIn("rewrite in place", out)
        self.assertNotIn("     →    ", out)

    def test_claude_relocate_still_moves_its_file(self):
        """The shared core must not regress the cwd-keyed claude layout."""
        cpath = self.write_claude()
        dest = self.root / "claude-moved"
        dest.mkdir()
        target = tk.find_session(CLAUDE_SID[:8])
        res = tk.relocate_session(target, str(dest))
        self.assertTrue(res.ok, res.message)
        self.assertEqual(res.new_path,
                         tk.PROJECTS_DIR / tk.encode_cwd(str(dest)) / cpath.name)
        self.assertTrue(res.new_path.exists())
        self.assertFalse(cpath.exists())


class TestBackupRestore(_Base):
    def _backup(self, **kw):
        args = dict(days=None, before="2099-01-01", cwd=None,
                    out=str(self.root / "bk.tar.gz"), delete=False, force=False,
                    dry_run=False, yes=True)
        args.update(kw)
        return self.run_cmd(tk.cmd_backup, **args)

    def test_codex_session_no_longer_crashes_backup(self):
        rc, out, _ = self._backup()
        self.assertEqual(rc, 0)
        self.assertIn("✓ Wrote 1/1", out)

    def test_members_are_grouped_by_agent(self):
        self.write_claude()
        self._backup()
        with tarfile.open(self.root / "bk.tar.gz") as tar:
            names = sorted(m.name for m in tar.getmembers())
        self.assertIn("manifest.json", names)
        self.assertTrue(any(n.startswith("codex/2026/03/03/rollout-") for n in names), names)
        self.assertTrue(any(n.startswith("projects/") for n in names), names)

    def test_manifest_records_agent_and_member(self):
        self._backup()
        with tarfile.open(self.root / "bk.tar.gz") as tar:
            mf = json.loads(tar.extractfile("manifest.json").read().decode("utf-8"))
        entry = mf["sessions"][0]
        self.assertEqual(entry["agent"], "codex")
        self.assertEqual(entry["arcname"], f"codex/{entry['relpath']}")

    def test_restore_puts_each_agent_back_under_its_own_root(self):
        self.write_claude()
        self._backup()
        for p in tk.CODEX_SESSIONS_DIR.rglob("*.jsonl"):
            p.unlink()
        for p in tk.PROJECTS_DIR.rglob("*.jsonl"):
            p.unlink()
        rc, out, _ = self.run_cmd(tk.cmd_restore, archive=str(self.root / "bk.tar.gz"),
                                  cwd=None, on_conflict="skip", dry_run=False, yes=True)
        self.assertEqual(rc, 0)
        self.assertIn("✓ Restored 2 file(s)", out)
        self.assertTrue(self.path.exists())
        self.assertEqual(len(list(tk.PROJECTS_DIR.rglob("*.jsonl"))), 1)

    def test_restore_round_trip_keeps_the_session_readable(self):
        self._backup()
        self.path.unlink()
        self.run_cmd(tk.cmd_restore, archive=str(self.root / "bk.tar.gz"), cwd=None,
                     on_conflict="skip", dry_run=False, yes=True)
        meta = tk.find_session(SID[:8])
        self.assertIsNotNone(meta)
        self.assertEqual(meta.agent, "codex")
        self.assertEqual(meta.cwd, CWD)

    def test_cwd_filter_uses_the_manifest_of_either_agent(self):
        self.write_claude()
        self._backup()
        rc, out, _ = self.run_cmd(tk.cmd_restore, archive=str(self.root / "bk.tar.gz"),
                                  cwd="/repo/codex", on_conflict="skip",
                                  dry_run=True, yes=True)
        self.assertEqual(rc, 0)
        self.assertIn("Files:   1", out)

    def test_pre_multi_agent_archive_still_restores(self):
        """Archives written by v1.x carry only `projects/` + `relpath`."""
        cpath = self.write_claude()
        rel = str(cpath.relative_to(tk.PROJECTS_DIR))
        legacy = self.root / "legacy.tar.gz"
        manifest = {"created_at": "2026-01-01T00:00:00+00:00",
                    "cutoff": "2026-01-01T00:00:00+00:00", "count": 1,
                    "sessions": [{"session_id": CLAUDE_SID, "cwd": "/repo/claude-app",
                                  "first_ts": None, "last_ts": None, "msg_count": 2,
                                  "first_user_msg": "ship the fix", "relpath": rel}]}
        with tarfile.open(legacy, "w:gz") as tar:
            blob = json.dumps(manifest).encode("utf-8")
            info = tarfile.TarInfo("manifest.json")
            info.size = len(blob)
            tar.addfile(info, io.BytesIO(blob))
            tar.add(str(cpath), arcname=f"projects/{rel}")
        cpath.unlink()
        rc, out, _ = self.run_cmd(tk.cmd_restore, archive=str(legacy), cwd=None,
                                  on_conflict="skip", dry_run=False, yes=True)
        self.assertEqual(rc, 0)
        self.assertTrue(cpath.exists())

    def test_traversal_member_is_refused_for_codex_too(self):
        evil = self.root / "evil.tar.gz"
        payload = self.root / "payload.jsonl"
        payload.write_text("{}\n", encoding="utf-8")
        with tarfile.open(evil, "w:gz") as tar:
            tar.add(str(payload), arcname="codex/../../escaped.jsonl")
        rc, out, err = self.run_cmd(tk.cmd_restore, archive=str(evil), cwd=None,
                                    on_conflict="skip", dry_run=False, yes=True)
        self.assertEqual(rc, 1)
        self.assertIn("unsafe", err + out)
        self.assertFalse((self.root / "codex").parent.joinpath("escaped.jsonl").exists())


class TestSubagents(_Base):
    def test_spawned_thread_links_to_its_parent(self):
        self.write_rollout(SUB, CWD, source={"subagent": {"other": "guardian"}},
                           extra_meta={"parent_thread_id": SID,
                                       "thread_source": "subagent"},
                           day="2026/03/04")
        subs = tk.list_subagents(self.path)
        self.assertEqual(len(subs), 1)
        path, meta = subs[0]
        self.assertIn(SUB, path.name)
        self.assertEqual(meta["agentType"], "guardian")

    def test_unrelated_thread_is_not_a_subagent(self):
        self.write_rollout(OTHER, CWD, day="2026/03/05")
        self.assertEqual(tk.list_subagents(self.path), [])

    def test_cmd_subagents_reports_the_child(self):
        self.write_rollout(SUB, CWD, source={"subagent": {"other": "guardian"}},
                           extra_meta={"parent_thread_id": SID,
                                       "thread_source": "guardian_review"},
                           day="2026/03/04")
        rc, out, _ = self.run_cmd(tk.cmd_subagents, session_id=SID[:8])
        self.assertEqual(rc, 0)
        self.assertIn("Subagents: 1", out)
        self.assertIn("type: guardian", out)
        self.assertIn("msgs: 2", out)

    def test_subagent_type_falls_back_to_thread_source(self):
        self.assertEqual(tk._codex_subagent_type({"thread_source": "subagent"}),
                         "subagent")
        self.assertEqual(tk._codex_subagent_type({}), "subagent")


class TestFingerprint(_Base):
    def _write_tool_calls(self):
        rows = [
            _line("2026-03-02T20:53:20.0Z", "session_meta",
                  {"session_id": OTHER, "id": OTHER, "cwd": CWD, "source": "cli"}),
            _line("2026-03-02T20:53:30.0Z", "response_item",
                  {"type": "custom_tool_call", "name": "apply_patch",
                   "input": "*** Begin Patch\n*** Update File: /repo/codex-app/package.json\n@@\n-a\n+b\n"}),
            _line("2026-03-02T20:53:31.0Z", "response_item",
                  {"type": "function_call", "name": "view_image",
                   "arguments": json.dumps({"path": "/repo/codex-app/docs/hero.png"})}),
            _line("2026-03-02T20:53:32.0Z", "response_item",
                  {"type": "function_call", "name": "exec_command",
                   "arguments": json.dumps({"cmd": "sed -n '1,40p' /repo/codex-app/src/main.ts",
                                            "workdir": CWD})}),
        ]
        d = tk.CODEX_SESSIONS_DIR / "2026/03/06"
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"rollout-2026-03-06T05-53-20-{OTHER}.jsonl"
        p.write_text("\n".join(rows) + "\n", encoding="utf-8")
        return p

    def test_paths_come_from_patches_images_and_commands(self):
        p = self._write_tool_calls()
        self.assertEqual(tk._session_file_fingerprint(p),
                         {"package.json", "hero.png", "main.ts"})

    def test_plain_conversation_has_no_fingerprint(self):
        self.assertEqual(tk._session_file_fingerprint(self.path), set())

    def test_limit_caps_the_set(self):
        p = self._write_tool_calls()
        self.assertEqual(len(tk._session_file_fingerprint(p, limit=2)), 2)

    def test_missing_file_is_empty_not_an_error(self):
        self.assertEqual(
            tk._session_file_fingerprint(tk.CODEX_SESSIONS_DIR / "gone.jsonl"), set())


if __name__ == "__main__":
    unittest.main()
