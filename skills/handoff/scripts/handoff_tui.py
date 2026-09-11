#!/usr/bin/env python3
"""Watch recorded HANDOFF.md progress, and hand a task to another agent, in a terminal."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
import secrets
from pathlib import Path
import sqlite3
import sys
import textwrap
import time
import unicodedata

from handoff_keys import available_agents, open_agent

try:
    from handoff_channel import Channel
except ImportError:  # an installed copy without the channel module beside it
    # The bar resolves a viewer out of plugin caches and runs on every
    # status-line tick. A viewer that cannot start prints nothing at all, so
    # a missing channel degrades this one view instead of the whole program.
    Channel = None  # type: ignore[assignment]
from handoff_guard import (
    OWNER_RE,
    NameClaim,
    Task,
    apply_session_intake,
    assigned_unstarted,
    find_repo_root,
    harness_for_agent,
    held_sessions,
    held_sessions_for_ledger,
    ledger_version,
    mark_step_complete,
    mark_task_complete,
    outside_fence_lines,
    owner_label_error,
    parse_tasks,
    recent_claims,
    recent_claims_for_ledger,
    reassign_task,
    recall_name,
    replace_owner,
    seed_claim,
    swap_ledger,
    transfer_step,
)
from handoff_lead import (
    DEFAULT_VIEWER_LEAD_HOURS,
    Assignment,
    build_claim,
    build_resign,
    completed_ids,
    read_assignment,
    read_lead,
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
    text: str = ""


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
    """Group by owner in ledger order, so the newest session leads.

    New entries go at the top of the ledger, so an owner's first appearance is
    their most recent task: keeping that order puts the agent who last raised
    work on the first row. An alphabetical list buried a new peer wherever
    their name happened to sort.
    """
    groups: dict[str, list[Task]] = {}
    for task in tasks:
        groups.setdefault(owner_name(task), []).append(task)
    return [(owner, count_tasks(groups[owner])) for owner in groups]


def repo_display_label(ledger_path: str | None, ledger: Path) -> str:
    """Short repository label for one name claim."""
    if not ledger_path:
        return "?"
    try:
        other = Path(ledger_path).resolve()
    except OSError:
        return "?"
    if other == ledger.resolve():
        return "here"
    return other.parent.name or other.name


def agent_rows(tasks: list[Task], ledger: Path | None = None,
               leader: str | None = None) -> list[tuple[str, Counts]]:
    """Ledger owners plus recent name claims for this ledger that hold no tasks yet.

    A session that claimed its name during preflight but has not written a
    ledger entry yet should still appear so the user can hand it work from the
    viewer. Those rows lead the list, newest claim first, with empty counts.

    `leader` is the owner of an active mandate. The mandate is ledger data, like
    an owner label, so its holder stays listed until it expires or resigns: a
    leader with no tasks whose name claim aged out otherwise vanished while the
    header still named it, and L could not resign it nor p give it work.
    """
    recorded = owner_counts(tasks)
    ledger_owners = {owner for owner, _ in recorded}
    waiting: list[tuple[str, Counts]] = []
    seen: set[str] = set()
    claims = recent_claims_for_ledger(ledger) if ledger is not None else recent_claims()
    for claim in claims:
        if claim.name in ledger_owners or claim.name == UNASSIGNED or claim.name in seen:
            continue
        seen.add(claim.name)
        waiting.append((claim.name, Counts()))
    if (leader and leader != UNASSIGNED and leader not in ledger_owners
            and leader not in seen):
        waiting.insert(0, (leader, Counts()))
    return waiting + recorded


def machine_agent_rows(ledger: Path) -> list[tuple[str, NameClaim]]:
    """Every recent name claim on this machine, newest claim first."""
    return [(claim.name, claim) for claim in recent_claims()]


def owner_harnesses(tasks: list[Task]) -> dict[str, str]:
    """The harness each owner recorded, from their newest entry that names one.

    Entries written before the field existed simply have none, so an owner
    shows a harness only where the ledger actually records it.
    """
    found: dict[str, str] = {}
    for task in tasks:
        owner = owner_name(task)
        if owner not in found and task.harness:
            found[owner] = task.harness
    return found


def harness_label(owner: str, harnesses: dict[str, str], recent: dict[str, str]) -> str:
    """What to show beside a name: the recorded harness, and a recent claim.

    A recent claim can name a harness the ledger does not carry yet, for a
    session that has claimed a name but not written an entry. It marks a claim
    made minutes ago on this machine, which is not proof the agent is running,
    so it is labelled "recent" rather than "live".
    """
    recorded = harnesses.get(owner, "")
    if owner in recent:
        return (recorded or recent[owner] or "unknown") + " (recent)"
    return recorded


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
    return Snapshot(tasks, statuses, ledger_version(text), datetime.now(), text=text)


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


def format_utc_short(stamp: str) -> str:
    """Show a UTC mandate or accept-by time in local clock form."""
    try:
        moment = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
        return moment.astimezone().strftime("%H:%M")
    except ValueError:
        return stamp


def lead_summary(text: str) -> str | None:
    """One header line for the recorded mandate, or None when leadership is off."""
    lead = read_lead(text)
    if lead is None:
        return None
    state = lead.state()
    if state == "invalid":
        return f"LEAD  invalid mandate on line {lead.line}"
    if state == "expired":
        return f"LEAD  {lead.owner} expired {lead.expires}"
    if lead.epoch is None:
        return f"LEAD  {lead.owner} until {lead.expires}"
    remaining = max(0, int(lead.epoch - time.time()))
    hours, rem = divmod(remaining, 3600)
    minutes = rem // 60
    left = f"{hours}h {minutes}m left" if hours else f"{minutes}m left"
    return f"LEAD  {lead.owner} | {left} | expires {lead.expires}"


def active_leader(snapshot: Snapshot | None) -> str | None:
    """The owner holding an active mandate, or None when none is in force."""
    if snapshot is None or not snapshot.text:
        return None
    lead = read_lead(snapshot.text)
    return lead.owner if lead and lead.state() == "active" else None


def assignment_lines(text: str, task: Task, completed: set[str]) -> list[str]:
    """Provenance, reservation, and dependency markers for one entry."""
    assignment = read_assignment(text, task)
    if assignment is None:
        return []
    lines = [assignment_summary(assignment)]
    unmet = [need for need in assignment.needs if need not in completed]
    if unmet:
        lines.append(f"Blocked by: {', '.join(unmet)}")
    if assignment.paths:
        lines.append(f"Reserved paths: {', '.join(assignment.paths)}")
    return lines


def assignment_summary(assignment: Assignment) -> str:
    parts = [f"state={assignment.state}"]
    if assignment.by:
        parts.append(f"assigned by {assignment.by}")
    if assignment.accept_by:
        parts.append(f"accept by {format_utc_short(assignment.accept_by)}")
    return "Assignment: " + ", ".join(parts)


def task_assignment_marker(text: str, task: Task, completed: set[str]) -> str:
    """A compact marker for the task list when leadership metadata is present."""
    assignment = read_assignment(text, task)
    if assignment is None:
        return ""
    parts = [assignment.state]
    if assignment.by:
        parts.append(f"by {assignment.by}")
    if assignment.accept_by:
        parts.append(f"accept {format_utc_short(assignment.accept_by)}")
    unmet = [need for need in assignment.needs if need not in completed]
    marker = " ".join(parts)
    if unmet:
        marker += f" | needs {unmet[0]}"
        if len(unmet) > 1:
            marker += f"+{len(unmet) - 1}"
    return f" [{marker}]"


def summary_lines(snapshot: Snapshot | None) -> list[str]:
    counts = count_tasks(snapshot.tasks if snapshot else [])
    lines = [
        f"TASKS  {progress(counts.completed, counts.tracked)} completed"
        f"   {counts.in_progress} in progress / {counts.pending} pending",
        f"STEPS  {progress(counts.checked, counts.steps)} checked",
        f"Excluded from totals: {counts.invalid} invalid / {counts.legacy} legacy entries",
    ]
    if snapshot and snapshot.text:
        lead_line = lead_summary(snapshot.text)
        if lead_line:
            lines.insert(0, lead_line)
    return lines


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
             blocks: bool = True, session_name: str | None = None) -> str:
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
    # The row names the session it serves, claimed at preflight, and never other
    # owners: per-owner progress belongs to the viewer's agent list, and a status
    # line naming someone else reads as that agent's bar.
    trailer = f" {dim}{gap}{reset} {session_name}" if session_name else ""
    # Work recorded to this reader that nobody has started. The bar is the only
    # surface that redraws without a model turn, so an assignment made while this
    # session sat idle is otherwise invisible until someone types into it.
    waiting = len(assigned_unstarted(snapshot.tasks if snapshot else [], session_name))
    if waiting:
        trailer += f" {dim}{gap}{reset} {shade}{waiting} assigned to you{reset}"
    return (f"{shade}handoff{reset} {shade}{full * filled}{empty * (width - filled)}{reset} "
            f"{counts.completed}/{counts.tracked} tasks {dim}{gap}{reset} "
            f"{counts.checked}/{counts.steps} steps{trailer}")


def status_line_payload(payload: str) -> dict | None:
    try:
        data = json.loads(payload)
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def status_line_root(payload: str) -> Path | None:
    """Read workspace.current_dir from a host status-line JSON payload."""
    data = status_line_payload(payload)
    if data is None:
        return None
    workspace = data.get("workspace")
    location = (workspace or {}).get("current_dir") if isinstance(workspace, dict) else None
    location = location or data.get("cwd")
    return Path(location) if isinstance(location, str) and location else None


def status_line_session(payload: str) -> str | None:
    """Read the host's session id from a status-line JSON payload, if it sends one."""
    data = status_line_payload(payload)
    session = data.get("session_id") if data else None
    return session.strip() if isinstance(session, str) and session.strip() else None


