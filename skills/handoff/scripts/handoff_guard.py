#!/usr/bin/env python3
"""Structure checks, template generation, and compare-and-swap writes for HANDOFF.md."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Iterable


HEADING_RE = re.compile(r"^##\s+(.+?)\s*$")
OWNER_RE = re.compile(r"\((?:owner|agent):\s*([^)]+)\)", re.IGNORECASE)
BOX_RE = re.compile(r"^\s*-\s+\[([ xX])\]\s+(.+?)\s*$")
FENCE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")

VERSION_PREFIX_MIN = 8
APPLY_EXIT = {"applied": 0, "dry-run": 0, "conflict": 3, "rejected": 4, "error": 1}


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


def checkbox_value(lines: Iterable[str], label: str) -> bool | None:
    wanted = label.casefold()
    for line in lines:
        match = BOX_RE.match(line)
        if match and match.group(2).strip().casefold() == wanted:
            return match.group(1).casefold() == "x"
    return None


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
            in_progress = checkbox_value(state_lines, "In progress")
            completed = checkbox_value(state_lines, "Completed")
            if in_progress is None:
                errors.append("missing In progress checkbox")
            if completed is None:
                errors.append("missing Completed checkbox")

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
                owner=owner_match.group(1).strip() if owner_match else None,
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


def atomic_write(path: Path, text: str) -> None:
    """Replace the ledger through a sibling temp file so no reader sees a partial write."""
    handle, temp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".handoff-", suffix=".tmp"
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    except BaseException:
        if temp.exists():
            temp.unlink()
        raise


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

    current = ledger.read_text(encoding="utf-8")
    current_version = ledger_version(current)
    if not version_matches(current_version, args.expect_version):
        return emit({
            **base,
            "status": "conflict",
            "expected_version": args.expect_version,
            "current_version": current_version,
            "errors": ["HANDOFF.md changed since this writer read it"],
            "note": (
                "Another writer changed the ledger. Re-read it, redo the progressive "
                "audit against the new entries, then apply again with the current "
                "version. Do not retry with the stale version."
            ),
        })

    payload = read_source(args.entry if args.entry else args.content)
    if args.entry:
        updated = insert_entry(current, payload)
    else:
        updated = payload if payload.endswith("\n") else payload + "\n"

    known = {(heading, error) for heading, error, _ in structure_findings(current)}
    introduced = [
        message
        for heading, error, message in structure_findings(updated)
        if (heading, error) not in known
    ]
    if introduced and not args.allow_structure_errors:
        return emit({
            **base,
            "status": "rejected",
            "current_version": current_version,
            "errors": introduced,
            "note": (
                "The write would introduce structural errors and was not applied. "
                "Fix the entry without falsifying task state, or pass "
                "--allow-structure-errors when the ledger is being repaired."
            ),
        })

    new_version = ledger_version(updated)
    if args.dry_run:
        return emit({
            **base,
            "status": "dry-run",
            "current_version": current_version,
            "new_version": new_version,
            "errors": introduced,
            "note": "Nothing was written.",
        })

    atomic_write(ledger, updated)
    return emit({
        **base,
        "status": "applied",
        "current_version": current_version,
        "new_version": new_version,
        "errors": introduced,
        "note": "Pass the new version to the next apply from this session.",
    })


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
