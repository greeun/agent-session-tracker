"""Exercise installed Codex hooks as subprocesses with isolated data homes."""
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


TRACKER = Path(__file__).resolve().parents[1] / "tracker.py"
SID = "019cb053-3333-4444-5555-666666666666"
OTHER = "019cb054-3333-4444-5555-666666666666"


class TestCodexHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ast hooks 한글 ")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.codex = self.root / "codex"
        self.ast = self.root / "ast"
        self.settings = self.codex / "hooks.json"
        self.env = {**os.environ, "CODEX_HOME": str(self.codex),
                    "CLAUDE_CONFIG_DIR": str(self.root / "claude"),
                    "AST_HOME": str(self.ast), "AST_INDEX_DIR": str(self.ast),
                    "AST_JOBS": "1"}

    def cli(self, *args, payload=None, command=None):
        return subprocess.run(command or [sys.executable, str(TRACKER), *args],
                              input=json.dumps(payload) if payload is not None else "",
                              capture_output=True, text=True, env=self.env,
                              cwd=self.root, timeout=20)

    def install(self):
        result = self.cli("install-hook", "--agent", "codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(self.settings.read_text())

    def hook(self, prompt, sid=SID, **fields):
        return self.cli("prompt-hook", "--agent", "codex", payload={
            "hook_event_name": "UserPromptSubmit", "session_id": sid,
            "cwd": str(self.root), "prompt": prompt, **fields})

    def state(self):
        path = self.ast / "state.json"
        return json.loads(path.read_text()) if path.exists() else {}

    def transcript(self, sid=SID):
        path = self.codex / "sessions" / "2026" / "11" / "16" / f"rollout-test-{sid}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        events = [
            {"type": "session_meta", "timestamp": "2026-11-16T00:00:00Z",
             "payload": {"id": sid, "cwd": str(self.root), "source": "cli"}},
            {"type": "response_item", "timestamp": "2026-11-16T00:01:00Z",
             "payload": {"type": "message", "role": "user", "content": [
                 {"type": "input_text", "text": "로컬 세션 테스트"}]}},
        ]
        path.write_text("".join(json.dumps(e) + "\n" for e in events))
        return path

    def test_installed_command_runs_without_ast_on_path_and_before_rollout(self):
        config = self.install()
        command = config["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
        result = self.cli(command=shlex.split(command), payload={
            "prompt": "done!", "session_id": SID, "cwd": str(self.root),
            "transcript_path": None})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["decision"], "block")
        self.assertIn(SID, self.state()["done"])
        self.assertNotIn(OTHER, self.state()["done"])

    def test_done_and_undone_are_blocked_and_idempotent(self):
        for prompt in ("done!", "done!", "undone!", "undone!"):
            result = self.hook(prompt)
            self.assertEqual(result.returncode, 0, result.stderr)
            body = json.loads(result.stdout)
            self.assertEqual(body["decision"], "block")
            self.assertIn("0 tokens", body["reason"])
            self.assertEqual(SID in self.state().get("done", {}), prompt == "done!")

    def test_explicit_target_resolves_prefix_without_marking_self(self):
        self.transcript(OTHER)
        result = self.hook(f"done! {OTHER[:8]}")
        self.assertIn("success", json.loads(result.stdout)["reason"])
        self.assertIn(OTHER, self.state()["done"])
        self.assertNotIn(SID, self.state()["done"])

    def test_unknown_or_ambiguous_explicit_target_changes_nothing(self):
        self.transcript(OTHER)
        self.transcript()
        for target in ("ffffffff", "019cb05"):
            result = self.hook(f"done! {target}")
            self.assertEqual(json.loads(result.stdout)["decision"], "block")
            self.assertIn("failed", json.loads(result.stdout)["reason"])
            self.assertFalse(self.state().get("done"))

    def test_explicit_working_target_guard_still_applies(self):
        import fcntl
        self.transcript(OTHER)
        lock = self.codex / "thread-writer-locks" / f"{OTHER}.lock"
        lock.parent.mkdir(parents=True)
        with lock.open("w") as held:
            fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.hook(f"done! {OTHER[:8]}")
        self.assertIn("refused", json.loads(result.stdout)["reason"])
        self.assertNotIn(OTHER, self.state().get("done", {}))

    def test_list_shortcuts_return_local_results_and_never_shell_out(self):
        self.transcript()
        for prompt in ("ast!", " /ast", "ast! --limit 1 --agent all"):
            result = self.hook(prompt)
            body = json.loads(result.stdout)
            self.assertEqual(body["decision"], "block")
            self.assertIn(SID[:8], body["reason"])
            self.assertIn("codex", body["reason"])
        for prompt in ("ast! --limit 0", "ast! rm abc", "ast! ; touch owned",
                       "ast! --cwd '", "ast! --help"):
            result = self.hook(prompt)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["decision"], "block")
        self.assertFalse((self.root / "owned").exists())
        self.assertFalse(self.state().get("done"))

    def test_normal_prompts_pass_through_and_record_working(self):
        for prompt in ("고쳐줘", "I am done!", "done! great work", "ast!\nrm abc"):
            result = self.hook(prompt)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
        result = self.cli("status-hook", "--agent", "codex", payload={
            "session_id": SID, "hook_event_name": "Stop"})
        self.assertEqual(result.returncode, 0, result.stderr)
        overlay = next(self.ast.glob("status.*.json"))
        self.assertEqual(json.loads(overlay.read_text())[SID]["state"], "idle")

    def test_status_events_and_subagents(self):
        for event, state in (("PermissionRequest", "waiting"), ("PostToolUse", "working"),
                             ("Interrupt", "idle"), ("Stop", "idle")):
            result = self.cli("status-hook", "--agent", "codex", payload={
                "session_id": SID, "hook_event_name": event})
            self.assertEqual(result.returncode, 0, result.stderr)
            overlay = next(self.ast.glob("status.*.json"))
            self.assertEqual(json.loads(overlay.read_text())[SID]["state"], state)
        self.cli("status-hook", "--agent", "codex", payload={
            "session_id": SID, "hook_event_name": "UserPromptSubmit"})
        self.cli("status-hook", "--agent", "codex", payload={
            "session_id": SID, "hook_event_name": "Stop", "agent_id": OTHER})
        self.assertEqual(json.loads(overlay.read_text())[SID]["state"], "working")
        self.cli("status-hook", "--agent", "codex", payload={
            "session_id": SID, "hook_event_name": "SessionEnd"})
        self.assertNotIn(SID, json.loads(overlay.read_text()))

    def test_blocked_shortcuts_do_not_record_working(self):
        for prompt in ("done!", "undone!", "ast!", "done! ffffffff"):
            self.hook(prompt)
        self.assertFalse(list(self.ast.glob("status.*.json")))

    def test_child_prompts_cannot_mark_parent_done_or_change_parent_status(self):
        for prompt in ("done!", "undone!", "ast!", "implement this"):
            result = self.hook(prompt, agent_id=OTHER)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
        self.assertFalse(self.state())
        self.assertFalse(list(self.ast.glob("status.*.json")))

    def test_malformed_payloads_are_noops(self):
        for payload in ([], None, 1, {"prompt": 7}, {"prompt": "done!", "session_id": []},
                        {"prompt": "done!", "session_id": SID, "transcript_path": []},
                        {"prompt": "done!", "session_id": SID, "cwd": {}}):
            result = self.cli("prompt-hook", "--agent", "codex", payload=payload)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, "")
        self.assertFalse(self.state().get("done"))

    def test_install_uninstall_preserve_mixed_foreign_handlers(self):
        self.settings.parent.mkdir(parents=True)
        original = {"description": "mine", "hooks": {"UserPromptSubmit": [{
            "matcher": "", "custom": "preserve", "hooks": [
                {"type": "command", "command": "foreign-hook"},
                {"type": "command", "command": "ast prompt-hook"}]}]}}
        self.settings.write_text(json.dumps(original))
        installed = self.install()
        self.assertNotIn("Notification", installed["hooks"])
        self.assertLessEqual(installed["hooks"]["SessionEnd"][0]["hooks"][0]["timeout"], 3)
        self.assertLessEqual(installed["hooks"]["Interrupt"][0]["hooks"][0]["timeout"], 3)
        before = self.settings.read_bytes()
        self.install()
        self.assertEqual(before, self.settings.read_bytes())
        result = self.cli("uninstall-hook", "--agent", "codex")
        self.assertEqual(result.returncode, 0, result.stderr)
        config = json.loads(self.settings.read_text())
        group = config["hooks"]["UserPromptSubmit"][0]
        self.assertEqual(group["custom"], "preserve")
        self.assertEqual(group["hooks"], [{"type": "command", "command": "foreign-hook"}])
        self.assertEqual(config["description"], "mine")
        for event, groups in config["hooks"].items():
            if event != "UserPromptSubmit":
                self.assertEqual(groups, [])

    def test_invalid_settings_are_not_overwritten(self):
        self.settings.parent.mkdir(parents=True)
        for content in ("[]", "null", '{"hooks": []}', '{"hooks":{"Stop":{}}}', "{oops"):
            self.settings.write_text(content)
            result = self.cli("install-hook", "--agent", "codex")
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(self.settings.read_text(), content)

    def test_explicit_settings_override_and_claude_default(self):
        custom = self.root / "custom.json"
        result = self.cli("install-hook", "--agent", "codex", "--settings", str(custom))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(custom.exists())
        self.assertFalse(self.settings.exists())
        result = self.cli("install-hook")
        self.assertEqual(result.returncode, 0, result.stderr)
        claude = json.loads((self.root / "claude" / "settings.json").read_text())
        self.assertIn("Notification", claude["hooks"])

    @unittest.skipUnless(os.environ.get("AST_TEST_CODEX_RUNTIME") == "1"
                         and shutil.which("codex"),
                         "set AST_TEST_CODEX_RUNTIME=1 to verify with a local Codex CLI")
    def test_real_codex_blocks_commands_before_any_model_usage(self):
        # No user credentials, real settings, or model endpoint. The flag is
        # limited to this temporary config containing only our vetted hooks.
        self.install()
        config = '\n'.join([
            'model = "ast-hook-test"', 'model_provider = "ast_hook_test"',
            '[model_providers.ast_hook_test]', 'name = "Isolated hook test"',
            'base_url = "http://127.0.0.1:1/v1"', 'wire_api = "responses"',
            'env_key = "AST_CODEX_TEST_KEY"', '[features]', 'hooks = true', '',
        ])
        (self.codex / "config.toml").write_text(config)
        self.env["AST_CODEX_TEST_KEY"] = "local-test-placeholder"
        for prompt in ("done!", "undone!", "ast!", "/ast"):
            command = [shutil.which("codex"), "exec", "--skip-git-repo-check",
                       "--sandbox", "read-only", "--dangerously-bypass-hook-trust",
                       "--json", "-C", str(self.root), prompt]
            result = self.cli(command=command)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            events = [json.loads(line) for line in result.stdout.splitlines()]
            completed = [e for e in events if e["type"] == "turn.completed"]
            self.assertEqual(len(completed), 1, result.stdout)
            self.assertEqual(completed[0]["usage"]["input_tokens"], 0)
            self.assertEqual(completed[0]["usage"]["output_tokens"], 0)
            self.assertNotIn("clamping", result.stdout)
            self.assertNotIn("Reconnecting", result.stdout)
            if prompt == "done!":
                sid = next(e["thread_id"] for e in events if e["type"] == "thread.started")
                self.assertIn(sid, self.state()["done"])


if __name__ == "__main__":
    unittest.main()