def bar_session_seeds(payload: str | None = None, seed: str | None = None) -> list[str]:
    """Session identifiers for this status-line reader, in lookup order."""
    seeds: list[str] = []
    if seed and seed.strip():
        seeds.append(seed.strip())
    if payload:
        session = status_line_session(payload)
        if session:
            seeds.append(session)
    for variable in ("HANDOFF_SESSION", "CLAUDE_CODE_SESSION_ID", "TERM_SESSION_ID"):
        value = os.environ.get(variable)
        if value and value.strip():
            seeds.append(value.strip())
    return list(dict.fromkeys(seeds))


def bar_cache_session_key(payload: str | None = None, seed: str | None = None) -> str:
    """Cache suffix for one terminal session's bar row.

    handoff-bar keys its cache on ledger content and this suffix so two agents
    in the same repository do not serve each other's claimed name from cache.
    """
    seeds = bar_session_seeds(payload, seed)
    if not seeds:
        return "no-session"
    return hashlib.sha256("\0".join(seeds).encode()).hexdigest()[:16]


def bar_session_name(ledger: Path, payload: str | None = None,
                     seed: str | None = None) -> str | None:
    """The name this session already claimed for this ledger, or None before it does.

    The host's reported session id leads, matching the seed the agent's own
    preflight claim is keyed on; the environment fallbacks follow session_seed's
    order. No record means the session has not claimed a name yet, and the bar
    then names no one rather than guessing.
    """
    for candidate in bar_session_seeds(payload, seed):
        name = recall_name(candidate, ledger)
        if name:
            return name
    return None


def machine_agent_row(name: str, claim: NameClaim, ledger: Path, width: int) -> str:
    """One machine-wide claim row: name, harness, repository."""
    repo = repo_display_label(claim.ledger, ledger)
    harness = claim.harness or "unknown"
    name_width = max(12, width - 44)
    return (f"{fit(name, name_width, pad=True)}  {fit(harness, 16, pad=True)}  "
            f"{fit(repo, 20, pad=True)}  (recent)")


def owner_row(owner: str, counts: Counts, width: int, harness: str = "",
              leader: str | None = None) -> str:
    # The harness borrows from the name column rather than widening the row, so
    # narrow terminals keep every count visible.
    label = owner + (" [LEAD]" if leader and owner == leader else "")
    harness_width = 0 if not harness else min(20, max(8, width - 72))
    name_width = max(12, width - 52 - (harness_width + 2 if harness_width else 0))
    shown = f"{fit(harness, harness_width, pad=True)}  " if harness_width else ""
    return (f"{fit(label, name_width, pad=True)}  {shown}"
            f"{counts.completed:3}/{counts.tracked:<3}  "
            f"{counts.in_progress:3}  {counts.pending:3}  "
            f"{progress(counts.checked, counts.steps, 8)}"
            f"  !{counts.invalid} ?{counts.legacy}")


