#!/usr/bin/env python3
"""Watch recorded HANDOFF.md progress, and hand a task to another agent, in a terminal."""

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
    owner_label_error,
    parse_tasks,
    reassign_task,
    replace_owner,
    swap_ledger,
)

UNASSIGNED = "unassigned"


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
    return task.owner or UNASSIGNED


def owner_counts(tasks: list[Task]) -> list[tuple[str, Counts]]:
    groups: dict[str, list[Task]] = {}
    for task in tasks:
        groups.setdefault(owner_name(task), []).append(task)
    return [(owner, count_tasks(groups[owner])) for owner in sorted(groups, key=str.casefold)]


def task_state(task: Task) -> str:
    if task.errors:
        return "invalid"
    return task.state.replace("_", " ")


def heading_title(heading: str) -> str:
    """Remove the recorded owner label; retain the ledger's title and date."""
    return OWNER_RE.sub("", heading, count=1).strip()


def task_title(task: Task) -> str:
    return heading_title(task.heading)


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


def use_utf8_stdout() -> None:
    """Windows consoles default to a legacy codepage that cannot encode a
    ledger's text, and an encoding error there crashes the status line."""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):  # pragma: no cover - old or wrapped stream
        pass


def stdout_encodes(sample: str) -> bool:
    encoding = getattr(sys.stdout, "encoding", None) or "ascii"
    try:
        sample.encode(encoding)
    except (UnicodeError, LookupError):
        return False
    return True


