#!/usr/bin/env python3
"""Structure checks, template generation, and compare-and-swap writes for HANDOFF.md."""

from __future__ import annotations

import argparse
import errno
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Callable, Iterable


HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
OWNER_RE = re.compile(r"\((?P<label>owner|agent):\s*(?P<name>[^)]+)\)", re.IGNORECASE)
# An optional second field: which tool the owning session ran in. Separate from
# the owner label because a name must survive a round trip through the heading,
# and OWNER_RE forbids the parentheses a combined label would need.
HARNESS_RE = re.compile(r"\(harness:\s*(?P<harness>[^)]+)\)", re.IGNORECASE)
BOX_RE = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")

VERSION_PREFIX_MIN = 8
APPLY_EXIT = {"applied": 0, "dry-run": 0, "conflict": 3, "rejected": 4, "error": 1}
LOCK_TIMEOUT_SECONDS = 30.0
# A valid empty ledger. Purge replaces HANDOFF.md with this; it does not
# delete the file, because an existing ledger is what keeps the repository
# one that tracks work this way.
EMPTY_LEDGER = "# Handoff\n"

try:
    import fcntl
except ImportError:  # pragma: no cover - selected by platform
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - selected by platform
    msvcrt = None


@dataclass
class Task:
    heading: str
    owner: str | None
    line: int
    modern: bool
    in_progress: bool | None
    completed: bool | None
    steps: list[tuple[bool, str]]
    has_status: bool
    state: str
    errors: list[str]
    # Optional: the tool the owning session ran in, when its heading records one.
    harness: str | None = None


def outside_fence_lines(lines: list[str]) -> list[str]:
    """Mask fenced examples while preserving source line numbers."""
    visible: list[str] = []
    fence: str | None = None
    for line in lines:
        match = FENCE_RE.match(line)
        if fence is not None:
            visible.append("")
            if (match and match.group(1)[0] == fence[0]
                    and len(match.group(1)) >= len(fence)
                    and not match.group(2).strip()):
                fence = None
        elif match and not (match.group(1)[0] == "`" and "`" in match.group(2)):
            fence = match.group(1)
            visible.append("")
        else:
            visible.append(line)
    return visible


def outside_fence_headings(lines: list[str]) -> list[tuple[int, str]]:
    headings: list[tuple[int, str]] = []
    for index, line in enumerate(outside_fence_lines(lines)):
        match = HEADING_RE.match(line)
        if match:
            headings.append((index, match.group(1)))
    return headings


def checkbox_values(lines: Iterable[str], label: str) -> list[bool]:
    """Every checkbox carrying this exact label, in order.

    Returning all of them rather than the first lets a task with contradictory or
    duplicated state boxes - a plausible merge artifact - be reported as an error
    instead of silently resolving to whichever box happens to come first.
    """
    wanted = label.casefold()
    values: list[bool] = []
    for line in lines:
        match = BOX_RE.match(line)
        if match and match.group(2).strip().casefold() == wanted:
            values.append(match.group(1).casefold() == "x")
    return values


def parse_tasks(text: str) -> list[Task]:
    lines = outside_fence_lines(text.splitlines())
    headings = outside_fence_headings(lines)
    tasks: list[Task] = []

    for position, (start, heading) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        block = lines[start + 1 : end]
        state_index = next(
            (index for index, line in enumerate(block) if line.strip() == "State:"),
            None,
        )
        steps_index = next(
            (index for index, line in enumerate(block) if line.strip() == "Steps:"),
            None,
        )
        modern = state_index is not None or steps_index is not None
        in_progress: bool | None = None
        completed: bool | None = None
        steps: list[tuple[bool, str]] = []
        errors: list[str] = []

        if modern:
            if state_index is None:
                errors.append("missing State section")
                state_lines: list[str] = []
            else:
                state_end = steps_index if steps_index is not None else len(block)
                state_lines = block[state_index + 1 : state_end]
            for label, name in (("In progress", "in_progress"), ("Completed", "completed")):
                values = checkbox_values(state_lines, label)
                if not values:
                    errors.append(f"missing {label} checkbox")
                elif len(values) > 1:
                    errors.append(f"duplicate {label} checkbox")
                    if len(set(values)) > 1:
                        errors.append(f"contradictory {label} checkbox")
                else:
                    if name == "in_progress":
                        in_progress = values[0]
                    else:
                        completed = values[0]

            if steps_index is None:
                errors.append("missing Steps section")
            else:
                for line in block[steps_index + 1 :]:
                    if line.strip().startswith("Status:"):
                        break
                    match = BOX_RE.match(line)
                    if match:
                        label = match.group(2).strip()
                        if label.casefold() not in {"in progress", "completed"}:
                            steps.append((match.group(1).casefold() == "x", label))
                if not steps:
                    errors.append("no concrete steps")

            if completed and not in_progress:
                errors.append("Completed is checked while In progress is unchecked")
            if completed and any(not checked for checked, _ in steps):
                errors.append("completed task has unchecked steps")
            if in_progress is False and completed is False and any(checked for checked, _ in steps):
                errors.append("pending task has checked steps")

        has_status = any(line.strip().startswith("Status:") for line in block)
        if modern and not has_status:
            errors.append("missing Status line")

        if not modern:
            state = "legacy"
        elif in_progress is False and completed is False:
            state = "pending"
        elif in_progress is True and completed is False:
            state = "in_progress"
        elif in_progress is True and completed is True:
            state = "completed"
        else:
            state = "invalid"

        owner_match = OWNER_RE.search(heading)
        harness_match = HARNESS_RE.search(heading)
        tasks.append(
            Task(
                heading=heading,
                owner=owner_match.group("name").strip() if owner_match else None,
                line=start + 1,
                modern=modern,
                in_progress=in_progress,
                completed=completed,
                steps=steps,
                has_status=has_status,
                state=state,
                errors=errors,
                harness=harness_match.group("harness").strip() if harness_match else None,
            )
        )
    return tasks


