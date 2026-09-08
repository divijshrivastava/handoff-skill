"""Run Codex in a private tmux session with a read-only Handoff footer."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time

from handoff_tui import Watcher, bar_line, clean_text, count_tasks


def footer(watcher: Watcher, color: bool = True) -> str:
    """Escape tmux formats as well as terminal controls from ledger text."""
    row = bar_line(watcher.snapshot, color=False)
    if watcher.error:
        row = "handoff | STALE | " + row if row else "handoff | waiting for readable ledger"
    elif not row:
        row = "handoff | no tracked tasks"
    counts = count_tasks(watcher.snapshot.tasks if watcher.snapshot else [])
    shade = "green" if counts.tracked and counts.completed == counts.tracked else "yellow"
    style = f"#[fg={shade}]" if color and not watcher.error else "#[default]"
    return style + " " + clean_text(row).replace("#", "##")


class CodexSession:
    """Own only this invocation's server, never an existing tmux session."""

    def __init__(self, tmux: str, socket: Path):
        self.command = [tmux, "-u", "-S", str(socket), "-f", os.devnull]
        self.environment = dict(os.environ)
        # A separate server can also run inside an existing tmux pane.
        self.environment.pop("TMUX", None)
        self.environment.pop("TMUX_PANE", None)
        self.directory = socket.parent
        self.client: subprocess.Popen | None = None

    def call(self, *arguments: str, check: bool = True) -> str:
        result = subprocess.run(self.command + list(arguments), env=self.environment,
                                capture_output=True, text=True, encoding="utf-8",
                                errors="replace", check=check)
        return result.stdout.strip()

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
        payload = base64.b64encode(json.dumps([str(cwd), [codex, *arguments]]).encode()).decode()
        self.call("respawn-pane", "-k", "-t", "handoff:0.0", "-c", str(self.directory),
                  sys.executable, "-c",
                  "import base64,json,os,sys; d,a=json.loads(base64.b64decode(sys.argv[1])); "
                  "os.chdir(d); os.execv(a[0],a)", payload)

    def attach(self) -> None:
        self.client = subprocess.Popen(self.command + ["attach-session", "-t", "handoff"],
                                       env=self.environment)

    def exit_status(self) -> int | None:
        state = self.call("display-message", "-p", "-t", "handoff:0.0",
                          "#{pane_dead}:#{pane_dead_status}")
        dead, _, status = state.partition(":")
        if dead == "1":
            return int(status) if status.isdigit() else 1
        return None

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
              interval: float, color: bool = True) -> int:
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
                row = footer(watcher, color)
                session.start(codex, arguments, cwd, row)
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
                        updated = footer(watcher, color)
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
