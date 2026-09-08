"""Run Codex in a private tmux session with a Handoff footer and viewer key."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from handoff_tui import Watcher, bar_line, clean_text, count_tasks

VIEWER_KEY = "C-g"
# Leave room for the Codex prompt and the bar itself, so the popup reads as an
# overlay the user is looking through rather than a screen they switched to.
POPUP_SIZE = ("90%", "85%")


def viewer_key() -> str | None:
    """The one key this session keeps for itself; "none" gives it back to Codex."""
    key = os.environ.get("HANDOFF_VIEWER_KEY", VIEWER_KEY).strip()
    if not key or key.lower() == "none":
        return None
    return key


def key_label(key: str) -> str:
    """Name a tmux key the way a keyboard shows it, so the hint reads as typed."""
    if len(key) > 2 and key[1] == "-" and key[0] in "cC":
        return "^" + key[2:].upper()
    return key


def viewer_command(ledger: Path, interval: float, read_only: bool) -> str:
    """Quote the viewer invocation for the shell tmux runs a popup under."""
    viewer = Path(__file__).resolve().with_name("handoff_tui.py")
    parts = [sys.executable, str(viewer), "--file", str(ledger),
             "--interval", str(interval)]
    if read_only:
        parts.append("--read-only")
    return " ".join(shlex.quote(part) for part in parts)


def footer(watcher: Watcher, color: bool = True, key: str | None = None) -> str:
    """Escape tmux formats as well as terminal controls from ledger text."""
    row = bar_line(watcher.snapshot, color=False)
    if watcher.error:
        row = "handoff | STALE | " + row if row else "handoff | waiting for readable ledger"
    elif not row:
        row = "handoff | no tracked tasks"
    counts = count_tasks(watcher.snapshot.tasks if watcher.snapshot else [])
    shade = "green" if counts.tracked and counts.completed == counts.tracked else "yellow"
    style = f"#[fg={shade}]" if color and not watcher.error else "#[default]"
    # The hint is this module's own text, so it needs no escaping; appending it
    # after the cleaning keeps a ledger owner from forging a shortcut.
    hint = f" \u00b7 {key_label(key)} open" if key else ""
    return style + " " + clean_text(row).replace("#", "##") + hint


class CodexSession:
    """Own only this invocation's server, never an existing tmux session."""

    def __init__(self, tmux: str, socket: Path):
        self.command = [tmux, "-u", "-S", str(socket), "-f", os.devnull]
        self.environment = dict(os.environ)
        # A separate server can also run inside an existing tmux pane.
        self.environment.pop("TMUX", None)
        self.environment.pop("TMUX_PANE", None)
        self.directory = socket.parent
        # tmux 3.4 leaves pane_dead_status empty on a dead pane, so the child's
        # own status is recorded here rather than trusted to the format.
        self.status_file = socket.parent / "status"
        self.client: subprocess.Popen | None = None

    def run(self, *arguments: str) -> subprocess.CompletedProcess:
        return subprocess.run(self.command + list(arguments), env=self.environment,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace")

    def call(self, *arguments: str, check: bool = True) -> str:
        result = self.run(*arguments)
        if check:
            result.check_returncode()
        return result.stdout.strip()

    def bind_viewer(self, key: str, command: str, cwd: Path) -> bool:
        """Open the viewer in a popup on one key, reporting whether tmux took it.

        This session has no prefix, so the binding goes in the root table and this
        is the only key Codex does not receive. tmux resolves the bound command
        when the binding is made, so a tmux without display-popup, or a key name
        it does not know, fails here rather than on the first keypress, and the
        bar can then leave the hint off instead of advertising a dead shortcut.
        """
        width, height = POPUP_SIZE
        return self.run("bind-key", "-n", key, "display-popup", "-E",
                        "-w", width, "-h", height, "-d", str(cwd),
                        command).returncode == 0

    def start(self, codex: str, arguments: list[str], cwd: Path, row: str) -> None:
        size = shutil.get_terminal_size((100, 30))
        # Keep a placeholder alive until remain-on-exit and the footer are set,
        # even if Codex will fail immediately. Multiple argv items bypass sh.
        self.call("new-session", "-d", "-s", "handoff", "-c", str(self.directory),
                  "-x", str(size.columns), "-y", str(size.lines),
                  sys.executable, "-c", "import time; time.sleep(86400)")
        for name, value in (
            ("status", "on"), ("status-position", "bottom"),
            ("status-style", "default"), ("status-interval", "0"),
            ("status-format[0]", row), ("prefix", "None"),
            ("prefix2", "None"), ("set-titles", "off"),
        ):
            self.call("set-option", "-t", "handoff", name, value)
        self.call("set-option", "-s", "escape-time", "10")
        self.call("set-option", "-w", "-t", "handoff:0", "remain-on-exit", "on")
        # tmux treats even an argv item consisting of ';' as a command
        # separator. Encode user arguments so its parser cannot interpret them.
        payload = base64.b64encode(json.dumps(
            [str(cwd), [codex, *arguments], str(self.status_file)]).encode()).decode()
        # The shim waits for Codex rather than exec'ing it, so the exit status
        # survives a tmux that does not report pane_dead_status. It ignores
        # SIGINT so Ctrl-C reaches Codex alone, as a shell would.
        self.call("respawn-pane", "-k", "-t", "handoff:0.0", "-c", str(self.directory),
                  sys.executable, "-c",
                  "import base64,json,os,pathlib,signal,subprocess,sys; "
                  "d,a,s=json.loads(base64.b64decode(sys.argv[1])); os.chdir(d); "
                  "signal.signal(signal.SIGINT, signal.SIG_IGN); c=subprocess.call(a); "
                  "pathlib.Path(s).write_text(str(c)); sys.exit(c)", payload)

    def attach(self) -> None:
        self.client = subprocess.Popen(self.command + ["attach-session", "-t", "handoff"],
                                       env=self.environment)

    def exit_status(self) -> int | None:
        state = self.call("display-message", "-p", "-t", "handoff:0.0",
                          "#{pane_dead}:#{pane_dead_status}")
        dead, _, status = state.partition(":")
        if dead != "1":
            return None
        if status.isdigit():
            return int(status)
        # tmux 3.4 reports a dead pane with an empty pane_dead_status. Reading
        # the shim's record keeps a real exit code from being reported as 1.
        try:
            return int(self.status_file.read_text(encoding="utf-8").strip())
        except (OSError, ValueError):
            return 1

    def close(self) -> None:
        try:
            self.call("kill-server", check=False)
        finally:
            if self.client is not None:
                try:
                    self.client.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    self.client.terminate()
                    self.client.wait(timeout=3)


def run_codex(watcher: Watcher, cwd: Path, arguments: list[str],
              interval: float, color: bool = True, read_only: bool = False) -> int:
    if os.name == "nt":
        print("Codex bar mode needs tmux on macOS/Linux or WSL.", file=sys.stderr)
        return 1
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        print("Codex bar mode needs an interactive terminal; run handoff-tui --codex there.",
              file=sys.stderr)
        return 1
    tmux, codex = shutil.which("tmux"), shutil.which("codex")
    if not tmux or not codex:
        missing = "tmux (3.2+)" if not tmux else "codex"
        print(f"Codex bar mode needs {missing} on PATH.", file=sys.stderr)
        return 1
    if not cwd.is_dir():
        print(f"Codex working directory does not exist: {cwd}", file=sys.stderr)
        return 1

    def stop(signum, frame) -> None:
        raise KeyboardInterrupt

    previous = signal.signal(signal.SIGTERM, stop)
    try:
        with tempfile.TemporaryDirectory(prefix="hc-") as directory:
            session = CodexSession(tmux, Path(directory) / "s")
            try:
                watcher.poll()
                key = viewer_key()
                row = footer(watcher, color, key)
                session.start(codex, arguments, cwd, row)
                if key and not session.bind_viewer(
                        key, viewer_command(watcher.path, interval, read_only), cwd):
                    # An unusable binding is not worth failing the session over,
                    # but the bar must stop promising a key that does nothing.
                    key = None
                    row = footer(watcher, color, key)
                    session.call("set-option", "-t", "handoff",
                                 "status-format[0]", row, check=False)
                session.attach()
                next_poll = time.monotonic() + interval
                while True:
                    code = session.exit_status()
                    if code is not None:
                        return code
                    if session.client.poll() is not None:
                        return session.client.returncode
                    if time.monotonic() >= next_poll:
                        watcher.poll()
                        updated = footer(watcher, color, key)
                        if updated != row:
                            session.call("set-option", "-t", "handoff", "status-format[0]", updated)
                            row = updated
                        next_poll = time.monotonic() + interval
                    time.sleep(min(interval, 0.25))
            finally:
                session.close()
    except KeyboardInterrupt:
        return 130
    except (OSError, subprocess.SubprocessError) as error:
        detail = getattr(error, "stderr", None) or str(error)
        print(f"Cannot start or update Codex bar: {clean_text(detail).strip()}", file=sys.stderr)
        return 1
    finally:
        signal.signal(signal.SIGTERM, previous)
