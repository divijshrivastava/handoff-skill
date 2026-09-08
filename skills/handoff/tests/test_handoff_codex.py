from __future__ import annotations

from contextlib import ExitStack
import base64
import json
import os
from pathlib import Path
import shlex
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

    def test_the_key_hint_appears_only_when_a_key_is_bound(self):
        watcher = tui.Watcher(Path("unused"))
        watcher.snapshot = tui.parse_snapshot(entry())
        self.assertNotIn("open", codex.footer(watcher))
        self.assertIn("\u00b7 ^G open", codex.footer(watcher, key="C-g"))
        self.assertIn("\u00b7 M-h open", codex.footer(watcher, key="M-h"))
        self.assertIn("\u00b7 F2 open", codex.footer(watcher, key="F2"))

    def test_a_ledger_owner_cannot_forge_the_hint_into_a_tmux_format(self):
        # The hint is appended after cleaning, so owner text stays escaped and
        # cannot close the format the hint is written in.
        watcher = tui.Watcher(Path("unused"))
        watcher.snapshot = tui.parse_snapshot(entry("#[fg=red]"))
        row = codex.footer(watcher, key="C-g")
        self.assertIn("##[fg=red]", row)
        self.assertTrue(row.endswith("\u00b7 ^G open"))

    def test_missing_and_empty_ledger_show_a_waiting_bar(self):
        with tempfile.TemporaryDirectory() as directory:
            watcher = tui.Watcher(Path(directory) / "HANDOFF.md")
            watcher.poll()
            self.assertIn("waiting", codex.footer(watcher))
            watcher.path.write_text("# Handoff\n", encoding="utf-8")
            watcher.poll()
            self.assertIn("no tracked tasks", codex.footer(watcher))