def plain_report(watcher: Watcher, *, agent_scope: str = "repo") -> str:
    """One readable snapshot for pipes and terminals without curses."""
    lines = ["HANDOFF | Recorded progress", str(watcher.path)]
    if watcher.error:
        lines.append(f"READ ERROR: {watcher.error}")
        if watcher.snapshot:
            lines.append("Showing the last readable snapshot; data is stale.")
    lines.extend(summary_lines(watcher.snapshot))
    if agent_scope == "machine":
        lines.extend(["", "AGENTS ON THIS MACHINE (newest claim first) | name, harness, repository",
                      "(recent) = claimed a name in the last 15 minutes; not proof of a running process"])
    else:
        lines.extend(["", "AGENTS IN THIS REPOSITORY (waiting first, then recorded owners newest first)"
                      " | harness, done/tasks, in progress, pending, checked steps",
                      "! = invalid; ? = legacy (excluded from totals); (recent) = claimed its "
                      "name here in the last 15 minutes with no ledger tasks yet"])
    if watcher.snapshot:
        harnesses = owner_harnesses(watcher.snapshot.tasks)
        live = (held_sessions_for_ledger(watcher.path) if agent_scope == "repo"
                else held_sessions())
        if agent_scope == "machine":
            width = 110
            for name, claim in machine_agent_rows(watcher.path):
                lines.append(machine_agent_row(name, claim, watcher.path, width))
        else:
            leader = active_leader(watcher.snapshot)
            for owner, counts in agent_rows(watcher.snapshot.tasks, watcher.path, leader=leader):
                harness = harness_label(owner, harnesses, live)
                # Avoid truncating ownership in redirected reports.
                width = max(110, sum(cell_width(c) for c in clean_text(owner))
                            + 69 + (len(harness) + 2 if harness else 0))
                lines.append(owner_row(owner, counts, width, harness, leader=leader))
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
    if target != UNASSIGNED and task.state != "completed":
        state_change = ("In progress was checked so the assignment shows under WIP; "
                        "steps were not changed.")
    else:
        state_change = "No state or step boxes were changed."
    note = (f"Reassigned {stamp}: moved from {owner_name(task)} to {target} in the "
            f"handoff viewer at the user's direction. {state_change} The entry keeps "
            "its place in ledger order.")
    if target != UNASSIGNED and task.state != "completed":
        note += (f" Execution request: {target} must finish its current task, then "
                 "audit and complete this task, including verification, without "
                 "waiting for another user prompt. If idle, start after the audit. "
                 "Preserve prior work; record any concrete blocker and next action.")
    return "\n".join(textwrap.wrap(clean_text(note), width=79))


