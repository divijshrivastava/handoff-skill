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
BOX_RE = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")

VERSION_PREFIX_MIN = 8
APPLY_EXIT = {"applied": 0, "dry-run": 0, "conflict": 3, "rejected": 4, "error": 1}
LOCK_TIMEOUT_SECONDS = 30.0

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


def make_template(task_date: str, title: str, owner: str, steps: list[str]) -> str:
    step_lines = "\n".join(f"- [ ] {step}" for step in steps)
    return (
        f"## {task_date} - {title} (owner: {owner})\n\n"
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


def owner_label_error(owner: str) -> str | None:
    """Reject an owner name a heading cannot carry back out unchanged."""
    if not owner.strip():
        return "owner name is empty"
    if any(character in owner for character in "()\n\r"):
        return "owner name cannot contain parentheses or line breaks"
    if len(owner) > 80:
        return "owner name is longer than 80 characters"
    return None


def replace_owner(heading: str, owner: str | None) -> str:
    """Swap one heading's recorded owner, keeping its own `owner`/`agent` wording."""
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
                allow_structure_errors: bool = False, dry_run: bool = False) -> dict[str, object]:
    """Apply `build(current_text)` to the ledger as one compare-and-swap.

    Every writer goes through here so the read, the version check, and the replace
    stay inside a single held lock; `build` runs on text whose hash already matched
    the caller's version, so a caller may locate an entry by the position it read.
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


def template_command(args: argparse.Namespace) -> int:
    print(make_template(args.date, args.title, args.owner, args.step))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect HANDOFF.md structure, print a canonical task entry, or apply "
            "a compare-and-swap ledger write."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    for name in ("doctor", "validate"):
        command = subparsers.add_parser(name)
        command.add_argument("--root", default=".", help="Repository path or child path")
        command.add_argument("--json", action="store_true", help="Emit JSON")
        command.set_defaults(handler=report_command)

    template = subparsers.add_parser("template")
    template.add_argument("--date", default=date.today().isoformat())
    template.add_argument("--title", required=True)
    template.add_argument("--owner", required=True)
    template.add_argument("--step", action="append", required=True)
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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.handler(args)


if __name__ == "__main__":
    sys.exit(main())
