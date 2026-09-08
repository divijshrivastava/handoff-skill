#!/usr/bin/env python3
"""Watch recorded HANDOFF.md progress in a read-only terminal dashboard."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import json
import math
from pathlib import Path
import sys
import textwrap
import time
import unicodedata

from handoff_guard import (
    OWNER_RE,
    Task,
    find_repo_root,
    ledger_version,
    outside_fence_lines,
    parse_tasks,
)


@dataclass
class Counts:
    tracked: int = 0
    completed: int = 0
    in_progress: int = 0
    pending: int = 0
    checked: int = 0
    steps: int = 0
    invalid: int = 0
    legacy: int = 0


@dataclass
class Snapshot:
    tasks: list[Task]
    statuses: list[str]
    version: str
    read_at: datetime


def count_tasks(tasks: list[Task]) -> Counts:
    """Exclude malformed and legacy entries from measurable progress."""
    counts = Counts()
    for task in tasks:
        if not task.modern:
            counts.legacy += 1
        elif task.errors or task.state == "invalid":
            counts.invalid += 1
        else:
            counts.tracked += 1
            if task.state == "completed":
                counts.completed += 1
            elif task.state == "in_progress":
                counts.in_progress += 1
            elif task.state == "pending":
                counts.pending += 1
            counts.steps += len(task.steps)
            counts.checked += sum(checked for checked, _ in task.steps)
    return counts


def owner_name(task: Task) -> str:
    return task.owner or "unassigned"


def owner_counts(tasks: list[Task]) -> list[tuple[str, Counts]]:
    groups: dict[str, list[Task]] = {}
    for task in tasks:
        groups.setdefault(owner_name(task), []).append(task)
    return [(owner, count_tasks(groups[owner])) for owner in sorted(groups, key=str.casefold)]


def task_state(task: Task) -> str:
    if task.errors:
        return "invalid"
    return task.state.replace("_", " ")


def task_title(task: Task) -> str:
    """Remove the parsed owner label; retain the ledger's title and date."""
    return OWNER_RE.sub("", task.heading, count=1).strip()


def parse_snapshot(text: str) -> Snapshot:
    tasks = parse_tasks(text)
    lines = outside_fence_lines(text.splitlines())
    statuses = []
    for index, task in enumerate(tasks):
        end = tasks[index + 1].line - 1 if index + 1 < len(tasks) else len(lines)
        block = lines[task.line:end]
        start = next(
            (i for i, line in enumerate(block) if line.strip().startswith("Status:")),
            None,
        )
        statuses.append(" ".join(line.strip() for line in block[start:] if line.strip())
                        if start is not None else "Status: Not recorded.")
    return Snapshot(tasks, statuses, ledger_version(text), datetime.now())


class Watcher:
    """Read one snapshot per poll; retain the last readable data on I/O failure."""

    def __init__(self, path: Path):
        self.path = path
        self.snapshot: Snapshot | None = None
        self.error: str | None = None

    def poll(self) -> None:
        try:
            text = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            self.error = str(error)
            return
        self.error = None
        if self.snapshot is None or ledger_version(text) != self.snapshot.version:
            self.snapshot = parse_snapshot(text)
        else:
            self.snapshot.read_at = datetime.now()


def clean_text(value: str) -> str:
    """Never let ledger text emit terminal controls or invisible formatting."""
    return "".join(character if character.isprintable() else " " for character in value)


def cell_width(character: str) -> int:
    if unicodedata.combining(character):
        return 0
    return 2 if unicodedata.east_asian_width(character) in {"W", "F"} else 1


def fit(value: str, width: int, pad: bool = False) -> str:
    """Clip by terminal cells, including wide owner names, without escape codes."""
    result = []
    used = 0
    for character in clean_text(value):
        size = cell_width(character)
        if used + size > width:
            break
        result.append(character)
        used += size
    return "".join(result) + (" " * max(0, width - used) if pad else "")


def progress(checked: int, total: int, width: int = 12) -> str:
    filled = checked * width // total if total else 0
    percent = f"{checked / total:4.0%}" if total else " n/a"
    return f"[{'#' * filled}{'-' * (width - filled)}] {percent} {checked}/{total}"


def summary_lines(snapshot: Snapshot | None) -> list[str]:
    counts = count_tasks(snapshot.tasks if snapshot else [])
    return [
        f"TASKS  {progress(counts.completed, counts.tracked)} completed"
        f"   {counts.in_progress} in progress / {counts.pending} pending",
        f"STEPS  {progress(counts.checked, counts.steps)} checked",
        f"Excluded from totals: {counts.invalid} invalid / {counts.legacy} legacy entries",
    ]