class Dashboard:
    def __init__(self, watcher: Watcher, read_only: bool = False, seed: str | None = None):
        self.watcher = watcher
        # How this window identifies the session it belongs to. A viewer opened
        # in a new terminal inherits nothing, so the launcher passes the opener's
        # seed; without it the window belongs to no session and says so.
        self.seed = seed
        self.view = "agents"
        self.agent_scope = "repo"
        self.owner: str | None = None
        self.selected = 0
        self.offset = 0
        self.detail: Task | None = None
        self.detail_offset = 0
        self.detail_step: int | None = None
        self.focus_step = False
        self.detail_width = 0
        self.read_only = read_only
        self.cut: Task | None = None
        self.cut_step: int | None = None
        self.cut_version: str | None = None
        self.prompt: str | None = None
        self.prompt_kind: str | None = None
        self.spawn_agent: str | None = None
        self.message: str | None = None
        # The last completed move, kept until the next one: a transient message
        # cannot answer "did it land" when checking costs a keypress.
        self.moved: tuple[str, str] | None = None
        # Half of a typed "gg", waiting one keypress for its pair.
        self.pending_g = False
        self.channel = Channel(watcher.path.resolve().parent) if Channel else None
        self.channel_data: dict = {"sessions": [], "messages": [], "truncated": False}
        self.channel_error: str | None = (
            None if Channel else "channel module is not installed beside this viewer")
        self.channel_mode = "messages"
        self.channel_session: str | None = None
        self.channel_detail: dict | None = None

    def nudge_sender(self) -> str | None:
        """The channel session this viewer may speak as, or None.

        A nudge is a message, and a message needs a real sender: the viewer is a
        window, not an agent. It speaks as the session whose terminal it runs in,
        found from the name that session already claimed, and refuses rather than
        borrowing another agent's identity when it cannot find one.
        """
        if self.channel is None:
            return None
        name = bar_session_name(self.watcher.path, seed=self.seed)
        return self.channel.session_for_owner(name) if name else None

    def nudge_selected(self) -> None:
        """Ask the selected session to answer. It changes nothing about that peer."""
        if self.read_only:
            self.message = "Nudging is disabled in read-only mode."
            return
        if self.channel is None:
            self.message = f"No channel here: {self.channel_error}."
            return
        row = self.selected_session()
        if row is None:
            self.message = ("Open the Channel view and select a session to nudge it. "
                            "Press s for the session list.")
            return
        sender = self.nudge_sender()
        if sender is None:
            self.message = ("Nothing was sent: this viewer has no session of its own to send "
                            "as. Nudge from an agent session, or watch the entry move to In "
                            "progress instead.")
            return
        if sender == row["id"]:
            self.message = "That is this viewer's own session. Nothing was sent."
            return
        try:
            result = self.channel.nudge(sender, row["id"],
                                        via="handoff viewer, at the user's direction")
        except (OSError, ValueError, RuntimeError) as error:
            self.message = f"Nothing was sent: {error}"
            return
        name = row["owner"]
        if not result["sent"]:
            self.message = (f"{name} was already nudged from this session in the last "
                            f"{round(result['repeat_in_seconds'] / 60)} minute(s). Asking again "
                            "buries the first request; nothing was sent.")
            return
        self.message = (f"Nudged {name}. It is a message, not a verdict: silence still leaves "
                        "availability unknown and moves no work.")

    def selected_session(self) -> dict | None:
        """Expose a stable session identity for session actions such as nudging."""
        if self.view != "channel":
            return None
        if self.channel_mode == "sessions":
            rows = self.rows()
            return rows[self.selected][1] if rows else None
        return next((row for row in self.channel_data["sessions"]
                     if row["id"] == self.channel_session), None)

    def tasks(self) -> list[Task]:
        snapshot = self.watcher.snapshot
        return [task for task in snapshot.tasks
                if self.owner is None or owner_name(task) == self.owner] if snapshot else []

    def rows(self) -> list[tuple[str, Counts | Task | dict]]:
        snapshot = self.watcher.snapshot
        if self.view == "channel":
            rows = self.channel_data[self.channel_mode]
            if self.channel_mode == "messages" and self.channel_session:
                session = self.channel_session
                rows = [row for row in rows if row["sender"] == session
                        or row["recipient"] in (session, "*")]
            return [(row["id"], row) for row in rows]
        if self.view == "spawn":
            return [(agent, agent) for agent in available_agents()]
        if self.view == "agents":
            if snapshot is None:
                return []
            if self.agent_scope == "machine":
                return machine_agent_rows(self.watcher.path)
            return agent_rows(snapshot.tasks, self.watcher.path, leader=active_leader(snapshot))
        return [(task.heading, task) for task in self.tasks()]

    def refresh(self) -> None:
        rows = self.rows()
        key = rows[min(self.selected, len(rows) - 1)][0] if rows else None
        self.watcher.poll()
        if self.view == "channel":
            if self.channel is None:
                self.channel_data = {"sessions": [], "messages": [], "truncated": False}
            else:
                try:
                    self.channel_data = self.channel.history()
                    self.channel_error = None
                except (OSError, ValueError, sqlite3.Error) as error:
                    self.channel_error = clean_text(str(error))
            if self.channel_detail:
                self.channel_detail = next((row for row in self.channel_data["messages"]
                                            if row["id"] == self.channel_detail["id"]), None)
        rows = self.rows()
        self.selected = next((i for i, row in enumerate(rows) if row[0] == key),
                             min(self.selected, max(0, len(rows) - 1)))
        if self.detail:
            old_steps = self.detail.steps
            self.detail = next((task for task in self.tasks()
                                if task.heading == self.detail.heading), None)
            if self.detail is None or self.detail.steps != old_steps:
                self.detail_step = None
        if self.cut:
            tasks = self.watcher.snapshot.tasks if self.watcher.snapshot else []
            current = next((task for task in tasks if task.heading == self.cut.heading), None)
            if current is None:
                self.clear_cut()
                self.message = ("The held task is no longer in the ledger. "
                                "Nothing was moved.")
            elif self.cut_version and self.cut_version != self.watcher.snapshot.version:
                self.clear_cut()
                self.message = ("The ledger changed while this view held the task, so nothing "
                                "was moved. Check the new entries and cut again.")
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
            self.clear_cut()
            self.message = f"'{title}' is already recorded to {label}. Nothing was moved."
            return
        if not self.watcher.path.is_file():
            self.message = f"Nothing was moved: no ledger at {self.watcher.path}."
            return
        owner = None if label == UNASSIGNED else label
        landing = replace_owner(task.heading, owner)

        def build(text: str) -> str:
            nonlocal landing
            if self.cut_step is not None:
                text, landing = transfer_step(
                    text, task.line, task.heading, self.cut_step,
                    task.steps[self.cut_step], owner,
                )
                return text
            return reassign_task(text, task.line, task.heading, owner, move_note(task, label),
                                 mark_in_progress=owner is not None and task.state != "completed")

        try:
            result = swap_ledger(
                self.watcher.path, self.cut_version or snapshot.version, build,
            )
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            self.message = f"Nothing was moved: {error}"
            return
        if result["status"] == "applied":
            self.clear_cut()
            self.message = None
            self.show_landing(landing, label)
            return
        if result["status"] == "conflict":
            self.clear_cut()
            self.message = ("The ledger changed while this view held the task, so nothing "
                            "was moved. Reloaded; check the new entries and cut again.")
        else:
            self.message = "Nothing was moved: " + "; ".join(
                str(error) for error in (result.get("errors") or ["write refused"]))
            return
        self.refresh()

    def clear_cut(self) -> None:
        self.cut = None
        self.cut_step = None
        self.cut_version = None

    def held_title(self) -> str:
        if self.cut is None:
            return ""
        if self.cut_step is not None:
            return self.cut.steps[self.cut_step][1]
        return task_title(self.cut)

    def jump_to_end(self, bottom: bool) -> None:
        """Go to the first or last line of whatever is being read."""
        if self.detail or self.channel_detail:
            self.detail_offset = sys.maxsize if bottom else 0
            if self.detail:
                self.detail_step = None if bottom or not self.detail.steps else 0
                self.focus_step = not bottom
        elif bottom:
            self.selected = max(0, len(self.rows()) - 1)
        else:
            self.selected = self.offset = self.detail_offset = 0

    def handle_prompt(self, key: int, curses) -> bool:
        """Read one owner name or an optional spawn task from the user."""
        limit = 200 if self.prompt_kind == "spawn_task" else 60
        if key in (27, 3):
            if self.prompt_kind == "spawn_task":
                self.prompt = self.prompt_kind = self.spawn_agent = None
                self.message = "Spawn cancelled."
            else:
                self.prompt = None
                self.message = ("Naming cancelled. The task is still held; "
                                "press x to release it.")
        elif key in (10, 13, curses.KEY_ENTER):
            text, self.prompt = self.prompt.strip(), None
            if self.prompt_kind == "spawn_task":
                agent = self.spawn_agent
                self.prompt_kind = self.spawn_agent = None
                self.launch_selected_agent(task=text or None, agent=agent)
            else:
                problem = owner_label_error(text) if text else "no name was typed"
                if problem:
                    self.message = f"Nothing was moved: {problem}."
                else:
                    self.move_task(text)
        elif key in (curses.KEY_BACKSPACE, 127, 8):
            self.prompt = self.prompt[:-1]
        elif 32 <= key < 127 and len(self.prompt) < limit:
            self.prompt += chr(key)
        return True

    def reload_detail(self, heading: str) -> None:
        """Keep detail view open on one heading after the ledger changes."""
        snapshot = self.watcher.snapshot
        if snapshot is None:
            self.detail = None
            return
        self.detail = next((task for task in snapshot.tasks if task.heading == heading), None)
        if self.detail and self.detail.steps:
            limit = len(self.detail.steps) - 1
            self.detail_step = min(self.detail_step or 0, limit)
        else:
            self.detail_step = None

    def complete_step(self) -> None:
        """Mark the selected detail step complete at the user's direction."""
        task = self.detail
        snapshot = self.watcher.snapshot
        if task is None or self.detail_step is None:
            self.message = "Open task details and select a step with j/k first."
            return
        if snapshot is None or not self.watcher.path.is_file():
            self.message = f"Nothing was saved: no ledger at {self.watcher.path}."
            return
        expected = task.steps[self.detail_step]
        if expected[0]:
            self.message = "That step is already marked complete."
            return
        if not task.modern or task.errors:
            self.message = "Repair this task's structure before marking a step complete."
            return

        def build(text: str) -> str:
            return mark_step_complete(text, task.line, task.heading,
                                      self.detail_step, expected)

        try:
            result = swap_ledger(self.watcher.path, snapshot.version, build)
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            self.message = f"Nothing was saved: {error}"
            return
        if result["status"] == "applied":
            self.message = f"Marked step complete in '{fit(task_title(task), 40)}'."
            self.refresh()
            self.reload_detail(task.heading)
            return
        if result["status"] == "conflict":
            self.message = ("The ledger changed while this view was open, so nothing "
                            "was saved. Reloaded; select the step and try again.")
        else:
            self.message = "Nothing was saved: " + "; ".join(
                str(error) for error in (result.get("errors") or ["write refused"]))
        self.refresh()
        self.reload_detail(task.heading)

    def complete_task(self) -> None:
        """Mark every step and the task-level boxes complete at the user's direction."""
        task = self.detail or self.selected_task()
        snapshot = self.watcher.snapshot
        if task is None:
            self.message = "Select a task to mark it complete."
            return
        if snapshot is None or not self.watcher.path.is_file():
            self.message = f"Nothing was saved: no ledger at {self.watcher.path}."
            return
        if task.state == "completed" and not task.errors:
            self.message = "That task is already marked complete."
            return
        if not task.modern or task.errors:
            self.message = "Repair this task's structure before marking it complete."
            return

        def build(text: str) -> str:
            return mark_task_complete(text, task.line, task.heading)

        try:
            result = swap_ledger(self.watcher.path, snapshot.version, build)
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            self.message = f"Nothing was saved: {error}"
            return
        if result["status"] == "applied":
            self.message = f"Marked '{fit(task_title(task), 46)}' complete."
            self.refresh()
            if self.detail:
                self.reload_detail(task.heading)
            return
        if result["status"] == "conflict":
            self.message = ("The ledger changed while this view was open, so nothing "
                            "was saved. Reloaded; select the task and try again.")
        else:
            self.message = "Nothing was saved: " + "; ".join(
                str(error) for error in (result.get("errors") or ["write refused"]))
        self.refresh()
        if self.detail:
            self.reload_detail(task.heading)

    def handle_complete_key(self, key: int) -> bool:
        """Handle user override completion keys; return False when the key was not one."""
        if key not in (ord("d"), ord("D")):
            return False
        if self.read_only:
            self.message = "Completion is disabled in read-only mode."
            return True
        if key == ord("d"):
            if not self.detail:
                self.message = "Open task details to mark one step complete with d."
                return True
            self.complete_step()
            return True
        if self.view not in ("tasks",) and not self.detail:
            self.message = "Open a task to mark it complete with D."
            return True
        self.complete_task()
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
            step = self.detail_step if self.detail and key == ord("x") else None
            if task is None:
                self.message = "Open the Tasks view and select a task to cut it."
            elif self.detail and key == ord("x") and step is None:
                self.message = "Select a step with j/k to cut it, or X to cut the whole task."
            elif (self.cut is not None and self.cut.heading == task.heading
                  and self.cut_step == step):
                self.clear_cut()
                self.message = "Released. Nothing is held."
            else:
                self.cut = task
                self.cut_step = step
                self.cut_version = self.watcher.snapshot.version
                self.moved = None
                self.message = (f"Cut '{fit(self.held_title(), 46)}'. Press p on the receiving "
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

    def begin_spawn_task_prompt(self) -> None:
        """Ask for an optional task before opening the selected agent CLI."""
        rows = self.rows()
        if not rows:
            self.message = "No agent CLIs on PATH. Install one, then try again."
            return
        self.spawn_agent = rows[self.selected][0]
        self.prompt_kind = "spawn_task"
        self.prompt = ""

    def launch_selected_agent(self, task: str | None = None,
                              agent: str | None = None) -> None:
        """Open one agent CLI in a new tab under the handoff bar."""
        rows = self.rows()
        if agent is None:
            if not rows:
                self.message = "No agent CLIs on PATH. Install one, then try again."
                return
            agent = rows[self.selected][0]
        seed = secrets.token_hex(16)
        ledger = self.watcher.path
        name = seed_claim(seed, ledger, agent)
        message = ""
        if name and not self.read_only:
            snapshot = self.watcher.snapshot
            if snapshot is not None:
                result = apply_session_intake(
                    ledger, snapshot.version, name, harness_for_agent(agent), task=task)
                if result["status"] == "applied":
                    message = "Recorded session intake in the ledger."
                elif result["status"] == "skipped":
                    message = str(result.get("note", ""))
                elif result["status"] == "conflict":
                    message = ("Session intake was not recorded: the ledger changed "
                               "while the agent opened; reload and check.")
        code, open_message, returned_name = open_agent(
            ledger.resolve().parent, agent, seed=seed, ledger=ledger,
            task=task, name=name)
        name = returned_name or name
        if code != 0:
            message = open_message
        elif open_message:
            message = (open_message + (" " + message if message else "")).strip()
        self.view = "agents"
        self.selected = self.offset = 0
        self.message = message or None
        self.refresh()
        if code == 0 and name:
            rows = self.rows()
            self.selected = next((i for i, (row_name, _) in enumerate(rows)
                                  if row_name == name), 0)
            self.offset = 0

    def designate_leader(self) -> None:
        """Designate the selected agent as leader, or resign the current one."""
        if self.read_only:
            self.message = "Leadership changes are disabled in read-only mode."
            return
        rows = self.rows()
        if self.view != "agents" or not rows:
            self.message = "Open the Agents view and select an agent first."
            return
        if self.agent_scope == "machine":
            self.message = "Press m for this repository's agents before designating a leader."
            return
        owner = rows[self.selected][0]
        if owner == UNASSIGNED:
            self.message = "Nothing was written: unassigned cannot lead."
            return
        problem = owner_label_error(owner)
        if problem or ";" in owner:
            self.message = f"Nothing was written: {problem or 'owner name cannot contain a semicolon'}."
            return
        snapshot = self.watcher.snapshot
        if snapshot is None or not self.watcher.path.is_file():
            self.message = f"Nothing was written: no ledger at {self.watcher.path}."
            return
        lead = read_lead(snapshot.text)
        resigning = lead is not None and lead.owner == owner and lead.state() == "active"

        def build(text: str) -> str:
            if resigning:
                return build_resign(text, owner)
            return build_claim(text, owner, DEFAULT_VIEWER_LEAD_HOURS)

        try:
            result = swap_ledger(self.watcher.path, snapshot.version, build)
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            self.message = f"Nothing was written: {error}"
            return
        if result["status"] == "applied":
            if resigning:
                self.message = f"{owner} resigned the leadership mandate."
            else:
                self.message = (f"{owner} is leader for {DEFAULT_VIEWER_LEAD_HOURS} hours. "
                                "Press L on that agent again to resign.")
            self.refresh()
            return
        if result["status"] == "conflict":
            self.message = ("The ledger changed while this view was open, so nothing "
                            "was written. Reloaded; try again.")
        else:
            self.message = "Nothing was written: " + "; ".join(
                str(error) for error in (result.get("errors") or ["write refused"]))
        self.refresh()

    def handle_key(self, key: int, curses, page: int) -> bool:
        if self.prompt is not None:
            return self.handle_prompt(key, curses)
        pending_g = False
        if key != -1:
            self.message = None
            # An idle poll passes -1; only a real keypress ends a pending "gg".
            pending_g, self.pending_g = self.pending_g, False
        if self.view == "spawn" and key in (27, ord("b"), curses.KEY_BACKSPACE, 127):
            self.view = "agents"
            self.selected = self.offset = 0
            return True
        if self.view == "spawn" and key in (10, 13, curses.KEY_ENTER):
            self.begin_spawn_task_prompt()
            return True
        if self.view == "agents" and key == ord("m"):
            self.agent_scope = "machine" if self.agent_scope == "repo" else "repo"
            self.selected = self.offset = 0
            self.message = ("Showing every recent name claim on this machine."
                            if self.agent_scope == "machine" else
                            "Showing agents for this repository only.")
            return True
        if self.view == "agents" and key == ord("N"):
            if not available_agents():
                self.message = "No agent CLIs on PATH. Install one, then try again."
            else:
                self.view = "spawn"
                self.selected = self.offset = 0
            return True
        if self.view == "agents" and key in (ord("l"), ord("L")):
            self.designate_leader()
            return True
        if key in (ord("g"), ord("G")):
            # vim: G goes to the bottom, gg to the top; a lone g awaits its pair.
            if key == ord("G") or pending_g:
                self.jump_to_end(bottom=key == ord("G"))
            else:
                self.pending_g = True
            return True
        if self.handle_complete_key(key):
            return True
        if self.handle_move_key(key):
            return True
        if key in (ord("q"), ord("Q"), 3):
            return False
        if key in (27, ord("b"), curses.KEY_BACKSPACE, 127):
            if self.channel_detail:
                self.channel_detail = None
            elif self.view == "channel" and self.channel_session:
                self.channel_session = None
                self.channel_mode = "sessions"
                self.selected = self.offset = 0
            elif self.detail:
                self.detail = None
            elif self.owner is not None:
                previous = self.owner
                self.owner = None
                self.view = "agents"
                rows = self.rows()
                self.selected = next((i for i, row in enumerate(rows) if row[0] == previous), 0)
                self.offset = 0
            return True
        if self.view == "channel" and key in (ord("n"), ord("N")):
            self.nudge_selected()
            return True
        if self.view == "channel" and key == ord("s"):
            self.channel_mode = "messages" if self.channel_mode == "sessions" else "sessions"
            self.channel_session = None
            self.channel_detail = None
            self.selected = self.offset = 0
        elif key in (9, ord("a"), ord("t"), ord("c")):
            if key == 9:
                self.view = "tasks" if self.view == "agents" else "agents"
            else:
                self.view = {ord("a"): "agents", ord("t"): "tasks", ord("c"): "channel"}[key]
            self.owner = None
            self.detail = None
            self.channel_detail = None
            self.selected = self.offset = 0
            if self.view == "channel":
                self.refresh()
        elif key in (10, 13, curses.KEY_ENTER) and not (self.detail or self.channel_detail):
            rows = self.rows()
            if rows:
                if self.view == "spawn":
                    self.begin_spawn_task_prompt()
                elif self.view == "channel":
                    if self.channel_mode == "sessions":
                        self.channel_session = rows[self.selected][0]
                        self.channel_mode = "messages"
                        self.selected = self.offset = 0
                    else:
                        self.channel_detail = rows[self.selected][1]
                        self.detail_offset = 0
                elif self.view == "agents":
                    if self.agent_scope == "machine":
                        self.message = ("Machine view lists recent name claims only. "
                                        "Press m for this repository's agents, then Enter "
                                        "to browse tasks.")
                    else:
                        self.owner = rows[self.selected][0]
                        self.view = "tasks"
                        self.selected = self.offset = 0
                else:
                    self.detail = rows[self.selected][1]
                    self.detail_offset = 0
                    self.detail_step = 0 if self.detail.steps else None
                    self.focus_step = True
        else:
            movement = {curses.KEY_DOWN: 1, ord("j"): 1, curses.KEY_UP: -1,
                        ord("k"): -1, curses.KEY_NPAGE: page, curses.KEY_PPAGE: -page}
            if key in movement:
                if self.detail and key in (curses.KEY_DOWN, ord("j"), curses.KEY_UP, ord("k")):
                    count = len(self.detail.steps)
                    if count:
                        self.detail_step = (0 if movement[key] > 0 else count - 1) if self.detail_step is None else (
                            min(count - 1, max(0, self.detail_step + movement[key])))
                        self.focus_step = True
                elif self.detail or self.channel_detail:
                    self.detail_offset = max(0, self.detail_offset + movement[key])
                    self.detail_step = None
                    self.focus_step = False
                else:
                    self.selected = min(max(0, len(self.rows()) - 1),
                                        max(0, self.selected + movement[key]))
            elif key in (curses.KEY_HOME, curses.KEY_END):
                self.jump_to_end(bottom=key == curses.KEY_END)
        return True

    def channel_detail_lines(self, width: int) -> list[str]:
        row = self.channel_detail
        if row is None:
            return []
        owners = {session["id"]: session["owner"] for session in self.channel_data["sessions"]}
        acknowledged = ", ".join(owners.get(session, session) for session in row["acknowledged_by"])
        blocks = [f"{row['sender_owner']} -> {row['recipient_owner']}",
                  f"Sent: {datetime.fromtimestamp(row['created']):%Y-%m-%d %H:%M:%S} (local time)",
                  f"Kind: {row['kind']} | ID: {row['id']}",
                  f"Acknowledged by: {acknowledged or 'none'}",
                  f"Reply to: {row['reply_to'] or 'none'}", ""] + row["body"].splitlines()
        wrap_width = max(1, width // 2 if any(cell_width(c) == 2 for b in blocks for c in b) else width)
        return [line for block in blocks for line in
                (textwrap.wrap(clean_text(block), width=wrap_width) or [""])]

    def detail_lines(self, width: int) -> list[str]:
        return [line for line, _ in self.detail_rows(width)]

    def detail_rows(self, width: int) -> list[tuple[str, int | None]]:
        task = self.detail
        snapshot = self.watcher.snapshot
        if task is None or snapshot is None:
            return []
        index = snapshot.tasks.index(task)
        completed = completed_ids(snapshot.text)
        blocks = [(block, None) for block in [task.heading,
                  f"Owner: {owner_name(task)} | State: {task_state(task)}",
                  f"Steps: {progress(sum(done for done, _ in task.steps), len(task.steps))}", ""]]
        blocks.extend((line, None) for line in assignment_lines(snapshot.text, task, completed))
        if assignment_lines(snapshot.text, task, completed):
            blocks.append(("", None))
        for step_index, (done, step) in enumerate(task.steps):
            held = self.cut is not None and self.cut.heading == task.heading and self.cut_step == step_index
            mark = "*" if held else ">" if self.detail_step == step_index else " "
            blocks.append((f"{mark} [{'x' if done else ' '}] {step}", step_index))
        blocks.extend([(block, None) for block in ["", snapshot.statuses[index]]])
        blocks.extend((f"Invalid: {error}", None) for error in task.errors)
        # Conservative wrapping prevents wide Unicode from falling off the right edge.
        wrap_width = max(1, width // 2 if any(cell_width(c) == 2 for b, _ in blocks for c in b) else width)
        return [(line, step) for block, step in blocks for line in
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
        snapshot = self.watcher.snapshot
        summary = summary_lines(snapshot)
        for index, line in enumerate(summary, 2):
            write(index, " " + line)
        tab_line = 2 + len(summary)
        scope = f" | {self.agent_scope}" if self.view == "agents" else ""
        write(tab_line, f" Agents   Tasks   [Channel]  {self.channel_mode} | s: sessions/messages" if self.view == "channel" else
              f" [Agents{scope}]   Tasks   c: Channel   m: scope   N: new agent   Enter: owner's tasks"
              if self.view == "agents" and self.agent_scope == "repo" else
              f" [Agents{scope}]   Tasks   c: Channel   m: scope   N: new agent   Enter: repo agents"
              if self.view == "agents" else
              " [Agents]   Tasks   c: Channel   N: pick agent CLI   Enter: open in terminal" if self.view == "spawn" else
              f" Agents   [Tasks]    Owner: {self.owner or 'all'}", curses.A_BOLD)
        content_start = tab_line + 2
        available = max(1, height - content_start - 4)
        rows = self.rows()
        leader = active_leader(snapshot) if self.view == "agents" else None
        if self.detail or self.channel_detail:
            if self.detail and width != self.detail_width:
                self.focus_step = self.detail_step is not None
            self.detail_width = width
            detail_rows = ([(line, None) for line in self.channel_detail_lines(width - 3)]
                           if self.channel_detail else self.detail_rows(width - 3))
            lines = [line for line, _ in detail_rows]
            if self.detail and self.focus_step and self.detail_step is not None:
                start = next((i for i, (_, step) in enumerate(detail_rows) if step == self.detail_step), 0)
                if start < self.detail_offset:
                    self.detail_offset = start
                elif start >= self.detail_offset + available:
                    self.detail_offset = start - available + 1
                self.focus_step = False
            self.detail_offset = min(self.detail_offset, max(0, len(lines) - available))
            label = "MESSAGE" if self.channel_detail else "TASK"
            write(tab_line + 1, f" {label} DETAILS | lines {self.detail_offset + 1}-{min(len(lines), self.detail_offset + available)}"
                  f"/{len(lines)} | b: back", curses.A_DIM)
            for i, (line, step) in enumerate(detail_rows[self.detail_offset:self.detail_offset + available]):
                selected = self.detail is not None and step is not None and step == self.detail_step
                write(content_start + i, " " + line, curses.A_REVERSE if selected else 0)
        else:
            if self.view == "agents":
                if self.agent_scope == "machine":
                    write(tab_line + 1, " NAME                 HARNESS           REPOSITORY           NOTE",
                          curses.A_DIM)
                else:
                    harnesses = owner_harnesses(self.tasks())
                    recent = held_sessions_for_ledger(self.watcher.path)
                    shown = any(harness_label(owner, harnesses, recent) for owner, _ in rows)
                    heading = ("WAITING / RECORDED OWNER (newest first)"
                                 + ("  HARNESS" if shown else ""))
                    write(tab_line + 1, f" {fit(heading, max(12, width - 55), pad=True)}"
                          "  DONE/TASK  WIP WAIT  CHECKED STEPS  !bad ?old", curses.A_DIM)
            elif self.view == "spawn":
                write(tab_line + 1,
                      " AGENT CLI ON PATH | Enter: optional task, then open with handoff bar",
                      curses.A_DIM)
            elif self.view == "channel":
                session = self.selected_session()
                write(tab_line + 1, " SESSION / HARNESS | REPORTED STATE / AGE" if self.channel_mode == "sessions" else
                      f" TIME   SENDER -> RECIPIENT | ACK | BODY (newest; {session['owner'] if session else 'all'})", curses.A_DIM)
            else:
                write(tab_line + 1, " STATE          STEPS    TASK / OWNER (ledger order)", curses.A_DIM)
            self.offset = max(0, min(self.offset, self.selected))
            if self.selected >= self.offset + available:
                self.offset = self.selected - available + 1
            for i, (label, value) in enumerate(rows[self.offset:self.offset + available]):
                selected = self.offset + i == self.selected
                held = landed = False
                if self.view == "agents":
                    if self.agent_scope == "machine":
                        line = machine_agent_row(label, value, self.watcher.path, width - 3)
                    else:
                        line = owner_row(label, value, width - 3,
                                         harness_label(label, harnesses, recent), leader=leader)
                elif self.view == "spawn":
                    line = fit(label, width - 3)
                elif self.view == "channel":
                    if self.channel_mode == "sessions":
                        age = max(0, int(time.time() - value["reported"]))
                        line = f"{value['owner']} / {value['harness']} | {value['state']} / {age}s ago"
                    else:
                        stamp = datetime.fromtimestamp(value["created"]).strftime("%H:%M")
                        ack = (f"{len(value['acknowledged_by'])} ack" if value["recipient"] == "*" else
                               "acked" if value["acknowledged_by"] else "unacked")
                        line = (f"{stamp} {value['sender_owner']} -> {value['recipient_owner']} | {ack} | "
                                + " ".join(value["body"].split()))
                else:
                    held = self.cut is not None and self.cut.heading == value.heading
                    landed = self.moved is not None and self.moved[0] == value.heading
                    checked = sum(done for done, _ in value.steps)
                    marker = (task_assignment_marker(snapshot.text, value, completed_ids(snapshot.text))
                              if snapshot and snapshot.text else "")
                    line = (f"{task_state(value):13}  {checked:2}/{len(value.steps):<2}  "
                            f"{task_title(value)} / {owner_name(value)}{marker}")
                mark = "*" if held else "+" if landed else ">" if selected else " "
                write(content_start + i, mark + line, curses.A_REVERSE if selected else 0)
            if not rows:
                write(content_start, " No agent CLIs on PATH. Install one, then press N again."
                      if self.view == "spawn" else
                      " No recent name claims on this machine. Press m for this repository's agents."
                      if self.view == "agents" and self.agent_scope == "machine" else
                      " No channel messages or sessions to display. Waiting for channel changes."
                      if self.view == "channel" else " No entries to display. Waiting for ledger changes.")

        write(height - 4, self.banner(), curses.A_BOLD)
        snapshot = self.watcher.snapshot
        if self.view == "channel" and self.channel_error:
            write(height - 3, f" STALE CHANNEL | READ ERROR: {self.channel_error}", curses.A_BOLD)
        elif self.watcher.error:
            stamp = f"STALE (last read {snapshot.read_at:%H:%M:%S})" if snapshot else "WAITING"
            write(height - 3, f" {stamp} | READ ERROR: {self.watcher.error}", curses.A_BOLD)
        elif snapshot:
            write(height - 3, f" Read {snapshot.read_at:%H:%M:%S} | revision {snapshot.version[:12]}"
                  f" | {len(rows)} {self.view} | automatic refresh", curses.A_DIM)
        write(height - 2, (" Showing newest 200 messages only. " if self.channel_data["truncated"] else " ")
              + "Reading does not acknowledge. Reports and receipts do not prove live activity."
              if self.view == "channel" else
              " Checkbox counts only; owner labels do not prove authorship or live activity.", curses.A_DIM)
        # Only the keys that work here, so the row survives a narrow terminal:
        # cut and give act on tasks, and the channel view has no task to hold.
        keys = (" q quit | a/t/c views | j/k move | gg/G ends | Enter open"
                " | b back | r reload")
        if self.view == "spawn":
            keys = " j/k move | Enter task prompt | b back | q quit"
        elif not self.read_only:
            if self.view == "channel":
                keys += " | n nudge"
            elif self.view == "tasks":
                keys += " | N new agent | x cut | p give | D mark task"
            elif self.view == "agents":
                keys += " | m repo/machine | L leader | N new agent | x cut | p give"
            else:
                keys += " | N new agent | x cut | p give"
        if self.detail:
            keys = (" j/k select step | PgUp/PgDn scroll | b back | a agents | q quit" if self.read_only else
                    " d mark step | D mark task | x cut step | p give | j/k select | "
                    "a agents | X whole task | b back | q quit")
        write(height - 1, keys)
        screen.refresh()
        return available

    def banner(self) -> str:
        """One line for the pending move: the prompt, the last outcome, or what is held."""
        if self.prompt is not None:
            if self.prompt_kind == "spawn_task":
                agent = self.spawn_agent or "agent"
                return (f" Task for {agent} (optional): {self.prompt}_"
                        "   Enter: spawn | Esc: cancel")
            return f" Give to agent: {self.prompt}_   Enter: confirm | Esc: cancel"
        if self.message:
            return " " + self.message
        if self.cut is not None:
            return (f" HOLDING '{fit(self.held_title(), 46)}' from {owner_name(self.cut)}"
                    " | p: give to selected | P: type a name | x: release")
        if self.moved is not None:
            # The receiving agent comes first: it is the fact the user is checking,
            # and whatever a narrow terminal clips should be the title, not this.
            heading, label = self.moved
            return f" MOVED to {label} | + {heading_title(heading)} | b: all tasks"
        return ""


def run_live(watcher: Watcher, interval: float, read_only: bool = False,
             seed: str | None = None) -> int:
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
        dashboard = Dashboard(watcher, read_only=read_only, seed=seed)
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
    parser.add_argument("--agents", choices=("repo", "machine"), default="repo",
                        help="Agents section scope for --once: this repository or this machine")
    parser.add_argument("--read-only", action="store_true",
                        help="Disable the cut and paste keys in the live view, including the "
                             "one Codex mode opens, so it never writes")
    parser.add_argument("--bar", action="store_true",
                        help="Print one status-line row; reads host JSON on stdin for the directory")
    parser.add_argument("--no-color", action="store_true", help="Omit colour from --bar or --codex")
    parser.add_argument("--session-seed",
                        help="Identifier of the session this window belongs to; the launcher "
                             "passes the opener's, because a new terminal inherits none")
    parser.add_argument("--codex", nargs=argparse.REMAINDER,
                        help="Run Codex with a live bottom bar (tmux 3.2+); remaining arguments go to Codex")
    parser.add_argument("--with", dest="agent", nargs=argparse.REMAINDER, metavar="AGENT",
                        help="Run AGENT (claude, codex, kimi, grok, ...) with a live bottom bar "
                             "and the viewer key (tmux 3.2+); remaining arguments go to AGENT")
    parser.add_argument("--install-viewer-key", action="store_true",
                        help="Install a viewer key binding for this terminal or host")
    parser.add_argument("--open", action="store_true",
                        help="Open the live viewer in a new terminal window and exit")
    parser.add_argument("--emulator", default="auto",
                        help="Emulator for --install-viewer-key: auto, claude, kitty, wezterm, iterm2")
    args = parser.parse_args(argv)
    use_utf8_stdout()
    wrapped = args.codex if args.codex is not None else args.agent
    if args.install_viewer_key:
        from handoff_keys import install
        root = args.root.resolve() if args.file is None else args.file.resolve().parent
        print(install(root=root, emulator=args.emulator))
        return 0
    if args.open:
        if wrapped is not None or args.bar or args.once:
            parser.error("--open cannot be combined with --bar, --once, --codex, or --with")
        from handoff_keys import open_viewer
        root = args.root.resolve() if args.file is None else args.file.resolve().parent
        code, message = open_viewer(root, read_only=args.read_only)
        print(message)
        return code
    # Both flags take the rest of the line, so only the first one given is ever
    # set; whichever it is, everything after it belongs to the wrapped agent.
    if wrapped is not None and (args.bar or args.once):
        parser.error("--codex and --with cannot be combined with --bar or --once")
    if args.agent is not None and not [word for word in args.agent if word != "--"]:
        parser.error("--with needs an agent to run, e.g. --with claude")
    root = args.root
    payload: str | None = None
    if args.bar and not sys.stdin.isatty():
        # A host status line pipes session JSON in; it carries both the
        # directory to report on and the session id the bar names. Hosts send a
        # single JSON line, so with an explicit --file one line is enough and a
        # host holding stdin open cannot stall the row.
        payload = sys.stdin.readline() if args.file else sys.stdin.read()
        if not args.file:
            reported = status_line_root(payload)
            if reported is not None and args.root == Path("."):
                root = reported
    path = args.file.resolve() if args.file else find_repo_root(root) / "HANDOFF.md"
    watcher = Watcher(path)
    if wrapped is not None:
        from handoff_codex import DEFAULT_AGENT, run_agent
        arguments = wrapped[1:] if wrapped[:1] == ["--"] else wrapped
        # `--codex` names its agent in the flag; `--with` takes it as the first word.
        agent = DEFAULT_AGENT if args.codex is not None else arguments.pop(0)
        return run_agent(watcher, args.file.resolve().parent if args.file else root.resolve(),
                         arguments, args.interval, color=not args.no_color,
                         read_only=args.read_only, agent=agent,
                         session_seed=args.session_seed)
    if args.bar:
        # A status line must never break the host: no ledger means no row.
        if not path.is_file():
            return 0
        watcher.poll()
        line = bar_line(watcher.snapshot, color=not args.no_color,
                        blocks=stdout_encodes("\u2588\u2591\u00b7"),
                        session_name=bar_session_name(path, payload))
        if line:
            print(line)
        return 0
    if args.once or not (sys.stdin.isatty() and sys.stdout.isatty()):
        watcher.poll()
        print(plain_report(watcher, agent_scope=args.agents), end="")
        return 1 if watcher.error or (watcher.snapshot and any(task.errors for task in watcher.snapshot.tasks)) else 0
    return run_live(watcher, args.interval, read_only=args.read_only, seed=args.session_seed)


if __name__ == "__main__":
    sys.exit(main())