def structure_findings(text: str) -> list[tuple[str, str, str]]:
    """Return (heading, error, formatted message) for every structural problem.

    The heading/error pair identifies a problem independently of line numbers,
    so an inserted entry does not make untouched errors look new.
    """
    return [
        (task.heading, error, f"line {task.line} ({task.heading}): {error}")
        for task in parse_tasks(text)
        for error in task.errors
    ]


def find_repo_root(start: Path) -> Path:
    resolved = start.resolve()
    if resolved.is_file():
        resolved = resolved.parent
    candidates = (resolved, *resolved.parents)
    for candidate in candidates:
        if (candidate / ".git").exists():
            return candidate
    for candidate in candidates:
        if (candidate / "HANDOFF.md").exists():
            return candidate
    return resolved


def git_status(repo: Path) -> list[str] | None:
    if not (repo / ".git").exists():
        return None
    result = subprocess.run(
        ["git", "status", "--short"],
        cwd=repo,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.splitlines()


def ledger_report(repo: Path) -> dict[str, object]:
    ledger = repo / "HANDOFF.md"
    instructions = [
        name
        for name in ("AGENTS.md", "CLAUDE.md")
        if (repo / name).exists()
    ]
    if not ledger.exists():
        return {
            "root": str(repo),
            "ledger": None,
            "version": None,
            "instructions": instructions,
            "git_status": git_status(repo),
            "tasks": [],
            "errors": ["HANDOFF.md not found"],
            "note": "Follow repository instructions before creating a ledger.",
        }

    text = ledger.read_text(encoding="utf-8")
    tasks = parse_tasks(text)
    errors = [message for _, _, message in structure_findings(text)]
    return {
        "root": str(repo),
        "ledger": str(ledger),
        "version": ledger_version(text),
        "instructions": instructions,
        "git_status": git_status(repo),
        "tasks": [asdict(task) for task in tasks],
        "errors": errors,
        "note": (
            "Task states are structural observations only. Audit later entries, "
            "commits, current source, and live ownership before deciding effective status."
        ),
    }


def print_human(report: dict[str, object]) -> None:
    print(f"Root: {report['root']}")
    print(f"Ledger: {report['ledger'] or 'missing'}")
    print(f"Version: {report['version'] or 'none'}")
    instruction_names = report["instructions"]
    print(f"Instructions: {', '.join(instruction_names) if instruction_names else 'none found'}")
    status_lines = report["git_status"]
    if status_lines is None:
        print("Git: unavailable")
    elif status_lines:
        print(f"Git: dirty ({len(status_lines)} paths)")
    else:
        print("Git: clean")

    tasks = report["tasks"]
    modern = [task for task in tasks if task["modern"]]
    legacy = [task for task in tasks if not task["modern"]]
    print(f"Tasks: {len(modern)} structured, {len(legacy)} legacy")
    for task in modern:
        owner = task["owner"] or "unassigned"
        print(f"- {task['state']}: {task['heading']} [owner: {owner}]")
    if legacy:
        print("Legacy entries require progressive review; their raw boxes were not classified.")

    errors = report["errors"]
    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
    print(f"Note: {report['note']}")


def make_template(task_date: str, title: str, owner: str, steps: list[str],
                  harness: str | None = None) -> str:
    step_lines = "\n".join(f"- [ ] {step}" for step in steps)
    # The harness field is optional and additive: an entry without one is still
    # a valid entry, and every ledger written before this existed stays valid.
    label = f" (harness: {harness.strip()})" if harness and harness.strip() else ""
    return (
        f"## {task_date} - {title} (owner: {owner}){label}\n\n"
        "State:\n\n"
        "- [ ] In progress\n"
        "- [ ] Completed\n\n"
        "Steps:\n\n"
        f"{step_lines}\n\n"
        "Status: Pending. No work has started.\n"
    )


def ledger_version(text: str) -> str:
    """Content hash identifying the ledger revision a writer read."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def version_matches(actual: str, expected: str) -> bool:
    """Accept the full hash or a prefix long enough to be unambiguous."""
    candidate = expected.strip().casefold()
    if len(candidate) < VERSION_PREFIX_MIN:
        return False
    return actual.casefold().startswith(candidate)


def insert_entry(text: str, entry: str) -> str:
    """Place a new task entry above existing tasks, keeping newest first."""
    lines = text.splitlines()
    headings = outside_fence_headings(lines)
    block = entry.strip("\n")
    if not headings:
        parts = [text.strip("\n"), block]
    else:
        first = headings[0][0]
        parts = [
            "\n".join(lines[:first]).strip("\n"),
            block,
            "\n".join(lines[first:]).strip("\n"),
        ]
    return "\n\n".join(part for part in parts if part) + "\n"


# One hundred figures from mythologies and folklore worldwide, grouped by
# tradition. A session claims one as its owner label so a ledger reads as named
# agents rather than a column of host session identifiers. Every name is a
# single ASCII word: an owner label travels through headings, tmux status
# formats, and clipped viewer columns, and a name that survives all three
# unchanged is worth more here than an exact transliteration.
MYTHIC_NAMES = (
    # Greek and Roman
    "Atalanta", "Chiron", "Daedalus", "Hyperion", "Nemesis", "Orpheus",
    "Prometheus", "Janus",
    # Norse
    "Bragi", "Fenrir", "Heimdall", "Idunn", "Mimir", "Ratatoskr", "Sleipnir",
    "Yggdrasil",
    # Celtic
    "Brigid", "Cernunnos", "Dagda", "Epona", "Lugh", "Rhiannon",
    # Finnish and Baltic
    "Ilmarinen", "Louhi", "Vainamoinen", "Perkunas",
    # Slavic
    "Perun", "Veles", "Zorya", "Rusalka", "Koschei",
    # Basque
    "Sugaar", "Basajaun",
    # Egyptian
    "Anubis", "Bastet", "Nephthys", "Sekhmet", "Sobek", "Thoth",
    # Mesopotamian
    "Anzu", "Enkidu", "Gilgamesh", "Inanna", "Ninurta", "Lamassu",
    # Persian and Armenian
    "Anahita", "Rostam", "Simurgh", "Zahhak", "Vahagn",
    # South Asian
    "Garuda", "Airavata", "Jatayu", "Vayu", "Kubera",
    # Chinese
    "Nuwa", "Pangu", "Houyi", "Taotie", "Qilin",
    # Japanese
    "Amaterasu", "Susanoo", "Tsukuyomi", "Inari", "Kitsune", "Tengu",
    # Korean
    "Dangun", "Haetae", "Ungnyeo",
    # Southeast Asian
    "Bathala", "Bakunawa", "Rangda", "Barong",
    # Pacific and Maori
    "Maui", "Pele", "Kanaloa", "Hina", "Tangaroa", "Rangi",
    # Arctic
    "Sedna", "Nanook",
    # Mesoamerican
    "Quetzalcoatl", "Tlaloc", "Xolotl", "Coatlicue", "Tezcatlipoca",
    "Kukulkan", "Ixchel",
    # Andean and Amazonian
    "Viracocha", "Inti", "Mamaquilla", "Curupira", "Iara",
    # African
    "Anansi", "Sundiata", "Nyaminyami", "Inkanyamba", "Sasabonsam",
    "Tokoloshe", "Simbi",
)

# A claim older than this is treated as a finished session, so a machine that
# has run hundreds of sessions does not run out of names.
NAME_CLAIM_SECONDS = 12 * 3600
# A separate, much shorter window for "did this session ask for its name just
# now". The 12-hour figure above reserves a name so two sessions cannot share
# one; it is deliberately generous and says nothing about whether a session is
# still working. A record is refreshed only when a session claims its name, so
# even this window reports a recent claim, never a running process.
RECENT_CLAIM_SECONDS = 15 * 60
# First-come-first-served naming cycles A through Z, then wraps to the next
# free A name. The slot counter lives beside per-session claim records.
LETTER_CYCLE = tuple(chr(ord("A") + index) for index in range(26))
FCFS_SLOT_FILE = "fcfs-slot"


def session_seed(explicit: str | None = None) -> str:
    """Identify this session, so repeated calls agree on one name.

    Prefers an identifier the host already assigns. `HANDOFF_SESSION` covers a
    host that exposes none, and a random seed keeps unidentified sessions apart
    rather than making them all claim the same first name.
    """
    for value in (explicit, os.environ.get("HANDOFF_SESSION"),
                  os.environ.get("CLAUDE_CODE_SESSION_ID"),
                  os.environ.get("TERM_SESSION_ID")):
        if value and value.strip():
            return value.strip()
    return os.urandom(16).hex()


def names_starting_with(letter: str) -> list[str]:
    """Roster names whose first letter matches, in alphabetical order."""
    upper = letter.upper()
    return sorted(name for name in MYTHIC_NAMES if name[0].upper() == upper)


def name_for_letter(letter: str, reserved: set[str]) -> str | None:
    """First free roster name for one initial, or None when that letter is exhausted."""
    for name in names_starting_with(letter):
        if name not in reserved:
            return name
    return None


def name_for_slot(slot: int, reserved: set[str]) -> str:
    """Pick the name this FCFS slot earns, cycling A through Z.

    When every name for one initial is taken, the next initial is tried so a
    busy machine still hands out a name rather than failing on empty letters
    such as W.
    """
    for offset in range(len(LETTER_CYCLE)):
        letter = LETTER_CYCLE[(slot + offset) % len(LETTER_CYCLE)]
        chosen = name_for_letter(letter, reserved)
        if chosen is not None:
            return chosen
    return free_name(sorted(MYTHIC_NAMES), reserved)


def allocate_fcfs_slot(directory: Path) -> int:
    """Hand out the next first-come-first-served naming slot."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return int(time.time() * 1000) % (len(LETTER_CYCLE) * 1000)
    slot_path = directory / FCFS_SLOT_FILE
    try:
        with ledger_lock(slot_path):
            try:
                slot = int(slot_path.read_text(encoding="utf-8").strip())
            except (OSError, ValueError):
                slot = 0
            slot_path.write_text(str(slot + 1) + "\n", encoding="utf-8")
            return slot
    except (RuntimeError, OSError):
        # Without a lock primitive, fall back to a best-effort slot.
        return int(time.time() * 1000) % (len(LETTER_CYCLE) * 1000)


def taken_names(text: str) -> set[str]:
    """Owner labels the ledger already carries, at any completion state.

    Completed entries count: reusing a retired owner's name would make the
    ledger's own history ambiguous about who did which work.
    """
    return {task.owner.strip() for task in parse_tasks(text) if task.owner}


def detect_harness() -> str | None:
    """Name the tool this session runs in, or None when nothing identifies it.

    Environment first, because a harness that identifies itself is the only
    evidence that does not guess. HANDOFF_HARNESS overrides everything, so a
    wrapper or an unrecognised tool can still record itself accurately.
    """
    override = os.environ.get("HANDOFF_HARNESS", "").strip()
    if override:
        return override[:80]
    if os.environ.get("CLAUDECODE") or os.environ.get("CLAUDE_CODE_SESSION_ID"):
        return "Claude Code"
    if os.environ.get("CODEX_HOME") or os.environ.get("CODEX_SANDBOX"):
        return "Codex"
    term_program = os.environ.get("TERM_PROGRAM", "").strip()
    if term_program.lower() == "vscode":
        # Cursor and VS Code both report vscode; the app name separates them.
        return "Cursor" if os.environ.get("CURSOR_TRACE_ID") else "VS Code"
    return None


def name_cache_dir() -> Path:
    location = os.environ.get("HANDOFF_NAME_CACHE")
    if location:
        return Path(location).expanduser()
    user = getattr(os, "getuid", lambda: 0)()
    return Path(tempfile.gettempdir()) / ("handoff-names-%s" % user)


def held_names(directory: Path, record: Path) -> set[str]:
    """Names live sessions have claimed but not yet written into a ledger."""
    names: set[str] = set()
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return names
    fresh = time.time() - NAME_CLAIM_SECONDS
    for entry in entries:
        if entry == record:
            continue
        try:
            if entry.stat().st_mtime < fresh:
                continue
            # A record is "name" or "name\nharness"; only the first line names
            # it, and an empty or truncated record names nothing.
            lines = entry.read_text(encoding="utf-8").splitlines()
            names.add(lines[0].strip() if lines else "")
        except OSError:
            continue
    return names - {""}


def held_sessions(directory: Path | None = None,
                  max_age: float = RECENT_CLAIM_SECONDS) -> dict[str, str]:
    """Harness by name for sessions that claimed a name within `max_age`.

    This reports a recent claim on this machine, not a running process: a record
    is touched only when a session asks for its name. Callers must not present
    it as proof that an agent is working.
    """
    directory = directory or name_cache_dir()
    live: dict[str, str] = {}
    fresh = time.time() - max_age
    try:
        entries = sorted(directory.iterdir())
    except OSError:
        return live
    for entry in entries:
        try:
            if entry.stat().st_mtime < fresh:
                continue
            lines = entry.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        if lines and lines[0].strip():
            live[lines[0].strip()] = lines[1].strip() if len(lines) > 1 else ""
    return live


def free_name(order: list[str], reserved: set[str]) -> str:
    """The first unused name, then numbered repeats once the roster runs out."""
    for name in order:
        if name not in reserved:
            return name
    suffix = 2
    while True:
        for name in order:
            candidate = "%s %d" % (name, suffix)
            if candidate not in reserved:
                return candidate
        suffix += 1


def bar_cache_dir() -> Path:
    location = os.environ.get("HANDOFF_BAR_CACHE")
    if location:
        return Path(location).expanduser()
    user = getattr(os, "getuid", lambda: 0)()
    return Path(tempfile.gettempdir()) / ("handoff-bar-%s" % user)


def bar_cache_key(ledger: Path) -> str:
    """Cache file stem for one ledger, matching handoff-bar's cksum key."""
    text = str(ledger.resolve()).encode("utf-8")
    try:
        result = subprocess.run(["cksum"], input=text, capture_output=True, check=False)
    except OSError:
        result = None
    if result is not None and result.returncode == 0:
        parts = result.stdout.decode("utf-8", errors="replace").split()
        if len(parts) >= 2:
            return parts[0] + parts[1]
    import zlib

    checksum = zlib.crc32(text) & 0xFFFFFFFF
    return "%s%s" % (checksum, len(text))


def invalidate_bar_cache(ledger: Path) -> None:
    """Drop a cached status row when a name claim changes what the bar shows."""
    try:
        (bar_cache_dir() / bar_cache_key(ledger.resolve())).unlink()
    except OSError:
        pass


def name_record(seed: str, ledger: Path) -> Path:
    """Where this session's claim for this ledger is remembered."""
    key = hashlib.sha256(("%s\0%s" % (seed, ledger)).encode("utf-8")).hexdigest()[:16]
    return name_cache_dir() / key


def recall_name(seed: str, ledger: Path) -> str | None:
    """The name this session already claimed for this ledger, without claiming.

    A status line asks who this session is far more often than the session asks
    for its name, so recalling only reads the record: it never creates one, and
    it never refreshes one, because a render is not the session asking.
    """
    try:
        lines = name_record(seed, ledger).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    name = lines[0].strip() if lines else ""
    return name or None


def claim_name(seed: str, ledger: Path, taken: set[str]) -> tuple[str, bool]:
    """Name this session for this ledger, and remember it for later calls.

    A named session keeps its name even once its own entry makes that name
    taken; without the record, an agent re-running preflight after writing an
    entry would be handed a second name and its own work would read as someone
    else's. The record is a convenience: if the cache cannot be read or
    written, naming still works and only stability across calls is lost.
    """
    record = name_record(seed, ledger)
    directory = record.parent
    harness = detect_harness()
    try:
        lines = record.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    remembered = lines[0].strip() if lines else ""
    if remembered:
        # Refresh the record so a live session keeps its claim and its harness.
        try:
            record.write_text(remembered + "\n" + (harness or "") + "\n", encoding="utf-8")
        except OSError:
            pass
        return remembered, True
    reserved = set(taken) | held_names(directory, record)
    chosen = name_for_slot(allocate_fcfs_slot(directory), reserved)
    try:
        directory.mkdir(parents=True, exist_ok=True)
        record.write_text(chosen + "\n" + (harness or "") + "\n", encoding="utf-8")
        invalidate_bar_cache(ledger)
    except OSError:
        pass
    return chosen, False


def owner_label_error(owner: str) -> str | None:
    """Reject an owner name a heading cannot carry back out unchanged."""
    if not owner.strip():
        return "owner name is empty"
    if any(character in owner for character in "()\n\r"):
        return "owner name cannot contain parentheses or line breaks"
    if len(owner) > 80:
        return "owner name is longer than 80 characters"
    return None


def strip_harness(heading: str) -> str:
    """Drop a heading's harness field.

    The field describes the session that held the task, so a reassignment must
    not carry it to the new owner: unknown is honest until that agent records
    its own.
    """
    match = HARNESS_RE.search(heading)
    if match is None:
        return heading
    remainder = heading[: match.start()] + heading[match.end():]
    return re.sub(r"\s{2,}", " ", remainder).strip()


def replace_owner(heading: str, owner: str | None) -> str:
    """Swap one heading's recorded owner, keeping its own `owner`/`agent` wording."""
    heading = strip_harness(heading)
    match = OWNER_RE.search(heading)
    if match is None:
        return f"{heading.rstrip()} (owner: {owner})" if owner else heading
    if owner is None:
        remainder = heading[: match.start()] + heading[match.end() :]
        return re.sub(r"\s{2,}", " ", remainder).strip()
    return f"{heading[: match.start()]}({match.group('label')}: {owner}){heading[match.end() :]}"


def reassign_task(text: str, line: int, heading: str, owner: str | None,
                  note: str | None = None) -> str:
    """Rewrite one task's owner label in place, optionally recording a status note.

    The entry keeps its position: ledger order records when work was raised, while
    the heading label records who holds it, so moving a task between agents must not
    reorder history. `line` and `heading` together identify the entry, and a mismatch
    raises rather than editing whichever entry now sits at that line.
    """
    if owner is not None:
        problem = owner_label_error(owner)
        if problem:
            raise ValueError(problem)
        owner = owner.strip()
    lines = text.splitlines()
    match = HEADING_RE.match(lines[line - 1]) if 0 < line <= len(lines) else None
    if match is None or match.group(1) != heading:
        raise ValueError(f"line {line} no longer holds the task '{heading}'")
    lines[line - 1] = lines[line - 1][: match.start(1)] + replace_owner(heading, owner)

    if note:
        masked = outside_fence_lines(lines)
        following = [index for index, _ in outside_fence_headings(lines) if index >= line]
        end = following[0] if following else len(lines)
        status = next((index for index in range(line, end)
                       if masked[index].strip().startswith("Status:")), None)
        if status is not None:
            # Append inside the status paragraph so the note travels with the status
            # text every reader and the viewer already show.
            while status + 1 < end and masked[status + 1].strip():
                status += 1
            lines.insert(status + 1, note)
    return "\n".join(lines) + "\n"


def atomic_write(path: Path, text: str) -> None:
    """Replace the ledger through a sibling temp file so no reader sees a partial write.

    mkstemp creates the temp file 0600 and os.replace carries that mode across, so the
    existing ledger's permissions are restored before the swap. Losing them would revoke
    collaborator access under a different OS account.
    """
    try:
        mode = os.stat(path).st_mode & 0o7777
    except FileNotFoundError:
        mode = None
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".handoff-", suffix=".tmp"
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        if mode is not None:
            os.chmod(temp, mode)
        os.replace(temp, path)
    except BaseException:
        if temp.exists():
            temp.unlink()
        raise


@contextmanager
def ledger_lock(ledger: Path, timeout: float = LOCK_TIMEOUT_SECONDS):
    """Serialize the whole read/check/replace sequence across cooperating writers.

    Comparing a hash is not by itself a compare-and-swap: without this lock two writers
    can both pass the version check against the same revision and the second replace
    silently discards the first writer's entry. The lock lives in a stable sidecar file
    rather than the ledger, because os.replace swaps the ledger's inode and a lock held
    on the old inode would not exclude a writer that opened the new one.
    """
    lock_path = ledger.with_name(ledger.name + ".lock")
    if fcntl is None and msvcrt is None:  # pragma: no cover - selected by platform
        raise RuntimeError(
            "No OS lock primitive (fcntl or msvcrt) is available, so apply cannot "
            "serialize writers. Refusing to write: proceeding unserialized would "
            "silently reintroduce the lost update this command exists to prevent."
        )

    def acquire(handle: int) -> None:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        else:  # pragma: no cover - selected by platform
            os.lseek(handle, 0, os.SEEK_SET)
            msvcrt.locking(handle, msvcrt.LK_NBLCK, 1)

    def release(handle: int) -> None:
        if fcntl is not None:
            fcntl.flock(handle, fcntl.LOCK_UN)
        else:  # pragma: no cover - selected by platform
            os.lseek(handle, 0, os.SEEK_SET)
            msvcrt.locking(handle, msvcrt.LK_UNLCK, 1)

    # Both primitives are released by the OS when the process dies, so a writer that
    # crashes cannot strand the lock. An exclusive-create lock file would: it is only
    # unlinked on a clean exit, so one kill -9 blocks every later writer forever, and
    # deleting a lock without proving it stale would break the guarantee outright.
    handle = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        deadline = time.monotonic() + timeout
        while True:
            try:
                acquire(handle)
                break
            except OSError as error:
                if error.errno not in (errno.EACCES, errno.EAGAIN, errno.EDEADLK):
                    raise
                if time.monotonic() >= deadline:
                    raise TimeoutError(f"Timed out waiting for {lock_path}")
                time.sleep(0.01)
        try:
            yield
        finally:
            release(handle)
    finally:
        os.close(handle)


def swap_ledger(ledger: Path, expect_version: str, build: Callable[[str], str], *,
                allow_structure_errors: bool = False, dry_run: bool = False,
                before_replace: Callable[[str], None] | None = None) -> dict[str, object]:
    """Apply `build(current_text)` to the ledger as one compare-and-swap.

    Every writer goes through here so the read, the version check, and the replace
    stay inside a single held lock; `build` runs on text whose hash already matched
    the caller's version, so a caller may locate an entry by the position it read.
    `before_replace(current)` runs after validation, only on the real write path,
    still holding the lock: a purge archive taken here is the bytes about to be
    replaced, not a stale snapshot from before the lock.
    """
    try:
        with ledger_lock(ledger):
            # Re-read under the lock. The version read outside it is not a
            # compare-and-swap; only this read/check/replace sequence is.
            current = ledger.read_text(encoding="utf-8")
            current_version = ledger_version(current)
            if not version_matches(current_version, expect_version):
                return {
                    "status": "conflict",
                    "expected_version": expect_version,
                    "current_version": current_version,
                    "errors": ["HANDOFF.md changed since this writer read it"],
                    "note": (
                        "Another writer changed the ledger. Re-read it, redo the progressive "
                        "audit against the new entries, then apply again with the current "
                        "version. Do not retry with the stale version."
                    ),
                }

            updated = build(current)
            if not updated.endswith("\n"):
                updated += "\n"

            known = {(heading, error) for heading, error, _ in structure_findings(current)}
            introduced = [
                message
                for heading, error, message in structure_findings(updated)
                if (heading, error) not in known
            ]
            if introduced and not allow_structure_errors:
                return {
                    "status": "rejected",
                    "current_version": current_version,
                    "errors": introduced,
                    "note": (
                        "The write would introduce structural errors and was not applied. "
                        "Fix the entry without falsifying task state, or pass "
                        "--allow-structure-errors when the ledger is being repaired."
                    ),
                }

            new_version = ledger_version(updated)
            if dry_run:
                return {
                    "status": "dry-run",
                    "current_version": current_version,
                    "new_version": new_version,
                    "errors": introduced,
                    "note": "Nothing was written.",
                }

            if before_replace is not None:
                try:
                    before_replace(current)
                except OSError as error:
                    return {
                        "status": "error",
                        "current_version": current_version,
                        "errors": [str(error)],
                        "note": "The pre-replace step failed; the ledger was not changed.",
                    }

            atomic_write(ledger, updated)
    except TimeoutError as error:
        return {
            "status": "error",
            "errors": [str(error)],
            "note": (
                "Another writer held the ledger lock past the timeout. Nothing was "
                "written; retry once that writer finishes."
            ),
        }

    return {
        "status": "applied",
        "current_version": current_version,
        "new_version": new_version,
        "errors": introduced,
        "note": "Pass the new version to the next apply from this session.",
    }


def read_source(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    return Path(source).read_text(encoding="utf-8")


def print_apply(result: dict[str, object]) -> None:
    print(f"Status: {result['status']}")
    print(f"Ledger: {result['ledger'] or 'missing'}")
    for label, key in (
        ("Expected version", "expected_version"),
        ("Current version", "current_version"),
        ("New version", "new_version"),
        ("Archive", "archive"),
    ):
        if result.get(key):
            print(f"{label}: {result[key]}")
    errors = result.get("errors") or []
    if errors:
        print("Errors:")
        for error in errors:
            print(f"- {error}")
    if result.get("note"):
        print(f"Note: {result['note']}")


def apply_command(args: argparse.Namespace) -> int:
    repo = find_repo_root(Path(args.root))
    ledger = repo / "HANDOFF.md"

    def emit(result: dict[str, object]) -> int:
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_apply(result)
        return APPLY_EXIT.get(str(result["status"]), 1)

    base: dict[str, object] = {"root": str(repo), "ledger": str(ledger)}

    if not ledger.exists():
        return emit({
            **base,
            "status": "error",
            "ledger": None,
            "errors": ["HANDOFF.md not found"],
            "note": "Create the ledger from references/ledger-contract.md before applying writes.",
        })

    # Read the payload before taking the lock: stdin or a named pipe can block
    # indefinitely, and holding the lock while it does would stall every peer.
    payload = read_source(args.entry if args.entry else args.content)

    def build(current: str) -> str:
        return insert_entry(current, payload) if args.entry else payload

    return emit({**base, **swap_ledger(
        ledger,
        args.expect_version,
        build,
        allow_structure_errors=args.allow_structure_errors,
        dry_run=args.dry_run,
    )})


def default_purge_archive(ledger: Path, version: str) -> Path:
    return ledger.with_name(f"{ledger.name}.{version[:12]}.bak")


def write_purge_archive(path: Path, text: str) -> None:
    """Write the replaced ledger bytes, refusing to clobber a different file.

    If a previous attempt archived the same bytes and then died before replacing
    the ledger, retrying is safe: matching content is treated as already archived.
    Differing content is a real collision and must not be overwritten.
    """
    payload = text if text.endswith("\n") else text + "\n"
    if path.exists():
        if path.read_text(encoding="utf-8") == payload:
            return
        raise FileExistsError(
            f"{path} already exists and differs from the ledger being purged"
        )
    atomic_write(path, payload)


def purge_command(args: argparse.Namespace) -> int:
    """Replace HANDOFF.md with an empty valid ledger through the one CAS.

    Failure case: an agent told to start fresh deletes the file (which drops the
    activation trigger) or writes empty content without a version check (which
    races peers and loses uncommitted history). Purge keeps the file, archives
    the replaced bytes under the lock, and refuses a stale version the same way
    apply does.
    """
    repo = find_repo_root(Path(args.root))
    ledger = repo / "HANDOFF.md"

    def emit(result: dict[str, object]) -> int:
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print_apply(result)
        return APPLY_EXIT.get(str(result["status"]), 1)

    base: dict[str, object] = {"root": str(repo), "ledger": str(ledger)}

    if not ledger.exists():
        return emit({
            **base,
            "status": "error",
            "ledger": None,
            "errors": ["HANDOFF.md not found"],
            "note": (
                "Purge does not create a ledger. Initialise one first, or stop: a "
                "repository with no HANDOFF.md is already a clean slate."
            ),
        })

    archived: list[str] = []

    def before_replace(current: str) -> None:
        if args.no_archive:
            return
        path = (
            Path(args.archive).expanduser()
            if args.archive
            else default_purge_archive(ledger, ledger_version(current))
        )
        write_purge_archive(path, current)
        archived.append(str(path))

    result = swap_ledger(
        ledger,
        args.expect_version,
        lambda _current: EMPTY_LEDGER,
        dry_run=args.dry_run,
        before_replace=before_replace,
    )
    if archived:
        result["archive"] = archived[0]
        result["note"] = (
            "Ledger emptied. The previous contents are in the archive; "
            "HANDOFF.md remains as an empty valid ledger. Pass the new version "
            "to the next apply from this session."
        )
    elif result.get("status") == "applied":
        result["note"] = (
            "Ledger emptied with no archive. HANDOFF.md remains as an empty "
            "valid ledger. Pass the new version to the next apply from this session."
        )
    return emit({**base, **result})


def read_command(args: argparse.Namespace) -> int:
    """Return the ledger text and its version from a single read.

    Reading the ledger and then separately asking doctor for a version is two reads: a
    peer write landing between them binds an audit of the old text to the new version,
    and a --content write built from that audit silently deletes the peer's entry. The
    audit and the write must both use the snapshot this command returns.
    """
    repo = find_repo_root(Path(args.root))
    ledger = repo / "HANDOFF.md"
    if not ledger.exists():
        result = {
            "root": str(repo),
            "ledger": None,
            "version": None,
            "text": None,
            "errors": ["HANDOFF.md not found"],
        }
        print(json.dumps(result, indent=2))
        return 1

    text = ledger.read_text(encoding="utf-8")
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    result = {
        "root": str(repo),
        "ledger": str(ledger),
        "version": ledger_version(text),
        "text": None if args.out else text,
        "saved_to": args.out,
        "errors": [message for _, _, message in structure_findings(text)],
        "note": (
            "Audit this exact text and pass this version to apply. Do not re-read the "
            "ledger separately for either one."
        ),
    }
    print(json.dumps(result, indent=2))
    return 0


def report_command(args: argparse.Namespace) -> int:
    repo = find_repo_root(Path(args.root))
    report = ledger_report(repo)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human(report)
    return 1 if report["errors"] else 0


def name_command(args: argparse.Namespace) -> int:
    """Print the name this session owns work under in this repository."""
    repo = find_repo_root(Path(args.root))
    ledger = repo / "HANDOFF.md"
    try:
        text = ledger.read_text(encoding="utf-8")
    except OSError:
        # A repository with no ledger yet still names the session that is about
        # to create one.
        text = ""
    name, remembered = claim_name(session_seed(args.seed), ledger, taken_names(text))
    if args.json:
        print(json.dumps({"name": name, "ledger": str(ledger),
                          "remembered": remembered, "roster": len(MYTHIC_NAMES),
                          "harness": detect_harness()}, indent=2))
    else:
        print(name)
    return 0


def template_command(args: argparse.Namespace) -> int:
    # --harness auto records what this session can detect; --harness "" opts out.
    harness = args.harness if args.harness is not None else ""
    if harness == "auto":
        harness = detect_harness() or ""
    problem = harness and owner_label_error(harness)
    if problem:
        print(f"handoff: harness label rejected ({problem})", file=sys.stderr)
        return 1
    print(make_template(args.date, args.title, args.owner, args.step, harness))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect HANDOFF.md structure, name this session, print a canonical task "
            "entry, apply a compare-and-swap ledger write, or purge the ledger."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("doctor", "validate"):
        command = subparsers.add_parser(name)
        command.add_argument("--root", default=".", help="Repository path or child path")
        command.add_argument("--json", action="store_true", help="Emit JSON")
        command.set_defaults(handler=report_command)

    name_parser = subparsers.add_parser("name")
    name_parser.add_argument("--root", default=".", help="Repository path or child path")
    name_parser.add_argument(
        "--seed",
        help="Identify the session explicitly instead of using the host's session id",
    )
    name_parser.add_argument("--json", action="store_true", help="Emit JSON")
    name_parser.set_defaults(handler=name_command)

    template = subparsers.add_parser("template")
    template.add_argument("--date", default=date.today().isoformat())
    template.add_argument("--title", required=True)
    template.add_argument("--owner", required=True)
    template.add_argument("--step", action="append", required=True)
    template.add_argument(
        "--harness",
        help="Record the tool this session runs in; 'auto' detects it",
    )
    template.set_defaults(handler=template_command)

    read_parser = subparsers.add_parser("read")
    read_parser.add_argument("--root", default=".", help="Repository path or child path")
    read_parser.add_argument(
        "--out", help="Write the ledger text to this file instead of returning it inline"
    )
    read_parser.set_defaults(handler=read_command)

    apply_parser = subparsers.add_parser("apply")
    apply_parser.add_argument("--root", default=".", help="Repository path or child path")
    apply_parser.add_argument(
        "--expect-version",
        required=True,
        help="Ledger version read before this edit; the write is refused if it moved",
    )
    source = apply_parser.add_mutually_exclusive_group(required=True)
    source.add_argument(
        "--entry",
        help="File holding one new task entry to insert at the newest position ('-' for stdin)",
    )
    source.add_argument(
        "--content",
        help="File holding the complete rewritten ledger ('-' for stdin)",
    )
    apply_parser.add_argument(
        "--allow-structure-errors",
        action="store_true",
        help="Apply even when the write introduces structural errors",
    )
    apply_parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    apply_parser.add_argument("--json", action="store_true", help="Emit JSON")
    apply_parser.set_defaults(handler=apply_command)

    purge_parser = subparsers.add_parser("purge")
    purge_parser.add_argument("--root", default=".", help="Repository path or child path")
    purge_parser.add_argument(
        "--expect-version",
        required=True,
        help="Ledger version read before this purge; the write is refused if it moved",
    )
    purge_parser.add_argument(
        "--confirm",
        required=True,
        choices=("purge",),
        help="Must be the word 'purge'; refuses to run without it",
    )
    archive = purge_parser.add_mutually_exclusive_group()
    archive.add_argument(
        "--archive",
        help="Write the replaced ledger bytes to this path instead of the default sidecar",
    )
    archive.add_argument(
        "--no-archive",
        action="store_true",
        help="Replace the ledger without writing a sidecar archive",
    )
    purge_parser.add_argument("--dry-run", action="store_true", help="Report without writing")
    purge_parser.add_argument("--json", action="store_true", help="Emit JSON")
    purge_parser.set_defaults(handler=purge_command)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