def bar_line(snapshot: Snapshot | None, width: int = 10, color: bool = True) -> str:
    """One row for a host status line; empty when nothing is tracked."""
    counts = count_tasks(snapshot.tasks if snapshot else [])
    if not counts.tracked:
        return ""
    filled = counts.completed * width // counts.tracked
    shade = "\033[32m" if counts.completed == counts.tracked else "\033[33m"
    reset = "\033[0m"
    dim = "\033[2m"
    if not color:
        shade = reset = dim = ""
    open_tasks = [t for t in (snapshot.tasks if snapshot else []) if t.modern and task_state(t) != "completed"]
    trailer = f" {dim}·{reset} " + ", ".join(sorted({owner_name(t) for t in open_tasks})) if open_tasks else ""
    return (f"{shade}handoff{reset} {shade}{'█' * filled}{'░' * (width - filled)}{reset} "
            f"{counts.completed}/{counts.tracked} tasks {dim}·{reset} "
            f"{counts.checked}/{counts.steps} steps{trailer}")


def status_line_root(payload: str) -> Path | None:
    """Read workspace.current_dir from a host status-line JSON payload."""
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    if not isinstance(data, dict):
        return None
    workspace = data.get("workspace")
    location = (workspace or {}).get("current_dir") if isinstance(workspace, dict) else None
    location = location or data.get("cwd")
    return Path(location) if isinstance(location, str) and location else None


def owner_row(owner: str, counts: Counts, width: int) -> str:
    name_width = max(12, width - 52)
    return (f"{fit(owner, name_width, pad=True)}  "
            f"{counts.completed:3}/{counts.tracked:<3}  "
            f"{counts.in_progress:3}  {counts.pending:3}  "
            f"{progress(counts.checked, counts.steps, 8)}"
            f"  !{counts.invalid} ?{counts.legacy}")


def plain_report(watcher: Watcher) -> str:
    """One readable snapshot for pipes and terminals without curses."""
    lines = ["HANDOFF | Recorded progress", str(watcher.path)]
    if watcher.error:
        lines.append(f"READ ERROR: {watcher.error}")
        if watcher.snapshot:
            lines.append("Showing the last readable snapshot; data is stale.")
    lines.extend(summary_lines(watcher.snapshot))
    lines.extend(["", "BY RECORDED OWNER | done/tasks, in progress, pending, checked steps",
                  "! = invalid; ? = legacy (excluded from totals)"])
    if watcher.snapshot:
        for owner, counts in owner_counts(watcher.snapshot.tasks):
            # Avoid truncating ownership in redirected reports.
            width = max(110, sum(cell_width(c) for c in clean_text(owner)) + 62)
            lines.append(owner_row(owner, counts, width))
        lines.extend(["", "TASKS (ledger order)"])
        for task, status in zip(watcher.snapshot.tasks, watcher.snapshot.statuses):
            checked = sum(done for done, _ in task.steps)
            lines.append(f"[{task_state(task)}] {task.heading}")
            lines.append(f"  Steps: {progress(checked, len(task.steps))}")
            lines.extend(f"  [{'x' if done else ' '}] {step}" for done, step in task.steps)
            lines.append(f"  {status}")
            lines.extend(f"  Invalid: {error}" for error in task.errors)
        if not watcher.snapshot.tasks:
            lines.append("No task entries found. Waiting for ledger entries in live mode.")
        lines.append(f"\nRead: {watcher.snapshot.read_at:%H:%M:%S}"
                     f" | Revision: {watcher.snapshot.version[:12]}")
    lines.append("\nCheckbox counts only; owner labels do not prove authorship or live activity.")
    return "\n".join(clean_text(line) for line in lines) + "\n"