class ViewerKeyTests(unittest.TestCase):
    def test_the_key_is_configurable_and_can_be_given_back_to_codex(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("HANDOFF_VIEWER_KEY", None)
            self.assertEqual(codex.viewer_key(), "C-g")
        for value, expected in (("M-h", "M-h"), (" F2 ", "F2"),
                                ("none", None), ("NONE", None), ("", None), ("  ", None)):
            with self.subTest(value=value), patch.dict(os.environ, {"HANDOFF_VIEWER_KEY": value}):
                self.assertEqual(codex.viewer_key(), expected)

    @unittest.skipIf(os.name == "nt", "the popup command is quoted for a POSIX shell")
    def test_the_popup_command_survives_a_shell_and_spaces_in_the_path(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "a repo" / "HANDOFF.md"
            ledger.parent.mkdir()
            ledger.write_text(entry(), encoding="utf-8")
            command = codex.viewer_command(ledger, 2.0, read_only=False)
            self.assertIn(shlex.quote(str(ledger)), command)
            self.assertIn("--interval 2.0", command)
            self.assertNotIn("--read-only", command)
            # Running it proves the quoting produces one runnable command line;
            # --once keeps the snapshot on stdout instead of opening curses.
            result = subprocess.run(["sh", "-c", command + " --once"],
                                    capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("0/1 completed", result.stdout)
            self.assertIn("--read-only", codex.viewer_command(ledger, 1.0, read_only=True))


class SessionTests(unittest.TestCase):
    def test_private_server_forwards_literal_arguments_and_disables_prefix(self):
        with patch.dict(os.environ, {"TMUX": "outer", "TMUX_PANE": "%8"}):
            session = codex.AgentSession("/usr/bin/tmux", Path("/tmp/private/s"))
        self.assertNotIn("TMUX", session.environment)
        self.assertNotIn("TMUX_PANE", session.environment)
        arguments = ["resume", "--last", "a prompt; $(touch sentinel) `false`", ";", "--model", "example"]
        with patch.object(session, "call") as call:
            session.start("/some path/codex", arguments, Path("/repo with space"), "bar")
        command = call.call_args.args
        cwd, forwarded, status = json.loads(base64.b64decode(command[-1]))
        self.assertEqual(forwarded, ["/some path/codex", *arguments])
        # Compare as paths: Windows renders this as a backslash path.
        self.assertEqual(Path(cwd), Path("/repo with space"))
        self.assertEqual(Path(status), session.status_file)
        call.assert_any_call("set-option", "-t", "handoff", "prefix", "None")
        call.assert_any_call("set-option", "-t", "handoff", "status-format[0]", "bar")
        self.assertEqual(session.command[2], "-S")
        self.assertEqual(Path(session.command[3]), Path("/tmp/private/s"))
        self.assertIn(os.devnull, session.command)

    def test_exit_status_is_codex_status_not_attach_status(self):
        session = codex.AgentSession("tmux", Path("s"))
        with patch.object(session, "call", side_effect=["0:", "1:7", "1:"]):
            self.assertIsNone(session.exit_status())
            self.assertEqual(session.exit_status(), 7)
            self.assertEqual(session.exit_status(), 1)

    def test_an_empty_pane_dead_status_reads_the_recorded_status(self):
        # tmux 3.4 reports a dead pane as '1:' with no status. Trusting the
        # format alone reported every Codex run as exit 1 on that version.
        with tempfile.TemporaryDirectory() as directory:
            session = codex.AgentSession("tmux", Path(directory) / "s")
            with patch.object(session, "call", return_value="1:"):
                self.assertEqual(session.exit_status(), 1)
                session.status_file.write_text("7", encoding="utf-8")
                self.assertEqual(session.exit_status(), 7)
                session.status_file.write_text("not a number", encoding="utf-8")
                self.assertEqual(session.exit_status(), 1)

    def test_cleanup_waits_for_attached_client(self):
        session = codex.AgentSession("tmux", Path("private"))
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
        session = stack.enter_context(patch.object(codex, "AgentSession")).return_value
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

    @unittest.skipIf(os.name == "nt", "Codex launch mode requires POSIX tmux")
    def test_the_key_opens_the_ledger_the_bar_is_reporting(self):
        stack, session = self.context()
        stack.enter_context(patch.dict(os.environ, {"HANDOFF_VIEWER_KEY": "C-g"}))
        session.exit_status.side_effect = [0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HANDOFF.md"
            path.write_text(entry(), encoding="utf-8")
            self.assertEqual(codex.run_codex(tui.Watcher(path), Path(directory), [], 2), 0)
        key, command, cwd = session.bind_viewer.call_args.args
        self.assertEqual(key, "C-g")
        self.assertIn(shlex.quote(str(path)), command)
        self.assertIn("--interval 2", command)
        self.assertEqual(Path(cwd), Path(directory))
        self.assertIn("^G open", session.start.call_args.args[-1])

    @unittest.skipIf(os.name == "nt", "Codex launch mode requires POSIX tmux")
    def test_a_rejected_binding_drops_the_hint_rather_than_the_session(self):
        # A tmux without display-popup would otherwise leave the bar advertising
        # a key that does nothing, and must not stop Codex from running.
        stack, session = self.context()
        stack.enter_context(patch.dict(os.environ, {"HANDOFF_VIEWER_KEY": "C-g"}))
        session.bind_viewer.return_value = False
        session.exit_status.side_effect = [7]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HANDOFF.md"
            path.write_text(entry(), encoding="utf-8")
            self.assertEqual(codex.run_codex(tui.Watcher(path), Path(directory), [], 1), 7)
        self.assertIn("^G open", session.start.call_args.args[-1])
        self.assertNotIn("^G open", session.call.call_args.args[-1])
        session.attach.assert_called_once()

    @unittest.skipIf(os.name == "nt", "Codex launch mode requires POSIX tmux")
    def test_giving_the_key_back_to_codex_binds_nothing(self):
        stack, session = self.context()
        stack.enter_context(patch.dict(os.environ, {"HANDOFF_VIEWER_KEY": "none"}))
        session.exit_status.side_effect = [0]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "HANDOFF.md"
            path.write_text(entry(), encoding="utf-8")
            self.assertEqual(codex.run_codex(tui.Watcher(path), Path(directory), [], 1), 0)
        session.bind_viewer.assert_not_called()
        self.assertNotIn("open", session.start.call_args.args[-1])

    def test_piped_invocation_has_actionable_error(self):
        result = subprocess.run([sys.executable, str(SCRIPTS / "handoff_tui.py"), "--codex"],
                                capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 1)
        self.assertIn("WSL" if os.name == "nt" else "interactive terminal", result.stderr)
        self.assertNotIn("Traceback", result.stderr)

    def test_viewer_forwards_codex_args_after_options(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(codex, "run_agent", return_value=0) as run:
                self.assertEqual(tui.main(["--root", directory, "--interval", "2", "--no-color",
                                           "--codex", "resume", "--last", "--model", "example"]), 0)
            self.assertEqual(run.call_args.args[1:], (Path(directory).resolve(),
                             ["resume", "--last", "--model", "example"], 2.0))
            self.assertEqual(run.call_args.kwargs,
                             {"color": False, "read_only": False, "agent": "codex"})

    def test_read_only_reaches_the_popup_the_codex_bar_opens(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(codex, "run_agent", return_value=0) as run:
                self.assertEqual(tui.main(["--root", directory, "--read-only", "--codex"]), 0)
            self.assertIs(run.call_args.kwargs["read_only"], True)

    def test_conflicting_modes_fail_before_launch(self):
        for mode in ("--bar", "--once"):
            with self.subTest(mode=mode), self.assertRaises(SystemExit) as error:
                tui.main([mode, "--codex"])
            self.assertEqual(error.exception.code, 2)

    def test_any_agent_can_be_wrapped_and_keeps_its_own_arguments(self):
        # The bar was Codex-only, but nothing in it is Codex-specific; the user
        # runs Claude, Kimi and Grok under the same footer and the same key.
        for agent, extra in (("claude", ["--resume"]), ("kimi", []), ("grok", ["-p", "hi"])):
            with self.subTest(agent=agent), tempfile.TemporaryDirectory() as directory:
                with patch.object(codex, "run_agent", return_value=0) as run:
                    self.assertEqual(tui.main(["--root", directory, "--with", agent, *extra]), 0)
                self.assertEqual(run.call_args.kwargs["agent"], agent)
                self.assertEqual(run.call_args.args[2], extra)

    def test_with_needs_an_agent_and_a_missing_one_names_itself(self):
        with self.assertRaises(SystemExit) as error:
            tui.main(["--with"])
        self.assertEqual(error.exception.code, 2)
        with tempfile.TemporaryDirectory() as directory:
            watcher = tui.Watcher(Path(directory) / "HANDOFF.md")
            with ExitStack() as stack:
                stack.enter_context(patch.object(codex.sys.stdin, "isatty", return_value=True))
                stack.enter_context(patch.object(codex.sys.stdout, "isatty", return_value=True))
                stack.enter_context(patch.object(codex.shutil, "which",
                                                 side_effect=lambda name: None if name == "nope" else "/bin/" + name))
                self.assertEqual(codex.run_agent(watcher, Path(directory), [], 1, agent="nope"), 1)


@unittest.skipIf(os.name == "nt" or not shutil.which("tmux"), "needs POSIX tmux")
class TmuxIntegrationTests(unittest.TestCase):
    def server(self, base: Path) -> codex.AgentSession:
        """A private server on this machine's tmux, or a skip when sockets are denied."""
        session = codex.AgentSession(shutil.which("tmux"), base / "s")
        probe = subprocess.run(session.command + ["new-session", "-d", "-s", "probe"],
                               env=session.environment, capture_output=True, text=True,
                               encoding="utf-8")
        if probe.returncode:
            if "Operation not permitted" in probe.stderr or "Permission denied" in probe.stderr:
                self.skipTest("environment disallows tmux sockets: " + probe.stderr.strip())
            self.fail(probe.stderr)
        self.addCleanup(session.close)
        return session

    def test_the_viewer_key_binds_in_the_root_table_and_a_bad_key_is_reported(self):
        # Codex keeps every other key because this session has no prefix, so the
        # binding has to land in the root table for the key to reach tmux at all.
        with tempfile.TemporaryDirectory(prefix="hc-test-") as directory:
            base = Path(directory)
            session = self.server(base)
            command = codex.viewer_command(base / "HANDOFF.md", 1.0, read_only=False)
            self.assertTrue(session.bind_viewer("C-g", command, base))
            bound = session.call("list-keys", "-T", "root", "C-g")
            self.assertIn("display-popup", bound)
            self.assertIn("handoff_tui.py", bound)
            self.assertIn(str(base / "HANDOFF.md"), bound)
            # tmux resolves the key name and the command now, so an unusable
            # binding is known before the bar advertises it.
            self.assertFalse(session.bind_viewer("Not-A-Key", command, base))

    def test_real_pane_input_arguments_format_escaping_and_exit(self):
        with tempfile.TemporaryDirectory(prefix="hc-test-") as directory:
            base = Path(directory)
            session = codex.AgentSession(shutil.which("tmux"), base / "s")
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



class HostKeybindingTests(unittest.TestCase):
    """The other half of one key, one meaning: the host must stop claiming it."""

    def path(self) -> Path:
        directory = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, directory, True)
        return Path(directory) / "keybindings.json"

    def test_only_control_keys_have_a_host_spelling(self):
        self.assertEqual(codex.host_key_name("C-g"), "ctrl+g")
        self.assertEqual(codex.host_key_name("c-k"), "ctrl+k")
        for unmappable in ("M-g", "F5", "BSpace", "C-Up"):
            self.assertIsNone(codex.host_key_name(unmappable))

    def test_it_releases_the_key_and_rehomes_the_action_it_displaced(self):
        target = self.path()
        message = codex.install_host_keybindings("C-g", target)
        self.assertIn("ctrl+g", message)
        written = json.loads(target.read_text(encoding="utf-8"))
        block = written["bindings"][0]
        self.assertEqual(block["context"], "Chat")
        self.assertIsNone(block["bindings"]["ctrl+g"])
        # Unbinding must not lose the action outright, only move it.
        self.assertEqual(block["bindings"]["ctrl+e"], "chat:externalEditor")

    def test_it_is_idempotent_and_keeps_every_other_binding(self):
        target = self.path()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps({"bindings": [
            {"context": "Global", "bindings": {"ctrl+q": "app:exit"}},
            {"context": "Chat", "bindings": {"ctrl+s": "chat:stash"}},
        ]}), encoding="utf-8")
        codex.install_host_keybindings("C-g", target)
        again = codex.install_host_keybindings("C-g", target)
        self.assertIn("already", again)
        written = json.loads(target.read_text(encoding="utf-8"))
        self.assertEqual(written["bindings"][0], {"context": "Global",
                                                  "bindings": {"ctrl+q": "app:exit"}})
        chat = written["bindings"][1]["bindings"]
        self.assertEqual(chat["ctrl+s"], "chat:stash")
        self.assertIsNone(chat["ctrl+g"])

    def test_an_unparseable_or_foreign_file_is_left_alone(self):
        target = self.path()
        target.parent.mkdir(parents=True, exist_ok=True)
        for content in ("{not json", json.dumps({"bindings": "wrong"}), json.dumps([1, 2])):
            with self.subTest(content=content[:12]):
                target.write_text(content, encoding="utf-8")
                message = codex.install_host_keybindings("C-g", target)
                self.assertIn("Leaving", message)
                self.assertEqual(target.read_text(encoding="utf-8"), content)

    def test_no_key_and_an_unmappable_key_change_nothing(self):
        target = self.path()
        self.assertIn("no host override", codex.install_host_keybindings(None, target))
        self.assertIn("skipped", codex.install_host_keybindings("F5", target))
        self.assertFalse(target.exists())

    def test_the_viewer_installs_the_override_and_exits(self):
        target = self.path()
        with patch.object(codex, "CLAUDE_KEYBINDINGS", target):
            self.assertEqual(tui.main(["--install-viewer-key"]), 0)
        self.assertIsNone(json.loads(target.read_text(encoding="utf-8"))
                          ["bindings"][0]["bindings"]["ctrl+g"])


if __name__ == "__main__":
    unittest.main()
