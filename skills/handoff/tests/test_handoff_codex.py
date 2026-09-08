from __future__ import annotations

from contextlib import ExitStack
import base64
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import handoff_codex as codex
import handoff_tui as tui
sys.path.pop(0)


def entry(owner="Codex", done=False):
    mark = "x" if done else " "
    return (f"## Task (owner: {owner})\n\nState:\n- [x] In progress\n"
            f"- [{mark}] Completed\n\nSteps:\n- [{mark}] Verify.\n\nStatus: Recorded.\n")


class FooterTests(unittest.TestCase):
    def test_updates_after_same_size_checkbox_edit_and_labels_stale_data(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HANDOFF.md"
            path.write_text(entry(), encoding="utf-8")
            watcher = tui.Watcher(path)
            watcher.poll()
            self.assertIn("0/1 tasks", codex.footer(watcher))
            path.write_text(entry(done=True), encoding="utf-8")
            watcher.poll()
            self.assertIn("1/1 tasks", codex.footer(watcher))
            self.assertIn("fg=green", codex.footer(watcher))
            path.unlink()
            watcher.poll()
            self.assertIn("STALE", codex.footer(watcher))

    def test_terminal_controls_and_tmux_formats_in_owner_are_inert(self):
        watcher = tui.Watcher(Path("unused"))
        watcher.snapshot = tui.parse_snapshot(entry("#[fg=red] #{pane_id} \x1b[2J"))
        row = codex.footer(watcher, color=False)
        self.assertIn("##[fg=red] ##{pane_id}", row)
        self.assertNotIn("\x1b", row)
        watcher.snapshot = tui.parse_snapshot(entry("#(touch /tmp/unwanted)"))
        self.assertIn("##(touch /tmp/unwanted", codex.footer(watcher))

    def test_missing_and_empty_ledger_show_a_waiting_bar(self):
        with tempfile.TemporaryDirectory() as directory:
            watcher = tui.Watcher(Path(directory) / "HANDOFF.md")
            watcher.poll()
            self.assertIn("waiting", codex.footer(watcher))
            watcher.path.write_text("# Handoff\n", encoding="utf-8")
            watcher.poll()
            self.assertIn("no tracked tasks", codex.footer(watcher))


class SessionTests(unittest.TestCase):
    def test_private_server_forwards_literal_arguments_and_disables_prefix(self):
        with patch.dict(os.environ, {"TMUX": "outer", "TMUX_PANE": "%8"}):
            session = codex.CodexSession("/usr/bin/tmux", Path("/tmp/private/s"))
        self.assertNotIn("TMUX", session.environment)
        self.assertNotIn("TMUX_PANE", session.environment)
        arguments = ["resume", "--last", "a prompt; $(touch sentinel) `false`", ";", "--model", "example"]
        with patch.object(session, "call") as call:
            session.start("/some path/codex", arguments, Path("/repo with space"), "bar")
        command = call.call_args.args
        cwd, forwarded = json.loads(base64.b64decode(command[-1]))
        self.assertEqual(forwarded, ["/some path/codex", *arguments])
        self.assertEqual(cwd, "/repo with space")
        call.assert_any_call("set-option", "-t", "handoff", "prefix", "None")
        call.assert_any_call("set-option", "-t", "handoff", "status-format[0]", "bar")
        self.assertEqual(session.command[2:4], ["-S", "/tmp/private/s"])
        self.assertIn(os.devnull, session.command)

    def test_exit_status_is_codex_status_not_attach_status(self):
        session = codex.CodexSession("tmux", Path("s"))
        with patch.object(session, "call", side_effect=["0:", "1:7", "1:"]):
            self.assertIsNone(session.exit_status())
            self.assertEqual(session.exit_status(), 7)
            self.assertEqual(session.exit_status(), 1)

    def test_cleanup_waits_for_attached_client(self):
        session = codex.CodexSession("tmux", Path("private"))
        session.client = MagicMock()
        with patch.object(session, "call") as call:
            session.close()
        call.assert_called_once_with("kill-server", check=False)
        session.client.wait.assert_called_once_with(timeout=3)


class RunTests(unittest.TestCase):
    def context(self):
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(patch.object(sys.stdin, "isatty", return_value=True))
        stack.enter_context(patch.object(sys.stdout, "isatty", return_value=True))
        stack.enter_context(patch.object(codex.shutil, "which", side_effect=lambda name: "/bin/" + name))
        session = stack.enter_context(patch.object(codex, "CodexSession")).return_value
        return stack, session

    @unittest.skipIf(os.name == "nt", "Codex launch mode requires POSIX tmux")
    def test_failed_start_cleans_up(self):
        _, session = self.context()
        session.start.side_effect = subprocess.CalledProcessError(1, "tmux", stderr="socket denied")
        with tempfile.TemporaryDirectory() as directory:
            watcher = tui.Watcher(Path(directory) / "HANDOFF.md")
            self.assertEqual(codex.run_codex(watcher, Path(directory), [], 1), 1)
        session.close.assert_called_once()
        session.attach.assert_not_called()

    @unittest.skipIf(os.name == "nt", "Codex launch mode requires POSIX tmux")
    def test_refreshes_without_input_then_returns_child_failure(self):
        stack, session = self.context()
        session.exit_status.side_effect = [None, None, 7]
        session.client.poll.return_value = None
        stack.enter_context(patch.object(codex.time, "monotonic", side_effect=[0, 2, 2, 3, 3]))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HANDOFF.md"
            path.write_text(entry(), encoding="utf-8")
            stack.enter_context(patch.object(codex.time, "sleep", side_effect=lambda _: path.write_text(entry(done=True), encoding="utf-8")))
            result = codex.run_codex(tui.Watcher(path), Path(directory), ["resume", "--last"], 1)
        self.assertEqual(result, 7)
        self.assertIn("1/1 tasks", session.call.call_args.args[-1])
        session.close.assert_called_once()

    def test_piped_invocation_has_actionable_error(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "handoff_tui.py"), "--codex"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertIn("WSL" if os.name == "nt" else "interactive terminal", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_viewer_forwards_codex_args_after_options(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(codex, "run_codex", return_value=0) as run:
                self.assertEqual(tui.main(["--root", directory, "--interval", "2", "--no-color",
                                           "--codex", "resume", "--last", "--model", "example"]), 0)
            self.assertEqual(run.call_args.args[1:], (Path(directory).resolve(),
                             ["resume", "--last", "--model", "example"], 2.0))
            self.assertEqual(run.call_args.kwargs, {"color": False})

    def test_conflicting_modes_fail_before_launch(self):
        for mode in ("--bar", "--once"):
            with self.subTest(mode=mode), self.assertRaises(SystemExit) as error:
                tui.main([mode, "--codex"])
            self.assertEqual(error.exception.code, 2)


@unittest.skipIf(os.name == "nt" or not shutil.which("tmux"), "needs POSIX tmux")
class TmuxIntegrationTests(unittest.TestCase):
    def test_real_pane_input_arguments_format_escaping_and_exit(self):
        with tempfile.TemporaryDirectory(prefix="hc-test-") as directory:
            base = Path(directory)
            session = codex.CodexSession(shutil.which("tmux"), base / "s")
            probe = subprocess.run(session.command + ["new-session", "-d", "-s", "probe"],
                                   env=session.environment, capture_output=True, text=True, encoding="utf-8")
            if probe.returncode:
                if "Operation not permitted" in probe.stderr or "Permission denied" in probe.stderr:
                    self.skipTest("environment disallows tmux sockets: " + probe.stderr.strip())
                self.fail(probe.stderr)
            session.close()
            script = base / "fake codex.py"
            report = base / "received.json"
            gate = base / "exit"
            script.write_text(
                "import json, os, pathlib, sys, time\n"
                "print('READY', flush=True)\n"
                "line = input()\n"
                "pathlib.Path(sys.argv[1]).write_text(json.dumps([os.getcwd(), sys.argv[3:], line]))\n"
                "while not pathlib.Path(sys.argv[2]).exists(): time.sleep(0.02)\n"
                "sys.exit(7)\n", encoding="utf-8")
            arguments = ["a prompt; $(false) `false`", ";", "--model", "example"]
            watcher = tui.Watcher(base / "HANDOFF.md")
            watcher.path.write_text(entry("#[fg=red] #{pane_id}"), encoding="utf-8")
            watcher.poll()
            try:
                session.start(sys.executable, [str(script), str(report), str(gate), *arguments],
                              base, codex.footer(watcher))
                session.call("send-keys", "-t", "handoff:0.0", "-l", "typed text")
                session.call("send-keys", "-t", "handoff:0.0", "Enter")
                deadline = time.monotonic() + 5
                while not report.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                cwd, received, line = json.loads(report.read_text(encoding="utf-8"))
                self.assertEqual(Path(cwd).resolve(), base.resolve())
                self.assertEqual(received, arguments)
                self.assertEqual(line, "typed text")
                initial = session.call("show-options", "-v", "-t", "handoff", "status-format[0]")
                self.assertIn("0/1 tasks", initial)
                expanded = session.call("display-message", "-p", "-t", "handoff:0.0", initial)
                self.assertIn("#[fg=red] #{pane_id}", expanded)
                watcher.path.write_text(entry(done=True), encoding="utf-8")
                watcher.poll()
                session.call("set-option", "-t", "handoff", "status-format[0]", codex.footer(watcher))
                self.assertIn("1/1 tasks", session.call("show-options", "-v", "-t", "handoff", "status-format[0]"))
                gate.touch()
                deadline = time.monotonic() + 5
                while session.exit_status() is None and time.monotonic() < deadline:
                    time.sleep(0.02)
                # A bare status mismatch cannot tell an unreported
                # pane_dead_status from a child that really exited 1, and the
                # two need opposite fixes. Report what tmux actually said.
                raw = session.call("display-message", "-p", "-t", "handoff:0.0",
                                   "#{pane_dead}:#{pane_dead_status}", check=False)
                pane = session.call("capture-pane", "-p", "-t", "handoff:0.0", check=False)
                version = subprocess.run([shutil.which("tmux"), "-V"], capture_output=True,
                                         text=True, encoding="utf-8").stdout.strip()
                detail = f"tmux={version!r} raw_state={raw!r} pane={pane!r}"
                self.assertEqual(session.exit_status(), 7, detail)
            finally:
                session.close()
            self.assertFalse(session.call("list-sessions", check=False))


if __name__ == "__main__":
    unittest.main()