class Dashboard:
    def __init__(self, watcher: Watcher):
        self.watcher = watcher
        self.view = "agents"
        self.owner: str | None = None
        self.selected = 0
        self.offset = 0
        self.detail: Task | None = None
        self.detail_offset = 0

    def tasks(self) -> list[Task]:
        snapshot = self.watcher.snapshot
        return [task for task in snapshot.tasks
                if self.owner is None or owner_name(task) == self.owner] if snapshot else []

    def rows(self) -> list[tuple[str, Counts | Task]]:
        snapshot = self.watcher.snapshot
        if self.view == "agents":
            return [(owner, counts) for owner, counts in owner_counts(snapshot.tasks)] if snapshot else []
        return [(task.heading, task) for task in self.tasks()]

    def refresh(self) -> None:
        rows = self.rows()
        key = rows[min(self.selected, len(rows) - 1)][0] if rows else None
        self.watcher.poll()
        rows = self.rows()
        self.selected = next((i for i, row in enumerate(rows) if row[0] == key),
                             min(self.selected, max(0, len(rows) - 1)))
        if self.detail:
            self.detail = next((task for task in self.tasks()
                                if task.heading == self.detail.heading), None)

    def handle_key(self, key: int, curses, page: int) -> bool:
        if key in (ord("q"), ord("Q"), 3):
            return False
        if key in (27, ord("b"), curses.KEY_BACKSPACE, 127):
            if self.detail:
                self.detail = None
            elif self.owner is not None:
                self.owner = None
                self.selected = self.offset = 0
            return True
        if key in (9, ord("a"), ord("t")):
            self.view = ("tasks" if self.view == "agents" else "agents") if key == 9 else (
                "agents" if key == ord("a") else "tasks")
            self.owner = None
            self.detail = None
            self.selected = self.offset = 0
        elif key in (10, 13, curses.KEY_ENTER) and not self.detail:
            rows = self.rows()
            if rows:
                if self.view == "agents":
                    self.owner = rows[self.selected][0]
                    self.view = "tasks"
                    self.selected = self.offset = 0
                else:
                    self.detail = rows[self.selected][1]
                    self.detail_offset = 0
        else:
            movement = {curses.KEY_DOWN: 1, ord("j"): 1, curses.KEY_UP: -1,
                        ord("k"): -1, curses.KEY_NPAGE: page, curses.KEY_PPAGE: -page}
            if key in movement:
                if self.detail:
                    self.detail_offset = max(0, self.detail_offset + movement[key])
                else:
                    self.selected = min(max(0, len(self.rows()) - 1),
                                        max(0, self.selected + movement[key]))
            elif key == curses.KEY_HOME:
                self.detail_offset = self.selected = 0
            elif key == curses.KEY_END:
                if self.detail:
                    self.detail_offset = sys.maxsize
                else:
                    self.selected = max(0, len(self.rows()) - 1)
        return True

    def detail_lines(self, width: int) -> list[str]:
        task = self.detail
        snapshot = self.watcher.snapshot
        if task is None or snapshot is None:
            return []
        index = snapshot.tasks.index(task)
        blocks = [task.heading, f"Owner: {owner_name(task)} | State: {task_state(task)}",
                  f"Steps: {progress(sum(done for done, _ in task.steps), len(task.steps))}", ""]
        blocks.extend(f"[{'x' if done else ' '}] {step}" for done, step in task.steps)
        blocks.extend(["", snapshot.statuses[index]])
        blocks.extend(f"Invalid: {error}" for error in task.errors)
        # Conservative wrapping prevents wide Unicode from falling off the right edge.
        wrap_width = max(1, width // 2 if any(cell_width(c) == 2 for b in blocks for c in b) else width)
        return [line for block in blocks for line in
                (textwrap.wrap(clean_text(block), width=wrap_width) or [""])]

    def draw(self, screen, curses) -> int:
        height, width = screen.getmaxyx()
        screen.erase()

        def write(y: int, text: str, style: int = 0) -> None:
            if 0 <= y < height:
                try:
                    screen.addstr(y, 0, fit(text, max(0, width - 1)), style)
                except curses.error:
                    # A resize can race getmaxyx/addstr; redraw on the next event.
                    pass

        if height < 14 or width < 64:
            write(0, "HANDOFF | Enlarge terminal to at least 64 x 14")
            write(1, "q: quit | --once: plain snapshot")
            screen.refresh()
            return 1

        write(0, " HANDOFF  /  Recorded progress", curses.A_BOLD)
        write(1, f" {self.watcher.path}", curses.A_DIM)
        for i, line in enumerate(summary_lines(self.watcher.snapshot), 2):
            write(i, " " + line)
        write(5, " [Agents]   Tasks    Enter: owner's tasks" if self.view == "agents" else
              f" Agents   [Tasks]    Owner: {self.owner or 'all'}", curses.A_BOLD)
        content_start = 7
        available = max(1, height - content_start - 3)
        rows = self.rows()
        if self.detail:
            lines = self.detail_lines(width - 3)
            self.detail_offset = min(self.detail_offset, max(0, len(lines) - available))
            write(6, f" TASK DETAILS | lines {self.detail_offset + 1}-{min(len(lines), self.detail_offset + available)}"
                  f"/{len(lines)} | b: back", curses.A_DIM)
            for i, line in enumerate(lines[self.detail_offset:self.detail_offset + available]):
                write(content_start + i, " " + line)
        else:
            if self.view == "agents":
                write(6, f" {fit('RECORDED OWNER', max(12, width - 55), pad=True)}"
                      "  DONE/TASK  WIP WAIT  CHECKED STEPS  !bad ?old", curses.A_DIM)
            else:
                write(6, " STATE          STEPS    TASK / OWNER (ledger order)", curses.A_DIM)
            self.offset = max(0, min(self.offset, self.selected))
            if self.selected >= self.offset + available:
                self.offset = self.selected - available + 1
            for i, (label, value) in enumerate(rows[self.offset:self.offset + available]):
                selected = self.offset + i == self.selected
                if self.view == "agents":
                    line = owner_row(label, value, width - 3)
                else:
                    checked = sum(done for done, _ in value.steps)
                    line = (f"{task_state(value):13}  {checked:2}/{len(value.steps):<2}  "
                            f"{task_title(value)} / {owner_name(value)}")
                write(content_start + i, (">" if selected else " ") + line,
                      curses.A_REVERSE if selected else 0)
            if not rows:
                write(content_start, " No entries to display. Waiting for ledger changes.")

        snapshot = self.watcher.snapshot
        if self.watcher.error:
            stamp = f"STALE (last read {snapshot.read_at:%H:%M:%S})" if snapshot else "WAITING"
            write(height - 3, f" {stamp} | READ ERROR: {self.watcher.error}", curses.A_BOLD)
        elif snapshot:
            write(height - 3, f" Read {snapshot.read_at:%H:%M:%S} | revision {snapshot.version[:12]}"
                  f" | {len(rows)} {self.view} | automatic refresh", curses.A_DIM)
        write(height - 2, " Checkbox counts only; owner labels do not prove authorship or live activity.", curses.A_DIM)
        write(height - 1, " q quit | Tab a/t views | j/k arrows | PgUp/Dn | Enter open | b back | r reload")
        screen.refresh()
        return available


def run_live(watcher: Watcher, interval: float) -> int:
    try:
        import curses
    except ImportError:
        print("Live view needs Python curses support; use --once for a snapshot.", file=sys.stderr)
        return 1

    def loop(screen) -> None:
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        screen.keypad(True)
        dashboard = Dashboard(watcher)
        next_poll = 0.0
        while True:
            now = time.monotonic()
            if now >= next_poll:
                dashboard.refresh()
                next_poll = time.monotonic() + interval
            page = dashboard.draw(screen, curses)
            screen.timeout(max(1, min(250, int((next_poll - time.monotonic()) * 1000))))
            key = screen.getch()
            if key == ord("r"):
                next_poll = 0.0
            if not dashboard.handle_key(key, curses, page):
                break

    try:
        curses.wrapper(loop)
    except KeyboardInterrupt:
        return 0
    except curses.error as error:
        print(f"Cannot start terminal dashboard: {error}. Use --once for a snapshot.", file=sys.stderr)
        return 1
    return 0


def refresh_interval(value: str) -> float:
    try:
        seconds = float(value)
    except ValueError:
        raise argparse.ArgumentTypeError("interval must be a number between 0.1 and 60")
    if not math.isfinite(seconds) or not 0.1 <= seconds <= 60:
        raise argparse.ArgumentTypeError("interval must be between 0.1 and 60 seconds")
    return seconds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    location = parser.add_mutually_exclusive_group()
    location.add_argument("--root", default=".", type=Path, help="Repository path or child path")
    location.add_argument("--file", type=Path, help="Explicit ledger path, e.g. ./handoff.md")
    parser.add_argument("--interval", type=refresh_interval, default=1.0,
                        help="Refresh seconds, 0.1 to 60 (default: 1)")
    parser.add_argument("--once", action="store_true", help="Print a snapshot and exit")
    parser.add_argument("--bar", action="store_true",
                        help="Print one status-line row; reads host JSON on stdin for the directory")
    parser.add_argument("--no-color", action="store_true", help="Omit ANSI colour from --bar")
    args = parser.parse_args(argv)
    root = args.root
    if args.bar and not args.file and not sys.stdin.isatty():
        # A host status line pipes session JSON in; prefer the directory it reports.
        reported = status_line_root(sys.stdin.read())
        if reported is not None and args.root == Path("."):
            root = reported
    path = args.file.resolve() if args.file else find_repo_root(root) / "HANDOFF.md"
    watcher = Watcher(path)
    if args.bar:
        # A status line must never break the host: no ledger means no row.
        if not path.is_file():
            return 0
        watcher.poll()
        line = bar_line(watcher.snapshot, color=not args.no_color)
        if line:
            print(line)
        return 0
    if args.once or not (sys.stdin.isatty() and sys.stdout.isatty()):
        watcher.poll()
        print(plain_report(watcher), end="")
        return 1 if watcher.error or (watcher.snapshot and any(task.errors for task in watcher.snapshot.tasks)) else 0
    return run_live(watcher, args.interval)


if __name__ == "__main__":
    sys.exit(main())