def bar_line(snapshot: Snapshot | None, width: int = 10, color: bool = True,
             blocks: bool = True) -> str:
    """One row for a host status line; empty when nothing is tracked."""
    counts = count_tasks(snapshot.tasks if snapshot else [])
    if not counts.tracked:
        return ""
    full, empty, gap = ("█", "░", "·") if blocks else ("#", "-", "|")
    filled = counts.completed * width // counts.tracked
    shade = "\033[32m" if counts.completed == counts.tracked else "\033[33m"
    reset = "\033[0m"
    dim = "\033[2m"
    if not color:
        shade = reset = dim = ""
    open_tasks = [t for t in (snapshot.tasks if snapshot else []) if t.modern and task_state(t) != "completed"]
    trailer = f" {dim}{gap}{reset} " + ", ".join(sorted({owner_name(t) for t in open_tasks})) if open_tasks else ""
    return (f"{shade}handoff{reset} {shade}{full * filled}{empty * (width - filled)}{reset} "
            f"{counts.completed}/{counts.tracked} tasks {dim}{gap}{reset} "
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


def move_note(task: Task, target: str, when: datetime | None = None) -> str:
    """Record the reassignment in the ledger's own status prose.

    Rewriting only the heading would erase who held the task without leaving any
    trace that it moved, which is the attribution loss the ledger contract exists
    to prevent. The note states what was changed and, deliberately, claims nothing
    about progress: a move does not verify a step.
    """
    stamp = (when or datetime.now()).date().isoformat()
    note = (f"Reassigned {stamp}: moved from {owner_name(task)} to {target} in the "
            "handoff viewer at the user's direction. No state or step boxes were "
            "changed, and the entry keeps its place in ledger order.")
    return "\n".join(textwrap.wrap(clean_text(note), width=79))


class Dashboard:
    def __init__(self, watcher: Watcher, read_only: bool = False):
        self.watcher = watcher
        self.view = "agents"
        self.owner: str | None = None
        self.selected = 0
        self.offset = 0
        self.detail: Task | None = None
        self.detail_offset = 0
        self.read_only = read_only
        self.cut: Task | None = None
        self.prompt: str | None = None
        self.message: str | None = None
        # The last completed move, kept until the next one: a transient message
        # cannot answer "did it land" when checking costs a keypress.
        self.moved: tuple[str, str] | None = None

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
        if self.cut:
            # Track the held task across peer writes so its recorded line stays
            # current; a task that left the ledger cannot be moved from here.
            tasks = self.watcher.snapshot.tasks if self.watcher.snapshot else []
            self.cut = next((task for task in tasks if task.heading == self.cut.heading), None)
            if self.cut is None:
                self.message = ("The held task is no longer in the ledger. "
                                "Nothing was moved.")
        if self.moved is not None:
            tasks = self.watcher.snapshot.tasks if self.watcher.snapshot else []
            if not any(task.heading == self.moved[0] for task in tasks):
                self.moved = None

    def selected_task(self) -> Task | None:
        rows = self.rows()
        if self.detail:
            return self.detail
        if self.view == "tasks" and rows:
            return rows[self.selected][1]
        return None

    def paste_target(self) -> str | None:
        """The owner a paste would hand the held task to, from the current row."""
        rows = self.rows()
        if self.view == "agents":
            return rows[self.selected][0] if rows else None
        if self.owner is not None:
            return self.owner
        task = self.selected_task()
        return owner_name(task) if task else None

    def show_landing(self, heading: str, label: str) -> None:
        """After a move, open the receiving agent's task list on the moved task.

        Answering "did it land" by reading a message is weaker than seeing the task
        in that agent's own list, and the paste happens in the Agents view, where no
        task rows are drawn at all.
        """
        self.moved = (heading, label)
        self.refresh()
        self.view, self.owner, self.detail = "tasks", label, None
        rows = self.rows()
        self.selected = next((i for i, row in enumerate(rows) if row[0] == heading), 0)
        self.offset = 0

    def move_task(self, label: str) -> None:
        """Reassign the held task with a compare-and-swap against the read revision."""
        task, snapshot = self.cut, self.watcher.snapshot
        if task is None or snapshot is None:
            self.message = "No task is held. Press x on a task first."
            return
        title = fit(task_title(task), 46)
        if label == owner_name(task):
            self.cut = None
            self.message = f"'{title}' is already recorded to {label}. Nothing was moved."
            return
        if not self.watcher.path.is_file():
            self.message = f"Nothing was moved: no ledger at {self.watcher.path}."
            return
        owner = None if label == UNASSIGNED else label
        try:
            result = swap_ledger(
                self.watcher.path, snapshot.version,
                lambda text: reassign_task(text, task.line, task.heading, owner,
                                           move_note(task, label)),
            )
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            self.message = f"Nothing was moved: {error}"
            return
        if result["status"] == "applied":
            self.cut = None
            self.message = None
            self.show_landing(replace_owner(task.heading, owner), label)
            return
        if result["status"] == "conflict":
            self.cut = None
            self.message = ("The ledger changed while this view held the task, so nothing "
                            "was moved. Reloaded; check the new entries and cut again.")
        else:
            self.message = "Nothing was moved: " + "; ".join(
                str(error) for error in (result.get("errors") or ["write refused"]))
            return
        self.refresh()

    def handle_prompt(self, key: int, curses) -> bool:
        """Read one owner name for a task whose new agent has no ledger entry yet."""
        if key in (27, 3):
            self.prompt = None
            self.message = "Naming cancelled. The task is still held; press x to release it."
        elif key in (10, 13, curses.KEY_ENTER):
            name, self.prompt = self.prompt.strip(), None
            problem = owner_label_error(name) if name else "no name was typed"
            if problem:
                self.message = f"Nothing was moved: {problem}."
            else:
                self.move_task(name)
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            self.prompt = self.prompt[:-1]
        elif 32 <= key < 127 and len(self.prompt) < 60:
            self.prompt += chr(key)
        return True

    def handle_move_key(self, key: int) -> bool:
        """Handle the cut and paste keys; return False when the key was not one."""
        if key not in (ord("x"), ord("X"), ord("p"), ord("P")):
            return False
        if self.read_only:
            self.message = "Moves are disabled in read-only mode."
            return True
        task = self.selected_task()
        if key in (ord("x"), ord("X")):
            if task is None:
                self.message = "Open the Tasks view and select a task to cut it."
            elif self.cut is not None and self.cut.heading == task.heading:
                self.cut = None
                self.message = "Released. Nothing is held."
            else:
                self.cut = task
                self.moved = None
                self.message = (f"Cut '{fit(task_title(task), 46)}'. Press p on the receiving "
                                "agent or task, P to type a name, x to put it back.")
            return True
        if self.cut is None:
            self.message = "Nothing is held. Press x on a task first."
        elif key == ord("P"):
            self.prompt = ""
        else:
            target = self.paste_target()
            if target is None:
                self.message = "No agent is selected to receive the task."
            else:
                self.move_task(target)
        return True

    def handle_key(self, key: int, curses, page: int) -> bool:
        if self.prompt is not None:
            return self.handle_prompt(key, curses)
        if key != -1:
            self.message = None
        if self.handle_move_key(key):
            return True
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
        available = max(1, height - content_start - 4)
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
                held = landed = False
                if self.view == "agents":
                    line = owner_row(label, value, width - 3)
                else:
                    held = self.cut is not None and self.cut.heading == value.heading
                    landed = self.moved is not None and self.moved[0] == value.heading
                    checked = sum(done for done, _ in value.steps)
                    line = (f"{task_state(value):13}  {checked:2}/{len(value.steps):<2}  "
                            f"{task_title(value)} / {owner_name(value)}")
                mark = "*" if held else "+" if landed else ">" if selected else " "
                write(content_start + i, mark + line, curses.A_REVERSE if selected else 0)
            if not rows:
                write(content_start, " No entries to display. Waiting for ledger changes.")

        write(height - 4, self.banner(), curses.A_BOLD)
        snapshot = self.watcher.snapshot
        if self.watcher.error:
            stamp = f"STALE (last read {snapshot.read_at:%H:%M:%S})" if snapshot else "WAITING"
            write(height - 3, f" {stamp} | READ ERROR: {self.watcher.error}", curses.A_BOLD)
        elif snapshot:
            write(height - 3, f" Read {snapshot.read_at:%H:%M:%S} | revision {snapshot.version[:12]}"
                  f" | {len(rows)} {self.view} | automatic refresh", curses.A_DIM)
        write(height - 2, " Checkbox counts only; owner labels do not prove authorship or live activity.", curses.A_DIM)
        write(height - 1, " q quit | Tab a/t views | j/k arrows | Enter open | b back | r reload"
              + ("" if self.read_only else " | x cut | p give"))
        screen.refresh()
        return available

    def banner(self) -> str:
        """One line for the pending move: the prompt, the last outcome, or what is held."""
        if self.prompt is not None:
            return f" Give to agent: {self.prompt}_   Enter: confirm | Esc: cancel"
        if self.message:
            return " " + self.message
        if self.cut is not None:
            return (f" HOLDING '{fit(task_title(self.cut), 46)}' from {owner_name(self.cut)}"
                    " | p: give to selected | P: type a name | x: release")
        if self.moved is not None:
            # The receiving agent comes first: it is the fact the user is checking,
            # and whatever a narrow terminal clips should be the title, not this.
            heading, label = self.moved
            return f" MOVED to {label} | + {heading_title(heading)} | b: all tasks"
        return ""


def run_live(watcher: Watcher, interval: float, read_only: bool = False) -> int:
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
        dashboard = Dashboard(watcher, read_only=read_only)
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
    parser.add_argument("--read-only", action="store_true",
                        help="Disable the live view's cut and paste keys, so it never writes")
    parser.add_argument("--bar", action="store_true",
                        help="Print one status-line row; reads host JSON on stdin for the directory")
    parser.add_argument("--no-color", action="store_true", help="Omit colour from --bar or --codex")
    parser.add_argument("--codex", nargs=argparse.REMAINDER,
                        help="Run Codex with a live bottom bar (tmux 3.2+); remaining arguments go to Codex")
    args = parser.parse_args(argv)
    use_utf8_stdout()
    if args.codex is not None and (args.bar or args.once):
        parser.error("--codex cannot be combined with --bar or --once")
    root = args.root
    if args.bar and not args.file and not sys.stdin.isatty():
        # A host status line pipes session JSON in; prefer the directory it reports.
        reported = status_line_root(sys.stdin.read())
        if reported is not None and args.root == Path("."):
            root = reported
    path = args.file.resolve() if args.file else find_repo_root(root) / "HANDOFF.md"
    watcher = Watcher(path)
    if args.codex is not None:
        from handoff_codex import run_codex
        arguments = args.codex[1:] if args.codex[:1] == ["--"] else args.codex
        return run_codex(watcher, args.file.resolve().parent if args.file else root.resolve(),
                         arguments, args.interval, color=not args.no_color)
    if args.bar:
        # A status line must never break the host: no ledger means no row.
        if not path.is_file():
            return 0
        watcher.poll()
        line = bar_line(watcher.snapshot, color=not args.no_color,
                        blocks=stdout_encodes("\u2588\u2591\u00b7"))
        if line:
            print(line)
        return 0
    if args.once or not (sys.stdin.isatty() and sys.stdout.isatty()):
        watcher.poll()
        print(plain_report(watcher), end="")
        return 1 if watcher.error or (watcher.snapshot and any(task.errors for task in watcher.snapshot.tasks)) else 0
    return run_live(watcher, args.interval, read_only=args.read_only)


if __name__ == "__main__":
    sys.exit(main())
